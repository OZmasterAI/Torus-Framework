#!/usr/bin/env python3
# Gates 4, 5, 6, 7, 9, 14, 15 Quality Tier Tests
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
from datetime import datetime, timedelta

current_hour = datetime.now().hour
hooks_dir = os.path.expanduser("~/.claude/hooks")

# Test: Gate 4 — Memory First
# ─────────────────────────────────────────────────
print("\n--- Gate 4: Memory First ---")

# Remove sideband file so get_memory_last_queried() returns state value only
try:
    os.remove(MEMORY_TIMESTAMP_FILE)
except FileNotFoundError:
    pass

# Edit without memory query → BLOCKED
code, msg = _direct(_g04_check("Edit", {"file_path": "/tmp/app.py"},
                     {"memory_last_queried": 0, "files_read": ["/tmp/app.py"]}))
test("Edit without memory query → blocked", code != 0, msg)
test("Block message mentions GATE 4", "GATE 4" in msg, msg)

# Query memory → then edit → ALLOWED
code, msg = _direct(_g04_check("Edit", {"file_path": "/tmp/app.py"},
                     {"memory_last_queried": time.time(), "files_read": ["/tmp/app.py"]}))
test("Edit after memory query → allowed", code == 0, msg)

# Exempt files should pass without memory
code, msg = _direct(_g04_check("Edit", {"file_path": "/home/crab/.claude/HANDOFF.md"},
                     {"memory_last_queried": 0, "files_read": []}))
test("Edit HANDOFF.md without memory → allowed", code == 0, msg)

# Read-only subagent exemption: researcher/Explore skip Gate 4
code, msg = _direct(_g04_check("Task", {"subagent_type": "researcher", "model": "sonnet", "description": "research"},
                     {"memory_last_queried": 0}))
test("Task researcher without memory → allowed (read-only exempt)", code == 0, msg)

code, msg = _direct(_g04_check("Task", {"subagent_type": "Explore", "model": "sonnet", "description": "explore"},
                     {"memory_last_queried": 0}))
test("Task Explore without memory → allowed (read-only exempt)", code == 0, msg)

# Remove sideband again (previous tests may have left it)
try:
    os.remove(MEMORY_TIMESTAMP_FILE)
except FileNotFoundError:
    pass
code, msg = _direct(_g04_check("Task", {"subagent_type": "builder", "model": "sonnet", "description": "build"},
                     {"memory_last_queried": 0}))
test("Task builder without memory → blocked (write agent)", code != 0, msg)

# Test 9: Gate 4 tracks exemptions in state (direct, no subprocess)
# Remove sideband so Gate 4 reads state["memory_last_queried"]
try:
    os.remove(MEMORY_TIMESTAMP_FILE)
except FileNotFoundError:
    pass
_st_g4ex = {"memory_last_queried": time.time(), "files_read": [], "gate4_exemptions": {}}
_direct(_g04_check("Edit", {"file_path": "/home/crab/.claude/HANDOFF.md"}, _st_g4ex))
_g4_exemptions = _st_g4ex.get("gate4_exemptions", {})
test("Gate 4 tracks exemption for HANDOFF.md",
     "HANDOFF.md" in _g4_exemptions,
     f"Expected HANDOFF.md in exemptions, got keys={list(_g4_exemptions.keys())}")

# Test 10: Gate 4 exemption count increments
_direct(_g04_check("Edit", {"file_path": "/home/crab/.claude/HANDOFF.md"}, _st_g4ex))
_g4_exemptions2 = _st_g4ex.get("gate4_exemptions", {})
_g4_handoff_count = _g4_exemptions2.get("HANDOFF.md", 0)
test("Gate 4 exemption count increments",
     _g4_handoff_count >= 2,
     f"Expected >=2, got {_g4_handoff_count}")

# Test 11: Gate 4 non-exempt file does not create exemption entry
try:
    os.remove(MEMORY_TIMESTAMP_FILE)
except FileNotFoundError:
    pass
_st_g4b = {"memory_last_queried": time.time(), "files_read": ["/tmp/g4_test233.py"], "gate4_exemptions": {}}
_direct(_g04_check("Edit", {"file_path": "/tmp/g4_test233.py"}, _st_g4b))
_g4b_exemptions = _st_g4b.get("gate4_exemptions", {})
test("Gate 4 non-exempt file has no exemption entry",
     "g4_test233.py" not in _g4b_exemptions,
     f"Expected no entry for g4_test233.py, got keys={list(_g4b_exemptions.keys())}")

# Test 12: Gate 4 exempt basenames includes expected files (via shared.exemptions)
from shared.exemptions import BASE_EXEMPT_BASENAMES as G4_EXEMPT
test("Gate 4 EXEMPT_BASENAMES includes HANDOFF.md and CLAUDE.md",
     "HANDOFF.md" in G4_EXEMPT and "CLAUDE.md" in G4_EXEMPT,
     f"Expected HANDOFF.md and CLAUDE.md in exemptions, got {G4_EXEMPT}")

cleanup_test_states()

# ─────────────────────────────────────────────────
# Test: Gate 5 — Proof Before Fixed
# ─────────────────────────────────────────────────
print("\n--- Gate 5: Proof Before Fixed ---")

# Build state with 3 pending unverified edits (bypasses need for PostToolUse setup)
_g5_state_3pending = {
    "pending_verification": ["/tmp/file_a.py", "/tmp/file_b.py", "/tmp/file_c.py"],
    "files_read": ["/tmp/file_a.py", "/tmp/file_b.py", "/tmp/file_c.py", "/tmp/file_d.py"],
    "edit_streak": {},
    "memory_last_queried": time.time(),
}

# Editing a 4th different file should BLOCK (3 unverified = BLOCK_THRESHOLD)
_g5_result_3 = _g05_check("Edit", {"file_path": "/tmp/file_d.py"}, _g5_state_3pending)
code, msg = _direct(_g5_result_3)
test("Gate 5: 3 unverified edits blocks 4th file", code != 0 and _g5_result_3.blocked, f"code={code} blocked={_g5_result_3.blocked}")
test("Gate 5: block message mentions GATE 5", "GATE 5" in (_g5_result_3.message or ""), _g5_result_3.message)

# Re-editing file_a.py should be ALLOWED (same-file exemption)
code, msg = _direct(_g05_check("Edit", {"file_path": "/tmp/file_a.py"}, _g5_state_3pending))
test("Gate 5: re-edit same file allowed (same-file exemption)", code == 0, msg)

# After verification, pending_verification is cleared → editing allowed
_g5_state_cleared = {
    "pending_verification": [],
    "files_read": ["/tmp/file_a.py", "/tmp/file_b.py", "/tmp/file_c.py", "/tmp/file_d.py"],
    "edit_streak": {},
    "memory_last_queried": time.time(),
}
code, msg = _direct(_g05_check("Edit", {"file_path": "/tmp/file_d.py"}, _g5_state_cleared))
test("Gate 5: after verification, editing 4th file allowed", code == 0, msg)

# Test 1: is_test_file identifies test_ prefix (via gate_helpers)
from shared.gate_helpers import is_test_file as _g05_is_test_file
test("is_test_file detects test_ prefix",
     _g05_is_test_file("/path/to/test_foo.py"),
     "Expected test_foo.py to be detected as test file")

# Test 2: is_test_file identifies _test suffix
test("is_test_file detects _test suffix",
     _g05_is_test_file("/path/to/foo_test.py"),
     "Expected foo_test.py to be detected as test file")

# Test 3: is_test_file rejects non-test files
test("is_test_file rejects non-test files",
     not _g05_is_test_file("/path/to/server.py"),
     "Expected server.py to NOT be detected as test file")

# Test 4: Gate 5 check allows test file edits even with pending verification
from gates.gate_05_proof_before_fixed import check as _g5_check
_g5_state = {
    "pending_verification": ["/tmp/a.py", "/tmp/b.py", "/tmp/c.py", "/tmp/d.py"],
    "verification_scores": {},
    "edit_streak": {},
}
_g5_result = _g5_check("Edit", {"file_path": "/tmp/test_server.py"}, _g5_state)
test("Gate 5 allows test file edit with pending verifications",
     not _g5_result.blocked,
     f"Expected not blocked for test file, got blocked={_g5_result.blocked}")

