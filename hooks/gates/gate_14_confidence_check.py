"""Gate 14: PRE-IMPLEMENTATION CONFIDENCE (Tier 2 — Quality)

Checks confidence signals before allowing new file creation via Edit/Write/NotebookEdit.
Progressive enforcement: warns once per signal per session, blocks on 3rd per-file attempt.

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

GATE_NAME = "GATE 14: CONFIDENCE CHECK"
WATCHED_TOOLS = {"Edit", "Write", "NotebookEdit"}
MAX_WARNINGS = 2  # Block on per-file attempt MAX_WARNINGS + 1

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

    if not isinstance(tool_input, dict):
        tool_input = {}

    file_path = tool_input.get("file_path", "") or tool_input.get("notebook_path", "")

    # Exempt files
    if _is_exempt(file_path):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Re-edits of pending files are allowed (iteration)
    if _is_re_edit(file_path, state):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Check confidence signals
    failures = _check_signals(state)
    if not failures:
        # All signals pass — reset per-file warning counter
        per_file = state.get("confidence_warnings_per_file", {})
        per_file.pop(file_path, None)
        state["confidence_warnings_per_file"] = per_file
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Per-file progressive enforcement
    per_file = state.get("confidence_warnings_per_file", {})
    file_warnings = per_file.get(file_path, 0) + 1
    per_file[file_path] = file_warnings
    state["confidence_warnings_per_file"] = per_file
    failure_str = "; ".join(failures)

    if file_warnings > MAX_WARNINGS:
        msg = (
            f"[{GATE_NAME}] BLOCKED: Low confidence ({failure_str}). "
            f"Run a Bash command (e.g. pytest) to set test baseline and clear pending verification. "
            f"({file_warnings} attempts on {os.path.basename(file_path)} — exceeded {MAX_WARNINGS} warning limit)"
        )
        return GateResult(blocked=True, gate_name=GATE_NAME, message=msg, severity="warn")

    # Suppress repeated warnings — only warn once per signal per session
    warned_signals = state.get("confidence_warned_signals", set())
    if isinstance(warned_signals, list):
        warned_signals = set(warned_signals)
    new_failures = [f for f in failures if f not in warned_signals]
    if not new_failures:
        # Already warned about these signals — pass silently
        return GateResult(blocked=False, gate_name=GATE_NAME)

    warned_signals.update(failures)
    state["confidence_warned_signals"] = list(warned_signals)
    msg = (
        f"[{GATE_NAME}] WARNING ({file_warnings}/{MAX_WARNINGS}): Low confidence ({failure_str}). "
        f"Consider running tests or verifying pending edits first."
    )
    print(msg, file=sys.stderr)
    return GateResult(blocked=False, gate_name=GATE_NAME, message=msg, severity="warn")
