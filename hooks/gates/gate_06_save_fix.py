"""Gate 6: SAVE VERIFIED FIX (Tier 2 — Quality)

After verifying a fix works, nudges (does not hard-block) to save
the knowledge to memory before continuing with new work.

This gate is softer than others — it tracks verified fixes and
reminds rather than blocks, since hard-blocking here would be
too disruptive to workflow.

The verified_fixes list is populated by the PostToolUse handler
when tests pass after edits were made.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.gate_result import GateResult

GATE_NAME = "GATE 6: SAVE VERIFIED FIX"

# How many unsaved verified fixes before we warn (not block)
WARN_THRESHOLD = 2

# Escalation: after this many warnings, Gate 6 becomes blocking
# Set to 5 (not 2) to give adequate room for remember_this() resets
# and avoid premature deadlocks where blocking prevents clearing
ESCALATION_THRESHOLD = 5

# Verified fixes older than this are considered stale (expired)
STALE_FIX_SECONDS = 1200  # 20 minutes

# Paths excluded from verified_fixes tracking (temp files, non-project files)
EXCLUDED_PREFIXES = ("/tmp/", "/var/tmp/", "/dev/")


def check(tool_name, tool_input, state, event_type="PreToolUse"):
    """Advisory gate that escalates to blocking after repeated ignored warnings."""
    if event_type != "PreToolUse":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if tool_name not in ("Edit", "Write", "Task", "Bash"):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    warn_count = state.get("gate6_warn_count", 0)
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
    if len(verified_fixes) >= WARN_THRESHOLD:
        fix_list = ", ".join(os.path.basename(f) for f in verified_fixes[:3])
        print(
            f"[{GATE_NAME}] WARNING: {len(verified_fixes)} verified fixes not saved to memory ({fix_list}). "
            f"Consider using remember_this() with outcome:success tag to save what worked.",
            file=sys.stderr,
        )
        issued_warning = True
        # Smart batching suggestion when multiple fixes unsaved
        if len(verified_fixes) >= 3:
            print(
                f"[{GATE_NAME}] TIP: Save all {len(verified_fixes)} fixes at once with a single "
                f"remember_this() call summarizing the changes.",
                file=sys.stderr,
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

    # Escalation: track warning count and block after threshold
    if issued_warning:
        warn_count += 1
        state["gate6_warn_count"] = warn_count
        # Note: enforcer saves state after all gates (enforcer.py line 318).
        # Do NOT save_state here — it races with external state clears
        # and overwrites resets from remember_this(), causing deadlocks.

        if warn_count >= ESCALATION_THRESHOLD:
            return GateResult(
                blocked=True,
                message=f"[{GATE_NAME}] BLOCKED: {warn_count} verified fixes unsaved. "
                        f"Call remember_this() to continue.",
                gate_name=GATE_NAME,
                severity="error",
            )

    # If warnings were issued but not blocking, mark as advisory
    severity = "warn" if issued_warning else "info"
    return GateResult(blocked=False, gate_name=GATE_NAME, severity=severity)
