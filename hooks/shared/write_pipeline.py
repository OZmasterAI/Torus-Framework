"""Write Pipeline — Layer 3 of the Memory v2 Layered Redesign.

Orchestrates the full write flow: validate → normalize → quality score →
dedup check → classify tier → store → side effects.

Public API:
    from shared.write_pipeline import WritePipeline
"""

import os
import time
from datetime import datetime


class WritePipeline:
    """7-step write orchestrator.

    Coordinates: validation, normalization, quality scoring, dedup,
    tier classification, storage, and side effects.
    """

    def __init__(self, collection, tag_index, graph, config, helpers):
        """
        Args:
            collection: ChromaDB/LanceDB collection for knowledge
            tag_index: TagIndex instance
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
        tag_index = self.tag_index
        h = self.h

        # Auto-detect source session ID
        if not source_session_id:
            source_session_id = self._detect_session_id()

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

        # ── Step 4: Dedup check ──
        _soft_dupe_tag = None
        _check_dedup = h.get("check_dedup")
        dedup_result = (
            _check_dedup(content, tags) if _check_dedup and not force else None
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

        # Retroactive interference
        self._retroactive_interference(content, tags, force, collection, h)

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

        # Cluster assignment
        _assigned_cluster_id = ""
        try:
            _cluster_store = h.get("cluster_store")
            _embed_text = h.get("embed_text")
            if _cluster_store and _embed_text:
                _cluster_vec = _embed_text(content)
                _assigned_cluster_id = _cluster_store.assign(_cluster_vec, content)
        except Exception:
            pass

        # ── Step 6: Store ──
        collection.upsert(
            documents=[content],
            metadatas=[
                {
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
                    "quality_score": _q_score,
                }
            ],
            ids=[doc_id],
        )

        # Update tag index
        tag_index.add_tags(doc_id, tags)

        # Knowledge graph population
        try:
            if self.graph:
                from shared.entity_extraction import (
                    extract_entities,
                    extract_cooccurrences,
                )

                _kg_text = f"{content} {context}"
                _kg_entities = extract_entities(_kg_text)
                for ent in _kg_entities:
                    self.graph.upsert_entity(ent["name"], ent["type"])
                _kg_coocs = extract_cooccurrences(_kg_text)
                _kg_total = collection.count()
                for e1, e2 in _kg_coocs:
                    self.graph.add_edge(e1, e2, "co_occurs")
                    self.graph.update_pmi(e1, e2, "co_occurs", _kg_total)
        except Exception:
            pass

        # ── Step 7: Side effects ──
        _touch = h.get("touch_memory_timestamp")
        if _touch:
            try:
                _touch()
            except Exception:
                pass

        # Hybrid memory linking
        resolves_id, linked_to, link_warning = self._hybrid_linking(
            doc_id, tags, collection, tag_index
        )

        # Fix-outcome bridge
        bridge_result = None
        if tags and "type:fix" in tags:
            _bridge = h.get("bridge_to_fix_outcomes")
            if _bridge:
                bridge_result = _bridge(content, context, tags)

        # Build result
        result = {
            "result": "Memory stored successfully!",
            "id": doc_id,
            "total_memories": collection.count(),
            "timestamp": timestamp,
            "quality_score": _q_score,
        }
        if bridge_result:
            result["fix_outcome_bridged"] = True
            result["bridge_chain_id"] = bridge_result.get("chain_id", "")
        if linked_to:
            result["linked_to"] = linked_to
        if link_warning:
            result["link_warning"] = link_warning
        if tags and "type:fix" in tags and not resolves_id and not linked_to:
            result["hint"] = (
                "Tip: add a resolves:MEMORY_ID tag to link this fix to the problem memory it resolves"
            )

        return result

    # ── Internal helpers ──────────────────────────────────────────────────

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

    def _retroactive_interference(self, content, tags, force, collection, h):
        """Corrections/fixes suppress similar existing memories."""
        try:
            if (
                collection
                and not force
                and any(t in tags for t in ("type:fix", "type:correction"))
            ):
                from shared.memory_replay import compute_interference

                _classify_tier = h.get("classify_tier")

                _ri_results = collection.query(
                    query_texts=[content],
                    n_results=3,
                    include=["metadatas", "distances"],
                )
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

    def _hybrid_linking(self, doc_id, tags, collection, tag_index):
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
                            try:
                                tag_index.add_tags(resolves_id, new_tags)
                            except Exception:
                                pass
                    linked_to = resolves_id
            except Exception as e:
                link_warning = f"Linking error: {e}"
                resolves_id = None

        return resolves_id, linked_to, link_warning
