"""Gate 20: SELF-CHECK (Tier 2 — Advisory)

PreToolUse gate that fires when a risk score reaches threshold.
Shows two targeted questions — one mechanical, one intent — to catch
high-confidence-but-wrong edits without nagging on routine work.

Risk signals (scored):
  edit_streak[file] >= 3:              +2 pts  (spinning on a file)
  tool_name == "Write":                +1 pt   (full rewrite, higher stakes)
  pending_verification >= 2, no fix:   +1 pt   (accumulating unverified debt)
  no test baseline + framework file:   +1 pt   (editing framework untested)
  Gate 16 warned on last edit:         +2 pts  (complexity flagged = possible design issue)

Fires when total score >= 3.

Always shows exactly two questions:
  Mechanical: Have callers and the public API been verified against this change?
  Intent:     Does this actually solve the stated problem — or does it just compile?

Overlap mitigations:
  - Skips when fixing_error == True (Gate 15 owns that territory)
  - Skips exempt files (test files, config, __init__.py)
  - Never blocks — warn-only, severity "info"

Extensible: C (trigger-specific 3rd question) and D (PostToolUse reflection)
can be added independently without changing this gate's logic.

Tier 2, fail-open: gate crash = warn + continue, not block.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.gate_result import GateResult
from shared.exemptions import is_exempt_full as _is_exempt
from shared.gate_helpers import extract_file_path, safe_tool_input

GATE_NAME = "GATE 20: SELF-CHECK"
WATCHED_TOOLS = {"Edit", "Write", "NotebookEdit"}

# Fire when risk score reaches this threshold
RISK_THRESHOLD = 3

# Framework paths that warrant extra scrutiny when untested
_FRAMEWORK_DIRS = (
    os.path.expanduser("~/.claude/hooks/gates/"),
    os.path.expanduser("~/.claude/hooks/shared/"),
)


def _risk_score(tool_name: str, file_path: str, state: dict) -> int:
    """Compute risk score from state signals. >= RISK_THRESHOLD triggers the gate."""
    score = 0

    # +2: spinning on a file without verification (high overconfidence risk)
    streak = state.get("edit_streak", {})
    file_streak = streak.get(file_path, 0) if file_path else 0
    if isinstance(file_streak, int) and file_streak >= 3:
        score += 2

    # +1: full rewrite carries more risk than a small edit
    if tool_name == "Write":
        score += 1

    # +1: accumulating unverified edits outside a known fix loop
    pending = state.get("pending_verification", [])
    if len(pending) >= 2 and not state.get("fixing_error", False):
        score += 1

    # +1: editing framework files without any test run this session
    if not state.get("session_test_baseline", False) and file_path:
        if any(file_path.startswith(d) for d in _FRAMEWORK_DIRS):
            score += 1

    # +2: Gate 16 flagged this file recently (complexity may signal a design problem)
    g16 = state.get("code_quality_warnings_per_file", {})
    if file_path and g16.get(file_path, 0) > 0:
        score += 2

    return score


def check(tool_name, tool_input, state, event_type="PreToolUse"):
    """Warn with two self-check questions when risk score indicates likely mistake."""
    if event_type != "PreToolUse":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if tool_name not in WATCHED_TOOLS:
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Gate 15 handles active error-fixing — don't pile on
    if state.get("fixing_error", False):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    tool_input = safe_tool_input(tool_input)
    file_path = extract_file_path(tool_input)

    if _is_exempt(file_path):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    score = _risk_score(tool_name, file_path, state)
    if score < RISK_THRESHOLD:
        return GateResult(blocked=False, gate_name=GATE_NAME)

    fname = os.path.basename(file_path) if file_path else "this file"
    msg = (
        f"[{GATE_NAME}] Before writing {fname} (risk={score}):\n"
        f"  Mechanical: Have callers and the public API been verified against this change?\n"
        f"  Intent:     Does this actually solve the stated problem — or does it just compile?"
    )
    print(msg, file=sys.stderr)
    return GateResult(blocked=False, gate_name=GATE_NAME, message=msg, severity="info")
