"""SurrealCollection — SurrealDB table wrapper with ChromaDB-compatible API.

Replaces LanceCollection. Uses SurrealDB embedded (surrealkv://) backend.
"""

from surrealdb import RecordID

_EMBEDDING_DIM = 4096

TABLE_SCHEMAS = {
    "knowledge": {
        "text": "string",
        "vector": "array<float>",
        "context": "string",
        "tags": "string",
        "timestamp": "string",
        "session_time": "float",
        "preview": "string",
        "primary_source": "string",
        "related_urls": "string",
        "source_method": "string",
        "tier": "int",
        "retrieval_count": "int",
        "last_retrieved": "string",
        "source_session_id": "string",
        "source_observation_ids": "string",
        "cluster_id": "string",
        "memory_type": "string",
        "state_type": "string",
        "quality_score": "float",
    },
    "fix_outcomes": {
        "text": "string",
        "vector": "array<float>",
        "error_hash": "string",
        "strategy_id": "string",
        "chain_id": "string",
        "outcome": "string",
        "confidence": "string",
        "attempts": "string",
        "successes": "string",
        "timestamp": "string",
        "last_outcome_time": "string",
        "banned": "string",
        "bridged": "string",
    },
    "observations": {
        "text": "string",
        "vector": "array<float>",
        "session_id": "string",
        "tool_name": "string",
        "timestamp": "string",
        "session_time": "float",
        "has_error": "string",
        "error_pattern": "string",
        "preview": "string",
    },
    "web_pages": {
        "text": "string",
        "vector": "array<float>",
        "url": "string",
        "title": "string",
        "chunk_index": "string",
        "total_chunks": "string",
        "indexed_at": "string",
        "content_hash": "string",
        "word_count": "string",
    },
    "quarantine": {
        "text": "string",
        "vector": "array<float>",
        "quarantine_reason": "string",
        "quarantine_pair": "string",
        "quarantined_at": "string",
        "context": "string",
        "tags": "string",
        "timestamp": "string",
        "session_time": "float",
        "preview": "string",
    },
    "clusters": {
        "centroid": "array<float>",
        "member_count": "int",
        "label": "string",
        "created_at": "string",
        "updated_at": "string",
    },
}


def init_surreal_db(
    db, embed_text=None, embed_texts=None, embedding_dim=_EMBEDDING_DIM
):
    db.query(
        "DEFINE ANALYZER IF NOT EXISTS mem_analyzer "
        "TOKENIZERS blank,class FILTERS lowercase,snowball(english)"
    )
    collections = {}
    for table_name, fields in TABLE_SCHEMAS.items():
        vec_field = "vector" if table_name != "clusters" else "centroid"
        coll = SurrealCollection(
            db=db,
            table_name=table_name,
            fields=fields,
            embed_text=embed_text,
            embed_texts=embed_texts,
            embedding_dim=embedding_dim,
            vector_field=vec_field,
        )
        coll.init_indexes()
        collections[table_name] = coll
    return collections


