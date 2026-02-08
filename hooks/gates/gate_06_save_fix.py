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

GATE_NAME = "GATE 6: SAVE VERIFIED FIX"

# How many unsaved verified fixes before we warn (not block)
WARN_THRESHOLD = 2


def check(tool_name, tool_input, state, event_type="PreToolUse"):
    """This gate only warns, never blocks. It prints to stderr as advisory."""
    if event_type != "PreToolUse":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if tool_name not in ("Edit", "Write", "Task"):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    verified_fixes = state.get("verified_fixes", [])
    if len(verified_fixes) >= WARN_THRESHOLD:
        fix_list = ", ".join(os.path.basename(f) for f in verified_fixes[:3])
        # Print warning but don't block
        print(
            f"[{GATE_NAME}] WARNING: {len(verified_fixes)} verified fixes not saved to memory ({fix_list}). "
            f"Consider using remember_this() to save what you learned.",
            file=sys.stderr,
        )

    return GateResult(blocked=False, gate_name=GATE_NAME)
