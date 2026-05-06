#!/usr/bin/env python3
"""Evolution trigger engine for Skill MCP v2.

Checks skill quality counters against thresholds and returns
candidates for FIX or DERIVED evolution. Anti-loop protection via minimum
selection gate (skills need >= 5 fresh selections after evolution).
"""

import sqlite3

from .skill_db import get_all_skill_records, get_skill_record, computed_rates

# Thresholds from OpenSpace (proven values)
FALLBACK_THRESHOLD = 0.4  # >40% fallback rate -> candidate
LOW_COMPLETION_THRESHOLD = 0.35  # <35% completion rate -> candidate
MIN_APPLIED_FOR_DERIVED = 0.25  # <25% applied rate + low completion -> DERIVED
MIN_SELECTIONS = 5  # Minimum selections before evaluation


def is_evolution_eligible(conn: sqlite3.Connection, skill_id: str) -> bool:
    """Check if a skill is eligible for evolution based on quality metrics.

    Returns True if:
    - Has >= MIN_SELECTIONS total selections (anti-loop: resets after evolution)
    - AND completion_rate < LOW_COMPLETION_THRESHOLD OR fallback_rate > FALLBACK_THRESHOLD
    """
    rec = get_skill_record(conn, skill_id)
    if rec is None:
        return False

    if rec["total_selections"] < MIN_SELECTIONS:
        return False

    rates = computed_rates(rec)

    # Check if applied > 0 before checking completion_rate
    if rec["total_applied"] > 0 and rates["completion_rate"] < LOW_COMPLETION_THRESHOLD:
        return True

    if rates["fallback_rate"] > FALLBACK_THRESHOLD:
        return True

    return False


def check_triggers(conn: sqlite3.Connection) -> list[dict]:
    """Check all active skills for evolution triggers.

    Returns list of candidates with trigger reason and recommended type.
    Phase 3: FIX only. Phase 4 adds DERIVED/CAPTURED.
    """
    records = get_all_skill_records(conn)
    candidates = []

    for rec in records:
        if rec["total_selections"] < MIN_SELECTIONS:
            continue

        rates = computed_rates(rec)
        reasons = []
        evo_type = "FIX"

        low_completion = (
            rec["total_applied"] > 0
            and rates["completion_rate"] < LOW_COMPLETION_THRESHOLD
        )
        high_fallback = rates["fallback_rate"] > FALLBACK_THRESHOLD
        low_applied = rates["applied_rate"] < MIN_APPLIED_FOR_DERIVED

        if low_completion:
            reasons.append(
                f"low completion_rate ({rates['completion_rate']:.2f} < {LOW_COMPLETION_THRESHOLD})"
            )

        if high_fallback:
            reasons.append(
                f"high fallback_rate ({rates['fallback_rate']:.2f} > {FALLBACK_THRESHOLD})"
            )

        # DERIVED: low applied + low completion = skill is being ignored AND failing
        if low_applied and low_completion:
            evo_type = "DERIVED"
            reasons.append(
                f"low applied_rate ({rates['applied_rate']:.2f} < {MIN_APPLIED_FOR_DERIVED}) suggests DERIVED"
            )

        if reasons:
            candidates.append(
                {
                    "skill_id": rec["skill_id"],
                    "name": rec["name"],
                    "evolution_type": evo_type,
                    "trigger_reason": "; ".join(reasons),
                    "total_selections": rec["total_selections"],
                    "completion_rate": round(rates["completion_rate"], 3),
                    "fallback_rate": round(rates["fallback_rate"], 3),
                    "effective_rate": round(rates["effective_rate"], 3),
                    "applied_rate": round(rates["applied_rate"], 3),
                }
            )

    return candidates


def add_tool_dep(
    conn: sqlite3.Connection, skill_id: str, tool_key: str, critical: bool = False
) -> None:
    """Record a tool dependency for a skill."""
    conn.execute(
        "INSERT OR IGNORE INTO skill_tool_deps (skill_id, tool_key, critical) VALUES (?, ?, ?)",
        (skill_id, tool_key, 1 if critical else 0),
    )
    conn.commit()


def get_tool_deps(conn: sqlite3.Connection, skill_id: str) -> list[dict]:
    """Return tool dependencies for a skill."""
    rows = conn.execute(
        "SELECT tool_key, critical FROM skill_tool_deps WHERE skill_id = ? ORDER BY tool_key",
        (skill_id,),
    ).fetchall()
    return [{"tool_key": r["tool_key"], "critical": bool(r["critical"])} for r in rows]


def get_skills_by_tool(conn: sqlite3.Connection, tool_key: str) -> list[str]:
    """Return skill_ids that depend on a given tool."""
    rows = conn.execute(
        "SELECT skill_id FROM skill_tool_deps WHERE tool_key = ?",
        (tool_key,),
    ).fetchall()
    return [r["skill_id"] for r in rows]
