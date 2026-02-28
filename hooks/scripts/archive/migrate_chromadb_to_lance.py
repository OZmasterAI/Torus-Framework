#!/usr/bin/env python3
"""
migrate_chromadb_to_lance.py
----------------------------
Standalone migration script: exports all 5 ChromaDB collections and imports
them into LanceDB tables.

Run with MCP server STOPPED:
    python3 /home/crab/.claude/hooks/scripts/migrate_chromadb_to_lance.py

ChromaDB source : ~/data/memory/          (PersistentClient)
LanceDB target  : ~/data/memory/lancedb/  (subdirectory)

Collections migrated
--------------------
    knowledge       -> knowledge      table
    fix_outcomes    -> fix_outcomes   table
    observations    -> observations   table
    web_pages       -> web_pages      table
    quarantine      -> quarantine     table

Embedding model  : nomic-ai/nomic-embed-text-v2-moe (768-dim)
"""

from __future__ import annotations

import os
import sys
import json
import random
import datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
HOME = Path.home()
CHROMA_PATH = HOME / "data" / "memory"
LANCE_PATH  = HOME / "data" / "memory" / "lancedb"
MARKER_FILE = LANCE_PATH / ".migration_complete"
BATCH_SIZE  = 50
EMBED_DIM   = 768

# ---------------------------------------------------------------------------
# Lazy imports — print friendly error if a library is missing
# ---------------------------------------------------------------------------
def _import_chromadb():
    try:
        import chromadb
        return chromadb
    except ImportError:
        print("ERROR: chromadb not installed.  pip install chromadb", file=sys.stderr)
        sys.exit(1)

def _import_lancedb():
    try:
        import lancedb
        return lancedb
    except ImportError:
        print("ERROR: lancedb not installed.  pip install lancedb", file=sys.stderr)
        sys.exit(1)

def _import_pyarrow():
    try:
        import pyarrow as pa
        return pa
    except ImportError:
        print("ERROR: pyarrow not installed.  pip install pyarrow", file=sys.stderr)
        sys.exit(1)

def _import_sentence_transformer():
    try:
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer
    except ImportError:
        print("ERROR: sentence-transformers not installed.  pip install sentence-transformers",
              file=sys.stderr)
        sys.exit(1)

# ---------------------------------------------------------------------------
# Arrow schema definitions
# ---------------------------------------------------------------------------
def _build_schemas(pa) -> dict[str, Any]:
    vec_type = pa.list_(pa.float32(), EMBED_DIM)

    knowledge_schema = pa.schema([
        pa.field("id",              pa.string()),
        pa.field("text",            pa.string()),
        pa.field("vector",          vec_type),
        pa.field("context",         pa.string()),
        pa.field("tags",            pa.string()),
        pa.field("timestamp",       pa.string()),
        pa.field("session_time",    pa.float64()),
        pa.field("preview",         pa.string()),
        pa.field("primary_source",  pa.string()),
        pa.field("related_urls",    pa.string()),
        pa.field("source_method",   pa.string()),
        pa.field("tier",            pa.int32()),
        pa.field("retrieval_count", pa.int32()),
        pa.field("last_retrieved",  pa.string()),
    ])

    fix_outcomes_schema = pa.schema([
        pa.field("id",               pa.string()),
        pa.field("text",             pa.string()),
        pa.field("vector",           vec_type),
        pa.field("error_hash",       pa.string()),
        pa.field("strategy_id",      pa.string()),
        pa.field("chain_id",         pa.string()),
        pa.field("outcome",          pa.string()),
        pa.field("confidence",       pa.string()),
        pa.field("attempts",         pa.string()),
        pa.field("successes",        pa.string()),
        pa.field("timestamp",        pa.string()),
        pa.field("last_outcome_time",pa.string()),
        pa.field("banned",           pa.string()),
        pa.field("bridged",          pa.string()),
    ])

    observations_schema = pa.schema([
        pa.field("id",            pa.string()),
        pa.field("text",          pa.string()),
        pa.field("vector",        vec_type),
        pa.field("session_id",    pa.string()),
        pa.field("tool_name",     pa.string()),
        pa.field("timestamp",     pa.string()),
        pa.field("session_time",  pa.float64()),
        pa.field("has_error",     pa.string()),
        pa.field("error_pattern", pa.string()),
        pa.field("preview",       pa.string()),
    ])

    web_pages_schema = pa.schema([
        pa.field("id",           pa.string()),
        pa.field("text",         pa.string()),
        pa.field("vector",       vec_type),
        pa.field("url",          pa.string()),
        pa.field("title",        pa.string()),
        pa.field("chunk_index",  pa.string()),
        pa.field("total_chunks", pa.string()),
        pa.field("indexed_at",   pa.string()),
        pa.field("content_hash", pa.string()),
        pa.field("word_count",   pa.string()),
    ])

    quarantine_schema = pa.schema([
        pa.field("id",               pa.string()),
        pa.field("text",             pa.string()),
        pa.field("vector",           vec_type),
        pa.field("quarantine_reason",pa.string()),
        pa.field("quarantine_pair",  pa.string()),
        pa.field("quarantined_at",   pa.string()),
        pa.field("context",          pa.string()),
        pa.field("tags",             pa.string()),
        pa.field("timestamp",        pa.string()),
        pa.field("session_time",     pa.float64()),
        pa.field("preview",          pa.string()),
    ])

    return {
        "knowledge":    knowledge_schema,
        "fix_outcomes": fix_outcomes_schema,
        "observations": observations_schema,
        "web_pages":    web_pages_schema,
        "quarantine":   quarantine_schema,
    }

