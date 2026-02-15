"""Gate 14: PRE-IMPLEMENTATION CONFIDENCE (Tier 2 — Quality)

Checks confidence signals before allowing new file creation via Edit/Write/NotebookEdit.
Progressive enforcement: warns 2x, blocks on 3rd attempt.

Confidence signals checked:
  1. session_test_baseline — has a test been run this session?
  2. pending_verification — are previous edits verified?
  3. memory_last_queried — is memory fresh (< 5 min)?

Exemptions:
  - Re-edits of files already in pending_verification (iteration, not new work)
  - Test files (*test*, *spec*), config files (HANDOFF.md, LIVE_STATE.json,
    CLAUDE.md, __init__.py), and skills/ directory

Tier 2 (non-safety): gate crash = warn + continue, not block.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.gate_result import GateResult
from shared.state import get_memory_last_queried

GATE_NAME = "GATE 14: PRE-IMPLEMENTATION CONFIDENCE"
WATCHED_TOOLS = {"Edit", "Write", "NotebookEdit"}
MEMORY_FRESHNESS_SECONDS = 300  # 5 minutes
MAX_WARNINGS = 2  # Block on attempt MAX_WARNINGS + 1

# Files/patterns exempt from confidence checks
EXEMPT_BASENAMES = {"HANDOFF.md", "LIVE_STATE.json", "CLAUDE.md", "__init__.py"}
EXEMPT_PATTERNS = ("test_", "_test.", ".test.", "spec_", "_spec.", ".spec.")


def _is_exempt(file_path):
    """Check if file is exempt from confidence checks."""
    if not file_path:
        return True
    basename = os.path.basename(file_path)
    # Exempt specific config files
    if basename in EXEMPT_BASENAMES:
        return True
    # Exempt test/spec files
    lower = basename.lower()
    if any(pat in lower for pat in EXEMPT_PATTERNS):
        return True
    # Exempt skills/ directory
    norm = os.path.normpath(file_path)
    if "/skills/" in norm or "\\skills\\" in norm:
        return True
    return False


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
    pending = state.get("pending_verification", [])
    if len(pending) > 0:
        failures.append(f"{len(pending)} file(s) with unverified edits")
    # Signal 3: memory freshness
    mem_ts = get_memory_last_queried(state)
    age = time.time() - mem_ts if mem_ts else float("inf")
    if age > MEMORY_FRESHNESS_SECONDS:
        failures.append(f"memory last queried {int(age)}s ago (>{MEMORY_FRESHNESS_SECONDS}s)")
    return failures


def check(tool_name, tool_input, state, event_type="PreToolUse"):
    """Check pre-implementation confidence before creating/editing new files."""
    if event_type != "PreToolUse":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if tool_name not in WATCHED_TOOLS:
        return GateResult(blocked=False, gate_name=GATE_NAME)

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
        # All signals pass — reset warning counter
        state["confidence_warnings"] = 0
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Progressive enforcement
    warnings = state.get("confidence_warnings", 0)
    warnings += 1
    state["confidence_warnings"] = warnings
    failure_str = "; ".join(failures)

    if warnings > MAX_WARNINGS:
        msg = (
            f"[{GATE_NAME}] BLOCKED: Low confidence ({failure_str}). "
            f"Run tests, verify pending edits, or query memory before creating new files. "
            f"({warnings} attempts — exceeded {MAX_WARNINGS} warning limit)"
        )
        return GateResult(blocked=True, gate_name=GATE_NAME, message=msg, severity="warn")

    msg = (
        f"[{GATE_NAME}] WARNING ({warnings}/{MAX_WARNINGS}): Low confidence ({failure_str}). "
        f"Consider running tests, verifying pending edits, or querying memory first."
    )
    # Print warning but don't block
    print(msg, file=sys.stderr)
    return GateResult(blocked=False, gate_name=GATE_NAME, message=msg, severity="warn")
