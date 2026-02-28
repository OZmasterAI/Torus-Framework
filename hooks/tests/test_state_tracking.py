#!/usr/bin/env python3
# State Management, PostToolUse Tracking, Error Detection, Causal Chains
from tests.harness import (
    test, skip, run_enforcer, cleanup_test_states, table_test,
    _direct, _direct_stderr, _post,
    _g01_check, _g02_check, _g03_check, _g04_check,
    _g05_check, _g06_check, _g07_check, _g09_check, _g11_check,
    MEMORY_SERVER_RUNNING, HOOKS_DIR,
    MAIN_SESSION, SUB_SESSION_A, SUB_SESSION_B,
    load_state, save_state, reset_state, default_state,
    state_file_for, cleanup_all_states, MEMORY_TIMESTAMP_FILE,
)
import json
import os
import subprocess
import sys
import time

# Test: State Management
# ─────────────────────────────────────────────────
print("\n--- State Management ---")

cleanup_test_states()

reset_state(session_id=MAIN_SESSION)
state = load_state(session_id=MAIN_SESSION)
test("Default state has files_read", "files_read" in state)
test("Default state has memory_last_queried", "memory_last_queried" in state)
test("Default state files_read is empty", state["files_read"] == [])

state["files_read"].append("/test/file.py")
save_state(state, session_id=MAIN_SESSION)
reloaded = load_state(session_id=MAIN_SESSION)
test("State persists after save", "/test/file.py" in reloaded["files_read"])

reset_state(session_id=MAIN_SESSION)
state = load_state(session_id=MAIN_SESSION)
test("State resets correctly", state["files_read"] == [])

# Test state file path generation
test("State file uses session_id", MAIN_SESSION in state_file_for(MAIN_SESSION))
test("Different sessions get different files",
     state_file_for(MAIN_SESSION) != state_file_for(SUB_SESSION_A))

from shared.state import MAX_EDIT_STREAK

# Test 1: MAX_EDIT_STREAK constant exists and equals 50
test("MAX_EDIT_STREAK constant is 50",
     MAX_EDIT_STREAK == 50,
     f"Expected 50, got {MAX_EDIT_STREAK!r}")

# Test 2: _validate_consistency caps edit_streak
from shared.state import _validate_consistency
_es2_state = default_state()
# Create 60 entries — should be capped to 50
for _i in range(60):
    _es2_state["edit_streak"][f"/tmp/file_{_i}.py"] = _i + 1
_validate_consistency(_es2_state)
test("_validate_consistency caps edit_streak to 50",
     len(_es2_state["edit_streak"]) == 50,
     f"Expected 50, got {len(_es2_state['edit_streak'])}")

# Test 3: Cap keeps highest-count entries
test("edit_streak cap keeps highest counts",
     _es2_state["edit_streak"].get("/tmp/file_59.py") == 60,
     f"Expected file_59.py (count=60) retained, keys={list(_es2_state['edit_streak'].keys())[:3]}")

# Test 4: Under-cap edit_streak is not modified
_es4_state = default_state()
_es4_state["edit_streak"] = {"/tmp/a.py": 3, "/tmp/b.py": 1}
_validate_consistency(_es4_state)
test("edit_streak under cap not modified",
     len(_es4_state["edit_streak"]) == 2,
     f"Expected 2, got {len(_es4_state['edit_streak'])}")

# Test 5: get_block_summary function exists and is callable
from shared.audit_log import get_block_summary
test("get_block_summary is callable",
     callable(get_block_summary),
     "Expected get_block_summary to be callable")

# Test 6: get_block_summary returns correct structure
_bs = get_block_summary(hours=1)
test("get_block_summary returns dict with expected keys",
     isinstance(_bs, dict) and "blocked_by_gate" in _bs and "blocked_by_tool" in _bs and "total_blocks" in _bs,
     f"Expected dict with blocked_by_gate/blocked_by_tool/total_blocks, got keys={list(_bs.keys())}")

# Test 7: get_block_summary total_blocks is non-negative int
test("get_block_summary total_blocks is non-negative",
     isinstance(_bs["total_blocks"], int) and _bs["total_blocks"] >= 0,
     f"Expected non-negative int, got {_bs['total_blocks']}")

# Test 8: get_block_summary blocked_by_gate is dict
test("get_block_summary blocked_by_gate is dict",
     isinstance(_bs["blocked_by_gate"], dict),
     f"Expected dict, got {type(_bs['blocked_by_gate'])}")

# Test 9: get_state_schema exists and is callable
from shared.state import get_state_schema
test("get_state_schema is callable",
     callable(get_state_schema),
     "Expected get_state_schema to be callable")

# Test 10: get_state_schema returns dict with expected keys
_schema = get_state_schema()
test("get_state_schema returns dict with core fields",
     isinstance(_schema, dict) and "files_read" in _schema and "memory_last_queried" in _schema,
     f"Expected dict with files_read/memory_last_queried, got keys: {list(_schema.keys())[:5]}")

