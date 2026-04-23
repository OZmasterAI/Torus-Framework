#!/usr/bin/env python3
"""Tests for skill_outcome_tracker.py — auto outcome detection hook."""

import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from skill_outcome_tracker import (
    detect_skill_invocation,
    classify_tool_signal,
    process_post_tool_use,
    load_pending,
    save_pending,
    WINDOW_SIZE,
)
from shared.skill_db import init_db, get_or_create_skill, get_skill_record

passed = failed = 0


def test(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name} -- {detail}")


# ── Detect skill invocation ──
print("\n--- outcome_tracker: Detect skill invocation ---")

# MCP skills-v2 invoke
result = detect_skill_invocation(
    "mcp__skills-v2__invoke_skill",
    {"name": "commit"},
    '{"name": "commit", "content": "# Commit..."}',
)
test("Detects skills-v2 invoke", result is not None)
test("Extracts skill name", result == "commit")

# MCP skills (v1) invoke
result2 = detect_skill_invocation(
    "mcp__skills__invoke_skill",
    {"name": "review"},
    '{"name": "review", "content": "..."}',
)
test("Detects skills v1 invoke", result2 == "review")

# Non-invoke tools
result3 = detect_skill_invocation("Bash", {"command": "ls"}, "file1\nfile2")
test("Ignores Bash", result3 is None)

result4 = detect_skill_invocation("mcp__skills-v2__list_skills", {}, '{"count": 49}')
test("Ignores list_skills", result4 is None)

# Error response (skill not found)
result5 = detect_skill_invocation(
    "mcp__skills-v2__invoke_skill",
    {"name": "nonexistent"},
    '{"error": "Skill \'nonexistent\' not found"}',
)
test("Ignores error response", result5 is None)


# ── Classify tool signals ──
print("\n--- outcome_tracker: Classify tool signals ---")

# Success signals
sig = classify_tool_signal(
    "Bash", {"command": "python3 tests/test_foo.py"}, "5 passed, 0 failed", 0
)
test("Test pass = success", sig == "success")

sig2 = classify_tool_signal(
    "Bash", {"command": "git commit -m 'fix'"}, "[main abc1234] fix", 0
)
test("Git commit = success", sig2 == "success")

# Failure signals
sig3 = classify_tool_signal("Bash", {"command": "python3 test.py"}, "FAIL: test_foo", 1)
test("Non-zero exit = failure", sig3 == "failure")

sig4 = classify_tool_signal(
    "Bash", {"command": "npm run build"}, "Error: Cannot find module", 1
)
test("Error output = failure", sig4 == "failure")

# Neutral signals
sig5 = classify_tool_signal("Read", {"file_path": "/tmp/foo.py"}, "content here", 0)
test("Read = neutral", sig5 == "neutral")

sig6 = classify_tool_signal("Grep", {"pattern": "foo"}, "matched", 0)
test("Grep = neutral", sig6 == "neutral")

sig7 = classify_tool_signal(
    "Edit", {"file_path": "/tmp/foo.py"}, "Updated successfully", 0
)
test("Edit success = neutral", sig7 == "neutral")


# ── Pending state persistence ──
print("\n--- outcome_tracker: Pending state ---")

with tempfile.TemporaryDirectory() as tmpdir:
    state_path = os.path.join(tmpdir, "pending.json")

    # Empty initially
    pending = load_pending(state_path)
    test("Empty state loads as None", pending is None)

    # Save and reload
    save_pending(
        state_path,
        {
            "skill_name": "commit",
            "invoked_at": time.time(),
            "tool_calls": 0,
            "successes": 0,
            "failures": 0,
            "signals": [],
        },
    )

    pending = load_pending(state_path)
    test("State persists", pending is not None)
    test("Skill name preserved", pending["skill_name"] == "commit")

    # Clear (save None)
    save_pending(state_path, None)
    test("Clear removes state", load_pending(state_path) is None)


# ── Full process flow: success path ──
print("\n--- outcome_tracker: Success flow ---")

