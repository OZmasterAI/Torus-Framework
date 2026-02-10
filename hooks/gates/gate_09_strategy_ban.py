"""Gate 9: STRATEGY BAN (Tier 2 — Quality)

Blocks Edit/Write when the current fix strategy has been proven ineffective
(banned after multiple failures). Forces Claude to try a different approach.

This gate only triggers when current_strategy_id is explicitly set AND appears
in the active_bans list. Fresh sessions have empty current_strategy_id,
so Gate 9 is inert by default.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.gate_result import GateResult

GATE_NAME = "GATE 9: STRATEGY BAN"


def check(tool_name, tool_input, state, event_type="PreToolUse"):
    """Block Edit/Write if the current strategy is banned."""
    if event_type != "PreToolUse":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if tool_name not in ("Edit", "Write", "NotebookEdit"):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    current_strategy = state.get("current_strategy_id", "")
    if not current_strategy:
        return GateResult(blocked=False, gate_name=GATE_NAME)

    active_bans = state.get("active_bans", [])
    if current_strategy in active_bans:
        return GateResult(
            blocked=True,
            gate_name=GATE_NAME,
            message=f"[{GATE_NAME}] BLOCKED: Strategy '{current_strategy}' is BANNED "
                    f"(proven ineffective). Call query_fix_history() for alternatives.",
        )

    return GateResult(blocked=False, gate_name=GATE_NAME)
