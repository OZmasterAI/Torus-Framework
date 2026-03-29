#!/usr/bin/env python3
"""Evolution trigger engine for Skill MCP v2.

Checks skill quality counters against thresholds and returns
candidates for FIX evolution. Anti-loop protection via minimum
selection gate (skills need >= 5 fresh selections after evolution).
"""

import sqlite3

from shared.skill_db import get_all_skill_records, get_skill_record, computed_rates

# Thresholds from OpenSpace (proven values)
FALLBACK_THRESHOLD = 0.4  # >40% fallback rate -> candidate
LOW_COMPLETION_THRESHOLD = 0.35  # <35% completion rate -> candidate
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

        if (
            rec["total_applied"] > 0
            and rates["completion_rate"] < LOW_COMPLETION_THRESHOLD
        ):
            reasons.append(
                f"low completion_rate ({rates['completion_rate']:.2f} < {LOW_COMPLETION_THRESHOLD})"
            )

        if rates["fallback_rate"] > FALLBACK_THRESHOLD:
            reasons.append(
                f"high fallback_rate ({rates['fallback_rate']:.2f} > {FALLBACK_THRESHOLD})"
            )

        if reasons:
            candidates.append(
                {
                    "skill_id": rec["skill_id"],
                    "name": rec["name"],
                    "evolution_type": "FIX",
                    "trigger_reason": "; ".join(reasons),
                    "total_selections": rec["total_selections"],
                    "completion_rate": round(rates["completion_rate"], 3),
                    "fallback_rate": round(rates["fallback_rate"], 3),
                    "effective_rate": round(rates["effective_rate"], 3),
                }
            )

    return candidates
