#!/usr/bin/env python3
"""Gather system status data and print a pre-formatted dashboard to stdout.

Reads from LIVE_STATE.json, HANDOFF.md, session state files, memory MCP,
gate/skill/hook counts, and git status. Claude displays the output directly.
"""

import json
import os
import re
import subprocess
import sys

# Path setup — reuse shared modules from hooks
CLAUDE_DIR = os.path.join(os.path.expanduser("~"), ".claude")
HOOKS_DIR = os.path.join(CLAUDE_DIR, "hooks")
GATES_DIR = os.path.join(HOOKS_DIR, "gates")
SKILLS_DIR = os.path.join(CLAUDE_DIR, "skills")
LIVE_STATE_FILE = os.path.join(CLAUDE_DIR, "LIVE_STATE.json")
SETTINGS_FILE = os.path.join(CLAUDE_DIR, "settings.json")
HANDOFF_FILE = os.path.join(CLAUDE_DIR, "HANDOFF.md")
STATS_CACHE = os.path.join(CLAUDE_DIR, "stats-cache.json")

sys.path.insert(0, HOOKS_DIR)
from shared.chromadb_socket import is_worker_available, count as socket_count, WorkerUnavailable

# Import reusable functions from statusline
from statusline import (
    count_gates,
    count_skills,
    count_hook_events,
    calculate_health,
    get_memory_count,
)

# Dashboard box dimensions
BOX_WIDTH = 50  # inner character width (between the two box-drawing verticals)


def pad_line(label, value, width=BOX_WIDTH):
    """Format a dashboard line: two-space indent, label: value, padded to width."""
    content = f"  {label}: {value}"
    if len(content) > width - 1:
        content = content[: width - 2] + "~"
    padded = content.ljust(width - 1)
    return f"\u2551{padded}\u2551"


def load_live_state():
    """Load LIVE_STATE.json, returning empty dict on failure."""
    try:
        with open(LIVE_STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def get_handoff_summary():
    """Read first 10 lines after '## What Was Done' from HANDOFF.md."""
    try:
        with open(HANDOFF_FILE) as f:
            lines = f.readlines()
    except (FileNotFoundError, OSError):
        return "none"

    capture = False
    collected = []
    for line in lines:
        if "## What Was Done" in line:
            capture = True
            continue
        if capture:
            if line.startswith("## ") and "What Was Done" not in line:
                break
            stripped = line.strip()
            # Skip markdown sub-headers (### lines)
            if stripped.startswith("#"):
                continue
            if stripped:
                # Strip leading markdown list markers
                cleaned = re.sub(r"^[-*]\s+", "", stripped)
                collected.append(cleaned)
            if len(collected) >= 10:
                break

    if not collected:
        return "none"
    # Join and truncate to fit box
    return "; ".join(collected)


def get_gate_metrics():
    """Read gate metrics from most recent state_*.json, fallback to LIVE_STATE."""
    import glob as globmod

    pattern = os.path.join(HOOKS_DIR, "state_*.json")
    files = globmod.glob(pattern)
    if files:
        files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
        try:
            with open(files[0]) as f:
                state = json.load(f)
            return {
                "reads": state.get("files_read_count", 0),
                "edits": state.get("files_edited_count", 0),
                "errors": sum(state.get("error_pattern_counts", {}).values()) if state.get("error_pattern_counts") else 0,
                "verified": len(state.get("verified_fixes", [])),
            }
        except (json.JSONDecodeError, OSError):
            pass

    # Fallback to LIVE_STATE
    ls = load_live_state()
    return ls.get("last_session_metrics", {"reads": 0, "edits": 0, "errors": 0, "verified": 0})


def get_test_count():
    """Count test invocations in test_framework.py by matching '    test(' pattern."""
    test_file = os.path.join(HOOKS_DIR, "test_framework.py")
    try:
        with open(test_file) as f:
            content = f.read()
        return len(re.findall(r"^\s+test\(", content, re.MULTILINE))
    except (FileNotFoundError, OSError):
        return 0


def get_git_status():
    """Get git status (clean/dirty + count) and branch name."""
    status = "unknown"
    branch = "unknown"
    try:
        result = subprocess.run(
            ["git", "-C", CLAUDE_DIR, "status", "--porcelain"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            lines = [l for l in result.stdout.strip().splitlines() if l.strip()]
            if lines:
                status = f"dirty ({len(lines)} files)"
            else:
                status = "clean"
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    try:
        result = subprocess.run(
            ["git", "-C", CLAUDE_DIR, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            branch = result.stdout.strip() or "unknown"
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    return status, branch


def main():
    """Gather all data and print the dashboard."""
    # 1. LIVE_STATE
    ls = load_live_state()
    project_name = ls.get("project", "") or "claude"
    session_count = ls.get("session_count", "?")
    known_issues = ls.get("known_issues", [])
    next_steps = ls.get("next_steps", [])

    # 2. HANDOFF summary
    handoff_summary = get_handoff_summary()

    # 3. Memory count
    try:
        mem_count = get_memory_count()
    except Exception:
        mem_count = "?"

    # 4. Gate count
    try:
        gates = count_gates()
    except Exception:
        gates = 0

    # 5. Skill count
    try:
        skills = count_skills()
    except Exception:
        skills = 0

    # 6. Hook event count
    try:
        hooks = count_hook_events()
    except Exception:
        hooks = 0

    # 7. Test count
    try:
        test_count = get_test_count()
    except Exception:
        test_count = 0

    # 8. Health
    try:
        health = calculate_health(gates, mem_count)
    except Exception:
        health = "?"

    # 9. Git status
    try:
        git_status, branch = get_git_status()
    except Exception:
        git_status, branch = "unknown", "unknown"

    # Format multi-value fields
    issues_str = ", ".join(known_issues) if known_issues else "none"
    next_str = ", ".join(next_steps) if next_steps else "none"

    # Build dashboard
    border_top = f"\u2554{'=' * BOX_WIDTH}\u2557"
    border_mid = f"\u2560{'=' * BOX_WIDTH}\u2563"
    border_bot = f"\u255a{'=' * BOX_WIDTH}\u255d"

    # Title line
    title = "  SYSTEM STATUS"
    title_line = f"\u2551{title.ljust(BOX_WIDTH - 1)}\u2551"

    lines = [
        border_top,
        title_line,
        border_mid,
        pad_line("Project", project_name),
        pad_line("Session", f"{session_count} | Health: {health}%"),
        pad_line("Gates", f"{gates} | Hooks: {hooks} | Skills: {skills}"),
        pad_line("Memories", f"{mem_count} | Tests: {test_count}"),
        pad_line("Git", f"{git_status} | Branch: {branch}"),
        border_mid,
        pad_line("Last Session", handoff_summary),
        pad_line("Known Issues", issues_str),
        pad_line("Next Steps", next_str),
        border_bot,
    ]

    print("\n".join(lines))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Status dashboard error: {exc}", file=sys.stderr)
        print("SYSTEM STATUS: gather failed")
