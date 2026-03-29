#!/usr/bin/env python3
"""Tests for shared/skill_analyzer.py — post-task analysis engine."""

import json
import os
import sys
import tempfile
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.skill_analyzer import (
    build_analysis_prompt,
    parse_analysis_response,
    analyze_task,
    store_analysis,
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


# ── Prompt building ──
print("\n--- skill_analyzer: Prompt building ---")

prompt = build_analysis_prompt(
    skill_name="commit",
    skill_content="# Commit\nStage and commit changes.",
    success=True,
    context="committed 3 files successfully",
)
test("Prompt contains skill name", "commit" in prompt)
test("Prompt contains skill content", "Stage and commit" in prompt)
test("Prompt contains status", "success" in prompt.lower() or "True" in prompt)
test("Prompt contains context", "committed 3 files" in prompt)
test("Prompt asks for JSON", "JSON" in prompt or "json" in prompt.lower())
test("Prompt has task_completed field", "task_completed" in prompt)
test("Prompt has skill_judgments field", "skill_judgments" in prompt)
test("Prompt has evolution_suggestions field", "evolution_suggestions" in prompt)


# ── Response parsing: valid JSON ──
print("\n--- skill_analyzer: Parse valid response ---")

valid_response = json.dumps(
    {
        "task_completed": True,
        "execution_note": "Task completed successfully. Commit created.",
        "tool_issues": [],
        "skill_judgments": [
            {"skill_id": "commit", "skill_applied": True, "note": "Applied correctly"}
        ],
        "evolution_suggestions": [],
    }
)

parsed = parse_analysis_response(valid_response)
test("Parsed task_completed", parsed["task_completed"] is True)
test("Parsed execution_note", "successfully" in parsed["execution_note"])
test("Parsed skill_judgments count", len(parsed["skill_judgments"]) == 1)
test("Parsed judgment skill_id", parsed["skill_judgments"][0]["skill_id"] == "commit")
test("Parsed judgment applied", parsed["skill_judgments"][0]["skill_applied"] is True)
test("Parsed evolution_suggestions empty", len(parsed["evolution_suggestions"]) == 0)
test("Parsed tool_issues empty", len(parsed["tool_issues"]) == 0)


# ── Response parsing: JSON in markdown fence ──
print("\n--- skill_analyzer: Parse fenced response ---")

fenced_response = """Here is my analysis:

```json
{
  "task_completed": false,
  "execution_note": "Task failed due to pre-commit hook error.",
  "tool_issues": ["Bash:git commit -- pre-commit hook rejected"],
  "skill_judgments": [
    {"skill_id": "commit", "skill_applied": true, "note": "Applied but hook failed"}
  ],
  "evolution_suggestions": [
    {"type": "fix", "target_skills": ["commit"], "category": "workflow", "direction": "Add pre-commit hook error handling"}
  ]
}
```
"""

parsed2 = parse_analysis_response(fenced_response)
test("Fenced: task_completed false", parsed2["task_completed"] is False)
test("Fenced: has tool issues", len(parsed2["tool_issues"]) == 1)
test("Fenced: has evolution suggestion", len(parsed2["evolution_suggestions"]) == 1)
test(
    "Fenced: suggestion type is fix",
    parsed2["evolution_suggestions"][0]["type"] == "fix",
)


# ── Response parsing: malformed ──
print("\n--- skill_analyzer: Parse malformed response ---")

parsed3 = parse_analysis_response("This is not JSON at all.")
test("Malformed returns defaults", parsed3 is not None)
test("Malformed task_completed false", parsed3["task_completed"] is False)
test(
    "Malformed has error note",
    "parse" in parsed3["execution_note"].lower()
    or "failed" in parsed3["execution_note"].lower(),
)


# ── Store analysis in SQLite ──
print("\n--- skill_analyzer: Store analysis ---")

with tempfile.TemporaryDirectory() as tmpdir:
    db_path = os.path.join(tmpdir, "skills.db")
    conn = init_db(db_path)

    sid = get_or_create_skill(conn, "commit", "Git commit", "/c")

    analysis_data = {
        "task_completed": True,
        "execution_note": "Commit succeeded on first try.",
        "tool_issues": [],
        "skill_judgments": [
            {"skill_id": sid, "skill_applied": True, "note": "Applied correctly"}
        ],
        "evolution_suggestions": [],
    }

    analysis_id = store_analysis(
        conn,
        task_id="task-001",
        analysis=analysis_data,
    )
    test(
        "Analysis ID returned",
        analysis_id is not None and analysis_id > 0,
        f"got {analysis_id}",
    )

    # Verify execution_analyses row
    row = conn.execute(
        "SELECT * FROM execution_analyses WHERE task_id = ?", ("task-001",)
    ).fetchone()
    test("Analysis stored", row is not None)
    test("Analysis task_completed", row["task_completed"] == 1)
    test("Analysis note stored", "succeeded" in row["execution_note"])

    # Verify skill_judgments row
    jrow = conn.execute(
        "SELECT * FROM skill_judgments WHERE analysis_id = ?", (analysis_id,)
    ).fetchone()
    test("Judgment stored", jrow is not None)
    test("Judgment skill_id matches", jrow["skill_id"] == sid)
    test("Judgment applied", jrow["skill_applied"] == 1)
    test("Judgment note", "correctly" in jrow["note"])

    conn.close()


# ── Store analysis updates counters ──
print("\n--- skill_analyzer: Counter updates from analysis ---")

with tempfile.TemporaryDirectory() as tmpdir:
    db_path = os.path.join(tmpdir, "skills.db")
    conn = init_db(db_path)

    sid = get_or_create_skill(conn, "review", "Code review", "/r")
    # Give it some initial selections
    for _ in range(3):
        conn.execute(
            "UPDATE skill_records SET total_selections = total_selections + 1 WHERE skill_id = ?",
            (sid,),
        )
    conn.commit()

    # Analysis: applied but task failed
    analysis_fail = {
        "task_completed": False,
        "execution_note": "Review failed - couldn't parse diff.",
        "tool_issues": ["Read:file -- permission denied"],
        "skill_judgments": [
            {"skill_id": sid, "skill_applied": True, "note": "Applied but failed"}
        ],
        "evolution_suggestions": [
            {
                "type": "fix",
                "target_skills": ["review"],
                "category": "workflow",
                "direction": "Handle permission errors gracefully",
            }
        ],
    }

    store_analysis(conn, task_id="task-002", analysis=analysis_fail)

    rec = get_skill_record(conn, sid)
    test(
        "Applied incremented", rec["total_applied"] == 1, f"got {rec['total_applied']}"
    )
    test("Completions not incremented", rec["total_completions"] == 0)
    test(
        "Fallbacks not incremented",
        rec["total_fallbacks"] == 0,
        f"got {rec['total_fallbacks']}",
    )

    # Analysis: not applied and task failed -> fallback
    analysis_fallback = {
        "task_completed": False,
        "execution_note": "Skill was ignored.",
        "tool_issues": [],
        "skill_judgments": [
            {"skill_id": sid, "skill_applied": False, "note": "Not used"}
        ],
        "evolution_suggestions": [],
    }

    store_analysis(conn, task_id="task-003", analysis=analysis_fallback)

    rec2 = get_skill_record(conn, sid)
    test(
        "Fallback incremented",
        rec2["total_fallbacks"] == 1,
        f"got {rec2['total_fallbacks']}",
    )

    # Analysis: applied and completed
    analysis_ok = {
        "task_completed": True,
        "execution_note": "All good.",
        "tool_issues": [],
        "skill_judgments": [
            {"skill_id": sid, "skill_applied": True, "note": "Perfect"}
        ],
        "evolution_suggestions": [],
    }

    store_analysis(conn, task_id="task-004", analysis=analysis_ok)

    rec3 = get_skill_record(conn, sid)
    test(
        "Completion incremented",
        rec3["total_completions"] == 1,
        f"got {rec3['total_completions']}",
    )
    test("Applied now 2", rec3["total_applied"] == 2, f"got {rec3['total_applied']}")

    conn.close()


# ── Full analyze_task with mocked LLM ──
print("\n--- skill_analyzer: Full analyze_task (mocked LLM) ---")

with tempfile.TemporaryDirectory() as tmpdir:
    db_path = os.path.join(tmpdir, "skills.db")
    conn = init_db(db_path)

    sid = get_or_create_skill(conn, "test-skill", "Testing", "/t")

    mock_llm_response = json.dumps(
        {
            "task_completed": True,
            "execution_note": "Task went smoothly.",
            "tool_issues": [],
            "skill_judgments": [
                {"skill_id": sid, "skill_applied": True, "note": "Used well"}
            ],
            "evolution_suggestions": [],
        }
    )

    mock_client = MagicMock()
    mock_client.complete.return_value = mock_llm_response

    result = analyze_task(
        conn=conn,
        llm_client=mock_client,
        skill_name="test-skill",
        skill_content="# Test\nDo testing things.",
        success=True,
        context="ran 5 tests, all passed",
        task_id="task-100",
    )

    test("analyze_task returns analysis", result is not None)
    test("analyze_task has task_completed", result["task_completed"] is True)
    test("LLM client called", mock_client.complete.called)

    # Check stored in DB
    row = conn.execute(
        "SELECT * FROM execution_analyses WHERE task_id = ?", ("task-100",)
    ).fetchone()
    test("Analysis persisted to DB", row is not None)

    # Check counter update
    rec = get_skill_record(conn, sid)
    test("Counter updated from analysis", rec["total_applied"] == 1)
    test("Completion updated", rec["total_completions"] == 1)

    conn.close()


# ── Duplicate task_id handling ──
print("\n--- skill_analyzer: Duplicate task_id ---")

with tempfile.TemporaryDirectory() as tmpdir:
    db_path = os.path.join(tmpdir, "skills.db")
    conn = init_db(db_path)

    sid = get_or_create_skill(conn, "dup-test", "Dup", "/d")

    analysis = {
        "task_completed": True,
        "execution_note": "First analysis.",
        "tool_issues": [],
        "skill_judgments": [{"skill_id": sid, "skill_applied": True, "note": "ok"}],
        "evolution_suggestions": [],
    }

    id1 = store_analysis(conn, task_id="dup-task", analysis=analysis)
    test("First store succeeds", id1 is not None)

    # Second store with same task_id should return None (skip)
    id2 = store_analysis(conn, task_id="dup-task", analysis=analysis)
    test("Duplicate returns None", id2 is None)

    conn.close()


print(f"\n{'=' * 40}")
print(f"skill_analyzer: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