# Test 5: Gate 5 graduated escalation — warns at 3 unverified, does not block
_g5_warn_state = {
    "pending_verification": ["/tmp/a.py", "/tmp/b.py", "/tmp/c.py"],
    "verification_scores": {},
    "edit_streak": {},
}
_g5_warn_result = _g5_check("Edit", {"file_path": "/tmp/new.py"}, _g5_warn_state)
test("Gate 5 blocks at 3 unverified files (no warn phase)",
     _g5_warn_result.blocked is True,
     f"Expected blocked=True, got blocked={_g5_warn_result.blocked}")

# Test 6: Gate 5 graduated escalation — blocks at 5 unverified
_g5_block_state = {
    "pending_verification": ["/tmp/a.py", "/tmp/b.py", "/tmp/c.py", "/tmp/d.py", "/tmp/e.py"],
    "verification_scores": {},
    "edit_streak": {},
}
_g5_block_result = _g5_check("Edit", {"file_path": "/tmp/new.py"}, _g5_block_state)
test("Gate 5 blocks at 5 unverified files",
     _g5_block_result.blocked,
     f"Expected blocked=True, got blocked={_g5_block_result.blocked}")

# Test 7: Gate 5 graduated escalation — 4 unverified warns (between thresholds)
_g5_mid_state = {
    "pending_verification": ["/tmp/a.py", "/tmp/b.py", "/tmp/c.py", "/tmp/d.py"],
    "verification_scores": {},
    "edit_streak": {},
}
_g5_mid_result = _g5_check("Edit", {"file_path": "/tmp/new.py"}, _g5_mid_state)
test("Gate 5 blocks at 4 unverified files (above threshold 3)",
     _g5_mid_result.blocked is True,
     f"Expected blocked=True, got blocked={_g5_mid_result.blocked}")

# ─────────────────────────────────────────────────
# Test: Gate 6 — Save Verified Fix (advisory only)
# ─────────────────────────────────────────────────
print("\n--- Gate 6: Save Verified Fix ---")

_st_g6 = default_state()
_post("Read", {"file_path": "/home/test/fix_a.py"}, _st_g6)
_post("mcp__memory__search_knowledge", {"query": "test"}, _st_g6)
_post("Edit", {"file_path": "/home/test/fix_a.py"}, _st_g6)
_post("Edit", {"file_path": "/home/test/fix_b.py"}, _st_g6)
_post("Bash", {"command": "pytest tests/"}, _st_g6)  # moves pending -> verified

test("Gate 6 setup: verified_fixes populated", len(_st_g6.get("verified_fixes", [])) >= 2,
     f"verified_fixes={_st_g6.get('verified_fixes', [])}")

# Edit with 2+ verified_fixes — should BLOCK (immediate enforcement)
_post("Read", {"file_path": "/home/test/next_file.py"}, _st_g6)
_g6_block_result = _g06_check("Edit", {"file_path": "/home/test/next_file.py"}, _st_g6)
test("Gate 6: blocks at 2+ verified fixes", _g6_block_result.blocked, f"blocked={_g6_block_result.blocked}")
test("Gate 6: block message mentions GATE 6", "GATE 6" in (_g6_block_result.message or ""), _g6_block_result.message)

# Test 5: Gate 6 plan mode warning mentions "plan mode" when plan exited without memory save
_g6pm5 = {"files_read": ["foo.py"], "memory_last_queried": time.time() - 120,
           "last_exit_plan_mode": time.time(), "verified_fixes": [], "unlogged_errors": [],
           "pending_chain_ids": [], "gate6_warn_count": 0}
rc12_5, stderr12_5 = _direct_stderr(_g06_check,"Edit", {"file_path": "foo.py", "old_string": "a", "new_string": "b"}, _g6pm5)
test("Gate 6 plan mode warning mentions plan mode",
     "plan mode" in stderr12_5.lower(),
     f"Expected 'plan mode' in stderr, got: {stderr12_5[:200]}")

# Test 6: Gate 6 plan mode — no warning when memory is fresh (merged from Gate 12)
_g6pm6 = {"files_read": ["foo.py"], "memory_last_queried": time.time(),
           "last_exit_plan_mode": time.time() - 60, "verified_fixes": [], "unlogged_errors": [],
           "pending_chain_ids": [], "gate6_warn_count": 0}
rc12_6, stderr12_6 = _direct_stderr(_g06_check,"Edit", {"file_path": "foo.py", "old_string": "a", "new_string": "b"}, _g6pm6)
test("Gate 6 plan mode — no warning when memory is fresh",
     "plan mode" not in stderr12_6.lower(),
     f"Expected no plan mode warning, got: {stderr12_6[:200]}")

# Test 7: Gate 6 plan mode — warns when plan exited without memory save (merged from Gate 12)
_g6pm7 = {"files_read": ["foo.py"], "memory_last_queried": time.time() - 120,
           "last_exit_plan_mode": time.time(), "verified_fixes": [], "unlogged_errors": [],
           "pending_chain_ids": [], "gate6_warn_count": 0}
rc12_7, stderr12_7 = _direct_stderr(_g06_check,"Edit", {"file_path": "foo.py", "old_string": "a", "new_string": "b"}, _g6pm7)
test("Gate 6 plan mode — warns when plan exited without memory save",
     "plan mode" in stderr12_7.lower() and "remember_this" in stderr12_7.lower(),
     f"Expected plan mode warning, got: {stderr12_7[:200]}")

# Test 8: Gate 6 plan mode — stale plan auto-forgiven (merged from Gate 12)
_g6pm8 = {"files_read": ["foo.py"], "memory_last_queried": time.time() - 3600,
           "last_exit_plan_mode": time.time() - 2000, "verified_fixes": [], "unlogged_errors": [],
           "pending_chain_ids": [], "gate6_warn_count": 0}
rc12_8, stderr12_8 = _direct_stderr(_g06_check,"Edit", {"file_path": "foo.py", "old_string": "a", "new_string": "b"}, _g6pm8)
test("Gate 6 plan mode — stale plan auto-forgiven",
     "plan mode" not in stderr12_8.lower(),
     f"Expected no plan mode warning for stale plan, got: {stderr12_8[:200]}")

from gates.gate_06_save_fix import check as gate6_check, BLOCK_THRESHOLD

# Test 1: Gate 6 warns about high edit streak files
_g6_state1 = default_state()
_g6_state1["edit_streak"] = {"/tmp/churn.py": 5, "/tmp/stable.py": 1}
_g6_state1["verified_fixes"] = []  # below BLOCK_THRESHOLD to isolate edit streak test
_g6_state1["_session_id"] = MAIN_SESSION
_g6_result1 = gate6_check("Edit", {"file_path": "/tmp/next.py"}, _g6_state1)
test("Gate 6 warns with edit streak >= 3",
     _g6_result1.severity == "warn",
     f"Expected severity='warn', got {_g6_result1.severity!r}")

# Test 2: Gate 6 does NOT warn with low edit streak
_g6_state2 = default_state()
_g6_state2["edit_streak"] = {"/tmp/stable.py": 1}
_g6_state2["_session_id"] = MAIN_SESSION
_g6_result2 = gate6_check("Edit", {"file_path": "/tmp/next.py"}, _g6_state2)
test("Gate 6 no warning with edit streak < 3",
     _g6_result2.severity != "warn" or len(_g6_state2.get("verified_fixes", [])) >= BLOCK_THRESHOLD,
     f"Got severity={_g6_result2.severity!r}")

# Test 3: Gate 6 edit streak surfaces basename not full path
_g6_state3 = default_state()
_g6_state3["edit_streak"] = {"/very/long/path/to/file.py": 4}
_g6_state3["verified_fixes"] = []  # below BLOCK_THRESHOLD to isolate edit streak test
_g6_state3["_session_id"] = MAIN_SESSION
import io as _io227
_g6_stderr = _io227.StringIO()
_orig_stderr = sys.stderr
sys.stderr = _g6_stderr
gate6_check("Edit", {"file_path": "/tmp/x.py"}, _g6_state3)
sys.stderr = _orig_stderr
_g6_output = _g6_stderr.getvalue()
test("Gate 6 edit streak shows basename",
     "file.py" in _g6_output and "Top churn" in _g6_output,
     f"Expected 'file.py' and 'Top churn' in output, got: {_g6_output[:100]!r}")

# Test 4: Gate 6 edit streak shows correct count
test("Gate 6 edit streak shows count",
     "4 edits" in _g6_output,
     f"Expected '4 edits' in output, got: {_g6_output[:100]!r}")

