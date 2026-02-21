"""Gate 4: MEMORY FIRST (Tier 2 — Quality)

Blocks code edits and task spawning if memory hasn't been queried in
the last 5 minutes. This ensures Claude always checks existing knowledge
before making changes, preventing repeated mistakes.

This gate is what transforms Claude from an amnesiac into a system
that learns from its own history.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.gate_result import GateResult
from shared.state import get_memory_last_queried

GATE_NAME = "GATE 4: MEMORY FIRST"

# Max time (seconds) since last memory query before edits are blocked
MEMORY_FRESHNESS_WINDOW = 300  # 5 minutes

# Tools that require recent memory query
GATED_TOOLS = {"Edit", "Write", "NotebookEdit", "Task"}

# Read-only subagent types — no Edit/Write/Bash, can't modify files
READ_ONLY_AGENTS = {"researcher", "Explore"}

# Files exempt by basename
EXEMPT_BASENAMES = {"state.json", "HANDOFF.md", "LIVE_STATE.json", "CLAUDE.md"}

# Directories exempt by normalized path prefix
EXEMPT_DIRS = [
    os.path.join(os.path.expanduser("~"), ".claude", "skills"),
]


def is_exempt(file_path):
    if os.path.basename(file_path) in EXEMPT_BASENAMES:
        return True
    norm = os.path.normpath(file_path)
    for d in EXEMPT_DIRS:
        nd = os.path.normpath(d)
        if norm.startswith(nd + os.sep) or norm == nd:
            return True
    return False


def check(tool_name, tool_input, state, event_type="PreToolUse"):
    if event_type != "PreToolUse":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if tool_name not in GATED_TOOLS:
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if not isinstance(tool_input, dict):
        tool_input = {}

    # Read-only subagents don't edit files — skip memory freshness check
    if tool_name == "Task":
        subagent_type = tool_input.get("subagent_type", "")
        if subagent_type in READ_ONLY_AGENTS:
            return GateResult(blocked=False, gate_name=GATE_NAME)

    # Check file exemptions
    file_path = tool_input.get("file_path", "") or tool_input.get("notebook_path", "")
    if is_exempt(file_path):
        # Track exemption for observability
        exempt_stats = state.setdefault("gate4_exemptions", {})
        basename = os.path.basename(file_path)
        exempt_stats[basename] = exempt_stats.get(basename, 0) + 1
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Check if memory was queried recently (checks both enforcer state AND MCP sideband file)
    last_query = get_memory_last_queried(state)
    elapsed = time.time() - last_query

    freshness_window = state.get("gate_tune_overrides", {}).get("gate_04_memory_first", {}).get("freshness_window", MEMORY_FRESHNESS_WINDOW)
    if elapsed > freshness_window:
        if last_query == 0:
            msg = f"[{GATE_NAME}] BLOCKED: Query memory before editing. Use search_knowledge() to check for existing knowledge about what you're changing."
        else:
            minutes = int(elapsed / 60)
            msg = f"[{GATE_NAME}] BLOCKED: Memory last queried {minutes} min ago. Query memory again before editing (stale knowledge window)."
        return GateResult(blocked=True, message=msg, gate_name=GATE_NAME)

    return GateResult(blocked=False, gate_name=GATE_NAME)
