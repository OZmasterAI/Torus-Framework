#!/usr/bin/env python3
"""Full re-embedding of all LanceDB memory tables with nomic-embed-text-v2-moe.

Unifies the vector space (gte + nomic → all nomic), fixes zero vectors,
backfills quality_score on knowledge table, adds embedding_model tracking.

Usage:
    python3 scripts/reembed_all_memories.py --dry-run    # preview only
    python3 scripts/reembed_all_memories.py --write       # actually re-embed

Tables processed: knowledge, fix_outcomes, observations, web_pages
Backup created automatically before any writes.
"""

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime

import numpy as np

# Paths
MEMORY_DIR = os.path.join(os.path.expanduser("~"), "data", "memory")
LANCE_DIR = os.path.join(MEMORY_DIR, "lancedb")
BACKUP_DIR = os.path.join(
    MEMORY_DIR, "backups", f"pre_reembed_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
)

EMBEDDING_MODEL = "nomic-ai/nomic-embed-text-v2-moe"
EMBEDDING_DIM = 768
BATCH_SIZE = 64  # Texts per embedding batch

TABLES = ["knowledge", "fix_outcomes", "observations", "web_pages"]

# Add shared modules to path for quality scoring
sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "hooks"))


def load_model():
    """Load the SentenceTransformer embedding model."""
    import torch

    torch.set_num_threads(4)
    torch.set_num_interop_threads(2)
    from sentence_transformers import SentenceTransformer

    print(f"Loading embedding model: {EMBEDDING_MODEL}...")
    model = SentenceTransformer(EMBEDDING_MODEL, trust_remote_code=True)
    print(f"Model loaded. Device: {model.device}")
    return model


def embed_batch(model, texts):
    """Embed a batch of texts. Returns list of 768-dim vectors."""
    vectors = model.encode(texts, show_progress_bar=False, batch_size=BATCH_SIZE)
    return [v.tolist() for v in vectors]


def backup_lancedb():
    """Create a full backup of LanceDB before modifying."""
    print(f"Backing up LanceDB to: {BACKUP_DIR}")
    os.makedirs(os.path.dirname(BACKUP_DIR), exist_ok=True)
    shutil.copytree(LANCE_DIR, BACKUP_DIR)
    print(f"Backup complete: {BACKUP_DIR}")


def compute_quality_scores(texts):
    """Compute quality scores for a list of texts. Returns list of floats."""
    try:
        from shared.memory_quality import quality_score

        return [quality_score(t) for t in texts]
    except ImportError:
        print("WARNING: shared.memory_quality not available, skipping quality scoring")
        return [0.5] * len(texts)


def analyze_table(db, table_name):
    """Analyze a table's current embedding state."""
    tbl = db.open_table(table_name)
    df = tbl.to_pandas()
    total = len(df)

    if total == 0:
        return {"total": 0, "zero_vectors": 0, "text_col": "text"}

    vecs = np.array(df["vector"].tolist())
    zero_count = sum(1 for v in vecs if np.allclose(v, 0))

    # Norm stats
    norms = np.linalg.norm(vecs, axis=1)
    nonzero_norms = norms[norms > 0.01]

    return {
        "total": total,
        "zero_vectors": zero_count,
        "norm_mean": float(nonzero_norms.mean()) if len(nonzero_norms) > 0 else 0,
        "norm_std": float(nonzero_norms.std()) if len(nonzero_norms) > 0 else 0,
    }


