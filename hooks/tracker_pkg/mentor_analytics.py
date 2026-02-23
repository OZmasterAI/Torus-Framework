"""Mentor Analytics (Module F) — analytics tool awareness nudges.

Context-sensitive nudges suggesting analytics MCP tools after
framework file edits. Per-trigger-type cooldowns prevent fatigue.

Called from orchestrator.py with the mentor_analytics toggle.
"""
import time

from tracker_pkg import _log_debug

# ── Trigger → analytics tool mapping with per-type cooldowns ──
# (path_fragment, suggested_tool, cooldown_seconds, human_label)
_TRIGGERS = [
    ("/gates/",    "gate_dashboard", 900,  "gate file"),      # 15 min
    ("/skills/",   "skill_health",   900,  "skill file"),     # 15 min
    ("enforcer",   "gate_timing",    1200, "enforcer"),       # 20 min
    ("tracker",    "gate_timing",    1200, "tracker"),        # 20 min
    ("/shared/",   "gate_timing",    1200, "shared module"),  # 20 min
]

# Periodic checkpoint — every Nth tool call
_PERIODIC_INTERVAL = 50


def _analytics_used_recently(state, tool_name, cooldown_s):
    """Check if a specific analytics tool was called within cooldown window."""
    last_used = state.get("analytics_last_used", {})
    if not isinstance(last_used, dict):
        return False
    last_ts = last_used.get(tool_name, 0)
    return (time.time() - last_ts) < cooldown_s


def evaluate(tool_name, tool_input, tool_response, state):
    """Evaluate a completed tool call and return analytics nudge messages.

    Returns list of message strings (empty = no nudges).
    Called from orchestrator.py during PostToolUse handling.
    """
    messages = []

    try:
        # Only nudge after Edit/Write of framework files
        if tool_name in ("Edit", "Write"):
            file_path = ""
            if isinstance(tool_input, dict):
                file_path = tool_input.get("file_path", "") or ""

            if file_path:
                for path_frag, suggested_tool, cooldown_s, label in _TRIGGERS:
                    if path_frag in file_path:
                        if not _analytics_used_recently(state, suggested_tool, cooldown_s):
                            messages.append(
                                f"You edited a {label}. "
                                f"Run mcp__analytics__{suggested_tool}() to check impact."
                            )
                        break  # first match wins — don't suggest multiple tools

        # Periodic checkpoint — every Nth tool call
        total_calls = state.get("total_tool_calls", 0)
        if total_calls > 0 and total_calls % _PERIODIC_INTERVAL == 0:
            if not _analytics_used_recently(state, "session_summary", 1800):  # 30 min
                messages.append(
                    f"[{total_calls} tool calls] "
                    f"Run mcp__analytics__session_summary() for a checkpoint."
                )

    except Exception as e:
        _log_debug(f"mentor_analytics.evaluate failed (non-blocking): {e}")

    return messages