# ---------------------------------------------------------------------------
# Per-collection row builders  (metadata → typed dict matching Arrow schema)
# ---------------------------------------------------------------------------
def _s(meta: dict, key: str) -> str:
    """Safe string getter with empty-string default."""
    val = meta.get(key, "")
    if val is None:
        return ""
    return str(val)

def _f(meta: dict, key: str) -> float:
    """Safe float getter with 0.0 default."""
    val = meta.get(key, 0.0)
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0

def _i(meta: dict, key: str) -> int:
    """Safe int getter with 0 default."""
    val = meta.get(key, 0)
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0

def _build_row_knowledge(doc_id: str, text: str, vector: list[float], meta: dict) -> dict:
    return {
        "id":              doc_id,
        "text":            text or "",
        "vector":          vector,
        "context":         _s(meta, "context"),
        "tags":            _s(meta, "tags"),
        "timestamp":       _s(meta, "timestamp"),
        "session_time":    _f(meta, "session_time"),
        "preview":         _s(meta, "preview"),
        "primary_source":  _s(meta, "primary_source"),
        "related_urls":    _s(meta, "related_urls"),
        "source_method":   _s(meta, "source_method"),
        "tier":            _i(meta, "tier"),
        "retrieval_count": _i(meta, "retrieval_count"),
        "last_retrieved":  _s(meta, "last_retrieved"),
    }

def _build_row_fix_outcomes(doc_id: str, text: str, vector: list[float], meta: dict) -> dict:
    return {
        "id":                doc_id,
        "text":              text or "",
        "vector":            vector,
        "error_hash":        _s(meta, "error_hash"),
        "strategy_id":       _s(meta, "strategy_id"),
        "chain_id":          _s(meta, "chain_id"),
        "outcome":           _s(meta, "outcome"),
        "confidence":        _s(meta, "confidence"),
        "attempts":          _s(meta, "attempts"),
        "successes":         _s(meta, "successes"),
        "timestamp":         _s(meta, "timestamp"),
        "last_outcome_time": _s(meta, "last_outcome_time"),
        "banned":            _s(meta, "banned"),
        "bridged":           _s(meta, "bridged"),
    }

def _build_row_observations(doc_id: str, text: str, vector: list[float], meta: dict) -> dict:
    return {
        "id":            doc_id,
        "text":          text or "",
        "vector":        vector,
        "session_id":    _s(meta, "session_id"),
        "tool_name":     _s(meta, "tool_name"),
        "timestamp":     _s(meta, "timestamp"),
        "session_time":  _f(meta, "session_time"),
        "has_error":     _s(meta, "has_error"),
        "error_pattern": _s(meta, "error_pattern"),
        "preview":       _s(meta, "preview"),
    }

