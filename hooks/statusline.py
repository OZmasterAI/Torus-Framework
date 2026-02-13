#!/usr/bin/env python3
"""Self-Healing Claude Framework — Status Line

Generates a compact status line for the Claude Code UI. Reads session data
from stdin (JSON with costs, context usage, etc.) and outputs a single
formatted line.

Format: project | G:12 | M:215 | CTX:23% | 15min | +120/-34 | $0.42

Usage: Configured in settings.json as "statusLine" command.

Claude Code sends nested JSON via stdin:
  cost.total_cost_usd, cost.total_duration_ms, cost.total_lines_added,
  cost.total_lines_removed, context_window.used_percentage, model.display_name
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
STATS_CACHE = os.path.join(CLAUDE_DIR, "stats-cache.json")

# Cache memory count for 60 seconds to avoid cold-starting ChromaDB on every render
CACHE_TTL = 60


def count_gates():
    """Count gate_*.py files in the gates directory."""
    if not os.path.isdir(GATES_DIR):
        return 0
    return len([f for f in os.listdir(GATES_DIR) if f.startswith("gate_") and f.endswith(".py")])


def get_memory_count():
    """Get curated memory count, cached to avoid cold-starting ChromaDB each time."""
    # Try cache first
    try:
        if os.path.exists(STATS_CACHE):
            with open(STATS_CACHE) as f:
                cache = json.load(f)
            if time.time() - cache.get("ts", 0) < CACHE_TTL:
                return cache.get("mem_count", "?")
    except (json.JSONDecodeError, OSError):
        pass

    # Cache miss — query ChromaDB
    try:
        import chromadb
        client = chromadb.PersistentClient(path=MEMORY_DIR)
        col = client.get_or_create_collection(
            name="knowledge", metadata={"hnsw:space": "cosine"}
        )
        count = col.count()
        # Write cache
        try:
            with open(STATS_CACHE, "w") as f:
                json.dump({"ts": time.time(), "mem_count": count}, f)
        except OSError:
            pass
        return count
    except Exception:
        return "?"


def get_project_name():
    """Read project name from LIVE_STATE.json."""
    try:
        with open(LIVE_STATE_FILE) as f:
            state = json.load(f)
        name = state.get("project", "claude")
        # Use short alias for known long names
        aliases = {
            "self-healing-framework": "shf",
        }
        return aliases.get(name, name)[:12]
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return "claude"


def main():
    # Read session data from stdin
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError, ValueError):
        data = {}

    # Extract session info (correct nested paths)
    cost_data = data.get("cost", {}) or {}
    ctx_data = data.get("context_window", {}) or {}

    cost = cost_data.get("total_cost_usd", 0) or 0
    duration_ms = cost_data.get("total_duration_ms", 0) or 0
    lines_added = cost_data.get("total_lines_added", 0) or 0
    lines_removed = cost_data.get("total_lines_removed", 0) or 0
    context_pct = ctx_data.get("used_percentage", 0) or 0

    # Calculate display values
    project = get_project_name()
    gate_count = count_gates()
    mem_count = get_memory_count()
    minutes = int(duration_ms / 60000) if duration_ms else 0

    # Format cost
    if isinstance(cost, (int, float)) and cost > 0:
        cost_str = f"${cost:.2f}"
    else:
        cost_str = "$0.00"

    # Format context with warning levels
    if isinstance(context_pct, (int, float)) and context_pct > 0:
        if context_pct >= 80:
            ctx_str = f"CTX:{int(context_pct)}%!"
        else:
            ctx_str = f"CTX:{int(context_pct)}%"
    else:
        ctx_str = "CTX:0%"

    # Format lines changed
    if lines_added or lines_removed:
        lines_str = f"+{lines_added}/-{lines_removed}"
    else:
        lines_str = ""

    # Build status line
    parts = [project, f"G:{gate_count}", f"M:{mem_count}", ctx_str]
    if minutes:
        parts.append(f"{minutes}min")
    if lines_str:
        parts.append(lines_str)
    parts.append(cost_str)

    print(" | ".join(parts))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Fail-open: output minimal line on crash
        print("claude | status error")
