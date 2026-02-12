#!/usr/bin/env python3
"""Self-Healing Claude Framework — Enforcer

Central dispatcher for all quality gates. Runs as a Claude Code hook
on PreToolUse events. Checks gates BEFORE a tool executes and can block
via sys.exit(1).

PostToolUse tracking has been moved to tracker.py (fail-open, always exit 0).

Each agent (main or team member) gets its own state file, keyed by the session_id
that Claude Code passes in the hook data. This prevents parallel agents from
contaminating each other's gate checks.

Usage (called by Claude Code hooks):
  echo '{"session_id":"abc","tool_name":"Edit","tool_input":{...}}' | python enforcer.py --event PreToolUse
"""

import importlib
import json
import os
import sys

# Add parent to path for shared imports
sys.path.insert(0, os.path.dirname(__file__))
from shared.state import load_state
from shared.gate_result import GateResult
from shared.audit_log import log_gate_decision

# Gate modules to load (in order of priority)
GATE_MODULES = [
    "gates.gate_01_read_before_edit",
    "gates.gate_02_no_destroy",
    "gates.gate_03_test_before_deploy",
    "gates.gate_04_memory_first",
    "gates.gate_05_proof_before_fixed",
    "gates.gate_06_save_fix",
    "gates.gate_07_critical_file_guard",
    "gates.gate_08_temporal",
    "gates.gate_09_strategy_ban",
    "gates.gate_10_model_enforcement",
    "gates.gate_11_rate_limit",
    "gates.gate_12_plan_mode_save",
]

# Tier 1 safety gates that MUST fail-closed (exceptions = block, not pass)
TIER1_SAFETY_GATES = {
    "gates.gate_01_read_before_edit",
    "gates.gate_02_no_destroy",
    "gates.gate_03_test_before_deploy",
}

# Tools that are always allowed (never gated)
ALWAYS_ALLOWED_TOOLS = {
    "Read", "Glob", "Grep", "WebFetch", "WebSearch",
    "AskUserQuestion", "EnterPlanMode", "ExitPlanMode",
    "TaskCreate", "TaskUpdate", "TaskList", "TaskGet",
    "TeamCreate", "TeamDelete", "SendMessage", "TaskOutput", "TaskStop",
}

# MCP memory tools are always allowed
MEMORY_TOOL_PREFIXES = [
    "mcp__memory__",
    "mcp_memory_",
]


def is_memory_tool(tool_name):
    for prefix in MEMORY_TOOL_PREFIXES:
        if tool_name.startswith(prefix):
            return True
    return False


def is_always_allowed(tool_name):
    return tool_name in ALWAYS_ALLOWED_TOOLS or is_memory_tool(tool_name)


def load_gates():
    """Dynamically load all available gate modules."""
    gates = []
    for module_name in GATE_MODULES:
        try:
            mod = importlib.import_module(module_name)
            if hasattr(mod, "check"):
                gates.append(mod)
        except ImportError as e:
            # Non-Tier-1 gate: log warning so missing gates are visible
            # Tier 1 missing gates are caught by the check below (fail-closed)
            if module_name not in TIER1_SAFETY_GATES:
                print(f"[ENFORCER] Warning: Gate '{module_name}' failed to load: {e}", file=sys.stderr)

    # Verify all Tier 1 safety gates loaded successfully (fail-closed)
    loaded_names = {gate.__name__ for gate in gates}
    missing_tier1 = TIER1_SAFETY_GATES - loaded_names
    if missing_tier1:
        print(
            f"[ENFORCER] BLOCKED: Tier 1 safety gate(s) failed to load: {', '.join(sorted(missing_tier1))}",
            file=sys.stderr,
        )
        sys.exit(1)

    return gates


def handle_pre_tool_use(tool_name, tool_input, state):
    """Run all gates before a tool call. Block if any gate fails."""
    if is_always_allowed(tool_name):
        return

    gates = load_gates()
    for gate in gates:
        try:
            result = gate.check(tool_name, tool_input, state, event_type="PreToolUse")
            gate_label = getattr(gate, "GATE_NAME", gate.__name__)
            session_id = state.get("_session_id", "")
            if result.blocked:
                log_gate_decision(gate_label, tool_name, "block", result.message, session_id)
                print(result.message, file=sys.stderr)
                sys.exit(1)
            elif result.message:
                log_gate_decision(gate_label, tool_name, "warn", result.message, session_id)
            else:
                log_gate_decision(gate_label, tool_name, "pass", "", session_id)
        except Exception as e:
            if gate.__name__ in TIER1_SAFETY_GATES:
                # Tier 1 safety gates MUST fail-closed — if we can't verify safety, block
                log_gate_decision(gate.__name__, tool_name, "block", f"crash: {e}", state.get("_session_id", ""))
                print(f"[ENFORCER] BLOCKED: Tier 1 safety gate '{gate.__name__}' crashed: {e}", file=sys.stderr)
                sys.exit(1)
            # Non-safety gate errors should not block work — log and continue
            print(f"[ENFORCER] Warning: Gate error in {gate.__name__}: {e}", file=sys.stderr)


def main():
    # Read tool call data from stdin (Claude Code hook protocol)
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        # Fail-closed: malformed input must not bypass gates
        print("[ENFORCER] BLOCKED: Malformed or missing JSON input", file=sys.stderr)
        sys.exit(1)

    tool_name = data.get("tool_name", "")
    if not tool_name:
        # Fail-closed: missing tool_name must not bypass gates
        print("[ENFORCER] BLOCKED: Missing or empty tool_name", file=sys.stderr)
        sys.exit(1)

    tool_input = data.get("tool_input", {})

    # Fail-closed for write-like tools with missing/empty tool_input
    if tool_name in ("Bash", "Edit", "Write", "NotebookEdit"):
        if not tool_input:
            print(f"[ENFORCER] BLOCKED: Missing or empty tool_input for {tool_name}", file=sys.stderr)
            sys.exit(1)

    session_id = data.get("session_id", "main")

    state = load_state(session_id=session_id)
    state["_session_id"] = session_id

    handle_pre_tool_use(tool_name, tool_input, state)


if __name__ == "__main__":
    main()
