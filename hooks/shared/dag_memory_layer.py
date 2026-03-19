#!/usr/bin/env python3
"""DAG Memory Layer — SQLite-backed memory interface on conversations.db.

Provides write/search/promote capabilities on the DAG's knowledge,
observations, and fix_outcomes tables. Mirrors LanceDB memory system
capabilities for dual-write and merged search (Option 3).

All methods are fail-open — exceptions are caught and logged to stderr.
"""

import json
import math
import secrets
import struct
import sys
import time

_EMBEDDING_DIM = 768


def _gen_id(prefix="dk_"):
    return prefix + secrets.token_hex(8)


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


class DAGMemoryLayer:
    """SQLite-backed memory layer on the DAG's conversations.db."""

    def __init__(self, dag):
        self._db = dag._db
        self._dag = dag

    def store(
        self,
        content,
        tags="",
        tier=1,
        memory_type="",
        state_type="",
        context="",
        source_node_id="",
        cluster_id="",
        quality_score=0.0,
        metadata=None,
    ):
        """Write a knowledge entry. Returns {"id": ..., "stored": True}."""
        doc_id = _gen_id("dk_")
        now = _now_iso()
        meta_json = json.dumps(metadata) if metadata else "{}"
        try:
            self._db.execute(
                "INSERT INTO knowledge "
                "(id, content, context, tags, tier, memory_type, state_type, "
                "cluster_id, retrieval_count, quality_score, source_node_id, "
                "created_at, updated_at, metadata) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    doc_id,
                    content,
                    context,
                    tags,
                    tier,
                    memory_type,
                    state_type,
                    cluster_id,
                    0,
                    quality_score,
                    source_node_id,
                    now,
                    now,
                    meta_json,
                ),
            )
            self._db.commit()
            return {"id": doc_id, "stored": True, "timestamp": now}
        except Exception as e:
            print(f"[DAG_MEMORY] store failed: {e}", file=sys.stderr)
            return {"id": "", "stored": False, "error": str(e)}

    def search(self, query, top_k=15, mode="keyword", project_scope=None):
        """Search knowledge via FTS5 (keyword) or LIKE fallback.

        Returns list of dicts with id, content, tags, tier, etc.
        """
        results = []
        try:
            if mode in ("keyword", "hybrid", ""):
                results = self._fts5_search(query, top_k, project_scope)
            if not results:
                # Fallback to LIKE
                results = self._like_search(query, top_k, project_scope)
        except Exception as e:
            print(f"[DAG_MEMORY] search failed: {e}", file=sys.stderr)
            # Final fallback
            try:
                results = self._like_search(query, top_k, project_scope)
            except Exception:
                pass
        return results

    def _fts5_search(self, query, top_k, project_scope=None):
        """Search knowledge_fts using FTS5 MATCH."""
        # Escape special FTS5 characters
        safe_query = query.replace('"', '""')
        sql = (
            "SELECT k.id, k.content, k.tags, k.tier, k.memory_type, "
            "k.retrieval_count, k.created_at, k.source_node_id, k.quality_score "
            "FROM knowledge k "
            "JOIN knowledge_fts f ON k.rowid = f.rowid "
            f"WHERE knowledge_fts MATCH '\"{safe_query}\"' "
            "ORDER BY rank "
            f"LIMIT {int(top_k)}"
        )
        rows = self._db.execute(sql).fetchall()
        return [self._knowledge_row_to_dict(r) for r in rows]

    def _like_search(self, query, top_k, project_scope=None):
        """Fallback LIKE search on knowledge content."""
        sql = (
            "SELECT id, content, tags, tier, memory_type, "
            "retrieval_count, created_at, source_node_id, quality_score "
            "FROM knowledge WHERE content LIKE ? "
            "ORDER BY created_at DESC "
            f"LIMIT {int(top_k)}"
        )
        rows = self._db.execute(sql, (f"%{query}%",)).fetchall()
        return [self._knowledge_row_to_dict(r) for r in rows]

    def _knowledge_row_to_dict(self, row):
        return {
            "id": row[0],
            "content": row[1],
            "tags": row[2],
            "tier": row[3],
            "memory_type": row[4],
            "retrieval_count": row[5],
            "created_at": row[6],
            "source_node_id": row[7],
            "quality_score": row[8],
            "source": "dag_sqlite",
        }

    def store_observation(self, content, tags="", metadata=None):
        """Write an observation entry."""
        doc_id = _gen_id("do_")
        now = _now_iso()
        meta_json = json.dumps(metadata) if metadata else "{}"
        try:
            self._db.execute(
                "INSERT INTO observations "
                "(id, content, tags, tier, retrieval_count, created_at, metadata) "
                "VALUES (?,?,?,?,?,?,?)",
                (doc_id, content, tags, 0, 0, now, meta_json),
            )
            self._db.commit()
            return {"id": doc_id, "stored": True}
        except Exception as e:
            print(f"[DAG_MEMORY] store_observation failed: {e}", file=sys.stderr)
            return {"id": "", "stored": False, "error": str(e)}

    def store_fix_outcome(self, chain_id, error, strategy="", outcome="", node_id=""):
        """Write a fix outcome entry."""
        doc_id = _gen_id("df_")
        now = _now_iso()
        try:
            self._db.execute(
                "INSERT INTO fix_outcomes "
                "(id, chain_id, error_description, strategy, outcome, node_id, "
                "created_at, metadata) VALUES (?,?,?,?,?,?,?,?)",
                (doc_id, chain_id, error, strategy, outcome, node_id, now, "{}"),
            )
            self._db.commit()
            return {"id": doc_id, "stored": True}
        except Exception as e:
            print(f"[DAG_MEMORY] store_fix_outcome failed: {e}", file=sys.stderr)
            return {"id": "", "stored": False, "error": str(e)}

    def add_edge(self, source_id, target_id, edge_type, weight=1.0):
        """Add a knowledge graph edge between nodes/knowledge entries."""
        now = _now_iso()
        try:
            self._db.execute(
                "INSERT OR REPLACE INTO node_edges "
                "(source_id, target_id, edge_type, weight, created_at) "
                "VALUES (?,?,?,?,?)",
                (source_id, target_id, edge_type, weight, now),
            )
            self._db.commit()
        except Exception as e:
            print(f"[DAG_MEMORY] add_edge failed: {e}", file=sys.stderr)

    def get_entry(self, entry_id):
        """Read a single knowledge entry by ID."""
        row = self._db.execute(
            "SELECT id, content, tags, tier, memory_type, "
            "retrieval_count, created_at, source_node_id, quality_score "
            "FROM knowledge WHERE id = ?",
            (entry_id,),
        ).fetchone()
        if not row:
            return None
        return self._knowledge_row_to_dict(row)

    def increment_retrieval(self, entry_id):
        """Bump retrieval_count for an entry (for LTP tracking)."""
        try:
            self._db.execute(
                "UPDATE knowledge SET retrieval_count = retrieval_count + 1, "
                "updated_at = ? WHERE id = ?",
                (_now_iso(), entry_id),
            )
            self._db.commit()
        except Exception:
            pass

    def count(self, table="knowledge"):
        """Return row count for a table."""
        try:
            row = self._db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            return row[0] if row else 0
        except Exception:
            return 0

    # --- Embedding methods ---

    def store_embedding(self, entry_id, source_table, vector):
        """Store an embedding vector as a BLOB."""
        try:
            blob = struct.pack(f"{len(vector)}f", *vector)
            self._db.execute(
                "INSERT OR REPLACE INTO embeddings "
                "(id, source_table, source_id, vector, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (f"emb_{entry_id}", source_table, entry_id, blob, _now_iso()),
            )
            self._db.commit()
        except Exception as e:
            print(f"[DAG_MEMORY] store_embedding failed: {e}", file=sys.stderr)

    def cosine_search(self, query_vec, top_k=15, source_table="knowledge"):
        """Python cosine similarity search over stored embeddings.

        Returns list of (source_id, similarity_score) tuples, highest first.
        """
        try:
            rows = self._db.execute(
                "SELECT source_id, vector FROM embeddings WHERE source_table = ?",
                (source_table,),
            ).fetchall()
            if not rows:
                return []
            scored = []
            q_mag = math.sqrt(sum(a * a for a in query_vec))
            if q_mag == 0:
                return []
            for source_id, blob in rows:
                n_floats = len(blob) // 4
                vec = struct.unpack(f"{n_floats}f", blob)
                dot = sum(a * b for a, b in zip(query_vec, vec))
                v_mag = math.sqrt(sum(b * b for b in vec))
                sim = dot / (q_mag * v_mag) if v_mag else 0
                scored.append((source_id, sim))
            scored.sort(key=lambda x: -x[1])
            return scored[:top_k]
        except Exception as e:
            print(f"[DAG_MEMORY] cosine_search failed: {e}", file=sys.stderr)
            return []

    def semantic_search(self, query, top_k=15, embed_fn=None):
        """Semantic search: embed query, then cosine search knowledge embeddings.

        embed_fn: callable that takes a string and returns a list of floats (768-dim).
        If not provided, falls back to FTS5 keyword search.
        """
        if embed_fn is None:
            return self.search(query, top_k=top_k, mode="keyword")
        try:
            query_vec = embed_fn(query)
            scored = self.cosine_search(query_vec, top_k=top_k)
            if not scored:
                return self.search(query, top_k=top_k, mode="keyword")
            # Fetch full entries for scored results
            results = []
            for source_id, sim in scored:
                entry = self.get_entry(source_id)
                if entry:
                    entry["relevance"] = sim
                    results.append(entry)
            return results
        except Exception:
            return self.search(query, top_k=top_k, mode="keyword")

    def embed_knowledge_batch(self, embed_fn, batch_size=50):
        """Embed all knowledge entries that don't have embeddings yet.

        Returns count of newly embedded entries.
        """
        try:
            # Find entries without embeddings
            rows = self._db.execute(
                "SELECT k.id, k.content FROM knowledge k "
                "LEFT JOIN embeddings e ON e.source_id = k.id AND e.source_table = 'knowledge' "
                "WHERE e.id IS NULL "
                f"LIMIT {batch_size}"
            ).fetchall()
            if not rows:
                return 0
            count = 0
            for entry_id, content in rows:
                try:
                    vec = embed_fn(content)
                    if vec and len(vec) > 0:
                        self.store_embedding(entry_id, "knowledge", vec)
                        count += 1
                except Exception:
                    continue
            return count
        except Exception as e:
            print(f"[DAG_MEMORY] embed_batch failed: {e}", file=sys.stderr)
            return 0

    def search_nodes_fts(self, query, top_k=10, role_filter=None):
        """Search DAG nodes via FTS5 (faster than LIKE for keyword search)."""
        try:
            safe_query = query.replace('"', '""')
            sql = (
                "SELECT n.id, n.parent_id, n.role, n.content, n.model, "
                "n.provider, n.timestamp, n.token_count, n.metadata "
                "FROM nodes n "
                "JOIN nodes_fts f ON n.rowid = f.rowid "
                f"WHERE nodes_fts MATCH '\"{safe_query}\"' "
            )
            if role_filter:
                sql += f"AND n.role = '{role_filter}' "
            sql += f"ORDER BY rank LIMIT {int(top_k)}"
            rows = self._db.execute(sql).fetchall()
            return [self._dag._row_to_dict(r) for r in rows]
        except Exception:
            # Fallback to DAG's LIKE search
            return self._dag.search_nodes(query, top_k, role_filter)


