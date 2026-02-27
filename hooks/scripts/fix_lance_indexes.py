#!/usr/bin/env python3
"""Drop IVF_PQ indexes that are hurting relevance on small tables.

For datasets under ~10K rows, brute-force cosine scan is both faster
and more accurate than IVF_PQ. LanceDB falls back to flat scan
when no index exists.
"""

import lancedb

LANCE_PATH = "~/data/memory/lancedb"

def main():
    db = lancedb.connect(LANCE_PATH)

    for name in ["knowledge", "fix_outcomes", "observations"]:
        tbl = db.open_table(name)
        indices = tbl.list_indices()
        print(f"{name}: {indices}")

        for idx in indices:
            idx_name = idx.name if hasattr(idx, "name") else str(idx)
            print(f"  Dropping index '{idx_name}'...")
            try:
                tbl.drop_index(idx_name)
                print(f"  Dropped.")
            except Exception as e:
                print(f"  Drop failed: {e}")

        # Verify
        remaining = tbl.list_indices()
        print(f"  Remaining indices: {remaining}")

    print("\nDone — tables now use brute-force flat scan.")

if __name__ == "__main__":
    main()