def _build_row_web_pages(doc_id: str, text: str, vector: list[float], meta: dict) -> dict:
    return {
        "id":           doc_id,
        "text":         text or "",
        "vector":       vector,
        "url":          _s(meta, "url"),
        "title":        _s(meta, "title"),
        "chunk_index":  _s(meta, "chunk_index"),
        "total_chunks": _s(meta, "total_chunks"),
        "indexed_at":   _s(meta, "indexed_at"),
        "content_hash": _s(meta, "content_hash"),
        "word_count":   _s(meta, "word_count"),
    }

def _build_row_quarantine(doc_id: str, text: str, vector: list[float], meta: dict) -> dict:
    return {
        "id":                doc_id,
        "text":              text or "",
        "vector":            vector,
        "quarantine_reason": _s(meta, "quarantine_reason"),
        "quarantine_pair":   _s(meta, "quarantine_pair"),
        "quarantined_at":    _s(meta, "quarantined_at"),
        "context":           _s(meta, "context"),
        "tags":              _s(meta, "tags"),
        "timestamp":         _s(meta, "timestamp"),
        "session_time":      _f(meta, "session_time"),
        "preview":           _s(meta, "preview"),
    }

_ROW_BUILDERS = {
    "knowledge":    _build_row_knowledge,
    "fix_outcomes": _build_row_fix_outcomes,
    "observations": _build_row_observations,
    "web_pages":    _build_row_web_pages,
    "quarantine":   _build_row_quarantine,
}

# ---------------------------------------------------------------------------
# Zero vector helper
# ---------------------------------------------------------------------------
def _zero_vector() -> list[float]:
    return [0.0] * EMBED_DIM

# ---------------------------------------------------------------------------
# Export one ChromaDB collection in batches
# ---------------------------------------------------------------------------
def export_collection(chroma_coll, name: str) -> list[dict]:
    """
    Fetch all documents from a ChromaDB collection in BATCH_SIZE chunks.
    Returns a list of raw result dicts (each covering one batch).
    """
    total = chroma_coll.count()
    print(f"  [{name}] total documents in ChromaDB: {total}")
    if total == 0:
        return []

    all_ids:        list[str]         = []
    all_documents:  list[str]         = []
    all_metadatas:  list[dict]        = []
    all_embeddings: list[list[float]] = []

    offset = 0
    while offset < total:
        limit = min(BATCH_SIZE, total - offset)
        batch = chroma_coll.get(
            limit=limit,
            offset=offset,
            include=["embeddings", "documents", "metadatas"],
        )
        ids_batch   = batch.get("ids") or []
        docs_batch  = batch.get("documents") or []
        meta_batch  = batch.get("metadatas") or []
        emb_raw     = batch.get("embeddings")
        emb_batch   = emb_raw if emb_raw is not None else []

        all_ids.extend(ids_batch)
        all_documents.extend(docs_batch)
        all_metadatas.extend(meta_batch)
        all_embeddings.extend(emb_batch)

        fetched = len(ids_batch)
        offset += fetched
        print(f"  [{name}]   fetched {offset}/{total} …", end="\r", flush=True)

        # Guard against infinite loop if ChromaDB returns 0 in a bad state
        if fetched == 0:
            print(f"\n  [{name}] WARNING: ChromaDB returned 0 items at offset {offset}, stopping.")
            break

    print()  # newline after \r progress
    return list(zip(all_ids, all_documents, all_metadatas, all_embeddings))

# ---------------------------------------------------------------------------
# Re-embed any rows that came back with None / empty embedding
# ---------------------------------------------------------------------------
def _ensure_embeddings(
    rows: list[tuple],
    model,
    name: str,
) -> list[tuple]:
    """
    rows is a list of (id, document, metadata, embedding).
    For any entry where embedding is None or empty, re-embed with model.
    """
    needs_embed = [i for i, (_, doc, _, emb) in enumerate(rows)
                   if emb is None or len(emb) == 0]
    if not needs_embed:
        return rows

    print(f"  [{name}] re-embedding {len(needs_embed)} entries with missing vectors …")
    texts_to_embed = [rows[i][1] or "" for i in needs_embed]

    try:
        vectors = model.encode(texts_to_embed, batch_size=32, show_progress_bar=False)
    except Exception as exc:
        print(f"  [{name}] WARNING: re-embed failed ({exc}); filling with zero vectors")
        vectors = [_zero_vector() for _ in needs_embed]

    rows = list(rows)  # make mutable copy
    for idx, vec in zip(needs_embed, vectors):
        doc_id, doc, meta, _ = rows[idx]
        rows[idx] = (doc_id, doc, meta, list(vec) if hasattr(vec, "__iter__") else _zero_vector())

    return rows

