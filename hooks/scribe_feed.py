#!/usr/bin/env python3
"""PostToolUse + UserPromptSubmit hook: writes compact JSONL events to scribe feed file.

The scribe feed is a per-session append-only JSONL file on ramdisk. A named Haiku
background agent ("scribe") reads it at session wrap-up to extract structured insights
(atomic facts, decisions, patterns, contradictions, course corrections, key learnings).

Feed files accumulate across sessions for potential cross-session analysis.

Must always exit 0 — never crash the hook pipeline.
"""

import json
import os
import sys
import time

# Ramdisk base path (already used by gates and sideband)
_UID = os.getuid()
_RAMDISK = f"/run/user/{_UID}/claude-hooks"


def _feed_path(session_id: str) -> str:
    return os.path.join(_RAMDISK, f".scribe_feed_{session_id}.jsonl")


def _ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def _extract_file(tool_name: str, tool_input: dict) -> str:
    """Best-effort file path extraction from tool input."""
    for key in ("file_path", "path", "file"):
        v = tool_input.get(key)
        if v and isinstance(v, str):
            return v
    return ""


def _tool_summary(tool_name: str, tool_input: dict) -> str:
    """Compact summary of a tool call from its input fields."""
    if tool_name in ("Edit", "Write", "NotebookEdit"):
        fp = _extract_file(tool_name, tool_input)
        return f"{tool_name} {fp}" if fp else tool_name

    if tool_name == "Read":
        fp = tool_input.get("file_path", "")
        return f"Read {fp}" if fp else "Read"

    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        return f"$ {cmd[:120]}" if cmd else "Bash"

    if tool_name in ("Grep", "Glob"):
        pat = tool_input.get("pattern", "")
        return f"{tool_name} {pat[:80]}" if pat else tool_name

    if tool_name == "Agent":
        desc = tool_input.get("description", "")
        return f"Agent: {desc[:80]}" if desc else "Agent"

    if tool_name == "SendMessage":
        to = tool_input.get("to", "")
        return f"SendMessage → {to}" if to else "SendMessage"

    if tool_name.startswith("mcp__memory__"):
        short = tool_name.replace("mcp__memory__", "mem:")
        content = tool_input.get("content", tool_input.get("query", ""))
        if content and isinstance(content, str):
            return f"{short} {content[:60]}"
        return short

    if tool_name in ("WebFetch", "WebSearch"):
        url_or_q = tool_input.get("url", tool_input.get("query", ""))
        if url_or_q and isinstance(url_or_q, str):
            return f"{tool_name} {url_or_q[:100]}"
        return tool_name

    if tool_name == "Skill":
        skill = tool_input.get("skill", "")
        return f"/{skill}" if skill else "Skill"

    # Fallback: tool name only
    return tool_name


def _handle_post_tool_use(data: dict) -> None:
    session_id = data.get("session_id", "main")
    tool_name = data.get("tool_name", "unknown")
    tool_input = data.get("tool_input", {})
    if not isinstance(tool_input, dict):
        tool_input = {}

    event = {
        "ts": _ts(),
        "ev": "tool",
        "tool": tool_name,
        "summary": _tool_summary(tool_name, tool_input),
        "file": _extract_file(tool_name, tool_input),
    }

    _append(session_id, event)


def _handle_user_prompt(data: dict) -> None:
    session_id = data.get("session_id", "main")
    prompt = data.get("prompt", "")
    if not isinstance(prompt, str):
        prompt = str(prompt)

    event = {
        "ts": _ts(),
        "ev": "user",
        "summary": prompt[:500],
    }

    _append(session_id, event)


def _append(session_id: str, event: dict) -> None:
    """Append a JSON line to the feed file. Best-effort, never raises."""
    path = _feed_path(session_id)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps(event, separators=(",", ":")) + "\n")
    except OSError:
        pass  # Ramdisk full or missing — silent fail


def main():
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            sys.exit(0)
        data = json.loads(raw)
    except (json.JSONDecodeError, OSError):
        sys.exit(0)

    # Determine event type from the payload
    if "tool_name" in data:
        _handle_post_tool_use(data)
    elif "prompt" in data:
        _handle_user_prompt(data)

    sys.exit(0)


if __name__ == "__main__":
    main()
