"""Gate 23: REQUIRE TESTS (Tier 2 — Quality)

Blocks Edit/Write on code files if prior code edits in this session
have no corresponding test files also edited.

Controlled by config.json "require_tests" flag (default: false).
When off, this gate allows everything.

Exemptions:
  - Test files themselves (always allowed — you need to write them)
  - Config/doc files (.md, .json, .yaml, etc.)
  - skills/ directory
  - .state/ directory
  - Re-edits of files already in pending_verification

Tier 2 (non-safety): gate crash = warn + continue, not block.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.gate_result import GateResult
from shared.gate_helpers import extract_file_path, safe_tool_input
from shared.exemptions import is_exempt_full as _is_exempt
from shared.exemptions import STANDARD_EXEMPT_PATTERNS as _TEST_PATTERNS

GATE_NAME = "GATE 23: REQUIRE TESTS"
WATCHED_TOOLS = {"Edit", "Write", "NotebookEdit"}
CONFIG_FILE = os.path.join(os.path.expanduser("~/.claude"), "config.json")
STATE_DIR = os.path.join(os.path.expanduser("~/.claude"), "hooks", ".state")


def _load_config():
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _is_test_file(path):
    if not path:
        return False
    lower = os.path.basename(path).lower()
    return any(pat in lower for pat in _TEST_PATTERNS)


def _is_state_dir(path):
    if not path:
        return False
    norm = os.path.normpath(path)
    state_norm = os.path.normpath(STATE_DIR)
    return norm.startswith(state_norm + os.sep) or norm == state_norm


def _code_files_without_tests(pending):
    """Return list of code files in pending that have no matching test file."""
    code_files = []
    test_basenames = set()
    for f in pending:
        if _is_test_file(f):
            test_basenames.add(os.path.basename(f).lower())
        elif not _is_exempt(f) and not _is_state_dir(f):
            code_files.append(f)

    unmatched = []
    for cf in code_files:
        base = os.path.basename(cf)
        name, _ = os.path.splitext(base)
        # Check common test naming patterns
        candidates = {
            f"test_{base}".lower(),
            f"test_{name}.py".lower(),
            f"{name}_test.py".lower(),
            f"{name}_test.go".lower(),
            f"{name}.test.ts".lower(),
            f"{name}.test.js".lower(),
            f"{name}.spec.ts".lower(),
            f"{name}.spec.js".lower(),
        }
        if not candidates & test_basenames:
            unmatched.append(cf)
    return unmatched


def check(tool_name, tool_input, state, event_type="PreToolUse"):
    if event_type != "PreToolUse":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if tool_name not in WATCHED_TOOLS:
        return GateResult(blocked=False, gate_name=GATE_NAME)

    cfg = _load_config()
    if not cfg.get("require_tests", False):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    tool_input = safe_tool_input(tool_input)
    file_path = extract_file_path(tool_input)

    # Always allow: exempt files, test files, .state/ files
    if _is_exempt(file_path) or _is_test_file(file_path) or _is_state_dir(file_path):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Check pending_verification for untested code files
    pending = state.get("pending_verification", [])
    unmatched = _code_files_without_tests(pending)

    if not unmatched:
        return GateResult(blocked=False, gate_name=GATE_NAME)

    names = ", ".join(os.path.basename(f) for f in unmatched[:3])
    if len(unmatched) > 3:
        names += f" +{len(unmatched) - 3} more"
    msg = (
        f"[{GATE_NAME}] BLOCKED: Write tests first for: {names}. "
        f"Edit/create test files for untested code, then retry."
    )
    return GateResult(blocked=True, gate_name=GATE_NAME, message=msg, severity="warn")
