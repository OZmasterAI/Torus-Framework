"""Agent messaging channel — lightweight SQLite WAL-mode inter-agent communication.

Agents post short messages (discoveries, warnings, status updates) that other
agents can read. All operations are fail-open: exceptions return empty results
rather than crashing the caller.

DB location: ~/.claude/hooks/agent_channel.db
"""

import fcntl
import os
import sqlite3
import time

DB_PATH = os.path.expanduser("~/.claude/hooks/agent_channel.db")
LOCK_PATH = DB_PATH + ".lock"


def _get_conn():
    """Get a WAL-mode SQLite connection with busy timeout."""
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            from_agent TEXT NOT NULL,
            to_agent TEXT NOT NULL DEFAULT 'all',
            msg_type TEXT NOT NULL,
            content TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_ts ON messages(ts)")
    return conn


def _with_lock(fn):
    """Execute fn under an advisory file lock (fail-open)."""
    lock_fd = None
    try:
        lock_fd = open(LOCK_PATH, "w")
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, IOError):
        pass  # Proceed without lock — fail-open

    try:
        return fn()
    finally:
        if lock_fd:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                lock_fd.close()
            except (OSError, IOError):
                pass


def post_message(from_agent, msg_type, content, to_agent="all"):
    """Post a message to the channel. Returns True on success."""
    def _post():
        conn = _get_conn()
        try:
            conn.execute(
                "INSERT INTO messages (ts, from_agent, to_agent, msg_type, content) VALUES (?, ?, ?, ?, ?)",
                (time.time(), from_agent, to_agent, msg_type, content),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    try:
        return _with_lock(_post)
    except Exception:
        return False


def read_messages(since_ts, agent_id=None, limit=50):
    """Read messages since a timestamp. Optionally filter by recipient agent.

    Returns list of dicts: [{ts, from_agent, to_agent, msg_type, content}, ...]
    """
    def _read():
        conn = _get_conn()
        try:
            if agent_id:
                rows = conn.execute(
                    "SELECT ts, from_agent, to_agent, msg_type, content FROM messages "
                    "WHERE ts > ? AND (to_agent = 'all' OR to_agent = ?) ORDER BY ts DESC LIMIT ?",
                    (since_ts, agent_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT ts, from_agent, to_agent, msg_type, content FROM messages "
                    "WHERE ts > ? ORDER BY ts DESC LIMIT ?",
                    (since_ts, limit),
                ).fetchall()
            return [
                {"ts": r[0], "from_agent": r[1], "to_agent": r[2], "msg_type": r[3], "content": r[4]}
                for r in rows
            ]
        finally:
            conn.close()

    try:
        return _with_lock(_read)
    except Exception:
        return []


def cleanup(max_age_hours=2):
    """Delete messages older than max_age_hours. Returns count deleted."""
    def _cleanup():
        cutoff = time.time() - (max_age_hours * 3600)
        conn = _get_conn()
        try:
            cursor = conn.execute("DELETE FROM messages WHERE ts < ?", (cutoff,))
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()

    try:
        return _with_lock(_cleanup)
    except Exception:
        return 0