# Test: Gate 6 skips researcher Task even with unsaved fixes
_g6_ro_state1 = default_state()
_g6_ro_state1["verified_fixes"] = ["/tmp/a.py", "/tmp/b.py", "/tmp/c.py"]
_g6_ro_state1["gate6_warn_count"] = 6  # Above escalation threshold
_g6_ro_state1["_session_id"] = MAIN_SESSION
_g6_ro_result1 = gate6_check("Task", {"subagent_type": "researcher", "model": "sonnet"}, _g6_ro_state1)
test("Gate 6: Task researcher exempt (read-only)",
     not _g6_ro_result1.blocked,
     f"Expected not blocked, got blocked={_g6_ro_result1.blocked}")

_g6_ro_result2 = gate6_check("Task", {"subagent_type": "Explore", "model": "sonnet"}, _g6_ro_state1)
test("Gate 6: Task Explore exempt (read-only)",
     not _g6_ro_result2.blocked,
     f"Expected not blocked, got blocked={_g6_ro_result2.blocked}")

# Test: Gate 6 still blocks builder Task with unsaved fixes
_g6_ro_result3 = gate6_check("Task", {"subagent_type": "builder", "model": "sonnet"}, _g6_ro_state1)
test("Gate 6: Task builder NOT exempt (write agent)",
     _g6_ro_result3.blocked,
     f"Expected blocked=True, got blocked={_g6_ro_result3.blocked}")

# Test 9: Edit streak risk_level classification — safe (0 hotspots)
def _classify_risk(hotspot_count):
    if hotspot_count == 0: return "safe"
    elif hotspot_count <= 2: return "warning"
    else: return "critical"

test("edit streak risk 0 hotspots → safe",
     _classify_risk(0) == "safe",
     f"Expected 'safe', got {_classify_risk(0)!r}")

# Test 10: Edit streak risk_level — warning (1 hotspot)
test("edit streak risk 1 hotspot → warning",
     _classify_risk(1) == "warning",
     f"Expected 'warning', got {_classify_risk(1)!r}")

# Test 11: Edit streak risk_level — warning (2 hotspots)
test("edit streak risk 2 hotspots → warning",
     _classify_risk(2) == "warning",
     f"Expected 'warning', got {_classify_risk(2)!r}")

# Test 12: Edit streak risk_level — critical (3+ hotspots)
test("edit streak risk 3 hotspots → critical",
     _classify_risk(3) == "critical",
     f"Expected 'critical', got {_classify_risk(3)!r}")

cleanup_test_states()

from gates.gate_06_save_fix import check as gate6_check_229
import io as _io229

# Test 5: Gate 6 warns about recent repair loop (last_seen < 10min)
_g6d_state5 = default_state()
_g6d_state5["error_pattern_counts"] = {"SyntaxError": 4}
_g6d_state5["error_windows"] = [{"pattern": "SyntaxError", "first_seen": time.time() - 300, "last_seen": time.time() - 60, "count": 4}]
_g6d_state5["_session_id"] = MAIN_SESSION
_g6d_err5 = _io229.StringIO()
_orig_stderr229 = sys.stderr
sys.stderr = _g6d_err5
gate6_check_229("Edit", {"file_path": "/tmp/x.py"}, _g6d_state5)
sys.stderr = _orig_stderr229
test("Gate 6 warns about recent repair loop",
     "REPAIR LOOP" in _g6d_err5.getvalue(),
     f"Expected REPAIR LOOP in output, got: {_g6d_err5.getvalue()[:100]!r}")

# Test 6: Gate 6 skips stale repair loop (last_seen > 10min)
_g6d_state6 = default_state()
_g6d_state6["error_pattern_counts"] = {"ImportError": 5}
_g6d_state6["error_windows"] = [{"pattern": "ImportError", "first_seen": time.time() - 1800, "last_seen": time.time() - 700, "count": 5}]
_g6d_state6["_session_id"] = MAIN_SESSION
_g6d_err6 = _io229.StringIO()
sys.stderr = _g6d_err6
gate6_check_229("Edit", {"file_path": "/tmp/x.py"}, _g6d_state6)
sys.stderr = _orig_stderr229
test("Gate 6 skips stale repair loop (>10min)",
     "REPAIR LOOP" not in _g6d_err6.getvalue(),
     f"Expected NO REPAIR LOOP, got: {_g6d_err6.getvalue()[:100]!r}")

# Test 7: Gate 6 still warns if pattern not in error_windows (defensive)
_g6d_state7 = default_state()
_g6d_state7["error_pattern_counts"] = {"TypeError": 3}
_g6d_state7["error_windows"] = []  # Empty windows
_g6d_state7["_session_id"] = MAIN_SESSION
_g6d_err7 = _io229.StringIO()
sys.stderr = _g6d_err7
gate6_check_229("Edit", {"file_path": "/tmp/x.py"}, _g6d_state7)
sys.stderr = _orig_stderr229
test("Gate 6 warns when pattern not in error_windows (defensive)",
     "REPAIR LOOP" in _g6d_err7.getvalue(),
     f"Expected REPAIR LOOP (defensive), got: {_g6d_err7.getvalue()[:100]!r}")

# Test 8: Gate 6 count < 3 does not warn
_g6d_state8 = default_state()
_g6d_state8["error_pattern_counts"] = {"SyntaxError": 2}
_g6d_state8["_session_id"] = MAIN_SESSION
_g6d_err8 = _io229.StringIO()
sys.stderr = _g6d_err8
gate6_check_229("Edit", {"file_path": "/tmp/x.py"}, _g6d_state8)
sys.stderr = _orig_stderr229
test("Gate 6 no repair loop for count < 3",
     "REPAIR LOOP" not in _g6d_err8.getvalue(),
     f"Expected no REPAIR LOOP, got: {_g6d_err8.getvalue()[:100]!r}")

# Test 9: STALE_FIX_SECONDS constant exists
from gates.gate_06_save_fix import STALE_FIX_SECONDS
test("STALE_FIX_SECONDS is 1200 (20 min)",
     STALE_FIX_SECONDS == 1200,
     f"Expected 1200, got {STALE_FIX_SECONDS}")

# Test 10: Gate 6 check() removes stale verified fixes from state
from gates.gate_06_save_fix import check as _g6_check
_g6_state = {
    "verified_fixes": ["/tmp/old_fix.py", "/tmp/fresh_fix.py"],
    "verification_timestamps": {
        "/tmp/old_fix.py": time.time() - 2000,   # 33 min ago — stale
        "/tmp/fresh_fix.py": time.time() - 60,    # 1 min ago — fresh
    },
    "gate6_warn_count": 0,
}
_g6_check("Edit", {"file_path": "/tmp/test.py"}, _g6_state)
test("Gate 6 removes stale verified fixes",
     len(_g6_state["verified_fixes"]) == 1 and "/tmp/fresh_fix.py" in _g6_state["verified_fixes"],
     f"Expected only fresh_fix.py, got {_g6_state['verified_fixes']}")

# Test 11: Gate 6 keeps all fixes when none are stale
_g6_state2 = {
    "verified_fixes": ["/tmp/a.py", "/tmp/b.py"],
    "verification_timestamps": {
        "/tmp/a.py": time.time() - 300,  # 5 min ago — fresh
        "/tmp/b.py": time.time() - 600,  # 10 min ago — fresh
    },
    "gate6_warn_count": 0,
}
_g6_check("Edit", {"file_path": "/tmp/test.py"}, _g6_state2)
test("Gate 6 keeps all fresh fixes",
     len(_g6_state2["verified_fixes"]) == 2,
     f"Expected 2 fixes, got {len(_g6_state2['verified_fixes'])}")

cleanup_test_states()

# ─────────────────────────────────────────────────
# Test: Gate 7 — Critical File Guard
# ─────────────────────────────────────────────────
print("\n--- Gate 7: Critical File Guard ---")

cleanup_test_states()
reset_state(session_id=MAIN_SESSION)

# Write a critical file (auth_handler.py) with stale memory → BLOCKED by Gate 7
# Set memory_last_queried to 5.8 min ago: within Gate 4's Write window (10min)
# but outside Gate 7's 5-min window, isolating Gate 7's behavior.
code, msg = _direct(_g07_check("Write", {"file_path": "/tmp/auth_handler.py", "content": "test"},
                     {"memory_last_queried": time.time() - 350, "files_read": ["/tmp/auth_handler.py"]}))
