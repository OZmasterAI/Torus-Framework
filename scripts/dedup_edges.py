#!/usr/bin/env python3
"""One-shot: deduplicate nodes and edges in the code graph.

Step 1: Merge duplicate nodes (same project/file/name, different IDs),
        migrating edges to the canonical node.
Step 2: Deduplicate relation tables so UNIQUE indexes can be created.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "hooks"))

from shared.indexer_schema import connect_code_graph, dedup_nodes

db = connect_code_graph()

# Step 1: Node dedup
sys.stdout.write("=== Node dedup ===\n")
sys.stdout.flush()
t0 = time.time()
groups_merged, edges_migrated = dedup_nodes(db)
elapsed = time.time() - t0
node_count = db.query("SELECT count() FROM code_node GROUP ALL")
nc = node_count[0].get("count", 0) if node_count else 0
sys.stdout.write(
    f"Merged {groups_merged} duplicate groups, "
    f"migrated {edges_migrated} edges ({elapsed:.1f}s). "
    f"{nc} nodes remain.\n"
)
sys.stdout.flush()

# Step 2: Edge dedup
sys.stdout.write("\n=== Edge dedup ===\n")
sys.stdout.flush()
for rel in ["calls", "imports", "reads", "writes", "implements"]:
    edges = db.query(f"SELECT id, in, out FROM {rel}")
    seen = {}
    to_delete = []
    for e in edges:
        key = (str(e.get("in")), str(e.get("out")))
        if key in seen:
            to_delete.append(e["id"])
        else:
            seen[key] = e["id"]

    if to_delete:
        sys.stdout.write(f"{rel}: {len(to_delete)} dupes to remove...")
        sys.stdout.flush()
        for rid in to_delete:
            try:
                db.query(f"DELETE {rid}")
            except Exception:
                time.sleep(0.05)
                try:
                    db.query(f"DELETE {rid}")
                except Exception:
                    pass

        after = db.query(f"SELECT count() FROM {rel} GROUP ALL")
        c = after[0].get("count", 0) if after else 0
        sys.stdout.write(f" done, {c} remain\n")
    else:
        sys.stdout.write(f"{rel}: clean ({len(seen)} unique)\n")
    sys.stdout.flush()