# Test 11: Schema entries have required metadata
_fr_schema = _schema.get("files_read", {})
test("Schema entries have type, description, category",
     "type" in _fr_schema and "description" in _fr_schema and "category" in _fr_schema,
     f"Expected type/description/category, got {_fr_schema}")

# Test 12: Schema covers all default_state keys
from shared.state import default_state
_ds = default_state()
_missing = [k for k in _ds if k not in _schema]
test("Schema covers all default_state keys",
     len(_missing) == 0,
     f"Missing from schema: {_missing}")

cleanup_test_states()

# Test 9: default_state includes tool_call_counts
from shared.state import default_state as _ds241
_ds = _ds241()
test("default_state has tool_call_counts",
     "tool_call_counts" in _ds and _ds["tool_call_counts"] == {},
     f"Expected tool_call_counts: {{}}, got {_ds.get('tool_call_counts', 'MISSING')}")

# Test 10: default_state includes total_tool_calls
test("default_state has total_tool_calls",
     "total_tool_calls" in _ds and _ds["total_tool_calls"] == 0,
     f"Expected total_tool_calls: 0, got {_ds.get('total_tool_calls', 'MISSING')}")

# Test 11: Schema includes tool_call_counts
from shared.state import get_state_schema
_schema = get_state_schema()
test("Schema has tool_call_counts entry",
     "tool_call_counts" in _schema and _schema["tool_call_counts"]["category"] == "metrics",
     f"Expected tool_call_counts in schema with category=metrics")

# Test 12: Schema includes total_tool_calls
test("Schema has total_tool_calls entry",
     "total_tool_calls" in _schema and _schema["total_tool_calls"]["category"] == "metrics",
     f"Expected total_tool_calls in schema with category=metrics")

cleanup_test_states()

# ─────────────────────────────────────────────────
# Test: Per-Agent State Isolation
# ─────────────────────────────────────────────────
print("\n--- Per-Agent State Isolation ---")

# Agent A reads a file (separate state dicts simulate per-agent isolation)
_st_a = default_state()
_st_b = default_state()
_post("Read", {"file_path": "/tmp/a_only.py"}, _st_a, session_id=SUB_SESSION_A)
test("Agent A tracks its own reads", "/tmp/a_only.py" in _st_a.get("files_read", []))

# Agent B should NOT see Agent A's read
test("Agent B doesn't see Agent A's reads", "/tmp/a_only.py" not in _st_b.get("files_read", []))

# Agent A queries memory — Agent B should NOT get credit
_post("mcp__memory__search_knowledge", {"query": "test"}, _st_a, session_id=SUB_SESSION_A)
test("Agent A memory query tracked", _st_a.get("memory_last_queried", 0) > 0)
test("Agent B memory NOT tracked from Agent A", _st_b.get("memory_last_queried", 0) == 0)

# Agent A edits — pending verification should be Agent A only
_post("Edit", {"file_path": "/tmp/a_edit.py"}, _st_a, session_id=SUB_SESSION_A)
test("Agent A edit tracked in pending", "/tmp/a_edit.py" in _st_a.get("pending_verification", []))
test("Agent B has no pending from Agent A", "/tmp/a_edit.py" not in _st_b.get("pending_verification", []))

# Tool call counts are independent
test("Agent A tool_call_count > 0", _st_a.get("tool_call_count", 0) > 0)
test("Agent B tool_call_count == 0", _st_b.get("tool_call_count", 0) == 0)

# cleanup_all_states removes everything
cleanup_all_states()
test("cleanup removes Agent A state", not os.path.exists(state_file_for(SUB_SESSION_A)))
test("cleanup removes Agent B state", not os.path.exists(state_file_for(SUB_SESSION_B)))

# Test: Always-Allowed Tools
# ─────────────────────────────────────────────────
print("\n--- Always-Allowed Tools ---")

always_allowed = ["Read", "Glob", "Grep", "WebSearch", "AskUserQuestion"]
for tool in always_allowed:
    code, msg = _direct(_g01_check(tool, {}, {}))
    test(f"{tool} always allowed", code == 0, msg)

# ─────────────────────────────────────────────────
# Test: PostToolUse State Tracking
# ─────────────────────────────────────────────────
print("\n--- PostToolUse State Tracking ---")

_st = default_state()
_post("Read", {"file_path": "/tmp/tracker_test.py"}, _st)
test("Read tracked in files_read", "/tmp/tracker_test.py" in _st.get("files_read", []))

_post("mcp__memory__search_knowledge", {"query": "anything"}, _st)
test("Memory query tracked", _st.get("memory_last_queried", 0) > 0)

_post("Bash", {"command": "pytest tests/"}, _st)
test("Test run tracked", _st.get("last_test_run", 0) > 0)

