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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.gate_result import GateResult
from shared.state import save_state

GATE_NAME = "GATE 6: SAVE VERIFIED FIX"

# How many unsaved verified fixes before we warn (not block)
WARN_THRESHOLD = 2

# Escalation: after this many warnings, Gate 6 becomes blocking
ESCALATION_THRESHOLD = 5


def check(tool_name, tool_input, state, event_type="PreToolUse"):
    """Advisory gate that escalates to blocking after repeated ignored warnings."""
    if event_type != "PreToolUse":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if tool_name not in ("Edit", "Write", "Task", "Bash"):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    warn_count = state.get("gate6_warn_count", 0)
    issued_warning = False

    verified_fixes = state.get("verified_fixes", [])
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
    pattern_counts = state.get("error_pattern_counts", {})
    for pat, count in pattern_counts.items():
        if count >= 3:
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
        # Persist counter (enforcer doesn't save state after gate checks)
        try:
            session_id = state.get("_session_id", "main")
            save_state(state, session_id=session_id)
        except Exception:
            pass  # Don't crash gate on save failure

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
