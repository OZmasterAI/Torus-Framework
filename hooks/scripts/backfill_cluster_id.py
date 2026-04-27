"""Backfill cluster_id for knowledge entries missing it.

Reads embeddings from LanceDB, assigns clusters via ClusterStore,
writes back in batches. Server must be STOPPED before running.

Usage:
    python3 backfill_cluster_id.py [--dry-run]
"""

import os
import sys
import time
import signal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import lancedb
from shared.cluster_store import ClusterStore

MEMORY_DIR = os.path.join(os.path.expanduser("~"), "data", "memory")
LANCE_DIR = os.path.join(MEMORY_DIR, "lancedb")
CLUSTERS_DB = os.path.join(MEMORY_DIR, "clusters.db")
PID_FILE = "/tmp/backfill_cluster_id.pid"

_stop = False


def _handle_signal(sig, frame):
    global _stop
    sys.stderr.write("\nCaught signal, finishing current batch then stopping...\n")
    _stop = True


def backfill(dry_run=False):
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    try:
        _run(dry_run)
    finally:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)


def _run(dry_run):
    global _stop

    db = lancedb.connect(LANCE_DIR)
    tbl = db.open_table("knowledge")

    sys.stderr.write("Loading knowledge rows...\n")
    df = tbl.to_pandas()
    total = len(df)

    missing = df[df["cluster_id"].isna() | (df["cluster_id"] == "")]
    sys.stderr.write(
        f"Total: {total}, Already assigned: {total - len(missing)}, Missing: {len(missing)}\n"
    )

    if len(missing) == 0:
        sys.stderr.write("Nothing to backfill.\n")
        return

    cs = ClusterStore(CLUSTERS_DB)
    sys.stderr.write(f"ClusterStore loaded from {CLUSTERS_DB}\n")

    updates = {}
    skipped = 0
    t0 = time.time()

    for idx, (_, row) in enumerate(missing.iterrows()):
        if _stop:
            sys.stderr.write(f"Stopped by signal after {idx} rows.\n")
            break

        vec = row.get("vector")
        if vec is None or (hasattr(vec, "__len__") and len(vec) == 0):
            skipped += 1
            continue

        vec_arr = np.array(vec, dtype=np.float32)
        if vec_arr.shape[0] != 4096:
            skipped += 1
            continue

        cid = cs.assign(vec_arr.tolist(), str(row.get("text", "")))
        if cid:
            updates[row["id"]] = cid

        if (idx + 1) % 200 == 0:
            elapsed = time.time() - t0
            rate = (idx + 1) / elapsed
            remaining = (len(missing) - idx - 1) / rate if rate > 0 else 0
            sys.stderr.write(
                f"  [{idx + 1}/{len(missing)}] {len(updates)} assigned, {skipped} skipped, {rate:.0f} rows/s, ~{remaining:.0f}s left\n"
            )

    sys.stderr.write(
        f"\nScan complete: {len(updates)} to update, {skipped} skipped (no/wrong-dim vector)\n"
    )

    if dry_run:
        sys.stderr.write("DRY RUN — no writes.\n")
        unique_clusters = len(set(updates.values()))
        sys.stderr.write(
            f"Would assign {len(updates)} rows across {unique_clusters} clusters.\n"
        )
        return

    if not updates:
        return

    # Use native LanceDB update — row-by-row SET on the column, no vector rewrite
    sys.stderr.write(f"Writing {len(updates)} updates via native table.update()...\n")
    written = 0
    errors = 0
    for doc_id, cid in updates.items():
        if _stop:
            sys.stderr.write(f"Stopped by signal after writing {written} rows.\n")
            break
        try:
            safe_id = doc_id.replace("'", "''")
            tbl.update(where=f"id = '{safe_id}'", values={"cluster_id": cid})
            written += 1
        except Exception as e:
            errors += 1
            if errors <= 3:
                sys.stderr.write(f"  Error on {doc_id}: {e}\n")
        if written % 500 == 0 and written > 0:
            elapsed = time.time() - t0
            sys.stderr.write(f"  Written {written}/{len(updates)} ({errors} errors)\n")

    elapsed = time.time() - t0
    unique_clusters = len(set(updates.values()))
    sys.stderr.write(
        f"Done: {written} rows assigned to {unique_clusters} clusters in {elapsed:.1f}s ({errors} errors)\n"
    )


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    backfill(dry_run=dry)
