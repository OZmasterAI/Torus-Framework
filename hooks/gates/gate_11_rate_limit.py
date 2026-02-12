"""Gate 11: RATE LIMIT (Tier 1 — Safety)

Blocks tool calls when the rate exceeds 60 calls/minute to prevent
runaway loops. Warns at >40 calls/minute to encourage slowing down.

Uses state["tool_call_count"] and state["session_start"] to calculate
the current calls-per-minute rate. A minimum elapsed time floor of
6 seconds prevents division-by-zero issues at session start.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.gate_result import GateResult

GATE_NAME = "GATE 11: RATE LIMIT"

BLOCK_THRESHOLD = 60   # calls/minute — hard block
WARN_THRESHOLD = 40    # calls/minute — stderr warning
MIN_ELAPSED_SECONDS = 6  # floor to avoid division issues at session start
MIN_CALLS_FOR_RATE = 20  # need enough samples for a meaningful rate


def check(tool_name, tool_input, state, event_type="PreToolUse"):
    """Block or warn when tool call rate is too high."""
    if event_type != "PreToolUse":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    tool_call_count = state.get("tool_call_count", 0)
    if tool_call_count < MIN_CALLS_FOR_RATE:
        return GateResult(blocked=False, gate_name=GATE_NAME)
    session_start = state.get("session_start", time.time())

    elapsed = max(time.time() - session_start, MIN_ELAPSED_SECONDS)
    rate = (tool_call_count / elapsed) * 60  # calls per minute

    if rate > BLOCK_THRESHOLD:
        return GateResult(
            blocked=True,
            gate_name=GATE_NAME,
            message=(
                f"[{GATE_NAME}] BLOCKED: Tool call rate is {rate:.1f} calls/min "
                f"(limit: {BLOCK_THRESHOLD}/min). Slow down — consider batching "
                f"work or waiting before the next call."
            ),
        )

    if rate > WARN_THRESHOLD:
        print(
            f"[{GATE_NAME}] WARNING: Tool call rate is {rate:.1f} calls/min "
            f"(warn threshold: {WARN_THRESHOLD}/min). Consider slowing down.",
            file=sys.stderr,
        )

    return GateResult(blocked=False, gate_name=GATE_NAME)
