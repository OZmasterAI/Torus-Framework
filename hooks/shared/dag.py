#!/usr/bin/env python3
"""Shadow DAG conversation storage — SQLite-backed conversation tree.

Mirrors Claude Code's conversation as a parallel DAG with branching support.
Schema matches go_sdk_agent's dag.go: nodes + branches tables.

All public methods are fail-open — exceptions are caught and logged to stderr.
"""

import datetime
import json
import os
import secrets
import sqlite3
import sys
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
    forked_from TEXT DEFAULT '',
    metadata TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS knowledge (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    context TEXT DEFAULT '',
    tags TEXT DEFAULT '',
    tier INTEGER DEFAULT 1,
    memory_type TEXT DEFAULT '',
    state_type TEXT DEFAULT '',
    cluster_id TEXT DEFAULT '',
    retrieval_count INTEGER DEFAULT 0,
    quality_score REAL DEFAULT 0.0,
    source_node_id TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_knowledge_source ON knowledge(source_node_id);

CREATE TABLE IF NOT EXISTS observations (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    tags TEXT DEFAULT '',
    tier INTEGER DEFAULT 0,
    retrieval_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    metadata TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS fix_outcomes (
    id TEXT PRIMARY KEY,
    chain_id TEXT NOT NULL,
    error_description TEXT NOT NULL,
    strategy TEXT DEFAULT '',
    outcome TEXT DEFAULT '',
    node_id TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    metadata TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_fix_chain ON fix_outcomes(chain_id);

CREATE TABLE IF NOT EXISTS node_edges (
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    weight REAL DEFAULT 1.0,
    created_at TEXT NOT NULL,
    PRIMARY KEY (source_id, target_id, edge_type)
);

CREATE TABLE IF NOT EXISTS embeddings (
    id TEXT PRIMARY KEY,
    source_table TEXT NOT NULL,
    source_id TEXT NOT NULL,
    vector BLOB NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_edges_target ON node_edges(target_id);

CREATE INDEX IF NOT EXISTS idx_emb_source ON embeddings(source_table, source_id);
"""


def _gen_id(prefix="nd_"):
    return prefix + secrets.token_hex(8)


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


class ConversationDAG:
    """SQLite-backed conversation DAG with branching."""

    def __init__(self, db_path):
        self._db_path = db_path
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA busy_timeout=5000")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.execute("PRAGMA cache_size=-64000")  # 64MB page cache
        self._db.execute("PRAGMA mmap_size=268435456")  # 256MB mmap
        self._db.execute("PRAGMA temp_store=MEMORY")
        self._db.executescript(_DAG_SCHEMA)
        # Index for DAG-to-memory promotion lookups
        try:
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_source ON knowledge(source_node_id)"
            )
            self._db.commit()
        except sqlite3.OperationalError:
            pass

        # Migration: add metadata column if missing
        try:
            self._db.execute("ALTER TABLE nodes ADD COLUMN metadata TEXT DEFAULT '{}'")
        except sqlite3.OperationalError:
            pass  # Column already exists
        try:
            self._db.execute(
                "ALTER TABLE branches ADD COLUMN metadata TEXT DEFAULT '{}'"
            )
        except sqlite3.OperationalError:
            pass  # Column already exists

        # FTS5 full-text indexes + sync triggers
        self._init_fts5()

        self._hooks = None
        self._branch_id = self._init_branch()

    def _init_fts5(self):
        """Create FTS5 virtual tables and sync triggers if they don't exist."""
        try:
            self._db.executescript("""
                CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
                    content, role UNINDEXED,
                    content=nodes, content_rowid=rowid
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
                    content, tags,
                    content=knowledge, content_rowid=rowid
                );
            """)
            # Sync triggers — wrap each in try/except since IF NOT EXISTS
            # isn't supported for triggers in all SQLite versions
            for sql in [
                """CREATE TRIGGER nodes_fts_ai AFTER INSERT ON nodes BEGIN
                    INSERT INTO nodes_fts(rowid, content, role)
                    VALUES (new.rowid, new.content, new.role);
                END""",
                """CREATE TRIGGER nodes_fts_ad AFTER DELETE ON nodes BEGIN
                    INSERT INTO nodes_fts(nodes_fts, rowid, content, role)
                    VALUES ('delete', old.rowid, old.content, old.role);
                END""",
                """CREATE TRIGGER knowledge_fts_ai AFTER INSERT ON knowledge BEGIN
                    INSERT INTO knowledge_fts(rowid, content, tags)
                    VALUES (new.rowid, new.content, new.tags);
                END""",
                """CREATE TRIGGER knowledge_fts_ad AFTER DELETE ON knowledge BEGIN
                    INSERT INTO knowledge_fts(knowledge_fts, rowid, content, tags)
                    VALUES ('delete', old.rowid, old.content, old.tags);
                END""",
            ]:
                try:
                    self._db.execute(sql)
                except sqlite3.OperationalError as e:
                    if "already exists" not in str(e):
                        print(f"[DAG] FTS5 trigger error: {e}", file=sys.stderr)
            self._db.commit()
        except Exception as e:
            print(f"[DAG] FTS5 init failed: {e}", file=sys.stderr)  # falls back to LIKE

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
        project=None,
        subproject=None,
    ):
        """Insert a node and advance the branch head. Returns node ID."""
        nid = _gen_id("nd_")
        ts = int(time.time() * 1000)
        meta = metadata or {}
        if project:
            meta["project"] = project
        if subproject:
            meta["subproject"] = subproject
        meta_json = json.dumps(meta)
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

    def new_branch(self, name, project=None, subproject=None):
        """Create a fresh branch (empty head), record fork point from current head."""
        head = self.get_head()
        bid = _gen_id("br_")
        meta = {}
        if project:
            meta["project"] = project
        if subproject:
            meta["subproject"] = subproject
        self._db.execute(
            "INSERT INTO branches (id, name, head_node_id, forked_from, metadata) VALUES (?,?,?,?,?)",
            (bid, name, "", head, json.dumps(meta) if meta else "{}"),
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
                    "project": project,
                    "subproject": subproject,
                },
            )
        return bid

    def branch_from(self, from_node_id, name, project=None, subproject=None):
        """Create branch continuing from an existing node (inherits history)."""
        bid = _gen_id("br_")
        meta = {}
        if project:
            meta["project"] = project
        if subproject:
            meta["subproject"] = subproject
        self._db.execute(
            "INSERT INTO branches (id, name, head_node_id, forked_from, metadata) VALUES (?,?,?,?,?)",
            (bid, name, from_node_id, from_node_id, json.dumps(meta) if meta else "{}"),
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

    def list_branches(self, project_scope=None):
        """Return branches as dicts, optionally scoped to a project hierarchy.

        project_scope: if set, only return branches where metadata.project matches.
        Hub (None) sees all branches.
        A project scope also includes its subprojects.
        """
        rows = self._db.execute(
            "SELECT id, name, head_node_id, forked_from, metadata FROM branches"
        ).fetchall()
        results = []
        for r in rows:
            meta = {}
            try:
                meta = json.loads(r[4]) if r[4] else {}
            except (json.JSONDecodeError, TypeError):
                pass
            if project_scope:
                branch_project = meta.get("project", "")
                if branch_project != project_scope:
                    continue
            results.append(
                {
                    "id": r[0],
                    "name": r[1],
                    "head_node_id": r[2],
                    "forked_from": r[3],
                    "metadata": meta,
                }
            )
        return results

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

    # --- Phase 2: search, labels, resolve ---

    def search_nodes(
        self,
        query,
        max_results=10,
        role_filter=None,
        branch_id=None,
        project_scope=None,
    ):
        """Search node content by keyword (LIKE). Returns matching nodes.

        project_scope: filter to nodes with matching project in metadata.
        Hub (None) searches all nodes.
        """
        sql = "SELECT id, parent_id, role, content, model, provider, timestamp, token_count, metadata FROM nodes WHERE content LIKE ?"
        params = [f"%{query}%"]
        if role_filter:
            sql += " AND role = ?"
            params.append(role_filter)
        if project_scope:
            sql += " AND json_extract(metadata, '$.project') = ?"
            params.append(project_scope)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(str(max_results))
        rows = self._db.execute(sql, params).fetchall()
        results = [self._row_to_dict(r) for r in rows]
        if branch_id:
            branch_nodes = set()
            row = self._db.execute(
                "SELECT head_node_id FROM branches WHERE id = ?", (branch_id,)
            ).fetchone()
            if row and row[0]:
                for anc in self.get_ancestors(row[0]):
                    branch_nodes.add(anc["id"])
            results = [n for n in results if n["id"] in branch_nodes]
        return results

    def label_branch(self, branch_id, label):
        """Set a task label on a branch (stored in name field as 'name:label')."""
        row = self._db.execute(
            "SELECT name FROM branches WHERE id = ?", (branch_id,)
        ).fetchone()
        if not row:
            return
        base_name = row[0].split(":")[0]  # Strip existing label
        self._db.execute(
            "UPDATE branches SET name = ? WHERE id = ?",
            (f"{base_name}:{label}", branch_id),
        )
        self._db.commit()

    def get_branch_label(self, branch_id=None):
        """Get the task label for a branch (or current branch)."""
        bid = branch_id or self._branch_id
        row = self._db.execute(
            "SELECT name FROM branches WHERE id = ?", (bid,)
        ).fetchone()
        if not row:
            return ""
        parts = row[0].split(":", 1)
        return parts[1] if len(parts) > 1 else ""

    def resolve_branch(self, branch_id):
        """Mark a branch as resolved by prefixing name with 'resolved/'."""
        row = self._db.execute(
            "SELECT name FROM branches WHERE id = ?", (branch_id,)
        ).fetchone()
        if not row:
            return
        name = row[0]
        if not name.startswith("resolved/"):
            self._db.execute(
                "UPDATE branches SET name = ? WHERE id = ?",
                (f"resolved/{name}", branch_id),
            )
            self._db.commit()

    def is_branch_resolved(self, branch_id):
        """Check if a branch is marked as resolved."""
        row = self._db.execute(
            "SELECT name FROM branches WHERE id = ?", (branch_id,)
        ).fetchone()
        return row[0].startswith("resolved/") if row else False

    def get_active_branches(self):
        """Return non-resolved branches."""
        return [
            b for b in self.list_branches() if not b["name"].startswith("resolved/")
        ]

    def trace_node(self, node_id, context_lines=3):
        """Return a formatted conversation excerpt around a node."""
        ancestors = self.get_ancestors(node_id)
        if not ancestors:
            return ""
        # Find the target node's index
        idx = next((i for i, a in enumerate(ancestors) if a["id"] == node_id), -1)
        if idx == -1:
            return ""
        start = max(0, idx - context_lines)
        end = min(len(ancestors), idx + context_lines + 1)
        lines = []
        for a in ancestors[start:end]:
            marker = ">>>" if a["id"] == node_id else "   "
            content = a["content"][:150]
            lines.append(f"{marker} [{a['role']}] {content}")
        return "\n".join(lines)

    def start_session_branch(self, session_num, project=None, subproject=None):
        """Create a new branch for a session. Called once at SessionStart.

        Branch name encodes the hierarchy: 'session-476', 'chainovi/session-12',
        'chainovi/frontend/session-3'.
        """
        parts = []
        if project:
            parts.append(project)
        if subproject:
            parts.append(subproject)
        parts.append(f"session-{session_num}")
        name = "/".join(parts)
        return self.new_branch(name, project=project, subproject=subproject)

    # --- Graph traversal ---

    def find_related(self, node_id, max_hops=3):
        """Return all nodes reachable from node_id within max_hops steps.

        Traverses both upward (via parent_id) and downward (via children)
        using recursive CTEs.  Returns a list of node dicts ordered by hop
        distance, then by timestamp.  The seed node itself is excluded.
        Fail-open -- returns [] on any error.
        """
        try:
            rows = self._db.execute(
                """
                WITH RECURSIVE
                upward(id, hops) AS (
                    SELECT parent_id, 1
                    FROM nodes WHERE id = ? AND parent_id != ''
                    UNION
                    SELECT n.parent_id, u.hops + 1
                    FROM nodes n
                    JOIN upward u ON n.id = u.id
                    WHERE u.hops < ? AND n.parent_id != ''
                ),
                downward(id, hops) AS (
                    SELECT id, 1
                    FROM nodes WHERE parent_id = ?
                    UNION
                    SELECT n.id, d.hops + 1
                    FROM nodes n
                    JOIN downward d ON n.parent_id = d.id
                    WHERE d.hops < ?
                ),
                combined(id, hops) AS (
                    SELECT id, hops FROM upward
                    UNION
                    SELECT id, hops FROM downward
                )
                SELECT DISTINCT n.id, n.parent_id, n.role, n.content,
                       n.model, n.provider, n.timestamp, n.token_count,
                       n.metadata, MIN(c.hops) AS hops
                FROM nodes n
                JOIN combined c ON n.id = c.id
                GROUP BY n.id
                ORDER BY hops, n.timestamp
                """,
                (node_id, max_hops, node_id, max_hops),
            ).fetchall()
            results = []
            for r in rows:
                d = self._row_to_dict(r[:9])
                d["hops"] = r[9]
                results.append(d)
            return results
        except Exception as exc:
            print(f"[dag] find_related error: {exc}", file=sys.stderr)
            return []

    def get_path(self, from_id, to_id):
        """Return the ancestor path between two nodes, if one exists.

        Checks both directions: from_id upward to to_id, and to_id upward
        to from_id.  Uses a recursive CTE to walk the parent chain.
        Returns an ordered list of node dicts (from_id first, to_id last),
        or [] if no direct ancestor path exists.  Fail-open.
        """
        try:
            if from_id == to_id:
                node = self.get_node(from_id)
                return [node] if node else []

            def _ancestors_cte(start, stop):
                rows = self._db.execute(
                    """
                    WITH RECURSIVE anc(id, parent_id, role, content, model,
                                       provider, timestamp, token_count,
                                       metadata, depth) AS (
                        SELECT id, parent_id, role, content, model,
                               provider, timestamp, token_count, metadata, 0
                        FROM nodes WHERE id = ?
                        UNION ALL
                        SELECT n.id, n.parent_id, n.role, n.content, n.model,
                               n.provider, n.timestamp, n.token_count,
                               n.metadata, a.depth + 1
                        FROM nodes n
                        JOIN anc a ON n.id = a.parent_id
                        WHERE a.parent_id != ''
                    )
                    SELECT id, parent_id, role, content, model,
                           provider, timestamp, token_count, metadata, depth
                    FROM anc
                    ORDER BY depth
                    """,
                    (start,),
                ).fetchall()
                chain = [self._row_to_dict(r[:9]) for r in rows]
                ids = [n["id"] for n in chain]
                if stop not in ids:
                    return []
                cut = ids.index(stop)
                return chain[: cut + 1]

            path = _ancestors_cte(from_id, to_id)
            if path:
                return path

            path_rev = _ancestors_cte(to_id, from_id)
            if path_rev:
                path_rev.reverse()
                return path_rev

            return []
        except Exception as exc:
            print(f"[dag] get_path error: {exc}", file=sys.stderr)
            return []


    # --- Stats & Metrics (Task #13) ---

    def get_stats(self):
        """Return comprehensive DAG stats dict."""
        try:
            node_count = self._db.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            branch_count = self._db.execute("SELECT COUNT(*) FROM branches").fetchone()[0]
            knowledge_count = self._db.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
            embedding_count = self._db.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
            edge_count = self._db.execute("SELECT COUNT(*) FROM node_edges").fetchone()[0]
            observation_count = self._db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
            fix_count = self._db.execute("SELECT COUNT(*) FROM fix_outcomes").fetchone()[0]

            promotion_count = self._db.execute(
                "SELECT COUNT(*) FROM nodes WHERE metadata LIKE ? OR metadata LIKE ?",
                ('%"promoted": true%', '%"promoted":true%'),
            ).fetchone()[0]

            depths = []
            heads = self._db.execute(
                "SELECT head_node_id FROM branches WHERE head_node_id != ''"
            ).fetchall()
            for (head,) in heads:
                depth = len(self.get_ancestors(head))
                depths.append(depth)
            avg_branch_depth = sum(depths) / len(depths) if depths else 0.0

            active_branch_count = self._db.execute(
                "SELECT COUNT(*) FROM branches WHERE name NOT LIKE 'resolved/%'"
            ).fetchone()[0]

            return {
                "node_count": node_count,
                "branch_count": branch_count,
                "knowledge_count": knowledge_count,
                "embedding_count": embedding_count,
                "active_branch_count": active_branch_count,
                "avg_branch_depth": round(avg_branch_depth, 1),
                "edge_count": edge_count,
                "observation_count": observation_count,
                "fix_count": fix_count,
                "promotion_count": promotion_count,
            }
        except Exception as e:
            print(f"[DAG] get_stats failed: {e}", file=sys.stderr)
            return {}

    def get_session_stats(self, branch_id=None):
        """Return stats for a specific branch/session."""
        bid = branch_id or self._branch_id
        try:
            row = self._db.execute(
                "SELECT name, head_node_id, forked_from FROM branches WHERE id = ?",
                (bid,),
            ).fetchone()
            if not row:
                return {}
            name, head, forked_from = row
            ancestors = self.get_ancestors(head) if head else []
            node_count = len(ancestors)
            roles = {}
            total_tokens = 0
            for a in ancestors:
                roles[a["role"]] = roles.get(a["role"], 0) + 1
                total_tokens += a.get("token_count", 0)

            knowledge_count = 0
            if ancestors:
                node_ids = [a["id"] for a in ancestors]
                placeholders = ",".join("?" * len(node_ids))
                knowledge_count = self._db.execute(
                    f"SELECT COUNT(*) FROM knowledge WHERE source_node_id IN ({placeholders})",
                    node_ids,
                ).fetchone()[0]

            return {
                "branch_id": bid,
                "name": name,
                "node_count": node_count,
                "roles": roles,
                "total_tokens": total_tokens,
                "knowledge_count": knowledge_count,
                "forked_from": forked_from,
            }
        except Exception as e:
            print(f"[DAG] get_session_stats failed: {e}", file=sys.stderr)
            return {}

    # --- FTS5 Maintenance (Task #11) ---

    def optimize_fts(self):
        """Run FTS5 optimize command to merge b-tree segments. Call on session close."""
        try:
            self._db.execute("INSERT INTO nodes_fts(nodes_fts) VALUES('optimize')")
            self._db.execute("INSERT INTO knowledge_fts(knowledge_fts) VALUES('optimize')")
            self._db.commit()
            return True
        except Exception as e:
            print(f"[DAG] optimize_fts failed: {e}", file=sys.stderr)
            return False

    def rebuild_fts(self):
        """Full FTS5 rebuild - re-index all content. Use sparingly."""
        try:
            self._db.execute("INSERT INTO nodes_fts(nodes_fts) VALUES('rebuild')")
            self._db.execute("INSERT INTO knowledge_fts(knowledge_fts) VALUES('rebuild')")
            self._db.commit()
            return True
        except Exception as e:
            print(f"[DAG] rebuild_fts failed: {e}", file=sys.stderr)
            return False

    # --- Soft Delete & Archival (Task #10) ---

    def _ensure_archive_table(self):
        """Create archive table if it doesn't exist."""
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS nodes_archive (
                id TEXT PRIMARY KEY,
                parent_id TEXT DEFAULT '',
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                model TEXT DEFAULT '',
                provider TEXT DEFAULT '',
                timestamp INTEGER NOT NULL,
                token_count INTEGER DEFAULT 0,
                metadata TEXT DEFAULT '{}',
                archived_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS branches_archive (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                head_node_id TEXT DEFAULT '',
                forked_from TEXT DEFAULT '',
                metadata TEXT DEFAULT '{}',
                archived_at TEXT NOT NULL
            );
        """)

    def soft_delete_node(self, node_id):
        """Mark a node as deleted (sets metadata.deleted=true). Does not remove from DB."""
        try:
            self.update_metadata(node_id, {"deleted": True, "deleted_at": _now_iso()})
            return True
        except Exception as e:
            print(f"[DAG] soft_delete_node failed: {e}", file=sys.stderr)
            return False

    def archive_old_sessions(self, days=30):
        """Move nodes from branches older than days to archive tables.

        Returns count of archived nodes.
        """
        try:
            self._ensure_archive_table()
            cutoff_ms = int((time.time() - days * 86400) * 1000)
            now_iso = _now_iso()

            old_branches = self._db.execute(
                "SELECT b.id, b.name, b.head_node_id, b.forked_from, b.metadata "
                "FROM branches b "
                "LEFT JOIN nodes n ON n.id = b.head_node_id "
                "WHERE COALESCE(n.timestamp, 0) < ? AND COALESCE(n.timestamp, 0) > 0 "
                "AND b.id != ?",
                (cutoff_ms, self._branch_id),
            ).fetchall()

            archived_count = 0
            for bid, bname, bhead, bforked, bmeta in old_branches:
                if not bhead:
                    continue
                ancestors = self.get_ancestors(bhead)
                node_ids = [a["id"] for a in ancestors]

                for nid in node_ids:
                    node = self.get_node(nid)
                    if not node:
                        continue
                    try:
                        self._db.execute(
                            "INSERT OR IGNORE INTO nodes_archive "
                            "(id, parent_id, role, content, model, provider, "
                            "timestamp, token_count, metadata, archived_at) "
                            "VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (node["id"], node["parent_id"], node["role"],
                             node["content"], node["model"], node["provider"],
                             node["timestamp"], node["token_count"],
                             json.dumps(node["metadata"]), now_iso),
                        )
                        archived_count += 1
                    except Exception:
                        continue

                self._db.execute(
                    "INSERT OR IGNORE INTO branches_archive "
                    "(id, name, head_node_id, forked_from, metadata, archived_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (bid, bname, bhead, bforked, bmeta or "{}", now_iso),
                )

                if node_ids:
                    placeholders = ",".join("?" * len(node_ids))
                    self._db.execute(
                        f"DELETE FROM nodes WHERE id IN ({placeholders})", node_ids
                    )
                self._db.execute("DELETE FROM branches WHERE id = ?", (bid,))

            self._db.commit()
            return archived_count
        except Exception as e:
            print(f"[DAG] archive_old_sessions failed: {e}", file=sys.stderr)
            return 0

    def purge_archived(self, older_than_days=90):
        """Permanently delete archived data older than specified days."""
        try:
            self._ensure_archive_table()
            cutoff = (datetime.datetime.now() - datetime.timedelta(days=older_than_days)).strftime("%Y-%m-%dT%H:%M:%S")
            c1 = self._db.execute(
                "DELETE FROM nodes_archive WHERE archived_at < ?", (cutoff,)
            ).rowcount
            c2 = self._db.execute(
                "DELETE FROM branches_archive WHERE archived_at < ?", (cutoff,)
            ).rowcount
            self._db.commit()
            return c1 + c2
        except Exception as e:
            print(f"[DAG] purge_archived failed: {e}", file=sys.stderr)
            return 0

    def close(self):
        try:
            self._db.execute("PRAGMA optimize")
        except Exception:
            pass
        self._db.close()


# --- Singleton factory ---

_instances = {}
_lock = threading.Lock()


def get_session_dag(session_id="main"):
    """Return a cached ConversationDAG instance for the given session.

    All sessions share the same DB file (B+C model). Session isolation is
    achieved via per-session branches with project/subproject metadata.
    """
    with _lock:
        if session_id not in _instances:
            db_path = os.path.join(
                os.path.expanduser("~"), ".claude", "data", "conversations.db"
            )
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            _instances[session_id] = ConversationDAG(db_path)
        return _instances[session_id]
