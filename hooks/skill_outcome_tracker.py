#!/usr/bin/env python3
"""PostToolUse hook — auto-detect skill execution outcomes.

Watches for invoke_skill calls from skills/skills-v2 MCP servers,
tracks subsequent tool calls for success/failure signals, then
writes the outcome to SQLite via skill_db.

Runs as a separate PostToolUse hook alongside tracker.py.
State stored on ramdisk for speed, fail-open on all errors.
"""

import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

# Window of tool calls to observe after skill invocation before deciding
WINDOW_SIZE = 8

# Ramdisk path for pending state (fast, ephemeral)
_UID = os.getuid()
_RAMDISK_DIR = f"/run/user/{_UID}/claude-hooks"
_DEFAULT_STATE_PATH = os.path.join(_RAMDISK_DIR, "skill_pending_outcome.json")
_DEFAULT_DB_PATH = os.path.join(
    os.path.expanduser("~"), ".claude", "hooks", ".state", "skills.db"
)

# Tool name patterns for skill invocation
_INVOKE_PATTERNS = (
    "mcp__skills-v2__invoke_skill",
    "mcp__skills__invoke_skill",
)

# Read-only/neutral tools (don't count as success or failure)
_NEUTRAL_TOOLS = {
    "Read",
    "Glob",
    "Grep",
    "Agent",
    "TodoRead",
    "TodoWrite",
    "TaskCreate",
    "TaskUpdate",
    "TaskGet",
    "TaskList",
    "WebSearch",
    "WebFetch",
}


def detect_skill_invocation(
    tool_name: str, tool_input: dict, tool_response: str
) -> str | None:
    """Check if this tool call is an invoke_skill. Returns skill name or None."""
    # Direct MCP call path
    if tool_name in _INVOKE_PATTERNS:
        skill_name = tool_input.get("name", "")
        if not skill_name:
            return None
    # Toolshed gateway path
    elif (
        tool_name == "mcp__toolshed__run_tool"
        and tool_input.get("server") == "skills-v2"
        and tool_input.get("tool") == "invoke_skill"
    ):
        skill_name = tool_input.get("args", {}).get("name", "")
        if not skill_name:
            return None
    else:
        return None

    # Check response isn't an error
    try:
        resp = (
            json.loads(tool_response)
            if isinstance(tool_response, str)
            else tool_response
        )
        if isinstance(resp, dict) and "error" in resp:
            return None
    except (json.JSONDecodeError, TypeError):
        pass

    return skill_name


def classify_tool_signal(
    tool_name: str, tool_input: dict, tool_response: str, exit_code: int
) -> str:
    """Classify a tool call as success, failure, or neutral signal.

    Returns: "success", "failure", or "neutral".
    """
    # Neutral tools — information gathering, no signal
    if tool_name in _NEUTRAL_TOOLS:
        return "neutral"
    if tool_name.startswith("mcp__"):
        return "neutral"

    # Edit/Write — neutral (intermediate steps)
    if tool_name in ("Edit", "Write", "NotebookEdit"):
        return "neutral"

    # Bash — main signal source
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        resp = str(tool_response or "")

        # Non-zero exit code = failure
        if exit_code and exit_code != 0:
            return "failure"

        # Success patterns in output
        if re.search(r"\d+\s+pass", resp, re.IGNORECASE):
            return "success"
        if re.search(r"\[[\w-]+\s+[a-f0-9]+\]", resp) and "commit" in cmd.lower():
            return "success"
        if "Successfully" in resp:
            return "success"

        # Failure patterns in output (even with exit code 0)
        if re.search(r"(?:Error|FAIL|Traceback|panic):", resp, re.IGNORECASE):
            return "failure"

    return "neutral"


def load_pending(state_path: str = _DEFAULT_STATE_PATH) -> dict | None:
    """Load pending skill outcome state. Returns None if no pending."""
    try:
        if not os.path.exists(state_path):
            return None
        with open(state_path) as f:
            data = json.load(f)
        return data if data else None
    except (json.JSONDecodeError, OSError):
        return None


