"""Agent communication & task coordination — unified SQLite WAL-mode module.

Two tables in one DB:
  messages — broadcast/directed messaging with inbox ack and reply threading
  tasks    — priority-based task queue with atomic claiming and goal ancestry

All operations are fail-open: exceptions return empty/False rather than crashing.

DB location: ~/.claude/hooks/agent_channel.db
"""

from __future__ import annotations

import os
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DB_PATH = os.path.expanduser("~/.claude/hooks/agent_channel.db")
LOCK_PATH = DB_PATH + ".lock"  # kept for test compat — not used internally

_MAX_TEXT = 2000

VALID_STATUSES = frozenset(
    ("pending", "assigned", "running", "done", "failed", "cancelled")
)


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------


def _get_conn() -> sqlite3.Connection:
    """Return a WAL-mode connection, creating schema if needed."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # Messages table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          REAL NOT NULL,
            from_agent  TEXT NOT NULL,
            to_agent    TEXT NOT NULL DEFAULT 'all',
            msg_type    TEXT NOT NULL,
            content     TEXT NOT NULL,
            consumed    INTEGER DEFAULT 0,
            reply_to    INTEGER DEFAULT NULL,
            FOREIGN KEY (reply_to) REFERENCES messages(id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_msg_ts ON messages(ts)")

    # Migrate old schema: add columns if missing (safe no-op on fresh DB)
    for col, defn in [
        ("consumed", "INTEGER DEFAULT 0"),
        ("reply_to", "INTEGER DEFAULT NULL"),
    ]:
        try:
            conn.execute(f"ALTER TABLE messages ADD COLUMN {col} {defn}")
        except sqlite3.OperationalError:
            pass  # column already exists

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_msg_to ON messages(to_agent, consumed)"
    )

    # Tasks table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id             TEXT PRIMARY KEY,
            created_at     REAL NOT NULL,
            updated_at     REAL NOT NULL,
            title          TEXT NOT NULL,
            description    TEXT DEFAULT '',
            created_by     TEXT NOT NULL,
            assigned_to    TEXT DEFAULT NULL,
            status         TEXT NOT NULL DEFAULT 'pending',
            priority       INTEGER DEFAULT 5,
            tags           TEXT DEFAULT '',
            result         TEXT DEFAULT '',
            depends_on     TEXT DEFAULT NULL,
            required_role  TEXT DEFAULT NULL,
            goal           TEXT DEFAULT NULL,
            parent_task_id TEXT DEFAULT NULL,
            FOREIGN KEY (parent_task_id) REFERENCES tasks(id)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status, priority)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_agent ON tasks(assigned_to)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_task_id)")

    return conn


def _row_to_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    """Convert a sqlite3.Row to a plain dict."""
    if row is None:
        return None
    return dict(row)


def _rows_to_dicts(rows: list) -> List[Dict[str, Any]]:
    """Convert a list of sqlite3.Row to list of dicts."""
    return [dict(r) for r in rows]


# ===================================================================
# MESSAGING
# ===================================================================


def post_message(
    from_agent: str, msg_type: str, content: str, to_agent: str = "all"
) -> bool:
    """Post a message to the channel. Returns True on success."""
    try:
        conn = _get_conn()
        try:
            conn.execute(
                "INSERT INTO messages (ts, from_agent, to_agent, msg_type, content) "
                "VALUES (?, ?, ?, ?, ?)",
                (time.time(), from_agent, to_agent, msg_type, content[:_MAX_TEXT]),
            )
            conn.commit()
            return True
        finally:
            conn.close()
    except Exception:
        return False


def read_messages(
    since_ts: float, agent_id: Optional[str] = None, limit: int = 50
) -> List[Dict[str, Any]]:
    """Read messages since a timestamp. Optionally filter by recipient agent."""
    try:
        conn = _get_conn()
        try:
            if agent_id:
                rows = conn.execute(
                    "SELECT id, ts, from_agent, to_agent, msg_type, content, consumed, reply_to "
                    "FROM messages WHERE ts > ? AND (to_agent = 'all' OR to_agent = ?) "
                    "ORDER BY ts DESC LIMIT ?",
                    (since_ts, agent_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, ts, from_agent, to_agent, msg_type, content, consumed, reply_to "
                    "FROM messages WHERE ts > ? ORDER BY ts DESC LIMIT ?",
                    (since_ts, limit),
                ).fetchall()
            return _rows_to_dicts(rows)
        finally:
            conn.close()
    except Exception:
        return []


def ack_message(msg_id: int, agent_id: str) -> bool:
    """Mark a message as consumed by agent_id. Returns True on success."""
    try:
        conn = _get_conn()
        try:
            cursor = conn.execute(
                "UPDATE messages SET consumed = 1 "
                "WHERE id = ? AND (to_agent = ? OR to_agent = 'all')",
                (msg_id, agent_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()
    except Exception:
        return False


def pending_count(agent_id: str) -> int:
    """Count unconsumed messages directed to agent_id."""
    try:
        conn = _get_conn()
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM messages "
                "WHERE (to_agent = ? OR to_agent = 'all') AND consumed = 0",
                (agent_id,),
            ).fetchone()
            return row[0] if row else 0
        finally:
            conn.close()
    except Exception:
        return 0


def get_thread(msg_id: int) -> List[Dict[str, Any]]:
    """Fetch a message and all replies to it, ordered by time."""
    try:
        conn = _get_conn()
        try:
            rows = conn.execute(
                "SELECT id, ts, from_agent, to_agent, msg_type, content, consumed, reply_to "
                "FROM messages WHERE id = ? OR reply_to = ? ORDER BY ts ASC",
                (msg_id, msg_id),
            ).fetchall()
            return _rows_to_dicts(rows)
        finally:
            conn.close()
    except Exception:
        return []


def reply(msg_id: int, from_agent: str, content: str) -> bool:
    """Reply to a message. Inherits to_agent from the original message's from_agent."""
    try:
        conn = _get_conn()
        try:
            original = conn.execute(
                "SELECT from_agent FROM messages WHERE id = ?", (msg_id,)
            ).fetchone()
            if not original:
                return False
            to_agent = original["from_agent"]
            conn.execute(
                "INSERT INTO messages (ts, from_agent, to_agent, msg_type, content, reply_to) "
                "VALUES (?, ?, ?, 'reply', ?, ?)",
                (time.time(), from_agent, to_agent, content[:_MAX_TEXT], msg_id),
            )
            conn.commit()
            return True
        finally:
            conn.close()
    except Exception:
        return False