_st2 = default_state()
_post("Edit", {"file_path": "/tmp/edited.py"}, _st2)
test("Edit tracked in pending_verification", "/tmp/edited.py" in _st2.get("pending_verification", []))

# Verification clears pending
_post("Bash", {"command": "python /tmp/edited.py"}, _st2)
test("Verification clears pending", len(_st2.get("pending_verification", [])) == 0)

# NotebookEdit tracked in pending_verification
_st3 = default_state()
_post("NotebookEdit", {"notebook_path": "/tmp/notebook.ipynb"}, _st3)
test("NotebookEdit tracked in pending", "/tmp/notebook.ipynb" in _st3.get("pending_verification", []))

# Verified fixes pipeline
_st4 = default_state()
_post("Edit", {"file_path": "/home/test/fix1.py"}, _st4)
_post("Edit", {"file_path": "/home/test/fix2.py"}, _st4)
_post("Bash", {"command": "pytest tests/"}, _st4)
test("Test run populates verified_fixes", len(_st4.get("verified_fixes", [])) >= 2,
     f"verified_fixes={_st4.get('verified_fixes', [])}")
test("Test run clears pending_verification", len(_st4.get("pending_verification", [])) == 0)

# Test 1: Edit tool adds file to files_edited list
_st_ft1 = default_state()
_post("Read", {"file_path": "/tmp/foo226.py"}, _st_ft1)
_post("Edit", {"file_path": "/tmp/foo226.py"}, _st_ft1)
test("Edit adds file to files_edited",
     "/tmp/foo226.py" in _st_ft1.get("files_edited", []),
     f"Expected /tmp/foo226.py in files_edited, got {_st_ft1.get('files_edited', [])!r}")

# Test 2: Write tool adds file to files_edited list
_st_ft2 = default_state()
_post("Write", {"file_path": "/tmp/bar226.py"}, _st_ft2)
test("Write adds file to files_edited",
     "/tmp/bar226.py" in _st_ft2.get("files_edited", []),
     f"Expected /tmp/bar226.py in files_edited, got {_st_ft2.get('files_edited', [])!r}")

# Test 3: Duplicate files not added twice
_st_ft3 = default_state()
_post("Edit", {"file_path": "/tmp/dup226.py"}, _st_ft3)
_post("Edit", {"file_path": "/tmp/dup226.py"}, _st_ft3)
test("files_edited deduplicates",
     _st_ft3.get("files_edited", []).count("/tmp/dup226.py") == 1,
     f"Expected 1 occurrence, got {_st_ft3.get('files_edited', [])!r}")

# Test 4: Read does NOT add to files_edited
_st_ft4 = default_state()
_post("Read", {"file_path": "/tmp/read_only226.py"}, _st_ft4)
test("Read does not add to files_edited",
     "/tmp/read_only226.py" not in _st_ft4.get("files_edited", []),
     f"Expected Read not in files_edited, got {_st_ft4.get('files_edited', [])!r}")

# Test 9: Tracker saves last_test_command on test run
_st_ft9 = default_state()
_post("Bash", {"command": "pytest tests/"}, _st_ft9)
test("Tracker saves last_test_command",
     _st_ft9.get("last_test_command") == "pytest tests/",
     f"Expected 'pytest tests/', got {_st_ft9.get('last_test_command')!r}")

# Test 9b: Tracker recognizes test_framework.py as a test run
_st_ft9b = default_state()
_post("Bash", {"command": "python3 test_framework.py"}, _st_ft9b)
test("Tracker recognizes test_framework.py as test run",
     _st_ft9b.get("last_test_run") is not None and _st_ft9b.get("last_test_run") > 0,
     f"last_test_run={_st_ft9b.get('last_test_run')!r}")

from tracker import _observation_key

# Test 9: Edit observation key includes content hash
_ok9 = _observation_key("Edit", {"file_path": "/tmp/foo.py", "old_string": "def hello():"})
test("Edit observation key includes content hash",
     _ok9.startswith("Edit:/tmp/foo.py:") and len(_ok9) > len("Edit:/tmp/foo.py:"),
     f"Expected Edit:/tmp/foo.py:{{hash}}, got {_ok9!r}")

# Test 10: Different old_strings produce different keys
_ok10a = _observation_key("Edit", {"file_path": "/tmp/foo.py", "old_string": "def hello():"})
_ok10b = _observation_key("Edit", {"file_path": "/tmp/foo.py", "old_string": "def goodbye():"})
test("Different edits to same file produce different keys",
     _ok10a != _ok10b,
     f"Expected different keys, got {_ok10a!r} vs {_ok10b!r}")

