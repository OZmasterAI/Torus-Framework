#!/usr/bin/env python3
"""Self-Healing Claude Framework — Boot Sequence

Runs on SessionStart to:
1. Load handoff context from previous session
2. Load live state
3. Display a dashboard with project status
4. Reset enforcement state for new session
5. Set edits locked until memory is queried

This ensures every session starts with full context rather than amnesia.
"""

import json
import os
import sys
from datetime import datetime

# Add hooks dir to path for shared imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from shared.state import cleanup_all_states

CLAUDE_DIR = os.path.join(os.path.expanduser("~"), ".claude")
HANDOFF_FILE = os.path.join(CLAUDE_DIR, "HANDOFF.md")
LIVE_STATE_FILE = os.path.join(CLAUDE_DIR, "LIVE_STATE.json")


def read_file(path):
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        return None


def extract_summary(handoff_content):
    """Extract the first meaningful line from HANDOFF.md as a summary."""
    if not handoff_content:
        return "No handoff file found"
    for line in handoff_content.split("\n"):
        line = line.strip()
        if line and not line.startswith("#") and not line.startswith("---"):
            return line[:70]
    return "Handoff exists but no summary found"


def extract_session_number(handoff_content):
    """Try to find session number from handoff."""
    if not handoff_content:
        return "?"
    for line in handoff_content.split("\n"):
        if "session" in line.lower() and any(c.isdigit() for c in line):
            digits = "".join(c for c in line if c.isdigit())
            if digits:
                return digits[:4]
    return "?"


def load_live_state():
    content = read_file(LIVE_STATE_FILE)
    if content:
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {}
    return {}


def reset_enforcement_state():
    """Reset all gate enforcement state files for a new session.

    Cleans up per-agent state files from the previous session (each team member
    had its own state_*.json file) and the legacy shared state.json.
    The new session's main agent will create its own state file on first tool use.
    """
    cleanup_all_states()


def main():
    now = datetime.now()
    hour = now.hour
    day = now.strftime("%A")

    # Load context
    handoff = read_file(HANDOFF_FILE)
    live_state = load_live_state()
    session_num = extract_session_number(handoff)
    summary = extract_summary(handoff)

    # Time-based warnings
    time_warning = ""
    if 1 <= hour <= 5:
        time_warning = "  !! LATE NIGHT — Extra caution required !!"
    elif hour >= 22:
        time_warning = "  -- Late evening session --"

    # Project name from live state
    project_name = live_state.get("project", "Self-Healing Claude")
    active_tasks = live_state.get("active_tasks", [])

    # Gate count
    gates_dir = os.path.join(CLAUDE_DIR, "hooks", "gates")
    gate_count = 0
    if os.path.isdir(gates_dir):
        gate_count = len([f for f in os.listdir(gates_dir) if f.startswith("gate_") and f.endswith(".py")])

    # Build dashboard
    dashboard = f"""
+====================================================================+
|  {project_name:<20} | Session {session_num:<6} | {day} {hour:02d}:{now.minute:02d}             |
|====================================================================|
|  LAST SESSION: {summary:<53}|
|--------------------------------------------------------------------|
|  GATES ACTIVE: {gate_count:<3} | MEMORY: ~/data/memory/                     |
|--------------------------------------------------------------------|"""

    if time_warning:
        dashboard += f"\n|  {time_warning:<67}|"
        dashboard += "\n|--------------------------------------------------------------------|"

    if active_tasks:
        dashboard += "\n|  ACTIVE TASKS:                                                     |"
        for task in active_tasks[:3]:
            dashboard += f"\n|    - {task:<63}|"
        dashboard += "\n|--------------------------------------------------------------------|"

    dashboard += """
|  TIP: Query memory about your task before starting work.           |
+====================================================================+
"""

    # Print to stderr (Claude Code displays this as hook output)
    print(dashboard, file=sys.stderr)

    # Reset state
    reset_enforcement_state()

    # Reset sideband memory timestamp file
    sideband_file = os.path.join(os.path.dirname(__file__), ".memory_last_queried")
    try:
        os.remove(sideband_file)
    except OSError:
        pass


if __name__ == "__main__":
    main()
