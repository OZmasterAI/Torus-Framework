#!/usr/bin/env python3
"""Standalone embedding migration: all-MiniLM-L6-v2 → nomic-embed-text-v2-moe.

Reads all docs from each collection, deletes collection, recreates with
nomic embedding function, re-inserts (ChromaDB auto-embeds).

REQUIRES: MCP server disconnected (ChromaDB can't handle concurrent access).
Run: python3 hooks/scripts/run_migration.py
"""

import json
import os
import sys
import time
from datetime import datetime

MEMORY_DIR = os.path.join(os.path.expanduser("~"), "data", "memory")
MARKER = os.path.join(os.path.expanduser("~"), ".claude", "hooks", ".embedding_migration_done")
BACKUP_PATH = os.path.join(MEMORY_DIR, "backup_minilm_20260222.json")
MODEL = "nomic-ai/nomic-embed-text-v2-moe"
COLLECTIONS = ["knowledge", "fix_outcomes", "observations", "web_pages", "quarantine"]
BATCH_SIZE = 50


def main():
    import chromadb
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

    # Verify backup exists
    if not os.path.exists(BACKUP_PATH):
        print(f"ERROR: Backup not found at {BACKUP_PATH}")
        sys.exit(1)
    print(f"Backup verified: {BACKUP_PATH}")

    # Load nomic embedding model
    print(f"Loading embedding model: {MODEL} ...")
    t0 = time.time()
    ef = SentenceTransformerEmbeddingFunction(model_name=MODEL, trust_remote_code=True)
    print(f"Model loaded in {time.time() - t0:.1f}s")

    # Open ChromaDB
    client = chromadb.PersistentClient(path=MEMORY_DIR)

    total_migrated = 0
    for name in COLLECTIONS:
        try:
            col = client.get_or_create_collection(name=name, metadata={"hnsw:space": "cosine"})
        except Exception:
            # If conflict, open without embedding to read data
            col = client.get_or_create_collection(name=name, metadata={"hnsw:space": "cosine"})

        count = col.count()
        if count == 0:
            print(f"  {name}: empty, skipping")
            continue

        # Export all data
        print(f"  {name}: exporting {count} docs ...", end=" ", flush=True)
        all_ids, all_docs, all_metas = [], [], []
        for offset in range(0, count, BATCH_SIZE):
            chunk = col.get(limit=BATCH_SIZE, offset=offset, include=["documents", "metadatas"])
            all_ids.extend(chunk.get("ids", []))
            all_docs.extend(chunk.get("documents") or [])
            all_metas.extend(chunk.get("metadatas") or [])
        print(f"got {len(all_ids)}")

        # Delete and recreate with nomic
        print(f"  {name}: deleting and recreating with nomic ...", end=" ", flush=True)
        client.delete_collection(name)
        new_col = client.get_or_create_collection(
            name=name, metadata={"hnsw:space": "cosine"}, embedding_function=ef,
        )
        print("done")

        # Re-insert in batches (nomic auto-embeds)
        print(f"  {name}: re-embedding {len(all_ids)} docs ...", flush=True)
        t1 = time.time()
        for start in range(0, len(all_ids), BATCH_SIZE):
            end = min(start + BATCH_SIZE, len(all_ids))
            kwargs = {"ids": all_ids[start:end]}
            if all_docs:
                kwargs["documents"] = all_docs[start:end]
            if all_metas:
                kwargs["metadatas"] = all_metas[start:end]
            new_col.upsert(**kwargs)
            done = min(end, len(all_ids))
            if done % 200 == 0 or end >= len(all_ids):
                elapsed = time.time() - t1
                print(f"    {done}/{len(all_ids)} ({elapsed:.1f}s)", flush=True)

        total_migrated += len(all_ids)
        print(f"  {name}: DONE ({len(all_ids)} migrated)")

    # Write marker
    with open(MARKER, "w") as f:
        f.write(f"{datetime.now().isoformat()} migrated={total_migrated} model={MODEL}")

    print(f"\nMigration complete: {total_migrated} total docs re-embedded with {MODEL}")
    print(f"Marker written: {MARKER}")


if __name__ == "__main__":
    main()
