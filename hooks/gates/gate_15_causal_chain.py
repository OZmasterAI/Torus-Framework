"""Gate 15: CAUSAL CHAIN ENFORCEMENT (Tier 2 — Quality)

Blocks Edit/Write when a test failure has been detected but query_fix_history
has not been called. Forces Claude to check what's been tried before attempting
a fix, feeding data into the causal chain system (record_attempt/record_outcome).

Trigger condition:
  - state["recent_test_failure"] is set (non-None) — tests recently failed
  - state["fix_history_queried"] is stale (>5 min ago or never)
  - Only triggers on Edit/Write/NotebookEdit (code changes)

When triggered:
  - BLOCKS the edit and tells Claude to call query_fix_history first
  - This ensures Gate 9 (strategy ban) has data to work with

Exemptions:
  - Test files (*test*, *spec*) — editing tests to fix them is fine
  - Config files (HANDOFF.md, LIVE_STATE.json, CLAUDE.md)
  - If fixing_error is False (no active error context)

Tier 2 (non-safety): gate crash = warn + continue, not block.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.gate_result import GateResult

GATE_NAME = "GATE 15: CAUSAL CHAIN ENFORCEMENT"
WATCHED_TOOLS = {"Edit", "Write", "NotebookEdit"}
FIX_HISTORY_FRESHNESS = 300  # 5 minutes

from shared.exemptions import is_exempt_standard as _is_exempt


def check(tool_name, tool_input, state, event_type="PreToolUse"):
    """Block Edit/Write when test failure detected but fix_history not queried."""
    if event_type != "PreToolUse":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if tool_name not in WATCHED_TOOLS:
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Only trigger when there's an active error context
    recent_failure = state.get("recent_test_failure")
    if not recent_failure:
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Check if we're actively fixing an error
    if not state.get("fixing_error", False):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Exempt files (test files, config files)
    file_path = tool_input.get("file_path", "") or tool_input.get("notebook_path", "")
    if _is_exempt(file_path):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Check if fix_history was queried recently
    fix_history_ts = state.get("fix_history_queried", 0)
    now = time.time()
    age = now - fix_history_ts if fix_history_ts else float("inf")

    fix_freshness = state.get("gate_tune_overrides", {}).get("gate_15_causal_chain", {}).get("fix_history_freshness", FIX_HISTORY_FRESHNESS)
    if age <= fix_freshness:
        # Fix history was queried recently — allow
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # BLOCK: test failure detected, fix_history not queried
    failure_pattern = recent_failure.get("pattern", "unknown") if isinstance(recent_failure, dict) else "unknown"
    failure_age = int(now - recent_failure.get("timestamp", now)) if isinstance(recent_failure, dict) else 0

    msg = (
        f"[{GATE_NAME}] BLOCKED: Test failure detected ({failure_pattern}, {failure_age}s ago) "
        f"but query_fix_history() not called. Call query_fix_history(\"{failure_pattern}\") "
        f"before editing code to check what strategies have been tried."
    )
    return GateResult(blocked=True, gate_name=GATE_NAME, message=msg, severity="error")
