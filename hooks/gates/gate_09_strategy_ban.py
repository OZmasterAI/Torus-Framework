"""Gate 9: STRATEGY BAN (Tier 2 — Quality)

Blocks Edit/Write when the current fix strategy has been proven ineffective
(banned after multiple failures). Forces Claude to try a different approach.

Retry budget:
  - fail_count == 1: Allow (first attempt might be flaky)
  - fail_count == 2: Warn ("Strategy X has failed twice. Consider a different approach.")
  - fail_count >= 3: Block (banned)
  - If a strategy has succeeded before (success_count > 0), block at fail_count >= 4

This gate only triggers when current_strategy_id is explicitly set AND appears
in active_bans. Fresh sessions have empty current_strategy_id,
so Gate 9 is inert by default.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.gate_result import GateResult

GATE_NAME = "GATE 9: STRATEGY BAN"

# Default ban threshold (block at this many failures)
DEFAULT_BAN_THRESHOLD = 3
# Extra retries granted if the strategy has succeeded before
SUCCESS_BONUS_RETRIES = 1


def check(tool_name, tool_input, state, event_type="PreToolUse"):
    """Block Edit/Write if the current strategy is banned, with retry budget."""
    if event_type != "PreToolUse":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if tool_name not in ("Edit", "Write", "NotebookEdit"):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    current_strategy = state.get("current_strategy_id", "")
    if not current_strategy:
        return GateResult(blocked=False, gate_name=GATE_NAME)

    active_bans = state.get("active_bans", [])

    # Backward compatibility: list format → all entries are fully banned (legacy behavior)
    if isinstance(active_bans, list):
        if current_strategy in active_bans:
            return GateResult(
                blocked=True,
                gate_name=GATE_NAME,
                message=f"[{GATE_NAME}] BLOCKED: Strategy '{current_strategy}' is BANNED "
                        f"(proven ineffective). Call query_fix_history() for alternatives.",
            )
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # New dict format: {strategy_id: {fail_count, first_failed, last_failed}}
    ban_info = active_bans.get(current_strategy)
    if not ban_info:
        return GateResult(blocked=False, gate_name=GATE_NAME)

    fail_count = ban_info.get("fail_count", 0)

    # Check if strategy has prior successes (gives +1 retry)
    successful_strategies = state.get("successful_strategies", {})
    success_info = successful_strategies.get(current_strategy, {})
    success_count = success_info.get("success_count", 0)

    ban_threshold = DEFAULT_BAN_THRESHOLD
    if success_count > 0:
        ban_threshold += SUCCESS_BONUS_RETRIES

    if fail_count >= ban_threshold:
        return GateResult(
            blocked=True,
            gate_name=GATE_NAME,
            message=f"[{GATE_NAME}] BLOCKED: Strategy '{current_strategy}' is BANNED "
                    f"({fail_count} failures, threshold={ban_threshold}). "
                    f"Call query_fix_history() for alternatives.",
        )

    if fail_count == 2:
        # Warn but allow
        print(
            f"[{GATE_NAME}] WARNING: Strategy '{current_strategy}' has failed twice. "
            f"Consider a different approach.",
            file=sys.stderr,
        )

    return GateResult(blocked=False, gate_name=GATE_NAME)