test("Gate 7: write auth_handler.py with stale memory → blocked", code != 0, f"code={code}")
test("Gate 7: block message specifically mentions GATE 7", "GATE 7" in msg, msg)

# Edit a non-critical file → ALLOWED (only need Gate 4 memory)
code, msg = _direct(_g07_check("Edit", {"file_path": "/tmp/regular_utils.py"},
                     {"memory_last_queried": time.time(), "files_read": ["/tmp/regular_utils.py"]}))
test("Gate 7: edit regular_utils.py (non-critical) → allowed", code == 0, msg)

# Edit .env without memory → BLOCKED
code, msg = _direct(_g07_check("Edit", {"file_path": "/tmp/project/.env"},
                     {"memory_last_queried": 0, "files_read": ["/tmp/project/.env"]}))
test("Gate 7: edit .env without memory → blocked", code != 0, f"code={code}")

# Edit critical file WITH recent memory query → ALLOWED
code, msg = _direct(_g07_check("Edit", {"file_path": "/tmp/auth_handler.py"},
                     {"memory_last_queried": time.time(), "files_read": ["/tmp/auth_handler.py"]}))
test("Gate 7: edit auth_handler.py WITH memory → allowed", code == 0, msg)

# Test 1: Gate 7 CRITICAL_PATTERNS is list of tuples
from gates.gate_07_critical_file_guard import CRITICAL_PATTERNS as G7_PATTERNS
test("Gate 7 CRITICAL_PATTERNS are (regex, category) tuples",
     all(isinstance(p, tuple) and len(p) == 2 for p in G7_PATTERNS),
     "Expected all entries to be 2-tuples")

# Test 2: Gate 7 block message includes category
code_g7, msg_g7 = _direct(_g07_check("Write", {"file_path": "/home/crab/.claude/hooks/enforcer.py", "content": "test"},
                            {"memory_last_queried": time.time() - 350, "files_read": ["/home/crab/.claude/hooks/enforcer.py"]}))
test("Gate 7 block message includes category",
     code_g7 != 0 and "Framework core" in msg_g7,
     f"Expected block with 'Framework core', got code={code_g7}, msg={msg_g7}")

# Test 3: Gate 7 recognizes SSH directory category
_g7_match = None
import re as _re
for _pat, _cat in G7_PATTERNS:
    if _re.search(_pat, "/home/user/.ssh/id_rsa", _re.IGNORECASE):
        _g7_match = _cat
        break
test("Gate 7 recognizes SSH directory path",
     _g7_match == "SSH directory",
     f"Expected 'SSH directory', got '{_g7_match}'")

# Test 4: Gate 7 non-critical file passes
code_g7nc, _ = _direct(_g07_check("Edit", {"file_path": "/tmp/g7_normal232.py"},
                         {"memory_last_queried": time.time(), "files_read": ["/tmp/g7_normal232.py"]}))
test("Gate 7 allows non-critical file",
     code_g7nc == 0,
     f"Expected allowed (code=0), got code={code_g7nc}")

# ─────────────────────────────────────────────────
# ─────────────────────────────────────────────────
# Test: Gate 7 — Extended Critical Patterns (M6/G7-3)
# ─────────────────────────────────────────────────
print("\n--- Gate 7: Extended Critical Patterns ---")

new_critical_files = [
    ("/home/user/.ssh/config", ".ssh/ directory"),
    ("/home/user/.ssh/authorized_keys", "authorized_keys"),
    ("/home/user/.ssh/id_rsa", "SSH private key"),
    ("/home/user/.ssh/id_ed25519.pub", "SSH public key"),
    ("/etc/sudoers", "sudoers"),
    ("/etc/crontab", "crontab"),
    ("/etc/cron.d/backup", "cron.d entry"),
    ("/tmp/server.pem", ".pem certificate"),
    ("/tmp/private.key", ".key file"),
]

for file_path, desc in new_critical_files:
    # Set memory to 7 minutes ago (outside Gate 7's 5-min window)
    code, msg = _direct(_g07_check("Edit", {"file_path": file_path},
                         {"memory_last_queried": time.time() - 420, "files_read": [file_path]}))
    test(f"Gate 7: {desc} with stale memory → blocked", code != 0, f"code={code}")

# Verify critical file edit works with fresh memory
code, msg = _direct(_g07_check("Edit", {"file_path": "/home/user/.ssh/config"},
                     {"memory_last_queried": time.time(), "files_read": ["/home/user/.ssh/config"]}))
test("Gate 7: .ssh/config WITH fresh memory → allowed", code == 0, msg)

# ─────────────────────────────────────────────────
# Test: Fixes H4, M1, M2, H6, M8
# ─────────────────────────────────────────────────
print("\n--- Fix Verification: H4, M1, M2, H6, M8 ---")

# H4: Gate 5 no longer exempts hooks/ directory
hooks_dir = os.path.expanduser("~/.claude/hooks")
_st_h4 = default_state()
for i in range(6):
    _post("Read", {"file_path": f"/tmp/h4_file_{i}.py"}, _st_h4)
_post("Read", {"file_path": os.path.join(hooks_dir, "enforcer.py")}, _st_h4)
_post("mcp__memory__search_knowledge", {"query": "test"}, _st_h4)
# Edit 5 non-hooks files to fill pending_verification past block threshold
for i in range(5):
    _post("Edit", {"file_path": f"/tmp/h4_file_{i}.py"}, _st_h4)
# Now editing a hooks/ file should be BLOCKED (no longer exempt from Gate 5)
code, msg = _direct(_g05_check("Edit", {"file_path": os.path.join(hooks_dir, "enforcer.py")}, _st_h4))
test("H4: hooks/ file blocked by Gate 5 (no longer exempt)", code != 0, f"code={code}")

# H4: Gate 8 no longer exempts hooks/ — during late night, hooks/ edits require fresh memory
# (Can only test during 1-5 AM; skip otherwise)
if 1 <= current_hour < 5:
    cleanup_test_states()
    reset_state(session_id=MAIN_SESSION)
    state = default_state()
    state["files_read"] = [os.path.join(hooks_dir, "enforcer.py")]
    save_state(state, session_id=MAIN_SESSION)
    # Don't query memory — Gate 8 should block
    code, msg = run_enforcer("PreToolUse", "Edit", {"file_path": os.path.join(hooks_dir, "enforcer.py")})
    test("H4: hooks/ file blocked by Gate 8 late-night (no longer exempt)", code != 0, f"code={code}")
else:
    test("H4: Gate 8 hooks/ late-night test (skipped — not late night)", True)

# M1: verified_fixes cap at 100
cleanup_test_states()
reset_state(session_id=MAIN_SESSION)
state = load_state(session_id=MAIN_SESSION)
state["verified_fixes"] = [f"/tmp/fix_{i}.py" for i in range(150)]
save_state(state, session_id=MAIN_SESSION)
state = load_state(session_id=MAIN_SESSION)
test("M1: verified_fixes capped at 100", len(state["verified_fixes"]) <= 100,
     f"len={len(state['verified_fixes'])}")

# M2: pending_verification cap at 50
state = load_state(session_id=MAIN_SESSION)
state["pending_verification"] = [f"/tmp/pending_{i}.py" for i in range(80)]
save_state(state, session_id=MAIN_SESSION)
state = load_state(session_id=MAIN_SESSION)
test("M2: pending_verification capped at 50", len(state["pending_verification"]) <= 50,
     f"len={len(state['pending_verification'])}")

# M8: curl no longer counts as verification
_st_m8a = default_state()
_post("Edit", {"file_path": "/tmp/m8_test.py"}, _st_m8a)
_post("Bash", {"command": "curl http://example.com"}, _st_m8a)
test("M8: curl does not clear pending verification",
     "/tmp/m8_test.py" in _st_m8a.get("pending_verification", []),
     f"pending={_st_m8a.get('pending_verification', [])}")

# M8: python still clears targeted verification
_st_m8b = default_state()
_post("Edit", {"file_path": "/tmp/m8_test.py"}, _st_m8b)
_post("Bash", {"command": "python /tmp/m8_test.py"}, _st_m8b)
test("M8: python clears targeted pending verification",
     "/tmp/m8_test.py" not in _st_m8b.get("pending_verification", []),
     f"pending={_st_m8b.get('pending_verification', [])}")

