#!/usr/bin/env python3
"""Backup all LanceDB tables to JSON.

Exports documents, metadatas, embeddings, and IDs for all 5 tables.
Run manually: python3 hooks/scripts/backup_embeddings.py

Output: ~/data/memory/backup_lance_YYYYMMDD.json
"""

import json
import os
import sys
from datetime import datetime

# Add hooks dir to path for shared imports
HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOKS_DIR)

MEMORY_DIR = os.path.join(os.path.expanduser("~"), "data", "memory")
LANCE_DIR = os.path.join(MEMORY_DIR, "lancedb")
TABLE_NAMES = ["knowledge", "fix_outcomes", "observations", "web_pages", "quarantine"]


def main():
    try:
        import lancedb
    except ImportError:
        print("ERROR: lancedb not installed")
        sys.exit(1)

    if not os.path.isdir(LANCE_DIR):
        print(f"ERROR: LanceDB directory not found: {LANCE_DIR}")
        sys.exit(1)

    db = lancedb.connect(LANCE_DIR)
    existing_tables = set(db.table_names())
    backup = {}
    total_docs = 0

    for name in TABLE_NAMES:
        try:
            if name not in existing_tables:
                backup[name] = {"count": 0, "ids": [], "documents": [], "metadatas": [], "embeddings": []}
                print(f"  {name}: 0 entries (table not found)")
                continue

            tbl = db.open_table(name)
            count = tbl.count_rows()
            if count == 0:
                backup[name] = {"count": 0, "ids": [], "documents": [], "metadatas": [], "embeddings": []}
                print(f"  {name}: 0 entries (empty)")
                continue

            # Read all rows
            rows = tbl.to_pandas()
            all_ids = rows["id"].tolist()
            all_docs = rows["text"].tolist() if "text" in rows.columns else [""] * count

            # Extract metadata (all columns except id, text, vector)
            meta_cols = [c for c in rows.columns if c not in ("id", "text", "vector")]
            all_metas = []
            for _, row in rows.iterrows():
                meta = {}
                for col in meta_cols:
                    val = row[col]
                    if val is not None:
                        meta[col] = val if not hasattr(val, 'item') else val.item()
                all_metas.append(meta)

            # Extract embeddings
            all_embs = []
            if "vector" in rows.columns:
                for vec in rows["vector"]:
                    if vec is not None:
                        all_embs.append([float(v) for v in vec])
                    else:
                        all_embs.append([])

            backup[name] = {
                "count": count,
                "ids": all_ids,
                "documents": all_docs,
                "metadatas": all_metas,
                "embeddings": all_embs,
            }
            total_docs += count
            valid_embs = sum(1 for e in all_embs if e)
            emb_dim = len(all_embs[0]) if all_embs and all_embs[0] else 0
            print(f"  {name}: {count} entries, {valid_embs} embeddings ({emb_dim}-dim)")
        except Exception as e:
            print(f"  {name}: SKIP ({e})")
            backup[name] = {"error": str(e)}

    # Write backup
    date_str = datetime.now().strftime("%Y%m%d")
    backup_path = os.path.join(MEMORY_DIR, f"backup_lance_{date_str}.json")

    with open(backup_path, "w") as f:
        json.dump(backup, f)

    size_mb = os.path.getsize(backup_path) / (1024 * 1024)
    print(f"\nBackup saved: {backup_path}")
    print(f"Total: {total_docs} documents, {size_mb:.1f} MB")


if __name__ == "__main__":
    print("LanceDB Embedding Backup")
    print("=" * 40)
    main()
