"""Gate 22: TOOL PROFILE WARNINGS (Tier 3 — Advisory)

Checks tool input against known failure patterns from tool profiles.
Issues warnings (never blocks) when a tool call matches a previously
observed failure pattern. This gives Claude a chance to adjust before
repeating a known mistake.

AutoAgent-inspired: online adaptation through learned tool profiles.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.gate_result import GateResult
from shared.gate_helpers import safe_tool_input

GATE_NAME = "GATE 22: TOOL PROFILE"

try:
    from shared.tool_profiles import (
        load_profiles,
        get_warnings_for_tool,
        get_success_rate,
        PROFILED_TOOLS,
    )

    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False


def check(tool_name, tool_input, state, event_type="PreToolUse"):
    if event_type != "PreToolUse":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if not _AVAILABLE:
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if tool_name not in PROFILED_TOOLS:
        return GateResult(blocked=False, gate_name=GATE_NAME)

    tool_input = safe_tool_input(tool_input)

    try:
        profiles = load_profiles()
        warnings = get_warnings_for_tool(profiles, tool_name, tool_input)

        if not warnings:
            return GateResult(blocked=False, gate_name=GATE_NAME)

        # Format warnings as advisory message (never block)
        warning_text = " | ".join(warnings[:3])  # Cap at 3 warnings
        msg = f"[{GATE_NAME}] ADVISORY: {warning_text}"

        return GateResult(
            blocked=False,
            message=msg,
            gate_name=GATE_NAME,
            severity="warn",
        )
    except Exception:
        # Fail-open: any error = allow
        return GateResult(blocked=False, gate_name=GATE_NAME)