def reembed_table(db, model, table_name, dry_run=False):
    """Re-embed all rows in a LanceDB table."""
    tbl = db.open_table(table_name)
    df = tbl.to_pandas()
    total = len(df)

    if total == 0:
        print(f"  {table_name}: empty, skipping")
        return 0

    texts = df["text"].tolist()
    ids = df["id"].tolist()

    # Replace None/NaN texts with empty string
    texts = [t if isinstance(t, str) and t else "" for t in texts]

    print(f"  {table_name}: {total} rows — embedding in batches of {BATCH_SIZE}...")

    if dry_run:
        print(f"  [DRY RUN] Would re-embed {total} rows")
        return total

    # Embed in batches
    all_vectors = []
    for i in range(0, total, BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        vectors = embed_batch(model, batch)
        all_vectors.extend(vectors)
        done = min(i + BATCH_SIZE, total)
        print(f"    Embedded {done}/{total} ({done * 100 // total}%)")

    # Quality scoring for knowledge table
    quality_scores = None
    if table_name == "knowledge":
        print(f"  Computing quality scores for {total} entries...")
        quality_scores = compute_quality_scores(texts)
        below_threshold = sum(1 for q in quality_scores if q < 0.3)
        print(f"  Quality scores: {below_threshold}/{total} below threshold (0.3)")

    # Update vectors in LanceDB using merge_insert (upsert by id)
    print(f"  Writing updated vectors to LanceDB...")

    import pyarrow as pa

    # Build update dataframe with id + new vector + metadata
    update_data = {
        "id": ids,
        "vector": all_vectors,
    }

    # New columns are added directly in the rebuilt Arrow table below.
    # No add_columns() calls needed — avoids concurrent commit conflicts with MCP server.
    if table_name == "knowledge" and quality_scores is not None:
        update_data["quality_score"] = quality_scores
        update_data["embedding_model"] = [EMBEDDING_MODEL] * total
    else:
        update_data["embedding_model"] = [EMBEDDING_MODEL] * total

    # Use row-by-row update for vectors (LanceDB update() supports SQL-like where clauses)
    # More efficient: delete all + re-add with updated vectors
    # Safest: build full rows and overwrite table

    # Strategy: read all data, replace vectors, drop+recreate table
    for col in df.columns:
        if col not in update_data:
            update_data[col] = df[col].tolist()

    # Convert vectors to proper format
    vector_array = pa.FixedSizeListArray.from_arrays(
        pa.array([v for vec in all_vectors for v in vec], type=pa.float32()),
        list_size=EMBEDDING_DIM,
    )

    # Build full Arrow table
    fields = []
    arrays = []
    for col in list(df.columns):
        if col == "vector":
            fields.append(pa.field("vector", pa.list_(pa.float32(), EMBEDDING_DIM)))
            arrays.append(vector_array)
        else:
            fields.append(pa.field(col, tbl.schema.field(col).type))
            arrays.append(pa.array(update_data[col], type=tbl.schema.field(col).type))

    # Add new columns
    if table_name == "knowledge" and quality_scores is not None:
        if "quality_score" not in df.columns:
            fields.append(pa.field("quality_score", pa.float64()))
            arrays.append(pa.array(quality_scores, type=pa.float64()))
        if "embedding_model" not in df.columns:
            fields.append(pa.field("embedding_model", pa.string()))
            arrays.append(pa.array([EMBEDDING_MODEL] * total, type=pa.string()))
    if table_name != "knowledge" and "embedding_model" not in df.columns:
        fields.append(pa.field("embedding_model", pa.string()))
        arrays.append(pa.array([EMBEDDING_MODEL] * total, type=pa.string()))

    new_table = pa.table(arrays, schema=pa.schema(fields))

    # Drop and recreate (atomic within LanceDB)
    db.drop_table(table_name)
    db.create_table(table_name, new_table)

    print(f"  {table_name}: {total} rows re-embedded successfully")
    return total


def main():
    parser = argparse.ArgumentParser(description="Re-embed all LanceDB memory tables")
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview only, no changes"
    )
    parser.add_argument(
        "--write", action="store_true", help="Actually perform re-embedding"
    )
    parser.add_argument(
        "--tables", nargs="+", default=TABLES, help="Tables to process (default: all)"
    )
    parser.add_argument(
        "--skip-backup", action="store_true", help="Skip backup (not recommended)"
    )
    args = parser.parse_args()

    if not args.dry_run and not args.write:
        print("ERROR: Must specify --dry-run or --write")
        print("  --dry-run   Preview what would happen")
        print("  --write     Actually re-embed (creates backup first)")
        sys.exit(1)

    import lancedb

    db = lancedb.connect(LANCE_DIR)

    # Phase 1: Analyze current state
    print("=" * 60)
    print("PHASE 1: Analyzing current embedding state")
    print("=" * 60)
    total_rows = 0
    total_zeros = 0
    for table_name in args.tables:
        stats = analyze_table(db, table_name)
        total_rows += stats["total"]
        total_zeros += stats["zero_vectors"]
        print(
            f"  {table_name}: {stats['total']} rows, {stats['zero_vectors']} zero vectors"
            + (
                f", norm mean={stats['norm_mean']:.4f} std={stats['norm_std']:.4f}"
                if stats["total"] > 0
                else ""
            )
        )

    print(f"\n  TOTAL: {total_rows} rows, {total_zeros} zero vectors to fix")
    print(f"  Model: {EMBEDDING_MODEL} ({EMBEDDING_DIM}-dim)")

    if args.dry_run:
        print(
            f"\n  [DRY RUN] Would re-embed {total_rows} rows across {len(args.tables)} tables"
        )
        print(f"  Estimated time: ~{total_rows // 100} minutes on CPU")
        return

    # Phase 2: Backup
    print()
    print("=" * 60)
    print("PHASE 2: Backup")
    print("=" * 60)
    if not args.skip_backup:
        backup_lancedb()
    else:
        print("  Backup skipped (--skip-backup)")

    # Phase 3: Load model
    print()
    print("=" * 60)
    print("PHASE 3: Load embedding model")
    print("=" * 60)
    model = load_model()

    # Phase 4: Re-embed each table
    print()
    print("=" * 60)
    print("PHASE 4: Re-embedding")
    print("=" * 60)
    start = time.time()
    total_done = 0
    for table_name in args.tables:
        t0 = time.time()
        count = reembed_table(db, model, table_name, dry_run=False)
        elapsed = time.time() - t0
        total_done += count
        print(f"  {table_name} done in {elapsed:.1f}s")
        print()

    total_elapsed = time.time() - start
    print("=" * 60)
    print(f"COMPLETE: {total_done} rows re-embedded in {total_elapsed:.1f}s")
    print(f"Backup at: {BACKUP_DIR}")
    print("=" * 60)

    # Phase 5: Verify
    print()
    print("PHASE 5: Verification")
    print("=" * 60)
    # Reconnect to verify
    db = lancedb.connect(LANCE_DIR)
    for table_name in args.tables:
        stats = analyze_table(db, table_name)
        status = (
            "OK"
            if stats["zero_vectors"] == 0
            else f"WARN: {stats['zero_vectors']} zero vectors remain"
        )
        print(f"  {table_name}: {stats['total']} rows, {status}")

    # Verify knowledge quality_score column
    if "knowledge" in args.tables:
        tbl = db.open_table("knowledge")
        df = tbl.to_pandas()
        if "quality_score" in df.columns:
            has_qs = df["quality_score"].notna().sum()
            print(f"  knowledge: {has_qs}/{len(df)} have quality_score")
        if "embedding_model" in df.columns:
            models = df["embedding_model"].value_counts().to_dict()
            print(f"  knowledge: embedding_model distribution: {models}")

    print("\nDone. Restart MCP server to use new embeddings.")


if __name__ == "__main__":
    main()
