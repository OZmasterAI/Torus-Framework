"""Gate 1: READ BEFORE EDIT (Tier 1 — Safety)

Blocks Edit/Write to .py files unless the file has been Read first in this session.
This prevents blind edits to code files, which is the #1 source of regressions.

Exceptions:
  - New files (file_path doesn't exist yet) are allowed for Write
  - Non-.py files are allowed (config, markdown, etc.)
  - __init__.py files that are empty are allowed
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.gate_result import GateResult

GATE_NAME = "GATE 1: READ BEFORE EDIT"

# File extensions that require read-before-edit
GUARDED_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".rs", ".go", ".java",
    ".c", ".cpp", ".rb", ".php", ".sh", ".sql", ".tf",
}

# Files/patterns always allowed to write without reading
EXEMPT_PATTERNS = [
    "__init__.py",
    "HANDOFF.md",
    "LIVE_STATE.json",
    "CLAUDE.md",
    "state.json",
]


def check(tool_name, tool_input, state, event_type="PreToolUse"):
    if event_type != "PreToolUse":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if tool_name not in ("Edit", "Write", "NotebookEdit"):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    file_path = tool_input.get("file_path", "") or tool_input.get("notebook_path", "")
    file_path = os.path.normpath(file_path)
    _, ext = os.path.splitext(file_path)
    ext = ext.lower()

    # Only guard specific extensions
    if ext not in GUARDED_EXTENSIONS:
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Check exemptions (exact basename match to prevent substring bypass)
    basename = os.path.basename(file_path)
    if basename in EXEMPT_PATTERNS:
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # New files are allowed for Write (creating from scratch)
    if tool_name == "Write" and not os.path.exists(file_path):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Check if file was read this session
    files_read = state.get("files_read", [])
    if file_path not in files_read:
        return GateResult(
            blocked=True,
            message=f"[{GATE_NAME}] BLOCKED: You must Read '{file_path}' before editing it.",
            gate_name=GATE_NAME,
        )

    return GateResult(blocked=False, gate_name=GATE_NAME)
