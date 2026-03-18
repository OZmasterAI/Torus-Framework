#!/usr/bin/env python3
"""Shadow DAG conversation storage — SQLite-backed conversation tree.

Mirrors Claude Code's conversation as a parallel DAG with branching support.
Schema matches go_sdk_agent's dag.go: nodes + branches tables.

All public methods are fail-open — exceptions are caught and logged to stderr.
"""

import json
import os
import secrets
import sqlite3
import time
import threading

_DAG_SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    parent_id TEXT DEFAULT '',
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    model TEXT DEFAULT '',
    provider TEXT DEFAULT '',
    timestamp INTEGER NOT NULL,
    token_count INTEGER DEFAULT 0,
    metadata TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_nodes_parent ON nodes(parent_id);

CREATE TABLE IF NOT EXISTS branches (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    head_node_id TEXT DEFAULT '',
    forked_from TEXT DEFAULT ''
);
"""


def _gen_id(prefix="nd_"):
    return prefix + secrets.token_hex(8)


class ConversationDAG:
    """SQLite-backed conversation DAG with branching."""

    def __init__(self, db_path):
        self._db_path = db_path
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA busy_timeout=5000")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.executescript(_DAG_SCHEMA)

        # Migration: add metadata column if missing
        try:
            self._db.execute("ALTER TABLE nodes ADD COLUMN metadata TEXT DEFAULT '{}'")
        except sqlite3.OperationalError:
            pass  # Column already exists

        self._hooks = None
        self._branch_id = self._init_branch()

    def _init_branch(self):
        """Pick or create the active branch."""
        row = self._db.execute("SELECT COUNT(*) FROM branches").fetchone()
        if row[0] == 0:
            bid = _gen_id("br_")
            self._db.execute(
                "INSERT INTO branches (id, name, head_node_id) VALUES (?, ?, ?)",
                (bid, "main", ""),
            )
            self._db.commit()
            return bid
        # Pick branch with most recent head node timestamp
        row = self._db.execute(
            """
            SELECT b.id FROM branches b
            LEFT JOIN nodes n ON n.id = b.head_node_id
            ORDER BY COALESCE(n.timestamp, 0) DESC
            LIMIT 1
            """
        ).fetchone()
        return row[0] if row else _gen_id("br_")

    def set_hooks(self, registry):
        """Attach a DAGHookRegistry for mutation events."""
        self._hooks = registry

    def add_node(
        self,
        parent_id,
        role,
        content,
        model="",
        provider="",
        token_count=0,
        metadata=None,
    ):
        """Insert a node and advance the branch head. Returns node ID."""
        nid = _gen_id("nd_")
        ts = int(time.time() * 1000)
        meta_json = json.dumps(metadata) if metadata else "{}"
        self._db.execute(
            "INSERT INTO nodes (id, parent_id, role, content, model, provider, "
            "timestamp, token_count, metadata) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                nid,
                parent_id,
                role,
                content,
                model,
                provider,
                ts,
                token_count,
                meta_json,
            ),
        )
        self._db.execute(
            "UPDATE branches SET head_node_id = ? WHERE id = ?",
            (nid, self._branch_id),
        )
        self._db.commit()
        if self._hooks:
            self._hooks.fire(
                "on_node_added",
                {
                    "node_id": nid,
                    "parent_id": parent_id,
                    "role": role,
                    "branch_id": self._branch_id,
                },
            )
        return nid

    def get_node(self, node_id):
        """Return a node dict or None."""
        row = self._db.execute(
            "SELECT id, parent_id, role, content, model, provider, "
            "timestamp, token_count, metadata FROM nodes WHERE id = ?",
            (node_id,),
        ).fetchone()
        if not row:
            return None
        return self._row_to_dict(row)

    def _row_to_dict(self, row):
        meta = {}
        try:
            meta = json.loads(row[8]) if row[8] else {}
        except (json.JSONDecodeError, TypeError):
            pass
        return {
            "id": row[0],
            "parent_id": row[1],
            "role": row[2],
            "content": row[3],
            "model": row[4],
            "provider": row[5],
            "timestamp": row[6],
            "token_count": row[7],
            "metadata": meta,
        }

    def get_ancestors(self, node_id):
        """Walk parent chain to root, return in chronological order (oldest first)."""
        ancestors = []
        cur = node_id
        seen = set()
        while cur and cur not in seen:
            seen.add(cur)
            row = self._db.execute(
                "SELECT id, parent_id, role, content, model, provider, "
                "timestamp, token_count, metadata FROM nodes WHERE id = ?",
                (cur,),
            ).fetchone()
            if not row:
                break
            ancestors.append(self._row_to_dict(row))
            cur = row[1]  # parent_id
        ancestors.reverse()
        return ancestors

    def prompt_from(self, node_id):
        """Build message list from ancestor chain."""
        ancestors = self.get_ancestors(node_id)
        return [{"role": n["role"], "content": n["content"]} for n in ancestors]

    def get_head(self):
        """Return current branch's head node ID (empty string if no messages)."""
        row = self._db.execute(
            "SELECT head_node_id FROM branches WHERE id = ?",
            (self._branch_id,),
        ).fetchone()
        return row[0] if row else ""

    def reset_head(self):
        """Clear head — next message starts fresh on same branch."""
        self._db.execute(
            "UPDATE branches SET head_node_id = '' WHERE id = ?",
            (self._branch_id,),
        )
        self._db.commit()
        if self._hooks:
            self._hooks.fire("on_branch_reset", {"branch_id": self._branch_id})

    def new_branch(self, name):
        """Create a fresh branch (empty head), record fork point from current head."""
        head = self.get_head()
        bid = _gen_id("br_")
        self._db.execute(
            "INSERT INTO branches (id, name, head_node_id, forked_from) VALUES (?,?,?,?)",
            (bid, name, "", head),
        )
        self._db.commit()
        self._branch_id = bid
        if self._hooks:
            self._hooks.fire(
                "on_branch_created",
                {
                    "branch_id": bid,
                    "name": name,
                    "forked_from": head,
                },
            )
        return bid

    def branch_from(self, from_node_id, name):
        """Create branch continuing from an existing node (inherits history)."""
        bid = _gen_id("br_")
        self._db.execute(
            "INSERT INTO branches (id, name, head_node_id, forked_from) VALUES (?,?,?,?)",
            (bid, name, from_node_id, from_node_id),
        )
        self._db.commit()
        self._branch_id = bid
        if self._hooks:
            self._hooks.fire(
                "on_branch_created",
                {
                    "branch_id": bid,
                    "name": name,
                    "forked_from": from_node_id,
                },
            )
        return bid

    def switch_branch(self, branch_id):
        """Switch to an existing branch."""
        row = self._db.execute(
            "SELECT COUNT(*) FROM branches WHERE id = ?", (branch_id,)
        ).fetchone()
        if row[0] == 0:
            raise ValueError(f"branch {branch_id} not found")
        old = self._branch_id
        self._branch_id = branch_id
        if self._hooks:
            self._hooks.fire(
                "on_branch_switch",
                {
                    "old_branch": old,
                    "new_branch": branch_id,
                },
            )

    def list_branches(self):
        """Return all branches as dicts."""
        rows = self._db.execute(
            "SELECT id, name, head_node_id, forked_from FROM branches"
        ).fetchall()
        return [
            {"id": r[0], "name": r[1], "head_node_id": r[2], "forked_from": r[3]}
            for r in rows
        ]

    def current_branch_id(self):
        return self._branch_id

    def current_branch_info(self):
        """Return branch ID, name, head, message count, total branches."""
        row = self._db.execute(
            "SELECT name, head_node_id FROM branches WHERE id = ?",
            (self._branch_id,),
        ).fetchone()
        name = row[0] if row else "unknown"
        head = row[1] if row else ""
        msg_count = len(self.get_ancestors(head)) if head else 0
        total = self._db.execute("SELECT COUNT(*) FROM branches").fetchone()[0]
        return {
            "branch_id": self._branch_id,
            "name": name,
            "head_node_id": head,
            "msg_count": msg_count,
            "total_branches": total,
        }

    def update_metadata(self, node_id, updates):
        """Merge updates into a node's metadata JSON."""
        node = self.get_node(node_id)
        if not node:
            return
        meta = node["metadata"]
        meta.update(updates)
        self._db.execute(
            "UPDATE nodes SET metadata = ? WHERE id = ?",
            (json.dumps(meta), node_id),
        )
        self._db.commit()

    def build_summary(self, max_nodes=10):
        """Build a compact summary of the current branch for post-compaction injection."""
        head = self.get_head()
        if not head:
            return ""
        ancestors = self.get_ancestors(head)
        recent = ancestors[-max_nodes:] if len(ancestors) > max_nodes else ancestors
        lines = []
        turn = 0
        for node in recent:
            role = node["role"]
            content = node["content"][:200]
            if role == "user":
                turn += 1
                lines.append(f"[turn {turn}] user: {content}")
            elif role == "assistant":
                lines.append(f"  assistant: {content}")
            elif role == "tool":
                try:
                    td = json.loads(content)
                    tname = td.get("tool_name", "tool")
                    lines.append(f"  tool({tname})")
                except (json.JSONDecodeError, TypeError):
                    lines.append(f"  tool: {content[:80]}")
        summary = "\n".join(lines)
        if len(summary) > 1500:
            summary = summary[:1500] + "\n..."
        return summary

    def close(self):
        self._db.close()


# --- Singleton factory ---

_instances = {}
_lock = threading.Lock()


def get_session_dag(session_id="main"):
    """Return a cached ConversationDAG instance for the given session.

    All sessions share the same DB file — session_id is reserved for future
    per-session branch isolation.
    """
    with _lock:
        if session_id not in _instances:
            db_path = os.path.join(
                os.path.expanduser("~"), ".claude", "data", "conversations.db"
            )
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            _instances[session_id] = ConversationDAG(db_path)
        return _instances[session_id]