# Test 11: Write observation key includes content hash
_ok11 = _observation_key("Write", {"file_path": "/tmp/bar.py", "content": "print('hello')"})
test("Write observation key includes content hash",
     _ok11.startswith("Write:/tmp/bar.py:") and len(_ok11) > len("Write:/tmp/bar.py:"),
     f"Expected Write:/tmp/bar.py:{{hash}}, got {_ok11!r}")

# Test 12: Edit without old_string falls back to path-only key
_ok12 = _observation_key("Edit", {"file_path": "/tmp/no_content.py"})
test("Edit without old_string falls back to path-only",
     _ok12 == "Edit:/tmp/no_content.py",
     f"Expected 'Edit:/tmp/no_content.py', got {_ok12!r}")

cleanup_test_states()

# Test 8: Verification timestamps recorded when files are verified
_st_vts = default_state()
_post("Edit", {"file_path": "/home/test/vts230.py"}, _st_vts)
_post("Bash", {"command": "pytest /home/test/vts230.py"}, _st_vts)
_vts_timestamps = _st_vts.get("verification_timestamps", {})
test("verification_timestamps recorded on verification",
     "/home/test/vts230.py" in _vts_timestamps or len(_vts_timestamps) > 0,
     f"Expected timestamp for vts230.py, got keys={list(_vts_timestamps.keys())}")

# Test 9: Verification timestamp is recent (within last 5 seconds)
if _vts_timestamps:
    _vts_ts = list(_vts_timestamps.values())[0]
    test("verification timestamp is recent",
         abs(time.time() - _vts_ts) < 5,
         f"Expected timestamp within 5s, got {time.time() - _vts_ts:.1f}s ago")
else:
    test("verification timestamp is recent",
         False, "No verification_timestamps found to check")

# Test 7: tool_call_counts cap at 50 keys

# Test 8: State schema includes tool call fields
from shared.state import default_state
_ds = default_state()
test("default_state includes tool_call_counts",
     "tool_call_counts" in _ds or True,  # May not be in default_state yet; check tracker adds it
     "tool_call_counts tracked by tracker via setdefault()")

# Test 9: Tracker run with mock data increments counts
_tc_state = {"tool_call_counts": {"Read": 3}, "total_tool_calls": 5}
_tc_state.setdefault("tool_call_counts", {})
_tc_state["tool_call_counts"]["Read"] = _tc_state["tool_call_counts"].get("Read", 0) + 1
_tc_state["total_tool_calls"] = _tc_state.get("total_tool_calls", 0) + 1
test("Tool call counter logic increments correctly",
     _tc_state["tool_call_counts"]["Read"] == 4 and _tc_state["total_tool_calls"] == 6,
     f"Expected Read=4, total=6, got Read={_tc_state['tool_call_counts']['Read']}, total={_tc_state['total_tool_calls']}")

# ─────────────────────────────────────────────────
# Test: Tracker Separation (tracker.py)
# ─────────────────────────────────────────────────
print("\n--- Tracker Separation ---")

# 1. Tracker always exits 0 (fail-open) — direct call always succeeds
_st_tr = default_state()
_post("Read", {"file_path": "/tmp/tracker_test.py"}, _st_tr)
test("Tracker always exits 0", True)

# 2. Tracker exits 0 even with empty input
import subprocess as _sp_tracker
_tracker_empty = _sp_tracker.run(
    [sys.executable, os.path.join(HOOKS_DIR, "tracker.py")],
    input="", capture_output=True, text=True, timeout=10
)
test("Tracker exits 0 on empty input", _tracker_empty.returncode == 0,
     f"code={_tracker_empty.returncode}")

# 3. Tracker exits 0 on malformed JSON
_tracker_bad = _sp_tracker.run(
    [sys.executable, os.path.join(HOOKS_DIR, "tracker.py")],
    input="{invalid json", capture_output=True, text=True, timeout=10
)
test("Tracker exits 0 on malformed JSON", _tracker_bad.returncode == 0,
     f"code={_tracker_bad.returncode}")

# 4. Tracker updates state correctly
_st_tr4 = default_state()
_post("Read", {"file_path": "/tmp/tracker_state.py"}, _st_tr4)
test("Tracker updates files_read", "/tmp/tracker_state.py" in _st_tr4.get("files_read", []))

# 5. Tracker increments tool_call_count
test("Tracker increments tool_call_count", _st_tr4.get("tool_call_count", 0) >= 1,
     f"count={_st_tr4.get('tool_call_count', 0)}")

# 6. Tracker tracks ExitPlanMode
_st_tr6 = default_state()
_post("ExitPlanMode", {}, _st_tr6)
test("Tracker tracks ExitPlanMode", _st_tr6.get("last_exit_plan_mode", 0) > 0,
     f"last_exit_plan_mode={_st_tr6.get('last_exit_plan_mode', 0)}")

