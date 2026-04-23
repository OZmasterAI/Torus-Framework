#!/usr/bin/env python3
"""Migrate LanceDB from nomic-embed-text-v2-moe (768-dim) to all-MiniLM-L6-v2 (384-dim).

Reads all rows from the backup, re-embeds text with MiniLM, writes new 384-dim tables.

Usage:
    python3 migrate_to_minilm.py [--backup-dir PATH] [--lance-dir PATH] [--batch-size N]
"""

import argparse
import os
import sys
import time

import lancedb
import numpy as np
import pyarrow as pa

# --------------------------------------------------------------------------
# Schemas (384-dim) — must match memory_server.py
# --------------------------------------------------------------------------
DIM = 384

_KNOWLEDGE_SCHEMA = pa.schema(
    [
        pa.field("id", pa.string()),
        pa.field("text", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), DIM)),
        pa.field("vector_256", pa.list_(pa.float32(), 256)),
        pa.field("context", pa.string()),
        pa.field("tags", pa.string()),
        pa.field("timestamp", pa.string()),
        pa.field("session_time", pa.float64()),
        pa.field("preview", pa.string()),
        pa.field("primary_source", pa.string()),
        pa.field("related_urls", pa.string()),
        pa.field("source_method", pa.string()),
        pa.field("tier", pa.int32()),
        pa.field("retrieval_count", pa.int32()),
        pa.field("last_retrieved", pa.string()),
        pa.field("source_session_id", pa.string()),
        pa.field("source_observation_ids", pa.string()),
        pa.field("cluster_id", pa.string()),
        pa.field("memory_type", pa.string()),
        pa.field("state_type", pa.string()),
        pa.field("quality_score", pa.float64()),
    ]
)

_FIX_OUTCOMES_SCHEMA = pa.schema(
    [
        pa.field("id", pa.string()),
        pa.field("text", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), DIM)),
        pa.field("vector_256", pa.list_(pa.float32(), 256)),
        pa.field("error_hash", pa.string()),
        pa.field("strategy_id", pa.string()),
        pa.field("chain_id", pa.string()),
        pa.field("outcome", pa.string()),
        pa.field("confidence", pa.string()),
        pa.field("attempts", pa.string()),
        pa.field("successes", pa.string()),
        pa.field("timestamp", pa.string()),
        pa.field("last_outcome_time", pa.string()),
        pa.field("banned", pa.string()),
        pa.field("bridged", pa.string()),
    ]
)

_OBSERVATIONS_SCHEMA = pa.schema(
    [
        pa.field("id", pa.string()),
        pa.field("text", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), DIM)),
        pa.field("vector_256", pa.list_(pa.float32(), 256)),
        pa.field("session_id", pa.string()),
        pa.field("tool_name", pa.string()),
        pa.field("timestamp", pa.string()),
        pa.field("session_time", pa.float64()),
        pa.field("has_error", pa.string()),
        pa.field("error_pattern", pa.string()),
        pa.field("preview", pa.string()),
    ]
)

_WEB_PAGES_SCHEMA = pa.schema(
    [
        pa.field("id", pa.string()),
        pa.field("text", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), DIM)),
        pa.field("vector_256", pa.list_(pa.float32(), 256)),
        pa.field("url", pa.string()),
        pa.field("title", pa.string()),
        pa.field("chunk_index", pa.string()),
        pa.field("total_chunks", pa.string()),
        pa.field("indexed_at", pa.string()),
        pa.field("content_hash", pa.string()),
        pa.field("word_count", pa.string()),
    ]
)

_QUARANTINE_SCHEMA = pa.schema(
    [
        pa.field("id", pa.string()),
        pa.field("text", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), DIM)),
        pa.field("vector_256", pa.list_(pa.float32(), 256)),
        pa.field("quarantine_reason", pa.string()),
        pa.field("quarantine_pair", pa.string()),
        pa.field("quarantined_at", pa.string()),
        pa.field("context", pa.string()),
        pa.field("tags", pa.string()),
        pa.field("timestamp", pa.string()),
        pa.field("session_time", pa.float64()),
        pa.field("preview", pa.string()),
    ]
)

