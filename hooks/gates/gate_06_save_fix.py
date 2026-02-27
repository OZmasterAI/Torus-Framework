"""Gate 6: SAVE TO MEMORY (Tier 2 — Quality)

Unified "save to memory" reminder gate. Nudges (does not hard-block)
to save knowledge before continuing with new work.

Checks:
  1. Verified fixes not saved (tests passed after edits)
  2. Unlogged errors
  3. Repair loops (same error 3+ times)
  4. Edit streak churn (high-churn files)
  5. Pending causal chain outcomes
  6. Plan mode exited without saving (absorbed from former Gate 12)

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

# How many unsaved verified fixes before we warn (not block)
WARN_THRESHOLD = 2

# Escalation: after this many warnings, Gate 6 becomes blocking
# Set to 5 (not 2) to give adequate room for remember_this() resets
# and avoid premature deadlocks where blocking prevents clearing
ESCALATION_THRESHOLD = 5

# Analytics awareness (Upgrade F): SEPARATE counter, loose threshold.
# Only fires for framework file edits without recent analytics query.
# Never cross-contaminates with gate6_warn_count.
ANALYTICS_ESCALATION_THRESHOLD = 15
ANALYTICS_STALE_SECONDS = 1800  # 30 min since last analytics call
FRAMEWORK_PATHS = ("/gates/", "/shared/", "enforcer", "tracker", "/skills/")

# Verified fixes older than this are considered stale (expired)
STALE_FIX_SECONDS = 1200  # 20 minutes

# Plan mode: how long before a plan exit is considered stale
PLAN_STALE_SECONDS = 1800  # 30 minutes

# Read-only subagent types — no Edit/Write/Bash, can't create unsaved fixes
READ_ONLY_AGENTS = {"researcher", "Explore"}

# Paths excluded from verified_fixes tracking (temp files, non-project files)
EXCLUDED_PREFIXES = ("/tmp/", "/var/tmp/", "/dev/")


def check(tool_name, tool_input, state, event_type="PreToolUse"):
    """Advisory gate that escalates to blocking after repeated ignored warnings."""
    if event_type != "PreToolUse":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if tool_name not in ("Edit", "Write", "Task", "Bash"):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Read-only subagents can't create unsaved fixes — skip
    if tool_name == "Task":
        subagent_type = tool_input.get("subagent_type", "")
        if subagent_type in READ_ONLY_AGENTS:
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

    # ── Analytics awareness (Upgrade F) — separate counter, loose threshold ──
    # Only checks Edit/Write on framework paths. Never increments gate6_warn_count.
    analytics_warned = False
    if tool_name in ("Edit", "Write"):
        file_path = tool_input.get("file_path", "") if isinstance(tool_input, dict) else ""
        if any(p in file_path for p in FRAMEWORK_PATHS):
            last_analytics = state.get("analytics_last_queried", 0)
            elapsed = time.time() - last_analytics if last_analytics else float("inf")
            if elapsed > ANALYTICS_STALE_SECONDS:
                analytics_count = state.get("analytics_warn_count", 0) + 1
                state["analytics_warn_count"] = analytics_count
                print(
                    f"[{GATE_NAME}] ANALYTICS: Editing framework file without recent analytics check "
                    f"({analytics_count}/{ANALYTICS_ESCALATION_THRESHOLD}). "
                    f"Consider: gate_dashboard(), gate_timing(), or skill_health()",
                    file=sys.stderr,
                )
                analytics_warned = True
                if analytics_count >= ANALYTICS_ESCALATION_THRESHOLD:
                    if tool_name == "Bash":
                        return GateResult(blocked=False, gate_name=GATE_NAME, severity="warn")
                    return GateResult(
                        blocked=True,
                        message=f"[{GATE_NAME}] BLOCKED: {analytics_count} framework edits without analytics check. "
                                f"Call any mcp__analytics__*() tool to continue.",
                        gate_name=GATE_NAME,
                        severity="error",
                    )

    # Escalation: only verified_fixes warnings count toward blocking.
    # Other warning types (unlogged errors, edit streaks, repair loops) stay
    # advisory-only — they should not accumulate toward blocking because
    # false positives from test output and crash logs inflate the counter.
    fixes_warning = len(verified_fixes) >= WARN_THRESHOLD
    if fixes_warning:
        warn_count += 1
        state["gate6_warn_count"] = warn_count

    escalation_threshold = state.get("gate_tune_overrides", {}).get("gate_06_save_fix", {}).get("escalation_threshold", ESCALATION_THRESHOLD)
    if fixes_warning and warn_count >= escalation_threshold:
            # Exempt Bash from escalation blocking — tests must still run
            # to satisfy Gate 5/15, and blocking Bash creates a deadlock
            if tool_name == "Bash":
                print(
                    f"[{GATE_NAME}] WARNING (escalated): {warn_count} unsaved fixes. "
                    f"Bash allowed for test verification. Call remember_this() soon.",
                    file=sys.stderr,
                )
                return GateResult(blocked=False, gate_name=GATE_NAME, severity="warn")
            return GateResult(
                blocked=True,
                message=f"[{GATE_NAME}] BLOCKED: {warn_count} verified fixes unsaved. "
                        f"Call remember_this() to continue.",
                gate_name=GATE_NAME,
                severity="error",
            )

    # If warnings were issued but not blocking, mark as advisory
    severity = "warn" if (issued_warning or analytics_warned) else "info"
    return GateResult(blocked=False, gate_name=GATE_NAME, severity=severity)