# ---------------------------------------------------------------------------
# Import rows into a LanceDB table
# ---------------------------------------------------------------------------
def import_to_lance(
    lance_db,
    name: str,
    schema,
    rows: list[tuple],
    pa,
) -> int:
    """
    Create or overwrite a LanceDB table for the given collection.
    Returns number of rows written.
    """
    if not rows:
        print(f"  [{name}] empty — creating empty table with schema")
        # Create table with zero rows but correct schema
        empty_table = pa.table({field.name: pa.array([], type=field.type)
                                 for field in schema}, schema=schema)
        if name in lance_db.table_names():
            lance_db.drop_table(name)
        lance_db.create_table(name, data=empty_table, schema=schema)
        return 0

    builder = _ROW_BUILDERS[name]
    records: list[dict] = []

    for doc_id, document, metadata, embedding in rows:
        meta = metadata or {}
        vec = list(embedding) if embedding is not None else _zero_vector()
        # Ensure exactly EMBED_DIM floats
        if len(vec) != EMBED_DIM:
            vec = (vec + _zero_vector())[:EMBED_DIM]
        vec = [float(v) for v in vec]
        row = builder(doc_id, document or "", vec, meta)
        records.append(row)

    # Build an Arrow table from the records list
    columns: dict[str, list] = {field.name: [] for field in schema}
    for rec in records:
        for field in schema:
            columns[field.name].append(rec[field.name])

    arrow_arrays = {}
    for field in schema:
        col_data = columns[field.name]
        arrow_arrays[field.name] = pa.array(col_data, type=field.type)

    arrow_table = pa.table(arrow_arrays, schema=schema)

    # Drop and recreate to ensure idempotency
    if name in lance_db.table_names():
        print(f"  [{name}] table already exists — dropping for clean re-import")
        lance_db.drop_table(name)

    lance_db.create_table(name, data=arrow_table, schema=schema)
    print(f"  [{name}] wrote {len(records)} rows to LanceDB")
    return len(records)

