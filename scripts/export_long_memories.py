#!/usr/bin/env python3
"""Export knowledge entries longer than THRESHOLD chars to JSONL.

Output: one JSON object per line — {id, text, tags, char_count}

Usage:
    python3 export_long_memories.py                        # threshold 2000, output to ./long_memories.jsonl
    python3 export_long_memories.py --threshold 1000
    python3 export_long_memories.py --out /tmp/long.jsonl
"""

import json
import os
import sys
import argparse

LANCE_DIR = os.path.join(os.path.expanduser("~"), "data", "memory", "lancedb")
DEFAULT_THRESHOLD = 2000
DEFAULT_OUT = os.path.join(os.path.dirname(__file__), "long_memories.jsonl")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD)
    parser.add_argument("--out", default=DEFAULT_OUT)
    args = parser.parse_args()

    import lancedb

    db = lancedb.connect(LANCE_DIR)
    tbl = db.open_table("knowledge")

    print(f"Scanning knowledge table...", file=sys.stderr)
    rows = tbl.search().limit(200000).to_list()
    print(f"  Total: {len(rows)}", file=sys.stderr)

    oversized = [r for r in rows if len(r.get("text", "")) > args.threshold]
    print(f"  Over {args.threshold} chars: {len(oversized)}", file=sys.stderr)

    with open(args.out, "w") as f:
        for r in oversized:
            f.write(
                json.dumps(
                    {
                        "id": r["id"],
                        "text": r["text"],
                        "tags": r.get("tags", ""),
                        "char_count": len(r["text"]),
                    }
                )
                + "\n"
            )

    print(f"Wrote {len(oversized)} entries to {args.out}", file=sys.stderr)
    print(args.out)


if __name__ == "__main__":
    main()