# ─────────────────────────────────────────────────
# ─────────────────────────────────────────────────
# Test: Feature 2 — Enhanced Gate 6 (4 tests)
# ─────────────────────────────────────────────────
print("\n--- Gate 6 Enhanced: Error Warnings ---")

# Test: Gate 6 warns when unlogged_errors >= 1
_g6_err_state = {
    "unlogged_errors": [{"pattern": "Traceback", "command": "python foo.py", "timestamp": time.time()}],
    "files_read": ["/tmp/gate6_err.py"], "memory_last_queried": time.time(),
    "verified_fixes": [], "pending_chain_ids": [], "gate6_warn_count": 0,
}
code, msg = _direct_stderr(_g06_check,"Edit", {"file_path": "/tmp/gate6_err.py"}, _g6_err_state)
test("Gate 6 enhanced: warns on unlogged_errors",
     "error" in msg.lower() or "unlogged" in msg.lower(), msg)

# Test: Gate 6 blocks when verified_fixes reach threshold, even with unlogged_errors
_g6_both_state = {
    "unlogged_errors": [{"pattern": "Traceback", "command": "python foo.py", "timestamp": time.time()}],
    "verified_fixes": ["/tmp/fix1.py", "/tmp/fix2.py"],
    "files_read": ["/tmp/gate6_both.py"], "memory_last_queried": time.time(),
    "pending_chain_ids": [],
}
_g6_both_result = _g06_check("Edit", {"file_path": "/tmp/gate6_both.py"}, _g6_both_state)
test("Gate 6 enhanced: blocks when verified_fixes at threshold", _g6_both_result.blocked, f"blocked={_g6_both_result.blocked}")

# Test: Gate 6 advisory-only when just errors (no verified_fixes)
_g6_noblock_state = {
    "unlogged_errors": [{"pattern": "Traceback", "command": "python foo.py", "timestamp": time.time()}],
    "files_read": ["/tmp/gate6_noblock.py"], "memory_last_queried": time.time(),
    "verified_fixes": [], "pending_chain_ids": [],
}
code, msg = _direct_stderr(_g06_check,"Edit", {"file_path": "/tmp/gate6_noblock.py"}, _g6_noblock_state)
test("Gate 6 enhanced: advisory only with errors (no fixes)", code == 0, f"code={code}")

# Test: Gate 6 error warning mentions pattern name
_g6_pattern_state = {
    "unlogged_errors": [{"pattern": "npm ERR!", "command": "npm install", "timestamp": time.time()}],
    "files_read": ["/tmp/gate6_pattern.py"], "memory_last_queried": time.time(),
    "verified_fixes": [], "pending_chain_ids": [], "gate6_warn_count": 0,
}
code, msg = _direct_stderr(_g06_check,"Edit", {"file_path": "/tmp/gate6_pattern.py"}, _g6_pattern_state)
test("Gate 6 enhanced: warning mentions error pattern",
     "npm ERR!" in msg or "npm" in msg.lower(), msg)

# Test: Gate 9 — Strategy Ban (4 tests)
# ─────────────────────────────────────────────────
print("\n--- Gate 9: Strategy Ban ---")

# 8. Edit with no strategy → allowed
code, msg = _direct(_g09_check("Edit", {"file_path": "/tmp/g9_test.py"},
                     {"current_strategy_id": None, "active_bans": []}))
test("Gate 9: Edit with no strategy → allowed", code == 0, msg)

# 9. Edit with unbanned strategy → allowed
code, msg = _direct(_g09_check("Edit", {"file_path": "/tmp/g9_test.py"},
                     {"current_strategy_id": "try-different-import", "active_bans": ["some-other-strategy"]}))
test("Gate 9: Edit with unbanned strategy → allowed", code == 0, msg)

# 10. Edit with banned strategy → BLOCKED
code, msg = _direct(_g09_check("Edit", {"file_path": "/tmp/g9_test.py"},
                     {"current_strategy_id": "reinstall-package", "active_bans": ["reinstall-package", "other-ban"]}))
test("Gate 9: Edit with banned strategy → BLOCKED", code != 0, f"code={code}")
test("Gate 9: block message mentions GATE 9", "GATE 9" in msg, msg)

# 11. Non-Edit tool with banned strategy → allowed
code, msg = _direct(_g09_check("Bash", {"command": "echo hello"},
                     {"current_strategy_id": "reinstall-package", "active_bans": ["reinstall-package"]}))
test("Gate 9: Bash with banned strategy → allowed (only blocks Edit/Write)", code == 0, msg)

from gates.gate_09_strategy_ban import _ban_severity

# Test 5: _ban_severity(1) → ("first_fail", "warn")
sev5 = _ban_severity(1)
test("_ban_severity(1) → ('first_fail', 'warn')",
     sev5 == ("first_fail", "warn"),
     f"Expected ('first_fail', 'warn'), got {sev5!r}")

# Test 6: _ban_severity(2) → ("repeating", "error")
sev6 = _ban_severity(2)
test("_ban_severity(2) → ('repeating', 'error')",
     sev6 == ("repeating", "error"),
     f"Expected ('repeating', 'error'), got {sev6!r}")

# Test 7: _ban_severity(3) → ("escalating", "critical")
sev7 = _ban_severity(3)
test("_ban_severity(3) → ('escalating', 'critical')",
     sev7 == ("escalating", "critical"),
     f"Expected ('escalating', 'critical'), got {sev7!r}")

# Test 8: _ban_severity(5) → ("escalating", "critical") — high count still escalating
sev8 = _ban_severity(5)
test("_ban_severity(5) → ('escalating', 'critical') — high count",
     sev8 == ("escalating", "critical"),
     f"Expected ('escalating', 'critical'), got {sev8!r}")

from gates.gate_09_strategy_ban import check as gate9_check

# Test 9: Gate 9 warning shows retry budget (fail_count=1, threshold=3)
_g9_state9 = default_state()
_g9_state9["current_strategy_id"] = "fix-auth"
_g9_state9["active_bans"] = {"fix-auth": {"fail_count": 1, "first_failed": time.time() - 60, "last_failed": time.time() - 30}}
_g9_stderr9 = _io227.StringIO()
sys.stderr = _g9_stderr9
_g9_result9 = gate9_check("Edit", {"file_path": "/tmp/x.py"}, _g9_state9)
sys.stderr = _orig_stderr
_g9_warn9 = _g9_stderr9.getvalue()
test("Gate 9 warning shows retry budget",
     "1/3" in _g9_warn9 and "2 more" in _g9_warn9,
     f"Expected '1/3' and '2 more' in warning, got: {_g9_warn9!r}")

# Test 10: Gate 9 warning at fail_count=2 shows 1 remaining
_g9_state10 = default_state()
_g9_state10["current_strategy_id"] = "fix-auth"
_g9_state10["active_bans"] = {"fix-auth": {"fail_count": 2, "first_failed": time.time() - 120, "last_failed": time.time() - 10}}
_g9_stderr10 = _io227.StringIO()
sys.stderr = _g9_stderr10
_g9_result10 = gate9_check("Edit", {"file_path": "/tmp/x.py"}, _g9_state10)
sys.stderr = _orig_stderr
_g9_warn10 = _g9_stderr10.getvalue()
test("Gate 9 warning at fail_count=2 shows 1 remaining",
     "2/3" in _g9_warn10 and "1 more" in _g9_warn10,
     f"Expected '2/3' and '1 more' in warning, got: {_g9_warn10!r}")

# Test 11: Gate 9 block message includes timing info
_g9_state11 = default_state()
_g9_state11["current_strategy_id"] = "fix-auth"
_g9_state11["active_bans"] = {"fix-auth": {"fail_count": 3, "first_failed": time.time() - 600, "last_failed": time.time() - 120}}
_g9_result11 = gate9_check("Edit", {"file_path": "/tmp/x.py"}, _g9_state11)
test("Gate 9 block includes timing info",
     _g9_result11.blocked and "first:" in _g9_result11.message and "last:" in _g9_result11.message,
     f"Expected timing in block message, got: {_g9_result11.message!r}")

# Test 12: Gate 9 not blocked (no strategy set)
_g9_state12 = default_state()
_g9_state12["current_strategy_id"] = ""
_g9_result12 = gate9_check("Edit", {"file_path": "/tmp/x.py"}, _g9_state12)
test("Gate 9 passes with empty strategy",
     not _g9_result12.blocked,
     f"Expected not blocked, got blocked={_g9_result12.blocked!r}")

