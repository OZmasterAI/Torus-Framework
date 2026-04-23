#!/usr/bin/env python3
"""SQLite skill store for Skill MCP v2.

Manages the 6-table schema (skill_records, skill_lineage_parents,
execution_analyses, skill_judgments, skill_tool_deps, skill_tags)
with WAL mode and foreign keys. Used by skill_server_v2.py.
"""

import sqlite3
import uuid
from datetime import datetime, timezone

# Thresholds for health classification (from OpenSpace)
_LOW_COMPLETION_THRESHOLD = 0.35
_FALLBACK_THRESHOLD = 0.4


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid8() -> str:
    return uuid.uuid4().hex[:8]


def init_db(db_path: str) -> sqlite3.Connection:
    """Create/open the skills database with WAL mode and all 6 tables."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS skill_records (
            skill_id               TEXT PRIMARY KEY,
            name                   TEXT NOT NULL,
            description            TEXT NOT NULL DEFAULT '',
            path                   TEXT NOT NULL DEFAULT '',
            is_active              INTEGER NOT NULL DEFAULT 1,
            category               TEXT NOT NULL DEFAULT 'workflow',
            lineage_origin         TEXT NOT NULL DEFAULT 'imported',
            lineage_generation     INTEGER NOT NULL DEFAULT 0,
            lineage_source_task_id TEXT,
            lineage_change_summary TEXT NOT NULL DEFAULT '',
            lineage_content_diff   TEXT NOT NULL DEFAULT '',
            lineage_content_snapshot TEXT NOT NULL DEFAULT '{}',
            lineage_created_at     TEXT NOT NULL,
            lineage_created_by     TEXT NOT NULL DEFAULT '',
            total_selections       INTEGER NOT NULL DEFAULT 0,
            total_applied          INTEGER NOT NULL DEFAULT 0,
            total_completions      INTEGER NOT NULL DEFAULT 0,
            total_fallbacks        INTEGER NOT NULL DEFAULT 0,
            first_seen             TEXT NOT NULL,
            last_updated           TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS skill_lineage_parents (
            skill_id        TEXT NOT NULL REFERENCES skill_records(skill_id) ON DELETE CASCADE,
            parent_skill_id TEXT NOT NULL,
            PRIMARY KEY (skill_id, parent_skill_id)
        );

        CREATE TABLE IF NOT EXISTS execution_analyses (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id                 TEXT NOT NULL UNIQUE,
            timestamp               TEXT NOT NULL,
            task_completed          INTEGER NOT NULL DEFAULT 0,
            execution_note          TEXT NOT NULL DEFAULT '',
            tool_issues             TEXT NOT NULL DEFAULT '[]',
            candidate_for_evolution INTEGER NOT NULL DEFAULT 0,
            evolution_suggestions   TEXT NOT NULL DEFAULT '[]',
            analyzed_by             TEXT NOT NULL DEFAULT '',
            analyzed_at             TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS skill_judgments (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_id    INTEGER NOT NULL REFERENCES execution_analyses(id) ON DELETE CASCADE,
            skill_id       TEXT NOT NULL,
            skill_applied  INTEGER NOT NULL DEFAULT 0,
            note           TEXT NOT NULL DEFAULT '',
            UNIQUE(analysis_id, skill_id)
        );

        CREATE TABLE IF NOT EXISTS skill_tool_deps (
            skill_id TEXT NOT NULL REFERENCES skill_records(skill_id) ON DELETE CASCADE,
            tool_key TEXT NOT NULL,
            critical INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (skill_id, tool_key)
        );

        CREATE TABLE IF NOT EXISTS skill_tags (
            skill_id TEXT NOT NULL REFERENCES skill_records(skill_id) ON DELETE CASCADE,
            tag      TEXT NOT NULL,
            PRIMARY KEY (skill_id, tag)
        );
    """)
    conn.commit()
    return conn


