"""Shared utilities for boot sequence."""

import json
import os
import tempfile

CLAUDE_DIR = os.path.join(os.path.expanduser("~"), ".claude")
LIVE_STATE_FILE = os.path.join(CLAUDE_DIR, "LIVE_STATE.json")
PROJECTS_DIR = os.path.join(os.path.expanduser("~"), "projects")
WORKTREES_DIR = os.path.join(os.path.expanduser("~"), "worktrees")
AGENTS_DIR = os.path.join(os.path.expanduser("~"), "agents")
PROJECT_STATE_FILENAME = ".claude-state.json"
SUBPROJECT_MARKER = ".claude-project"

try:
    from shared.ramdisk import get_state_dir as _ramdisk_state_dir

    STATE_DIR = _ramdisk_state_dir()
except ImportError:
    STATE_DIR = os.path.dirname(os.path.dirname(__file__))


def read_file(path):
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        return None


def load_live_state():
    content = read_file(LIVE_STATE_FILE)
    if content:
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {}
    return {}


def detect_project(cwd=None):
    """Detect if cwd is inside ~/projects/<name>/ or ~/worktrees/<name>/<experiment>/.

    Returns (project_name, project_dir, subproject_name, subproject_dir).
    Subproject fields are None when cwd is not inside a marked subproject.
    All four are None when cwd is not under ~/projects/ or ~/worktrees/.

    ~/worktrees/ behaviour: every <experiment> subdir gets automatic state
    isolation (no .claude-project marker required) so worktree sessions never
    share LIVE_STATE.json with the main instance.
    """
    if cwd is None:
        cwd = os.getcwd()
    cwd = os.path.realpath(cwd)

    # --- ~/worktrees/<root>/<experiment>/ ---
    worktrees = os.path.realpath(WORKTREES_DIR)
    if cwd.startswith(worktrees + os.sep):
        rel = cwd[len(worktrees) + 1 :]
        parts = rel.split(os.sep)
        root = parts[0]
        if not root:
            return None, None, None, None
        root_dir = os.path.join(worktrees, root)
        # Any subdir is auto-isolated — no marker needed
        if len(parts) >= 2 and parts[1]:
            exp_name = parts[1]
            exp_dir = os.path.join(root_dir, exp_name)
            return root, root_dir, exp_name, exp_dir
        return root, root_dir, None, None

    # --- ~/agents/<role>/ ---
    agents = os.path.realpath(AGENTS_DIR)
    if cwd.startswith(agents + os.sep):
        rel = cwd[len(agents) + 1 :]
        parts = rel.split(os.sep)
        role = parts[0]
        if not role:
            return None, None, None, None
        role_dir = os.path.join(agents, role)
        return role, role_dir, None, None

    # --- ~/projects/<name>/ ---
    projects = os.path.realpath(PROJECTS_DIR)
    if not cwd.startswith(projects + os.sep):
        return None, None, None, None
    # Extract path components after PROJECTS_DIR
    rel = cwd[len(projects) + 1 :]
    parts = rel.split(os.sep)
    name = parts[0]
    if not name:
        return None, None, None, None
    project_dir = os.path.join(projects, name)
    # Check for subproject: needs 2+ components and marker file
    if len(parts) >= 2 and parts[1]:
        sub_name = parts[1]
        sub_dir = os.path.join(project_dir, sub_name)
        if os.path.isfile(os.path.join(sub_dir, SUBPROJECT_MARKER)):
            return name, project_dir, sub_name, sub_dir
    return name, project_dir, None, None


def load_project_state(project_dir):
    """Read .claude-state.json from project_dir. Returns dict or {}."""
    path = os.path.join(project_dir, PROJECT_STATE_FILENAME)
    content = read_file(path)
    if content:
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {}
    return {}


def save_project_state(project_dir, state):
    """Atomic write of .claude-state.json to project_dir."""
    path = os.path.join(project_dir, PROJECT_STATE_FILENAME)
    fd, tmp = tempfile.mkstemp(dir=project_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def scan_subproject_states(project_dir):
    """Scan project_dir/*/ for subprojects with .claude-project marker.

    Returns list of state dicts from each marked subdir that has a state file.
    """
    results = []
    if not os.path.isdir(project_dir):
        return results
    for entry in sorted(os.listdir(project_dir)):
        sub_dir = os.path.join(project_dir, entry)
        if not os.path.isdir(sub_dir):
            continue
        if not os.path.isfile(os.path.join(sub_dir, SUBPROJECT_MARKER)):
            continue
        state = load_project_state(sub_dir)
        if state:
            state.setdefault("project_name", entry)
            results.append(state)
    return results


def scan_all_project_states():
    """Scan ~/projects/*/.claude-state.json, return list of state dicts."""
    results = []
    if not os.path.isdir(PROJECTS_DIR):
        return results
    for entry in sorted(os.listdir(PROJECTS_DIR)):
        proj_dir = os.path.join(PROJECTS_DIR, entry)
        if not os.path.isdir(proj_dir):
            continue
        state = load_project_state(proj_dir)
        if state:
            state.setdefault("project_name", entry)
            results.append(state)
    return results
