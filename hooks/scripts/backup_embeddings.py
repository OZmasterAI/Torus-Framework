#!/usr/bin/env python3
"""Backup all ChromaDB collections to JSON before embedding migration.

Exports documents, metadatas, embeddings, and IDs for all 5 collections.
Run manually: python3 hooks/scripts/backup_embeddings.py

Output: ~/data/memory/backup_minilm_YYYYMMDD.json
"""

import json
import os
import sys
from datetime import datetime

# Add hooks dir to path for shared imports
HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOKS_DIR)

MEMORY_DIR = os.path.join(os.path.expanduser("~"), "data", "memory")
COLLECTION_NAMES = ["knowledge", "fix_outcomes", "observations", "web_pages", "quarantine"]


def main():
    try:
        import chromadb
    except ImportError:
        print("ERROR: chromadb not installed")
        sys.exit(1)

    client = chromadb.PersistentClient(path=MEMORY_DIR)
    backup = {}
    total_docs = 0

    for name in COLLECTION_NAMES:
        try:
            col = client.get_collection(name)
            count = col.count()
            if count == 0:
                backup[name] = {"count": 0, "ids": [], "documents": [], "metadatas": [], "embeddings": []}
                print(f"  {name}: 0 entries (empty)")
                continue

            # Fetch docs+metas in chunks (always works even with MCP running)
            all_ids, all_docs, all_metas = [], [], []
            batch_size = 20
            for offset in range(0, count, batch_size):
                try:
                    chunk = col.get(
                        limit=batch_size, offset=offset,
                        include=["documents", "metadatas"],
                    )
                    all_ids.extend(chunk.get("ids", []))
                    all_docs.extend(chunk.get("documents") or [])
                    all_metas.extend(chunk.get("metadatas") or [])
                except Exception:
                    pass  # Skip failed chunks

            # Embeddings best-effort (may fail under concurrent access)
            all_embs = []
            emb_errors = 0
            for offset in range(0, count, batch_size):
                try:
                    chunk = col.get(
                        limit=batch_size, offset=offset,
                        include=["embeddings"],
                    )
                    raw_embs = chunk.get("embeddings")
                    if raw_embs is not None:
                        for emb in raw_embs:
                            if emb is not None:
                                all_embs.append([float(v) for v in emb])
                            else:
                                all_embs.append([])
                except Exception:
                    emb_errors += 1
                    for _ in range(batch_size):
                        all_embs.append([])

            backup[name] = {
                "count": count,
                "ids": all_ids,
                "documents": all_docs,
                "metadatas": all_metas,
                "embeddings": all_embs[:len(all_ids)],
            }
            total_docs += count
            valid_embs = sum(1 for e in all_embs if e)
            emb_dim = len(all_embs[0]) if all_embs and all_embs[0] else 0
            warn = f" ({emb_errors} emb chunk errors)" if emb_errors else ""
            print(f"  {name}: {count} entries, {valid_embs} embeddings ({emb_dim}-dim){warn}")
        except Exception as e:
            print(f"  {name}: SKIP ({e})")
            backup[name] = {"error": str(e)}

    # Write backup
    date_str = datetime.now().strftime("%Y%m%d")
    backup_path = os.path.join(MEMORY_DIR, f"backup_minilm_{date_str}.json")

    with open(backup_path, "w") as f:
        json.dump(backup, f)

    size_mb = os.path.getsize(backup_path) / (1024 * 1024)
    print(f"\nBackup saved: {backup_path}")
    print(f"Total: {total_docs} documents, {size_mb:.1f} MB")


if __name__ == "__main__":
    print("ChromaDB Embedding Backup")
    print("=" * 40)
    main()