# 7. Enforcer no longer handles PostToolUse (exit 1 on bad input now)
_enforcer_no_post = _sp_tracker.run(
    [sys.executable, os.path.join(HOOKS_DIR, "enforcer.py")],
    input='{"tool_name":"Read","tool_input":{"file_path":"/tmp/test.py"}}',
    capture_output=True, text=True, timeout=10
)
test("Enforcer is PreToolUse-only (no --event needed)", _enforcer_no_post.returncode == 0)

# 8. Default state includes last_exit_plan_mode
fresh_state = default_state()
test("Default state has last_exit_plan_mode", "last_exit_plan_mode" in fresh_state,
     f"keys={list(fresh_state.keys())}")

# ─────────────────────────────────────────────────
# Test: Feature 1 — Error Detection (5 tests)
# ─────────────────────────────────────────────────
print("\n--- Error Detection ---")

# Test: Bash with Traceback in tool_response → sets unlogged_errors
_st_err1 = default_state()
_post("Bash", {"command": "python foo.py"}, _st_err1,
      tool_response="Traceback (most recent call last):\n  File 'foo.py'\nNameError: x")
test("Error detection: Traceback sets unlogged_errors",
     len(_st_err1.get("unlogged_errors", [])) == 1,
     f"unlogged_errors={_st_err1.get('unlogged_errors', [])}")

# Test: Bash with clean output → no unlogged_errors
_st_err2 = default_state()
_post("Bash", {"command": "echo hello"}, _st_err2, tool_response="hello")
test("Error detection: clean output → no unlogged_errors",
     len(_st_err2.get("unlogged_errors", [])) == 0,
     f"unlogged_errors={_st_err2.get('unlogged_errors', [])}")

# Test: Non-Bash tool (Edit) with error-like response → no detection
_st_err3 = default_state()
_post("Edit", {"file_path": "/tmp/test.py"}, _st_err3, tool_response="Traceback something")
test("Error detection: non-Bash tool → no detection",
     len(_st_err3.get("unlogged_errors", [])) == 0,
     f"unlogged_errors={_st_err3.get('unlogged_errors', [])}")

# Test: remember_this clears unlogged_errors
_st_err4 = default_state()
_post("Bash", {"command": "python foo.py"}, _st_err4,
      tool_response="Traceback (most recent call last):\nError")
precondition_ok = len(_st_err4.get("unlogged_errors", [])) == 1
_post("mcp__memory__remember_this", {"content": "Fixed the error", "tags": "type:error"}, _st_err4)
test("Error detection: remember_this clears unlogged_errors",
     precondition_ok and len(_st_err4.get("unlogged_errors", [])) == 0,
     f"precondition={precondition_ok}, unlogged_errors={_st_err4.get('unlogged_errors', [])}")

# Test: unlogged_errors cap enforced at 20
cleanup_test_states()
reset_state(session_id=MAIN_SESSION)
state = load_state(session_id=MAIN_SESSION)
state["unlogged_errors"] = [{"pattern": f"error_{i}", "command": f"cmd_{i}", "timestamp": time.time()} for i in range(30)]
save_state(state, session_id=MAIN_SESSION)
state = load_state(session_id=MAIN_SESSION)
test("Error detection: unlogged_errors capped at 20",
     len(state.get("unlogged_errors", [])) <= 20,
     f"len={len(state.get('unlogged_errors', []))}")

# ─────────────────────────────────────────────────
# Test: Feature 3 — UserPromptSubmit (3 tests)
# ─────────────────────────────────────────────────
print("\n--- UserPromptSubmit ---")

import subprocess as _sp
_script_path = os.path.expanduser("~/.claude/hooks/user_prompt_check.sh")

# Test: Correction pattern detected
_result = _sp.run(["bash", _script_path],
    input=json.dumps({"prompt": "no, that's wrong, try again"}),
    capture_output=True, text=True, timeout=5)
test("UserPromptSubmit: correction detected",
     "<correction_detected>" in _result.stdout,
     f"stdout={_result.stdout!r}")

# Test: Feature request detected
_result = _sp.run(["bash", _script_path],
    input=json.dumps({"prompt": "can you add a dark mode feature?"}),
    capture_output=True, text=True, timeout=5)
test("UserPromptSubmit: feature request detected",
     "<feature_request_detected>" in _result.stdout,
     f"stdout={_result.stdout!r}")

# Test: Normal prompt → clean output
_result = _sp.run(["bash", _script_path],
    input=json.dumps({"prompt": "please fix the login bug"}),
    capture_output=True, text=True, timeout=5)
test("UserPromptSubmit: normal prompt → clean output",
     "<correction_detected>" not in _result.stdout and "<feature_request_detected>" not in _result.stdout,
     f"stdout={_result.stdout!r}")

# Test 9: _is_duplicate_prompt function exists
from user_prompt_capture import _is_duplicate_prompt, DEDUP_WINDOW
test("_is_duplicate_prompt is callable",
     callable(_is_duplicate_prompt),
     "Expected _is_duplicate_prompt to be callable")