def cleanup(max_age_hours: int = 2) -> int:
    """Delete messages older than max_age_hours. Returns count deleted."""
    try:
        cutoff = time.time() - (max_age_hours * 3600)
        conn = _get_conn()
        try:
            cursor = conn.execute("DELETE FROM messages WHERE ts < ?", (cutoff,))
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()
    except Exception:
        return 0


# ===================================================================
# TASKS
# ===================================================================


def create_task(
    title: str,
    description: str = "",
    created_by: str = "",
    priority: int = 5,
    tags: Optional[list] = None,
    assigned_to: Optional[str] = None,
    depends_on: Optional[str] = None,
    required_role: Optional[str] = None,
    goal: Optional[str] = None,
    parent_task_id: Optional[str] = None,
    notify: bool = True,
) -> Optional[str]:
    """Create a task. Auto-propagates goal from parent if not provided. Returns task_id."""
    try:
        conn = _get_conn()
        try:
            # Goal propagation from parent
            if parent_task_id and not goal:
                parent = conn.execute(
                    "SELECT goal, title FROM tasks WHERE id = ?", (parent_task_id,)
                ).fetchone()
                if parent:
                    parent_goal = parent["goal"] or ""
                    goal = (
                        f"{parent_goal} → {parent['title']}"
                        if parent_goal
                        else parent["title"]
                    )

            task_id = str(uuid.uuid4())
            now = time.time()
            tags_str = ",".join(tags) if tags else ""

            conn.execute(
                "INSERT INTO tasks "
                "(id, created_at, updated_at, title, description, created_by, "
                "assigned_to, status, priority, tags, result, depends_on, "
                "required_role, goal, parent_task_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, '', ?, ?, ?, ?)",
                (
                    task_id,
                    now,
                    now,
                    title[:_MAX_TEXT],
                    (description or "")[:_MAX_TEXT],
                    created_by,
                    assigned_to,
                    priority,
                    tags_str,
                    depends_on,
                    required_role,
                    (goal or "")[:_MAX_TEXT],
                    parent_task_id,
                ),
            )
            conn.commit()

            # Notify assigned agent via messaging
            if notify and assigned_to:
                post_message(
                    "system", "task_assigned", title[:_MAX_TEXT], to_agent=assigned_to
                )

            return task_id
        finally:
            conn.close()
    except Exception:
        return None


