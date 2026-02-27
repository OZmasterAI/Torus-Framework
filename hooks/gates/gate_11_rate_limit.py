"""Gate 11: RATE LIMIT (Tier 2 — Quality)

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
WINDOW_SECONDS = 120   # rolling window size
MAX_WINDOW_ENTRIES = 200  # cap stored timestamps


ANALYTICS_TOOL_PREFIX = "mcp__analytics__"


def check(tool_name, tool_input, state, event_type="PreToolUse"):
    """Block or warn when tool call rate is too high (rolling window)."""
    if event_type != "PreToolUse":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Analytics tools are read-only — don't count toward rate limit
    if tool_name.startswith(ANALYTICS_TOOL_PREFIX):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    now = time.time()
    timestamps = state.get("rate_window_timestamps", [])

    # Append current call timestamp
    timestamps.append(now)

    # Filter to only timestamps within the rolling window
    cutoff = now - WINDOW_SECONDS
    recent = [t for t in timestamps if t > cutoff]

    # Cap at max entries (keep most recent)
    if len(recent) > MAX_WINDOW_ENTRIES:
        recent = recent[-MAX_WINDOW_ENTRIES:]

    # Save filtered list back to state (enforcer saves state after all gates run)
    state["rate_window_timestamps"] = recent

    # First call — allow through
    if len(recent) <= 1:
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Calculate windowed rate: calls in window / window size in minutes
    windowed_rate = len(recent) / (WINDOW_SECONDS / 60.0)  # calls per minute

    block_threshold = state.get("gate_tune_overrides", {}).get("gate_11_rate_limit", {}).get("block_threshold", BLOCK_THRESHOLD)
    if windowed_rate > block_threshold:
        return GateResult(
            blocked=True,
            gate_name=GATE_NAME,
            message=(
                f"[{GATE_NAME}] BLOCKED: Tool call rate is {windowed_rate:.1f} calls/min "
                f"({len(recent)} calls in {WINDOW_SECONDS}s window, limit: {BLOCK_THRESHOLD}/min). "
                f"Slow down — consider batching work or waiting before the next call."
            ),
        )

    if windowed_rate > WARN_THRESHOLD:
        print(
            f"[{GATE_NAME}] WARNING: Tool call rate is {windowed_rate:.1f} calls/min "
            f"({len(recent)} calls in {WINDOW_SECONDS}s window, warn: {WARN_THRESHOLD}/min). "
            f"Consider slowing down.",
            file=sys.stderr,
        )

    return GateResult(blocked=False, gate_name=GATE_NAME)
