"""Gate 9: STRATEGY BAN (Tier 2 — Quality)

Blocks Edit/Write when the current fix strategy has been proven ineffective
(banned after multiple failures). Forces Claude to try a different approach.

Retry budget:
  - fail_count == 1: Allow (first attempt might be flaky)
  - fail_count == 2: Warn ("Strategy X has failed twice. Consider a different approach.")
  - fail_count >= 3: Block + auto-defer (banned, written to deferred items)
  - If a strategy has succeeded before (success_count > 0), block at fail_count >= 4

On ban (3+ failures): writes error + context to {prp}.deferred.md if a PRP is active,
and adds to state["deferred_items"]. This gives a graceful exit path instead of a
hard wall — the error is tracked as technical debt and surfaced at verify-phase.

This gate only triggers when current_strategy_id is explicitly set AND appears
in active_bans. Fresh sessions have empty current_strategy_id,
so Gate 9 is inert by default.
"""

import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.gate_result import GateResult

GATE_NAME = "GATE 9: STRATEGY BAN"

# Default ban threshold (block at this many failures)
DEFAULT_BAN_THRESHOLD = 3
# Extra retries granted if the strategy has succeeded before
SUCCESS_BONUS_RETRIES = 1
# PRP directory for deferred items
PRP_DIR = os.path.expanduser("~/.claude/PRPs")


def _write_deferred_item(strategy, error_sig, fail_count, filepath):
    """Write a deferred item to the active PRP's deferred.md (if any) and return the entry."""
    entry = {
        "strategy": strategy,
        "error_signature": error_sig,
        "fail_count": fail_count,
        "file": filepath,
        "deferred_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    # Find active PRP: look for any .tasks.json with in_progress tasks
    active_prp = None
    for tf in glob.glob(os.path.join(PRP_DIR, "*.tasks.json")):
        try:
            with open(tf) as f:
                data = json.load(f)
            if any(t.get("status") == "in_progress" for t in data.get("tasks", [])):
                active_prp = os.path.basename(tf).replace(".tasks.json", "")
                break
        except (json.JSONDecodeError, IOError):
            continue

    if active_prp:
        deferred_file = os.path.join(PRP_DIR, f"{active_prp}.deferred.md")
        header_needed = not os.path.exists(deferred_file)
        with open(deferred_file, "a") as f:
            if header_needed:
                f.write(f"# Deferred Items: {active_prp}\n\n")
            f.write(f"### {entry['deferred_at']} — Strategy `{strategy}` banned\n")
            f.write(f"- **Error**: {error_sig[:200]}\n")
            f.write(f"- **File**: {filepath}\n")
            f.write(f"- **Failures**: {fail_count}\n")
            f.write(f"- **Action needed**: Try different approach or escalate to human review\n\n")

    return entry


def _ban_severity(fail_count):
    """Compute escalation severity from failure count."""
    if fail_count >= 3:
        return "escalating", "critical"
    elif fail_count >= 2:
        return "repeating", "error"
    else:
        return "first_fail", "warn"


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
            level_name, result_severity = _ban_severity(3)  # legacy defaults to 3
            return GateResult(
                blocked=True,
                gate_name=GATE_NAME,
                severity=result_severity,
                message=f"[{GATE_NAME}] BLOCKED ({level_name}): Strategy '{current_strategy}' is BANNED "
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
        level_name, result_severity = _ban_severity(fail_count)
        first_failed = ban_info.get("first_failed", 0)
        last_failed = ban_info.get("last_failed", 0)
        now = time.time()
        first_ago = int((now - first_failed) / 60) if first_failed else 0
        last_ago = int((now - last_failed) / 60) if last_failed else 0

        # Auto-defer: write to deferred items file and state
        error_sig = state.get("current_error_signature", "unknown")
        filepath = ""
        if isinstance(tool_input, dict):
            filepath = tool_input.get("file_path", tool_input.get("path", ""))
        deferred_entry = _write_deferred_item(current_strategy, error_sig, fail_count, filepath)

        # Add to state's deferred_items list
        deferred_items = state.get("deferred_items", [])
        deferred_items.append(deferred_entry)
        # Cap at 50 to prevent unbounded growth
        if len(deferred_items) > 50:
            deferred_items = deferred_items[-50:]
        state["deferred_items"] = deferred_items

        return GateResult(
            blocked=True,
            gate_name=GATE_NAME,
            severity=result_severity,
            message=f"[{GATE_NAME}] BLOCKED + DEFERRED ({level_name}): Strategy '{current_strategy}' is BANNED "
                    f"({fail_count} failures, threshold={ban_threshold}). "
                    f"first: {first_ago}m ago, last: {last_ago}m ago. "
                    f"Call record_attempt() with a NEW strategy_id, or record_outcome() to close the current chain. "
                    f"Use query_fix_history() to see what's been tried.",
        )

    if fail_count >= 1:
        # Warn but allow — show retry budget with success context
        remaining = ban_threshold - fail_count
        success_context = f" (past successes: {success_count})" if success_count > 0 else ""
        print(
            f"[{GATE_NAME}] WARNING: Strategy '{current_strategy}' has failed "
            f"{fail_count}/{ban_threshold} times{success_context}. "
            f"{remaining} more failure(s) before ban. Consider a different approach.",
            file=sys.stderr,
        )

    return GateResult(blocked=False, gate_name=GATE_NAME)
