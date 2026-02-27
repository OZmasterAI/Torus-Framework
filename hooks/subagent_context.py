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

# Rules injected into sub-agents (no gates protect them)
EDIT_AGENT_RULES = "RULES: Always Read a file before Edit/Write. No rm -rf, force push, or reset --hard. Extra caution with critical files (auth, config, enforcer, memory_server) — query search_knowledge first."
BASH_AGENT_RULES = "RULES: No rm -rf, force push, or reset --hard."


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


def _format_skill_usage(session_state):
    """Format recent skill usage: 'Recent skills: commit, build, deep-dive'."""
    skills = session_state.get("recent_skills", [])
    if not skills:
        return ""
    # Deduplicate while preserving order (most recent last)
    seen = set()
    unique = []
    for s in reversed(skills):
        if s not in seen:
            seen.add(s)
            unique.append(s)
    unique.reverse()
    # Take last 5 (most recent)
    max_skills = 5
    if len(unique) > max_skills:
        shown = unique[-max_skills:]
        extra = len(unique) - max_skills
        return "Recent skills: " + ", ".join(shown) + f" +{extra} more."
    return "Recent skills: " + ", ".join(unique) + "."


# ─── Domain knowledge for sub-agents ─────────────────────────────────

def _get_domain_snippet(max_chars=500):
    """Load a compact domain knowledge snippet for sub-agent injection.

    Returns a short string with domain context, or empty string if no domain active.
    Truncates to max_chars to keep sub-agent context lean.
    """
    try:
        sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "hooks"))
        from shared.domain_registry import get_active_domain, load_domain_knowledge
        domain = get_active_domain()
        if not domain:
            return ""
        knowledge = load_domain_knowledge(domain)
        if not knowledge:
            return f"Active domain: {domain}."
        # Truncate for sub-agent budget
        if len(knowledge) > max_chars:
            knowledge = knowledge[:max_chars] + "..."
        return f"Domain expertise ({domain}): {knowledge}"
    except Exception:
        return ""


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
        skills_str = _format_skill_usage(session_state)
        if skills_str:
            parts.append(skills_str)
        parts.append("IMPORTANT: Query search_knowledge before making claims or assumptions.")
        parts.append("Explore and report findings only.")
        domain_snippet = _get_domain_snippet()
        if domain_snippet:
            parts.append(domain_snippet)
        return " ".join(parts)

    if agent_type == "general-purpose":
        parts = [
            f"Project: {project}. Feature: {feature}.",
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
        skills_str = _format_skill_usage(session_state)
        if skills_str:
            parts.append(skills_str)
        parts.append("IMPORTANT: Query search_knowledge before editing any files.")
        parts.append(EDIT_AGENT_RULES)
        domain_snippet = _get_domain_snippet()
        if domain_snippet:
            parts.append(domain_snippet)
        return " ".join(parts)

    if agent_type == "builder":
        parts = [
            f"Project: {project}. Feature: {feature}.",
        ]
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
        parts.append("IMPORTANT: Query search_knowledge before editing. Use remember_this after fixes.")
        parts.append(EDIT_AGENT_RULES)
        domain_snippet = _get_domain_snippet()
        if domain_snippet:
            parts.append(domain_snippet)
        return " ".join(parts)

    if agent_type == "Bash":
        parts = [
            f"Project: {project}.",
        ]
        errors_str = _format_error_state(session_state)
        if errors_str:
            parts.append(errors_str)
        parts.append(BASH_AGENT_RULES)
        domain_snippet = _get_domain_snippet()
        if domain_snippet:
            parts.append(domain_snippet)
        return " ".join(parts)

    # Default / unknown agent type
    parts = [f"Project: {project}. Active feature: {feature}."]
    files_str = _format_file_list(session_state.get("files_read", []))
    if files_str:
        parts.append(f"Recently read: {files_str}.")
    parts.append(EDIT_AGENT_RULES)

    # Inject domain knowledge snippet for all agent types
    domain_snippet = _get_domain_snippet()
    if domain_snippet:
        parts.append(domain_snippet)

    return " ".join(parts)


def _track_subagent_start(data):
    """Record active subagent in session state for statusline visibility."""
    try:
        agent_id = data.get("agent_id", "")
        if not agent_id:
            return  # Skip phantom entries with no agent_id
        agent_type = data.get("agent_type", "unknown")
        session_id = data.get("session_id", "")
        transcript_path = data.get("agent_transcript_path", "")

        # Construct transcript path if not provided (SubagentStart may not have it)
        if not transcript_path and session_id and agent_id:
            base = os.path.join(
                os.path.expanduser("~"), ".claude", "projects", "-home-$USER",
                session_id, "subagents", f"agent-{agent_id}.jsonl"
            )
            transcript_path = base

        # Find and update session state
        pattern = os.path.join(STATE_DIR, "state_*.json")
        files = glob.glob(pattern)
        if not files:
            return
        files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
        state_path = files[0]
        with open(state_path) as f:
            state = json.load(f)

        active = state.get("active_subagents", [])
        # Avoid duplicates
        if not any(sa.get("agent_id") == agent_id for sa in active):
            active.append({
                "agent_id": agent_id,
                "agent_type": agent_type,
                "transcript_path": transcript_path,
                "start_ts": time.time(),
            })
        state["active_subagents"] = active

        # Atomic write
        tmp = state_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, state_path)
    except Exception:
        pass  # Fail-open


def main():
    try:
        data = json.load(sys.stdin)
        agent_type = data.get("agent_type", "")

        live_state = load_live_state()
        session_state = find_current_session_state()
        context = build_context(agent_type, live_state, session_state)

        # Track subagent in session state for statusline
        _track_subagent_start(data)

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
