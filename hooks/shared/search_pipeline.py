"""Search Pipeline — Layer 3 of the Memory v2 Layered Redesign.

Orchestrates the full search flow: mode detection → primary retrieval →
cascade → enrichment → scoring → post-retrieval context → side effects.

All 7 search modes supported. Cascade behavior preserved.

Public API:
    from shared.search_pipeline import SearchPipeline
"""

import json
import os
import subprocess
import sys as _sys
import re

from shared.context_compressor import compress_results
from shared.scoring_engine import ScoringContext, score_result
from shared.search_cache import SearchCache


def _derive_query_tags(query, results):
    """Extract query_tags by matching query words against result tags.

    Reproduces the monolith's _rerank_composite heuristic: for each tag in the
    result set, if any query word (>3 chars) appears within that tag, include it.
    """
    if not query or not results:
        return ""
    query_lower = query.lower()
    words = [w for w in query_lower.split() if len(w) > 3]
    if not words:
        return ""
    tags = set()
    for r in results:
        for tag in (r.get("tags", "") or "").split(","):
            tag = tag.strip().lower()
            if tag and any(w in tag for w in words):
                tags.add(tag)
    return ",".join(sorted(tags)) if tags else ""


class SearchPipeline:
    """10-step search orchestrator.

    Coordinates: mode detection, primary retrieval, cascade (L2/L0/L3),
    enrichment, scoring, trimming, post-retrieval context, side effects,
    and counterfactual retrieval.
    """

    def __init__(
        self,
        collection,
        graph=None,
        ltp=None,
        adaptive=None,
        config=None,
        helpers=None,
        **kwargs,
    ):
        """
        Args:
            collection: SurrealCollection for knowledge
            graph: KnowledgeGraph instance (or None)
            ltp: LTPTracker instance (or None)
            adaptive: AdaptiveWeights instance (or None)
            config: dict of config toggles (from config.json)
            helpers: dict of server-level helper functions:
                format_summaries, keyword_search, merge_results,
                detect_query_mode, search_observations_internal,
                get_expanded_tags, tag_ids_to_summaries,
                generate_counterfactual_query, touch_memory_timestamp,
                validate_top_k, fix_outcomes,
                server_project, server_subproject, embed_text,
                search_by_tags_path (terminal history DB path)
        """
        self.collection = collection
        self.graph = graph
        self.ltp = ltp
        self.adaptive = adaptive
        self.config = config or {}
        self.h = helpers or {}
        self.cache = SearchCache(ttl_seconds=120, max_entries=200)

    def search(
        self,
        query,
        top_k=15,
        mode="",
        recency_weight=0.15,
        match_all=False,
        counterfactual=False,
        memory_type="",
        state_type="",
    ):
        """Full search pipeline — 10 steps.

        Returns:
            dict with results, total_memories, query, mode, and metadata counts
        """
        collection = self.collection
        h = self.h
        config = self.config

        # Cache check
        _cache_key = self.cache.make_key(
            query,
            top_k=top_k,
            mode=mode,
            memory_type=memory_type,
            state_type=state_type,
        )
        _cached = self.cache.get(_cache_key)
        if _cached is not None:
            return _cached

        recency_weight = max(0.0, min(1.0, recency_weight))
        _validate_top_k = h.get("validate_top_k")
        if _validate_top_k:
            top_k = _validate_top_k(top_k, default=15, min_val=1, max_val=500)
        else:
            top_k = max(1, min(500, int(top_k)))

        count = collection.count()
        if count == 0:
            return {
                "results": [],
                "total_memories": 0,
                "message": "Memory is empty. Start building knowledge with remember_this().",
            }

        # ── Step 1: Mode detection ──
        VALID_MODES = {
            "keyword",
            "semantic",
            "hybrid",
            "tags",
            "observations",
            "all",
            "transcript",
        }
        if mode and mode not in VALID_MODES:
            mode = ""
        if not mode:
            _routing = config.get("search_routing", "default")
            _detect = h.get("detect_query_mode")
            if _detect:
                mode = _detect(query, routing=_routing)
            else:
                mode = "semantic"

        # Query alias expansion
        QUERY_ALIASES = {"torus": "megaman", "megaman": "torus"}
        query_lower = query.lower()
        for alias_from, alias_to in QUERY_ALIASES.items():
            if alias_from in query_lower and alias_to not in query_lower:
                query = f"{query} {alias_to}"
                break

        # Handle observations-only mode (early return)
        if mode == "observations":
            _search_obs = h.get("search_observations_internal")
            if _search_obs:
                result = _search_obs(query, top_k, recency_weight)
            else:
                result = {"results": []}
            result["mode"] = "observations"
            result["query"] = query
            result["total_memories"] = count
            self._touch_timestamp()
            return result

        # Handle transcript mode (early return)
        if mode == "transcript":
            self._touch_timestamp()
            return self._search_transcript(query, count, config)

        # ── Step 1a: Query decomposition (split compound queries) ──
        if mode not in ("tags",):
            sub_queries = self._decompose_query(query)
            if sub_queries and len(sub_queries) > 1:
                return self._search_decomposed(
                    sub_queries,
                    top_k,
                    mode,
                    recency_weight,
                    match_all,
                    counterfactual,
                    memory_type,
                    state_type,
                    count,
                )

        # ── Step 1b: Query expansion for keyword/hybrid only ──
        if mode in ("keyword", "hybrid"):
            query = self._expand_query(query)

        # ── Step 1c: HyDE for semantic only ──
        _hyde_doc = None
        if mode in ("semantic", ""):
            _hyde_doc = self._hyde_generate(query)

        # ── Step 2: Primary retrieval ──
        actual_k = min(top_k * 2, count)
        format_summaries = h.get("format_summaries", lambda x: [])
        _where = {}
        if memory_type:
            _where["memory_type"] = memory_type
        if state_type:
            _where["state_type"] = state_type
        _where = _where or None

        # Embed once for all vector searches
        _embed_fn = h.get("embed_text")
        _query_vec = None
        if _embed_fn and mode in ("semantic", "hybrid", ""):
            try:
                _query_vec = _embed_fn(_hyde_doc if _hyde_doc else query)
            except Exception:
                pass

        if mode == "tags":
            tag_query = re.sub(r"^tags?:\s*", "", query, flags=re.IGNORECASE)
            tags_list = [t.strip() for t in tag_query.split(",") if t.strip()]
            tag_ids = collection.tag_search(
                tags_list, match_all=match_all, top_k=actual_k
            )
            _tag_to_summaries = h.get("tag_ids_to_summaries")
            formatted = _tag_to_summaries(tag_ids) if _tag_to_summaries else []
        elif mode == "keyword":
            _kw_search = h.get("keyword_search")
            formatted = _kw_search(query, top_k=actual_k) if _kw_search else []
        elif mode == "hybrid":
            _kw_search = h.get("keyword_search")
            _merge = h.get("merge_results")
            fts_results = _kw_search(query, top_k=actual_k) if _kw_search else []
            lance_results = collection.query(
                query_texts=[query] if not _query_vec else None,
                query_vector=_query_vec,
                n_results=actual_k,
                include=["metadatas", "distances"],
                where=_where,
            )
            lance_summaries = format_summaries(lance_results)
            formatted = (
                _merge(fts_results, lance_summaries, top_k=actual_k)
                if _merge
                else lance_summaries
            )
        else:
            results = collection.query(
                query_texts=[query] if not _query_vec else None,
                query_vector=_query_vec,
                n_results=actual_k,
                include=["metadatas", "distances"],
                where=_where,
            )
            formatted = format_summaries(results)

        # ── Step 3: Cascade (L2, L0, L3 after scoring) ──
        terminal_l2_count = self._cascade_terminal_l2(formatted, query, config)
        transcript_l0_count = self._cascade_transcript_l0(
            formatted, query, mode, config
        )

        # ── Step 4: Tag expansion + enrichment ──
        tag_expanded = False
        try:
            _get_expanded = h.get("get_expanded_tags")
            if _get_expanded:
                expanded_tags = _get_expanded(query)
                if expanded_tags:
                    seen_ids = {r.get("id") for r in formatted if r.get("id")}
                    tag_ids = collection.tag_search(
                        expanded_tags, match_all=False, top_k=actual_k
                    )
                    _tag_to_summaries = h.get("tag_ids_to_summaries")
                    tag_results = (
                        _tag_to_summaries(tag_ids) if _tag_to_summaries else []
                    )
                    if tag_results:
                        for tr in tag_results:
                            tid = tr.get("id", "")
                            if tid and tid not in seen_ids:
                                tr["tag_expanded"] = True
                                formatted.append(tr)
                                seen_ids.add(tid)
                        tag_expanded = True

                    # Terminal L2 tag search
                    self._cascade_terminal_l2_tags(
                        formatted, expanded_tags, seen_ids, config
                    )
        except Exception:
            pass

        # ── Step 5-6: Scoring (unified — one pass via scoring_engine) ──
        try:
            _ltp_factors = {}
            if self.ltp:
                for entry in formatted:
                    mem_id = entry.get("id", "")
                    if mem_id:
                        try:
                            _ltp_factors[mem_id] = self.ltp.get_decay_factor(mem_id)
                        except Exception:
                            pass

            _graph_scores = {}
            if self.graph:
                top_ids = {r.get("id") for r in formatted[:5] if r.get("id")}
                for entry in formatted:
                    mem_id = entry.get("id", "")
                    if mem_id:
                        try:
                            neighbors = self.graph._get_neighbors(mem_id)
                            if neighbors:
                                neighbor_ids = {n[0] for n in neighbors}
                                connected = len(neighbor_ids & top_ids - {mem_id})
                                if connected > 0:
                                    _graph_scores[mem_id] = connected * 0.03
                        except Exception:
                            pass

            _ltp_blend = 0.3
            if self.adaptive:
                _ltp_blend = self.adaptive.get_weights().get("ltp_blend", 0.3)

            _server_project = h.get("server_project", "") or ""
            _server_subproject = h.get("server_subproject", "") or ""
            _query_tags = _derive_query_tags(query, formatted)
            _scoring_ctx = ScoringContext(
                ltp_factors=_ltp_factors,
                graph_scores=_graph_scores,
                query_tags=_query_tags,
                project=_server_project,
                server_subproject=_server_subproject,
                query=query,
                ltp_blend=_ltp_blend,
            )

            for entry in formatted:
                base_sim = (
                    entry.get("relevance", 0)
                    or entry.get("score", 0)
                    or entry.get("fts_score", 0)
                    or 0
                )
                entry["relevance"] = score_result(entry, base_sim, _scoring_ctx)
                mem_id = entry.get("id", "")
                if mem_id in _ltp_factors:
                    entry["ltp_factor"] = _ltp_factors[mem_id]

            formatted.sort(key=lambda x: x.get("relevance", 0), reverse=True)
        except Exception:
            pass

        # ── Step 6b: Cross-encoder rerank (NVIDIA NIM) ──
        formatted = self._rerank_nim(query, formatted, top_k)

        # ── Step 7: Trim to top_k ──
        formatted = formatted[:top_k]

        # ── Step 8: Post-retrieval context ──
        _action_pattern_count = self._action_patterns(
            formatted, query, h, _query_vec=_query_vec
        )

        # "all" mode: merge observations
        if mode == "all":
            obs_budget = max(3, top_k // 3)
            knowledge_budget = top_k - obs_budget
            formatted = formatted[:knowledge_budget]
            _search_obs = h.get("search_observations_internal")
            if _search_obs:
                obs_results = _search_obs(
                    query, obs_budget, recency_weight=0, query_vec=_query_vec
                )
                obs_formatted = obs_results.get("results", [])
                seen_ids = {r.get("id") for r in formatted if r.get("id")}
                for obs in obs_formatted:
                    oid = obs.get("id", "")
                    if oid and oid not in seen_ids:
                        obs["source"] = "observations"
                        formatted.append(obs)
                        seen_ids.add(oid)

        # Auto-fallback to observations
        if len(formatted) == 0 and mode not in ("tags", "observations", "all"):
            _search_obs = h.get("search_observations_internal")
            if _search_obs:
                obs_results = _search_obs(
                    query, min(top_k, 10), recency_weight=0, query_vec=_query_vec
                )
                obs_formatted = obs_results.get("results", [])
                if obs_formatted:
                    for obs in obs_formatted:
                        obs["source"] = "observations"
                        obs["fallback"] = True
                    formatted = obs_formatted
                    mode = mode + "+fallback"

        self._touch_timestamp()
        formatted = formatted[:top_k]

        # Hybrid memory linking
        linked_memories_count = self._hybrid_linking(formatted, collection)

        # A-Mem network expansion: traverse linked_memory edges to surface connected knowledge
        amem_link_count = self._amem_expansion(formatted, collection)

        # Telegram L3 cascade (after trim, after linking)
        tg_fallback_count = self._cascade_telegram_l3(formatted, query, config)

        # Final trim
        formatted = formatted[:top_k]

        # Session context enrichment
        enrichment_count = self._enrich_session_context(formatted, config)

        # TG context enrichment
        tg_enrichment_count = self._enrich_tg_context(formatted, config)

        # ── Step 9: Side effects (LTP tracking, Hebbian co-retrieval) ──
        try:
            _mem_ids = [
                r.get("id") for r in formatted if r.get("id") and not r.get("source")
            ]
            if self.ltp and _mem_ids:
                for mid in _mem_ids[:10]:
                    self.ltp.record_access(mid)
            if self.graph and len(_mem_ids) >= 2:
                self.graph.strengthen_coretrieval(_mem_ids[:10])
        except Exception:
            pass

        # Graph-enriched search via spreading activation
        graph_enriched_count = self._graph_enrichment(
            formatted, query, mode, collection, h
        )

        # ── Step 10: Counterfactual retrieval ──
        counterfactual_count = self._counterfactual(
            formatted, query, mode, top_k, counterfactual, collection, config, h
        )

        # Build result
        result = {
            "results": formatted,
            "total_memories": count,
            "query": query,
            "mode": mode,
        }
        if linked_memories_count > 0:
            result["linked_memories_count"] = linked_memories_count
        if tg_fallback_count > 0:
            result["telegram_l3_count"] = tg_fallback_count
        if terminal_l2_count > 0:
            result["terminal_l2_count"] = terminal_l2_count
        if transcript_l0_count > 0:
            result["transcript_l0_count"] = transcript_l0_count
        if enrichment_count > 0:
            result["enrichment_count"] = enrichment_count
        if tg_enrichment_count > 0:
            result["tg_enrichment_count"] = tg_enrichment_count
        if _action_pattern_count > 0:
            result["action_pattern_count"] = _action_pattern_count
        if amem_link_count > 0:
            result["amem_link_count"] = amem_link_count
        if graph_enriched_count > 0:
            result["graph_enriched_count"] = graph_enriched_count
        if counterfactual_count > 0:
            result["counterfactual_count"] = counterfactual_count
        if tag_expanded:
            result["tag_expanded"] = True
        if formatted:
            result["compressed_results"] = compress_results(formatted)

        self.cache.put(_cache_key, result)
        return result

    # ── Internal helpers ──────────────────────────────────────────────────

    def _rerank_nim(self, query, candidates, top_k):
        """Rerank candidates using NVIDIA NIM cross-encoder. Fail-open."""
        config = self.config
        if not config.get("nim_rerank", False):
            return candidates
        if len(candidates) <= 3:
            return candidates

        rerank_k = min(len(candidates), max(top_k * 2, 30))
        passages = []
        for c in candidates[:rerank_k]:
            text = c.get("content") or c.get("preview") or ""
            if text:
                passages.append({"text": text[:2000]})
        if not passages:
            return candidates

        try:
            import requests

            nim_key = config.get("nim_api_key", "")
            if not nim_key:
                return candidates
            resp = requests.post(
                "https://ai.api.nvidia.com/v1/retrieval/nvidia/llama-3_2-nv-rerankqa-1b-v2/reranking",
                headers={
                    "Authorization": f"Bearer {nim_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "nvidia/llama-3.2-nv-rerankqa-1b-v2",
                    "query": {"text": query},
                    "passages": passages,
                    "truncate": "END",
                },
                timeout=10,
            )
            resp.raise_for_status()
            rankings = resp.json().get("rankings", [])
            reranked = []
            for r in sorted(rankings, key=lambda x: x.get("logit", 0), reverse=True):
                idx = r.get("index", 0)
                if idx < len(candidates):
                    candidates[idx]["rerank_score"] = r.get("logit", 0)
                    reranked.append(candidates[idx])
            remaining = [c for c in candidates[rerank_k:]]
            return reranked + remaining
        except Exception as e:
            print(
                f"[SearchPipeline] NIM rerank failed (fail-open): {e}", file=_sys.stderr
            )
            return candidates

    def _expand_query(self, query):
        """Expand query with LLM-generated related terms. Groq primary, NIM fallback. Fail-open."""
        config = self.config
        if not config.get("query_expansion", False):
            return query
        if len(query.split()) > 20:
            return query

        if not hasattr(self, "_qe_cache"):
            self._qe_cache = {}
        cached = self._qe_cache.get(query)
        if cached is not None:
            return cached

        prompt_msgs = [
            {
                "role": "system",
                "content": "Expand this search query with related terms to improve retrieval. "
                "Return ONLY a comma-separated list of 3-5 related terms. No explanation.",
            },
            {"role": "user", "content": query},
        ]

        expanded_terms = self._expand_via_groq(query, prompt_msgs)
        if not expanded_terms:
            expanded_terms = self._expand_via_nim_chat(query, prompt_msgs)

        if expanded_terms:
            terms = expanded_terms.replace('"', "").replace("'", "")
            result = f"{query} {terms}"
        else:
            result = query

        self._qe_cache[query] = result
        return result

    def _expand_via_groq(self, query, prompt_msgs):
        """Call Groq llama-3.1-8b-instant for query expansion. Returns expanded terms or None."""
        groq_key = self.config.get("groq_api_key", "") or os.environ.get(
            "GROQ_API_KEY", ""
        )
        if not groq_key:
            return None
        try:
            import requests

            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {groq_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "llama-3.1-8b-instant",
                    "messages": prompt_msgs,
                    "max_tokens": 60,
                    "temperature": 0,
                },
                timeout=5,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(
                f"[SearchPipeline] Groq expansion failed (fail-open): {e}",
                file=_sys.stderr,
            )
            return None

    def _expand_via_nim_chat(self, query, prompt_msgs):
        """Call NIM llama-3.1-8b-instruct for query expansion. Returns expanded terms or None."""
        nim_key = self.config.get("nim_api_key", "")
        if not nim_key:
            return None
        try:
            import requests

            resp = requests.post(
                "https://integrate.api.nvidia.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {nim_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "meta/llama-3.1-8b-instruct",
                    "messages": prompt_msgs,
                    "max_tokens": 60,
                    "temperature": 0,
                },
                timeout=8,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(
                f"[SearchPipeline] NIM expansion failed (fail-open): {e}",
                file=_sys.stderr,
            )
            return None

    def _decompose_query(self, query):
        """Split compound queries into sub-queries. Returns list or None. Fail-open."""
        config = self.config
        if not config.get("query_decomposition", False):
            return None
        if len(query.split()) < 6:
            return None
        if not any(
            w in query.lower() for w in ("and", "also", "plus", "as well", "both")
        ):
            return None

        if not hasattr(self, "_qd_cache"):
            self._qd_cache = {}
        cached = self._qd_cache.get(query)
        if cached is not None:
            return cached

        prompt_msgs = [
            {
                "role": "system",
                "content": "Decide if this search query contains multiple distinct questions. "
                "If yes, split into separate queries (one per line). "
                "If it's a single question, return ONLY the word SINGLE. "
                "No numbering, no explanation.",
            },
            {"role": "user", "content": query},
        ]

        response = self._expand_via_groq(query, prompt_msgs)
        if not response:
            response = self._expand_via_nim_chat(query, prompt_msgs)

        if not response or response.strip().upper() == "SINGLE":
            self._qd_cache[query] = None
            return None

        sub_queries = [q.strip() for q in response.strip().splitlines() if q.strip()]
        if len(sub_queries) < 2 or len(sub_queries) > 5:
            self._qd_cache[query] = None
            return None

        self._qd_cache[query] = sub_queries
        return sub_queries

    def _search_decomposed(
        self,
        sub_queries,
        top_k,
        mode,
        recency_weight,
        match_all,
        counterfactual,
        memory_type,
        state_type,
        total_count,
    ):
        """Run each sub-query through the full pipeline, merge and deduplicate."""
        per_query_k = max(5, top_k // len(sub_queries) + 2)
        all_results = []
        seen_ids = set()

        for sq in sub_queries:
            result = self.search(
                sq,
                top_k=per_query_k,
                mode=mode,
                recency_weight=recency_weight,
                match_all=match_all,
                counterfactual=counterfactual,
                memory_type=memory_type,
                state_type=state_type,
            )
            for r in result.get("results", []):
                rid = r.get("id", "")
                if rid and rid not in seen_ids:
                    r["decomposed_from"] = sq
                    all_results.append(r)
                    seen_ids.add(rid)

        all_results.sort(key=lambda x: x.get("relevance", 0), reverse=True)
        all_results = all_results[:top_k]

        return {
            "results": all_results,
            "total_memories": total_count,
            "query": " | ".join(sub_queries),
            "mode": mode,
            "decomposed": True,
            "sub_queries": sub_queries,
            "compressed_results": compress_results(all_results) if all_results else [],
        }

    def _hyde_generate(self, query):
        """Generate a hypothetical document for HyDE embedding. Fail-open."""
        config = self.config
        if not config.get("hyde", False):
            return None
        if len(query.split()) > 30:
            return None

        if not hasattr(self, "_hyde_cache"):
            self._hyde_cache = {}
        cached = self._hyde_cache.get(query)
        if cached is not None:
            return cached

        prompt_msgs = [
            {
                "role": "system",
                "content": "Write a brief factual statement that answers this query. "
                "One or two sentences, as if from a knowledge base entry. No preamble.",
            },
            {"role": "user", "content": query},
        ]

        doc = None
        groq_key = config.get("groq_api_key", "") or os.environ.get("GROQ_API_KEY", "")
        if groq_key:
            try:
                import requests

                resp = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {groq_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "llama-3.1-8b-instant",
                        "messages": prompt_msgs,
                        "max_tokens": 120,
                        "temperature": 0,
                    },
                    timeout=5,
                )
                resp.raise_for_status()
                doc = resp.json()["choices"][0]["message"]["content"].strip()
            except Exception as e:
                print(
                    f"[SearchPipeline] Groq HyDE failed (fail-open): {e}",
                    file=_sys.stderr,
                )

        if not doc:
            nim_key = config.get("nim_api_key", "")
            if nim_key:
                try:
                    import requests

                    resp = requests.post(
                        "https://integrate.api.nvidia.com/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {nim_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": "meta/llama-3.1-8b-instruct",
                            "messages": prompt_msgs,
                            "max_tokens": 120,
                            "temperature": 0,
                        },
                        timeout=8,
                    )
                    resp.raise_for_status()
                    doc = resp.json()["choices"][0]["message"]["content"].strip()
                except Exception as e:
                    print(
                        f"[SearchPipeline] NIM HyDE failed (fail-open): {e}",
                        file=_sys.stderr,
                    )

        self._hyde_cache[query] = doc
        return doc

    def _touch_timestamp(self):
        fn = self.h.get("touch_memory_timestamp")
        if fn:
            try:
                fn()
            except Exception:
                pass

    def _terminal_db_path(self):
        return os.path.join(
            os.path.expanduser("~"),
            ".claude",
            "integrations",
            "terminal-history",
            "terminal_history.db",
        )

    def _terminal_dir(self):
        return os.path.join(
            os.path.expanduser("~"),
            ".claude",
            "integrations",
            "terminal-history",
        )

    def _ensure_terminal_path(self):
        d = self._terminal_dir()
        if d not in _sys.path:
            _sys.path.insert(0, d)
        return d

    def _search_transcript(self, query, count, config):
        """Handle transcript mode search."""
        _transcript_enabled = config.get("transcript_l0", False)
        if not _transcript_enabled:
            return {
                "results": [],
                "mode": "transcript",
                "query": query,
                "total_memories": count,
                "source": "transcript_l0",
                "disabled": True,
                "hint": "Enable with transcript_l0: true in config.json",
            }
        transcript_results = []
        try:
            _term_db = self._terminal_db_path()
            if os.path.isfile(_term_db):
                self._ensure_terminal_path()
                from db import search_fts as _t_search_fts
                from db import get_raw_transcript_window as _get_raw_window

                hits = _t_search_fts(_term_db, query, limit=10)
                seen_sessions = {}
                for hit in hits:
                    sid = hit.get("session_id", "")
                    if sid and sid not in seen_sessions:
                        seen_sessions[sid] = hit.get("timestamp", "")
                for sid, ts in list(seen_sessions.items())[:3]:
                    window = _get_raw_window(
                        sid, around_timestamp=ts, window_minutes=10, max_records=30
                    )
                    transcript_results.append(window)
        except Exception:
            pass
        return {
            "results": transcript_results,
            "mode": "transcript",
            "query": query,
            "total_memories": count,
            "source": "transcript_l0",
        }

    def _cascade_terminal_l2(self, formatted, query, config):
        """Terminal History L2 cascade. Returns count of added results."""
        count = 0
        _terminal_l2_always = config.get("terminal_l2_always", True)
        _run = _terminal_l2_always or (
            formatted
            and all(
                r.get("relevance", 0) < 0.3 for r in formatted if not r.get("linked")
            )
        )
        if not _run:
            return 0
        try:
            _term_db = self._terminal_db_path()
            if os.path.isfile(_term_db):
                self._ensure_terminal_path()
                from db import search_fts as _search_fts

                for tr in _search_fts(_term_db, query, limit=5):
                    _bm25 = abs(float(tr.get("bm25", 0)))
                    _relevance = min(1.0, _bm25 / 20.0)
                    _entry = {
                        "id": f"term_{tr.get('session_id', '?')[:12]}",
                        "preview": (tr.get("text", "")[:120] + "...")
                        if len(tr.get("text", "")) > 120
                        else tr.get("text", ""),
                        "relevance": round(_relevance, 4),
                        "source": "terminal_l2",
                        "timestamp": tr.get("timestamp", ""),
                    }
                    if tr.get("tags"):
                        _entry["tags"] = tr["tags"]
                    if tr.get("linked_memory_ids"):
                        _entry["linked_memory_ids"] = tr["linked_memory_ids"]
                    formatted.append(_entry)
                    count += 1
        except Exception:
            pass
        return count

    def _cascade_transcript_l0(self, formatted, query, mode, config):
        """L0 Raw Transcript cascade. Returns count of added results."""
        count = 0
        _transcript_l0_enabled = config.get("transcript_l0", False)
        if not _transcript_l0_enabled or mode in ("tags", "observations"):
            return 0
        _l0_weak = not formatted or all(
            r.get("relevance", 0) < 0.3
            for r in formatted
            if not r.get("linked") and not r.get("tag_expanded")
        )
        if not _l0_weak:
            return 0
        try:
            _term_db = self._terminal_db_path()
            if os.path.isfile(_term_db):
                self._ensure_terminal_path()
                from db import search_fts as _l0_search_fts
                from db import get_raw_transcript_window as _l0_get_raw_window

                _l0_hits = _l0_search_fts(_term_db, query, limit=6)
                _l0_seen_sessions = {}
                for _l0_hit in _l0_hits:
                    _l0_sid = _l0_hit.get("session_id", "")
                    if _l0_sid and _l0_sid not in _l0_seen_sessions:
                        _l0_seen_sessions[_l0_sid] = _l0_hit.get("timestamp", "")
                for _l0_sid, _l0_ts in list(_l0_seen_sessions.items())[:2]:
                    _l0_window = _l0_get_raw_window(
                        _l0_sid,
                        around_timestamp=_l0_ts,
                        window_minutes=10,
                        max_records=20,
                    )
                    if _l0_window and _l0_window.get("records"):
                        _l0_preview = "; ".join(
                            r.get("summary", r.get("text", ""))[:80]
                            for r in _l0_window.get("records", [])[:3]
                        )
                        formatted.append(
                            {
                                "id": f"l0_{_l0_sid[:16]}",
                                "preview": _l0_preview[:200],
                                "relevance": 0.22,
                                "source": "transcript_l0",
                                "timestamp": _l0_ts,
                                "session_id": _l0_sid,
                                "record_count": len(_l0_window.get("records", [])),
                            }
                        )
                        count += 1
        except Exception:
            pass
        return count

    def _cascade_terminal_l2_tags(self, formatted, expanded_tags, seen_ids, config):
        """Terminal L2 tag search as part of tag expansion."""
        try:
            _term_db = self._terminal_db_path()
            if os.path.isfile(_term_db):
                self._ensure_terminal_path()
                from db import search_by_tags as _search_by_tags

                _tag_term_results = _search_by_tags(_term_db, expanded_tags, limit=3)
                for ttr in _tag_term_results:
                    _tid = f"term_tag_{ttr.get('session_id', '?')[:12]}"
                    if _tid not in seen_ids:
                        formatted.append(
                            {
                                "id": _tid,
                                "preview": (ttr.get("text", "")[:120] + "...")
                                if len(ttr.get("text", "")) > 120
                                else ttr.get("text", ""),
                                "relevance": 0.25,
                                "source": "terminal_l2",
                                "timestamp": ttr.get("timestamp", ""),
                                "tags": ttr.get("tags", ""),
                                "tag_expanded": True,
                            }
                        )
                        seen_ids.add(_tid)
        except Exception:
            pass

    def _cascade_telegram_l3(self, formatted, query, config):
        """Telegram L3 cascade. Returns count of added results."""
        count = 0
        _tg_l3_always = config.get("tg_l3_always", False)
        _run = _tg_l3_always or (
            formatted
            and all(
                r.get("relevance", 0) < 0.3 for r in formatted if not r.get("linked")
            )
        )
        if not _run:
            return 0
        try:
            _tg_search = os.path.join(
                os.path.expanduser("~"),
                ".claude",
                "integrations",
                "telegram-bot",
                "search.py",
            )
            if os.path.isfile(_tg_search):
                _tg_result = subprocess.run(
                    [_sys.executable, _tg_search, query, "--json", "--limit", "5"],
                    capture_output=True,
                    text=True,
                    timeout=8,
                    stdin=subprocess.DEVNULL,
                )
                if _tg_result.returncode == 0 and _tg_result.stdout.strip():
                    _tg_data = json.loads(_tg_result.stdout)
                    for tr in _tg_data.get("results", []):
                        _bm25 = abs(float(tr.get("bm25", 0)))
                        _relevance = min(1.0, _bm25 / 20.0) if _bm25 > 0 else 0.2
                        formatted.append(
                            {
                                "id": f"tg_{tr.get('msg_id', '?')}",
                                "preview": (tr.get("text", "")[:120] + "...")
                                if len(tr.get("text", "")) > 120
                                else tr.get("text", ""),
                                "relevance": round(_relevance, 4),
                                "source": "telegram_l3",
                                "timestamp": tr.get("date", ""),
                            }
                        )
                        count += 1
        except Exception:
            pass
        return count

    def _action_patterns(self, formatted, query, h, _query_vec=None):
        """Action pattern lookup from fix_outcomes. Returns count."""
        count = 0
        try:
            from shared.action_patterns import is_error_query as _is_error_q
            from shared.action_patterns import extract_pattern as _extract_ap
            from shared.action_patterns import format_pattern as _format_ap
            from shared.action_patterns import rank_patterns as _rank_ap

            fix_outcomes = h.get("fix_outcomes")
            if _is_error_q(query) and fix_outcomes is not None:
                _fo_count = fix_outcomes.count()
                if _fo_count > 0:
                    _fo_results = fix_outcomes.query(
                        query_texts=[query] if not _query_vec else None,
                        query_vector=_query_vec,
                        n_results=min(5, _fo_count),
                        include=["metadatas", "documents"],
                    )
                    if _fo_results and _fo_results.get("documents"):
                        _fo_docs = _fo_results["documents"][0]
                        _fo_metas = (
                            _fo_results["metadatas"][0]
                            if _fo_results.get("metadatas")
                            else []
                        )
                        _patterns = []
                        for _ap_i, _ap_doc in enumerate(_fo_docs):
                            _ap_meta = (
                                _fo_metas[_ap_i] if _ap_i < len(_fo_metas) else {}
                            )
                            if _ap_meta.get("outcome") in ("success", "failed"):
                                _patterns.append(_extract_ap(_ap_doc, _ap_meta))
                        _patterns = _rank_ap(_patterns)
                        for _ap in _patterns[:3]:
                            if _ap["confidence"] > 0.1:
                                formatted.insert(
                                    0,
                                    {
                                        "id": f"ap_{_ap['chain_id'][:12]}",
                                        "preview": _format_ap(_ap),
                                        "relevance": 0.95,
                                        "source": "action_pattern",
                                        "action_pattern": _ap,
                                        "timestamp": "",
                                    },
                                )
                                count += 1
        except (ImportError, ValueError, TypeError, KeyError, AttributeError):
            pass
        return count

    def _amem_expansion(self, formatted, collection):
        """Expand search results via A-Mem linked_memory edges. Returns count of added results."""
        count = 0
        if not self.graph:
            return 0
        try:
            seen_ids = {r.get("id") for r in formatted if r.get("id")}
            linked_candidates = {}  # id -> strength

            # For each top result, traverse linked_memory edges (max_depth=2)
            for r in formatted[:5]:
                mem_id = r.get("id", "")
                if not mem_id:
                    continue
                linked = self.graph.get_linked_memories(mem_id, max_depth=2)
                for link in linked:
                    lid = link["id"]
                    if lid not in seen_ids:
                        # Keep the strongest link if seen from multiple seeds
                        old_strength = linked_candidates.get(lid, 0.0)
                        if link["strength"] > old_strength:
                            linked_candidates[lid] = link["strength"]

            if not linked_candidates:
                return 0

            # Fetch the linked memory contents from the collection
            candidate_ids = list(linked_candidates.keys())[:10]  # cap at 10
            try:
                linked_results = collection.get(
                    ids=candidate_ids,
                    include=["metadatas", "documents"],
                )
            except Exception:
                return 0

            if linked_results and linked_results.get("ids"):
                l_ids = linked_results["ids"]
                l_metas = linked_results.get("metadatas") or [{}] * len(l_ids)
                l_docs = linked_results.get("documents") or [""] * len(l_ids)
                for i, lid in enumerate(l_ids):
                    if lid in seen_ids:
                        continue
                    meta = l_metas[i] if i < len(l_metas) else {}
                    doc = l_docs[i] if i < len(l_docs) else ""
                    preview = meta.get("preview", "") or (
                        doc[:120] + "..." if doc and len(doc) > 120 else doc
                    )
                    link_strength = linked_candidates.get(lid, 0.0)
                    formatted.append(
                        {
                            "id": lid,
                            "preview": preview,
                            "content": doc,
                            "tags": meta.get("tags", ""),
                            "timestamp": meta.get("timestamp", ""),
                            "relevance": link_strength * 0.6,  # discount linked results
                            "amem_linked": True,
                            "amem_strength": round(link_strength, 4),
                        }
                    )
                    seen_ids.add(lid)
                    count += 1
        except Exception:
            pass  # Fail-open: A-Mem expansion failure must not block search
        return count

    def _hybrid_linking(self, formatted, collection):
        """Co-retrieve linked memories via resolves:/resolved_by: tags. Returns count."""
        count = 0
        try:
            organic_ids = {r.get("id") for r in formatted if r.get("id")}
            linked_ids = set()
            for r in formatted:
                r_tags = r.get("tags", "") or ""
                for tag in r_tags.split(","):
                    tag = tag.strip()
                    if tag.startswith("resolves:"):
                        lid = tag.split(":", 1)[1].strip()
                        if lid and lid not in organic_ids:
                            linked_ids.add(lid)
                    elif tag.startswith("resolved_by:"):
                        lid = tag.split(":", 1)[1].strip()
                        if lid and lid not in organic_ids:
                            linked_ids.add(lid)
                r_linked = r.get("linked_memory_ids", "") or ""
                if r_linked and r.get("source") == "terminal_l2":
                    for mid in r_linked.split(","):
                        mid = mid.strip()
                        if mid and mid not in organic_ids:
                            linked_ids.add(mid)

            if linked_ids:
                linked_results = collection.get(
                    ids=list(linked_ids),
                    include=["metadatas", "documents"],
                )
                if linked_results and linked_results.get("ids"):
                    l_ids = linked_results["ids"]
                    l_metas = linked_results.get("metadatas") or [{}] * len(l_ids)
                    l_docs = linked_results.get("documents") or [""] * len(l_ids)
                    for i, lid in enumerate(l_ids):
                        meta = l_metas[i] if i < len(l_metas) else {}
                        doc = l_docs[i] if i < len(l_docs) else ""
                        preview = meta.get("preview", "") or (
                            doc[:120] + "..." if doc and len(doc) > 120 else doc
                        )
                        formatted.append(
                            {
                                "id": lid,
                                "preview": preview,
                                "tags": meta.get("tags", ""),
                                "timestamp": meta.get("timestamp", ""),
                                "linked": True,
                            }
                        )
                        count += 1
        except Exception:
            pass
        return count

    def _enrich_session_context(self, formatted, config):
        """Attach session context to vector search hits. Returns count."""
        count = 0
        if not config.get("context_enrichment", False):
            return 0
        try:
            _term_db = self._terminal_db_path()
            if os.path.isfile(_term_db):
                self._ensure_terminal_path()
                from db import get_context_by_timestamp as _get_ctx

                for r in list(formatted):
                    if r.get("linked") or r.get("source", "").startswith("terminal_"):
                        continue
                    ts = r.get("timestamp", "")
                    if not ts:
                        continue
                    ctx = _get_ctx(_term_db, ts, window_minutes=30, limit=3)
                    if ctx:
                        ctx_text = " | ".join(
                            f"[{c['role']}] {c['text'][:80]}" for c in ctx
                        )
                        r["session_context"] = ctx_text[:300]
                        count += 1
        except Exception:
            pass
        return count

    def _enrich_tg_context(self, formatted, config):
        """Attach Telegram context to search hits. Returns count."""
        count = 0
        if not config.get("tg_enrichment", False):
            return 0
        try:
            _tg_db = os.path.join(
                os.path.expanduser("~"),
                ".claude",
                "integrations",
                "telegram-bot",
                "msg_log.db",
            )
            if os.path.isfile(_tg_db):
                _tg_db_dir = os.path.join(
                    os.path.expanduser("~"),
                    ".claude",
                    "integrations",
                    "telegram-bot",
                )
                if _tg_db_dir not in _sys.path:
                    _sys.path.insert(0, _tg_db_dir)
                from db import get_context_by_timestamp as _get_tg_ctx

                for r in list(formatted):
                    if r.get("linked") or r.get("source", "").startswith("telegram_"):
                        continue
                    ts = r.get("timestamp", "")
                    if not ts:
                        continue
                    tg_ctx = _get_tg_ctx(_tg_db, ts, window_minutes=30, limit=3)
                    if tg_ctx:
                        tg_ctx_text = " | ".join(
                            f"[{c['sender']}] {c['text'][:80]}" for c in tg_ctx
                        )
                        r["tg_context"] = tg_ctx_text[:300]
                        count += 1
        except Exception:
            pass
        return count

    def _graph_enrichment(self, formatted, query, mode, collection, h):
        """Graph-enriched search via spreading activation. Returns count."""
        count = 0
        if not self.graph or mode in ("tags", "observations", "transcript"):
            return 0
        try:
            from shared.entity_extraction import extract_entities

            format_summaries = h.get("format_summaries", lambda x: [])
            _query_entities = [e["name"] for e in extract_entities(query)]
            if _query_entities:
                _activated = self.graph.spreading_activation(
                    _query_entities, max_hops=3
                )
                if _activated:
                    _seen_ids = {r.get("id") for r in formatted if r.get("id")}
                    _activated_names = [
                        a["name"] for a in _activated[:5] if a["activation"] > 0.1
                    ]
                    _kw_search = h.get("keyword_search")
                    for _aname in _activated_names:
                        try:
                            if _kw_search:
                                _graph_summaries = _kw_search(_aname, top_k=3)
                            else:
                                _graph_results = collection.query(
                                    query_texts=[_aname],
                                    n_results=3,
                                    include=["metadatas", "distances"],
                                )
                                _graph_summaries = format_summaries(_graph_results)
                            for gs in _graph_summaries:
                                gid = gs.get("id", "")
                                if gid and gid not in _seen_ids:
                                    gs["graph_enriched"] = True
                                    _graph_disc = 0.8
                                    if self.adaptive:
                                        _graph_disc = self.adaptive.get_weights().get(
                                            "graph_discount", 0.8
                                        )
                                    gs["relevance"] = (
                                        gs.get("relevance", 0) * _graph_disc
                                    )
                                    formatted.append(gs)
                                    _seen_ids.add(gid)
                                    count += 1
                        except Exception:
                            continue
        except Exception:
            pass
        return count

    def _counterfactual(
        self, formatted, query, mode, top_k, counterfactual_param, collection, config, h
    ):
        """Counterfactual retrieval pass. Returns count."""
        count = 0
        try:
            _cf_enabled = config.get("counterfactual_retrieval", False)
            _cf_mode = config.get("counterfactual_mode", "always")
            _cf_model = config.get("counterfactual_model", "haiku")
            _cf_threshold = config.get("counterfactual_threshold", 0.4)
            _should_cf = False

            if _cf_enabled:
                if _cf_mode == "always":
                    _should_cf = True
                elif _cf_mode == "threshold" and formatted:
                    _best_rel = max(
                        (r.get("relevance", 0) for r in formatted), default=0
                    )
                    if _best_rel < _cf_threshold:
                        _should_cf = True

            if counterfactual_param and _cf_enabled:
                _should_cf = True

            if mode in ("tags", "observations", "transcript"):
                _should_cf = False

            if _should_cf and formatted:
                _gen_cf = h.get("generate_counterfactual_query")
                format_summaries = h.get("format_summaries", lambda x: [])
                if _gen_cf:
                    _cf_query = _gen_cf(query, formatted, model_key=_cf_model)
                    if _cf_query:
                        _seen_ids = {r.get("id") for r in formatted if r.get("id")}
                        _cf_results = collection.query(
                            query_texts=[_cf_query],
                            n_results=min(top_k, 5),
                            include=["metadatas", "distances"],
                        )
                        _cf_summaries = format_summaries(_cf_results)
                        _cf_disc = config.get("counterfactual_discount", 0.8)
                        for cs in _cf_summaries:
                            cid = cs.get("id", "")
                            if cid and cid not in _seen_ids:
                                cs["counterfactual"] = True
                                cs["cf_query"] = _cf_query
                                cs["relevance"] = cs.get("relevance", 0) * _cf_disc
                                formatted.append(cs)
                                _seen_ids.add(cid)
                                count += 1
        except Exception:
            pass
        return count
