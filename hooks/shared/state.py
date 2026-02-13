"""Shared state management for the enforcer gate system.

State is persisted to per-session JSON files with atomic writes to prevent
corruption. Each Claude Code agent (main or team member) gets its own state file,
keyed by session_id, ensuring parallel agents don't contaminate each other's
gate checks.

File locking (fcntl.flock) is used around state reads and writes to prevent
parallel agents from clobbering each other's state during concurrent access.

State files: ~/.claude/hooks/state_{session_id}.json
Legacy file: ~/.claude/hooks/state.json (cleaned up on boot)

Schema versioning: STATE_VERSION tracks the current schema. On load, old
state files are auto-migrated forward through the migration chain.
"""

import fcntl
import glob
import json
import logging
import os
import time

STATE_DIR = os.path.join(os.path.expanduser("~"), ".claude", "hooks")
MEMORY_TIMESTAMP_FILE = os.path.join(STATE_DIR, ".memory_last_queried")

# Schema version — bump when adding/removing/renaming fields
STATE_VERSION = 2

# Cap lists to prevent unbounded growth
MAX_FILES_READ = 200
MAX_VERIFIED_FIXES = 100
MAX_PENDING_VERIFICATION = 50
MAX_UNLOGGED_ERRORS = 20
MAX_ERROR_PATTERNS = 50
MAX_ACTIVE_BANS = 50
MAX_PENDING_CHAINS = 10

logger = logging.getLogger(__name__)


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
        "_version": STATE_VERSION,
        "files_read": [],
        "memory_last_queried": 0,
        "pending_verification": [],
        "last_test_run": 0,
        "verified_fixes": [],
        "session_start": time.time(),
        "edits_locked": False,
        "tool_call_count": 0,
        "unlogged_errors": [],
        "error_pattern_counts": {},
        "pending_chain_ids": [],
        "current_strategy_id": "",
        "current_error_signature": "",
        "active_bans": [],
        "last_exit_plan_mode": 0,
        # v2 fields
        "error_windows": [],
        "skill_usage": {},
        "recent_skills": [],
        # v2.0.6 fields (gate upgrades)
        "gate6_warn_count": 0,
        "verification_scores": {},
        "successful_strategies": {},
    }


def migrate_v1_to_v2(state):
    """Migrate state from v1 (no _version field) to v2.

    Adds new fields introduced in v2.0.3/v2.0.4 with safe defaults.
    """
    if "error_windows" not in state:
        state["error_windows"] = []
    if "skill_usage" not in state:
        state["skill_usage"] = {}
    if "recent_skills" not in state:
        state["recent_skills"] = []
    if "gate6_warn_count" not in state:
        state["gate6_warn_count"] = 0
    if "verification_scores" not in state:
        state["verification_scores"] = {}
    if "successful_strategies" not in state:
        state["successful_strategies"] = {}

    state["_version"] = 2
    return state


# Migration chain: maps (from_version) -> migration function
_MIGRATIONS = {
    1: migrate_v1_to_v2,
}


def _run_migrations(state):
    """Run the migration chain from current version to STATE_VERSION.

    Returns the migrated state. If any migration fails, logs a warning
    and returns the state as-is with version set to STATE_VERSION.
    """
    version = state.get("_version", 1)
    if version >= STATE_VERSION:
        return state

    while version < STATE_VERSION:
        migrate_fn = _MIGRATIONS.get(version)
        if migrate_fn is None:
            logger.warning("No migration for v%d -> v%d, skipping", version, version + 1)
            version += 1
            continue
        try:
            state = migrate_fn(state)
            version = state.get("_version", version + 1)
        except Exception as e:
            logger.warning("Migration v%d failed: %s", version, e)
            state["_version"] = STATE_VERSION
            break

    return state


def _validate_consistency(state):
    """Validate and fix state consistency after load.

    - Remove duplicates from lists
    - Ensure pending_verification and verified_fixes are disjoint
    - Cap all lists to their MAX_* limits
    Logs warnings for any corrections made.
    """
    corrections = []

    # Deduplicate lists
    for list_key in ("files_read", "pending_verification", "verified_fixes",
                     "unlogged_errors", "pending_chain_ids", "active_bans",
                     "error_windows", "recent_skills"):
        lst = state.get(list_key)
        if isinstance(lst, list):
            # Use dict.fromkeys to preserve order while deduplicating
            # Only works for hashable items; skip unhashable gracefully
            try:
                deduped = list(dict.fromkeys(lst))
                if len(deduped) < len(lst):
                    corrections.append(f"{list_key}: removed {len(lst) - len(deduped)} duplicates")
                    state[list_key] = deduped
            except TypeError:
                pass  # Items not hashable, skip dedup

    # Ensure pending_verification and verified_fixes are disjoint
    pending = set(state.get("pending_verification", []))
    verified = set(state.get("verified_fixes", []))
    overlap = pending & verified
    if overlap:
        # Items that are verified should be removed from pending
        state["pending_verification"] = [p for p in state["pending_verification"] if p not in overlap]
        corrections.append(f"pending_verification: removed {len(overlap)} items already in verified_fixes")

    # Cap all lists to MAX_* limits
    _cap_list(state, "files_read", MAX_FILES_READ, corrections)
    _cap_list(state, "verified_fixes", MAX_VERIFIED_FIXES, corrections)
    _cap_list(state, "pending_verification", MAX_PENDING_VERIFICATION, corrections)
    _cap_list(state, "unlogged_errors", MAX_UNLOGGED_ERRORS, corrections)
    _cap_list(state, "active_bans", MAX_ACTIVE_BANS, corrections)
    _cap_list(state, "pending_chain_ids", MAX_PENDING_CHAINS, corrections)

    # Cap error_pattern_counts dict
    pattern_counts = state.get("error_pattern_counts", {})
    if len(pattern_counts) > MAX_ERROR_PATTERNS:
        sorted_patterns = sorted(pattern_counts.items(), key=lambda x: x[1], reverse=True)
        state["error_pattern_counts"] = dict(sorted_patterns[:MAX_ERROR_PATTERNS])
        corrections.append(f"error_pattern_counts: trimmed from {len(pattern_counts)} to {MAX_ERROR_PATTERNS}")

    # Ensure skill_usage is a dict
    if not isinstance(state.get("skill_usage"), dict):
        state["skill_usage"] = {}
        corrections.append("skill_usage: reset to empty dict (was not a dict)")

    if corrections:
        logger.warning("State consistency corrections: %s", "; ".join(corrections))

    return state


