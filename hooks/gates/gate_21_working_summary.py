"""Gate 21: WORKING SUMMARY (Tier 2 — Quality)

Blocks code edits after context threshold fires until Claude writes
a working summary via /working-summary skill. This ensures critical
context is preserved before compaction.

Gated tools: Edit, Write, NotebookEdit, Bash, Task
Always allowed: Read, Grep, Glob, WebSearch, WebFetch, Skill, memory tools
Always allowed: Write to working-summary.md itself
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.gate_result import GateResult
from shared.gate_helpers import extract_file_path, safe_tool_input
from shared.exemptions import is_exempt_base as is_exempt

GATE_NAME = "GATE 21: WORKING SUMMARY"

SUMMARY_PATH = os.path.join(
    os.path.expanduser("~"), ".claude", "rules", "working-summary.md"
)
MIN_SUMMARY_CHARS = 2000

GATED_TOOLS = {"Edit", "Write", "NotebookEdit", "Bash", "Task"}
ALWAYS_ALLOWED = {"Read", "Grep", "Glob", "WebSearch", "WebFetch", "Skill"}


def _get_summary_size():
    """Return file size of working-summary.md, 0 if missing."""
    try:
        if os.path.exists(SUMMARY_PATH):
            return os.path.getsize(SUMMARY_PATH)
        return 0
    except Exception:
        return 0


def check(tool_name, tool_input, state, event_type="PreToolUse",
          _summary_size_override=None):
    if event_type != "PreToolUse":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Only activate after threshold fires
    if not state.get("summary_threshold_fired", False):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Always allow read-only and meta tools
    if tool_name in ALWAYS_ALLOWED:
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Always allow memory tools (needed to gather context for summary)
    if tool_name.startswith("mcp__memory__") or tool_name.startswith("mcp_memory_"):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Not a gated tool — allow
    if tool_name not in GATED_TOOLS:
        return GateResult(blocked=False, gate_name=GATE_NAME)

    tool_input = safe_tool_input(tool_input)

    # Allow writes to working-summary.md itself
    file_path = extract_file_path(tool_input)
    if file_path and os.path.basename(file_path) == "working-summary.md":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Check exemptions
    if file_path and is_exempt(file_path):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Check if summary has been written (>2000 chars)
    size = (_summary_size_override if _summary_size_override is not None
            else _get_summary_size())
    if size >= MIN_SUMMARY_CHARS:
        return GateResult(blocked=False, gate_name=GATE_NAME)

    return GateResult(
        blocked=True,
        message=(
            f"[{GATE_NAME}] BLOCKED: Context threshold reached (~65%). "
            f"Write a working summary before continuing. "
            f"Run /working-summary to capture context, then resume work."
        ),
        gate_name=GATE_NAME,
        severity="warn",
    )
