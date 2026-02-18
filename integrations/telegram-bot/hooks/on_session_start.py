#!/usr/bin/env python3
"""Telegram Bot — Session Start Hook

Searches FTS5 message log for context relevant to the new session.
Called by boot.py via subprocess with search query as argv[1].

Outputs JSON to stdout: {"results": [{text, date, source}], "count": N}
Always exits 0.
"""

import json
import os
import sys

_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PLUGIN_DIR)

DB_PATH = os.path.join(_PLUGIN_DIR, "msg_log.db")


def _search_fts(query: str, limit: int = 5) -> list:
    """Search local FTS5 message log. Returns list of {text, date, source}."""
    from db import search_fts
    results = search_fts(DB_PATH, query, limit=limit)
    return [
        {
            "text": r["text"][:500],
            "date": r["date"],
            "source": "telegram_fts",
        }
        for r in results
    ]


def main():
    try:
        query = sys.argv[1] if len(sys.argv) > 1 else ""
        if not query.strip():
            print(json.dumps({"results": [], "count": 0}))
            sys.exit(0)

        results = _search_fts(query)
        output = {"results": results, "count": len(results)}
        print(json.dumps(output))

    except Exception as e:
        print(json.dumps({"results": [], "count": 0, "error": str(e)}))

    sys.exit(0)


if __name__ == "__main__":
    main()