def promote_nodes(dag, layer, threshold=0.15, max_promotions=20):
    """Scan unpromoted nodes, score with salience_score, promote above threshold.

    Returns list of promoted knowledge entry IDs.
    """
    try:
        from shared.memory_classification import salience_score
    except ImportError:
        try:
            import os
            import importlib.util

            spec = importlib.util.spec_from_file_location(
                "memory_classification",
                os.path.join(os.path.dirname(__file__), "memory_classification.py"),
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            salience_score = mod.salience_score
        except Exception:
            return []

    promoted = []
    try:
        # Find unpromoted nodes with substantial content
        rows = dag._db.execute(
            "SELECT id, role, content, metadata FROM nodes "
            "WHERE role IN ('assistant', 'user') "
            "AND length(content) > 50 "
            "AND metadata NOT LIKE '%\"promoted\": true%' "
            "AND metadata NOT LIKE '%\"promoted\":true%' "
            "ORDER BY timestamp DESC "
            f"LIMIT {max_promotions * 3}"
        ).fetchall()

        for node_id, role, content, meta_json in rows:
            if len(promoted) >= max_promotions:
                break

            # Infer tags from content for salience scoring
            tags = _infer_tags(content, role)
            score = salience_score(content, tags)

            if score >= threshold:
                # Get parent context for richer content
                context_content = _build_promotion_context(dag, node_id)
                promoted_content = content
                if context_content:
                    promoted_content = f"{content}\n\n[Context: {context_content}]"

                result = layer.store(
                    content=promoted_content[:800],
                    tags=f"{tags},source:dag,dag_node:{node_id}",
                    tier=1 if score >= 0.25 else 2,
                    quality_score=score,
                    source_node_id=node_id,
                )
                if result.get("stored"):
                    promoted.append(result["id"])
                    dag.update_metadata(node_id, {"promoted": True})

    except Exception as e:
        print(f"[DAG_MEMORY] promote_nodes failed: {e}", file=sys.stderr)

    return promoted


def _infer_tags(content, role):
    """Infer basic tags from content for salience scoring."""
    tags = []
    lower = content.lower()
    if role == "user":
        if any(w in lower for w in ("actually", "no,", "wrong", "that's not")):
            tags.append("type:correction")
        elif any(w in lower for w in ("can you", "i wish", "would it be")):
            tags.append("type:feature-request")
    elif role == "assistant":
        if any(w in lower for w in ("fixed", "fix:", "bug", "root cause")):
            tags.append("type:fix")
        elif any(w in lower for w in ("decided", "decision", "chose", "going with")):
            tags.append("type:decision")
        elif any(
            w in lower for w in ("learned", "discovery", "found that", "turns out")
        ):
            tags.append("type:learning")
    if any(w in lower for w in ("critical", "important", "breaking")):
        tags.append("priority:high")
    return ",".join(tags) if tags else "type:auto-captured"


def _build_promotion_context(dag, node_id, max_ancestors=3):
    """Get a few ancestor messages for context around a promoted node."""
    try:
        ancestors = dag.get_ancestors(node_id)
        if len(ancestors) <= 1:
            return ""
        # Get up to max_ancestors messages before the target
        idx = next((i for i, a in enumerate(ancestors) if a["id"] == node_id), -1)
        if idx <= 0:
            return ""
        start = max(0, idx - max_ancestors)
        context_parts = []
        for a in ancestors[start:idx]:
            content = a["content"][:150]
            context_parts.append(f"[{a['role']}] {content}")
        return " | ".join(context_parts)
    except Exception:
        return ""
