#!/usr/bin/env python3
"""Tests for shared/skill_db.py — SQLite skill store for v2 MCP."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.skill_db import (
    init_db,
    get_or_create_skill,
    record_selection,
    record_outcome,
    get_skill_record,
    get_all_skill_records,
    get_skill_health,
    get_skill_lineage,
    add_lineage_parent,
    add_skill_tag,
    get_skill_tags,
    computed_rates,
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


# ── Schema creation ──
print("\n--- skill_db: Schema creation ---")

with tempfile.TemporaryDirectory() as tmpdir:
    db_path = os.path.join(tmpdir, "skills.db")
    conn = init_db(db_path)

    # Check all 6 tables exist
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = sorted(r[0] for r in cur.fetchall() if not r[0].startswith("sqlite_"))
    expected = sorted(
        [
            "execution_analyses",
            "skill_judgments",
            "skill_lineage_parents",
            "skill_records",
            "skill_tags",
            "skill_tool_deps",
        ]
    )
    test("All 6 tables created", tables == expected, f"got {tables}")

    # Check WAL mode
    cur = conn.execute("PRAGMA journal_mode")
    mode = cur.fetchone()[0]
    test("WAL mode enabled", mode == "wal", f"got {mode}")

    # Check foreign keys
    cur = conn.execute("PRAGMA foreign_keys")
    fk = cur.fetchone()[0]
    test("Foreign keys enabled", fk == 1, f"got {fk}")

    conn.close()

# ── Skill CRUD ──
print("\n--- skill_db: Skill CRUD ---")

with tempfile.TemporaryDirectory() as tmpdir:
    db_path = os.path.join(tmpdir, "skills.db")
    conn = init_db(db_path)

    # Create a skill
    sid = get_or_create_skill(conn, "commit", "Quick git commit", "/path/to/commit")
    test("Skill ID format", sid.startswith("commit__imp_"), f"got {sid}")
    test("Skill ID length", len(sid) > len("commit__imp_"), f"got {sid}")

    # Get it back
    rec = get_skill_record(conn, sid)
    test("Record name", rec["name"] == "commit")
    test("Record description", rec["description"] == "Quick git commit")
    test("Record path", rec["path"] == "/path/to/commit")
    test("Record is_active", rec["is_active"] == 1)
    test("Record generation 0", rec["lineage_generation"] == 0)
    test("Record origin imported", rec["lineage_origin"] == "imported")
    test("Initial selections 0", rec["total_selections"] == 0)
    test("Initial completions 0", rec["total_completions"] == 0)

    # Idempotent: same name returns same skill_id
    sid2 = get_or_create_skill(conn, "commit", "Quick git commit", "/path/to/commit")
    test("Idempotent create", sid == sid2)

    # Different skill
    sid3 = get_or_create_skill(conn, "review", "Code review", "/path/to/review")
    test("Different skill different ID", sid != sid3)
    test("Review ID format", sid3.startswith("review__imp_"))

    conn.close()

# ── Counter updates ──
print("\n--- skill_db: Counter updates ---")

with tempfile.TemporaryDirectory() as tmpdir:
    db_path = os.path.join(tmpdir, "skills.db")
    conn = init_db(db_path)

    sid = get_or_create_skill(conn, "test-skill", "For testing", "/tmp")

    # Record 3 selections
    record_selection(conn, sid)
    record_selection(conn, sid)
    record_selection(conn, sid)
    rec = get_skill_record(conn, sid)
    test("3 selections", rec["total_selections"] == 3)

    # Record outcomes: 2 applied+completed, 1 fallback
    record_outcome(conn, sid, applied=True, completed=True)
    record_outcome(conn, sid, applied=True, completed=True)
    record_outcome(conn, sid, applied=False, completed=False)

    rec = get_skill_record(conn, sid)
    test("2 applied", rec["total_applied"] == 2)
    test("2 completions", rec["total_completions"] == 2)
    test("1 fallback", rec["total_fallbacks"] == 1)

    conn.close()

# ── Computed rates ──
print("\n--- skill_db: Computed rates ---")

with tempfile.TemporaryDirectory() as tmpdir:
    db_path = os.path.join(tmpdir, "skills.db")
    conn = init_db(db_path)

    sid = get_or_create_skill(conn, "rates-skill", "Testing rates", "/tmp")

    # 10 selections, 8 applied, 6 completions, 2 fallbacks
    for _ in range(10):
        record_selection(conn, sid)
    for _ in range(6):
        record_outcome(conn, sid, applied=True, completed=True)
    for _ in range(2):
        record_outcome(conn, sid, applied=True, completed=False)
    for _ in range(2):
        record_outcome(conn, sid, applied=False, completed=False)

    rec = get_skill_record(conn, sid)
    rates = computed_rates(rec)
    test(
        "applied_rate 0.8",
        abs(rates["applied_rate"] - 0.8) < 0.01,
        f"got {rates['applied_rate']}",
    )
    test(
        "completion_rate 0.75",
        abs(rates["completion_rate"] - 0.75) < 0.01,
        f"got {rates['completion_rate']}",
    )
    test(
        "effective_rate 0.6",
        abs(rates["effective_rate"] - 0.6) < 0.01,
        f"got {rates['effective_rate']}",
    )
    test(
        "fallback_rate 0.2",
        abs(rates["fallback_rate"] - 0.2) < 0.01,
        f"got {rates['fallback_rate']}",
    )

    # Zero division safety
    empty_rec = {
        "total_selections": 0,
        "total_applied": 0,
        "total_completions": 0,
        "total_fallbacks": 0,
    }
    rates0 = computed_rates(empty_rec)
    test("Zero selections safe", rates0["applied_rate"] == 0.0)
    test("Zero applied safe", rates0["completion_rate"] == 0.0)

    conn.close()

# ── List all records ──
print("\n--- skill_db: List all records ---")

with tempfile.TemporaryDirectory() as tmpdir:
    db_path = os.path.join(tmpdir, "skills.db")
    conn = init_db(db_path)

    get_or_create_skill(conn, "alpha", "A", "/a")
    get_or_create_skill(conn, "beta", "B", "/b")
    get_or_create_skill(conn, "gamma", "C", "/c")

    all_recs = get_all_skill_records(conn)
    names = sorted(r["name"] for r in all_recs)
    test("3 records", len(all_recs) == 3)
    test("Sorted names", names == ["alpha", "beta", "gamma"])

    conn.close()

# ── Health report ──
print("\n--- skill_db: Health report ---")

with tempfile.TemporaryDirectory() as tmpdir:
    db_path = os.path.join(tmpdir, "skills.db")
    conn = init_db(db_path)

    sid1 = get_or_create_skill(conn, "healthy", "Good", "/h")
    sid2 = get_or_create_skill(conn, "degraded", "Bad", "/d")

    # healthy: 10 selections, 9 completions
    for _ in range(10):
        record_selection(conn, sid1)
    for _ in range(9):
        record_outcome(conn, sid1, applied=True, completed=True)
    record_outcome(conn, sid1, applied=True, completed=False)

    # degraded: 10 selections, 2 completions, 5 fallbacks
    for _ in range(10):
        record_selection(conn, sid2)
    for _ in range(2):
        record_outcome(conn, sid2, applied=True, completed=True)
    for _ in range(3):
        record_outcome(conn, sid2, applied=True, completed=False)
    for _ in range(5):
        record_outcome(conn, sid2, applied=False, completed=False)

    health = get_skill_health(conn)
    test("Health has 2 skills", len(health) == 2)

    degraded_entry = next(h for h in health if h["name"] == "degraded")
    test(
        "Degraded flagged",
        degraded_entry["status"] == "degraded",
        f"got {degraded_entry.get('status')}",
    )

    healthy_entry = next(h for h in health if h["name"] == "healthy")
    test(
        "Healthy is ok",
        healthy_entry["status"] == "ok",
        f"got {healthy_entry.get('status')}",
    )

    conn.close()

# ── Lineage ──
print("\n--- skill_db: Lineage ---")

with tempfile.TemporaryDirectory() as tmpdir:
    db_path = os.path.join(tmpdir, "skills.db")
    conn = init_db(db_path)

    parent_id = get_or_create_skill(conn, "commit", "v1", "/c")
    child_id = get_or_create_skill(conn, "commit-v2", "v2 evolved", "/c2")

    add_lineage_parent(conn, child_id, parent_id)

    lineage = get_skill_lineage(conn, child_id)
    test("Has parents", len(lineage["parents"]) == 1)
    test("Parent is commit", lineage["parents"][0]["name"] == "commit")

    lineage_parent = get_skill_lineage(conn, parent_id)
    test("Parent has child", len(lineage_parent["children"]) == 1)
    test("Child is commit-v2", lineage_parent["children"][0]["name"] == "commit-v2")

    conn.close()

# ── Tags ──
print("\n--- skill_db: Tags ---")

with tempfile.TemporaryDirectory() as tmpdir:
    db_path = os.path.join(tmpdir, "skills.db")
    conn = init_db(db_path)

    sid = get_or_create_skill(conn, "tagged", "Has tags", "/t")
    add_skill_tag(conn, sid, "workflow")
    add_skill_tag(conn, sid, "git")
    add_skill_tag(conn, sid, "workflow")  # duplicate — should be idempotent

    tags = get_skill_tags(conn, sid)
    test("2 unique tags", len(tags) == 2, f"got {tags}")
    test("Has workflow", "workflow" in tags)
    test("Has git", "git" in tags)

    conn.close()

# ── Reinit idempotent ──
print("\n--- skill_db: Reinit idempotent ---")

with tempfile.TemporaryDirectory() as tmpdir:
    db_path = os.path.join(tmpdir, "skills.db")
    conn1 = init_db(db_path)
    get_or_create_skill(conn1, "persist", "Should survive", "/p")
    conn1.close()

    conn2 = init_db(db_path)
    rec = get_all_skill_records(conn2)
    test("Data survives reinit", len(rec) == 1 and rec[0]["name"] == "persist")
    conn2.close()


print(f"\n{'=' * 40}")
print(f"skill_db: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
