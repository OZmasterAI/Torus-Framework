"""Tests for session_end.py — vault session note writing."""

import json
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

from session_end import write_vault_session_note

# Restore after import
_util.load_project_state = _orig_load


def test_framework_session_uses_global_count():
    """Framework sessions use LIVE_STATE session_count."""
    tmpdir = tempfile.mkdtemp()
    vault_dir = os.path.join(tmpdir, "vault", "sessions")
    os.makedirs(vault_dir)

    # Monkey-patch vault path
    import session_end

    orig = session_end.write_vault_session_note.__code__
    # Instead, just call with mocked live_state
    state = {}
    live_state = {"session_count": 42, "project": "torus-framework"}

    # Patch os.path.expanduser temporarily
    _orig_expand = os.path.expanduser
    os.path.expanduser = lambda p: p.replace("~", tmpdir)
    try:
        write_vault_session_note(state, live_state, project_name="torus-framework")
    finally:
        os.path.expanduser = _orig_expand

    files = os.listdir(vault_dir)
    assert len(files) == 1, f"Expected 1 file, got {files}"
    assert "session-042" in files[0], f"Expected session-042 in {files[0]}"
    assert "torus" not in files[0], (
        f"Framework session should not have project suffix: {files[0]}"
    )

    # Check frontmatter
    with open(os.path.join(vault_dir, files[0])) as f:
        content = f.read()
    assert "session_number: 42" in content
    shutil.rmtree(tmpdir)
    print("PASS: framework session uses global count")


def test_project_session_uses_local_count():
    """Project sessions use .claude-state.json session_count."""
    tmpdir = tempfile.mkdtemp()
    vault_dir = os.path.join(tmpdir, "vault", "sessions")
    os.makedirs(vault_dir)
    proj_dir = os.path.join(tmpdir, "project")
    os.makedirs(proj_dir)

    # Mock project state
    _mock_project_states[proj_dir] = {"session_count": 53}

    state = {}
    live_state = {"session_count": 527, "project": "go_sdk_agent"}

    _orig_expand = os.path.expanduser
    _orig_load_proj = _util.load_project_state
    os.path.expanduser = lambda p: p.replace("~", tmpdir)
    _util.load_project_state = _mock_load_project_state
    try:
        write_vault_session_note(
            state,
            live_state,
            project_name="go_sdk_agent",
            project_dir=proj_dir,
        )
    finally:
        os.path.expanduser = _orig_expand
        _util.load_project_state = _orig_load_proj

    files = os.listdir(vault_dir)
    assert len(files) == 1, f"Expected 1 file, got {files}"
    assert "session-053" in files[0], (
        f"Expected session-053 (project-local), got {files[0]}"
    )
    assert "go-sdk-agent" in files[0], f"Expected project suffix in {files[0]}"

    with open(os.path.join(vault_dir, files[0])) as f:
        content = f.read()
    assert "session_number: 53" in content

    del _mock_project_states[proj_dir]
    shutil.rmtree(tmpdir)
    print("PASS: project session uses local count")


def test_collision_safe_skips_existing():
    """If note already exists, skip silently."""
    tmpdir = tempfile.mkdtemp()
    vault_dir = os.path.join(tmpdir, "vault", "sessions")
    os.makedirs(vault_dir)

    state = {}
    live_state = {"session_count": 99}

    _orig_expand = os.path.expanduser
    os.path.expanduser = lambda p: p.replace("~", tmpdir)

    # Write first note
    write_vault_session_note(state, live_state)
    files_before = os.listdir(vault_dir)

    # Write again — should skip
    write_vault_session_note(state, live_state)
    files_after = os.listdir(vault_dir)

    os.path.expanduser = _orig_expand
    assert files_before == files_after, "Second write should be skipped"
    shutil.rmtree(tmpdir)
    print("PASS: collision-safe skip works")


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