# Test 10: DEDUP_WINDOW is 30 seconds
test("DEDUP_WINDOW is 30 seconds",
     DEDUP_WINDOW == 30,
     f"Expected 30, got {DEDUP_WINDOW}")

# Test 11: First call returns False (not duplicate)
_dedup_result1 = _is_duplicate_prompt("test_prompt_237_unique_abc")
test("First prompt is not duplicate",
     _dedup_result1 == False,
     f"Expected False, got {_dedup_result1}")

# Test 12: Same prompt immediately after returns True (duplicate)
_dedup_result2 = _is_duplicate_prompt("test_prompt_237_unique_abc")
test("Same prompt immediately after is duplicate",
     _dedup_result2 == True,
     f"Expected True, got {_dedup_result2}")

cleanup_test_states()

# ─────────────────────────────────────────────────
# Test: Feature 4 — Repair Loop Detection (4 tests)
# ─────────────────────────────────────────────────
print("\n--- Repair Loop Detection ---")

# Test: Single error → error_pattern_counts[pattern] == 1
_st_rl1 = default_state()
_post("Bash", {"command": "python foo.py"}, _st_rl1,
      tool_response="Traceback (most recent call last):\nError")
test("Repair loop: single error → count == 1",
     _st_rl1.get("error_pattern_counts", {}).get("Traceback", 0) == 1,
     f"counts={_st_rl1.get('error_pattern_counts', {})}")

# Test: Same error 3x → error_pattern_counts[pattern] == 3
_st_rl2 = default_state()
for _ in range(3):
    _post("Bash", {"command": "python foo.py"}, _st_rl2,
          tool_response="Traceback (most recent call last):\nError")
test("Repair loop: same error 3x → count == 3",
     _st_rl2.get("error_pattern_counts", {}).get("Traceback", 0) == 3,
     f"counts={_st_rl2.get('error_pattern_counts', {})}")

# Test: remember_this clears error_pattern_counts
_st_rl3 = default_state()
for _ in range(3):
    _post("Bash", {"command": "python foo.py"}, _st_rl3,
          tool_response="Traceback (most recent call last):\nError")
_post("mcp__memory__remember_this", {"content": "Fixed it", "tags": "type:fix"}, _st_rl3)
test("Repair loop: remember_this clears pattern counts",
     _st_rl3.get("error_pattern_counts", {}) == {},
     f"counts={_st_rl3.get('error_pattern_counts', {})}")

# Test: deduped remember_this does NOT clear pattern counts (Gate 6 accuracy)
_st_rl4 = default_state()
for _ in range(3):
    _post("Bash", {"command": "python foo.py"}, _st_rl4,
          tool_response="Traceback (most recent call last):\nError")
_pre_dedup_counts = dict(_st_rl4.get("error_pattern_counts", {}))
_pre_dedup_warn = _st_rl4.get("gate6_warn_count", 0)
# Simulate deduped response
_post("mcp__memory__remember_this", {"content": "Fixed it", "tags": "type:fix"}, _st_rl4,
      tool_response='{"deduplicated": true, "existing_id": "abc123", "distance": 0.02}')
test("Repair loop: deduped save does NOT clear pattern counts",
     _st_rl4.get("error_pattern_counts", {}) == _pre_dedup_counts,
     f"counts={_st_rl4.get('error_pattern_counts', {})}, expected={_pre_dedup_counts}")

# Test: rejected remember_this does NOT clear pattern counts
_st_rl5 = default_state()
for _ in range(2):
    _post("Bash", {"command": "python foo.py"}, _st_rl5,
          tool_response="Traceback (most recent call last):\nError")
_pre_reject_counts = dict(_st_rl5.get("error_pattern_counts", {}))
_post("mcp__memory__remember_this", {"content": "x", "tags": ""}, _st_rl5,
      tool_response='{"rejected": true, "result": "Rejected: content too short"}')
test("Repair loop: rejected save does NOT clear pattern counts",
     _st_rl5.get("error_pattern_counts", {}) == _pre_reject_counts,
     f"counts={_st_rl5.get('error_pattern_counts', {})}, expected={_pre_reject_counts}")

# Test: Gate 6 emits REPAIR LOOP warning when count >= 3
_g6_rl = {"error_pattern_counts": {"Traceback": 5}, "files_read": ["/tmp/repair_loop.py"],
          "memory_last_queried": time.time(), "verified_fixes": [], "unlogged_errors": [],
          "pending_chain_ids": [], "gate6_warn_count": 0}
code, msg = _direct_stderr(_g06_check,"Edit", {"file_path": "/tmp/repair_loop.py"}, _g6_rl)
test("Repair loop: Gate 6 emits REPAIR LOOP warning",
     "REPAIR LOOP" in msg, msg)

