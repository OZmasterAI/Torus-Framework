"""Write Pipeline — Layer 3 of the Memory v2 Layered Redesign.

Orchestrates the full write flow: validate → normalize → A-Mem enrich →
quality score → dedup check → classify tier → store → side effects.

Performance (session 506): embed-once cache, entity cache, background
post-store work. Cuts remember_this from ~3min to seconds.

Public API:
    from shared.write_pipeline import WritePipeline
"""

import logging
import os
import re
import threading
import time
from datetime import datetime

_log = logging.getLogger(__name__)


class WritePipeline:
    """7-step write orchestrator (with A-Mem enrichment sub-step).

    Coordinates: validation, normalization, A-Mem enrichment, quality scoring,
    tier classification, storage, and side effects.
    """

    def __init__(
        self, collection, tag_index=None, graph=None, config=None, helpers=None
    ):
        """
        Args:
            collection: SurrealCollection for knowledge
            tag_index: Unused (kept for backward compat)
            graph: KnowledgeGraph instance (or None)
            config: dict of config toggles
            helpers: dict of server-level helper functions:
                normalize_tags, inject_project_tag, build_project_prefix,
                check_dedup, classify_tier, extract_citations,
                bridge_to_fix_outcomes, touch_memory_timestamp,
                generate_id, embed_text, cluster_store,
                fix_outcomes, noise_regexes, min_content_length,
                summary_length, server_project, server_subproject
        """
        self.collection = collection
        self.tag_index = tag_index
        self.graph = graph
        self.config = config or {}
        self.h = helpers or {}
        self._cached_session_id = None
        self._bg_semaphore = threading.Semaphore(1)  # queue bg threads, 1 at a time

    def write(
        self,
        content,
        context="",
        tags="",
        force=False,
        source_session_id="",
        source_observation_ids="",
    ):
        """Full write pipeline — 7 steps.

        Returns:
            dict with result status, id, total_memories, etc.
        """
        collection = self.collection
        h = self.h

        # Auto-detect source session ID (cached after first call)
        if not source_session_id:
            if self._cached_session_id is None:
                self._cached_session_id = self._detect_session_id()
            source_session_id = self._cached_session_id

        # ── Step 1: Validate ──
        min_content_length = h.get("min_content_length", 20)
        if len(content.strip()) < min_content_length:
            return {
                "result": "Rejected: content too short (minimum 20 characters)",
                "rejected": True,
                "total_memories": collection.count(),
            }

        max_content_length = 800
        if not force and len(content.strip()) > max_content_length:
            return {
                "result": f"Rejected: content too long ({len(content.strip())} chars, max {max_content_length}). Distill to key facts only.",
                "rejected": True,
                "total_memories": collection.count(),
            }

        # Cap metadata strings
        if len(context) > 500:
            context = context[:497] + "..."
        if len(tags) > 500:
            tags = tags[:497] + "..."

        # ── Step 2: Normalize ──
        _normalize = h.get("normalize_tags")
        if _normalize:
            tags = _normalize(tags)
        _inject_project = h.get("inject_project_tag")
        if _inject_project:
            tags = _inject_project(tags)
        _build_prefix = h.get("build_project_prefix")
        if _build_prefix:
            _prefix = _build_prefix()
            if _prefix and not content.startswith("["):
                content = _prefix + content

        # Noise rejection (skip if force=True)
        if not force:
            noise_regexes = h.get("noise_regexes", [])
            _content_len = len(content.strip())
            for noise_re in noise_regexes:
                if noise_re.search(content):
                    if _content_len > 85:
                        break
                    return {
                        "result": f"Rejected: matches noise pattern ('{noise_re.pattern}')",
                        "rejected": True,
                        "total_memories": collection.count(),
                    }

        # ── Embed once, reuse everywhere ──
        _embed_text = h.get("embed_text")
        _cached_vec = None
        if _embed_text:
            try:
                _cached_vec = _embed_text(content)
            except Exception:
                pass

        # ── Step 2b: Context description (fast string-only, entities moved to background) ──
        _amem_context_desc = ""
        try:
            _amem_context_desc = _generate_context_description(content, context)
        except Exception:
            pass

        # ── Step 3: Quality score ──
        _q_score = 0.5
        try:
            from shared.memory_quality import quality_score, QUALITY_THRESHOLD

            _q_score = quality_score(content)
            if _q_score < QUALITY_THRESHOLD:
                _enrichment_tag = "needs-enrichment"
                tags = f"{tags},{_enrichment_tag}" if tags else _enrichment_tag
        except Exception:
            pass

        # ── Step 4: Dedup check (pass cached vector to skip re-embedding) ──
        _soft_dupe_tag = None
        _check_dedup = h.get("check_dedup")
        dedup_result = (
            _check_dedup(content, tags, query_vector=_cached_vec)
            if _check_dedup and not force
            else None
        )
        if dedup_result:
            if dedup_result.get("blocked"):
                return {
                    "result": "Deduplicated: very similar memory already exists",
                    "deduplicated": True,
                    "existing_id": dedup_result["existing_id"],
                    "distance": dedup_result["distance"],
                    "total_memories": collection.count(),
                }
            elif dedup_result.get("soft_dupe_tag"):
                _soft_dupe_tag = dedup_result["soft_dupe_tag"]

        # Citation extraction
        _extract_citations = h.get("extract_citations")
        primary_source = ""
        related_urls = ""
        source_method = ""
        if _extract_citations:
            citation = _extract_citations(content, context)
            content = citation["clean_content"]
            primary_source = citation["primary_source"]
            related_urls = citation["related_urls"]
            source_method = citation["source_method"]

        # ── Step 5: Classify tier ──
        _generate_id = h.get("generate_id")
        doc_id = _generate_id(content) if _generate_id else self._fallback_id(content)
        timestamp = datetime.now().isoformat()
        summary_length = h.get("summary_length", 120)
        preview = content[:summary_length].replace("\n", " ")
        if len(content) > summary_length:
            preview += "..."
        now = time.time()

        if _soft_dupe_tag:
            tags = f"{tags},{_soft_dupe_tag}" if tags else _soft_dupe_tag

        _classify_tier = h.get("classify_tier")
        tier = _classify_tier(content, tags) if _classify_tier else 2
        _classify_memory_type = h.get("classify_memory_type")
        memory_type = (
            _classify_memory_type(content, tags) if _classify_memory_type else ""
        )
        # Semantic classification via daemon for unclassified memories
        if not memory_type:
            _classify_mode = h.get("memory_classify_mode", "tags_only")
            if _classify_mode == "per_save":
                try:
                    from shared.memory_classification import classify_via_daemon

                    memory_type = classify_via_daemon(content, tags)
                except Exception:
                    pass
        _classify_state_type = h.get("classify_state_type")
        state_type = _classify_state_type(content, tags) if _classify_state_type else ""

        # Cluster assignment (reuse cached embedding)
        _assigned_cluster_id = ""
        try:
            _cluster_store = h.get("cluster_store")
            if _cluster_store and _cached_vec:
                _assigned_cluster_id = _cluster_store.assign(_cached_vec, content)
        except Exception:
            pass

        # ── Step 6: Store (pass cached vector to skip re-embedding) ──
        _upsert_meta = {
            "context": context,
            "tags": tags,
            "timestamp": timestamp,
            "session_time": now,
            "preview": preview,
            "primary_source": primary_source,
            "related_urls": related_urls,
            "source_method": source_method,
            "tier": tier,
            "source_session_id": source_session_id,
            "source_observation_ids": source_observation_ids,
            "cluster_id": _assigned_cluster_id,
            "memory_type": memory_type,
            "state_type": state_type,
            "quality_score": _q_score,
            "keywords": "",
            "context_description": _amem_context_desc,
        }
        _upsert_kwargs = {
            "documents": [content],
            "metadatas": [_upsert_meta],
            "ids": [doc_id],
        }
        if _cached_vec:
            _upsert_kwargs["vectors"] = [_cached_vec]
        collection.upsert(**_upsert_kwargs)

        # ── Build result and return immediately ──
        result = {
            "result": "Memory stored successfully!",
            "id": doc_id,
            "total_memories": collection.count(),
            "timestamp": timestamp,
            "quality_score": _q_score,
            "memory_type": memory_type,
            "state_type": state_type,
            "keywords": "",
            "context_description": _amem_context_desc,
        }

        # ── Background: post-store side effects (all fail-open) ──
        bg_args = {
            "doc_id": doc_id,
            "content": content,
            "context": context,
            "tags": tags,
            "tier": tier,
            "memory_type": memory_type,
            "state_type": state_type,
            "quality_score": _q_score,
            "cluster_id": _assigned_cluster_id,
            "cached_vec": _cached_vec,
            "cached_entities": None,
        }
        t = threading.Thread(
            target=self._post_store_background,
            args=(bg_args,),
            daemon=True,
            name="write-pipeline-bg",
        )
        t.start()

        return result

    # ── Background post-store work ────────────────────────────────────────

    def _post_store_background(self, args):
        """Run all fail-open side effects in a background thread (queued)."""
        with self._bg_semaphore:
            try:
                self._bg_inner(args)
            except Exception as e:
                _log.debug("write-pipeline background error: %s", e)

    def _bg_inner(self, a):
        collection = self.collection
        h = self.h

        doc_id = a["doc_id"]
        content = a["content"]
        context = a["context"]
        tags = a["tags"]
        cached_vec = a["cached_vec"]
        cached_entities = a["cached_entities"]

        # Entity extraction (moved from sync path)
        try:
            from shared.entity_extraction import extract_entities

            combined_text = f"{content} {context}" if context else content
            cached_entities = extract_entities(combined_text)
        except Exception:
            cached_entities = []

        # Update keywords metadata in background
        if cached_entities:
            try:
                seen = set()
                keyword_names = []
                for ent in cached_entities:
                    name_lower = ent["name"].lower()
                    if name_lower not in seen:
                        seen.add(name_lower)
                        keyword_names.append(ent["name"])
                keywords_str = ",".join(keyword_names[:10])
                if len(keywords_str) > 500:
                    keywords_str = keywords_str[:497] + "..."
                if keywords_str:
                    collection.update(
                        ids=[doc_id], metadatas=[{"keywords": keywords_str}]
                    )
            except Exception:
                pass

        # Retroactive interference (moved from sync path)
        try:
            self._retroactive_interference(
                content, tags, False, collection, h, query_vector=cached_vec
            )
        except Exception:
            pass

        # Knowledge graph population (reuse cached entities)
        try:
            if self.graph and cached_entities:
                from shared.entity_extraction import extract_cooccurrences

                for ent in cached_entities:
                    self.graph.upsert_entity(ent["name"], ent["type"])
                _kg_text = f"{content} {context}"
                _kg_coocs = extract_cooccurrences(_kg_text)
                _kg_total = collection.count()
                for e1, e2 in _kg_coocs:
                    self.graph.add_edge(e1, e2, "co_occurs")
                    self.graph.update_pmi(e1, e2, "co_occurs", _kg_total)
        except Exception:
            pass

        # A-Mem linking
        try:
            if self.graph and collection.count() > 1:
                _amem_results = collection.query(
                    query_texts=[content] if not cached_vec else None,
                    query_vector=cached_vec if cached_vec else None,
                    n_results=6,
                    include=["metadatas", "distances"],
                )
                if (
                    _amem_results
                    and _amem_results.get("ids")
                    and _amem_results["ids"][0]
                ):
                    _amem_threshold = 0.7
                    for _amem_idx, _amem_id in enumerate(_amem_results["ids"][0]):
                        if _amem_id == doc_id:
                            continue
                        _amem_dist = (
                            _amem_results["distances"][0][_amem_idx]
                            if _amem_results.get("distances")
                            else 1.0
                        )
                        _amem_sim = max(0.0, 1.0 - _amem_dist)
                        if _amem_sim >= _amem_threshold:
                            self.graph.add_edge(
                                doc_id, _amem_id, "linked_memory", strength=_amem_sim
                            )
                            self.graph.add_edge(
                                _amem_id, doc_id, "linked_memory", strength=_amem_sim
                            )
        except Exception:
            pass

        # A-Mem evolution (reuse cached entities for new memory)
        if self.config.get("enable_evolution", True):
            try:
                self._evolve_neighbors_cached(
                    doc_id,
                    content,
                    tags,
                    collection,
                    cached_entities,
                    cached_vec=cached_vec,
                )
            except Exception:
                pass

        # Touch memory timestamp
        _touch = h.get("touch_memory_timestamp")
        if _touch:
            try:
                _touch()
            except Exception:
                pass

        # Hybrid memory linking
        try:
            self._hybrid_linking(doc_id, tags, collection)
        except Exception:
            pass

        # Fix-outcome bridge
        if tags and "type:fix" in tags:
            _bridge = h.get("bridge_to_fix_outcomes")
            if _bridge:
                try:
                    _bridge(content, context, tags)
                except Exception:
                    pass

    # ── Internal helpers ──────────────────────────────────────────────────

    @staticmethod
    def _amem_enrich_cached(content, context, cached_entities):
        """A-Mem enrichment using pre-extracted entities.

        Returns:
            (keywords_str, context_description) -- both strings.
        """
        keywords_str = ""
        context_description = ""

        if cached_entities:
            seen = set()
            keyword_names = []
            for ent in cached_entities:
                name_lower = ent["name"].lower()
                if name_lower not in seen:
                    seen.add(name_lower)
                    keyword_names.append(ent["name"])
            keywords_str = ",".join(keyword_names[:10])
            if len(keywords_str) > 500:
                keywords_str = keywords_str[:497] + "..."

        try:
            context_description = _generate_context_description(content, context)
        except Exception:
            pass

        return keywords_str, context_description

    def _evolve_neighbors_cached(
        self,
        doc_id,
        content,
        tags,
        collection,
        cached_entities,
        cached_vec=None,
    ):
        """A-Mem evolution using pre-extracted entities for the new memory."""
        _MAX_UPDATES = 3
        _MIN_SIMILARITY = 0.3
        _TAG_CAP = 500

        if not tags or not collection:
            return 0

        try:
            from shared.entity_extraction import extract_entities
        except ImportError:
            return 0

        new_entities = set()
        if cached_entities:
            for ent in cached_entities:
                new_entities.add(ent["name"].lower())

        if not new_entities:
            return 0

        new_tag_set = set(t.strip() for t in tags.split(",") if t.strip())
        if not new_tag_set:
            return 0

        try:
            neighbors = collection.query(
                query_texts=[content] if not cached_vec else None,
                query_vector=cached_vec if cached_vec else None,
                n_results=4,
                include=["metadatas", "documents", "distances"],
            )
        except Exception:
            return 0

        if not neighbors or not neighbors.get("ids") or not neighbors["ids"][0]:
            return 0

        updated = 0
        for idx, neighbor_id in enumerate(neighbors["ids"][0]):
            if updated >= _MAX_UPDATES:
                break

            if neighbor_id == doc_id:
                continue

            dist = neighbors["distances"][0][idx] if neighbors.get("distances") else 1.0
            similarity = max(0, 1.0 - dist)
            if similarity < _MIN_SIMILARITY:
                continue

            neighbor_meta = (
                neighbors["metadatas"][0][idx] if neighbors.get("metadatas") else {}
            )
            neighbor_doc = (
                neighbors["documents"][0][idx] if neighbors.get("documents") else ""
            )
            neighbor_tags_str = neighbor_meta.get("tags", "") or ""
            neighbor_context = neighbor_meta.get("context", "") or ""

            neighbor_text = f"{neighbor_doc} {neighbor_context}"
            neighbor_entities = set()
            for ent in extract_entities(neighbor_text):
                neighbor_entities.add(ent["name"].lower())

            shared_entities = new_entities & neighbor_entities
            if not shared_entities:
                continue

            neighbor_tag_set = set(
                t.strip() for t in neighbor_tags_str.split(",") if t.strip()
            )
            propagatable_tags = set()
            _skip_prefixes = ("resolves:", "resolved_by:", "source:", "cluster:")
            for tag in new_tag_set:
                if tag in neighbor_tag_set:
                    continue
                if any(tag.startswith(p) for p in _skip_prefixes):
                    continue
                propagatable_tags.add(tag)

            if not propagatable_tags:
                continue

            merged_tags = neighbor_tags_str
            for ptag in sorted(propagatable_tags):
                candidate = f"{merged_tags},{ptag}" if merged_tags else ptag
                if len(candidate) > _TAG_CAP:
                    break
                merged_tags = candidate

            if merged_tags == neighbor_tags_str:
                continue

            updated_meta = dict(neighbor_meta)
            updated_meta["tags"] = merged_tags
            try:
                collection.update(
                    ids=[neighbor_id],
                    metadatas=[updated_meta],
                )
                updated += 1
            except Exception:
                pass

        return updated

    def _detect_session_id(self):
        """Auto-detect source session ID from most recent JSONL session file."""
        try:
            import glob as _glob

            _sessions_pattern = os.path.join(
                os.path.expanduser("~"),
                ".claude",
                "projects",
                "**",
                "sessions",
                "*.jsonl",
            )
            _jsonl_files = sorted(
                _glob.glob(_sessions_pattern, recursive=True),
                key=os.path.getmtime,
                reverse=True,
            )
            if _jsonl_files:
                return os.path.splitext(os.path.basename(_jsonl_files[0]))[0]
        except Exception:
            pass
        return ""

    def _fallback_id(self, content):
        """Generate a simple ID if generate_id helper not available."""
        import hashlib

        return hashlib.md5(content.encode()).hexdigest()[:16]

    def _retroactive_interference(
        self, content, tags, force, collection, h, query_vector=None
    ):
        """Corrections/fixes suppress similar existing memories."""
        try:
            if (
                collection
                and not force
                and any(t in tags for t in ("type:fix", "type:correction"))
            ):
                from shared.memory_replay import compute_interference

                _classify_tier = h.get("classify_tier")

                _ri_kwargs = {"n_results": 3, "include": ["metadatas", "distances"]}
                if query_vector is not None:
                    _ri_kwargs["query_vector"] = query_vector
                else:
                    _ri_kwargs["query_texts"] = [content]
                _ri_results = collection.query(**_ri_kwargs)
                if _ri_results and _ri_results.get("ids") and _ri_results["ids"][0]:
                    _new_tier = _classify_tier(content, tags) if _classify_tier else 2
                    _new_mem = {"tier": _new_tier, "tags": tags}
                    for _ri_idx, _ri_id in enumerate(_ri_results["ids"][0]):
                        _ri_dist = (
                            _ri_results["distances"][0][_ri_idx]
                            if _ri_results.get("distances")
                            else 1.0
                        )
                        _ri_sim = max(0, 1.0 - _ri_dist)
                        _ri_meta = (
                            _ri_results["metadatas"][0][_ri_idx]
                            if _ri_results.get("metadatas")
                            else {}
                        )
                        _old_mem = {
                            "tier": _ri_meta.get("tier", 2),
                            "tags": _ri_meta.get("tags", ""),
                        }
                        _ri_action = compute_interference(_new_mem, _old_mem, _ri_sim)
                        if _ri_action.get("action") == "suppress":
                            _new_tier_val = _ri_action.get("tier_change", 3)
                            collection.update(
                                ids=[_ri_id],
                                metadatas=[{**_ri_meta, "tier": _new_tier_val}],
                            )
        except Exception:
            pass

    def _hybrid_linking(self, doc_id, tags, collection):
        """Create bidirectional resolves:/resolved_by: links. Returns (resolves_id, linked_to, warning)."""
        resolves_id = None
        linked_to = None
        link_warning = None

        try:
            if tags:
                resolves_tags = [
                    t.strip()
                    for t in tags.split(",")
                    if t.strip().startswith("resolves:")
                ]
                if len(resolves_tags) > 1:
                    link_warning = f"Multiple resolves: tags found; using first: {resolves_tags[0]}"
                if resolves_tags:
                    resolves_id = resolves_tags[0].split(":", 1)[1].strip()
                    if not resolves_id:
                        resolves_id = None
                        link_warning = "resolves: tag has empty ID"
        except Exception as e:
            link_warning = f"Tag parse error: {e}"
            resolves_id = None

        if resolves_id:
            try:
                target = collection.get(ids=[resolves_id], include=["metadatas"])
                if not target or not target.get("ids") or len(target["ids"]) == 0:
                    link_warning = f"resolves:{resolves_id} — target memory not found"
                    resolves_id = None
                else:
                    target_meta = (
                        target["metadatas"][0] if target.get("metadatas") else {}
                    )
                    target_tags = target_meta.get("tags", "") or ""
                    back_link = f"resolved_by:{doc_id}"

                    if back_link not in target_tags:
                        new_tags = (
                            f"{target_tags},{back_link}" if target_tags else back_link
                        )
                        if len(new_tags) > 500:
                            link_warning = f"Tag overflow (>{500} chars) — skipped resolved_by: back-link on target"
                        else:
                            target_meta_updated = dict(target_meta)
                            target_meta_updated["tags"] = new_tags
                            collection.update(
                                ids=[resolves_id],
                                metadatas=[target_meta_updated],
                            )
                    linked_to = resolves_id
            except Exception as e:
                link_warning = f"Linking error: {e}"
                resolves_id = None

        return resolves_id, linked_to, link_warning