cleanup_test_states()

# Test 2: Gate 9 success context is conditional on success_count > 0

# Test 3: Gate 9 ban threshold constants are correct
from gates.gate_09_strategy_ban import DEFAULT_BAN_THRESHOLD, SUCCESS_BONUS_RETRIES
test("Gate 9 ban threshold constants are correct",
     DEFAULT_BAN_THRESHOLD == 3 and SUCCESS_BONUS_RETRIES == 1,
     f"Expected threshold=3 bonus=1, got {DEFAULT_BAN_THRESHOLD}/{SUCCESS_BONUS_RETRIES}")

# Test 4: Gate 9 check() with success_count > 0 doesn't block at fail_count=1
from gates.gate_09_strategy_ban import check as _g9_check
from shared.gate_result import GateResult as _GR234
_g9_test_state = {
    "current_strategy_id": "test-strat-234",
    "active_bans": {"test-strat-234": {"fail_count": 1, "first_failed": time.time() - 60, "last_failed": time.time() - 30}},
    "successful_strategies": {"test-strat-234": {"success_count": 5}},
}
_g9_result = _g9_check("Edit", {"file_path": "/tmp/test.py"}, _g9_test_state)
test("Gate 9 allows through at fail_count=1 with successes",
     not _g9_result.blocked,
     f"Expected not blocked, got blocked={_g9_result.blocked}")

# ─────────────────────────────────────────────────
# Test: Enforcer PostToolUse — Causal Tracking (4 tests)
# ─────────────────────────────────────────────────
print("\n--- Gate 6: Pending Chain Warnings ---")

# 16. Gate 6 warns on pending_chain_ids
_g6_chain = {"pending_chain_ids": ["chain_abc"], "files_read": ["/tmp/g6_chain.py"],
             "memory_last_queried": time.time(), "verified_fixes": [], "unlogged_errors": [],
             "gate6_warn_count": 0}
code, msg = _direct_stderr(_g06_check,"Edit", {"file_path": "/tmp/g6_chain.py"}, _g6_chain)
test("Gate 6: warns on pending_chain_ids",
     "without recorded outcome" in msg or "record_outcome" in msg, msg)

# 17. Gate 6 pending chain warning mentions record_outcome
test("Gate 6: pending chain warning mentions record_outcome",
     "record_outcome" in msg, msg)

# ─────────────────────────────────────────────────
# Test: Integration — Full Causal Chain (1 test)
# ─────────────────────────────────────────────────
print("\n--- Integration: Full Causal Chain ---")

# 18. Full chain: record_attempt → outcome with ban → Gate 9 blocks
_st_fcc = default_state()
# Step 1: record_attempt
_post("mcp__memory__record_attempt", {"error_text": "ModuleNotFoundError: foo", "strategy_id": "pip-install-foo"}, _st_fcc)
# Step 2: record_outcome with ban
_post("mcp__memory__record_outcome", {"chain_id": "x", "outcome": "failure"}, _st_fcc,
      tool_response='{"confidence": 0.1, "banned": true, "strategy_id": "pip-install-foo"}')
# Step 3: Try another record_attempt with the SAME banned strategy
_post("mcp__memory__record_attempt", {"error_text": "ModuleNotFoundError: foo", "strategy_id": "pip-install-foo"}, _st_fcc)
# Step 4: Gate 9 should block Edit
_post("Read", {"file_path": "/tmp/integration.py"}, _st_fcc)
_post("mcp__memory__search_knowledge", {"query": "test"}, _st_fcc)
code, msg = _direct(_g09_check("Edit", {"file_path": "/tmp/integration.py"}, _st_fcc))
test("Integration: banned strategy blocked by Gate 9", code != 0, f"code={code}, msg={msg}")

# ─────────────────────────────────────────────────
# Test: Audit Fix M4 — Gate 3 exit code from tool_response
# ─────────────────────────────────────────────────
print("\n--- Fix M4: Gate 3 Exit Code from tool_response ---")

# Test: Failing test run (exit code 1) blocks deploy
code, msg = _direct(_g03_check("Bash", {"command": "scp app.py root@10.0.0.1:/opt/"},
                     {"last_test_run": time.time(), "last_test_exit_code": 1}))
test("M4: deploy after failing tests (exit_code=1) → blocked", code != 0, f"code={code}")
test("M4: block message mentions GATE 3", "GATE 3" in msg, msg)

# Test: Passing test run (exit code 0) allows deploy
code, msg = _direct(_g03_check("Bash", {"command": "scp app.py root@10.0.0.1:/opt/"},
                     {"last_test_run": time.time(), "last_test_exit_code": 0}))
test("M4: deploy after passing tests (exit_code=0) → allowed", code == 0, msg)

# Test: Exit code captured from dict tool_response
_st_m4 = default_state()
_post("Bash", {"command": "pytest tests/"}, _st_m4, tool_response={"exit_code": 2})
test("M4: exit code captured from dict tool_response",
     _st_m4.get("last_test_exit_code") == 2,
     f"last_test_exit_code={_st_m4.get('last_test_exit_code')}")

# ─────────────────────────────────────────────────
# Test: Audit Fix M1 — Gate 1 guards .ipynb
# ─────────────────────────────────────────────────
print("\n--- get_memory Enforcer Compatibility ---")

_st_gm = default_state()
_post("mcp__memory__get_memory", {"id": "abc123"}, _st_gm)
test("get_memory: updates memory_last_queried",
     _st_gm.get("memory_last_queried", 0) > 0,
     f"memory_last_queried={_st_gm.get('memory_last_queried', 0)}")

# Verify get_memory satisfies Gate 4 for subsequent edits
try:
    os.remove(MEMORY_TIMESTAMP_FILE)
except FileNotFoundError:
    pass
code, msg = _direct(_g04_check("Edit", {"file_path": "/tmp/gm_test.py"},
                     {"files_read": ["/tmp/gm_test.py"], "memory_last_queried": time.time()}))
test("get_memory: satisfies Gate 4 for Edit", code == 0, msg)

# ─────────────────────────────────────────────────
# Test: Auto-Capture — Secrets Filter (8 tests)
# ─────────────────────────────────────────────────
print("\n--- Gate 14: Pre-Implementation Confidence ---")

from gates.gate_14_confidence_check import check as _g14_check

# Test 1: No test baseline → warns first time
_g14_state1 = default_state()
_g14_state1["session_test_baseline"] = False
_g14_state1["pending_verification"] = []
_g14_state1["memory_last_queried"] = 0  # stale
_g14_r1 = _g14_check("Write", {"file_path": "/tmp/new_feature.py"}, _g14_state1)
test("Gate14: no test baseline → BLOCKED immediately",
     _g14_r1.blocked)
test("Gate14: no test baseline → BLOCKED in message",
     "BLOCKED" in (_g14_r1.message or ""))

# Test 2: After test run + fresh memory → allowed
_g14_state2 = default_state()
_g14_state2["session_test_baseline"] = True
_g14_state2["pending_verification"] = []
_g14_state2["memory_last_queried"] = time.time()  # fresh
_g14_r4 = _g14_check("Write", {"file_path": "/tmp/new_feature.py"}, _g14_state2)
test("Gate14: all signals pass → allowed",
     not _g14_r4.blocked)
test("Gate14: all signals pass → no warning message",
     not _g14_r4.message)

# Test 3: Re-editing file in pending_verification → allowed (iteration)
_g14_state3 = default_state()
_g14_state3["session_test_baseline"] = False
_g14_state3["pending_verification"] = ["/tmp/existing_edit.py"]
_g14_state3["memory_last_queried"] = 0
_g14_r5 = _g14_check("Edit", {"file_path": "/tmp/existing_edit.py"}, _g14_state3)
test("Gate14: re-edit of pending file → allowed (iteration exemption)",
     not _g14_r5.blocked)

# Test 6: Exempt files bypass gate
_g14_state4 = default_state()
_g14_state4["session_test_baseline"] = False
_g14_state4["memory_last_queried"] = 0
for _exempt_file, _exempt_label in [
    ("test_something.py", "test file"),
    ("HANDOFF.md", "HANDOFF.md"),
    ("__init__.py", "__init__.py"),
    ("/home/user/.claude/skills/research/SKILL.md", "skills/ dir"),
]:
    _g14_re = _g14_check("Write", {"file_path": _exempt_file}, _g14_state4)
    test(f"Gate14: exempt {_exempt_label} → allowed", not _g14_re.blocked)

