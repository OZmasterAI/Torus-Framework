#!/usr/bin/env python3
"""Tests for shared/skill_evolver.py — FIX, DERIVED, CAPTURED evolution."""

import json
import os
import sys
import tempfile
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.skill_evolver import (
    build_fix_prompt,
    build_derived_prompt,
    build_captured_prompt,
    parse_evolution_response,
    parse_derived_response,
    evolve_skill,
    evolve_derived,
    evolve_captured,
    EVOLUTION_COMPLETE,
    EVOLUTION_FAILED,
    MAX_ITERATIONS,
    MAX_ATTEMPTS,
)
from shared.skill_db import (
    init_db,
    get_or_create_skill,
    get_skill_record,
    get_skill_lineage,
    add_lineage_parent,
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


# ── Constants ──
print("\n--- skill_evolver: Constants ---")

test("EVOLUTION_COMPLETE token", EVOLUTION_COMPLETE == "<EVOLUTION_COMPLETE>")
test("EVOLUTION_FAILED token", EVOLUTION_FAILED == "<EVOLUTION_FAILED>")
test("MAX_ITERATIONS is 5", MAX_ITERATIONS == 5)
test("MAX_ATTEMPTS is 3", MAX_ATTEMPTS == 3)


# ── FIX prompt building ──
print("\n--- skill_evolver: FIX prompt ---")

prompt = build_fix_prompt(
    current_content="# Commit\nStage and commit changes.",
    direction="Pre-commit hook failures not handled",
    failure_context="Hook rejected due to lint errors in 3 recent executions",
    tool_issue_summary="Bash:git commit -- pre-commit hook failed",
    metric_summary="completion_rate=0.20, fallback_rate=0.10",
)
test("Prompt has current content", "Stage and commit" in prompt)
test("Prompt has direction", "Pre-commit hook" in prompt)
test("Prompt has failure context", "lint errors" in prompt)
test("Prompt has tool issues", "pre-commit hook failed" in prompt)
test("Prompt has metrics", "completion_rate=0.20" in prompt)
test("Prompt has CHANGE_SUMMARY instruction", "CHANGE_SUMMARY" in prompt)
test("Prompt has EVOLUTION_COMPLETE", EVOLUTION_COMPLETE in prompt)
test("Prompt has EVOLUTION_FAILED", EVOLUTION_FAILED in prompt)


# ── Parse: successful evolution ──
print("\n--- skill_evolver: Parse successful ---")

good_response = f"""CHANGE_SUMMARY: Added pre-commit hook error handling with retry logic

# Commit
Stage and commit changes with pre-commit hook error handling.

## Steps
1. Stage files
2. Run commit
3. If pre-commit hook fails, show error and suggest fixes

{EVOLUTION_COMPLETE}"""

parsed = parse_evolution_response(good_response)
test("Success: complete is True", parsed["complete"] is True)
test("Success: failed is False", parsed["failed"] is False)
test("Has change_summary", "pre-commit hook" in parsed["change_summary"])
test("Has content", "# Commit" in parsed["content"])
test("Content excludes CHANGE_SUMMARY line", "CHANGE_SUMMARY:" not in parsed["content"])
test("Content excludes EVOLUTION token", EVOLUTION_COMPLETE not in parsed["content"])


# ── Parse: failed evolution ──
print("\n--- skill_evolver: Parse failed ---")

fail_response = f"""{EVOLUTION_FAILED}
Reason: The skill's issues stem from external hook configuration, not the skill itself."""

parsed_fail = parse_evolution_response(fail_response)
test("Failed: complete is False", parsed_fail["complete"] is False)
test("Failed: failed is True", parsed_fail["failed"] is True)
test("Failed: content is empty", parsed_fail["content"] == "")


# ── Parse: neither token (needs nudge) ──
print("\n--- skill_evolver: Parse ambiguous ---")

ambiguous = """CHANGE_SUMMARY: Updated the commit flow

# Commit
New improved commit skill content here.
"""

parsed_ambiguous = parse_evolution_response(ambiguous)
test("Ambiguous: complete is False", parsed_ambiguous["complete"] is False)
test("Ambiguous: failed is False", parsed_ambiguous["failed"] is False)
test("Ambiguous: has content", len(parsed_ambiguous["content"]) > 0)


# ── Full evolve_skill: success on first try ──
print("\n--- skill_evolver: evolve_skill success ---")

with tempfile.TemporaryDirectory() as tmpdir:
    db_path = os.path.join(tmpdir, "skills.db")
    conn = init_db(db_path)
    sid = get_or_create_skill(conn, "test-fix", "Needs fixing", tmpdir)

    # Write initial SKILL.md
    skill_dir = os.path.join(tmpdir, "test-fix")
    os.makedirs(skill_dir, exist_ok=True)
    md_path = os.path.join(skill_dir, "SKILL.md")
    with open(md_path, "w") as f:
        f.write("# Test Fix\nOriginal content that needs fixing.\n")

    evolved_content = f"""CHANGE_SUMMARY: Fixed the broken test instructions

# Test Fix
Improved content with better error handling.

## Steps
1. Do the thing
2. Handle errors properly

{EVOLUTION_COMPLETE}"""

    mock_client = MagicMock()
    mock_client.complete.return_value = evolved_content

    result = evolve_skill(
        conn=conn,
        llm_client=mock_client,
        skill_id=sid,
        skill_name="test-fix",
        skill_dir=skill_dir,
        direction="Fix the broken test instructions",
        failure_context="Tests kept failing",
        tool_issues="",
        metric_summary="completion_rate=0.15",
    )

    test("evolve_skill returns result", result is not None)
    test("Result success", result["success"] is True)
    test("Result has change_summary", "broken test" in result.get("change_summary", ""))
    test("LLM called once (success on first try)", mock_client.complete.call_count == 1)

    # Verify SKILL.md updated
    with open(md_path) as f:
        new_content = f.read()
    test("SKILL.md updated", "Improved content" in new_content)
    test("SKILL.md no token leak", EVOLUTION_COMPLETE not in new_content)

    conn.close()


# ── evolve_skill: iteration with nudge ──
print("\n--- skill_evolver: evolve_skill with nudge ---")

with tempfile.TemporaryDirectory() as tmpdir:
    db_path = os.path.join(tmpdir, "skills.db")
    conn = init_db(db_path)
    sid = get_or_create_skill(conn, "nudge-test", "Needs nudge", tmpdir)

    skill_dir = os.path.join(tmpdir, "nudge-test")
    os.makedirs(skill_dir, exist_ok=True)
    md_path = os.path.join(skill_dir, "SKILL.md")
    with open(md_path, "w") as f:
        f.write("# Nudge Test\nOriginal.\n")

    # First call: no termination token
    ambiguous_response = (
        "CHANGE_SUMMARY: Tweaked things\n\n# Nudge Test\nBetter content.\n"
    )
    # Second call: includes EVOLUTION_COMPLETE
    final_response = f"CHANGE_SUMMARY: Properly fixed\n\n# Nudge Test\nFinal good content.\n\n{EVOLUTION_COMPLETE}"

    mock_client = MagicMock()
    mock_client.complete.side_effect = [ambiguous_response, final_response]

    result = evolve_skill(
        conn=conn,
        llm_client=mock_client,
        skill_id=sid,
        skill_name="nudge-test",
        skill_dir=skill_dir,
        direction="Fix it",
        failure_context="",
        tool_issues="",
        metric_summary="",
    )

    test("Nudge: success after 2 iterations", result["success"] is True)
    test(
        "Nudge: LLM called twice",
        mock_client.complete.call_count == 2,
        f"called {mock_client.complete.call_count}",
    )

    conn.close()


# ── evolve_skill: EVOLUTION_FAILED ──
print("\n--- skill_evolver: evolve_skill failed ---")

with tempfile.TemporaryDirectory() as tmpdir:
    db_path = os.path.join(tmpdir, "skills.db")
    conn = init_db(db_path)
    sid = get_or_create_skill(conn, "fail-test", "Will fail", tmpdir)

    skill_dir = os.path.join(tmpdir, "fail-test")
    os.makedirs(skill_dir, exist_ok=True)
    md_path = os.path.join(skill_dir, "SKILL.md")
    original = "# Fail Test\nOriginal stays.\n"
    with open(md_path, "w") as f:
        f.write(original)

    fail_response = f"{EVOLUTION_FAILED}\nReason: External issue, not fixable in skill."

    mock_client = MagicMock()
    mock_client.complete.return_value = fail_response

    result = evolve_skill(
        conn=conn,
        llm_client=mock_client,
        skill_id=sid,
        skill_name="fail-test",
        skill_dir=skill_dir,
        direction="Try to fix",
        failure_context="",
        tool_issues="",
        metric_summary="",
    )

    test("Failed: success is False", result["success"] is False)

    # SKILL.md should NOT be changed
    with open(md_path) as f:
        content = f.read()
    test("Failed: SKILL.md unchanged", content == original)

    conn.close()


# ── evolve_skill: max iterations exhausted ──
print("\n--- skill_evolver: Max iterations ---")

with tempfile.TemporaryDirectory() as tmpdir:
    db_path = os.path.join(tmpdir, "skills.db")
    conn = init_db(db_path)
    sid = get_or_create_skill(conn, "exhaust", "Max out", tmpdir)

    skill_dir = os.path.join(tmpdir, "exhaust")
    os.makedirs(skill_dir, exist_ok=True)
    md_path = os.path.join(skill_dir, "SKILL.md")
    with open(md_path, "w") as f:
        f.write("# Exhaust\nOriginal.\n")

    # Always return ambiguous (no termination token)
    mock_client = MagicMock()
    mock_client.complete.return_value = (
        "CHANGE_SUMMARY: Tried\n\n# Exhaust\nSome content.\n"
    )

    result = evolve_skill(
        conn=conn,
        llm_client=mock_client,
        skill_id=sid,
        skill_name="exhaust",
        skill_dir=skill_dir,
        direction="Fix",
        failure_context="",
        tool_issues="",
        metric_summary="",
    )

    test("Exhausted: success is False", result["success"] is False)
    test(
        "Exhausted: called MAX_ITERATIONS times",
        mock_client.complete.call_count == MAX_ITERATIONS,
        f"called {mock_client.complete.call_count}",
    )

    conn.close()


# ── Lineage recording ──
print("\n--- skill_evolver: Lineage ---")

with tempfile.TemporaryDirectory() as tmpdir:
    db_path = os.path.join(tmpdir, "skills.db")
    conn = init_db(db_path)
    sid = get_or_create_skill(conn, "lineage-test", "Track lineage", tmpdir)

    skill_dir = os.path.join(tmpdir, "lineage-test")
    os.makedirs(skill_dir, exist_ok=True)
    md_path = os.path.join(skill_dir, "SKILL.md")
    with open(md_path, "w") as f:
        f.write("# Lineage\nOld.\n")

    good = f"CHANGE_SUMMARY: Fixed lineage test\n\n# Lineage\nNew improved.\n\n{EVOLUTION_COMPLETE}"
    mock_client = MagicMock()
    mock_client.complete.return_value = good

    result = evolve_skill(
        conn=conn,
        llm_client=mock_client,
        skill_id=sid,
        skill_name="lineage-test",
        skill_dir=skill_dir,
        direction="Fix lineage tracking",
        failure_context="",
        tool_issues="",
        metric_summary="",
    )

    test("Lineage: has new_skill_id", "new_skill_id" in result)
    if result.get("new_skill_id"):
        new_sid = result["new_skill_id"]
        test("Lineage: new ID has v1 format", "__v1_" in new_sid, f"got {new_sid}")

        # Check lineage parent recorded
        lineage = get_skill_lineage(conn, new_sid)
        test(
            "Lineage: parent recorded",
            len(lineage["parents"]) == 1,
            f"parents: {lineage['parents']}",
        )

        # Check new record generation
        new_rec = get_skill_record(conn, new_sid)
        test(
            "Lineage: generation is 1",
            new_rec["lineage_generation"] == 1,
            f"got {new_rec['lineage_generation']}",
        )
        test(
            "Lineage: change_summary stored",
            "lineage test" in new_rec["lineage_change_summary"].lower(),
        )

        # Check old skill deactivated
        old_rec = get_skill_record(conn, sid)
        test("Lineage: old skill deactivated", old_rec["is_active"] == 0)

        # Check counter reset (anti-loop)
        test("Lineage: new skill selections = 0", new_rec["total_selections"] == 0)

    conn.close()


# ══════════════════════════════════════════
# DERIVED evolution tests
# ══════════════════════════════════════════

# ── DERIVED prompt building ──
print("\n--- skill_evolver: DERIVED prompt ---")

dprompt = build_derived_prompt(
    parent_content="# Commit\nBasic commit flow.",
    direction="Specialize for monorepo commits with scope prefixes",
    execution_insights="Users often need scoped commits in monorepos",
    metric_summary="applied_rate=0.20, completion_rate=0.30",
)
test("DERIVED: has parent content", "Basic commit" in dprompt)
test("DERIVED: has direction", "monorepo" in dprompt)
test("DERIVED: has insights", "scoped commits" in dprompt)
test("DERIVED: has metrics", "applied_rate=0.20" in dprompt)
test(
    "DERIVED: has name instruction",
    "different" in dprompt.lower() and "name" in dprompt.lower(),
)


# ── DERIVED response parsing ──
print("\n--- skill_evolver: Parse DERIVED response ---")

derived_response = f"""CHANGE_SUMMARY: Created monorepo-commit skill specialized for scoped commits
NEW_SKILL_NAME: monorepo-commit

# Monorepo Commit
Scoped commit flow for monorepos with conventional commit prefixes.

## Steps
1. Detect monorepo structure
2. Scope changes by package
3. Create scoped commit messages

{EVOLUTION_COMPLETE}"""

parsed_d = parse_derived_response(derived_response)
test("DERIVED parse: complete", parsed_d["complete"] is True)
test("DERIVED parse: new_name extracted", parsed_d["new_name"] == "monorepo-commit")
test("DERIVED parse: has content", "Monorepo Commit" in parsed_d["content"])
test("DERIVED parse: content clean", "NEW_SKILL_NAME:" not in parsed_d["content"])


# ── DERIVED response: no name fallback ──
print("\n--- skill_evolver: DERIVED no name fallback ---")

no_name_resp = f"""CHANGE_SUMMARY: Enhanced for CI pipelines

# CI Commit Helper
Auto-commit for CI pipelines.

{EVOLUTION_COMPLETE}"""

parsed_nn = parse_derived_response(no_name_resp)
test(
    "DERIVED no-name: infers from heading", parsed_nn["new_name"] == "ci-commit-helper"
)


# ── Full evolve_derived ──
print("\n--- skill_evolver: evolve_derived ---")

with tempfile.TemporaryDirectory() as tmpdir:
    db_path = os.path.join(tmpdir, "skills.db")
    conn = init_db(db_path)

    # Create parent skill
    parent_dir = os.path.join(tmpdir, "skill-library", "commit")
    os.makedirs(parent_dir, exist_ok=True)
    with open(os.path.join(parent_dir, "SKILL.md"), "w") as f:
        f.write("# Commit\nBasic commit.\n")
    parent_id = get_or_create_skill(conn, "commit", "Basic commit", parent_dir)

    lib_dir = os.path.join(tmpdir, "skill-library")

    evolved_resp = f"""CHANGE_SUMMARY: Derived monorepo-commit from commit
NEW_SKILL_NAME: monorepo-commit

# Monorepo Commit
Specialized for monorepo scoped commits.

{EVOLUTION_COMPLETE}"""

    mock_client = MagicMock()
    mock_client.complete.return_value = evolved_resp

    result = evolve_derived(
        conn=conn,
        llm_client=mock_client,
        parent_skill_id=parent_id,
        parent_skill_name="commit",
        parent_skill_dir=parent_dir,
        direction="Specialize for monorepos",
        execution_insights="",
        metric_summary="",
        skill_library_dir=lib_dir,
    )

    test("DERIVED: success", result["success"] is True)
    test("DERIVED: has new_name", result.get("new_name") == "monorepo-commit")
    test(
        "DERIVED: has new_skill_id",
        "monorepo-commit__v0_" in result.get("new_skill_id", ""),
    )

    # Check new skill dir created
    new_dir = os.path.join(lib_dir, "monorepo-commit")
    test("DERIVED: new dir exists", os.path.isdir(new_dir))
    test(
        "DERIVED: new SKILL.md exists",
        os.path.exists(os.path.join(new_dir, "SKILL.md")),
    )

    # Parent stays active
    parent_rec = get_skill_record(conn, parent_id)
    test("DERIVED: parent still active", parent_rec["is_active"] == 1)

    # New skill has lineage
    new_sid = result["new_skill_id"]
    lineage = get_skill_lineage(conn, new_sid)
    test("DERIVED: lineage parent recorded", len(lineage["parents"]) == 1)

    new_rec = get_skill_record(conn, new_sid)
    test("DERIVED: generation is 0", new_rec["lineage_generation"] == 0)
    test(
        "DERIVED: origin is evolved_derived",
        new_rec["lineage_origin"] == "evolved_derived",
    )

    conn.close()


# ══════════════════════════════════════════
# CAPTURED evolution tests
# ══════════════════════════════════════════

# ── CAPTURED prompt building ──
print("\n--- skill_evolver: CAPTURED prompt ---")

cprompt = build_captured_prompt(
    direction="Extract the pattern of using git stash before risky operations",
    category="workflow",
    execution_highlights="In 3 tasks, the agent used git stash before refactors",
)
test("CAPTURED: has direction", "git stash" in cprompt)
test("CAPTURED: has category", "workflow" in cprompt)
test("CAPTURED: has highlights", "3 tasks" in cprompt)
test("CAPTURED: has name instruction", "name" in cprompt.lower())


# ── Full evolve_captured ──
print("\n--- skill_evolver: evolve_captured ---")

with tempfile.TemporaryDirectory() as tmpdir:
    db_path = os.path.join(tmpdir, "skills.db")
    conn = init_db(db_path)
    lib_dir = os.path.join(tmpdir, "skill-library")
    os.makedirs(lib_dir, exist_ok=True)

    captured_resp = f"""CHANGE_SUMMARY: Captured git-stash-guard workflow pattern
NEW_SKILL_NAME: git-stash-guard

# Git Stash Guard
Automatically stash uncommitted changes before risky operations.

## Steps
1. Check for uncommitted changes
2. Stash if dirty
3. Run operation
4. Pop stash

{EVOLUTION_COMPLETE}"""

    mock_client = MagicMock()
    mock_client.complete.return_value = captured_resp

    result = evolve_captured(
        conn=conn,
        llm_client=mock_client,
        direction="Extract git stash before risky ops pattern",
        category="workflow",
        execution_highlights="Used in 3 refactoring tasks",
        skill_library_dir=lib_dir,
    )

    test("CAPTURED: success", result["success"] is True)
    test("CAPTURED: has new_name", result.get("new_name") == "git-stash-guard")
    test(
        "CAPTURED: has new_skill_id",
        "git-stash-guard__v0_" in result.get("new_skill_id", ""),
    )

    # Check skill dir created
    new_dir = os.path.join(lib_dir, "git-stash-guard")
    test("CAPTURED: dir exists", os.path.isdir(new_dir))
    with open(os.path.join(new_dir, "SKILL.md")) as f:
        content = f.read()
    test("CAPTURED: SKILL.md has content", "Stash Guard" in content)
    test("CAPTURED: no token leak", EVOLUTION_COMPLETE not in content)

    # Check SQLite record
    new_sid = result["new_skill_id"]
    new_rec = get_skill_record(conn, new_sid)
    test("CAPTURED: origin is captured", new_rec["lineage_origin"] == "captured")
    test("CAPTURED: generation is 0", new_rec["lineage_generation"] == 0)
    test("CAPTURED: no parents", len(get_skill_lineage(conn, new_sid)["parents"]) == 0)

    conn.close()


# ── CAPTURED: EVOLUTION_FAILED ──
print("\n--- skill_evolver: CAPTURED failed ---")

with tempfile.TemporaryDirectory() as tmpdir:
    db_path = os.path.join(tmpdir, "skills.db")
    conn = init_db(db_path)
    lib_dir = os.path.join(tmpdir, "skill-library")
    os.makedirs(lib_dir, exist_ok=True)

    mock_client = MagicMock()
    mock_client.complete.return_value = (
        f"{EVOLUTION_FAILED}\nReason: Pattern too specific to generalize."
    )

    result = evolve_captured(
        conn=conn,
        llm_client=mock_client,
        direction="Extract some niche pattern",
        category="workflow",
        execution_highlights="",
        skill_library_dir=lib_dir,
    )

    test("CAPTURED failed: success is False", result["success"] is False)

    conn.close()


print(f"\n{'=' * 40}")
print(f"skill_evolver: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
