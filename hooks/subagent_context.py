#!/usr/bin/env python3
"""SubagentStart hook: inject rich project context into sub-agents.

Reads agent_type from stdin JSON and loads project context from both
LIVE_STATE.json (project metadata) and the active session's state file
(operational state: files read, errors, test status, bans). Outputs
tailored context so sub-agents start with full situational awareness.

Fail-open: always exits 0, never crashes the agent spawn.
"""

import glob
import json
import os
import sys
import time

LIVE_STATE_FILE = os.path.join(os.path.expanduser("~"), ".claude", "LIVE_STATE.json")
STATE_DIR = os.path.join(os.path.expanduser("~"), ".claude", "hooks")

FALLBACK_CONTEXT = "No project context available. Query memory before starting work."


def load_live_state():
    """Load project state, returning empty dict on any failure."""
    try:
        with open(LIVE_STATE_FILE) as f:
            return json.loads(f.read())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def find_current_session_state():
    """Find and load the most recently modified session state file.

    Globs for state_*.json, picks the newest by mtime, and returns its
    contents as a dict. Returns {} on any failure (fail-open).
    """
    try:
        pattern = os.path.join(STATE_DIR, "state_*.json")
        files = glob.glob(pattern)
        if not files:
            return {}
        # Sort by modification time, most recent first
        files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
        with open(files[0]) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError, IndexError):
        return {}


# ─── Compact formatting helpers ─────────────────────────────────────

def _format_file_list(files, max_files=5):
    """Format a list of file paths compactly: 'a.py, b.py +3 more'."""
    if not files:
        return ""
    # Extract basenames for brevity
    names = [os.path.basename(f) for f in files]
    # Deduplicate while preserving order (most recent last, so reverse)
    seen = set()
    unique = []
    for n in reversed(names):
        if n not in seen:
            seen.add(n)
            unique.append(n)
    unique.reverse()
    # Take last max_files (most recent)
    if len(unique) > max_files:
        shown = unique[-max_files:]
        extra = len(unique) - max_files
        return ", ".join(shown) + f" +{extra} more"
    return ", ".join(unique)


def _format_error_state(session_state):
    """Format active error patterns: 'Active errors: Traceback x2, SyntaxError x1'."""
    patterns = session_state.get("error_pattern_counts", {})
    if not patterns:
        return ""
    # Sort by count descending, take top 3
    sorted_p = sorted(patterns.items(), key=lambda x: x[1], reverse=True)[:3]
    parts = [f"{name} x{count}" for name, count in sorted_p]
    return "Active errors: " + ", ".join(parts) + "."


def _format_test_status(session_state):
    """Format last test run info: 'Last test: PASS (5 min ago)' or ''."""
    last_run = session_state.get("last_test_run", 0)
    if not last_run:
        return ""
    elapsed = time.time() - last_run
    if elapsed < 60:
        ago = "just now"
    elif elapsed < 3600:
        ago = f"{int(elapsed / 60)} min ago"
    else:
        ago = f"{int(elapsed / 3600)}h ago"
    return f"Last test: {ago}."


def _format_pending(session_state):
    """Format pending verification list."""
    pending = session_state.get("pending_verification", [])
    if not pending:
        return ""
    names = [os.path.basename(f) for f in pending[:5]]
    result = "Pending verification: " + ", ".join(names)
    if len(pending) > 5:
        result += f" +{len(pending) - 5} more"
    return result + "."


def _format_bans(session_state):
    """Format banned strategies."""
    bans = session_state.get("active_bans", [])
    if not bans:
        return ""
    return "Banned strategies: " + ", ".join(bans[:5]) + "."


# ─── Context builder ────────────────────────────────────────────────

def build_context(agent_type, live_state, session_state=None):
    """Build context string tailored to the agent type.

    Args:
        agent_type: The type of sub-agent being spawned.
        live_state: Dict from LIVE_STATE.json (project metadata).
        session_state: Dict from state_{session_id}.json (operational state).
    """
    if session_state is None:
        session_state = {}

    project = live_state.get("project", "unknown")
    feature = live_state.get("feature", "none")
    test_count = live_state.get("test_count", "?")
    status = live_state.get("status", "unknown")

    if not live_state:
        return FALLBACK_CONTEXT

    if agent_type in ("Explore", "Plan"):
        parts = [
            f"You are a READ-ONLY {agent_type} agent. Do not create or edit files.",
            f"Project: {project}. Active feature: {feature}.",
        ]
        # Add recent files so they know what's already been explored
        files_str = _format_file_list(session_state.get("files_read", []))
        if files_str:
            parts.append(f"Recently read: {files_str}.")
        # Add active errors so they can investigate
        errors_str = _format_error_state(session_state)
        if errors_str:
            parts.append(errors_str)
        parts.append("Explore and report findings only.")
        return " ".join(parts)

    if agent_type == "general-purpose":
        parts = [
            f"Project: {project}. Feature: {feature}.",
            f"Status: {status}. Tests: {test_count}.",
        ]
        # Rich operational context
        files_str = _format_file_list(session_state.get("files_read", []))
        if files_str:
            parts.append(f"Recently read: {files_str}.")
        pending_str = _format_pending(session_state)
        if pending_str:
            parts.append(pending_str)
        test_str = _format_test_status(session_state)
        if test_str:
            parts.append(test_str)
        errors_str = _format_error_state(session_state)
        if errors_str:
            parts.append(errors_str)
        bans_str = _format_bans(session_state)
        if bans_str:
            parts.append(bans_str)
        parts.append("IMPORTANT: Query search_knowledge before editing any files.")
        return " ".join(parts)

    if agent_type == "Bash":
        parts = [
            f"Project: {project}.",
        ]
        errors_str = _format_error_state(session_state)
        if errors_str:
            parts.append(errors_str)
        return " ".join(parts)

    # Default / unknown agent type
    parts = [f"Project: {project}. Active feature: {feature}."]
    files_str = _format_file_list(session_state.get("files_read", []))
    if files_str:
        parts.append(f"Recently read: {files_str}.")
    return " ".join(parts)


def main():
    try:
        data = json.load(sys.stdin)
        agent_type = data.get("agent_type", "")

        live_state = load_live_state()
        session_state = find_current_session_state()
        context = build_context(agent_type, live_state, session_state)

        output = {
            "hookSpecificOutput": {
                "hookEventName": "SubagentStart",
                "additionalContext": context,
            }
        }
        print(json.dumps(output))
    except Exception:
        # Fail-open: emit generic context on any error
        output = {
            "hookSpecificOutput": {
                "hookEventName": "SubagentStart",
                "additionalContext": FALLBACK_CONTEXT,
            }
        }
        print(json.dumps(output))

    sys.exit(0)


if __name__ == "__main__":
    main()
