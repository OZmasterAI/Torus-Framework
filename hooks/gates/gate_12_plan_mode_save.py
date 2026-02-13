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
from shared.state import save_state

GATE_NAME = "GATE 12: PLAN MODE SAVE"
ESCALATION_THRESHOLD = 3

WATCHED_TOOLS = ("Edit", "Write", "Bash", "NotebookEdit")


def check(tool_name, tool_input, state, event_type="PreToolUse"):
    """Warn if plan mode was exited without saving the plan to memory.

    Tracks consecutive warnings via gate12_warn_count in state. After
    ESCALATION_THRESHOLD repeated warnings, escalates to a blocking gate.
    Resets the counter when memory is queried (gate passes).
    """
    if event_type != "PreToolUse":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if tool_name not in WATCHED_TOOLS:
        return GateResult(blocked=False, gate_name=GATE_NAME)

    last_exit_plan_mode = state.get("last_exit_plan_mode", 0)
    memory_last_queried = state.get("memory_last_queried", 0)

    if last_exit_plan_mode > 0 and last_exit_plan_mode > memory_last_queried:
        count = state.get("gate12_warn_count", 0) + 1
        state["gate12_warn_count"] = count
        session_id = state.get("_session_id", "main")
        save_state(state, session_id=session_id)

        if count >= ESCALATION_THRESHOLD:
            msg = (
                f"[{GATE_NAME}] BLOCKED ({count}/{ESCALATION_THRESHOLD}): "
                f"Save plan insights to memory. Use remember_this() before continuing."
            )
            print(msg, file=sys.stderr)
            return GateResult(
                blocked=True,
                gate_name=GATE_NAME,
                message=msg,
                severity="warn",
            )

        msg = (
            f"[{GATE_NAME}] WARNING ({count}/{ESCALATION_THRESHOLD}): "
            f"Plan mode exited without saving plan to memory. "
            f"Consider using remember_this() to preserve your plan."
        )
        print(msg, file=sys.stderr)
        return GateResult(
            blocked=False,
            gate_name=GATE_NAME,
            message=msg,
        )

    # Gate passes — memory was queried after plan mode exit; reset counter
    if state.get("gate12_warn_count", 0) > 0:
        state["gate12_warn_count"] = 0
        session_id = state.get("_session_id", "main")
        save_state(state, session_id=session_id)

    return GateResult(blocked=False, gate_name=GATE_NAME)
