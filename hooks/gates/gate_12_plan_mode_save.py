"""Gate 12: PLAN MODE SAVE (Advisory)

Warns when plan mode was exited without saving the plan to memory.
This is an advisory gate — it NEVER blocks, only prints a warning to stderr.

Checks state["last_exit_plan_mode"] vs state["memory_last_queried"] to detect
when a plan was created but not persisted via remember_this().
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.gate_result import GateResult

GATE_NAME = "GATE 12: PLAN MODE SAVE"

WATCHED_TOOLS = ("Edit", "Write", "Bash", "NotebookEdit")


def check(tool_name, tool_input, state, event_type="PreToolUse"):
    """Warn if plan mode was exited without saving the plan to memory."""
    if event_type != "PreToolUse":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if tool_name not in WATCHED_TOOLS:
        return GateResult(blocked=False, gate_name=GATE_NAME)

    last_exit_plan_mode = state.get("last_exit_plan_mode", 0)
    memory_last_queried = state.get("memory_last_queried", 0)

    if last_exit_plan_mode > 0 and last_exit_plan_mode > memory_last_queried:
        msg = (
            f"[{GATE_NAME}] Warning: Plan mode exited without saving plan "
            f"to memory. Consider using remember_this() to preserve your plan."
        )
        print(msg, file=sys.stderr)
        return GateResult(
            blocked=False,
            gate_name=GATE_NAME,
            message=msg,
        )

    return GateResult(blocked=False, gate_name=GATE_NAME)
