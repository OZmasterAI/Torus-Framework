#!/usr/bin/env python3
"""Self-Healing Claude Framework — Status Line

Generates a compact status line for the Claude Code UI. Reads session data
from stdin (JSON with costs, context usage, etc.) and outputs a single
formatted line.

Format: project | G:12 | M:197 | CTX:23% | 15min | $0.42

Usage: Configured in settings.json as "statusLine" command.
"""

import json
import os
import sys
import time


CLAUDE_DIR = os.path.join(os.path.expanduser("~"), ".claude")
HOOKS_DIR = os.path.join(CLAUDE_DIR, "hooks")
GATES_DIR = os.path.join(HOOKS_DIR, "gates")
LIVE_STATE_FILE = os.path.join(CLAUDE_DIR, "LIVE_STATE.json")
MEMORY_DIR = os.path.join(os.path.expanduser("~"), "data", "memory")


def count_gates():
    """Count gate_*.py files in the gates directory."""
    if not os.path.isdir(GATES_DIR):
        return 0
    return len([f for f in os.listdir(GATES_DIR) if f.startswith("gate_") and f.endswith(".py")])


def get_memory_count():
    """Get curated memory count from ChromaDB (cached via count file)."""
    try:
        import chromadb
        client = chromadb.PersistentClient(path=MEMORY_DIR)
        col = client.get_or_create_collection(
            name="knowledge", metadata={"hnsw:space": "cosine"}
        )
        return col.count()
    except Exception:
        return "?"


def get_project_name():
    """Read project name from LIVE_STATE.json."""
    try:
        with open(LIVE_STATE_FILE) as f:
            state = json.load(f)
        return state.get("project", "claude")[:20]
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return "claude"


def main():
    # Read session data from stdin
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError, ValueError):
        data = {}

    # Extract session info
    cost = data.get("total_cost_usd", 0)
    context_pct = data.get("context_window_percent", 0)
    duration_secs = data.get("duration_seconds", 0)

    # Calculate display values
    project = get_project_name()
    gate_count = count_gates()
    mem_count = get_memory_count()
    minutes = int(duration_secs / 60) if duration_secs else 0

    # Format cost
    if isinstance(cost, (int, float)) and cost > 0:
        cost_str = f"${cost:.2f}"
    else:
        cost_str = "$0.00"

    # Format context
    if isinstance(context_pct, (int, float)) and context_pct > 0:
        ctx_str = f"CTX:{int(context_pct)}%"
    else:
        ctx_str = "CTX:0%"

    # Build status line
    line = f"{project} | G:{gate_count} | M:{mem_count} | {ctx_str} | {minutes}min | {cost_str}"
    print(line)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Fail-open: output minimal line on crash
        print("claude | status error")