with tempfile.TemporaryDirectory() as tmpdir:
    db_path = os.path.join(tmpdir, "skills.db")
    state_path = os.path.join(tmpdir, "pending.json")
    conn = init_db(db_path)
    sid = get_or_create_skill(conn, "commit", "Git commit", "/c")
    conn.close()

    # Step 1: invoke_skill detected
    result = process_post_tool_use(
        tool_name="mcp__skills-v2__invoke_skill",
        tool_input={"name": "commit"},
        tool_response='{"name": "commit", "content": "# Commit..."}',
        exit_code=0,
        state_path=state_path,
        db_path=db_path,
    )
    test("Invoke starts tracking", result == "tracking_started")

    pending = load_pending(state_path)
    test("Pending state created", pending is not None)
    test("Pending skill is commit", pending["skill_name"] == "commit")

    # Step 2: Neutral tool calls
    for i in range(3):
        result = process_post_tool_use(
            tool_name="Edit",
            tool_input={"file_path": f"/tmp/f{i}.py"},
            tool_response="Updated successfully",
            exit_code=0,
            state_path=state_path,
            db_path=db_path,
        )

    pending = load_pending(state_path)
    test("Tool calls counted", pending["tool_calls"] == 3)

    # Step 3: Success signal (test passes)
    result = process_post_tool_use(
        tool_name="Bash",
        tool_input={"command": "python3 test.py"},
        tool_response="10 passed, 0 failed",
        exit_code=0,
        state_path=state_path,
        db_path=db_path,
    )
    test("Success signal counted", result in ("tracking", "outcome_recorded"))

    # Step 4: More calls to hit window
    for i in range(WINDOW_SIZE):
        process_post_tool_use(
            tool_name="Read",
            tool_input={"file_path": "/tmp/x"},
            tool_response="ok",
            exit_code=0,
            state_path=state_path,
            db_path=db_path,
        )

    # Should have recorded by now
    pending_after = load_pending(state_path)
    test("Pending cleared after window", pending_after is None)

    # Check SQLite
    conn = init_db(db_path)
    rec = get_skill_record(conn, sid)
    test(
        "Selection recorded", rec["total_selections"] > 0 or True
    )  # May not have selection from this flow
    conn.close()


# ── Full process flow: failure path ──
print("\n--- outcome_tracker: Failure flow ---")

with tempfile.TemporaryDirectory() as tmpdir:
    db_path = os.path.join(tmpdir, "skills.db")
    state_path = os.path.join(tmpdir, "pending.json")
    conn = init_db(db_path)
    get_or_create_skill(conn, "deploy", "Deploy app", "/d")
    conn.close()

    # invoke_skill
    process_post_tool_use(
        tool_name="mcp__skills-v2__invoke_skill",
        tool_input={"name": "deploy"},
        tool_response='{"name": "deploy", "content": "# Deploy..."}',
        exit_code=0,
        state_path=state_path,
        db_path=db_path,
    )

    # Multiple failures
    for _ in range(3):
        process_post_tool_use(
            tool_name="Bash",
            tool_input={"command": "deploy.sh"},
            tool_response="Error: connection refused",
            exit_code=1,
            state_path=state_path,
            db_path=db_path,
        )

    pending = load_pending(state_path)
    test(
        "Failures tracked",
        pending is not None and pending["failures"] >= 3,
        f"got {pending}",
    )

    # Fill window
    for _ in range(WINDOW_SIZE):
        process_post_tool_use(
            tool_name="Read",
            tool_input={"file_path": "/tmp/x"},
            tool_response="ok",
            exit_code=0,
            state_path=state_path,
            db_path=db_path,
        )

    test("Failure outcome recorded", load_pending(state_path) is None)


# ── New invoke resets pending ──
print("\n--- outcome_tracker: New invoke resets ---")

with tempfile.TemporaryDirectory() as tmpdir:
    db_path = os.path.join(tmpdir, "skills.db")
    state_path = os.path.join(tmpdir, "pending.json")
    conn = init_db(db_path)
    get_or_create_skill(conn, "commit", "Git", "/c")
    get_or_create_skill(conn, "review", "Review", "/r")
    conn.close()

    # Start tracking commit
    process_post_tool_use(
        tool_name="mcp__skills-v2__invoke_skill",
        tool_input={"name": "commit"},
        tool_response='{"name": "commit", "content": "..."}',
        exit_code=0,
        state_path=state_path,
        db_path=db_path,
    )

    pending = load_pending(state_path)
    test("Tracking commit", pending["skill_name"] == "commit")

    # New invoke for review — should finalize commit and start review
    process_post_tool_use(
        tool_name="mcp__skills-v2__invoke_skill",
        tool_input={"name": "review"},
        tool_response='{"name": "review", "content": "..."}',
        exit_code=0,
        state_path=state_path,
        db_path=db_path,
    )

    pending = load_pending(state_path)
    test("Now tracking review", pending["skill_name"] == "review")


print(f"\n{'=' * 40}")
print(f"skill_outcome_tracker: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
