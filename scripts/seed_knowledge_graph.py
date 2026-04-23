#!/usr/bin/env python3
"""Seed the knowledge graph from all LanceDB memories.

Reads all memories, runs entity extraction + co-occurrence detection,
and populates the KG with entities and edges.
"""

import os
import sys
import time

sys.path.insert(0, os.path.expanduser("~/.claude/hooks"))

from shared.knowledge_graph import KnowledgeGraph
from shared.entity_extraction import extract_entities, extract_cooccurrences

MEMORY_DIR = os.path.expanduser("~/.claude/data/memory")
LANCE_DIR = os.path.join(MEMORY_DIR, "lance_memories")


def main():
    import lancedb

    db = lancedb.connect(LANCE_DIR)
    table = db.open_table("knowledge")
    kg = KnowledgeGraph()

    rows = table.to_pandas()
    total = len(rows)
    print(f"Processing {total} memories...")

    entity_count = 0
    edge_count = 0
    t0 = time.monotonic()

    for i, row in rows.iterrows():
        content = str(row.get("content", ""))
        context = str(row.get("context", ""))
        tags = str(row.get("tags", ""))
        text = f"{content} {context} {tags}"

        # Extract and upsert entities
        entities = extract_entities(text)
        for ent in entities:
            kg.upsert_entity(ent["name"], ent["type"])
            entity_count += 1

        # Extract and add co-occurrence edges
        coocs = extract_cooccurrences(text)
        for e1, e2 in coocs:
            kg.add_edge(e1, e2, "co_occurs")
            edge_count += 1

        # Also update PMI for edges
        total_mems = total
        for e1, e2 in coocs:
            kg.update_pmi(e1, e2, "co_occurs", total_mems)

        if (i + 1) % 500 == 0:
            print(f"  {i + 1}/{total} processed...")

    elapsed = time.monotonic() - t0
    print(f"\nDone in {elapsed:.1f}s")
    print(f"Entities: {kg.entity_count()}")
    print(f"Edges: {kg.edge_count()}")
    kg.close()


if __name__ == "__main__":
    main()
