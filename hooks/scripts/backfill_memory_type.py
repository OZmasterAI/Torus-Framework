"""Backfill memory_type for existing knowledge entries.

Classifies unclassified memories as 'reference' or 'working'
using the same rules applied to new memories.

Usage:
    python backfill_memory_type.py [--dry-run]
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import lancedb
import pyarrow as pa
from shared.memory_classification import classify_memory_type

MEMORY_DIR = os.path.join(os.path.expanduser("~"), "data", "memory")
LANCE_DIR = os.path.join(MEMORY_DIR, "lancedb")


def backfill(dry_run=False):
    db = lancedb.connect(LANCE_DIR)
    tbl = db.open_table("knowledge")
    df = tbl.to_pandas()

    counts = {"reference": 0, "working": 0, "": 0}
    updates = []

    for _, row in df.iterrows():
        current = row.get("memory_type", "")
        if current:  # already classified
            counts[current] = counts.get(current, 0) + 1
            continue
        new_type = classify_memory_type(
            str(row.get("text", "")), str(row.get("tags", ""))
        )
        counts[new_type] += 1
        if new_type:
            updates.append({"id": row["id"], "memory_type": new_type})

    print(
        f"Already classified: {sum(1 for _, r in df.iterrows() if r.get('memory_type', ''))}"
    )
    print(
        f"Reference: {counts['reference']}, Working: {counts['working']}, Unclassified: {counts['']}"
    )
    print(f"Would update: {len(updates)} entries")

    if updates and not dry_run:
        update_tbl = pa.table(
            {
                "id": [u["id"] for u in updates],
                "memory_type": [u["memory_type"] for u in updates],
            }
        )
        tbl.merge(update_tbl, left_on="id", right_on="id")
        print(f"Updated {len(updates)} entries")
    elif dry_run:
        print("(dry run — no changes made)")


if __name__ == "__main__":
    backfill(dry_run="--dry-run" in sys.argv)
