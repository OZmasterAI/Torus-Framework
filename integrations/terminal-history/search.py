#!/usr/bin/env python3
"""Terminal History — CLI Search

Search FTS5 index of terminal session conversations.

Usage:
    python3 search.py "query"           # Human-readable output
    python3 search.py "query" --json    # Machine output (for memory_server.py)
    python3 search.py "query" --limit 5 # Limit results
"""

import argparse
import json
import os
import sys

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _PLUGIN_DIR)

DB_PATH = os.path.join(_PLUGIN_DIR, "terminal_history.db")


def main():
    parser = argparse.ArgumentParser(description="Search terminal session history")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--limit", type=int, default=10, help="Max results (default: 10)")
    args = parser.parse_args()

    if not args.query.strip():
        if args.json:
            print(json.dumps({"results": [], "count": 0}))
        else:
            print("No query provided.")
        sys.exit(0)

    from db import search_fts
    raw_results = search_fts(DB_PATH, args.query, limit=args.limit)

    results = [
        {
            "text": r["text"],
            "timestamp": r["timestamp"],
            "role": r["role"],
            "session_id": r["session_id"],
            "bm25": r.get("bm25", 0),
            "tags": r.get("tags", ""),
            "linked_memory_ids": r.get("linked_memory_ids", ""),
            "source": "terminal_l2",
        }
        for r in raw_results
    ]

    if args.json:
        print(json.dumps({"results": results, "count": len(results)}))
    else:
        if not results:
            print(f"No results for: {args.query}")
        else:
            print(f"Found {len(results)} results for: {args.query}\n")
            for i, r in enumerate(results, 1):
                text_preview = r["text"][:200]
                if len(r["text"]) > 200:
                    text_preview += "..."
                ts = r.get("timestamp", "unknown")
                role = r.get("role", "?")
                sid = r.get("session_id", "?")[:12]
                print(f"  [{i}] ({role}, {ts}, session:{sid}...)")
                print(f"      {text_preview}")
                print()


if __name__ == "__main__":
    main()
