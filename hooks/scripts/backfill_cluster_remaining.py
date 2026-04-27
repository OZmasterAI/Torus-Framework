"""Finish backfilling cluster_id for remaining rows.

Batches updates per cluster_id (one UPDATE per cluster, not per row)
to minimize LanceDB version fragmentation.

Usage: python3 backfill_cluster_remaining.py
"""

import sys
import os
import numpy as np
import lancedb

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.cluster_store import ClusterStore

MEMORY_DIR = os.path.join(os.path.expanduser("~"), "data", "memory")
LANCE_DIR = os.path.join(MEMORY_DIR, "lancedb")
CLUSTERS_DB = os.path.join(MEMORY_DIR, "clusters.db")


def run():
    db = lancedb.connect(LANCE_DIR)
    tbl = db.open_table("knowledge")
    cs = ClusterStore(CLUSTERS_DB)

    sys.stderr.write("Loading...\n")
    df = tbl.to_pandas()
    missing = df[df["cluster_id"].isna() | (df["cluster_id"] == "")]
    sys.stderr.write(f"Missing: {len(missing)}\n")

    if len(missing) == 0:
        sys.stderr.write("Nothing to backfill.\n")
        return

    assignments = {}
    for _, row in missing.iterrows():
        vec = row.get("vector")
        if vec is None:
            continue
        vec_arr = np.array(vec, dtype=np.float32)
        if vec_arr.shape[0] != 4096:
            continue
        cid = cs.assign(vec_arr.tolist(), str(row.get("text", "")))
        if cid:
            assignments.setdefault(cid, []).append(row["id"])

    total = sum(len(v) for v in assignments.values())
    sys.stderr.write(f"Assignments: {total} rows across {len(assignments)} clusters\n")

    written = 0
    errors = 0
    for cid, ids in assignments.items():
        try:
            id_list = ", ".join(
                f"'{i.replace(chr(39), chr(39) + chr(39))}'" for i in ids
            )
            tbl.update(where=f"id IN ({id_list})", values={"cluster_id": cid})
            written += len(ids)
        except Exception as e:
            errors += len(ids)
            if errors <= 15:
                sys.stderr.write(f"  Error ({len(ids)} rows): {e}\n")
        if written % 100 == 0 and written > 0:
            sys.stderr.write(f"  {written}/{total} rows done\n")

    sys.stderr.write(f"Done: {written} written, {errors} errors\n")


if __name__ == "__main__":
    run()
