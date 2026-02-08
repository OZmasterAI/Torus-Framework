"""Shared state management for the enforcer gate system.

State is persisted to per-session JSON files with atomic writes to prevent
corruption. Each Claude Code agent (main or team member) gets its own state file,
keyed by session_id, ensuring parallel agents don't contaminate each other's
gate checks.

State files: ~/.claude/hooks/state_{session_id}.json
Legacy file: ~/.claude/hooks/state.json (cleaned up on boot)
"""

import glob
import json
import os
import time

STATE_DIR = os.path.join(os.path.expanduser("~"), ".claude", "hooks")
MEMORY_TIMESTAMP_FILE = os.path.join(STATE_DIR, ".memory_last_queried")

# Cap files_read to prevent unbounded growth (W4 fix)
MAX_FILES_READ = 200


def state_file_for(session_id="main"):
    """Get the state file path for a specific session/agent.

    Each Claude Code session (main agent or team member) gets its own state file.
    This prevents parallel agents from overwriting each other's state.
    """
    # Sanitize session_id for use in filenames
    safe_id = "".join(c for c in str(session_id) if c.isalnum() or c in "-_")
    if not safe_id:
        safe_id = "main"
    return os.path.join(STATE_DIR, f"state_{safe_id}.json")


def default_state():
    return {
        "files_read": [],
        "memory_last_queried": 0,
        "pending_verification": [],
        "last_test_run": 0,
        "verified_fixes": [],
        "session_start": time.time(),
        "edits_locked": False,
        "tool_call_count": 0,
    }


def load_state(session_id="main"):
    """Load state for a specific session/agent."""
    state_file = state_file_for(session_id)
    if os.path.exists(state_file):
        try:
            with open(state_file) as f:
                state = json.load(f)
            # Ensure all expected keys exist (forward compat)
            for key, val in default_state().items():
                if key not in state:
                    state[key] = val
            return state
        except (json.JSONDecodeError, IOError):
            return default_state()
    return default_state()


def save_state(state, session_id="main"):
    """Save state for a specific session/agent with atomic write."""
    # Cap files_read to prevent unbounded growth (W4 fix)
    files_read = state.get("files_read", [])
    if len(files_read) > MAX_FILES_READ:
        state["files_read"] = files_read[-MAX_FILES_READ:]

    state_file = state_file_for(session_id)
    os.makedirs(os.path.dirname(state_file), exist_ok=True)
    tmp = state_file + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, state_file)


def get_memory_last_queried(state):
    """Get the most recent memory query timestamp.

    For team members (session_id != "main"), only the per-agent enforcer
    timestamp is used. This prevents the global sideband file (written by
    the MCP server) from letting one agent's memory query satisfy Gate 4
    for a different agent.

    For the main agent, both the enforcer state and the sideband file are
    checked for backward compatibility.
    """
    enforcer_ts = state.get("memory_last_queried", 0)

    # Team members use only their own per-agent state (no sideband leakage)
    session_id = state.get("_session_id", "main")
    if session_id != "main":
        return enforcer_ts

    # Main agent also checks sideband (backward compat)
    sideband_ts = 0
    try:
        if os.path.exists(MEMORY_TIMESTAMP_FILE):
            with open(MEMORY_TIMESTAMP_FILE) as f:
                data = json.load(f)
            sideband_ts = data.get("timestamp", 0)
    except (json.JSONDecodeError, IOError, OSError):
        pass
    return max(enforcer_ts, sideband_ts)


def reset_state(session_id="main"):
    """Reset state for a specific session/agent."""
    save_state(default_state(), session_id=session_id)


def cleanup_all_states():
    """Remove all session state files. Called by boot.py on session start.

    Cleans up both per-session state files (state_*.json) and the legacy
    shared state file (state.json) from previous sessions.
    """
    # Remove per-session state files
    pattern = os.path.join(STATE_DIR, "state_*.json")
    for f in glob.glob(pattern):
        # Don't remove .tmp files (in-progress writes)
        if not f.endswith(".tmp"):
            try:
                os.remove(f)
            except OSError:
                pass

    # Remove legacy shared state file
    legacy = os.path.join(STATE_DIR, "state.json")
    if os.path.exists(legacy):
        try:
            os.remove(legacy)
        except OSError:
            pass
