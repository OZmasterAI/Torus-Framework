"""Tests for session_end.py — wiki log append."""

import os
import sys
import tempfile
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Mock load_project_state before importing session_end
_mock_project_states = {}


def _mock_load_project_state(project_dir):
    return _mock_project_states.get(project_dir, {})


import boot_pkg.util as _util

_orig_load = _util.load_project_state
_util.load_project_state = _mock_load_project_state

from session_end import append_wiki_log

# Restore after import
_util.load_project_state = _orig_load

LOG_SEED = """---
type: log
last_updated: 2026-04-23
session: 677
---
# Wiki Log

Chronological record of all wiki changes. Append-only.

---

## [2026-04-23] init | wiki — Initialized wiki
"""


def _setup_wiki(tmpdir):
    """Create a minimal wiki with log.md."""
    wiki_dir = os.path.join(tmpdir, "vault", "wiki")
    os.makedirs(wiki_dir)
    log_path = os.path.join(wiki_dir, "log.md")
    with open(log_path, "w") as f:
        f.write(LOG_SEED)
    return log_path


def test_framework_session_appends_to_log():
    """Framework sessions append to wiki/log.md using global session count."""
    tmpdir = tempfile.mkdtemp()
    log_path = _setup_wiki(tmpdir)

    state = {}
    live_state = {
        "session_count": 42,
        "project": "torus-framework",
        "feature": "gate-fixes",
        "what_was_done": "Fixed gate 01 bypass",
    }

    _orig_expand = os.path.expanduser
    os.path.expanduser = lambda p: p.replace("~", tmpdir)
    try:
        append_wiki_log(state, live_state, project_name="torus-framework")
    finally:
        os.path.expanduser = _orig_expand

    with open(log_path) as f:
        content = f.read()
    assert "session 42" in content, f"Expected session 42 in log:\n{content}"
    assert "torus-framework" in content
    assert "gate-fixes" in content
    assert "Fixed gate 01 bypass" in content
    shutil.rmtree(tmpdir)
    print("PASS: framework session appends to wiki log")


def test_project_session_uses_local_count():
    """Project sessions use .claude-state.json session_count."""
    tmpdir = tempfile.mkdtemp()
    log_path = _setup_wiki(tmpdir)
    proj_dir = os.path.join(tmpdir, "project")
    os.makedirs(proj_dir)

    _mock_project_states[proj_dir] = {
        "session_count": 53,
        "feature": "api-work",
        "what_was_done": "Built API endpoints",
    }

    state = {}
    live_state = {"session_count": 527, "project": "go_sdk_agent"}

    _orig_expand = os.path.expanduser
    _orig_load_proj = _util.load_project_state
    os.path.expanduser = lambda p: p.replace("~", tmpdir)
    _util.load_project_state = _mock_load_project_state
    try:
        append_wiki_log(
            state,
            live_state,
            project_name="go_sdk_agent",
            project_dir=proj_dir,
        )
    finally:
        os.path.expanduser = _orig_expand
        _util.load_project_state = _orig_load_proj

    with open(log_path) as f:
        content = f.read()
    assert "session 53" in content, f"Expected session 53 (local count):\n{content}"
    assert "go_sdk_agent" in content

    del _mock_project_states[proj_dir]
    shutil.rmtree(tmpdir)
    print("PASS: project session uses local count in wiki log")


def test_collision_safe_skips_duplicate():
    """If session already in log, skip silently."""
    tmpdir = tempfile.mkdtemp()
    log_path = _setup_wiki(tmpdir)

    state = {}
    live_state = {"session_count": 99, "project": "test", "what_was_done": "Testing"}

    _orig_expand = os.path.expanduser
    os.path.expanduser = lambda p: p.replace("~", tmpdir)

    append_wiki_log(state, live_state)
    with open(log_path) as f:
        content_after_first = f.read()

    append_wiki_log(state, live_state)
    with open(log_path) as f:
        content_after_second = f.read()

    os.path.expanduser = _orig_expand
    assert content_after_first == content_after_second, "Second write should be skipped"
    shutil.rmtree(tmpdir)
    print("PASS: collision-safe skip works for wiki log")


def test_no_wiki_skips_silently():
    """If wiki/log.md doesn't exist, skip without error."""
    tmpdir = tempfile.mkdtemp()

    state = {}
    live_state = {"session_count": 1, "project": "test"}

    _orig_expand = os.path.expanduser
    os.path.expanduser = lambda p: p.replace("~", tmpdir)
    try:
        append_wiki_log(state, live_state)
    finally:
        os.path.expanduser = _orig_expand

    shutil.rmtree(tmpdir)
    print("PASS: missing wiki skips silently")


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except Exception as e:
                print(f"FAIL: {name}: {e}")
                failed += 1
    sys.exit(1 if failed else 0)
