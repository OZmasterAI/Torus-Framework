"""Gate 23: REQUIRE TESTS (Tier 2 — Quality)

Blocks Edit/Write on code files if prior code edits in this session
have no corresponding test files also edited.

Tracks its own state key "untested_code_files" — NOT dependent on
pending_verification (which gets cleared by any Bash command).

Code files are added to the tracking list on PostToolUse (after edit succeeds).
Test files written clear matching code files from the list.
PreToolUse blocks if the list has unmatched entries.

Controlled by config.json "require_tests" flag (default: false).
When off, this gate allows everything.

Exemptions:
  - Test files themselves (always allowed — you need to write them)
  - Config/doc files (.md, .json, .yaml, etc.)
  - skills/ directory
  - .state/ directory

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

# State key for in-memory state dict (may not persist between enforcer calls)
STATE_KEY = "untested_code_files"

# File-based persistence (survives between enforcer calls)
_TRACKER_FILE = os.path.join(
    os.path.expanduser("~/.claude"), "hooks", ".untested_code_files.json"
)


def _load_tracker():
    """Load untested code files from disk."""
    try:
        with open(_TRACKER_FILE) as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def _save_tracker(files):
    """Save untested code files to disk."""
    try:
        with open(_TRACKER_FILE, "w") as f:
            json.dump(files, f)
    except OSError:
        pass


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


def _is_code_file(path):
    """True if path is a code file (not exempt, not test, not .state/)."""
    if not path:
        return False
    return not _is_exempt(path) and not _is_test_file(path) and not _is_state_dir(path)


def _match_test_to_code(test_path, code_files):
    """Return list of code files that this test file covers."""
    if not test_path or not code_files:
        return []
    test_base = os.path.basename(test_path).lower()
    matched = []
    for cf in code_files:
        base = os.path.basename(cf)
        name, _ = os.path.splitext(base)
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
        if test_base in candidates:
            matched.append(cf)
    return matched


def _get_unmatched(state):
    """Return list of code files without matching tests."""
    return _load_tracker()


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

    # ── Track test files: clear matching code files from untested list ──
    if _is_test_file(file_path):
        untested = _load_tracker()
        matched = _match_test_to_code(file_path, untested)
        if matched:
            remaining = [f for f in untested if f not in matched]
            _save_tracker(remaining)
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Always allow: exempt files, .state/ files
    if _is_exempt(file_path) or _is_state_dir(file_path):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # ── Check for untested code files from prior edits ──
    untested = _load_tracker()

    if untested:
        names = ", ".join(os.path.basename(f) for f in untested[:3])
        if len(untested) > 3:
            names += f" +{len(untested) - 3} more"
        msg = (
            f"[{GATE_NAME}] BLOCKED: Write tests first for: {names}. "
            f"Edit/create test files for untested code, then retry."
        )
        return GateResult(
            blocked=True, gate_name=GATE_NAME, message=msg, severity="warn"
        )

    # ── Track this code file for next check ──
    if _is_code_file(file_path):
        norm = os.path.normpath(file_path)
        if norm not in untested:
            untested.append(norm)
            _save_tracker(untested)

    return GateResult(blocked=False, gate_name=GATE_NAME)
