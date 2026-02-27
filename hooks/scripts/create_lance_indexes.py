#!/usr/bin/env python3
"""Create vector indexes on LanceDB tables for fast ANN search."""

import lancedb
import math
import time

LANCE_PATH = "~/data/memory/lancedb"

def main():
    db = lancedb.connect(LANCE_PATH)

    tables_to_index = {
        "knowledge":    1402,
        "fix_outcomes":  264,
        "observations": 4579,
    }

    for name, expected_rows in tables_to_index.items():
        tbl = db.open_table(name)
        rows = tbl.count_rows()
        print(f"\n--- {name} ({rows} rows) ---")

        if rows < 256:
            num_partitions = max(1, rows // 16)
            num_sub_vectors = 16
        elif rows < 1000:
            num_partitions = 4
            num_sub_vectors = 16
        else:
            num_partitions = max(4, int(math.sqrt(rows)))
            num_sub_vectors = 24

        print(f"  Creating IVF_PQ index: partitions={num_partitions}, sub_vectors={num_sub_vectors}")

        start = time.time()
        try:
            tbl.create_index(
                metric="cosine",
                num_partitions=num_partitions,
                num_sub_vectors=num_sub_vectors,
                vector_column_name="vector",
            )
            elapsed = time.time() - start
            print(f"  Index created in {elapsed:.1f}s")
        except Exception as e:
            print(f"  Index creation failed: {e}")
            try:
                print(f"  Retrying with fewer partitions...")
                tbl.create_index(
                    metric="cosine",
                    num_partitions=min(4, rows),
                    num_sub_vectors=16,
                    vector_column_name="vector",
                )
                elapsed = time.time() - start
                print(f"  Index created (retry) in {elapsed:.1f}s")
            except Exception as e2:
                print(f"  Retry also failed: {e2}")

    print("\n--- Index verification ---")
    for name in tables_to_index:
        tbl = db.open_table(name)
        indices = tbl.list_indices()
        print(f"  {name}: {indices}")

    print("\nDone.")

if __name__ == "__main__":
    main()