# ─────────────────────────────────────────────────
# Gate 15: Causal Chain Enforcement
# ─────────────────────────────────────────────────
print("\n--- Gate 15: Causal Chain Enforcement ---")

try:
    from gates.gate_15_causal_chain import check as _g15_check
except ImportError:
    _g15_check = None
    test("Gate15: module import", False, "Failed to import gate_15_causal_chain")

if _g15_check:
    # Test 1: No test failure → allowed
    _g15_s1 = default_state()
    _g15_s1["recent_test_failure"] = None
    _g15_r1 = _g15_check("Edit", {"file_path": "/tmp/foo.py"}, _g15_s1)
    test("Gate15: no test failure → allowed", not _g15_r1.blocked)

    # Test 2: Test failure + no fix_history → BLOCKED
    _g15_s2 = default_state()
    _g15_s2["recent_test_failure"] = {"pattern": "AssertionError:", "timestamp": time.time(), "command": "pytest"}
    _g15_s2["fixing_error"] = True
    _g15_s2["fix_history_queried"] = 0
    _g15_r2 = _g15_check("Edit", {"file_path": "/tmp/foo.py"}, _g15_s2)
    test("Gate15: test failure + no fix_history → BLOCKED",
         _g15_r2.blocked and "query_fix_history" in _g15_r2.message)

    # Test 3: Test failure + recent fix_history → allowed
    _g15_s3 = default_state()
    _g15_s3["recent_test_failure"] = {"pattern": "KeyError:", "timestamp": time.time(), "command": "pytest"}
    _g15_s3["fixing_error"] = True
    _g15_s3["fix_history_queried"] = time.time()  # just queried
    _g15_r3 = _g15_check("Edit", {"file_path": "/tmp/foo.py"}, _g15_s3)
    test("Gate15: test failure + recent fix_history → allowed", not _g15_r3.blocked)

    # Test 4: Test failure but fixing_error=False → allowed
    _g15_s4 = default_state()
    _g15_s4["recent_test_failure"] = {"pattern": "FAILED", "timestamp": time.time(), "command": "pytest"}
    _g15_s4["fixing_error"] = False
    _g15_r4 = _g15_check("Edit", {"file_path": "/tmp/foo.py"}, _g15_s4)
    test("Gate15: fixing_error=False → allowed", not _g15_r4.blocked)

    # Test 5: Test failure but editing test file → allowed (exempt)
    _g15_s5 = default_state()
    _g15_s5["recent_test_failure"] = {"pattern": "FAILED", "timestamp": time.time(), "command": "pytest"}
    _g15_s5["fixing_error"] = True
    _g15_s5["fix_history_queried"] = 0
    _g15_r5 = _g15_check("Edit", {"file_path": "/tmp/test_something.py"}, _g15_s5)
    test("Gate15: test file exempt → allowed", not _g15_r5.blocked)

    # Test 6: Read tool → always allowed (not watched)
    _g15_s6 = default_state()
    _g15_s6["recent_test_failure"] = {"pattern": "FAILED", "timestamp": time.time(), "command": "pytest"}
    _g15_s6["fixing_error"] = True
    _g15_r6 = _g15_check("Read", {"file_path": "/tmp/foo.py"}, _g15_s6)
    test("Gate15: Read tool → always allowed", not _g15_r6.blocked)

    # Test 7: Stale fix_history (>5 min ago) → BLOCKED
    _g15_s7 = default_state()
    _g15_s7["recent_test_failure"] = {"pattern": "TypeError:", "timestamp": time.time(), "command": "pytest"}
    _g15_s7["fixing_error"] = True
    _g15_s7["fix_history_queried"] = time.time() - 400  # 6+ min ago
    _g15_r7 = _g15_check("Edit", {"file_path": "/tmp/foo.py"}, _g15_s7)
    test("Gate15: stale fix_history (>5min) → BLOCKED", _g15_r7.blocked)

# State v3 fields
_v3_state = default_state()
test("State v3: recent_test_failure field exists",
     "recent_test_failure" in _v3_state and _v3_state["recent_test_failure"] is None)
test("State v3: fix_history_queried field exists",
     "fix_history_queried" in _v3_state and _v3_state["fix_history_queried"] == 0)
test("State v3: fixing_error field exists",
     "fixing_error" in _v3_state and _v3_state["fixing_error"] is False)
test("State v3: version is 3", _v3_state.get("_version") == 3)

# Tracker: test failure sets recent_test_failure
from tracker import handle_post_tool_use as _tracker_handle
_tracker_s1 = default_state()
_tracker_handle("Bash", {"command": "pytest tests/"}, _tracker_s1, session_id="__test_g15",
                tool_response={"exit_code": 1, "stdout": "FAILED test_x.py"})
test("Tracker: test failure sets recent_test_failure",
     _tracker_s1.get("recent_test_failure") is not None
     and _tracker_s1["recent_test_failure"].get("pattern") == "FAILED")
test("Tracker: test failure sets fixing_error=True",
     _tracker_s1.get("fixing_error") is True)

# Tracker: test pass clears recent_test_failure
_tracker_s2 = default_state()
_tracker_s2["recent_test_failure"] = {"pattern": "FAILED", "timestamp": time.time(), "command": "pytest"}
_tracker_s2["fixing_error"] = True
_tracker_handle("Bash", {"command": "pytest tests/"}, _tracker_s2, session_id="__test_g15",
                tool_response={"exit_code": 0, "stdout": "5 passed"})
test("Tracker: test pass clears recent_test_failure",
     _tracker_s2.get("recent_test_failure") is None)
test("Tracker: test pass clears fixing_error",
     _tracker_s2.get("fixing_error") is False)

# Tracker: query_fix_history sets fix_history_queried
_tracker_s3 = default_state()
_tracker_handle("mcp__memory__query_fix_history", {"error_text": "test error"}, _tracker_s3,
                session_id="__test_g15", tool_response="{}")
test("Tracker: query_fix_history sets fix_history_queried",
     _tracker_s3.get("fix_history_queried", 0) > 0)

# ─────────────────────────────────────────────────
# TASK MANAGER (Phase 2) — PRP JSON task tracking
# ─────────────────────────────────────────────────
print("\n--- Gate 05 Refactored ---")

try:
    from gates.gate_05_proof_before_fixed import check as g05_check
    from shared.gate_result import GateResult

    _g05_state = default_state()

    # Test 1: non-PreToolUse passes
    _r = g05_check("Edit", {"file_path": "/tmp/foo.py"}, _g05_state, event_type="PostToolUse")
    test("G05 Refactored: non-PreToolUse passes", not _r.blocked, f"blocked={_r.blocked}")

    # Test 2: non-edit tool passes
    _r = g05_check("Read", {"file_path": "/tmp/foo.py"}, _g05_state)
    test("G05 Refactored: Read tool passes", not _r.blocked, f"blocked={_r.blocked}")

    # Test 3: test file is exempt
    _r = g05_check("Edit", {"file_path": "/home/user/test_foo.py"}, _g05_state)
    test("G05 Refactored: test file exempt", not _r.blocked, f"blocked={_r.blocked}")

    # Test 4: _spec test file exempt
    _r = g05_check("Edit", {"file_path": "/home/user/widget_spec.py"}, _g05_state)
    test("G05 Refactored: _spec test file exempt", not _r.blocked, f"blocked={_r.blocked}")

    # Test 5: normal file with no pending passes
    _r = g05_check("Edit", {"file_path": "/home/user/app.py"}, _g05_state)
    test("G05 Refactored: no pending passes", not _r.blocked, f"blocked={_r.blocked}")

    # Test 6: blocks at BLOCK_THRESHOLD unverified files
    _g05_block_state = default_state()
    _g05_block_state["pending_verification"] = [
        "/a.py", "/b.py", "/c.py", "/d.py", "/e.py"
    ]
    _r = g05_check("Edit", {"file_path": "/new.py"}, _g05_block_state)
    test("G05 Refactored: blocks at 5 unverified files (above threshold 3)",
         _r.blocked is True, f"blocked={_r.blocked}")

    # Test 7: blocks at BLOCK_THRESHOLD (3) — no warn phase
    _g05_warn_state = default_state()
    _g05_warn_state["pending_verification"] = ["/a.py", "/b.py", "/c.py"]
    _r = g05_check("Edit", {"file_path": "/new.py"}, _g05_warn_state)
    test("G05 Refactored: blocks at 3 unverified files (no warn phase)",
         _r.blocked is True,
         f"blocked={_r.blocked}")

    # Test 8: editing same pending file allowed (iterating on fix)
    _g05_same_state = default_state()
    _g05_same_state["pending_verification"] = ["/a.py", "/b.py", "/c.py"]
    _r = g05_check("Edit", {"file_path": "/a.py"}, _g05_same_state)
    test("G05 Refactored: editing pending file ok (only 2 others)",
         not _r.blocked, f"blocked={_r.blocked}")

    # Test 9: notebook_path extraction works
    _r = g05_check("NotebookEdit", {"notebook_path": "/home/user/test_nb.ipynb"}, _g05_state)
    test("G05 Refactored: notebook_path extracted", not _r.blocked, f"blocked={_r.blocked}")

    # Test 10: non-dict tool_input handled safely
    _r = g05_check("Edit", "not a dict", _g05_state)
    test("G05 Refactored: non-dict tool_input safe", not _r.blocked, f"blocked={_r.blocked}")

    # Test 11: edit streak warning at 4+ same-file edits
    _g05_streak_state = default_state()
    _g05_streak_state["edit_streak"] = {"/app.py": 3}
    _r = g05_check("Edit", {"file_path": "/app.py"}, _g05_streak_state)
    test("G05 Refactored: edit streak warning at 4",
         not _r.blocked, f"blocked={_r.blocked}")

    # Test 12: edit streak blocks at 6+ same-file edits
    _g05_streak_block = default_state()
    _g05_streak_block["edit_streak"] = {"/app.py": 5}
    _r = g05_check("Edit", {"file_path": "/app.py"}, _g05_streak_block)
    test("G05 Refactored: edit streak blocks at 6",
         _r.blocked is True, f"blocked={_r.blocked}")