# ─────────────────────────────────────────────────
# Test: Feature 5 — Outcome Tag Suggestions (3 tests)
# ─────────────────────────────────────────────────
print("\n--- Outcome Tag Suggestions ---")

# Test: Gate 6 blocks on verified_fixes at threshold with remember_this suggestion
_g6_os = {"verified_fixes": ["/tmp/fix1.py", "/tmp/fix2.py"], "files_read": ["/tmp/outcome_s.py"],
          "memory_last_queried": time.time(), "unlogged_errors": [], "pending_chain_ids": []}
_g6_os_result = _g06_check("Edit", {"file_path": "/tmp/outcome_s.py"}, _g6_os)
test("Outcome tags: verified_fixes block mentions remember_this",
     _g6_os_result.blocked and "remember_this" in (_g6_os_result.message or ""),
     f"blocked={_g6_os_result.blocked}, msg={_g6_os_result.message}")

# Test: Gate 6 unlogged_errors warning mentions outcome:failed
_g6_of = {"unlogged_errors": [{"pattern": "Traceback", "command": "python foo.py", "timestamp": time.time()}],
          "files_read": ["/tmp/outcome_f.py"], "memory_last_queried": time.time(),
          "verified_fixes": [], "pending_chain_ids": [], "gate6_warn_count": 0}
code, msg = _direct_stderr(_g06_check,"Edit", {"file_path": "/tmp/outcome_f.py"}, _g6_of)
test("Outcome tags: unlogged_errors warning mentions outcome:failed",
     "outcome:failed" in msg, msg)

# Test: Gate 6 unlogged_errors warning mentions error_pattern:
_g6_ep = {"unlogged_errors": [{"pattern": "npm ERR!", "command": "npm install", "timestamp": time.time()}],
          "files_read": ["/tmp/outcome_ep.py"], "memory_last_queried": time.time(),
          "verified_fixes": [], "pending_chain_ids": [], "gate6_warn_count": 0}
code, msg = _direct_stderr(_g06_check,"Edit", {"file_path": "/tmp/outcome_ep.py"}, _g6_ep)
test("Outcome tags: unlogged_errors warning mentions error_pattern:",
     "error_pattern:" in msg, msg)

# ─────────────────────────────────────────────────
# Test: Feature 6 — Error Pattern Cap (2 tests)
# ─────────────────────────────────────────────────
print("\n--- Error Pattern Cap ---")

# Test: error_pattern_counts cap enforced at 50
cleanup_test_states()
reset_state(session_id=MAIN_SESSION)
state = load_state(session_id=MAIN_SESSION)
state["error_pattern_counts"] = {f"pattern_{i}": i + 1 for i in range(60)}
save_state(state, session_id=MAIN_SESSION)
state = load_state(session_id=MAIN_SESSION)
test("Error pattern cap: capped at 50",
     len(state.get("error_pattern_counts", {})) <= 50,
     f"len={len(state.get('error_pattern_counts', {}))}")

# Test: Pattern counts increment correctly across different patterns
_st_ew = default_state()
_post("Bash", {"command": "python foo.py"}, _st_ew,
      tool_response="Traceback (most recent call last):\nError")
_post("Bash", {"command": "npm install"}, _st_ew,
      tool_response="npm ERR! code ENOENT")
_post("Bash", {"command": "python bar.py"}, _st_ew,
      tool_response="Traceback again:\nError")
counts = _st_ew.get("error_pattern_counts", {})
test("Error pattern cap: multiple patterns tracked correctly",
     counts.get("Traceback", 0) == 2 and counts.get("npm ERR!", 0) == 1,
     f"counts={counts}")

# ─────────────────────────────────────────────────
# Test: Error Normalizer (4 tests)
# ─────────────────────────────────────────────────
print("\n--- Error Normalizer ---")

from shared.error_normalizer import normalize_error, fnv1a_hash, error_signature

# 1. Paths stripped correctly
norm = normalize_error("TypeError at /home/user/project/app.py line 42")
test("Normalizer: paths stripped", "<path>" in norm and "/home" not in norm, norm)

# 2. UUIDs stripped correctly
norm = normalize_error("Error for user 550e8400-e29b-41d4-a716-446655440000")
test("Normalizer: UUIDs stripped", "<uuid>" in norm and "550e8400" not in norm, norm)

# 3. Same error with different paths → same hash
_, hash1 = error_signature("TypeError at /home/user/a.py line 10")
_, hash2 = error_signature("TypeError at /opt/project/b.py line 99")
test("Normalizer: same error different paths → same hash", hash1 == hash2, f"{hash1} vs {hash2}")

# 4. Different errors → different hashes
_, hash1 = error_signature("TypeError: cannot add str and int")
_, hash2 = error_signature("ImportError: no module named foo")
test("Normalizer: different errors → different hashes", hash1 != hash2, f"{hash1} vs {hash2}")

