"""LanceCollection — LanceDB table wrapper with ChromaDB-compatible API.

Extracted from memory_server.py as part of Memory v2 Layered Redesign.

Public API:
    from shared.lance_collection import LanceCollection, lance_retry
"""

import sys
import time

import pyarrow as pa


def lance_retry(fn, retries=3, base_delay=0.1):
    """Retry a LanceDB write operation on OSError (file lock contention).

    Exponential backoff: 0.1s, 0.3s, 0.9s (1.3s max total).
    Only catches OSError — other exceptions propagate immediately.
    """
    for attempt in range(retries):
        try:
            return fn()
        except OSError:
            if attempt < retries - 1:
                delay = base_delay * (3**attempt)
                time.sleep(delay)
            else:
                raise


class LanceCollection:
    """LanceDB table wrapper with a familiar API surface.

    Provides query, get, upsert, update, delete, count methods.

    LanceDB cosine distance: 0 = identical, 2 = opposite (range 0-2).
    No conversion needed — distance semantics match directly.

    Args:
        table: LanceDB table object
        schema: PyArrow schema for the table
        name: Table name (for logging)
        embed_text: Callable(str) -> list[float] (single text embedding)
        embed_texts: Callable(list[str]) -> list[list[float]] (batch embedding)
        embedding_dim: Embedding dimensionality (default 768)
    """

    def __init__(
        self, table, schema, name, embed_text=None, embed_texts=None, embedding_dim=768
    ):
        self._table = table
        self._schema = schema
        self._name = name
        self._embed_text = embed_text
        self._embed_texts = embed_texts
        self._embedding_dim = embedding_dim
        # Build set of known column names for metadata handling
        self._has_vector_256 = "vector_256" in {f.name for f in schema}
        if self._has_vector_256:
            v256_field = schema.field("vector_256")
            self._vector_256_dim = (
                v256_field.type.list_size
                if hasattr(v256_field.type, "list_size")
                else 256
            )
        else:
            self._vector_256_dim = 256
        self._meta_cols = {f.name for f in schema} - {
            "id",
            "text",
            "vector",
            "vector_256",
        }

    def count(self):
        """Return number of rows in the table."""
        try:
            return self._table.count_rows()
        except Exception:
            return 0

    def query(
        self, query_texts=None, n_results=5, include=None, where=None, query_vector=None
    ):
        """Semantic search. Returns nested results.

        Result format: {"ids": [[...]], "documents": [[...]], "metadatas": [[...]], "distances": [[...]]}

        Args:
            query_vector: Pre-computed embedding vector. Skips embed_text if provided.
        """
        if include is None:
            include = ["metadatas", "distances"]
        if query_vector is not None:
            vector = query_vector
        else:
            text = query_texts[0] if query_texts else ""
            vector = (
                self._embed_text(text)
                if self._embed_text
                else [0.0] * self._embedding_dim
            )

        try:
            q = self._table.search(vector).distance_type("cosine").limit(n_results)
            if where:
                sql_where = self._translate_where(where)
                if sql_where:
                    q = q.where(sql_where, prefilter=True)
            rows = q.to_list()
        except Exception:
            rows = []

        ids = [[r["id"] for r in rows]]
        result = {"ids": ids}

        if "documents" in include:
            result["documents"] = [[r.get("text", "") for r in rows]]
        if "distances" in include:
            result["distances"] = [[r.get("_distance", 1.0) for r in rows]]
        if "metadatas" in include:
            result["metadatas"] = [[self._row_to_meta(r) for r in rows]]
        if "embeddings" in include:
            result["embeddings"] = [[r.get("vector", []) for r in rows]]

        return result

    def query_approximate(
        self, query_vector_256, n_candidates=50, where=None, nprobes=10
    ):
        """Stage 1: Fast approximate search on vector_256 column.

        Returns raw row dicts with full metadata + 768-dim vector for Stage 2
        reranking. Does NOT update retrieval_count.

        Falls back to flat scan on vector_256 (no index) if IVF not built yet.
        """
        if not self._has_vector_256:
            # Fallback: use full vector query, return as flat rows
            result = self.query(
                query_vector=query_vector_256
                + [0.0] * (self._embedding_dim - len(query_vector_256)),
                n_results=n_candidates,
                where=where,
                include=["metadatas", "distances", "embeddings"],
            )
            rows = []
            ids = result.get("ids", [[]])[0]
            metas = result.get("metadatas", [[]])[0]
            dists = result.get("distances", [[]])[0]
            vecs = result.get("embeddings", [[]])[0]
            for i, rid in enumerate(ids):
                row = {"id": rid, "_distance": dists[i] if i < len(dists) else 1.0}
                if i < len(metas):
                    row.update(metas[i])
                if i < len(vecs):
                    row["vector"] = vecs[i]
                rows.append(row)
            return rows

        try:
            q = (
                self._table.search(query_vector_256, vector_column_name="vector_256")
                .distance_type("cosine")
                .nprobes(nprobes)
                .limit(n_candidates)
            )
            if where:
                sql_where = self._translate_where(where)
                if sql_where:
                    q = q.where(sql_where, prefilter=True)
            return q.to_list()
        except Exception:
            # Index not built yet — fall back to flat scan on vector_256
            try:
                q = (
                    self._table.search(
                        query_vector_256, vector_column_name="vector_256"
                    )
                    .distance_type("cosine")
                    .limit(n_candidates)
                )
                if where:
                    sql_where = self._translate_where(where)
                    if sql_where:
                        q = q.where(sql_where, prefilter=True)
                return q.to_list()
            except Exception:
                return []

    @staticmethod
    def _sanitize_id(i):
        """Escape single quotes to prevent filter injection."""
        return str(i).replace("'", "''")

    def get(self, ids=None, where=None, limit=None, offset=0, include=None):
        """Fetch by IDs or filter. Returns flat results.

        Result format: {"ids": [...], "documents": [...], "metadatas": [...]}
        """
        if include is None:
            include = ["metadatas", "documents"]

        try:
            if ids is not None and len(ids) > 0:
                # Fetch by specific IDs
                escaped = ", ".join(f"'{self._sanitize_id(i)}'" for i in ids)
                sql = f"id IN ({escaped})"
                rows = (
                    self._table.search()
                    .where(sql, prefilter=True)
                    .limit(len(ids) + 10)
                    .to_list()
                )
                # Preserve requested order
                id_order = {i: idx for idx, i in enumerate(ids)}
                rows.sort(key=lambda r: id_order.get(r["id"], 999999))
            elif where:
                sql_where = self._translate_where(where)
                q = self._table.search().where(sql_where, prefilter=True)
                if limit:
                    q = q.limit(limit)
                else:
                    q = q.limit(10000)  # practical cap
                rows = q.to_list()
            elif limit:
                rows = self._table.search().limit(limit).to_list()
                if offset and offset > 0:
                    rows = rows[offset:]
            else:
                rows = self._table.search().limit(10000).to_list()
        except Exception:
            rows = []

        result = {"ids": [r["id"] for r in rows]}

        if "documents" in include:
            result["documents"] = [r.get("text", "") for r in rows]
        if "metadatas" in include:
            result["metadatas"] = [self._row_to_meta(r) for r in rows]
        if "embeddings" in include:
            result["embeddings"] = [r.get("vector", []) for r in rows]

        return result

    def upsert(self, documents=None, metadatas=None, ids=None, vectors=None):
        """Upsert records using LanceDB merge_insert.

        Args:
            vectors: Pre-computed embedding vectors. Skips embed_texts if provided.
        """
        if not ids or not documents:
            return
        records = []
        if vectors is None:
            vectors = (
                self._embed_texts(documents)
                if self._embed_texts
                else [[0.0] * self._embedding_dim for _ in documents]
            )
        for i, doc_id in enumerate(ids):
            doc = documents[i] if i < len(documents) else ""
            meta = metadatas[i] if metadatas and i < len(metadatas) else {}
            record = self._build_record(doc_id, doc, vectors[i], meta)
            records.append(record)

        try:
            lance_retry(
                lambda: (
                    self._table.merge_insert("id")
                    .when_matched_update_all()
                    .when_not_matched_insert_all()
                    .execute(records)
                )
            )
        except Exception as e:
            # Fallback: try add (for new tables or if merge_insert fails)
            try:
                self._table.add(records)
            except Exception as e2:
                print(
                    f"[Lance] upsert failed for {self._name}: merge_insert={e}, add={e2}",
                    file=sys.stderr,
                )
                raise RuntimeError(f"upsert failed for {self._name}: {e}") from e

    def update(self, ids=None, metadatas=None, documents=None):
        """Update metadata and/or documents for existing records.

        API: collection.update(ids=[...], metadatas=[...], documents=[...])
        LanceDB: fetch existing, merge, re-upsert (merge_insert pattern).
        """
        if not ids:
            return
        try:
            # Fetch existing records
            escaped = ", ".join(f"'{self._sanitize_id(i)}'" for i in ids)
            existing = (
                self._table.search()
                .where(f"id IN ({escaped})", prefilter=True)
                .limit(len(ids) + 10)
                .to_list()
            )
            existing_map = {r["id"]: r for r in existing}

            records = []
            for i, doc_id in enumerate(ids):
                old = existing_map.get(doc_id, {})
                meta = metadatas[i] if metadatas and i < len(metadatas) else {}
                doc = (
                    documents[i]
                    if documents and i < len(documents)
                    else old.get("text", "")
                )
                vector = old.get("vector", [0.0] * self._embedding_dim)

                # If document changed, re-embed
                if (
                    documents
                    and i < len(documents)
                    and documents[i] != old.get("text", "")
                ):
                    vector = (
                        self._embed_text(documents[i]) if self._embed_text else vector
                    )

                # Merge: old metadata + new metadata
                merged_meta = self._row_to_meta(old)
                merged_meta.update(meta)

                record = self._build_record(doc_id, doc, vector, merged_meta)
                records.append(record)

            if records:
                lance_retry(
                    lambda: (
                        self._table.merge_insert("id")
                        .when_matched_update_all()
                        .when_not_matched_insert_all()
                        .execute(records)
                    )
                )
        except Exception as e:
            print(f"[Lance] update failed for {self._name}: {e}", file=sys.stderr)

    def delete(self, ids=None):
        """Delete records by IDs."""
        if not ids:
            return
        try:
            escaped = ", ".join(f"'{self._sanitize_id(i)}'" for i in ids)
            lance_retry(lambda: self._table.delete(f"id IN ({escaped})"))
        except Exception as e:
            print(f"[Lance] delete failed for {self._name}: {e}", file=sys.stderr)

    def _build_record(self, doc_id, text, vector, meta):
        """Build a typed record dict matching the Arrow schema."""
        record = {
            "id": str(doc_id),
            "text": str(text) if text else "",
            "vector": vector
            if vector and len(vector) == self._embedding_dim
            else [0.0] * self._embedding_dim,
        }
        # Auto-derive vector_256 via Matryoshka prefix truncation
        if self._has_vector_256:
            full_vec = record["vector"]
            dim = self._vector_256_dim
            record["vector_256"] = (
                full_vec[:dim] if len(full_vec) >= dim else [0.0] * dim
            )
        # Fill metadata columns from schema
        for col_name in self._meta_cols:
            field = self._schema.field(col_name)
            val = meta.get(col_name)
            if pa.types.is_float64(field.type):
                try:
                    record[col_name] = float(val) if val is not None else 0.0
                except (ValueError, TypeError):
                    record[col_name] = 0.0
            elif pa.types.is_int32(field.type):
                try:
                    record[col_name] = int(val) if val is not None else 0
                except (ValueError, TypeError):
                    record[col_name] = 0
            else:
                record[col_name] = str(val) if val is not None else ""
        return record

    def _row_to_meta(self, row):
        """Extract metadata dict from a LanceDB row (exclude id, text, vector, _distance)."""
        meta = {}
        for col_name in self._meta_cols:
            val = row.get(col_name)
            if val is not None:
                meta[col_name] = val
        return meta

    @staticmethod
    def _translate_where(where):
        """Translate where-clause dict to a LanceDB SQL filter string.

        Examples:
            {"session_time": {"$lt": 123.4}} → "session_time < 123.4"
            {"error_hash": "abc"} → "error_hash = 'abc'"
            {"$and": [...]} → "(clause1) AND (clause2)"
        """
        if not where or not isinstance(where, dict):
            return ""

        parts = []
        for key, val in where.items():
            if key == "$and":
                sub_parts = []
                for sub in val:
                    translated = LanceCollection._translate_where(sub)
                    if translated:
                        sub_parts.append(f"({translated})")
                if sub_parts:
                    parts.append(" AND ".join(sub_parts))
            elif key == "$or":
                sub_parts = []
                for sub in val:
                    translated = LanceCollection._translate_where(sub)
                    if translated:
                        sub_parts.append(f"({translated})")
                if sub_parts:
                    parts.append(" OR ".join(sub_parts))
            elif isinstance(val, dict):
                # Operator clause: {"$lt": X}, {"$gte": X}, etc.
                op_map = {
                    "$lt": "<",
                    "$lte": "<=",
                    "$gt": ">",
                    "$gte": ">=",
                    "$eq": "=",
                    "$ne": "!=",
                }
                for op, sql_op in op_map.items():
                    if op in val:
                        v = val[op]
                        if isinstance(v, str):
                            parts.append(f"{key} {sql_op} '{v}'")
                        else:
                            parts.append(f"{key} {sql_op} {v}")
            else:
                # Exact match: {"error_hash": "abc"}
                if isinstance(val, str):
                    parts.append(f"{key} = '{val}'")
                else:
                    parts.append(f"{key} = {val}")

        return " AND ".join(parts)
