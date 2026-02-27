"""Gate 6: SAVE TO MEMORY (Tier 2 — Quality)

Blocks edits when verified fixes haven't been saved to memory.
Advisory warnings (stderr) for other conditions.

Checks:
  1. Verified fixes not saved → BLOCKS at threshold (no warn phase)
  2. Unlogged errors → advisory stderr
  3. Repair loops (same error 3+ times) → advisory stderr
  4. Edit streak churn (high-churn files) → advisory stderr
  5. Pending causal chain outcomes → advisory stderr
  6. Plan mode exited without saving → advisory stderr

The verified_fixes list is populated by the PostToolUse handler
when tests pass after edits were made.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.gate_result import GateResult
from shared.state import get_memory_last_queried

GATE_NAME = "GATE 6: SAVE TO MEMORY"

# Block immediately at this many unsaved verified fixes (no warn phase)
BLOCK_THRESHOLD = 2

# Verified fixes older than this are considered stale (expired)
STALE_FIX_SECONDS = 1200  # 20 minutes

# Plan mode: how long before a plan exit is considered stale
PLAN_STALE_SECONDS = 1800  # 30 minutes

# Read-only subagent types — no Edit/Write/Bash, can't create unsaved fixes
READ_ONLY_AGENTS = {"researcher", "Explore"}

# Paths excluded from verified_fixes tracking (temp files, non-project files)
EXCLUDED_PREFIXES = ("/tmp/", "/var/tmp/", "/dev/")


def check(tool_name, tool_input, state, event_type="PreToolUse"):
    """Blocks edits when verified fixes are unsaved. Advisory warnings for other conditions."""
    if event_type != "PreToolUse":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if tool_name not in ("Edit", "Write", "Task", "Bash"):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Read-only subagents can't create unsaved fixes — skip
    if tool_name == "Task":
        subagent_type = tool_input.get("subagent_type", "")
        if subagent_type in READ_ONLY_AGENTS:
            return GateResult(blocked=False, gate_name=GATE_NAME)

    issued_warning = False

    verified_fixes = state.get("verified_fixes", [])
    # Note: /tmp exclusion happens at insertion time in tracker.py, not here.
    # Filtering here would break tests that use /tmp paths for verification.
    # Time-decay: remove verified fixes older than STALE_FIX_SECONDS
    verification_timestamps = state.get("verification_timestamps", {})
    now = time.time()
    fresh_fixes = [f for f in verified_fixes if now - verification_timestamps.get(f, now) <= STALE_FIX_SECONDS]
    if len(fresh_fixes) < len(verified_fixes):
        state["verified_fixes"] = fresh_fixes
        verified_fixes = fresh_fixes

    # Block immediately when unsaved verified fixes reach threshold
    if len(verified_fixes) >= BLOCK_THRESHOLD:
        # Exempt Bash — tests must still run to satisfy Gate 5/15
        if tool_name == "Bash":
            fix_list = ", ".join(os.path.basename(f) for f in verified_fixes[:3])
            print(
                f"[{GATE_NAME}] WARNING: {len(verified_fixes)} verified fixes unsaved ({fix_list}). "
                f"Bash allowed for test verification. Call remember_this() soon.",
                file=sys.stderr,
            )
            return GateResult(blocked=False, gate_name=GATE_NAME, severity="warn")
        fix_list = ", ".join(os.path.basename(f) for f in verified_fixes[:3])
        return GateResult(
            blocked=True,
            message=f"[{GATE_NAME}] BLOCKED: {len(verified_fixes)} verified fixes unsaved ({fix_list}). "
                    f"Call remember_this() to continue.",
            gate_name=GATE_NAME,
            severity="error",
        )

    # Also warn about unlogged errors
    unlogged_errors = state.get("unlogged_errors", [])
    if len(unlogged_errors) >= 1:
        latest = unlogged_errors[-1]
        pattern = latest.get("pattern", "unknown")
        command = latest.get("command", "unknown")
        print(
            f"[{GATE_NAME}] WARNING: {len(unlogged_errors)} unlogged error(s) detected "
            f"(latest: '{pattern}' from `{command}`). "
            f"Consider using remember_this() with outcome:failed,error_pattern:{pattern} tags.",
            file=sys.stderr,
        )
        issued_warning = True

    # Repair loop detection — warn when the same error recurs 3+ times
    # Time-aware: skip warning if the error pattern is stale (>10 min old)
    pattern_counts = state.get("error_pattern_counts", {})
    error_windows = state.get("error_windows", [])
    now = time.time()
    STALE_THRESHOLD = 600  # 10 minutes
    for pat, count in pattern_counts.items():
        if count >= 3:
            # Check if this pattern has a recent entry in error_windows
            is_stale = False
            for window in error_windows:
                if window.get("pattern") == pat:
                    last_seen = window.get("last_seen", 0)
                    if now - last_seen > STALE_THRESHOLD:
                        is_stale = True
                    break
            # If pattern not found in error_windows, still warn (defensive)
            if is_stale:
                continue
            print(
                f"[{GATE_NAME}] REPAIR LOOP: Error '{pat}' has occurred {count} times. "
                f"Consider a different approach instead of retrying the same fix.",
                file=sys.stderr,
            )
            issued_warning = True
            break

    # Edit streak: warn about high-churn files
    edit_streak = state.get("edit_streak", {})
    if edit_streak:
        top_file = max(edit_streak, key=lambda f: edit_streak[f])
        top_count = edit_streak[top_file]
        if top_count >= 3:
            print(
                f"[{GATE_NAME}] Top churn: {os.path.basename(top_file)} ({top_count} edits)",
                file=sys.stderr,
            )
            issued_warning = True

    # Causal tracking: warn about pending chains without recorded outcomes
    pending_chains = state.get("pending_chain_ids", [])
    if len(pending_chains) >= 1:
        print(
            f"[{GATE_NAME}] WARNING: {len(pending_chains)} fix attempt(s) without recorded outcome. "
            f"Call record_outcome() to log whether the fix worked or failed.",
            file=sys.stderr,
        )
        issued_warning = True

    # Plan mode: warn if plan mode exited without saving to memory (former Gate 12)
    last_exit_plan_mode = state.get("last_exit_plan_mode", 0)
    memory_last_queried = get_memory_last_queried(state)
    if last_exit_plan_mode > 0:
        plan_age = time.time() - last_exit_plan_mode
        if plan_age > PLAN_STALE_SECONDS:
            # Stale — auto-forgive
            state["last_exit_plan_mode"] = 0
        elif last_exit_plan_mode > memory_last_queried:
            plan_age_min = int(plan_age / 60)
            print(
                f"[{GATE_NAME}] WARNING: Plan mode exited without saving plan to memory. "
                f"Consider using remember_this() to preserve your plan. "
                f"Plan created {plan_age_min} min ago.",
                file=sys.stderr,
            )
            issued_warning = True

    # If warnings were issued but not blocking, mark as advisory
    severity = "warn" if issued_warning else "info"
    return GateResult(blocked=False, gate_name=GATE_NAME, severity=severity)
