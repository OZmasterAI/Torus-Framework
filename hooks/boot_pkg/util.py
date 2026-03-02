"""Shared utilities for boot sequence."""
import json
import os
import tempfile

CLAUDE_DIR = os.path.join(os.path.expanduser("~"), ".claude")
LIVE_STATE_FILE = os.path.join(CLAUDE_DIR, "LIVE_STATE.json")
PROJECTS_DIR = os.path.join(os.path.expanduser("~"), "projects")
PROJECT_STATE_FILENAME = ".claude-state.json"

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
    """Detect if cwd is inside ~/projects/<name>/.

    Returns (project_name, project_dir) or (None, None).
    """
    if cwd is None:
        cwd = os.getcwd()
    cwd = os.path.realpath(cwd)
    projects = os.path.realpath(PROJECTS_DIR)
    if not cwd.startswith(projects + os.sep):
        return None, None
    # Extract the first path component after PROJECTS_DIR
    rel = cwd[len(projects) + 1:]
    name = rel.split(os.sep)[0]
    if not name:
        return None, None
    return name, os.path.join(projects, name)


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
