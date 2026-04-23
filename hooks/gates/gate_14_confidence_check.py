"""Gate 14: PRE-IMPLEMENTATION CONFIDENCE (Tier 2 — Quality)

Checks confidence signals before allowing new file creation via Edit/Write/NotebookEdit.

Confidence signals checked:
  1. session_test_baseline — has a test been run this session? (WARN-ONLY, not blocking)
  2. pending_verification — are previous edits verified? (BLOCKING)
  3. memory_last_queried — DORMANT (redundant with Gate 4)

Signal 1 was changed from blocking to warn-only to avoid session-start deadlock:
the first edit of any session would always be blocked since no tests have run yet.

Exemptions:
  - Re-edits of files already in pending_verification (iteration, not new work)
  - Test files (*test*, *spec*), config files (LIVE_STATE.json,
    CLAUDE.md, __init__.py), skills/ directory, and non-code files (.md, .json, .sh, etc.)

Tier 2 (non-safety): gate crash = warn + continue, not block.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.gate_result import GateResult
from shared.gate_helpers import extract_file_path, safe_tool_input

GATE_NAME = "GATE 14: CONFIDENCE CHECK"
WATCHED_TOOLS = {"Edit", "Write", "NotebookEdit"}

# Block when pending_verification count meets or exceeds this threshold.
# Raised from 2→5 to avoid deadlocking multi-file workflows. Gate 5
# (proof-before-fixed) already blocks at 4 other-file edits, so Gate 14
# acts as a softer outer fence that catches sustained unverified streaks.
# Tunable via state["gate_tune_overrides"]["gate_14_confidence_check"]["pending_threshold"].
PENDING_THRESHOLD = 5

from shared.exemptions import is_exempt_full as _is_exempt


# Map source directories to their most relevant test file (fast, targeted tests)
_TEST_MAP = {
    "gates/": "tests/test_gates_quality.py",
    "shared/": "tests/test_shared_core.py",
    "tracker_pkg/": "tests/test_state_tracking.py",
    "boot_pkg/": "tests/test_project_detection.py",
}


def _suggest_test(pending_files):
    """Suggest a targeted test command for the pending files."""
    if not pending_files:
        return "pytest -x -q"
    # Find best test file based on first pending file's directory
    for fp in pending_files:
        for src_dir, test_file in _TEST_MAP.items():
            if src_dir in fp:
                return f"pytest hooks/{test_file} -x -q"
    # Fallback: smallest general test
    return "pytest hooks/tests/test_edit_streak.py -x -q"


def _is_re_edit(file_path, state):
    """Check if this file is already in pending_verification (iteration)."""
    if not file_path:
        return False
    pending = state.get("pending_verification", [])
    norm = os.path.normpath(file_path)
    return norm in pending or file_path in pending


def _is_new_file(file_path):
    """Check if this is a Write to a file that doesn't exist yet (greenfield)."""
    if not file_path:
        return False
    return not os.path.exists(file_path)


def _check_signals(state, file_path=""):
    """Check confidence signals. Returns list of failed signal descriptions."""
    failures = []
    # Signal 1: session_test_baseline — require for all code files
    if not state.get("session_test_baseline", False):
        failures.append("no test run this session")
    # Signal 2: pending_verification
    # Suppress during active error fixing — having unverified edits is expected
    # when fixing a known test failure. Gate 5 still limits unverified file count.
    pending = state.get("pending_verification", [])
    tune = state.get("gate_tune_overrides", {}).get("gate_14_confidence_check", {})
    pending_threshold = tune.get("pending_threshold", PENDING_THRESHOLD)
    if len(pending) >= pending_threshold and not state.get("fixing_error", False):
        failures.append(f"{len(pending)} file(s) with unverified edits")
    # Signal 3: memory freshness — DORMANT (redundant with Gate 4)
    # mem_ts = get_memory_last_queried(state)
    # age = time.time() - mem_ts if mem_ts else float("inf")
    # if age > MEMORY_FRESHNESS_SECONDS:
    #     failures.append(f"memory last queried {int(age)}s ago (>{MEMORY_FRESHNESS_SECONDS}s)")
    return failures


def check(tool_name, tool_input, state, event_type="PreToolUse"):
    """Check pre-implementation confidence before creating/editing new files."""
    if event_type != "PreToolUse":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if tool_name not in WATCHED_TOOLS:
        return GateResult(blocked=False, gate_name=GATE_NAME)

    tool_input = safe_tool_input(tool_input)
    file_path = extract_file_path(tool_input)

    # Exempt files
    if _is_exempt(file_path):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Re-edits of pending files are allowed (iteration)
    if _is_re_edit(file_path, state):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Greenfield: creating a new file that doesn't exist yet — allow through.
    # Pending verification from other files shouldn't block new file creation.
    if tool_name == "Write" and _is_new_file(file_path):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Check confidence signals
    failures = _check_signals(state, file_path=file_path)
    if not failures:
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Separate hard-block failures (pending verification) from soft warnings (test baseline).
    # Test baseline alone should warn, not block — avoids deadlock at session start
    # where no tests have been run yet but the first edit is needed.
    hard_failures = [f for f in failures if "test run" not in f]
    soft_failures = [f for f in failures if "test run" in f]

    if hard_failures:
        pending = state.get("pending_verification", [])
        pending_str = ", ".join(os.path.basename(f) for f in pending[:5])
        suggested = _suggest_test(pending)
        msg = (
            f"[{GATE_NAME}] BLOCKED: {len(pending)} unverified file(s): {pending_str}. "
            f"Run: {suggested}"
        )
        return GateResult(
            blocked=True, gate_name=GATE_NAME, message=msg, severity="warn"
        )

    # Soft-only: warn but allow through
    if soft_failures:
        msg = (
            f"[{GATE_NAME}] WARNING: no test run this session. "
            f"Consider: pytest hooks/tests/test_edit_streak.py -x -q"
        )
        return GateResult(
            blocked=False, gate_name=GATE_NAME, message=msg, severity="warn"
        )
