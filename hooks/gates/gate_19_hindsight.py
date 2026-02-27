"""Gate 19: HINDSIGHT GATE (Tier 3 — Advisory/Advanced)

PreToolUse gate that reads mentor signals from PostToolUse evaluation.
Blocks Edit/Write/NotebookEdit when the mentor system has detected
sustained poor quality (low score + multiple escalations).

This gate is part of the Mentor System (Module B). It reads state fields
written by Modules A (Tracker Mentor), D (Outcome Chains), and E (Memory Mentor).

Overlap mitigations:
  - Never reads pending_verification or edit_streak (Gate 5's territory)
  - Never reads fixing_error/fix_history_queried for decisions (Gate 15's territory)
  - Skips entirely when state["fixing_error"] == True (defer to Gate 15)
  - Checks mentor_warned_this_cycle to avoid duplicate messages with Module A

Toggle: LIVE_STATE.json["mentor_hindsight_gate"] must be true.
Tier 3, fail-open: gate crash = warn + continue, not block.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.gate_result import GateResult
from shared.state import get_live_toggle
from shared.exemptions import is_exempt_standard as _is_exempt

GATE_NAME = "GATE 19: HINDSIGHT"
WATCHED_TOOLS = {"Edit", "Write", "NotebookEdit"}

# Block thresholds
SCORE_BLOCK_THRESHOLD = 0.3      # mentor_last_score below this triggers block check
ESCALATION_BLOCK_THRESHOLD = 2   # need this many consecutive escalations to actually block
CHAIN_SCORE_WARN_THRESHOLD = 0.3 # warn if outcome chain score is low


def check(tool_name, tool_input, state, event_type="PreToolUse"):
    """Block Edit/Write when mentor signals indicate sustained poor quality."""
    if event_type != "PreToolUse":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if tool_name not in WATCHED_TOOLS:
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Toggle check — skip entirely if hindsight gate is off (mentor_all overrides)
    if not (get_live_toggle("mentor_hindsight_gate") or get_live_toggle("mentor_all")):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Skip when Gate 15 is active (fixing_error = true) — that's Gate 15's territory
    if state.get("fixing_error", False):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Exempt files (test files, config files)
    file_path = tool_input.get("file_path", "") or tool_input.get("notebook_path", "")
    if _is_exempt(file_path):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Read mentor state fields
    mentor_score = state.get("mentor_last_score", 1.0)
    mentor_verdict = state.get("mentor_last_verdict", "proceed")
    escalation_count = state.get("mentor_escalation_count", 0)
    chain_score = state.get("mentor_chain_score", 1.0)
    warned_this_cycle = state.get("mentor_warned_this_cycle", False)

    # BLOCK: sustained escalation (low score + multiple consecutive escalations)
    if mentor_score < SCORE_BLOCK_THRESHOLD and escalation_count >= ESCALATION_BLOCK_THRESHOLD:
        msg = (
            f"[{GATE_NAME}] BLOCKED: Mentor score critically low ({mentor_score:.2f}) "
            f"with {escalation_count} consecutive escalations. "
            f"Last verdict: {mentor_verdict}. "
            f"Run tests, verify your approach, or check memory for prior solutions."
        )
        return GateResult(blocked=True, gate_name=GATE_NAME, message=msg, severity="error")

    # WARN: low chain score (outcome chain detected churn/stuck pattern)
    if chain_score < CHAIN_SCORE_WARN_THRESHOLD and not warned_this_cycle:
        chain_pattern = state.get("mentor_chain_pattern", "")
        msg = (
            f"[{GATE_NAME}] WARNING: Outcome chain score low ({chain_score:.2f}, "
            f"pattern: {chain_pattern or 'unknown'}). Consider changing approach."
        )
        return GateResult(blocked=False, gate_name=GATE_NAME, message=msg, severity="warn")

    # WARN: historical context available from memory mentor
    memory_match = state.get("mentor_memory_match")
    if memory_match and isinstance(memory_match, dict) and not warned_this_cycle:
        context = state.get("mentor_historical_context", "")
        if context:
            msg = f"[{GATE_NAME}] INFO: {context}"
            return GateResult(blocked=False, gate_name=GATE_NAME, message=msg, severity="info")

    return GateResult(blocked=False, gate_name=GATE_NAME)
