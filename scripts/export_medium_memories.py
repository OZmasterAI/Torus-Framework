#!/usr/bin/env python3
"""Export knowledge entries where 800 < len(text) <= 2000 chars to JSONL.

Output: one JSON object per line — {id, text}
"""

import json
import os
import sys

LANCE_DIR = os.path.join(os.path.expanduser("~"), "data", "memory", "lancedb")
OUT = os.path.join(os.path.dirname(__file__), "medium_memories.jsonl")

import lancedb

db = lancedb.connect(LANCE_DIR)
tbl = db.open_table("knowledge")

print("Scanning knowledge table...", file=sys.stderr)
rows = tbl.search().limit(200000).to_list()
print(f"  Total: {len(rows)}", file=sys.stderr)

medium = [r for r in rows if 800 < len(r.get("text", "")) <= 2000]
print(f"  800 < len <= 2000: {len(medium)}", file=sys.stderr)

with open(OUT, "w") as f:
    for r in medium:
        f.write(json.dumps({"id": r["id"], "text": r["text"]}) + "\n")

print(f"Wrote {len(medium)} entries to {OUT}", file=sys.stderr)
print(f"COUNT:{len(medium)}")
