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
    ".c", ".cpp", ".rb", ".php", ".sh", ".sql", ".tf", ".ipynb",
}

# Files/patterns always allowed to write without reading
EXEMPT_PATTERNS = [
    "__init__.py",
    "HANDOFF.md",
    "LIVE_STATE.json",
    "CLAUDE.md",
    "state.json",
]


def _stem_normalize(filepath):
    """Extract normalized stem from a filepath for related-read matching.

    Strips test prefixes (test_, test) and test suffixes (_test, _spec, .test, .spec)
    from the basename stem so that 'foo.py' and 'test_foo.py' share the same normalized stem.
    """
    stem = os.path.splitext(os.path.basename(filepath))[0]
    # Strip test prefixes
    for prefix in ("test_", "test"):
        if stem.startswith(prefix):
            stem = stem[len(prefix):]
            break
    # Strip test suffixes
    for suffix in ("_test", "_spec", ".test", ".spec"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    return stem.lower()


def _is_related_read(read_path, edit_path):
    """Return True if read_path is semantically related to edit_path.

    Related means:
    - Same normalized stem (after stripping test prefixes/suffixes)
    - OR same basename in a different directory
    """
    read_base = os.path.basename(read_path)
    edit_base = os.path.basename(edit_path)

    # Same basename in different directory
    if read_base == edit_base:
        return True

    # Same normalized stem (e.g., foo.py ↔ test_foo.py)
    return _stem_normalize(read_path) == _stem_normalize(edit_path)


def check(tool_name, tool_input, state, event_type="PreToolUse"):
    if event_type != "PreToolUse":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if tool_name not in ("Edit", "Write", "NotebookEdit"):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if not isinstance(tool_input, dict):
        tool_input = {}

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

    # Check if file was read this session (resolve symlinks to prevent bypass)
    files_read = state.get("files_read", [])
    file_path_real = os.path.realpath(file_path)
    files_read_real = [os.path.realpath(f) for f in files_read]
    if file_path_real not in files_read_real:
        # Check if any read file is semantically related (e.g., read foo.py → edit test_foo.py)
        for read_file in files_read:
            if _is_related_read(os.path.realpath(read_file), file_path_real):
                return GateResult(blocked=False, gate_name=GATE_NAME)

        return GateResult(
            blocked=True,
            message=f"[{GATE_NAME}] BLOCKED: You must Read '{file_path}' before editing it.",
            gate_name=GATE_NAME,
        )

    return GateResult(blocked=False, gate_name=GATE_NAME)
