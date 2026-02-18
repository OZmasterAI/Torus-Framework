#!/usr/bin/env python3
"""Telegram Memory Plugin — Sync to SQLite FTS5

Pulls recent messages from Telegram Saved Messages and stores them in a
local FTS5-indexed SQLite database for fast offline search.

Usage:
    python3 sync.py [--limit N]  (default: 200)
"""

import argparse
import os
import sqlite3
import sys
import time

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _PLUGIN_DIR)

INDEX_DB = os.path.join(_PLUGIN_DIR, "index.db")


def _init_db(conn):
    """Create FTS5 and metadata tables if they don't exist."""
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS tg_fts USING fts5(
            text, date, msg_id UNINDEXED
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tg_meta (
            msg_id INTEGER PRIMARY KEY,
            date TEXT,
            synced_at REAL
        )
    """)
    conn.commit()


def _get_existing_ids(conn) -> set:
    """Get set of already-synced message IDs."""
    cursor = conn.execute("SELECT msg_id FROM tg_meta")
    return {row[0] for row in cursor}


def sync(limit: int = 200):
    """Pull messages from Telegram and upsert into FTS5 index."""
    from telegram_memory import get_history, TelegramError

    print(f"Fetching up to {limit} messages from Telegram...")
    try:
        messages = get_history(limit=limit)
    except TelegramError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    if not messages:
        print("No messages found in Saved Messages.")
        return

    print(f"Fetched {len(messages)} messages.")

    conn = sqlite3.connect(INDEX_DB)
    _init_db(conn)

    existing = _get_existing_ids(conn)
    now = time.time()
    new_count = 0

    for msg in messages:
        msg_id = msg["id"]
        if msg_id in existing:
            continue

        text = msg.get("text", "")
        date = msg.get("date", "")

        if not text.strip():
            continue

        conn.execute(
            "INSERT INTO tg_fts (text, date, msg_id) VALUES (?, ?, ?)",
            (text, date, msg_id),
        )
        conn.execute(
            "INSERT OR REPLACE INTO tg_meta (msg_id, date, synced_at) VALUES (?, ?, ?)",
            (msg_id, date, now),
        )
        new_count += 1

    conn.commit()

    total = conn.execute("SELECT COUNT(*) FROM tg_meta").fetchone()[0]
    conn.close()

    print(f"Synced {new_count} new messages ({total} total in index).")


def main():
    parser = argparse.ArgumentParser(description="Sync Telegram -> SQLite FTS5")
    parser.add_argument("--limit", type=int, default=200, help="Messages to fetch (default: 200)")
    args = parser.parse_args()

    sync(limit=args.limit)


if __name__ == "__main__":
    main()