def save_pending(state_path: str, data: dict | None) -> None:
    """Save pending state, or remove file if data is None."""
    try:
        if data is None:
            if os.path.exists(state_path):
                os.remove(state_path)
            return
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        with open(state_path, "w") as f:
            json.dump(data, f)
    except OSError:
        pass


def _record_to_db(skill_name: str, success: bool, context: str, db_path: str) -> None:
    """Write outcome directly to SQLite. Fail-open."""
    try:
        from shared.skill_db import init_db, get_or_create_skill, record_outcome

        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        conn = init_db(db_path)
        skill_id = get_or_create_skill(conn, skill_name)
        record_outcome(conn, skill_id, applied=True, completed=success)
        conn.close()
    except Exception:
        pass


def _finalize_outcome(pending: dict, db_path: str) -> None:
    """Determine success/failure from accumulated signals and write to DB."""
    successes = pending.get("successes", 0)
    failures = pending.get("failures", 0)

    # Majority vote, with bias toward failure (any failure is notable)
    if failures > 0 and failures >= successes:
        success = False
        context = f"auto-detected: {failures} failures, {successes} successes in {pending['tool_calls']} tool calls"
    elif successes > 0:
        success = True
        context = f"auto-detected: {successes} successes, {failures} failures in {pending['tool_calls']} tool calls"
    else:
        # All neutral — assume success (skill was invoked, nothing broke)
        success = True
        context = (
            f"auto-detected: no explicit signals in {pending['tool_calls']} tool calls"
        )

    _record_to_db(pending["skill_name"], success, context, db_path)


def process_post_tool_use(
    tool_name: str,
    tool_input: dict,
    tool_response: str,
    exit_code: int = 0,
    state_path: str = _DEFAULT_STATE_PATH,
    db_path: str = _DEFAULT_DB_PATH,
) -> str:
    """Process a PostToolUse event for skill outcome tracking.

    Returns: "tracking_started", "tracking", "outcome_recorded", or "idle".
    """
    pending = load_pending(state_path)

    # Check if this is a new skill invocation
    skill_name = detect_skill_invocation(tool_name, tool_input, tool_response)

    if skill_name:
        # New invocation — finalize any previous pending
        if pending:
            _finalize_outcome(pending, db_path)

        # Start new tracking
        save_pending(
            state_path,
            {
                "skill_name": skill_name,
                "invoked_at": time.time(),
                "tool_calls": 0,
                "successes": 0,
                "failures": 0,
            },
        )
        return "tracking_started"

    if pending is None:
        return "idle"

    # Update pending with this tool's signal
    signal = classify_tool_signal(tool_name, tool_input, tool_response, exit_code)

    pending["tool_calls"] += 1
    if signal == "success":
        pending["successes"] += 1
    elif signal == "failure":
        pending["failures"] += 1

    # Check if window exceeded
    if pending["tool_calls"] >= WINDOW_SIZE:
        _finalize_outcome(pending, db_path)
        save_pending(state_path, None)
        return "outcome_recorded"

    # Early termination: clear success signal (test pass, commit)
    if pending["successes"] >= 2 and pending["failures"] == 0:
        _finalize_outcome(pending, db_path)
        save_pending(state_path, None)
        return "outcome_recorded"

    save_pending(state_path, pending)
    return "tracking"


def main():
    """Main entry point — PostToolUse hook. Fail-open: always exits 0."""
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    if not tool_name:
        sys.exit(0)

    tool_input = data.get("tool_input", {})
    tool_response = data.get("tool_response", "")
    if isinstance(tool_response, dict):
        tool_response = json.dumps(tool_response)

    # Extract exit code from Bash tool responses
    exit_code = 0
    if tool_name == "Bash":
        try:
            resp = (
                json.loads(data.get("tool_response", "{}"))
                if isinstance(data.get("tool_response"), str)
                else data.get("tool_response", {})
            )
            if isinstance(resp, dict):
                exit_code = resp.get("exitCode", resp.get("exit_code", 0))
        except (json.JSONDecodeError, TypeError):
            pass

    process_post_tool_use(
        tool_name=tool_name,
        tool_input=tool_input,
        tool_response=str(tool_response),
        exit_code=exit_code,
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
