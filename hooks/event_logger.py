#!/usr/bin/env python3
"""Event logger for supplementary Claude Code hook events.

Handles: SubagentStop, PostToolUseFailure, Notification, TeammateIdle, TaskCompleted.

Logs events to stderr (visible in debug) and updates session state where relevant.
Fail-open: always exits 0, never disrupts the event.

Usage:
    echo '{"agent_type":"Explore",...}' | python3 event_logger.py --event SubagentStop
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

STATE_DIR = os.path.join(os.path.expanduser("~"), ".claude", "hooks")
AUDIT_DIR = os.path.join(STATE_DIR, "audit")


def _find_session_state():
    """Find the most recently modified session state file."""
    import glob
    pattern = os.path.join(STATE_DIR, "state_*.json")
    files = glob.glob(pattern)
    if not files:
        return None, {}
    files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
    try:
        with open(files[0]) as f:
            return files[0], json.load(f)
    except (json.JSONDecodeError, OSError):
        return files[0], {}


def _save_state(path, state):
    """Atomic write to state file."""
    if not path:
        return
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, path)
    except OSError:
        pass


def _audit_log(event_name, data):
    """Append a line to today's audit log."""
    try:
        os.makedirs(AUDIT_DIR, exist_ok=True)
        today = time.strftime("%Y-%m-%d")
        log_file = os.path.join(AUDIT_DIR, f"{today}.jsonl")
        entry = {
            "ts": time.time(),
            "event": event_name,
            "data": data,
        }
        with open(log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def handle_subagent_stop(data):
    """Log when a sub-agent finishes or crashes."""
    agent_type = data.get("agent_type", "unknown")
    # Extract any error info if present
    error = data.get("error", "")
    status = "error" if error else "completed"
    msg = f"[SubagentStop] {agent_type} agent {status}"
    if error:
        msg += f": {str(error)[:100]}"
    print(msg, file=sys.stderr)
    _audit_log("SubagentStop", {"agent_type": agent_type, "status": status})


def handle_post_tool_use_failure(data):
    """Log tool failures and update error pattern counts in session state."""
    tool_name = data.get("tool_name", "unknown")
    error = data.get("error", str(data.get("tool_response", "")))[:200]
    print(f"[PostToolUseFailure] {tool_name}: {error[:80]}", file=sys.stderr)
    _audit_log("PostToolUseFailure", {"tool": tool_name, "error": error[:200]})

    # Update error pattern counts in session state
    state_path, state = _find_session_state()
    if state:
        patterns = state.get("error_pattern_counts", {})
        # Use tool name as pattern key for tool failures
        key = f"ToolFail:{tool_name}"
        patterns[key] = patterns.get(key, 0) + 1
        state["error_pattern_counts"] = patterns
        _save_state(state_path, state)


def handle_notification(data):
    """Log system-level notifications."""
    message = data.get("message", data.get("content", str(data)))[:200]
    print(f"[Notification] {message[:80]}", file=sys.stderr)
    _audit_log("Notification", {"message": message})


def handle_teammate_idle(data):
    """Log when a team member goes idle."""
    agent_name = data.get("agent_name", data.get("name", "unknown"))
    print(f"[TeammateIdle] {agent_name}", file=sys.stderr)
    _audit_log("TeammateIdle", {"agent": agent_name})


def handle_task_completed(data):
    """Log when a team task is completed."""
    task_id = data.get("task_id", data.get("id", "unknown"))
    subject = data.get("subject", data.get("title", ""))[:100]
    print(f"[TaskCompleted] #{task_id}: {subject[:60]}", file=sys.stderr)
    _audit_log("TaskCompleted", {"task_id": task_id, "subject": subject})


HANDLERS = {
    "SubagentStop": handle_subagent_stop,
    "PostToolUseFailure": handle_post_tool_use_failure,
    "Notification": handle_notification,
    "TeammateIdle": handle_teammate_idle,
    "TaskCompleted": handle_task_completed,
}


def main():
    event_name = ""
    for i, arg in enumerate(sys.argv):
        if arg == "--event" and i + 1 < len(sys.argv):
            event_name = sys.argv[i + 1]
            break

    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, Exception):
        data = {}

    handler = HANDLERS.get(event_name)
    if handler:
        try:
            handler(data)
        except Exception as e:
            print(f"[event_logger] Error in {event_name}: {e}", file=sys.stderr)

    # Always exit 0 — fail-open
    sys.exit(0)


if __name__ == "__main__":
    main()
