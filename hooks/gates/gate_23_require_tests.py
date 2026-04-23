"""Gate 23: REQUIRE TESTS (Tier 2 — Quality)

Blocks Edit/Write on code files if prior code edits in this session
have no corresponding test files (on disk or recently edited).

Uses file-based tracker (.untested_code_files.json) — NOT dependent on
pending_verification (which gets cleared by any Bash command).

On PreToolUse:
  - If editing a test file: clear matching code files from tracker, allow.
  - If editing a code file: check tracker for untested files, block if any.
    Then check if THIS code file has a test on disk — if not, track it.
  - Files with existing tests on disk are never tracked or blocked.

Controlled by config.json "require_tests" flag (default: false).

Exemptions:
  - Test files themselves (always allowed — you need to write them)
  - Config/doc files (.md, .json, .yaml, etc.)
  - skills/ directory, .state/ directory
  - Code files that already have a matching test file on disk

Tier 2 (non-safety): gate crash = warn + continue, not block.
"""

import json
import os
import re
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

STATE_KEY = "untested_code_files"

_TRACKER_DIR = os.path.expanduser("~/.claude/hooks")
_TRACKER_FILE = os.path.join(_TRACKER_DIR, ".untested_code_files.json")  # legacy


def _tracker_path(session_id=None):
    """Return per-session tracker path, or legacy shared path."""
    if session_id:
        safe_id = "".join(c for c in str(session_id) if c.isalnum() or c in "-_")[:8]
        return os.path.join(_TRACKER_DIR, f".untested_code_files_{safe_id}.json")
    return _TRACKER_FILE


def _load_tracker(session_id=None):
    """Load untested code files from disk."""
    try:
        with open(_tracker_path(session_id)) as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def _save_tracker(files, session_id=None):
    """Save untested code files to disk."""
    try:
        with open(_tracker_path(session_id), "w") as f:
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


def _test_candidates(code_path):
    """Return list of possible test file names for a code file."""
    base = os.path.basename(code_path)
    name, _ = os.path.splitext(base)
    return [
        f"test_{base}",
        f"test_{name}.py",
        f"{name}_test.py",
        f"{name}_test.go",
        f"{name}.test.ts",
        f"{name}.test.js",
        f"{name}.spec.ts",
        f"{name}.spec.js",
    ]


def _test_search_dirs(code_path):
    """Return directories to search for test files."""
    code_dir = os.path.dirname(code_path)
    parent = os.path.dirname(code_dir)
    dirs = [code_dir]
    for td in ("tests", "test", "__tests__"):
        dirs.append(os.path.join(code_dir, td))
        dirs.append(os.path.join(parent, td))
    return dirs


_TEST_FUNC_PATTERNS = [
    re.compile(r"def test_"),  # Python
    re.compile(r"func Test"),  # Go
    re.compile(r"\bit\("),  # JS/TS mocha/jest
    re.compile(r"\bdescribe\("),  # JS/TS
    re.compile(r"\btest\("),  # Jest
    re.compile(r"#\[test\]"),  # Rust
    re.compile(r"@Test"),  # Java/Kotlin
]
_HEAD_LINES = 80


def _has_real_tests(path):
    """Check if a test file contains at least one actual test function."""
    try:
        with open(path) as f:
            head = "".join(f.readline() for _ in range(_HEAD_LINES))
        return any(pat.search(head) for pat in _TEST_FUNC_PATTERNS)
    except OSError:
        return False


def _has_test_on_disk(code_path):
    """Check if a matching test file with real tests exists on disk."""
    if not code_path:
        return False
    candidates = _test_candidates(code_path)
    for search_dir in _test_search_dirs(code_path):
        for c in candidates:
            full = os.path.join(search_dir, c)
            if os.path.exists(full) and _has_real_tests(full):
                return True
    return False


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
    sid = state.get("_session_id")

    # ── Track test files: clear matching code files from tracker ──
    if _is_test_file(file_path):
        untested = _load_tracker(sid)
        matched = _match_test_to_code(file_path, untested)
        if matched:
            remaining = [f for f in untested if f not in matched]
            _save_tracker(remaining, sid)
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Always allow: exempt files, .state/ files
    if _is_exempt(file_path) or _is_state_dir(file_path):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # ── Filter tracker: remove deleted files and files that now have tests ──
    untested = _load_tracker(sid)
    filtered = [f for f in untested if os.path.exists(f) and not _has_test_on_disk(f)]
    if len(filtered) != len(untested):
        _save_tracker(filtered, sid)
        untested = filtered

    # ── Block code edits if untested files exist in the SAME directory ──
    edit_dir = os.path.dirname(os.path.normpath(file_path)) if file_path else ""
    same_dir = [f for f in untested if os.path.dirname(f) == edit_dir]
    if same_dir:
        names = ", ".join(os.path.basename(f) for f in same_dir[:3])
        if len(same_dir) > 3:
            names += f" +{len(same_dir) - 3} more"
        msg = (
            f"[{GATE_NAME}] BLOCKED: Write tests first for: {names}. "
            f"Edit/create test files for untested code, then retry."
        )
        return GateResult(
            blocked=True, gate_name=GATE_NAME, message=msg, severity="warn"
        )

    # ── Track this code file (only if no test exists on disk) ──
    if _is_code_file(file_path) and not _has_test_on_disk(file_path):
        norm = os.path.normpath(file_path)
        if norm not in untested:
            untested.append(norm)
            _save_tracker(untested, sid)

    return GateResult(blocked=False, gate_name=GATE_NAME)