def _cap_list(state, key, max_size, corrections):
    """Cap a list field to max_size, keeping the most recent (tail) entries."""
    lst = state.get(key, [])
    if isinstance(lst, list) and len(lst) > max_size:
        corrections.append(f"{key}: capped from {len(lst)} to {max_size}")
        state[key] = lst[-max_size:]


def load_state(session_id="main"):
    """Load state for a specific session/agent with shared file locking.

    Acquires a shared (read) lock on the state file's lock file to prevent
    reading while a write is in progress. Auto-migrates old schema versions
    and validates consistency.
    """
    state_file = state_file_for(session_id)
    if os.path.exists(state_file):
        lock_path = state_file + ".lock"
        try:
            with open(lock_path, "a+") as lock_fd:
                try:
                    fcntl.flock(lock_fd.fileno(), fcntl.LOCK_SH)
                    with open(state_file) as f:
                        state = json.load(f)
                    # Ensure all expected keys exist (forward compat)
                    for key, val in default_state().items():
                        if key not in state:
                            state[key] = val
                    # Run migrations if needed
                    state = _run_migrations(state)
                    # Validate consistency
                    state = _validate_consistency(state)
                    return state
                except (json.JSONDecodeError, IOError):
                    return default_state()
                finally:
                    fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        except OSError:
            # If we can't acquire the lock, fall back to unlocked read
            try:
                with open(state_file) as f:
                    state = json.load(f)
                for key, val in default_state().items():
                    if key not in state:
                        state[key] = val
                state = _run_migrations(state)
                state = _validate_consistency(state)
                return state
            except (json.JSONDecodeError, IOError):
                return default_state()
    return default_state()


def save_state(state, session_id="main"):
    """Save state for a specific session/agent with atomic write."""
    # Cap lists to prevent unbounded growth
    files_read = state.get("files_read", [])
    if len(files_read) > MAX_FILES_READ:
        state["files_read"] = files_read[-MAX_FILES_READ:]

    verified = state.get("verified_fixes", [])
    if len(verified) > MAX_VERIFIED_FIXES:
        state["verified_fixes"] = verified[-MAX_VERIFIED_FIXES:]

    pending = state.get("pending_verification", [])
    if len(pending) > MAX_PENDING_VERIFICATION:
        state["pending_verification"] = pending[-MAX_PENDING_VERIFICATION:]

    unlogged = state.get("unlogged_errors", [])
    if len(unlogged) > MAX_UNLOGGED_ERRORS:
        state["unlogged_errors"] = unlogged[-MAX_UNLOGGED_ERRORS:]

    # Cap error_pattern_counts dict — keep top N by count
    pattern_counts = state.get("error_pattern_counts", {})
    if len(pattern_counts) > MAX_ERROR_PATTERNS:
        sorted_patterns = sorted(pattern_counts.items(), key=lambda x: x[1], reverse=True)
        state["error_pattern_counts"] = dict(sorted_patterns[:MAX_ERROR_PATTERNS])

    # Cap active_bans list
    bans = state.get("active_bans", [])
    if len(bans) > MAX_ACTIVE_BANS:
        state["active_bans"] = bans[-MAX_ACTIVE_BANS:]

    # Cap pending_chain_ids list
    chains = state.get("pending_chain_ids", [])
    if len(chains) > MAX_PENDING_CHAINS:
        state["pending_chain_ids"] = chains[-MAX_PENDING_CHAINS:]

    # Ensure version is set
    state["_version"] = STATE_VERSION

    state_file = state_file_for(session_id)
    os.makedirs(os.path.dirname(state_file), exist_ok=True)
    lock_path = state_file + ".lock"
    with open(lock_path, "a+") as lock_fd:
        try:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
            tmp = state_file + ".tmp"
            with open(tmp, "w") as f:
                json.dump(state, f, indent=2)
            os.replace(tmp, state_file)
        finally:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)


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
            # Clamp to current time: prevent future timestamps from permanently bypassing gates
            sideband_ts = min(sideband_ts, time.time())
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
    # Remove per-session state files and their lock files
    pattern = os.path.join(STATE_DIR, "state_*.json")
    for f in glob.glob(pattern):
        # Don't remove .tmp files (in-progress writes)
        if not f.endswith(".tmp"):
            try:
                os.remove(f)
            except OSError:
                pass
    # Clean up lock files
    lock_pattern = os.path.join(STATE_DIR, "state_*.json.lock")
    for f in glob.glob(lock_pattern):
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
