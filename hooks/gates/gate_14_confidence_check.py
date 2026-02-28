"""Gate 14: PRE-IMPLEMENTATION CONFIDENCE (Tier 2 — Quality)

Checks confidence signals before allowing new file creation via Edit/Write/NotebookEdit.
Blocks immediately on first confidence failure (no warn phase).

Confidence signals checked:
  1. session_test_baseline — has a test been run this session? (code files only)
  2. pending_verification — are previous edits verified?
  3. memory_last_queried — DORMANT (redundant with Gate 4)

Exemptions:
  - Re-edits of files already in pending_verification (iteration, not new work)
  - Test files (*test*, *spec*), config files (HANDOFF.md, LIVE_STATE.json,
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

from shared.exemptions import is_exempt_full as _is_exempt


def _is_re_edit(file_path, state):
    """Check if this file is already in pending_verification (iteration)."""
    if not file_path:
        return False
    pending = state.get("pending_verification", [])
    norm = os.path.normpath(file_path)
    return norm in pending or file_path in pending


def _check_signals(state):
    """Check confidence signals. Returns list of failed signal descriptions."""
    failures = []
    # Signal 1: session_test_baseline
    if not state.get("session_test_baseline", False):
        failures.append("no test run this session")
    # Signal 2: pending_verification
    # Suppress during active error fixing — having unverified edits is expected
    # when fixing a known test failure. Gate 5 still limits unverified file count.
    pending = state.get("pending_verification", [])
    if len(pending) > 0 and not state.get("fixing_error", False):
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

    # Check confidence signals — block immediately on failure
    failures = _check_signals(state)
    if not failures:
        return GateResult(blocked=False, gate_name=GATE_NAME)

    failure_str = "; ".join(failures)
    msg = (
        f"[{GATE_NAME}] BLOCKED: Low confidence ({failure_str}). "
        f"Run a Bash command (e.g. pytest) to set test baseline and clear pending verification."
    )
    return GateResult(blocked=True, gate_name=GATE_NAME, message=msg, severity="warn")
