#!/usr/bin/env python3
"""DAG Memory Layer — SQLite-backed memory interface on conversations.db.

Provides write/search/promote capabilities on the DAG's knowledge,
observations, and fix_outcomes tables. Mirrors LanceDB memory system
capabilities for dual-write and merged search (Option 3).

All methods are fail-open — exceptions are caught and logged to stderr.
"""

import json
import re
import secrets
import struct
import sys
import time

import numpy as np

_EMBEDDING_DIM = 768

# FTS5 special characters that must be stripped/replaced before a MATCH query.
# Wrapping in phrase quotes ("...") handles most operators, but these chars
# can still break the tokenizer or produce syntax errors inside a phrase token.
_FTS5_SPECIAL = re.compile(r"[*&|()\-:^~]")


def _gen_id(prefix="dk_"):
    return prefix + secrets.token_hex(8)


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _fnv1a_hash(text: str) -> str:
    """FNV-1a 64-bit hash of text, truncated to 16 hex chars.

    Mirrors error_normalizer.fnv1a_hash but operates on raw content so we
    don't need to import the shared module (avoids circular imports).
    """
    h = 14695981039346656037  # FNV offset basis
    for byte in text.encode("utf-8"):
        h ^= byte
        h = (h * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return format(h, "016x")


def _escape_fts5(query: str) -> str:
    """Strip all FTS5 operator characters from a query string.

    Double-quotes are escaped as two double-quotes (SQLite FTS5 convention).
    All other special chars (*&|()\-:^~) are replaced with a space so
    multi-word phrases remain usable.
    """
    q = query.replace('"', '""')
    q = _FTS5_SPECIAL.sub(" ", q)
    # Collapse runs of whitespace that replacement may have introduced
    q = re.sub(r"\s+", " ", q).strip()
    return q


class DAGMemoryLayer:
    """SQLite-backed memory layer on the DAG's conversations.db."""

    def __init__(self, dag, embed_fn=None):
        self._db = dag._db
        self._dag = dag
        self._embed_fn = embed_fn

    # ------------------------------------------------------------------
    # Write methods
    # ------------------------------------------------------------------

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
        """Write a knowledge entry. Returns {"id": ..., "stored": True}.

        Deduplication: if an entry with the same FNV-1a content hash already
        exists, the existing entry's ID is returned without a new insert.
        """
        content_hash = _fnv1a_hash(content)

        # Check for existing entry with identical content hash (fail-open)
        try:
            existing = self._db.execute(
                "SELECT id FROM knowledge WHERE metadata LIKE ? LIMIT 1",
                (f'%"content_hash": "{content_hash}"%',),
            ).fetchone()
            if existing:
                return {"id": existing[0], "stored": False, "duplicate": True}
        except Exception:
            pass  # If dedup check fails, proceed with insert

        doc_id = _gen_id("dk_")
        now = _now_iso()
        # Embed content hash in metadata for future dedup checks
        if metadata is None:
            metadata = {}
        metadata["content_hash"] = content_hash
        meta_json = json.dumps(metadata)
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
        """Search knowledge_fts using FTS5 MATCH.

        Uses _escape_fts5() to strip ALL special chars (*, &, |, parens, -, :, ^, ~)
        and passes the phrase as a parameterized value (not interpolated into SQL).
        """
        safe_query = _escape_fts5(query)
        if not safe_query:
            return []
        sql = (
            "SELECT k.id, k.content, k.tags, k.tier, k.memory_type, "
            "k.retrieval_count, k.created_at, k.source_node_id, k.quality_score "
            "FROM knowledge k "
            "JOIN knowledge_fts f ON k.rowid = f.rowid "
            "WHERE knowledge_fts MATCH ? "
            "ORDER BY rank "
            f"LIMIT {int(top_k)}"
        )
        rows = self._db.execute(sql, (f'"{safe_query}"',)).fetchall()
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

    def find_related_nodes(
        self, node_id, edge_type=None, direction="both", limit=50, max_hops=3
    ):
        """Find nodes connected to node_id via recursive CTE BFS traversal.

        Uses SQLite recursive CTEs with UNION (not UNION ALL) for cycle
        prevention.  Traverses node_edges in the specified direction up to
        max_hops steps.

        Args:
            node_id: The node to find relations for.
            edge_type: Optional filter by edge type (e.g. 'derived_from', 'co_occurs').
            direction: 'outgoing', 'incoming', or 'both'.
            limit: Max results.
            max_hops: Maximum traversal depth (default 3, hard cap 20).

        Returns list of dicts: {node_id, edge_type, weight, direction, created_at, depth}.
        """
        max_hops = min(max_hops, 20)  # Safety cap
        results = []
        try:
            if direction in ("outgoing", "both"):
                edge_filter = "AND e.edge_type = ?" if edge_type else ""
                sql = f"""
                    WITH RECURSIVE traverse(nid, etype, weight, created_at, depth) AS (
                        SELECT e.target_id, e.edge_type, e.weight, e.created_at, 1
                        FROM node_edges e
                        WHERE e.source_id = ? {edge_filter}
                        UNION
                        SELECT e.target_id, e.edge_type, e.weight, e.created_at, t.depth + 1
                        FROM node_edges e
                        JOIN traverse t ON e.source_id = t.nid
                        WHERE t.depth < ? {edge_filter}
                          AND e.target_id != ?
                    )
                    SELECT nid, etype, weight, created_at, MIN(depth) AS min_depth
                    FROM traverse
                    GROUP BY nid
                    ORDER BY weight DESC
                    LIMIT ?
                """
                params = [node_id]
                if edge_type:
                    params.append(edge_type)
                params.append(max_hops)
                if edge_type:
                    params.append(edge_type)
                params.extend([node_id, limit])
                for row in self._db.execute(sql, params).fetchall():
                    results.append(
                        {
                            "node_id": row[0],
                            "edge_type": row[1],
                            "weight": row[2],
                            "direction": "outgoing",
                            "created_at": row[3],
                            "depth": row[4],
                        }
                    )
            if direction in ("incoming", "both"):
                edge_filter = "AND e.edge_type = ?" if edge_type else ""
                remaining = max(1, limit - len(results))
                sql = f"""
                    WITH RECURSIVE traverse(nid, etype, weight, created_at, depth) AS (
                        SELECT e.source_id, e.edge_type, e.weight, e.created_at, 1
                        FROM node_edges e
                        WHERE e.target_id = ? {edge_filter}
                        UNION
                        SELECT e.source_id, e.edge_type, e.weight, e.created_at, t.depth + 1
                        FROM node_edges e
                        JOIN traverse t ON e.target_id = t.nid
                        WHERE t.depth < ? {edge_filter}
                          AND e.source_id != ?
                    )
                    SELECT nid, etype, weight, created_at, MIN(depth) AS min_depth
                    FROM traverse
                    GROUP BY nid
                    ORDER BY weight DESC
                    LIMIT ?
                """
                params = [node_id]
                if edge_type:
                    params.append(edge_type)
                params.append(max_hops)
                if edge_type:
                    params.append(edge_type)
                params.extend([node_id, remaining])
                for row in self._db.execute(sql, params).fetchall():
                    results.append(
                        {
                            "node_id": row[0],
                            "edge_type": row[1],
                            "weight": row[2],
                            "direction": "incoming",
                            "created_at": row[3],
                            "depth": row[4],
                        }
                    )
        except Exception as e:
            print(f"[DAG_MEMORY] find_related_nodes failed: {e}", file=sys.stderr)
        return results

    def get_edge_path(self, from_id, to_id, max_hops=6):
        """Find shortest path between two nodes via recursive CTE BFS.

        Uses SQLite recursive CTE with UNION for cycle prevention over
        the node_edges table, treating edges as bidirectional.  Reconstructs
        the path by storing the full trail as a comma-separated string.

        Returns list of node IDs forming the path (inclusive of from_id and to_id),
        or empty list if no path exists within max_hops.  Hard cap at 20 hops.
        """
        if from_id == to_id:
            return [from_id]
        max_hops = min(max_hops, 20)  # Safety cap
        try:
            # Recursive CTE BFS with path tracking via comma-separated string.
            # INSTR guards against revisiting nodes already on the current path.
            sql = """
                WITH RECURSIVE bfs(nid, depth, path) AS (
                    SELECT ?, 0, ?
                    UNION
                    SELECT
                        CASE
                            WHEN e.source_id = b.nid THEN e.target_id
                            ELSE e.source_id
                        END,
                        b.depth + 1,
                        b.path || ',' ||
                        CASE
                            WHEN e.source_id = b.nid THEN e.target_id
                            ELSE e.source_id
                        END
                    FROM node_edges e
                    JOIN bfs b ON (e.source_id = b.nid OR e.target_id = b.nid)
                    WHERE b.depth < ?
                      AND INSTR(',' || b.path || ',', ',' ||
                          CASE
                              WHEN e.source_id = b.nid THEN e.target_id
                              ELSE e.source_id
                          END || ',') = 0
                )
                SELECT path FROM bfs
                WHERE nid = ?
                ORDER BY depth
                LIMIT 1
            """
            row = self._db.execute(sql, (from_id, from_id, max_hops, to_id)).fetchone()
            if row:
                return row[0].split(",")
            return []
        except Exception as e:
            print(f"[DAG_MEMORY] get_edge_path failed: {e}", file=sys.stderr)
            return []

    def get_subgraph(self, seed_ids, max_hops=2, edge_type=None):
        """BFS expansion from seed nodes using recursive CTE, returning all
        reachable nodes and edges within max_hops.

        Uses SQLite recursive CTE with UNION for cycle prevention over
        the node_edges table, treating edges as bidirectional.

        Args:
            seed_ids: List of starting node IDs.
            max_hops: Maximum traversal depth (hard cap 20).
            edge_type: Optional filter by edge type.

        Returns dict with 'nodes' (set of IDs) and 'edges' (list of edge tuples).
        """
        max_hops = min(max_hops, 20)  # Safety cap
        all_nodes = set(seed_ids)
        all_edges = []
        try:
            for seed in seed_ids:
                edge_filter = "AND e.edge_type = ?" if edge_type else ""
                # Bidirectional BFS via recursive CTE with UNION for cycle safety
                sql = f"""
                    WITH RECURSIVE traverse(nid, depth) AS (
                        SELECT ?, 0
                        UNION
                        SELECT
                            CASE
                                WHEN e.source_id = t.nid THEN e.target_id
                                ELSE e.source_id
                            END,
                            t.depth + 1
                        FROM node_edges e
                        JOIN traverse t ON (e.source_id = t.nid OR e.target_id = t.nid)
                        WHERE t.depth < ? {edge_filter}
                    )
                    SELECT DISTINCT nid FROM traverse
                """
                params = [seed, max_hops]
                if edge_type:
                    params.append(edge_type)
                for row in self._db.execute(sql, params).fetchall():
                    all_nodes.add(row[0])

            # Collect edges between discovered nodes
            if all_nodes:
                placeholders = ",".join("?" * len(all_nodes))
                node_list = list(all_nodes)
                edge_sql = (
                    f"SELECT source_id, target_id, edge_type, weight "
                    f"FROM node_edges "
                    f"WHERE source_id IN ({placeholders}) "
                    f"AND target_id IN ({placeholders})"
                )
                params = node_list + node_list
                if edge_type:
                    edge_sql += " AND edge_type = ?"
                    params.append(edge_type)
                for row in self._db.execute(edge_sql, params).fetchall():
                    all_edges.append((row[0], row[1], row[2], row[3]))
        except Exception as e:
            print(f"[DAG_MEMORY] get_subgraph failed: {e}", file=sys.stderr)
        # Deduplicate edges
        seen = set()
        unique = []
        for e in all_edges:
            key = (e[0], e[1], e[2])
            if key not in seen:
                seen.add(key)
                unique.append(e)
        return {"nodes": all_nodes, "edges": unique}

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

    # ------------------------------------------------------------------
    # Embedding methods
    # ------------------------------------------------------------------

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
        """Numpy-vectorized cosine similarity search over stored embeddings.

        Returns list of (source_id, similarity_score) tuples, highest first.
        """
        try:
            rows = self._db.execute(
                "SELECT source_id, vector FROM embeddings WHERE source_table = ?",
                (source_table,),
            ).fetchall()
            if not rows:
                return []
            q = np.array(query_vec, dtype=np.float32)
            q_mag = np.linalg.norm(q)
            if q_mag == 0:
                return []
            ids = []
            vecs = []
            for source_id, blob in rows:
                n_floats = len(blob) // 4
                vecs.append(np.frombuffer(blob, dtype=np.float32, count=n_floats))
                ids.append(source_id)
            matrix = np.vstack(vecs)
            dots = matrix @ q
            norms = np.linalg.norm(matrix, axis=1)
            norms[norms == 0] = 1.0
            sims = dots / (q_mag * norms)
            top_indices = np.argpartition(-sims, min(top_k, len(sims) - 1))[:top_k]
            top_indices = top_indices[np.argsort(-sims[top_indices])]
            return [(ids[i], float(sims[i])) for i in top_indices]
        except Exception as e:
            print(f"[DAG_MEMORY] cosine_search failed: {e}", file=sys.stderr)
            return []

    def semantic_search(self, query, top_k=15, embed_fn=None, query_vector=None):
        """Semantic search: embed query, then cosine search knowledge embeddings.

        embed_fn: callable that takes a string and returns a list of floats (768-dim).
        query_vector: pre-computed embedding vector (skips embed_fn call if provided).
        If not provided, uses self._embed_fn from the constructor.
        If neither is available, falls back to FTS5 keyword search.
        """
        fn = embed_fn or self._embed_fn
        if query_vector is None and fn is None:
            return self.search(query, top_k=top_k, mode="keyword")
        try:
            query_vec = query_vector if query_vector is not None else fn(query)
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

        The SQL LIMIT is parameterized (not an f-string), ensuring fetchall()
        is bounded before the per-entry embedding loop unpacks rows.
        Returns count of newly embedded entries.
        """
        try:
            # LIMIT applied in SQL via parameter — fetchall() list is bounded
            # by batch_size before we start unpacking and calling embed_fn.
            rows = self._db.execute(
                "SELECT k.id, k.content FROM knowledge k "
                "LEFT JOIN embeddings e "
                "  ON e.source_id = k.id AND e.source_table = 'knowledge' "
                "WHERE e.id IS NULL "
                "LIMIT ?",
                (int(batch_size),),
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

    # ------------------------------------------------------------------
    # Node search methods
    # ------------------------------------------------------------------

    def search_nodes_fts(self, query, top_k=10, role_filter=None):
        """Search DAG nodes via FTS5 (faster than LIKE for keyword search).

        Uses _escape_fts5() for complete special-char stripping and passes
        the match string as a parameterized value.
        """
        try:
            safe_query = _escape_fts5(query)
            if not safe_query:
                return self._dag.search_nodes(query, top_k, role_filter)
            sql = (
                "SELECT n.id, n.parent_id, n.role, n.content, n.model, "
                "n.provider, n.timestamp, n.token_count, n.metadata "
                "FROM nodes n "
                "JOIN nodes_fts f ON n.rowid = f.rowid "
                "WHERE nodes_fts MATCH ? "
            )
            params = [f'"{safe_query}"']
            if role_filter:
                sql += "AND n.role = ? "
                params.append(role_filter)
            sql += f"ORDER BY rank LIMIT {int(top_k)}"
            rows = self._db.execute(sql, params).fetchall()
            return [self._dag._row_to_dict(r) for r in rows]
        except Exception:
            # Fallback to DAG's LIKE search
            return self._dag.search_nodes(query, top_k, role_filter)

    def semantic_search_nodes(self, query, top_k=20, embed_fn=None, branch_ids=None):
        """Cross-branch semantic discovery over DAG nodes.

        Finds nodes semantically similar to `query` across all branches (or
        a supplied subset).  Falls back to FTS5 keyword search when no
        embed_fn is provided or no embeddings are available.

        The embed_fn can be passed per-call or set once in the constructor.
        Per-call embed_fn takes precedence over the constructor one.

        Args:
            query:      Natural-language search query.
            top_k:      Maximum results to return (default 20).
            embed_fn:   Optional callable(str) -> list[float].  When omitted
                        uses self._embed_fn from the constructor.  If neither
                        is available, falls back to search_nodes_fts().
            branch_ids: Optional list of branch IDs to restrict search to.
                        When None all branches are searched.

        Returns:
            List of node dicts (same shape as search_nodes_fts) with an
            extra "relevance" key when embedding search is used.
        """
        fn = embed_fn or self._embed_fn
        if fn is None:
            return self.search_nodes_fts(query, top_k=top_k)

        try:
            query_vec = fn(query)
            scored = self.cosine_search(query_vec, top_k=top_k, source_table="nodes")
            if not scored:
                # No node embeddings yet — fall back to keyword search
                return self.search_nodes_fts(query, top_k=top_k)

            results = []
            for source_id, sim in scored:
                row = self._db.execute(
                    "SELECT id, parent_id, role, content, model, "
                    "provider, timestamp, token_count, metadata "
                    "FROM nodes WHERE id = ?",
                    (source_id,),
                ).fetchone()
                if row is None:
                    continue

                # Optional branch filter: check ancestor chain of each branch head
                if branch_ids is not None:
                    in_branch = False
                    for bid in branch_ids:
                        head_row = self._db.execute(
                            "SELECT head_node_id FROM branches WHERE id = ?",
                            (bid,),
                        ).fetchone()
                        if head_row and head_row[0]:
                            ancestors = self._dag.get_ancestors(head_row[0])
                            if any(a["id"] == source_id for a in ancestors):
                                in_branch = True
                                break
                    if not in_branch:
                        continue

                node_dict = self._dag._row_to_dict(row)
                node_dict["relevance"] = sim
                results.append(node_dict)

            return results
        except Exception as e:
            print(f"[DAG_MEMORY] semantic_search_nodes failed: {e}", file=sys.stderr)
            return self.search_nodes_fts(query, top_k=top_k)


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def promote_nodes(dag, layer, threshold=0.15, max_promotions=20, kg=None):
    """Scan unpromoted nodes, score with salience_score, promote above threshold.

    When a KnowledgeGraph instance (kg) is provided, Hebbian co-retrieval
    boosting is applied: promoted nodes are linked via strengthen_coretrieval,
    and spreading_activation discovers related context nodes whose IDs are
    stored in promotion metadata.

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
    promoted_node_ids = []  # Track DAG node IDs for Hebbian linking
    try:
        # Fetch timestamp alongside other fields so context records it.
        rows = dag._db.execute(
            "SELECT id, role, content, metadata, timestamp FROM nodes "
            "WHERE role IN ('assistant', 'user') "
            "AND length(content) > 50 "
            "AND metadata NOT LIKE '%\"promoted\": true%' "
            "AND metadata NOT LIKE '%\"promoted\":true%' "
            "ORDER BY timestamp DESC "
            f"LIMIT {max_promotions * 3}"
        ).fetchall()

        for node_id, role, content, meta_json, node_ts in rows:
            if len(promoted) >= max_promotions:
                break

            # Infer tags from content for salience scoring
            tags = _infer_tags(content, role)
            score = salience_score(content, tags)

            if score >= threshold:
                # Build context string including ancestor timestamps
                context_content = _build_promotion_context(dag, node_id)
                promoted_content = content
                if context_content:
                    promoted_content = f"{content}\n\n[Context: {context_content}]"

                # Use spreading activation to find related context nodes
                activation_context = []
                if kg is not None:
                    activation_context = _get_activation_context(kg, node_id)

                # Build metadata with activation context
                promo_metadata = {}
                if activation_context:
                    promo_metadata["activated_context"] = [
                        {
                            "name": a["name"],
                            "activation": round(a["activation"], 4),
                            "hops": a["hops"],
                        }
                        for a in activation_context[:10]  # Cap at 10 context nodes
                    ]

                # Use the node's own timestamp as the context field value
                ts_str = _format_node_timestamp(node_ts)

                result = layer.store(
                    content=promoted_content[:800],
                    tags=f"{tags},source:dag,dag_node:{node_id}",
                    tier=1 if score >= 0.25 else 2,
                    quality_score=score,
                    source_node_id=node_id,
                    context=ts_str,
                    metadata=promo_metadata if promo_metadata else None,
                )
                if result.get("stored"):
                    promoted.append(result["id"])
                    promoted_node_ids.append(node_id)
                    dag.update_metadata(node_id, {"promoted": True})

        # Hebbian co-retrieval: strengthen edges between all co-promoted nodes
        if kg is not None and len(promoted) >= 2:
            try:
                kg.strengthen_coretrieval(promoted)
                # Also link DAG node IDs so future spreading activation
                # can traverse from node IDs to knowledge entry IDs
                kg.strengthen_coretrieval(promoted_node_ids)
            except Exception as e:
                print(f"[DAG_MEMORY] Hebbian co-retrieval failed: {e}", file=sys.stderr)

    except Exception as e:
        print(f"[DAG_MEMORY] promote_nodes failed: {e}", file=sys.stderr)

    return promoted


def _get_activation_context(kg, node_id, max_hops=2, threshold=0.01):
    """Use spreading activation from a node ID to find related context entities.

    Returns list of activated entity dicts: [{"name", "activation", "hops"}, ...]
    Fail-open: returns empty list on any error.
    """
    try:
        activated = kg.spreading_activation(
            seed_entities=[node_id],
            max_hops=max_hops,
            threshold=threshold,
        )
        return activated
    except Exception:
        return []


def _format_node_timestamp(ts):
    """Convert a node's integer Unix timestamp to an ISO-8601 string.

    Returns empty string if ts is None or non-numeric.
    """
    if ts is None:
        return ""
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(int(ts)))
    except (ValueError, TypeError, OSError):
        return str(ts)


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
    """Get a few ancestor messages for context around a promoted node.

    Each ancestor entry now includes a formatted timestamp so promoted
    knowledge records carry temporal provenance.
    """
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
            ts_str = _format_node_timestamp(a.get("timestamp"))
            ts_prefix = f" @{ts_str}" if ts_str else ""
            context_parts.append(f"[{a['role']}{ts_prefix}] {content}")
        return " | ".join(context_parts)
    except Exception:
        return ""
