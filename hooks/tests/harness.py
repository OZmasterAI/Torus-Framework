#!/usr/bin/env python3
"""Shared test harness for Torus Framework test suite.

Provides test(), skip(), run_enforcer(), _direct(), _direct_stderr(), _post()
helpers and global PASS/FAIL/RESULTS/SKIPPED counters shared across all test modules.
"""

import json
import os
import subprocess
import sys
import time

# Add hooks dir to path so gate/shared imports work
HOOKS_DIR = os.path.dirname(os.path.dirname(__file__))
if HOOKS_DIR not in sys.path:
    sys.path.insert(0, HOOKS_DIR)

from shared.state import (
    load_state, save_state, reset_state, default_state,
    state_file_for, cleanup_all_states, MEMORY_TIMESTAMP_FILE,
)

# ── Global counters (shared across all test modules) ──
PASS = 0
FAIL = 0
RESULTS = []
SKIPPED = 0

# ── Memory server detection ──
from shared.memory_socket import is_worker_available as _uds_available

def _memory_server_running():
    if _uds_available(retries=1, delay=0.1):
        return True
    try:
        r = subprocess.run(
            ["pgrep", "-f", "memory_server.py"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0:
            return False
        own_pid = str(os.getpid())
        pids = [p for p in r.stdout.strip().split() if p != own_pid]
        return len(pids) > 0
    except Exception:
        return False

MEMORY_SERVER_RUNNING = _memory_server_running()
if MEMORY_SERVER_RUNNING:
    print("[INFO] Memory MCP server is running — skipping direct import tests")
    print("[INFO] (LanceDB concurrent access avoided for test isolation)")
    print()

# Back up sideband file so real memory queries don't interfere with gate tests
_SIDEBAND_BACKUP = None
if os.path.exists(MEMORY_TIMESTAMP_FILE):
    with open(MEMORY_TIMESTAMP_FILE) as _sbf:
        _SIDEBAND_BACKUP = _sbf.read()
    os.remove(MEMORY_TIMESTAMP_FILE)

# ── Test session IDs ──
MAIN_SESSION = "test-main"
SUB_SESSION_A = "test-sub-a"
SUB_SESSION_B = "test-sub-b"

def test(name, condition, detail=""):
    """Record a test result."""
    global PASS, FAIL
    if condition:
        PASS += 1
        RESULTS.append(f"  PASS  {name}")
    else:
        FAIL += 1
        RESULTS.append(f"  FAIL  {name} — {detail}")

def skip(name, reason="memory server running"):
    """Mark a test as skipped (counts as pass)."""
    global PASS, SKIPPED
    PASS += 1
    SKIPPED += 1
    RESULTS.append(f"  SKIP  {name} — {reason}")

def run_enforcer(event_type, tool_name, tool_input, session_id=MAIN_SESSION, tool_response=None):
    """Simulate running the enforcer (PreToolUse) or tracker (PostToolUse)."""
    payload = {
        "session_id": session_id,
        "tool_name": tool_name,
        "tool_input": tool_input,
    }
    if tool_response is not None:
        payload["tool_response"] = tool_response
    data = json.dumps(payload)
    if event_type == "PostToolUse":
        cmd = [sys.executable, os.path.join(HOOKS_DIR, "tracker.py")]
    else:
        cmd = [sys.executable, os.path.join(HOOKS_DIR, "enforcer.py")]
    result = subprocess.run(
        cmd, input=data, capture_output=True, text=True, timeout=10
    )
    return result.returncode, result.stderr.strip()

def cleanup_test_states():
    """Remove test state files, enforcer sideband files, memory sideband file, and clean file claims."""
    from shared.state import delete_enforcer_sideband
    for sid in [MAIN_SESSION, SUB_SESSION_A, SUB_SESSION_B, "rich-context-test", "main"]:
        path = state_file_for(sid)
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        delete_enforcer_sideband(sid)
    try:
        os.remove(MEMORY_TIMESTAMP_FILE)
    except FileNotFoundError:
        pass
    claims_file = os.path.join(HOOKS_DIR, ".file_claims.json")
    try:
        if os.path.exists(claims_file):
            with open(claims_file) as f:
                claims = json.load(f)
            test_sids = {MAIN_SESSION, SUB_SESSION_A, SUB_SESSION_B}
            cleaned = {fp: info for fp, info in claims.items()
                       if isinstance(info, dict) and info.get("session_id") in test_sids}
            with open(claims_file, "w") as f:
                json.dump(cleaned, f)
    except (json.JSONDecodeError, OSError):
        pass

# ── Direct gate imports for in-process testing ──
from gates.gate_01_read_before_edit import check as _g01_check
from gates.gate_02_no_destroy import check as _g02_check
from gates.gate_03_test_before_deploy import check as _g03_check
from gates.gate_04_memory_first import check as _g04_check
from gates.gate_05_proof_before_fixed import check as _g05_check
from gates.gate_06_save_fix import check as _g06_check
from gates.gate_07_critical_file_guard import check as _g07_check
from gates.gate_09_strategy_ban import check as _g09_check
from gates.gate_11_rate_limit import check as _g11_check

def _direct(result):
    """Convert GateResult to (exit_code, msg) matching run_enforcer return."""
    return (2 if result.blocked else 0), (result.message or "")

import io as _io
import contextlib as _contextlib

def _direct_stderr(check_fn, tool_name, tool_input, state):
    """Call gate check() and capture stderr (for advisory gates that print warnings)."""
    buf = _io.StringIO()
    with _contextlib.redirect_stderr(buf):
        result = check_fn(tool_name, tool_input, state)
    code = 2 if result.blocked else 0
    msg = result.message or ""
    captured = buf.getvalue().strip()
    if captured:
        msg = (msg + "\n" + captured).strip() if msg else captured
    return code, msg

from tracker_pkg.orchestrator import handle_post_tool_use as _tracker_post

def _post(tool_name, tool_input, state, session_id="main", tool_response=None):
    """Call tracker PostToolUse directly, mutating state in-place. Returns state."""
    _tracker_post(tool_name, tool_input, state, session_id=session_id, tool_response=tool_response)
    return state

def table_test(prefix, check_fn, cases, state_factory=None):
    """Run a table of (label, tool_name, tool_input, expect_blocked) tests."""
    for label, tool_name, tool_input, expect_blocked in cases:
        st = state_factory() if state_factory else {}
        result = check_fn(tool_name, tool_input, st)
        test(f"{prefix}: {label}", result.blocked == expect_blocked,
             f"blocked={result.blocked}, expected={expect_blocked}")