class SurrealCollection:
    def __init__(
        self,
        db,
        table_name,
        fields=None,
        embed_text=None,
        embed_texts=None,
        embedding_dim=4096,
        vector_field="vector",
    ):
        self._db = db
        self._name = table_name
        self._fields = fields or {}
        self._embed_text = embed_text
        self._embed_texts = embed_texts
        self._embedding_dim = embedding_dim
        self._vector_field = vector_field
        self._meta_cols = set(self._fields.keys()) - {"id", "text", vector_field}
        self._initialized = False

    def _ensure_table(self):
        if self._initialized:
            return
        self._db.query(f"DEFINE TABLE IF NOT EXISTS {self._name} SCHEMALESS")
        self._initialized = True

    def init_indexes(self):
        self._ensure_table()
        vf = self._vector_field
        import time as _time

        for _attempt in range(3):
            try:
                self._db.query(
                    f"DEFINE INDEX IF NOT EXISTS {self._name}_vec ON {self._name} FIELDS {vf} "
                    f"HNSW DIMENSION {self._embedding_dim} TYPE F32 DIST COSINE EFC 150 M 12"
                )
                if "text" in self._fields:
                    self._db.query(
                        "DEFINE ANALYZER IF NOT EXISTS mem_analyzer "
                        "TOKENIZERS blank,class FILTERS lowercase,snowball(english)"
                    )
                    self._db.query(
                        f"DEFINE INDEX IF NOT EXISTS {self._name}_fts ON {self._name} FIELDS text "
                        "FULLTEXT ANALYZER mem_analyzer BM25(1.2, 0.75)"
                    )
                break
            except Exception as e:
                if "retry" in str(e).lower() and _attempt < 2:
                    _time.sleep(2)
                    continue
                raise

    def count(self):
        try:
            r = self._db.query(f"SELECT count() FROM {self._name} GROUP ALL")
            if r and isinstance(r, list) and len(r) > 0:
                return r[0].get("count", 0)
            return 0
        except Exception:
            return 0

    def upsert(self, ids=None, documents=None, metadatas=None, vectors=None):
        if not ids or not documents:
            return
        self._ensure_table()

        if vectors is None:
            vectors = (
                self._embed_texts(documents)
                if self._embed_texts
                else [[0.0] * self._embedding_dim for _ in documents]
            )

        for i, doc_id in enumerate(ids):
            doc = documents[i] if i < len(documents) else ""
            vec = vectors[i] if i < len(vectors) else [0.0] * self._embedding_dim
            meta = metadatas[i] if metadatas and i < len(metadatas) else {}

            vf = self._vector_field
            params = {"vec": vec}
            set_clauses = [f"{vf} = $vec"]
            if "text" in self._fields:
                params["text"] = doc
                set_clauses.append("text = $text")

            for col in self._meta_cols:
                if col in meta:
                    param_name = f"m_{col}"
                    params[param_name] = meta[col]
                    set_clauses.append(f"{col} = ${param_name}")
                elif col not in ("text", vf):
                    field_type = self._fields.get(col, "string")
                    if field_type == "int":
                        set_clauses.append(f"{col} = 0")
                    elif field_type == "float":
                        set_clauses.append(f"{col} = 0.0")
                    else:
                        set_clauses.append(f"{col} = ''")

            safe_id = str(doc_id).replace("'", "")
            set_str = ", ".join(set_clauses)
            self._db.query(f"UPSERT {self._name}:`{safe_id}` SET {set_str}", params)

    def get(
        self, ids=None, where=None, limit=None, offset=0, include=None, columns=None
    ):
        if include is None:
            include = ["metadatas", "documents"]

        try:
            if ids is not None and len(ids) > 0:
                rows = []
                for doc_id in ids:
                    safe_id = str(doc_id).replace("'", "")
                    r = self._db.query(f"SELECT * FROM {self._name}:`{safe_id}`")
                    if r:
                        rows.extend(r)
            elif where:
                sql_where = self._translate_where(where)
                lim = limit or 10000
                r = self._db.query(
                    f"SELECT * FROM {self._name} WHERE {sql_where} LIMIT {lim}"
                )
                rows = r if r else []
            elif limit:
                r = self._db.query(
                    f"SELECT * FROM {self._name} LIMIT {limit} START {offset}"
                )
                rows = r if r else []
            else:
                r = self._db.query(f"SELECT * FROM {self._name} LIMIT 10000")
                rows = r if r else []
        except Exception:
            rows = []

        result = {"ids": [self._extract_id(r) for r in rows]}

        if "documents" in include:
            result["documents"] = [r.get("text", "") for r in rows]
        if "metadatas" in include:
            result["metadatas"] = [self._row_to_meta(r) for r in rows]
        if "embeddings" in include:
            result["embeddings"] = [r.get("vector", []) for r in rows]

        return result

    def update(self, ids=None, metadatas=None, documents=None):
        if not ids:
            return
        for i, doc_id in enumerate(ids):
            meta = metadatas[i] if metadatas and i < len(metadatas) else {}
            doc = documents[i] if documents and i < len(documents) else None

            set_parts = []
            params = {}
            for col, val in meta.items():
                param_name = f"m_{col}"
                params[param_name] = val
                set_parts.append(f"{col} = ${param_name}")

            if doc is not None:
                params["text"] = doc
                set_parts.append("text = $text")
                if self._embed_text:
                    params["vec"] = self._embed_text(doc)
                    set_parts.append("vector = $vec")

            if set_parts:
                safe_id = str(doc_id).replace("'", "")
                set_str = ", ".join(set_parts)
                self._db.query(f"UPDATE {self._name}:`{safe_id}` SET {set_str}", params)

    def delete(self, ids=None):
        if not ids:
            return
        for doc_id in ids:
            safe_id = str(doc_id).replace("'", "")
            self._db.query(f"DELETE {self._name}:`{safe_id}`")

    def query(
        self, query_texts=None, n_results=5, include=None, where=None, query_vector=None
    ):
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

        where_clause = ""
        if where:
            translated = self._translate_where(where)
            if translated:
                where_clause = f"AND {translated}"

        vf = self._vector_field
        try:
            rows = self._db.query(
                f"SELECT *, vector::distance::knn() AS dist "
                f"FROM {self._name} WHERE {vf} <|{n_results}, COSINE|> $vec "
                f"{where_clause} ORDER BY dist ASC",
                {"vec": vector},
            )
        except Exception:
            rows = []

        ids = [[self._extract_id(r) for r in rows]]
        result = {"ids": ids}

        if "documents" in include:
            result["documents"] = [[r.get("text", "") for r in rows]]
        if "distances" in include:
            result["distances"] = [[r.get("dist", 1.0) for r in rows]]
        if "metadatas" in include:
            result["metadatas"] = [[self._row_to_meta(r) for r in rows]]
        if "embeddings" in include:
            result["embeddings"] = [[r.get("vector", []) for r in rows]]

        return result

    def keyword_search(self, query_text, top_k=5):
        try:
            rows = self._db.query(
                f"SELECT *, search::score(1) AS score FROM {self._name} "
                f"WHERE text @1@ $q ORDER BY score DESC LIMIT {top_k}",
                {"q": query_text},
            )
        except Exception:
            rows = []

        return [
            {
                "id": self._extract_id(r),
                "text": r.get("text", ""),
                "score": r.get("score", 0.0),
                **self._row_to_meta(r),
            }
            for r in rows
            if r.get("score", 0.0) != 0.0
        ]

    def tag_search(self, tags_list, match_all=False, top_k=200):
        if not tags_list:
            return []
        params = {}
        conditions = []
        for i, tag in enumerate(tags_list):
            key = f"t{i}"
            conditions.append(f"tags CONTAINS ${key}")
            params[key] = tag.strip()
        joiner = " AND " if match_all else " OR "
        where = joiner.join(conditions)
        try:
            rows = self._db.query(
                f"SELECT id FROM {self._name} WHERE {where} LIMIT {top_k}",
                params,
            )
        except Exception:
            return []
        return [self._extract_id(r) for r in rows]

    def _extract_id(self, row):
        rid = row.get("id")
        if rid is None:
            return ""
        if isinstance(rid, RecordID):
            return str(rid.id)
        return str(rid).split(":", 1)[-1] if ":" in str(rid) else str(rid)

    def _row_to_meta(self, row):
        meta = {}
        for col in self._meta_cols:
            val = row.get(col)
            if val is not None:
                meta[col] = val
        return meta

    @staticmethod
    def _translate_where(where):
        if not where or not isinstance(where, dict):
            return ""
        parts = []
        for key, val in where.items():
            if key == "$and":
                sub = [SurrealCollection._translate_where(s) for s in val]
                sub = [s for s in sub if s]
                if sub:
                    parts.append("(" + " AND ".join(f"({s})" for s in sub) + ")")
            elif key == "$or":
                sub = [SurrealCollection._translate_where(s) for s in val]
                sub = [s for s in sub if s]
                if sub:
                    parts.append("(" + " OR ".join(f"({s})" for s in sub) + ")")
            elif isinstance(val, dict):
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
                if isinstance(val, str):
                    parts.append(f"{key} = '{val}'")
                else:
                    parts.append(f"{key} = {val}")
        return " AND ".join(parts)
