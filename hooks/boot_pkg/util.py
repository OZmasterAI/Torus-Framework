"""Shared utilities for boot sequence."""
import fcntl
import json
import os

CLAUDE_DIR = os.path.join(os.path.expanduser("~"), ".claude")
LIVE_STATE_FILE = os.path.join(CLAUDE_DIR, "LIVE_STATE.json")
LIVE_STATE_LOCK = LIVE_STATE_FILE + ".lock"

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


def update_live_state(updates):
    """Atomically update fields in LIVE_STATE.json under file lock.

    All writers to LIVE_STATE.json MUST use this function to prevent
    concurrent read-modify-write races (e.g., session_end clobbering
    session_count that boot just incremented).

    Args:
        updates: dict of fields to merge into the current state.

    Returns the full state dict after update.
    """
    os.makedirs(os.path.dirname(LIVE_STATE_FILE), exist_ok=True)
    with open(LIVE_STATE_LOCK, "w") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            state = load_live_state()
            state.update(updates)
            tmp = LIVE_STATE_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(state, f, indent=2)
                f.write("\n")
            os.replace(tmp, LIVE_STATE_FILE)
            return state
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)


def increment_session_count():
    """Atomically increment session_count in LIVE_STATE.json using file locking.

    Returns the new session number. Concurrent calls from different processes
    will serialize via fcntl.LOCK_EX, so each session gets a unique number.
    """
    os.makedirs(os.path.dirname(LIVE_STATE_FILE), exist_ok=True)
    with open(LIVE_STATE_LOCK, "w") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            state = load_live_state()
            state["session_count"] = state.get("session_count", 0) + 1
            tmp = LIVE_STATE_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(state, f, indent=2)
                f.write("\n")
            os.replace(tmp, LIVE_STATE_FILE)
            return state["session_count"]
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