# ---------------------------------------------------------------------------
# Validation: count check + 10 random spot-checks
# ---------------------------------------------------------------------------
def validate_table(lance_db, name: str, expected_count: int) -> bool:
    """
    Verify that the LanceDB table has the expected number of rows and
    that 10 randomly sampled entries are non-empty.
    """
    if name not in lance_db.table_names():
        print(f"  [{name}] VALIDATION FAILED: table not found in LanceDB")
        return False

    tbl = lance_db.open_table(name)
    actual = tbl.count_rows()

    if actual != expected_count:
        print(f"  [{name}] VALIDATION FAILED: expected {expected_count} rows, got {actual}")
        return False

    print(f"  [{name}] count check OK: {actual} rows")

    # Spot-check up to 10 random rows
    if actual == 0:
        print(f"  [{name}] spot-check skipped (empty table)")
        return True

    sample_n = min(10, actual)
    try:
        # Fetch all IDs and sample random offsets
        all_rows_df = tbl.to_lance().to_table(columns=["id", "text"]).to_pydict()
        all_ids  = all_rows_df.get("id", [])
        all_text = all_rows_df.get("text", [])
        indices = random.sample(range(len(all_ids)), sample_n)
        failures = 0
        for idx in indices:
            doc_id = all_ids[idx]
            text   = all_text[idx]
            if not doc_id:
                print(f"  [{name}]   spot-check WARN: row {idx} has empty id")
                failures += 1
            # text may legitimately be empty for some collections
        print(f"  [{name}] spot-check OK: {sample_n} rows sampled, {failures} warnings")
    except Exception as exc:
        print(f"  [{name}] spot-check WARNING: could not sample rows ({exc})")

    return True

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    print("=" * 60)
    print("ChromaDB → LanceDB migration")
    print(f"  source : {CHROMA_PATH}")
    print(f"  target : {LANCE_PATH}")
    print("=" * 60)

    # ---- Idempotency guard ---------------------------------------------------
    if MARKER_FILE.exists():
        print(f"\nMarker file found: {MARKER_FILE}")
        print("Migration has already been completed.")
        print("Delete the marker file to re-run:")
        print(f"    rm {MARKER_FILE}")
        return 0

    # ---- Imports ------------------------------------------------------------
    chromadb   = _import_chromadb()
    lancedb    = _import_lancedb()
    pa         = _import_pyarrow()
    STClass    = _import_sentence_transformer()

    # ---- Validate source path -----------------------------------------------
    if not CHROMA_PATH.exists():
        print(f"ERROR: ChromaDB path does not exist: {CHROMA_PATH}", file=sys.stderr)
        return 1

    # ---- Connect to ChromaDB ------------------------------------------------
    print(f"\nConnecting to ChromaDB at {CHROMA_PATH} …")
    try:
        chroma_client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    except Exception as exc:
        print(f"ERROR: Could not open ChromaDB: {exc}", file=sys.stderr)
        return 1

    # ---- List available collections -----------------------------------------
    existing_names = {c.name for c in chroma_client.list_collections()}
    print(f"Collections found in ChromaDB: {sorted(existing_names)}")

    # ---- Load embedding model (for re-embedding fallback) -------------------
    print(f"\nLoading embedding model nomic-ai/nomic-embed-text-v2-moe …")
    try:
        embed_model = STClass(
            "nomic-ai/nomic-embed-text-v2-moe",
            trust_remote_code=True,
        )
    except Exception as exc:
        print(f"WARNING: Could not load embedding model: {exc}")
        print("         Entries with missing embeddings will receive zero vectors.")
        embed_model = None

    # ---- Prepare LanceDB ----------------------------------------------------
    LANCE_PATH.mkdir(parents=True, exist_ok=True)
    print(f"\nConnecting to LanceDB at {LANCE_PATH} …")
    lance_db = lancedb.connect(str(LANCE_PATH))

    schemas = _build_schemas(pa)

    # ---- Migrate each collection --------------------------------------------
    COLLECTIONS = ["knowledge", "fix_outcomes", "observations", "web_pages", "quarantine"]
    migration_summary: dict[str, dict] = {}

    for coll_name in COLLECTIONS:
        print(f"\n--- {coll_name} ---")

        # Open or skip ChromaDB collection
        if coll_name not in existing_names:
            print(f"  [{coll_name}] not found in ChromaDB — creating empty LanceDB table")
            import_to_lance(lance_db, coll_name, schemas[coll_name], [], pa)
            migration_summary[coll_name] = {"chroma_count": 0, "lance_count": 0, "ok": True}
            continue

        chroma_coll = chroma_client.get_collection(coll_name)

        # Export
        rows = export_collection(chroma_coll, coll_name)
        chroma_count = len(rows)

        # Re-embed any rows missing vectors
        if embed_model is not None:
            rows = _ensure_embeddings(rows, embed_model, coll_name)
        else:
            # Fill None embeddings with zero vectors
            rows = [
                (doc_id, doc, meta, emb if (emb is not None and len(emb) > 0) else _zero_vector())
                for doc_id, doc, meta, emb in rows
            ]

        # Import into LanceDB
        lance_count = import_to_lance(lance_db, coll_name, schemas[coll_name], rows, pa)

        # Validate
        ok = validate_table(lance_db, coll_name, lance_count)
        migration_summary[coll_name] = {
            "chroma_count": chroma_count,
            "lance_count":  lance_count,
            "ok":           ok,
        }

    # ---- Summary -----------------------------------------------------------
    print("\n" + "=" * 60)
    print("Migration Summary")
    print("=" * 60)
    all_ok = True
    for name, info in migration_summary.items():
        status = "OK" if info["ok"] else "FAILED"
        print(f"  {name:<16} chroma={info['chroma_count']:>6}  lance={info['lance_count']:>6}  [{status}]")
        if not info["ok"]:
            all_ok = False

    if all_ok:
        # Write marker file so re-runs are safe
        MARKER_FILE.write_text(
            json.dumps({
                "migrated_at": datetime.datetime.utcnow().isoformat() + "Z",
                "collections": list(migration_summary.keys()),
                "summary":     migration_summary,
            }, indent=2)
        )
        print(f"\nMarker written: {MARKER_FILE}")
        print("Migration COMPLETE.")
        return 0
    else:
        print("\nMigration completed with ERRORS — marker file NOT written.")
        print("Fix the issues above and re-run.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
