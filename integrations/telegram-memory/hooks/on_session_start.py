#!/usr/bin/env python3
"""Telegram Memory Plugin — Session Start Hook

Searches Telegram Saved Messages for context relevant to the new session.
Called by boot.py via subprocess with search query as argv[1].

Outputs JSON to stdout: {"results": [{text, date, source}], "count": N}
Always exits 0.
"""

import json
import os
import sqlite3
import sys

_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PLUGIN_DIR)

INDEX_DB = os.path.join(_PLUGIN_DIR, "index.db")


def _search_fts(query: str, limit: int = 5) -> list:
    """Search local FTS5 cache. Returns list of {text, date, source}."""
    if not os.path.isfile(INDEX_DB):
        return []

    try:
        conn = sqlite3.connect(INDEX_DB)
        cursor = conn.execute(
            "SELECT text, date FROM tg_fts WHERE tg_fts MATCH ? ORDER BY rank LIMIT ?",
            (query, limit),
        )
        results = []
        for row in cursor:
            results.append({
                "text": row[0][:500],
                "date": row[1],
                "source": "telegram_fts",
            })
        conn.close()
        return results
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return []


def _search_live(query: str, limit: int = 5) -> list:
    """Search Telegram API directly. Returns list of {text, date, source}."""
    try:
        from telegram_memory import search, TelegramError
        results = search(query, limit=limit)
        return [
            {
                "text": r["text"][:500],
                "date": r["date"],
                "source": "telegram_live",
            }
            for r in results
        ]
    except Exception:
        return []


def main():
    try:
        query = sys.argv[1] if len(sys.argv) > 1 else ""
        if not query.strip():
            print(json.dumps({"results": [], "count": 0}))
            sys.exit(0)

        # Try FTS cache first
        results = _search_fts(query)

        # Fall back to live Telegram if cache miss
        if not results:
            results = _search_live(query)

        output = {"results": results, "count": len(results)}
        print(json.dumps(output))

    except Exception as e:
        print(json.dumps({"results": [], "count": 0, "error": str(e)}))

    sys.exit(0)


if __name__ == "__main__":
    main()