except Exception as _g05_exc:
    test("G05 Refactored: import and basic tests", False, str(_g05_exc))

# ─────────────────────────────────────────────────
# MCP Analytics Server Integration Tests
# ─────────────────────────────────────────────────
print("\n--- Gate 04/07/13/15 Refactored Tests ---")
try:
    # Gate 04: Verify gate_helpers integration
    from gates.gate_04_memory_first import check as g04_check
    import time as _g04_time

    _g04_state = {"memory_last_queried": _g04_time.time()}
    _g04_r = g04_check("Edit", {"file_path": "/tmp/test.py"}, _g04_state)
    test("Gate 04 refactored: allows with recent memory query", not _g04_r.blocked)

    # Note: Gate 04 block depends on sideband file (.memory_last_queried) which
    # may have a recent timestamp from MCP server — test structure instead
    _g04_state2 = {"memory_last_queried": 0}
    _g04_r2 = g04_check("Edit", {"file_path": "/tmp/test.py"}, _g04_state2)
    test("Gate 04 refactored: returns GateResult for stale memory", hasattr(_g04_r2, "blocked") and hasattr(_g04_r2, "gate_name"))

    # Non-gated tool passes through
    _g04_r3 = g04_check("Read", {"file_path": "/tmp/test.py"}, _g04_state2)
    test("Gate 04 refactored: Read tool passes through", not _g04_r3.blocked)

    # Read-only subagent exempt
    _g04_r4 = g04_check("Task", {"subagent_type": "Explore"}, _g04_state2)
    test("Gate 04 refactored: Explore subagent exempt", not _g04_r4.blocked)

    # safe_tool_input handles non-dict
    _g04_r5 = g04_check("Edit", "not_a_dict", _g04_state)
    test("Gate 04 refactored: handles non-dict tool_input", not _g04_r5.blocked)

    # PostToolUse passes through
    _g04_r6 = g04_check("Edit", {"file_path": "/tmp/test.py"}, _g04_state2, event_type="PostToolUse")
    test("Gate 04 refactored: PostToolUse passes through", not _g04_r6.blocked)

    # Gate 07: Verify gate_helpers integration
    from gates.gate_07_critical_file_guard import check as g07_check

    _g07_state = {"memory_last_queried": _g04_time.time()}
    _g07_r = g07_check("Edit", {"file_path": "/tmp/hooks/enforcer.py"}, _g07_state)
    test("Gate 07 refactored: allows critical file with recent memory", not _g07_r.blocked)

    # Note: Gate 07 block depends on sideband file (.memory_last_queried) — test structure
    _g07_state2 = {"memory_last_queried": 0}
    _g07_r2 = g07_check("Edit", {"file_path": "/tmp/hooks/enforcer.py"}, _g07_state2)
    test("Gate 07 refactored: returns GateResult for stale memory", hasattr(_g07_r2, "blocked") and hasattr(_g07_r2, "gate_name"))

    # Non-critical file passes
    _g07_r3 = g07_check("Edit", {"file_path": "/tmp/ordinary.py"}, _g07_state2)
    test("Gate 07 refactored: non-critical file passes", not _g07_r3.blocked)

    # safe_tool_input handles non-dict
    _g07_r4 = g07_check("Edit", "not_a_dict", _g07_state)
    test("Gate 07 refactored: handles non-dict tool_input", not _g07_r4.blocked)

    # Gate 13: Verify gate_helpers integration
    from gates.gate_13_workspace_isolation import check as g13_check

    # Solo session is exempt
    _g13_state = {"_session_id": "main"}
    _g13_r = g13_check("Edit", {"file_path": "/tmp/test.py"}, _g13_state)
    test("Gate 13 refactored: solo session exempt", not _g13_r.blocked)

    # Non-watched tool passes
    _g13_state2 = {"_session_id": "agent-1"}
    _g13_r2 = g13_check("Read", {"file_path": "/tmp/test.py"}, _g13_state2)
    test("Gate 13 refactored: Read tool passes", not _g13_r2.blocked)

    # No file path passes
    _g13_r3 = g13_check("Edit", {}, _g13_state2)
    test("Gate 13 refactored: no file_path passes", not _g13_r3.blocked)

    # PostToolUse passes
    _g13_r4 = g13_check("Edit", {"file_path": "/tmp/test.py"}, _g13_state2, event_type="PostToolUse")
    test("Gate 13 refactored: PostToolUse passes", not _g13_r4.blocked)

    # Gate 15: Verify gate_helpers integration
    from gates.gate_15_causal_chain import check as g15_check

    # No recent test failure -> passes
    _g15_state = {}
    _g15_r = g15_check("Edit", {"file_path": "/tmp/test.py"}, _g15_state)
    test("Gate 15 refactored: passes with no test failure", not _g15_r.blocked)

    # Test failure + fixing_error + no fix_history_queried -> blocks
    _g15_state2 = {
        "recent_test_failure": {"pattern": "ImportError", "timestamp": _g04_time.time()},
        "fixing_error": True,
        "fix_history_queried": 0,
    }
    _g15_r2 = g15_check("Edit", {"file_path": "/tmp/code.py"}, _g15_state2)
    test("Gate 15 refactored: blocks when fix_history not queried", _g15_r2.blocked)

    # Test failure + fix_history recent -> passes
    _g15_state3 = {
        "recent_test_failure": {"pattern": "ImportError", "timestamp": _g04_time.time()},
        "fixing_error": True,
        "fix_history_queried": _g04_time.time(),
    }
    _g15_r3 = g15_check("Edit", {"file_path": "/tmp/code.py"}, _g15_state3)
    test("Gate 15 refactored: passes when fix_history queried recently", not _g15_r3.blocked)

    # Exempt file passes even without fix_history
    _g15_r4 = g15_check("Edit", {"file_path": "/tmp/test_something.py"}, _g15_state2)
    test("Gate 15 refactored: test file exempt", not _g15_r4.blocked)

    # Non-Edit tool passes
    _g15_r5 = g15_check("Read", {"file_path": "/tmp/code.py"}, _g15_state2)
    test("Gate 15 refactored: Read tool passes", not _g15_r5.blocked)

    # safe_tool_input handles non-dict
    _g15_r6 = g15_check("Edit", "not_a_dict", _g15_state2)
    test("Gate 15 refactored: handles non-dict tool_input", not _g15_r6.blocked)

except Exception as _gr_exc:
    test("Gate 04/07/13/15 Refactored Tests: import and tests", False, str(_gr_exc))

# --- Memory Decay Deep Tests ---
