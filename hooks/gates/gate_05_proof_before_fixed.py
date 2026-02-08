"""Gate 5: PROOF BEFORE FIXED (Tier 2 — Quality)

After editing a file, blocks further edits to OTHER files until the
previous edit has been verified (by running a command, test, or check).

This prevents the pattern where Claude says "fixed" and moves on
without ever verifying the fix actually works.

The pending_verification list is cleared when:
- A Bash command is run (tests, running scripts, curl, etc.)
- Only the specific verified files are cleared
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.gate_result import GateResult

GATE_NAME = "GATE 5: PROOF BEFORE FIXED"

# Max pending verifications before blocking
MAX_UNVERIFIED = 3

# Files exempt by basename
EXEMPT_BASENAMES = {"state.json", "HANDOFF.md", "LIVE_STATE.json", "CLAUDE.md", "__init__.py"}

# Directories exempt by normalized path prefix
EXEMPT_DIRS = [
    os.path.join(os.path.expanduser("~"), ".claude", "hooks"),
    os.path.join(os.path.expanduser("~"), ".claude", "skills"),
]


def is_exempt(file_path):
    if os.path.basename(file_path) in EXEMPT_BASENAMES:
        return True
    norm = os.path.normpath(file_path)
    for d in EXEMPT_DIRS:
        nd = os.path.normpath(d)
        if norm.startswith(nd + os.sep) or norm == nd:
            return True
    return False


def check(tool_name, tool_input, state, event_type="PreToolUse"):
    if event_type != "PreToolUse":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if tool_name not in ("Edit", "Write"):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    file_path = tool_input.get("file_path", "")

    # Check exemptions
    if is_exempt(file_path):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Check pending verifications
    pending = state.get("pending_verification", [])

    # Allow editing the same file that's pending (iterating on a fix)
    pending_other = [p for p in pending if p != file_path]

    if len(pending_other) >= MAX_UNVERIFIED:
        file_list = ", ".join(os.path.basename(p) for p in pending_other[:3])
        return GateResult(
            blocked=True,
            message=f"[{GATE_NAME}] BLOCKED: {len(pending_other)} files with unverified edits ({file_list}). Verify your changes (run tests, execute script, check output) before editing more files.",
            gate_name=GATE_NAME,
        )

    return GateResult(blocked=False, gate_name=GATE_NAME)
