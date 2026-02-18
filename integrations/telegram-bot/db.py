#!/usr/bin/env python3
"""Telegram Bot — FTS5 message log database.

Schema tracks sender + chat_id for multi-chat support.
"""

import os
import sqlite3
import time
import uuid


def init_db(db_path):
    """Create FTS5 and metadata tables if they don't exist."""
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE VIRTUAL TABLE IF NOT EXISTS tg_fts USING fts5(
            text, date, sender UNINDEXED, chat_id UNINDEXED, msg_id UNINDEXED
        );
        CREATE TABLE IF NOT EXISTS tg_meta (
            msg_id TEXT PRIMARY KEY,
            chat_id INTEGER,
            sender TEXT,
            date TEXT,
            logged_at REAL
        );
    """)
    # Index for per-chat recent lookups — CREATE INDEX IF NOT EXISTS is safe
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_tg_meta_chat ON tg_meta(chat_id, logged_at DESC)"
    )
    conn.commit()
    conn.close()


def log_message(db_path, chat_id, sender, text, date):
    """Insert a message into FTS5 + metadata. Returns the synthetic msg_id."""
    if not text or not text.strip():
        return None

    msg_id = uuid.uuid4().hex[:16]
    now = time.time()
    date_str = date if isinstance(date, str) else date.isoformat() if hasattr(date, "isoformat") else str(date)

    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO tg_fts (text, date, sender, chat_id, msg_id) VALUES (?, ?, ?, ?, ?)",
        (text, date_str, sender, chat_id, msg_id),
    )
    conn.execute(
        "INSERT INTO tg_meta (msg_id, chat_id, sender, date, logged_at) VALUES (?, ?, ?, ?, ?)",
        (msg_id, chat_id, sender, date_str, now),
    )
    conn.commit()
    conn.close()
    return msg_id


def search_fts(db_path, query, limit=10):
    """FTS5 MATCH search. Returns list of {text, date, sender, chat_id, msg_id, source}."""
    if not os.path.isfile(db_path):
        return []
    if not query or not query.strip():
        return []

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT text, date, sender, chat_id, msg_id, rank FROM tg_fts WHERE tg_fts MATCH ? ORDER BY rank LIMIT ?",
            (query, limit),
        )
        results = [
            {
                "text": row[0],
                "date": row[1],
                "sender": row[2],
                "chat_id": row[3],
                "msg_id": row[4],
                "bm25": row[5],
                "source": "bot_fts",
            }
            for row in cursor
        ]
        conn.close()
        return results
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return []


def get_context_by_timestamp(db_path, timestamp, window_minutes=30, limit=5):
    """Find TG messages around a given timestamp.

    Returns list of {text, sender, date}.
    """
    if not os.path.isfile(db_path):
        return []
    if not timestamp:
        return []

    try:
        # Normalize: strip Z, fractional seconds, timezone offset for comparison
        ts_clean = timestamp.replace("Z", "").split(".")[0].split("+")[0]
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT f.text, m.sender, m.date "
            "FROM tg_meta m JOIN tg_fts f ON m.msg_id = f.msg_id "
            "WHERE substr(m.date, 1, 19) BETWEEN "
            "strftime('%Y-%m-%dT%H:%M:%S', ?, '-' || ? || ' minutes') AND "
            "strftime('%Y-%m-%dT%H:%M:%S', ?, '+' || ? || ' minutes') "
            "ORDER BY m.date LIMIT ?",
            (ts_clean, str(window_minutes), ts_clean, str(window_minutes), limit),
        )
        results = [
            {"text": row[0], "sender": row[1], "date": row[2]}
            for row in cursor
        ]
        conn.close()
        return results
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return []


def get_recent(db_path, chat_id, limit=20):
    """Get recent messages for a specific chat. Returns list of {text, date, sender, msg_id}."""
    if not os.path.isfile(db_path):
        return []

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT m.msg_id, m.sender, m.date, f.text "
            "FROM tg_meta m JOIN tg_fts f ON m.msg_id = f.msg_id "
            "WHERE m.chat_id = ? ORDER BY m.logged_at DESC LIMIT ?",
            (chat_id, limit),
        )
        results = [
            {"msg_id": row[0], "sender": row[1], "date": row[2], "text": row[3]}
            for row in cursor
        ]
        conn.close()
        return results
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return []