def claim_next_task(
    agent_id: str, role: Optional[str] = None, tag: str = ""
) -> Optional[Dict[str, Any]]:
    """Atomically claim the highest-priority pending task.

    Uses BEGIN EXCLUSIVE to prevent two agents from claiming the same task.
    Respects depends_on (skips tasks with unfinished dependencies),
    required_role (skips tasks requiring a different role), and tag filtering.
    """
    try:
        conn = _get_conn()
        try:
            conn.execute("BEGIN EXCLUSIVE")

            conditions = ["status = 'pending'"]
            params: list = []

            # Dependency check: only claim if dependency is done or NULL
            conditions.append(
                "(depends_on IS NULL OR depends_on IN "
                "(SELECT id FROM tasks WHERE status = 'done'))"
            )

            # Role check
            if role:
                conditions.append("(required_role IS NULL OR required_role = ?)")
                params.append(role)
            else:
                conditions.append("required_role IS NULL")

            # Tag filter
            if tag:
                conditions.append("tags LIKE ?")
                params.append(f"%{tag}%")

            where = " AND ".join(conditions)
            row = conn.execute(
                f"SELECT * FROM tasks WHERE {where} "
                "ORDER BY priority ASC, created_at ASC LIMIT 1",
                params,
            ).fetchone()

            if not row:
                conn.execute("COMMIT")
                return None

            task = _row_to_dict(row)
            conn.execute(
                "UPDATE tasks SET status = 'assigned', assigned_to = ?, updated_at = ? "
                "WHERE id = ?",
                (agent_id, time.time(), task["id"]),
            )
            conn.execute("COMMIT")
            task["status"] = "assigned"
            task["assigned_to"] = agent_id
            return task
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            conn.close()
    except Exception:
        return None


def update_task(task_id: str, status: str, result: str = "") -> bool:
    """Update a task's status and optional result."""
    if status not in VALID_STATUSES:
        return False
    try:
        conn = _get_conn()
        try:
            cursor = conn.execute(
                "UPDATE tasks SET status = ?, result = ?, updated_at = ? WHERE id = ?",
                (status, (result or "")[:_MAX_TEXT], time.time(), task_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()
    except Exception:
        return False


def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    """Get a single task by ID."""
    try:
        conn = _get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            return _row_to_dict(row)
        finally:
            conn.close()
    except Exception:
        return None


def list_tasks(
    status: Optional[str] = None,
    agent_id: Optional[str] = None,
    tag: Optional[str] = None,
    parent_task_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List tasks with optional filters. All filters are combinable."""
    try:
        conn = _get_conn()
        try:
            conditions: list = []
            params: list = []

            if status:
                conditions.append("status = ?")
                params.append(status)
            if agent_id:
                conditions.append("(assigned_to = ? OR created_by = ?)")
                params.extend([agent_id, agent_id])
            if tag:
                conditions.append("tags LIKE ?")
                params.append(f"%{tag}%")
            if parent_task_id:
                conditions.append("parent_task_id = ?")
                params.append(parent_task_id)

            where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
            rows = conn.execute(
                f"SELECT * FROM tasks{where} ORDER BY priority ASC, created_at ASC",
                params,
            ).fetchall()
            return _rows_to_dicts(rows)
        finally:
            conn.close()
    except Exception:
        return []


def cancel_stale(timeout_s: int = 300) -> int:
    """Cancel assigned/running tasks not updated within timeout_s. Returns count."""
    try:
        cutoff = time.time() - timeout_s
        conn = _get_conn()
        try:
            cursor = conn.execute(
                "UPDATE tasks SET status = 'cancelled', updated_at = ? "
                "WHERE status IN ('assigned', 'running') AND updated_at < ?",
                (time.time(), cutoff),
            )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()
    except Exception:
        return 0


def archive_tasks(older_than_hours: int = 48) -> int:
    """Delete completed/failed/cancelled tasks older than threshold. Returns count."""
    try:
        cutoff = time.time() - (older_than_hours * 3600)
        conn = _get_conn()
        try:
            cursor = conn.execute(
                "DELETE FROM tasks WHERE status IN ('done', 'failed', 'cancelled') "
                "AND updated_at < ?",
                (cutoff,),
            )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()
    except Exception:
        return 0


# ===================================================================
# BRIDGE
# ===================================================================


def complete_task(task_id: str, result: str, broadcast: bool = True) -> bool:
    """Mark a task done and optionally broadcast completion to the channel."""
    ok = update_task(task_id, "done", result)
    if ok and broadcast:
        task = get_task(task_id)
        if task:
            from_agent = task.get("assigned_to") or "system"
            post_message(
                from_agent,
                "task_complete",
                f"{task['title']}: {result}"[:_MAX_TEXT],
            )
    return ok
