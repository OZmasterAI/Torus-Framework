#!/usr/bin/env python3
"""Telegram Mirror Tools — PostToolUse Hook

Appends tool call summaries to a per-session temp file.
The Stop hook (tg_mirror.py) reads and sends the batch.

Gated by tg_mirror_messages toggle (same as tg_mirror.py).
Always exits 0 (fail-open).

Input (stdin JSON):
  {"tool_name": "Bash", "tool_input": {...}, "session_id": "..."}
"""

import json
import os
import sys

CLAUDE_DIR = os.path.join(os.path.expanduser("~"), ".claude")
CONFIG_FILE = os.path.join(CLAUDE_DIR, "config.json")

# Tool display config
TOOL_ICONS = {
    "Bash": "\U0001f4c2",       # 📂
    "Edit": "\u270f\ufe0f",     # ✏️
    "Write": "\U0001f4dd",      # 📝
    "Read": "\U0001f4d6",       # 📖
    "Glob": "\U0001f50d",       # 🔍
    "Grep": "\U0001f50d",       # 🔍
    "Agent": "\U0001f916",      # 🤖
    "Skill": "\u2699\ufe0f",    # ⚙️
    "WebFetch": "\U0001f310",   # 🌐
    "WebSearch": "\U0001f310",  # 🌐
}


def _summarize_tool(tool_name, tool_input):
    """Create a short one-line summary of a tool call."""
    icon = TOOL_ICONS.get(tool_name, "\U0001f527")  # 🔧 default

    if tool_name == "Bash":
        cmd = (tool_input.get("command") or "")[:120]
        return f"{icon} Bash: {cmd}"
    elif tool_name in ("Edit", "Write"):
        path = tool_input.get("file_path", "")
        name = os.path.basename(path) if path else "?"
        return f"{icon} {tool_name}: {name}"
    elif tool_name == "Read":
        path = tool_input.get("file_path", "")
        name = os.path.basename(path) if path else "?"
        return f"{icon} Read: {name}"
    elif tool_name in ("Glob", "Grep"):
        pattern = tool_input.get("pattern", "")[:80]
        return f"{icon} {tool_name}: {pattern}"
    elif tool_name == "Agent":
        desc = tool_input.get("description", "")[:80]
        return f"{icon} Agent: {desc}"
    elif tool_name == "Skill":
        skill = tool_input.get("skill", "")
        return f"{icon} Skill: {skill}"
    elif tool_name in ("WebFetch", "WebSearch"):
        url = tool_input.get("url", tool_input.get("query", ""))[:80]
        return f"{icon} {tool_name}: {url}"
    elif "memory" in tool_name.lower() or "mcp__memory" in tool_name:
        query = tool_input.get("query") or tool_input.get("content", "")
        query = query[:80] if query else tool_name
        return f"\U0001f9e0 memory: {query}"  # 🧠
    else:
        return f"{icon} {tool_name}"


def main():
    try:
        data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    # Check toggle
    try:
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
        if not cfg.get("tg_mirror_messages", False):
            sys.exit(0)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    session_id = data.get("session_id", "unknown")

    if not tool_name:
        sys.exit(0)

    summary = _summarize_tool(tool_name, tool_input)
    tmp_file = f"/tmp/tg-mirror-tools-{session_id}.jsonl"

    try:
        with open(tmp_file, "a") as f:
            f.write(json.dumps({"summary": summary}) + "\n")
    except OSError:
        pass

    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
