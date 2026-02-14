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

_DISK_STATE_DIR = os.path.join(os.path.expanduser("~"), ".claude", "hooks")

try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
    from shared.ramdisk import get_audit_dir, get_state_dir, is_ramdisk_available, async_mirror_append
    _HAS_RAMDISK = True
    AUDIT_DIR = get_audit_dir()
    STATE_DIR = get_state_dir()
except ImportError:
    _HAS_RAMDISK = False
    AUDIT_DIR = os.path.join(_DISK_STATE_DIR, "audit")
    STATE_DIR = _DISK_STATE_DIR


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


def _audit_log(event_name, data, session_id=""):
    """Append a line to today's audit log with session correlation."""
    try:
        os.makedirs(AUDIT_DIR, exist_ok=True)
        today = time.strftime("%Y-%m-%d")
        log_file = os.path.join(AUDIT_DIR, f"{today}.jsonl")
        entry = {
            "ts": time.time(),
            "event": event_name,
            "data": data,
            "session_id": session_id,
        }
        line = json.dumps(entry) + "\n"
        if _HAS_RAMDISK and is_ramdisk_available():
            async_mirror_append(log_file, line)
        else:
            with open(log_file, "a") as f:
                f.write(line)
    except OSError:
        pass


def _sum_transcript_tokens(transcript_path):
    """Parse a subagent transcript JSONL and sum all token usage."""
    total = 0
    if not transcript_path or not os.path.isfile(transcript_path):
        return 0
    try:
        with open(transcript_path) as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    usage = entry.get("message", {}).get("usage", {})
                    total += usage.get("input_tokens", 0)
                    total += usage.get("output_tokens", 0)
                except (json.JSONDecodeError, AttributeError):
                    continue
    except OSError:
        pass
    return total


def _fmt_tokens(n):
    """Format token count compactly: 834 → '834', 19700 → '19.7k'."""
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        k = n / 1000
        return f"{k:.1f}k" if k < 100 else f"{int(k)}k"
    return f"{n / 1_000_000:.1f}M"


def handle_subagent_stop(data):
    """Log when a sub-agent finishes, parse transcript tokens, update state."""
    agent_id = data.get("agent_id", "unknown")
    agent_type = data.get("agent_type", "unknown")
    transcript_path = data.get("agent_transcript_path", "")
    error = data.get("error", "")
    status = "error" if error else "completed"

    # Parse transcript for token usage
    tokens = _sum_transcript_tokens(transcript_path)

    # Update session state: remove from active, add to history
    try:
        import glob
        pattern = os.path.join(STATE_DIR, "state_*.json")
        files = glob.glob(pattern)
        if files:
            files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
            state_path = files[0]
            with open(state_path) as f:
                state = json.load(f)

            # Remove from active_subagents
            active = state.get("active_subagents", [])
            start_ts = time.time()
            for sa in active:
                if sa.get("agent_id") == agent_id:
                    start_ts = sa.get("start_ts", time.time())
                    break
            state["active_subagents"] = [
                sa for sa in active if sa.get("agent_id") != agent_id
            ]

            # Add to history
            duration_s = round(time.time() - start_ts, 1)
            history = state.get("subagent_history", [])
            history.append({
                "agent_id": agent_id,
                "agent_type": agent_type,
                "tokens": tokens,
                "duration_s": duration_s,
            })
            # Cap history at 20 entries
            state["subagent_history"] = history[-20:]

            # Accumulate total tokens
            state["subagent_total_tokens"] = state.get("subagent_total_tokens", 0) + tokens

            # Atomic write
            tmp = state_path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(state, f, indent=2)
            os.replace(tmp, state_path)
    except Exception:
        pass  # Fail-open

    # Enhanced stderr log
    msg = f"[SubagentStop] {agent_type} {status}"
    if tokens:
        msg += f" | {_fmt_tokens(tokens)} tok"
    if error:
        msg += f" | {str(error)[:80]}"
    print(msg, file=sys.stderr)


def handle_post_tool_use_failure(data):
    """Log tool failures and update error pattern counts in session state."""
    tool_name = data.get("tool_name", "unknown")
    error = data.get("error", str(data.get("tool_response", "")))[:200]
    print(f"[PostToolUseFailure] {tool_name}: {error[:80]}", file=sys.stderr)

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


def handle_teammate_idle(data):
    """Log when a team member goes idle."""
    agent_name = data.get("agent_name", data.get("name", "unknown"))
    print(f"[TeammateIdle] {agent_name}", file=sys.stderr)


def handle_task_completed(data):
    """Log when a team task is completed, with quality warnings."""
    task_id = data.get("task_id", data.get("id", "unknown"))
    subject = data.get("subject", data.get("title", ""))[:100]
    print(f"[TaskCompleted] #{task_id}: {subject[:60]}", file=sys.stderr)

    # Quality checks from completing agent's state
    try:
        _, state = _find_session_state()
        if not state:
            return

        warnings = []

        # Check for unverified edits
        pending = state.get("pending_verification", [])
        if pending:
            files = ", ".join(os.path.basename(f) for f in pending[:3])
            suffix = f" (+{len(pending)-3} more)" if len(pending) > 3 else ""
            warnings.append(
                f"Task completed with {len(pending)} unverified edit(s): {files}{suffix}. "
                f"Consider running tests before marking tasks complete."
            )

        # Check for unlogged errors
        unlogged = state.get("unlogged_errors", [])
        if unlogged:
            patterns = set(e.get("pattern", "unknown") for e in unlogged[:5])
            warnings.append(
                f"Task completed with {len(unlogged)} unlogged error(s) ({', '.join(patterns)}). "
                f"Consider using remember_this() to save error context."
            )

        # Check for recurring error patterns
        pattern_counts = state.get("error_pattern_counts", {})
        recurring = {p: c for p, c in pattern_counts.items() if c >= 3}
        if recurring:
            top = max(recurring, key=lambda p: recurring[p])
            warnings.append(
                f"Recurring error pattern '{top}' ({recurring[top]}x) detected during task. "
                f"Consider investigating root cause."
            )

        # Emit warnings
        for w in warnings:
            print(f"[TaskCompleted WARNING] {w}", file=sys.stderr)

    except Exception:
        pass  # Fail-open: quality checks must not crash event logger


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

    # Extract session ID for audit correlation
    session_id = data.get("session_id", "")

    handler = HANDLERS.get(event_name)
    if handler:
        try:
            handler(data)
        except Exception as e:
            print(f"[event_logger] Error in {event_name}: {e}", file=sys.stderr)

    # Unified audit with session correlation
    _audit_log(event_name, data, session_id=session_id)

    # Always exit 0 — fail-open
    sys.exit(0)


if __name__ == "__main__":
    main()
