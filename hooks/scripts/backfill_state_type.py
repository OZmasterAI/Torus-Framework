"""Backfill state_type for existing knowledge entries.

Classifies memories as 'ephemeral', 'conceptual', or '' (unclassified)
using deterministic keyword scanner. Part of C-lite Final (Rule 5b upgrade).

Usage:
    python3 backfill_state_type.py [--dry-run]
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import lancedb
from shared.memory_classification import classify_state_type
from shared.lance_collection import LanceCollection

MEMORY_DIR = os.path.join(os.path.expanduser("~"), "data", "memory")
LANCE_DIR = os.path.join(MEMORY_DIR, "lancedb")

BATCH_SIZE = 50


def backfill(dry_run=False):
    db = lancedb.connect(LANCE_DIR)
    tbl = db.open_table("knowledge")
    df = tbl.to_pandas()
    schema = tbl.schema
    col = LanceCollection(tbl, schema, "knowledge")

    counts = {"ephemeral": 0, "conceptual": 0, "": 0}
    updates = []

    for _, row in df.iterrows():
        current = row.get("state_type", "")
        if current:
            counts[current] = counts.get(current, 0) + 1
            continue
        new_type = classify_state_type(
            str(row.get("text", "")), str(row.get("tags", ""))
        )
        counts[new_type] += 1
        if new_type:
            updates.append({"id": row["id"], "state_type": new_type})

    already = sum(1 for _, r in df.iterrows() if r.get("state_type", ""))
    sys.stderr.write(f"Already classified: {already}\n")
    sys.stderr.write(
        f"Ephemeral: {counts['ephemeral']}, Conceptual: {counts['conceptual']}, Unclassified: {counts['']}\n"
    )
    sys.stderr.write(f"Would update: {len(updates)} entries\n")

    if updates and not dry_run:
        for i in range(0, len(updates), BATCH_SIZE):
            batch = updates[i : i + BATCH_SIZE]
            ids = [u["id"] for u in batch]
            metas = [{"state_type": u["state_type"]} for u in batch]
            col.update(ids=ids, metadatas=metas)
            sys.stderr.write(
                f"  Batch {i // BATCH_SIZE + 1}: updated {len(batch)} entries\n"
            )
        sys.stderr.write(f"Updated {len(updates)} entries total\n")
    elif dry_run:
        sys.stderr.write("(dry run — no changes made)\n")


if __name__ == "__main__":
    backfill(dry_run="--dry-run" in sys.argv)
