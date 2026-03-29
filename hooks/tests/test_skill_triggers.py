#!/usr/bin/env python3
"""Tests for shared/skill_triggers.py — evolution trigger engine."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.skill_db import (
    init_db,
    get_or_create_skill,
    record_selection,
    record_outcome,
)
from shared.skill_triggers import (
    check_triggers,
    is_evolution_eligible,
    FALLBACK_THRESHOLD,
    LOW_COMPLETION_THRESHOLD,
    MIN_SELECTIONS,
)

passed = failed = 0


def test(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name} -- {detail}")


# ── Constants sanity ──
print("\n--- skill_triggers: Constants ---")

test("FALLBACK_THRESHOLD is 0.4", FALLBACK_THRESHOLD == 0.4)
test("LOW_COMPLETION_THRESHOLD is 0.35", LOW_COMPLETION_THRESHOLD == 0.35)
test("MIN_SELECTIONS is 5", MIN_SELECTIONS == 5)


# ── Eligibility: too few selections ──
print("\n--- skill_triggers: Eligibility - insufficient data ---")

with tempfile.TemporaryDirectory() as tmpdir:
    db_path = os.path.join(tmpdir, "skills.db")
    conn = init_db(db_path)
    sid = get_or_create_skill(conn, "new-skill", "Brand new", "/n")

    # Only 3 selections — below MIN_SELECTIONS
    for _ in range(3):
        record_selection(conn, sid)
    record_outcome(conn, sid, applied=True, completed=False)

    eligible = is_evolution_eligible(conn, sid)
    test("Not eligible with < 5 selections", eligible is False)

    conn.close()


# ── Eligibility: healthy skill not triggered ──
print("\n--- skill_triggers: Eligibility - healthy skill ---")

with tempfile.TemporaryDirectory() as tmpdir:
    db_path = os.path.join(tmpdir, "skills.db")
    conn = init_db(db_path)
    sid = get_or_create_skill(conn, "healthy", "Works well", "/h")

    # 10 selections, 9 applied+completed, 1 applied+not completed
    for _ in range(10):
        record_selection(conn, sid)
    for _ in range(9):
        record_outcome(conn, sid, applied=True, completed=True)
    record_outcome(conn, sid, applied=True, completed=False)

    eligible = is_evolution_eligible(conn, sid)
    test("Healthy skill not eligible", eligible is False)

    conn.close()


# ── Eligibility: degraded completion rate ──
print("\n--- skill_triggers: Eligibility - low completion ---")

with tempfile.TemporaryDirectory() as tmpdir:
    db_path = os.path.join(tmpdir, "skills.db")
    conn = init_db(db_path)
    sid = get_or_create_skill(conn, "broken", "Keeps failing", "/b")

    # 10 selections, 10 applied, only 2 completed -> completion_rate = 0.2
    for _ in range(10):
        record_selection(conn, sid)
    for _ in range(2):
        record_outcome(conn, sid, applied=True, completed=True)
    for _ in range(8):
        record_outcome(conn, sid, applied=True, completed=False)

    eligible = is_evolution_eligible(conn, sid)
    test("Low completion triggers eligibility", eligible is True)

    conn.close()


# ── Eligibility: high fallback rate ──
print("\n--- skill_triggers: Eligibility - high fallback ---")

with tempfile.TemporaryDirectory() as tmpdir:
    db_path = os.path.join(tmpdir, "skills.db")
    conn = init_db(db_path)
    sid = get_or_create_skill(conn, "ignored", "Gets ignored", "/i")

    # 10 selections, 5 fallbacks (not applied, not completed) -> fallback_rate = 0.5
    for _ in range(10):
        record_selection(conn, sid)
    for _ in range(5):
        record_outcome(conn, sid, applied=False, completed=False)
    for _ in range(5):
        record_outcome(conn, sid, applied=True, completed=True)

    eligible = is_evolution_eligible(conn, sid)
    test("High fallback triggers eligibility", eligible is True)

    conn.close()


# ── check_triggers returns candidates ──
print("\n--- skill_triggers: check_triggers ---")

with tempfile.TemporaryDirectory() as tmpdir:
    db_path = os.path.join(tmpdir, "skills.db")
    conn = init_db(db_path)

    # One healthy, one degraded
    sid_ok = get_or_create_skill(conn, "good-skill", "Works", "/g")
    sid_bad = get_or_create_skill(conn, "bad-skill", "Broken", "/b")

    for _ in range(10):
        record_selection(conn, sid_ok)
        record_selection(conn, sid_bad)

    for _ in range(9):
        record_outcome(conn, sid_ok, applied=True, completed=True)
    record_outcome(conn, sid_ok, applied=True, completed=False)

    # bad: 10 applied, 1 completed -> completion_rate = 0.1
    record_outcome(conn, sid_bad, applied=True, completed=True)
    for _ in range(9):
        record_outcome(conn, sid_bad, applied=True, completed=False)

    candidates = check_triggers(conn)
    test("check_triggers returns list", isinstance(candidates, list))
    test("One candidate", len(candidates) == 1, f"got {len(candidates)}")
    if candidates:
        test("Candidate is bad-skill", candidates[0]["name"] == "bad-skill")
        test("Candidate has trigger_reason", "trigger_reason" in candidates[0])
        test("Candidate type is FIX", candidates[0]["evolution_type"] == "FIX")

    conn.close()


# ── Anti-loop: reset after evolution ──
print("\n--- skill_triggers: Anti-loop protection ---")

with tempfile.TemporaryDirectory() as tmpdir:
    db_path = os.path.join(tmpdir, "skills.db")
    conn = init_db(db_path)
    sid = get_or_create_skill(conn, "evolved", "Was fixed", "/e")

    # Build up degraded state: 10 selections, low completion
    for _ in range(10):
        record_selection(conn, sid)
    for _ in range(9):
        record_outcome(conn, sid, applied=True, completed=False)
    record_outcome(conn, sid, applied=True, completed=True)

    # Should be eligible now
    test("Pre-evolution: eligible", is_evolution_eligible(conn, sid))

    # Simulate evolution: reset selections to 0 (new skill_id in real flow,
    # but for anti-loop we just check the counter reset)
    conn.execute(
        "UPDATE skill_records SET total_selections = 0 WHERE skill_id = ?",
        (sid,),
    )
    conn.commit()

    # Now not eligible (needs 5 fresh selections)
    test("Post-evolution reset: not eligible", not is_evolution_eligible(conn, sid))

    # Add 4 selections — still not enough
    for _ in range(4):
        record_selection(conn, sid)
    test("4 selections: still not eligible", not is_evolution_eligible(conn, sid))

    # Add 1 more — now at 5, build degraded counters again
    record_selection(conn, sid)
    for _ in range(5):
        record_outcome(conn, sid, applied=True, completed=False)
    test("5 selections + degraded: eligible again", is_evolution_eligible(conn, sid))

    conn.close()


# ── Edge: exactly at threshold ──
print("\n--- skill_triggers: Edge cases ---")

with tempfile.TemporaryDirectory() as tmpdir:
    db_path = os.path.join(tmpdir, "skills.db")
    conn = init_db(db_path)
    sid = get_or_create_skill(conn, "edge", "Edge case", "/e")

    # Exactly 5 selections, completion_rate exactly 0.35 (not < 0.35)
    # 20 selections, 20 applied, 7 completed -> 7/20 = 0.35
    for _ in range(20):
        record_selection(conn, sid)
    for _ in range(7):
        record_outcome(conn, sid, applied=True, completed=True)
    for _ in range(13):
        record_outcome(conn, sid, applied=True, completed=False)

    eligible = is_evolution_eligible(conn, sid)
    test(
        "Exactly at threshold: not eligible (< not <=)",
        eligible is False,
        "completion_rate=0.35 should NOT trigger",
    )

    conn.close()


print(f"\n{'=' * 40}")
print(f"skill_triggers: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
