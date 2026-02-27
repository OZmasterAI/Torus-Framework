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

_DISK_STATE_DIR = os.path.join(os.path.expanduser("~"), ".claude", "hooks")

try:
    from shared.ramdisk import get_state_dir, is_ramdisk_available
    STATE_DIR = get_state_dir()
except ImportError:
    STATE_DIR = _DISK_STATE_DIR

# Memory timestamp sideband always lives on disk (read by gate_04, written by boot.py)
MEMORY_TIMESTAMP_FILE = os.path.join(_DISK_STATE_DIR, ".memory_last_queried")

# Schema version — bump when adding/removing/renaming fields
STATE_VERSION = 3

# Cap lists to prevent unbounded growth
MAX_FILES_READ = 200
MAX_VERIFIED_FIXES = 100
MAX_PENDING_VERIFICATION = 50
MAX_UNLOGGED_ERRORS = 20
MAX_ERROR_PATTERNS = 50
MAX_ACTIVE_BANS = 50
MAX_PENDING_CHAINS = 10
MAX_EDIT_STREAK = 50
MAX_GATE_BLOCK_OUTCOMES = 100

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


def _sideband_path_for(session_id="main"):
    """Sideband file path for enforcer mutations (ramdisk, same dir as state)."""
    safe_id = "".join(c for c in str(session_id) if c.isalnum() or c in "-_")
    if not safe_id:
        safe_id = "main"
    return os.path.join(STATE_DIR, f".enforcer_sideband_{safe_id}.json")


def write_enforcer_sideband(state, session_id="main"):
    """Write enforcer state to sideband file (ramdisk, atomic)."""
    sideband_file = _sideband_path_for(session_id)
    os.makedirs(os.path.dirname(sideband_file), exist_ok=True)
    tmp = sideband_file + f".tmp.{os.getpid()}"
    try:
        with open(tmp, "w") as f:
            json.dump(state, f)
        os.replace(tmp, sideband_file)
    except OSError:
        # Fail-open: if sideband write fails, mutations are lost but framework continues
        try:
            os.unlink(tmp)
        except OSError:
            pass


def read_enforcer_sideband(session_id="main"):
    """Read sideband file. Returns dict or None if no sideband exists."""
    sideband_file = _sideband_path_for(session_id)
    try:
        with open(sideband_file) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def delete_enforcer_sideband(session_id="main"):
    """Delete sideband file after tracker promotes to disk state."""
    sideband_file = _sideband_path_for(session_id)
    try:
        os.unlink(sideband_file)
    except OSError:
        pass  # Already deleted or never existed


