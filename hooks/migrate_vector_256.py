#!/usr/bin/env python3
"""One-time migration: backfill vector_256 + compact + build IVF index.

Run: python ~/.claude/hooks/migrate_vector_256.py
"""

import os
import sys
import time

LANCE_DIR = os.path.expanduser("~/data/memory/lancedb")


def migrate():
    import lancedb
    import pyarrow as pa

    db = lancedb.connect(LANCE_DIR)
    tables = ["knowledge", "observations", "fix_outcomes", "web_pages", "quarantine"]

    for name in tables:
        try:
            tbl = db.open_table(name)
        except Exception as e:
            print(f"[SKIP] {name}: {e}")
            continue

        row_count = tbl.count_rows()
        cols = set(tbl.schema.names)
        print(f"\n=== {name} ({row_count} rows) ===")

        # Step 1: Add or fix vector_256 column
        import pyarrow as _pa

        needs_create = "vector_256" not in cols
        if not needs_create:
            # Check for type mismatch (e.g. string instead of list)
            v256_type = tbl.schema.field("vector_256").type
            if not _pa.types.is_list(v256_type):
                print(f"  vector_256 has wrong type ({v256_type}), dropping...")
                tbl.drop_columns(["vector_256"])
                needs_create = True
            else:
                print(f"  vector_256 already exists with correct type")
        if needs_create:
            print(f"  Adding vector_256 column...")
            try:
                pdf = tbl.to_pandas()
                pdf["vector_256"] = pdf["vector"].apply(
                    lambda v: (
                        v[:256] if v is not None and len(v) >= 256 else [0.0] * 256
                    )
                )
                db.create_table(name, data=pdf, mode="overwrite")
                tbl = db.open_table(name)
                print(f"  Recreated table with correct vector_256 ({row_count} rows)")
            except Exception as e2:
                print(f"  FAILED: {e2}")
                continue

        # Step 2: Compact fragments
        print(f"  Compacting...")
        t0 = time.time()
        try:
            stats = tbl.compact_files()
            print(f"  Compacted in {time.time() - t0:.1f}s: {stats}")
        except Exception as e:
            print(f"  Compact failed: {e}")

        try:
            tbl.cleanup_old_versions(older_than=None)
            print(f"  Cleaned old versions")
        except Exception as e:
            print(f"  Cleanup failed: {e}")

        # Step 3: Build IVF_PQ index (knowledge and observations only — others too small)
        if name in ("knowledge", "observations") and row_count >= 256:
            print(f"  Building IVF_PQ index on vector_256...")
            t0 = time.time()
            num_partitions = max(4, int(row_count**0.5))
            try:
                tbl.create_index(
                    metric="cosine",
                    num_partitions=num_partitions,
                    num_sub_vectors=16,
                    vector_column_name="vector_256",
                    index_type="IVF_PQ",
                    replace=True,
                )
                print(
                    f"  Index built in {time.time() - t0:.1f}s (partitions={num_partitions})"
                )
            except Exception as e:
                print(f"  Index build failed: {e}")

    print("\n=== Migration complete ===")


if __name__ == "__main__":
    migrate()
