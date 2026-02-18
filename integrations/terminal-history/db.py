#!/usr/bin/env python3
"""Terminal History — FTS5 message log database.

Schema tracks role + session_id for multi-session support.
Mirrors integrations/telegram-bot/db.py pattern.
"""

import os
import sqlite3
import time
import uuid


def init_db(db_path):
    """Create FTS5 and metadata tables if they don't exist."""
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE VIRTUAL TABLE IF NOT EXISTS term_fts USING fts5(
            text, role UNINDEXED, session_id UNINDEXED,
            timestamp UNINDEXED, slug UNINDEXED
        );
        CREATE TABLE IF NOT EXISTS term_meta (
            row_id TEXT PRIMARY KEY,
            session_id TEXT,
            role TEXT,
            timestamp TEXT,
            slug TEXT,
            logged_at REAL
        );
        CREATE TABLE IF NOT EXISTS indexed_sessions (
            session_id TEXT PRIMARY KEY,
            indexed_at REAL,
            record_count INTEGER DEFAULT 0
        );
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_term_meta_session "
        "ON term_meta(session_id, logged_at DESC)"
    )
    conn.commit()
    conn.close()


def log_entry(db_path, session_id, role, text, timestamp, slug=""):
    """Insert a message into FTS5 + metadata. Returns the synthetic row_id."""
    if not text or not text.strip():
        return None

    row_id = uuid.uuid4().hex[:16]
    now = time.time()
    ts_str = timestamp if isinstance(timestamp, str) else str(timestamp)

    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO term_fts (text, role, session_id, timestamp, slug) "
        "VALUES (?, ?, ?, ?, ?)",
        (text, role, session_id, ts_str, slug),
    )
    conn.execute(
        "INSERT INTO term_meta (row_id, session_id, role, timestamp, slug, logged_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (row_id, session_id, role, ts_str, slug, now),
    )
    conn.commit()
    conn.close()
    return row_id


def search_fts(db_path, query, limit=10):
    """FTS5 MATCH search. Returns list of dicts."""
    if not os.path.isfile(db_path):
        return []
    if not query or not query.strip():
        return []

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT text, role, session_id, timestamp, slug "
            "FROM term_fts WHERE term_fts MATCH ? ORDER BY rank LIMIT ?",
            (query, limit),
        )
        results = [
            {
                "text": row[0],
                "role": row[1],
                "session_id": row[2],
                "timestamp": row[3],
                "slug": row[4],
                "source": "terminal_l2",
            }
            for row in cursor
        ]
        conn.close()
        return results
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return []


def is_session_indexed(db_path, session_id):
    """Check if a session has already been indexed."""
    if not os.path.isfile(db_path):
        return False
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT 1 FROM indexed_sessions WHERE session_id = ?", (session_id,)
        )
        found = cursor.fetchone() is not None
        conn.close()
        return found
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return False


def mark_session_indexed(db_path, session_id, record_count):
    """Mark a session as indexed with its record count."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT OR REPLACE INTO indexed_sessions (session_id, indexed_at, record_count) "
        "VALUES (?, ?, ?)",
        (session_id, time.time(), record_count),
    )
    conn.commit()
    conn.close()