def default_state():
    return {
        "_version": STATE_VERSION,
        "files_read": [],
        "memory_last_queried": 0,
        "pending_verification": [],
        "last_test_run": 0,
        "verified_fixes": [],
        "session_start": time.time(),
        # edits_locked: removed in refactor1 (never read by any gate)
        "tool_call_count": 0,
        "unlogged_errors": [],
        "error_pattern_counts": {},
        "pending_chain_ids": [],
        "current_strategy_id": "",
        "current_error_signature": "",
        "active_bans": {},
        "last_exit_plan_mode": 0,
        # v2 fields
        "error_windows": [],
        "skill_usage": {},
        "recent_skills": [],
        # v2.0.6 fields (gate upgrades)
        "gate6_warn_count": 0,
        "verification_scores": {},
        "successful_strategies": {},
        # v2.1.9 fields (enhanced tracking)
        "tool_stats": {},           # Per-tool call counts {tool_name: {"count": N}}
        "edit_streak": {},          # Consecutive edits per file without verification
        "last_test_exit_code": None,  # Exit code from most recent test run
        "gate_timing_stats": {},    # Per-gate timing: {gate_name: {count, total_ms, min_ms, max_ms}}
        "rate_window_timestamps": [],  # Rolling window of tool call timestamps for Gate 11
        "tool_call_counts": {},     # Per-tool call counts
        "total_tool_calls": 0,      # Total tool calls this session
        # v2.4.2 fields (subagent visibility)
        "active_subagents": [],     # Currently running: [{agent_id, agent_type, transcript_path, start_ts}]
        "subagent_total_tokens": 0, # Cumulative tokens from completed subagents
        "subagent_history": [],     # Completed: [{agent_id, agent_type, tokens, duration_s}]
        # v2.4.2 fields (confidence gate)
        "session_test_baseline": False,  # Has any test been run this session?
        # confidence_warnings: removed in refactor1 (replaced by confidence_warnings_per_file)
        # v3 fields (causal chain enforcement)
        "recent_test_failure": None,     # {pattern, timestamp, command} when tests fail; None when passing
        "fix_history_queried": 0,        # Timestamp of last query_fix_history call
        "fixing_error": False,           # True when actively fixing a detected error
        # v3 fields (code quality gate)
        "code_quality_warnings_per_file": {},  # Gate 16: {filepath: warn_count}
        # v3 fields (previously undocumented — used by gates/tracker via .get() defaults)
        "gate4_exemptions": {},              # Gate 4: {filename: count} exempt files from memory-first check
        "model_agent_usage": {},            # Gate 10: {agent_type: usage_count}
        # gate12_warn_count: removed in refactor1 (Gate 12 merged into Gate 6)
        "confidence_warnings_per_file": {}, # Gate 14: {filepath: warn_count}
        "confidence_warned_signals": [],    # Gate 14: signals already warned this session
        "verification_timestamps": {},      # Gate 6: {filepath: last_verified_ts}
        "last_test_command": "",            # Gate 3: last test command run (hint display)
        "files_edited": [],                 # tracker: files edited this session
        "session_duration_nudge_hour": 0,   # tracker: last milestone hour nudged (1/2/3)
        "auto_remember_count": 0,           # tracker: auto-remember calls this session
        # v3.1 fields (self-evolving framework)
        "gate_effectiveness": {},            # {gate_name: {blocks: N, overrides: N, prevented: N}}
        "gate_block_outcomes": [],           # [{gate, tool, file, timestamp, resolved_by}] capped at 100
        "session_token_estimate": 0,         # Estimated total tokens this session
        "gate_tune_overrides": {},           # {gate_name: {param: value}} — written by boot.py auto-tune
        # v3.2 fields (error recovery — deferred items)
        "deferred_items": [],               # [{strategy, error_signature, fail_count, file, deferred_at}] capped at 50
        # v3.3 fields (security profiles)
        "security_profile": "balanced",     # Active risk profile: "strict" | "balanced" | "permissive"
        # v3.4 fields (mentor system — A+B+D+E)
        "mentor_last_verdict": "proceed",        # Last mentor verdict: "proceed"|"advise"|"warn"|"escalate"
        "mentor_last_score": 1.0,                # Weighted signal score 0.0-1.0 (1.0 = healthy)
        "mentor_escalation_count": 0,            # Consecutive escalations (resets on proceed/advise)
        "mentor_signals": [],                    # Recent Signal list from last evaluation
        "mentor_warned_this_cycle": False,       # Prevents duplicate warnings in same PostToolUse
        # v3.4 fields (analytics awareness — Upgrades C+F)
        "analytics_last_used": {},              # {tool_name: timestamp} per analytics MCP tool
        "analytics_last_queried": 0,            # Timestamp of last any mcp__analytics__ call
        "analytics_warn_count": 0,              # Gate 6 F-track: separate counter, threshold 15
        "mentor_chain_pattern": "",              # Detected chain pattern: "churn"|"stuck"|"healthy"|""
        "mentor_chain_score": 1.0,               # Outcome chain score 0.0-1.0
        "mentor_memory_match": None,             # Historical match from memory mentor (dict or None)
        "mentor_historical_context": "",         # Human-readable historical context string
        # v3.5 fields (domain mastery)
        "active_domain": "",                       # Currently active domain name (or empty)
    }