TABLE_SCHEMAS = {
    "knowledge": _KNOWLEDGE_SCHEMA,
    "fix_outcomes": _FIX_OUTCOMES_SCHEMA,
    "observations": _OBSERVATIONS_SCHEMA,
    "web_pages": _WEB_PAGES_SCHEMA,
    "quarantine": _QUARANTINE_SCHEMA,
}


def migrate(backup_dir: str, lance_dir: str, batch_size: int = 64):
    import torch

    torch.set_num_threads(4)
    from sentence_transformers import SentenceTransformer

    print(f"Loading all-MiniLM-L6-v2...")
    model = SentenceTransformer("all-MiniLM-L6-v2")

    print(f"Opening backup: {backup_dir}")
    old_db = lancedb.connect(backup_dir)
    old_tables = old_db.table_names()
    print(f"Found tables: {old_tables}")

    # Remove old lance dir contents (not the backup)
    if os.path.exists(lance_dir):
        import shutil

        for item in os.listdir(lance_dir):
            path = os.path.join(lance_dir, item)
            if os.path.isdir(path) and path.endswith(".lance"):
                shutil.rmtree(path)
                print(f"Removed old table: {item}")

    new_db = lancedb.connect(lance_dir)
    zero_256 = [0.0] * 256

    total_migrated = 0
    t_start = time.time()

    for table_name in old_tables:
        if table_name not in TABLE_SCHEMAS:
            print(f"Skipping unknown table: {table_name}")
            continue

        schema = TABLE_SCHEMAS[table_name]
        old_table = old_db.open_table(table_name)
        row_count = old_table.count_rows()
        print(f"\n--- {table_name}: {row_count} rows ---")

        if row_count == 0:
            new_db.create_table(table_name, schema=schema)
            print(f"  Created empty table")
            continue

        # Read only non-vector columns (skip 768-dim vectors — massive I/O savings)
        non_vector_cols = [
            f.name for f in schema if f.name not in ("vector", "vector_256")
        ]
        df = old_table.to_pandas(columns=non_vector_cols)

        # Get text column for re-embedding
        texts = df["text"].fillna("").tolist()

        # Batch embed
        print(f"  Embedding {len(texts)} texts in batches of {batch_size}...")
        t0 = time.time()
        all_vectors = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            vecs = model.encode(batch, show_progress_bar=False)
            all_vectors.extend(vecs.tolist())
            if (i + batch_size) % (batch_size * 10) == 0:
                print(f"    {i + len(batch)}/{len(texts)}")
        elapsed = time.time() - t0
        print(f"  Embedded in {elapsed:.1f}s ({len(texts) / elapsed:.0f} rows/s)")

        # Build new dataframe with 384-dim vectors
        df["vector"] = all_vectors
        df["vector_256"] = [zero_256] * len(df)

        # Ensure schema-compatible types
        schema_fields = {f.name for f in schema}
        # Drop columns not in new schema
        for col in list(df.columns):
            if col not in schema_fields:
                df = df.drop(columns=[col])

        # Create new table
        new_db.create_table(table_name, data=df, schema=schema, mode="overwrite")
        total_migrated += row_count
        print(f"  Written {row_count} rows")

    elapsed_total = time.time() - t_start
    print(
        f"\n=== Migration complete: {total_migrated} rows in {elapsed_total:.1f}s ==="
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--backup-dir",
        default=os.path.expanduser("~/data/memory/lancedb_backup_768dim"),
    )
    parser.add_argument(
        "--lance-dir", default=os.path.expanduser("~/data/memory/lancedb")
    )
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args()
    migrate(args.backup_dir, args.lance_dir, args.batch_size)