# ── Module-level helpers ─────────────────────────────────────────────────────────────

# Sentence boundary pattern: split on  followed by capital, or on  /
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def _generate_context_description(content, context=""):
    """Generate a 1-sentence context description for A-Mem structured notes.

    Strategy:
    1. If context is provided and non-trivial, use it directly (already a description).
    2. Otherwise, extract first sentence from content as the context description.
    3. Cap at 200 chars for metadata safety.
    """
    # If caller provided a context string, prefer it (it is typically a description)
    if context and len(context.strip()) >= 10:
        desc = context.strip()
        # Take first sentence if context is multi-sentence
        sentences = _SENTENCE_END_RE.split(desc)
        if sentences:
            desc = sentences[0].strip()
        if len(desc) > 200:
            desc = desc[:197] + "..."
        return desc

    # Fall back to first sentence of content
    stripped = content.strip()
    if not stripped:
        return ""

    # Remove leading project prefix like [project:xyz]
    if stripped.startswith("["):
        bracket_end = stripped.find("]")
        if bracket_end > 0 and bracket_end < 60:
            stripped = stripped[bracket_end + 1 :].strip()

    sentences = _SENTENCE_END_RE.split(stripped)
    if sentences:
        desc = sentences[0].strip()
    else:
        desc = stripped

    if len(desc) > 200:
        desc = desc[:197] + "..."
    return desc