def get_state_schema():
    """Return structured schema metadata for all state fields.

    Returns a dict mapping field names to their metadata:
    {field_name: {"type": str, "description": str, "category": str}}

    Used by dashboard for state visualization and documentation.
    """
    return {
        "_version": {"type": "int", "description": "State schema version", "category": "meta"},
        "files_read": {"type": "list", "description": "Recently read file paths", "category": "gate1", "max_size": MAX_FILES_READ},
        "memory_last_queried": {"type": "float", "description": "Timestamp of last memory query", "category": "gate4"},
        "pending_verification": {"type": "list", "description": "Files with unverified edits", "category": "gate5", "max_size": MAX_PENDING_VERIFICATION},
        "last_test_run": {"type": "float", "description": "Timestamp of last test run", "category": "gate3"},
        "verified_fixes": {"type": "list", "description": "Files with verified fixes", "category": "gate6", "max_size": MAX_VERIFIED_FIXES},
        "session_start": {"type": "float", "description": "Session start timestamp", "category": "session"},
        # edits_locked: removed in refactor1
        "tool_call_count": {"type": "int", "description": "Total tool calls this session", "category": "metrics"},
        "unlogged_errors": {"type": "list", "description": "Errors not saved to memory", "category": "gate6", "max_size": MAX_UNLOGGED_ERRORS},
        "error_pattern_counts": {"type": "dict", "description": "Error pattern frequencies", "category": "gate6", "max_size": MAX_ERROR_PATTERNS},
        "pending_chain_ids": {"type": "list", "description": "Causal chains awaiting outcome", "category": "causal", "max_size": MAX_PENDING_CHAINS},
        "current_strategy_id": {"type": "str", "description": "Active fix strategy ID", "category": "causal"},
        "current_error_signature": {"type": "str", "description": "Active error signature hash", "category": "causal"},
        "active_bans": {"type": "dict", "description": "Banned strategy IDs: {id: {fail_count, first_failed, last_failed}}", "category": "gate9", "max_size": MAX_ACTIVE_BANS},
        "last_exit_plan_mode": {"type": "float", "description": "Timestamp of last plan mode exit", "category": "gate6"},
        "error_windows": {"type": "list", "description": "Time-windowed error tracking", "category": "gate6"},
        "skill_usage": {"type": "dict", "description": "Skill invocation counts", "category": "skills"},
        "recent_skills": {"type": "list", "description": "Recently used skills", "category": "skills"},
        "gate6_warn_count": {"type": "int", "description": "Gate 6 warning escalation counter", "category": "gate6"},
        "verification_scores": {"type": "dict", "description": "Partial verification scores per file", "category": "gate5"},
        "successful_strategies": {"type": "dict", "description": "Strategy success counts", "category": "gate9"},
        "tool_stats": {"type": "dict", "description": "Per-tool call statistics", "category": "metrics"},
        "edit_streak": {"type": "dict", "description": "Consecutive edits per file without verification", "category": "gate5", "max_size": MAX_EDIT_STREAK},
        "last_test_exit_code": {"type": "int", "description": "Exit code from most recent test", "category": "gate3"},
        "gate_timing_stats": {"type": "dict", "description": "Per-gate timing metrics", "category": "metrics"},
        "rate_window_timestamps": {"type": "list", "description": "Rolling window for rate limiting", "category": "gate11"},
        "tool_call_counts": {"type": "dict", "description": "Per-tool call counts", "category": "metrics"},
        "total_tool_calls": {"type": "int", "description": "Total tool calls this session", "category": "metrics"},
        "active_subagents": {"type": "list", "description": "Currently running subagents", "category": "subagents"},
        "subagent_total_tokens": {"type": "int", "description": "Cumulative tokens from completed subagents", "category": "subagents"},
        "subagent_history": {"type": "list", "description": "Completed subagent records", "category": "subagents"},
        "session_test_baseline": {"type": "bool", "description": "Whether any test has been run this session", "category": "gate14"},
        # confidence_warnings: removed in refactor1 (replaced by confidence_warnings_per_file)
        "recent_test_failure": {"type": "dict", "description": "Error info from most recent test failure", "category": "gate15"},
        "fix_history_queried": {"type": "float", "description": "Timestamp of last query_fix_history call", "category": "gate15"},
        "fixing_error": {"type": "bool", "description": "Whether actively fixing a detected error", "category": "gate15"},
        "code_quality_warnings_per_file": {"type": "dict", "description": "Per-file code quality warning counter", "category": "gate16"},
        # v3 fields (previously undocumented)
        "gate4_exemptions": {"type": "dict", "description": "Exempt files from memory-first check: {filename: count}", "category": "gate4"},
        "model_agent_usage": {"type": "dict", "description": "Agent type usage counts for model enforcement", "category": "gate10"},
        # gate12_warn_count: removed in refactor1 (Gate 12 merged into Gate 6)
        "confidence_warnings_per_file": {"type": "dict", "description": "Per-file confidence warning counts", "category": "gate14"},
        "confidence_warned_signals": {"type": "list", "description": "Signals already warned this session by Gate 14", "category": "gate14"},
        "verification_timestamps": {"type": "dict", "description": "Last verified timestamp per file", "category": "gate6"},
        "last_test_command": {"type": "str", "description": "Last test command run (shown in Gate 3 hints)", "category": "gate3"},
        "files_edited": {"type": "list", "description": "Files edited this session (tracker)", "category": "metrics"},
        "session_duration_nudge_hour": {"type": "int", "description": "Last session-length milestone hour nudged (1/2/3)", "category": "metrics"},
        "auto_remember_count": {"type": "int", "description": "Auto-remember calls made this session", "category": "metrics"},
        # v3.1 fields (self-evolving framework)
        "gate_effectiveness": {"type": "dict", "description": "Per-gate effectiveness tracking: {gate: {blocks, overrides, prevented}}", "category": "evolve"},
        "gate_block_outcomes": {"type": "list", "description": "Recent gate block outcomes for effectiveness analysis", "category": "evolve", "max_size": MAX_GATE_BLOCK_OUTCOMES},
        "session_token_estimate": {"type": "int", "description": "Estimated total tokens consumed this session", "category": "evolve"},
        "gate_tune_overrides": {"type": "dict", "description": "Auto-tune threshold overrides per gate: {gate: {param: value}}", "category": "evolve"},
        # v3.2 fields (error recovery — deferred items)
        "deferred_items": {"type": "list", "description": "Deferred error recovery items: [{strategy, error_signature, fail_count, file, deferred_at}]", "category": "causal", "max_size": 50},
        # v3.3 fields (security profiles)
        "security_profile": {"type": "str", "description": "Active security risk profile: strict | balanced | permissive", "category": "security"},
        # v3.4 fields (mentor system)
        "mentor_last_verdict": {"type": "str", "description": "Last mentor verdict: proceed|advise|warn|escalate", "category": "mentor"},
        "mentor_last_score": {"type": "float", "description": "Weighted mentor signal score 0.0-1.0", "category": "mentor"},
        "mentor_escalation_count": {"type": "int", "description": "Consecutive escalation count (resets on proceed/advise)", "category": "mentor"},
        "mentor_signals": {"type": "list", "description": "Recent signals from last mentor evaluation", "category": "mentor"},
        "mentor_warned_this_cycle": {"type": "bool", "description": "Whether mentor warned in current PostToolUse cycle", "category": "mentor"},
        "mentor_chain_pattern": {"type": "str", "description": "Detected chain pattern: churn|stuck|healthy|empty", "category": "mentor"},
        "mentor_chain_score": {"type": "float", "description": "Outcome chain score 0.0-1.0", "category": "mentor"},
        "mentor_memory_match": {"type": "dict", "description": "Historical match from memory mentor (dict or None)", "category": "mentor"},
        "mentor_historical_context": {"type": "str", "description": "Human-readable historical context from memory mentor", "category": "mentor"},
        # v3.4 fields (analytics awareness — Upgrades C+F)
        "analytics_last_used": {"type": "dict", "description": "Per-analytics-tool last-used timestamps: {tool_name: timestamp}", "category": "analytics"},
        "analytics_last_queried": {"type": "float", "description": "Timestamp of last any mcp__analytics__ call", "category": "analytics"},
        "analytics_warn_count": {"type": "int", "description": "Gate 6 analytics F-track: separate counter, threshold 15", "category": "analytics"},
        # v3.5 fields (domain mastery)
        "active_domain": {"type": "str", "description": "Currently active domain name (or empty)", "category": "domain"},
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
    if "tool_call_counts" not in state:
        state["tool_call_counts"] = {}
    if "total_tool_calls" not in state:
        state["total_tool_calls"] = 0
    if "active_subagents" not in state:
        state["active_subagents"] = []
    if "subagent_total_tokens" not in state:
        state["subagent_total_tokens"] = 0
    if "subagent_history" not in state:
        state["subagent_history"] = []

    state["_version"] = 2
    return state


def migrate_v2_to_v3(state):
    """Migrate state from v2 to v3.

    Adds causal chain enforcement fields for Gate 15.
    """
    if "recent_test_failure" not in state:
        state["recent_test_failure"] = None
    if "fix_history_queried" not in state:
        state["fix_history_queried"] = 0
    if "fixing_error" not in state:
        state["fixing_error"] = False
    state["_version"] = 3
    return state


# Migration chain: maps (from_version) -> migration function
_MIGRATIONS = {
    1: migrate_v1_to_v2,
    2: migrate_v2_to_v3,
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
                     "unlogged_errors", "pending_chain_ids",
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
    # active_bans: support both legacy list and new dict format
    bans = state.get("active_bans", {})
    if isinstance(bans, list):
        migrated = {}
        for item in bans:
            if isinstance(item, str):
                migrated[item] = {"fail_count": 3, "first_failed": time.time(), "last_failed": time.time()}
        state["active_bans"] = migrated
        bans = migrated
        corrections.append(f"active_bans: migrated {len(migrated)} entries from list to dict")
    if isinstance(bans, dict) and len(bans) > MAX_ACTIVE_BANS:
        sorted_keys = sorted(bans, key=lambda k: bans[k].get("last_failed", 0) if isinstance(bans[k], dict) else 0)
        excess = sorted_keys[:len(bans) - MAX_ACTIVE_BANS]
        for k in excess:
            del bans[k]
        state["active_bans"] = bans
        corrections.append(f"active_bans: trimmed to {MAX_ACTIVE_BANS}")
    _cap_list(state, "pending_chain_ids", MAX_PENDING_CHAINS, corrections)

    # Cap error_pattern_counts dict
    pattern_counts = state.get("error_pattern_counts", {})
    if len(pattern_counts) > MAX_ERROR_PATTERNS:
        sorted_patterns = sorted(pattern_counts.items(), key=lambda x: x[1], reverse=True)
        state["error_pattern_counts"] = dict(sorted_patterns[:MAX_ERROR_PATTERNS])
        corrections.append(f"error_pattern_counts: trimmed from {len(pattern_counts)} to {MAX_ERROR_PATTERNS}")

    # Cap edit_streak dict — keep top N by count
    edit_streak = state.get("edit_streak", {})
    if len(edit_streak) > MAX_EDIT_STREAK:
        sorted_streak = sorted(edit_streak.items(), key=lambda x: x[1], reverse=True)
        state["edit_streak"] = dict(sorted_streak[:MAX_EDIT_STREAK])
        corrections.append(f"edit_streak: trimmed from {len(edit_streak)} to {MAX_EDIT_STREAK}")

    # Ensure skill_usage is a dict
    if not isinstance(state.get("skill_usage"), dict):
        state["skill_usage"] = {}
        corrections.append("skill_usage: reset to empty dict (was not a dict)")

    # Cap gate_timing_stats dict
    timing = state.get("gate_timing_stats", {})
    if len(timing) > 20:
        sorted_timing = sorted(timing.items(), key=lambda x: x[1].get("count", 0), reverse=True)
        state["gate_timing_stats"] = dict(sorted_timing[:20])
        corrections.append(f"gate_timing_stats: trimmed from {len(timing)} to 20")

    # Cap canary state lists (Gate 18)
    for canary_key in ("canary_short_timestamps", "canary_long_timestamps"):
        ts_list = state.get(canary_key)
        if isinstance(ts_list, list) and len(ts_list) > 600:
            old_len = len(ts_list)
            state[canary_key] = ts_list[-600:]
            corrections.append(f"{canary_key}: trimmed from {old_len} to 600")

    # Remove orphaned keys from previous schema versions
    _ORPHANED_KEYS = {"edits_locked", "confidence_warnings", "gate12_warn_count"}
    for key in _ORPHANED_KEYS:
        if key in state:
            del state[key]
            corrections.append(f"{key}: removed (orphaned)")

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

    # Cap edit_streak dict — keep top N by count
    edit_streak = state.get("edit_streak", {})
    if len(edit_streak) > MAX_EDIT_STREAK:
        sorted_streak = sorted(edit_streak.items(), key=lambda x: x[1], reverse=True)
        state["edit_streak"] = dict(sorted_streak[:MAX_EDIT_STREAK])

    # Cap active_bans dict — migrate list if needed, then cap
    bans = state.get("active_bans", {})
    if isinstance(bans, list):
        migrated = {}
        for item in bans:
            if isinstance(item, str):
                migrated[item] = {"fail_count": 3, "first_failed": time.time(), "last_failed": time.time()}
        state["active_bans"] = migrated
        bans = migrated
    if isinstance(bans, dict) and len(bans) > MAX_ACTIVE_BANS:
        sorted_keys = sorted(bans, key=lambda k: bans[k].get("last_failed", 0) if isinstance(bans[k], dict) else 0)
        for k in sorted_keys[:len(bans) - MAX_ACTIVE_BANS]:
            del bans[k]
        state["active_bans"] = bans

    # Cap pending_chain_ids list
    chains = state.get("pending_chain_ids", [])
    if len(chains) > MAX_PENDING_CHAINS:
        state["pending_chain_ids"] = chains[-MAX_PENDING_CHAINS:]

    # Cap gate_timing_stats dict — keep only active gates (max 20 entries)
    timing = state.get("gate_timing_stats", {})
    if len(timing) > 20:
        sorted_timing = sorted(timing.items(), key=lambda x: x[1].get("count", 0), reverse=True)
        state["gate_timing_stats"] = dict(sorted_timing[:20])

    # Cap canary timestamp lists to prevent unbounded growth (Gate 18)
    for canary_key in ("canary_short_timestamps", "canary_long_timestamps"):
        ts_list = state.get(canary_key)
        if isinstance(ts_list, list) and len(ts_list) > 600:
            state[canary_key] = ts_list[-600:]
    canary_seq = state.get("canary_recent_seq")
    if isinstance(canary_seq, list) and len(canary_seq) > 10:
        state["canary_recent_seq"] = canary_seq[-10:]

    # Cap gate_block_outcomes list
    outcomes = state.get("gate_block_outcomes", [])
    if isinstance(outcomes, list) and len(outcomes) > MAX_GATE_BLOCK_OUTCOMES:
        state["gate_block_outcomes"] = outcomes[-MAX_GATE_BLOCK_OUTCOMES:]

    # Ensure version is set
    state["_version"] = STATE_VERSION

    state_file = state_file_for(session_id)
    os.makedirs(os.path.dirname(state_file), exist_ok=True)
    lock_path = state_file + ".lock"
    with open(lock_path, "a+") as lock_fd:
        try:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
            tmp = state_file + f".tmp.{os.getpid()}"
            with open(tmp, "w") as f:
                json.dump(state, f, indent=2)
            os.replace(tmp, state_file)
        finally:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)


def get_memory_last_queried(state):
    """Get the most recent memory query timestamp.

    Checks both the per-agent enforcer state AND the global sideband file
    (written by the MCP server on every memory tool call). Returns the max
    of both timestamps. The sideband file is always checked because:
    - The MCP server writes it on every memory tool call
    - The main session may have a UUID session_id (not "main")
    - PostToolUse tracker also updates state, but sideband is more reliable
    """
    enforcer_ts = state.get("memory_last_queried", 0)

    # Always check sideband — MCP server writes it on every memory tool call
    sideband_ts = 0
    try:
        if os.path.exists(MEMORY_TIMESTAMP_FILE):
            with open(MEMORY_TIMESTAMP_FILE) as f:
                data = json.load(f)
            sideband_ts = data.get("timestamp", 0)
            # Clamp to current time: prevent future timestamps from permanently bypassing gates
            sideband_ts = max(0, min(sideband_ts, time.time()))
    except (json.JSONDecodeError, IOError, OSError):
        pass
    return max(enforcer_ts, sideband_ts)


_live_state_cache = None  # Per-process cache (each hook invocation is a fresh process)
_config_cache = None      # Per-process cache for config.json toggles

_CLAUDE_DIR = os.path.join(os.path.expanduser("~"), ".claude")
_CONFIG_PATH = os.path.join(_CLAUDE_DIR, "config.json")
_LIVE_STATE_PATH = os.path.join(_CLAUDE_DIR, "LIVE_STATE.json")


def load_config():
    """Load config.json (toggles). Returns full dict. Cached per-process."""
    global _config_cache
    if _config_cache is None:
        try:
            with open(_CONFIG_PATH) as f:
                _config_cache = json.load(f)
        except (OSError, json.JSONDecodeError):
            _config_cache = {}
    return _config_cache


def get_live_toggle(key, default=None):
    """Read a toggle value from config.json, falling back to LIVE_STATE.json.

    Used by gates and boot.py to check self-evolving feature flags.
    Files are read once per process and cached — multiple calls cost zero I/O.
    """
    global _live_state_cache
    # Check config.json first (new canonical location for toggles)
    cfg = load_config()
    if key in cfg:
        return cfg[key]
    # Fall back to LIVE_STATE.json for backward compat
    if _live_state_cache is None:
        try:
            with open(_LIVE_STATE_PATH) as f:
                _live_state_cache = json.load(f)
        except (OSError, json.JSONDecodeError):
            _live_state_cache = {}
    return _live_state_cache.get(key, default)


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


# --- Persistent gate effectiveness (survives across sessions) ---

EFFECTIVENESS_FILE = os.path.join(_DISK_STATE_DIR, ".gate_effectiveness.json")


def update_gate_effectiveness(gate: str, field: str):
    """Atomically increment a gate effectiveness counter in the persistent file.

    Fields: "blocks", "overrides", "prevented".
    Uses _DISK_STATE_DIR (not ramdisk) so data survives reboots.
    """
    try:
        data = {}
        if os.path.exists(EFFECTIVENESS_FILE):
            with open(EFFECTIVENESS_FILE) as f:
                data = json.load(f)
        ge = data.setdefault(gate, {"blocks": 0, "overrides": 0, "prevented": 0})
        ge[field] = ge.get(field, 0) + 1
        tmp = EFFECTIVENESS_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, EFFECTIVENESS_FILE)
    except Exception:
        pass  # fail-open — don't break enforcement over stats


def load_gate_effectiveness():
    """Load the persistent gate effectiveness data."""
    try:
        if os.path.exists(EFFECTIVENESS_FILE):
            with open(EFFECTIVENESS_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {}