def get_or_create_skill(
    conn: sqlite3.Connection, name: str, description: str = "", path: str = ""
) -> str:
    """Return skill_id for name, creating if needed. Idempotent by name."""
    row = conn.execute(
        "SELECT skill_id FROM skill_records WHERE name = ?", (name,)
    ).fetchone()
    if row:
        return row["skill_id"]

    skill_id = f"{name}__imp_{_uuid8()}"
    now = _now_iso()
    conn.execute(
        """INSERT INTO skill_records
           (skill_id, name, description, path, lineage_created_at, first_seen, last_updated)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (skill_id, name, description, path, now, now, now),
    )
    conn.commit()
    return skill_id


def record_selection(conn: sqlite3.Connection, skill_id: str) -> None:
    """Increment total_selections for a skill."""
    conn.execute(
        """UPDATE skill_records
           SET total_selections = total_selections + 1, last_updated = ?
           WHERE skill_id = ?""",
        (_now_iso(), skill_id),
    )
    conn.commit()


def record_outcome(
    conn: sqlite3.Connection,
    skill_id: str,
    applied: bool = True,
    completed: bool = False,
) -> None:
    """Update quality counters based on outcome.

    Logic matches OpenSpace:
    - applied=True, completed=True  -> +1 applied, +1 completions
    - applied=True, completed=False -> +1 applied
    - applied=False, completed=False -> +1 fallbacks
    - applied=False, completed=True -> no counter (selection-only)
    """
    applied_inc = 1 if applied else 0
    completed_inc = 1 if (applied and completed) else 0
    fallback_inc = 1 if (not applied and not completed) else 0

    conn.execute(
        """UPDATE skill_records SET
           total_applied     = total_applied + ?,
           total_completions = total_completions + ?,
           total_fallbacks   = total_fallbacks + ?,
           last_updated      = ?
           WHERE skill_id = ?""",
        (applied_inc, completed_inc, fallback_inc, _now_iso(), skill_id),
    )
    conn.commit()


def get_skill_record(conn: sqlite3.Connection, skill_id: str) -> dict | None:
    """Fetch a single skill record as a dict."""
    row = conn.execute(
        "SELECT * FROM skill_records WHERE skill_id = ?", (skill_id,)
    ).fetchone()
    return dict(row) if row else None


def get_skill_by_name(conn: sqlite3.Connection, name: str) -> dict | None:
    """Fetch a skill record by name."""
    row = conn.execute("SELECT * FROM skill_records WHERE name = ?", (name,)).fetchone()
    return dict(row) if row else None


def get_all_skill_records(conn: sqlite3.Connection) -> list[dict]:
    """Fetch all active skill records."""
    rows = conn.execute(
        "SELECT * FROM skill_records WHERE is_active = 1 ORDER BY name"
    ).fetchall()
    return [dict(r) for r in rows]


def computed_rates(rec: dict) -> dict:
    """Compute quality rates from counter fields. Safe for zero division."""
    sel = rec.get("total_selections", 0)
    app = rec.get("total_applied", 0)
    comp = rec.get("total_completions", 0)
    fall = rec.get("total_fallbacks", 0)
    return {
        "applied_rate": app / sel if sel else 0.0,
        "completion_rate": comp / app if app else 0.0,
        "effective_rate": comp / sel if sel else 0.0,
        "fallback_rate": fall / sel if sel else 0.0,
    }


def get_skill_health(conn: sqlite3.Connection) -> list[dict]:
    """Return health report for all active skills with computed rates."""
    records = get_all_skill_records(conn)
    results = []
    for rec in records:
        rates = computed_rates(rec)
        # Classify health status
        if rec["total_selections"] < 5:
            status = "insufficient_data"
        elif rates["completion_rate"] < _LOW_COMPLETION_THRESHOLD:
            status = "degraded"
        elif rates["fallback_rate"] > _FALLBACK_THRESHOLD:
            status = "degraded"
        else:
            status = "ok"
        results.append(
            {
                "skill_id": rec["skill_id"],
                "name": rec["name"],
                "total_selections": rec["total_selections"],
                "status": status,
                **rates,
            }
        )
    return results


def add_lineage_parent(
    conn: sqlite3.Connection, skill_id: str, parent_skill_id: str
) -> None:
    """Record a parent-child lineage relationship."""
    conn.execute(
        "INSERT OR IGNORE INTO skill_lineage_parents (skill_id, parent_skill_id) VALUES (?, ?)",
        (skill_id, parent_skill_id),
    )
    conn.commit()


def get_skill_lineage(conn: sqlite3.Connection, skill_id: str) -> dict:
    """Return parents and children for a skill."""
    # Parents of this skill
    parent_rows = conn.execute(
        """SELECT sr.skill_id, sr.name, sr.lineage_generation
           FROM skill_lineage_parents slp
           JOIN skill_records sr ON sr.skill_id = slp.parent_skill_id
           WHERE slp.skill_id = ?""",
        (skill_id,),
    ).fetchall()

    # Children of this skill
    child_rows = conn.execute(
        """SELECT sr.skill_id, sr.name, sr.lineage_generation
           FROM skill_lineage_parents slp
           JOIN skill_records sr ON sr.skill_id = slp.skill_id
           WHERE slp.parent_skill_id = ?""",
        (skill_id,),
    ).fetchall()

    return {
        "skill_id": skill_id,
        "parents": [dict(r) for r in parent_rows],
        "children": [dict(r) for r in child_rows],
    }


def add_skill_tag(conn: sqlite3.Connection, skill_id: str, tag: str) -> None:
    """Add a tag to a skill (idempotent)."""
    conn.execute(
        "INSERT OR IGNORE INTO skill_tags (skill_id, tag) VALUES (?, ?)",
        (skill_id, tag),
    )
    conn.commit()


def get_skill_tags(conn: sqlite3.Connection, skill_id: str) -> list[str]:
    """Return all tags for a skill."""
    rows = conn.execute(
        "SELECT tag FROM skill_tags WHERE skill_id = ? ORDER BY tag",
        (skill_id,),
    ).fetchall()
    return [r["tag"] for r in rows]
