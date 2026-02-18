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
    # Schema migration: add tags and linked_memory_ids columns
    _migrate_columns(conn)
    conn.commit()
    conn.close()


def _migrate_columns(conn):
    """Add tags and linked_memory_ids columns if missing."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(term_meta)").fetchall()}
    if "tags" not in existing:
        conn.execute("ALTER TABLE term_meta ADD COLUMN tags TEXT DEFAULT ''")
    if "linked_memory_ids" not in existing:
        conn.execute("ALTER TABLE term_meta ADD COLUMN linked_memory_ids TEXT DEFAULT ''")


def log_entry(db_path, session_id, role, text, timestamp, slug="", tags="", linked_memory_ids=""):
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
        "INSERT INTO term_meta (row_id, session_id, role, timestamp, slug, logged_at, tags, linked_memory_ids) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (row_id, session_id, role, ts_str, slug, now, tags, linked_memory_ids),
    )
    conn.commit()
    conn.close()
    return row_id


def search_fts(db_path, query, limit=10):
    """FTS5 MATCH search. Returns list of dicts with BM25 rank and tags."""
    if not os.path.isfile(db_path):
        return []
    if not query or not query.strip():
        return []

    try:
        conn = sqlite3.connect(db_path)
        # Join with term_meta to get tags and linked_memory_ids
        cursor = conn.execute(
            "SELECT f.text, f.role, f.session_id, f.timestamp, f.slug, f.rank, "
            "m.tags, m.linked_memory_ids "
            "FROM term_fts f "
            "LEFT JOIN term_meta m ON f.rowid = m.rowid "
            "WHERE term_fts MATCH ? ORDER BY f.rank LIMIT ?",
            (query, limit),
        )
        results = [
            {
                "text": row[0],
                "role": row[1],
                "session_id": row[2],
                "timestamp": row[3],
                "slug": row[4],
                "bm25": row[5],
                "tags": row[6] or "",
                "linked_memory_ids": row[7] or "",
                "source": "terminal_l2",
            }
            for row in cursor
        ]
        conn.close()
        return results
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return []


def search_by_tags(db_path, tags, limit=10):
    """Search terminal records by tags. Returns list of dicts."""
    if not os.path.isfile(db_path):
        return []
    if not tags:
        return []

    try:
        conn = sqlite3.connect(db_path)
        # Build OR conditions for each tag
        conditions = []
        params = []
        for tag in tags:
            tag = tag.strip()
            if tag:
                conditions.append("m.tags LIKE ?")
                params.append(f"%{tag}%")

        if not conditions:
            conn.close()
            return []

        sql = (
            "SELECT f.text, f.role, f.session_id, f.timestamp, f.slug, "
            "m.tags, m.linked_memory_ids "
            "FROM term_meta m "
            "JOIN term_fts f ON f.rowid = m.rowid "
            f"WHERE ({' OR '.join(conditions)}) "
            "ORDER BY m.logged_at DESC LIMIT ?"
        )
        params.append(limit)
        cursor = conn.execute(sql, params)
        results = [
            {
                "text": row[0],
                "role": row[1],
                "session_id": row[2],
                "timestamp": row[3],
                "slug": row[4],
                "tags": row[5] or "",
                "linked_memory_ids": row[6] or "",
                "source": "terminal_l2",
            }
            for row in cursor
        ]
        conn.close()
        return results
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return []


def update_session_tags(db_path, session_id, tags, linked_memory_ids=""):
    """Update tags and linked_memory_ids for all records in a session."""
    if not os.path.isfile(db_path):
        return 0
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "UPDATE term_meta SET tags = ?, linked_memory_ids = ? WHERE session_id = ?",
            (tags, linked_memory_ids, session_id),
        )
        count = cursor.rowcount
        conn.commit()
        conn.close()
        return count
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return 0


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


def get_context_by_timestamp(db_path, timestamp, window_minutes=30, limit=5):
    """Find conversation context around a given timestamp.

    Looks up the session active at that time and returns surrounding messages.
    Returns list of {text, role, timestamp, session_id}.
    """
    if not os.path.isfile(db_path):
        return []
    if not timestamp:
        return []

    try:
        # Normalize timestamp: strip Z, ensure consistent format for comparison
        ts_clean = timestamp.replace("Z", "").split(".")[0]  # "2026-02-18T16:27:04"
        conn = sqlite3.connect(db_path)
        # Find the session that contains records closest to this timestamp
        cursor = conn.execute(
            "SELECT session_id FROM term_meta "
            "WHERE substr(timestamp, 1, 19) BETWEEN "
            "strftime('%Y-%m-%dT%H:%M:%S', ?, '-' || ? || ' minutes') AND "
            "strftime('%Y-%m-%dT%H:%M:%S', ?, '+' || ? || ' minutes') "
            "LIMIT 1",
            (ts_clean, str(window_minutes), ts_clean, str(window_minutes)),
        )
        row = cursor.fetchone()
        if not row:
            conn.close()
            return []

        session_id = row[0]
        # Get messages from that session around the timestamp
        cursor = conn.execute(
            "SELECT text, role, timestamp FROM term_fts "
            "WHERE session_id = ? "
            "ORDER BY timestamp LIMIT ?",
            (session_id, limit),
        )
        results = [
            {
                "text": r[0],
                "role": r[1],
                "timestamp": r[2],
                "session_id": session_id,
            }
            for r in cursor
        ]
        conn.close()
        return results
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return []


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
