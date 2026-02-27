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
WRITE_FRESHNESS_WINDOW = 600   # 10 minutes — Write gets more time (large file composition)

# Tools that require recent memory query
GATED_TOOLS = {"Edit", "Write", "NotebookEdit", "Task"}

# Read-only subagent types — no Edit/Write/Bash, can't modify files
READ_ONLY_AGENTS = {"researcher", "Explore"}

from shared.exemptions import is_exempt_base as is_exempt


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

    # Check file exemptions (only when a file_path is present — Task calls have none)
    file_path = tool_input.get("file_path", "") or tool_input.get("notebook_path", "")
    if file_path and is_exempt(file_path):
        # Track exemption for observability
        exempt_stats = state.setdefault("gate4_exemptions", {})
        basename = os.path.basename(file_path)
        exempt_stats[basename] = exempt_stats.get(basename, 0) + 1
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # F2e: Write to non-existent file (new file creation) is exempt from staleness
    # window IF memory was queried at least once this session. This prevents the
    # staleness loop where subagents research, compose, then get blocked by Write.
    if tool_name == "Write" and file_path and not os.path.exists(file_path):
        if get_memory_last_queried(state) > 0:
            return GateResult(blocked=False, gate_name=GATE_NAME)
        # Memory never queried — fall through to normal block

    # Check if memory was queried recently (checks both enforcer state AND MCP sideband file)
    last_query = get_memory_last_queried(state)
    elapsed = time.time() - last_query

    # F3: Per-tool freshness windows — Write gets 10 min (composition takes longer)
    base_window = WRITE_FRESHNESS_WINDOW if tool_name == "Write" else MEMORY_FRESHNESS_WINDOW
    freshness_window = state.get("gate_tune_overrides", {}).get("gate_04_memory_first", {}).get("freshness_window", base_window)
    if elapsed > freshness_window:
        if last_query == 0:
            msg = f"[{GATE_NAME}] BLOCKED: Query memory before editing. Use search_knowledge() to check for existing knowledge about what you're changing."
        else:
            minutes = int(elapsed / 60)
            msg = f"[{GATE_NAME}] BLOCKED: Memory last queried {minutes} min ago. Query memory again before editing (stale knowledge window)."
        return GateResult(blocked=True, message=msg, gate_name=GATE_NAME)

    return GateResult(blocked=False, gate_name=GATE_NAME)