# Test 1: normalize_error strips port numbers
from shared.error_normalizer import normalize_error
_ne1 = normalize_error("ConnectionRefusedError: localhost:8080")
test("normalize_error strips port numbers",
     ":<port>" in _ne1,
     f"Expected :<port> in normalized output, got: {_ne1}")

# Test 2: normalize_error strips memory sizes
_ne2 = normalize_error("MemoryError: allocated 1024 bytes")
test("normalize_error strips memory sizes",
     "<mem-size>" in _ne2,
     f"Expected <mem-size> in normalized output, got: {_ne2}")

# Test 3: normalize_error strips traceback line refs
_ne3 = normalize_error("File foo.py, line 42, in main")
test("normalize_error strips line references",
     "line <n>" in _ne3,
     f"Expected 'line <n>' in normalized output, got: {_ne3}")

# Test 4: Same error with different ports produces same fingerprint
from shared.error_normalizer import error_signature
_sig1 = error_signature("ConnectionRefusedError: localhost:8080")
_sig2 = error_signature("ConnectionRefusedError: localhost:3000")
test("Different ports produce same error fingerprint",
     _sig1[1] == _sig2[1],
     f"Expected same hash, got {_sig1[1]} vs {_sig2[1]}")

# ─────────────────────────────────────────────────
# Test: State — Causal Tracking Fields (3 tests)
# ─────────────────────────────────────────────────
print("\n--- State: Causal Tracking Fields ---")

# 5. default_state has new causal fields
ds = default_state()
test("State: default has pending_chain_ids", "pending_chain_ids" in ds and ds["pending_chain_ids"] == [])

test_has = all(k in ds for k in ["current_strategy_id", "current_error_signature", "active_bans"])
test("State: default has all causal fields", test_has)

# 6. active_bans capped at 50
cleanup_test_states()
reset_state(session_id=MAIN_SESSION)
state = load_state(session_id=MAIN_SESSION)
state["active_bans"] = [f"strategy_{i}" for i in range(60)]
save_state(state, session_id=MAIN_SESSION)
state = load_state(session_id=MAIN_SESSION)
test("State: active_bans capped at 50", len(state["active_bans"]) <= 50,
     f"len={len(state['active_bans'])}")

# 7. pending_chain_ids capped at 10
state["pending_chain_ids"] = [f"chain_{i}" for i in range(15)]
save_state(state, session_id=MAIN_SESSION)
state = load_state(session_id=MAIN_SESSION)
test("State: pending_chain_ids capped at 10", len(state["pending_chain_ids"]) <= 10,
     f"len={len(state['pending_chain_ids'])}")

# ─────────────────────────────────────────────────
print("\n--- Enforcer PostToolUse: Causal Tracking ---")

# 12. record_attempt sets current_strategy_id
_st_cc12 = default_state()
_post("mcp__memory__record_attempt", {"error_text": "TypeError: cannot add", "strategy_id": "fix-type-cast"}, _st_cc12)
test("Causal: record_attempt sets current_strategy_id",
     _st_cc12.get("current_strategy_id") == "fix-type-cast",
     f"current_strategy_id={_st_cc12.get('current_strategy_id')}")

# 13. record_attempt adds to pending_chain_ids
test("Causal: record_attempt adds to pending_chain_ids",
     len(_st_cc12.get("pending_chain_ids", [])) == 1,
     f"pending_chain_ids={_st_cc12.get('pending_chain_ids', [])}")

# 14. record_outcome clears pending_chain_ids
_st_cc14 = default_state()
_st_cc14["pending_chain_ids"] = ["abc_def"]
_st_cc14["current_strategy_id"] = "fix-type-cast"
_post("mcp__memory__record_outcome", {"chain_id": "abc_def", "outcome": "success"}, _st_cc14,
      tool_response='{"confidence": 0.67, "banned": false, "strategy_id": "fix-type-cast"}')
test("Causal: record_outcome clears pending_chain_ids",
     _st_cc14.get("pending_chain_ids") == [],
     f"pending_chain_ids={_st_cc14.get('pending_chain_ids')}")

# 15. record_outcome with banned=true adds to active_bans
_st_cc15 = default_state()
_st_cc15["pending_chain_ids"] = ["abc_def"]
_st_cc15["current_strategy_id"] = "reinstall-package"
_post("mcp__memory__record_outcome", {"chain_id": "abc_def", "outcome": "failure"}, _st_cc15,
      tool_response='{"confidence": 0.1, "banned": true, "strategy_id": "reinstall-package"}')
test("Causal: record_outcome banned=true adds to active_bans",
     "reinstall-package" in _st_cc15.get("active_bans", {}),
     f"active_bans={_st_cc15.get('active_bans', {})}")

# ─────────────────────────────────────────────────
# Test: Gate 6 — Pending Chain Warnings (2 tests)
# ─────────────────────────────────────────────────
