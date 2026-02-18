#!/usr/bin/env python3
"""Telegram Memory Plugin — CLI Search

Search Telegram Saved Messages via local FTS5 cache or live API.

Usage:
    python3 search.py "query"           # Human-readable output
    python3 search.py "query" --json    # Machine output (for memory_server.py)
    python3 search.py "query" --live    # Skip FTS, search Telegram directly
    python3 search.py "query" --limit 5 # Limit results
"""

import argparse
import json
import os
import sqlite3
import sys

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _PLUGIN_DIR)

INDEX_DB = os.path.join(_PLUGIN_DIR, "index.db")


def _search_fts(query: str, limit: int = 10) -> list:
    """Search local FTS5 cache."""
    if not os.path.isfile(INDEX_DB):
        return []

    try:
        conn = sqlite3.connect(INDEX_DB)
        cursor = conn.execute(
            "SELECT text, date, msg_id FROM tg_fts WHERE tg_fts MATCH ? ORDER BY rank LIMIT ?",
            (query, limit),
        )
        results = []
        for row in cursor:
            results.append({
                "text": row[0],
                "date": row[1],
                "msg_id": row[2],
                "source": "fts",
            })
        conn.close()
        return results
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return []


def _search_live(query: str, limit: int = 10) -> list:
    """Search Telegram API directly."""
    from telegram_memory import search
    results = search(query, limit=limit)
    return [
        {
            "text": r["text"],
            "date": r["date"],
            "msg_id": r["id"],
            "source": "live",
        }
        for r in results
    ]


def main():
    parser = argparse.ArgumentParser(description="Search Telegram memory")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--live", action="store_true", help="Search Telegram directly")
    parser.add_argument("--limit", type=int, default=10, help="Max results (default: 10)")
    args = parser.parse_args()

    if not args.query.strip():
        if args.json:
            print(json.dumps({"results": [], "count": 0}))
        else:
            print("No query provided.")
        sys.exit(0)

    results = []

    if args.live:
        results = _search_live(args.query, limit=args.limit)
    else:
        # Try FTS first, fall back to live
        results = _search_fts(args.query, limit=args.limit)
        if not results:
            try:
                results = _search_live(args.query, limit=args.limit)
            except Exception as e:
                if not args.json:
                    print(f"Live search failed: {e}", file=sys.stderr)

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
                date = r.get("date", "unknown")
                source = r.get("source", "?")
                print(f"  [{i}] ({source}, {date})")
                print(f"      {text_preview}")
                print()


if __name__ == "__main__":
    main()
