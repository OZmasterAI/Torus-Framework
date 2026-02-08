#!/usr/bin/env python3
"""Self-Healing Claude Framework — Enforcer

Central dispatcher for all quality gates. Runs as a Claude Code hook
on PreToolUse and PostToolUse events.

PreToolUse: Checks gates BEFORE a tool executes. Can block via sys.exit(1).
PostToolUse: Tracks state AFTER a tool executes (what files were read, etc.).

Each agent (main or subagent) gets its own state file, keyed by the session_id
that Claude Code passes in the hook data. This prevents parallel agents from
contaminating each other's gate checks.

Usage (called by Claude Code hooks):
  echo '{"session_id":"abc","tool_name":"Edit","tool_input":{...}}' | python enforcer.py --event PreToolUse
"""

import argparse
import importlib
import json
import os
import re
import sys
import time

# Add parent to path for shared imports
sys.path.insert(0, os.path.dirname(__file__))
from shared.state import load_state, save_state
from shared.gate_result import GateResult

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
        except ImportError:
            # Gate not yet installed — skip silently
            pass

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
            if result.blocked:
                print(result.message, file=sys.stderr)
                sys.exit(1)
        except Exception as e:
            if gate.__name__ in TIER1_SAFETY_GATES:
                # Tier 1 safety gates MUST fail-closed — if we can't verify safety, block
                print(f"[ENFORCER] BLOCKED: Tier 1 safety gate '{gate.__name__}' crashed: {e}", file=sys.stderr)
                sys.exit(1)
            # Non-safety gate errors should not block work — log and continue
            print(f"[ENFORCER] Warning: Gate error in {gate.__name__}: {e}", file=sys.stderr)


def handle_post_tool_use(tool_name, tool_input, state, session_id="main"):
    """Track state after a tool call completes."""
    state["tool_call_count"] = state.get("tool_call_count", 0) + 1

    # Track file reads
    if tool_name == "Read":
        file_path = tool_input.get("file_path", "")
        if file_path and file_path not in state.get("files_read", []):
            state["files_read"].append(file_path)

    # Track memory queries
    if is_memory_tool(tool_name):
        state["memory_last_queried"] = time.time()

    # Track test runs
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        if any(kw in command for kw in ["pytest", "python -m pytest", "npm test", "cargo test", "go test"]):
            state["last_test_run"] = time.time()

    # Track edits for pending verification (including NotebookEdit)
    if tool_name in ("Edit", "Write", "NotebookEdit"):
        file_path = tool_input.get("file_path", "") or tool_input.get("notebook_path", "")
        if file_path and file_path not in state.get("pending_verification", []):
            pending = state.get("pending_verification", [])
            pending.append(file_path)
            state["pending_verification"] = pending

    # Verification clears pending files that match the command context
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        verify_keywords = ["pytest", "python -m pytest", "npm test", "cargo test", "go test",
                          "python ", "node ", "curl ", "systemctl status"]
        if any(kw in command for kw in verify_keywords):
            # Only clear files that are referenced in the command, or all if running a broad test suite
            broad_test_commands = ["pytest", "python -m pytest", "npm test", "cargo test", "go test"]
            if any(kw in command for kw in broad_test_commands):
                # Running a full test suite counts as verifying everything
                verified = state.get("pending_verification", [])
                state["verified_fixes"] = state.get("verified_fixes", []) + verified
                state["pending_verification"] = []
            else:
                # For targeted commands, only clear files mentioned in the command
                pending = state.get("pending_verification", [])
                remaining = []
                for filepath in pending:
                    basename = os.path.basename(filepath)
                    stem = os.path.splitext(basename)[0]
                    matched = (
                        re.search(r'\b' + re.escape(filepath) + r'\b', command)
                        or re.search(r'\b' + re.escape(basename) + r'\b', command)
                        or re.search(r'\b' + re.escape(stem) + r'\b', command)
                    )
                    if matched:
                        state.setdefault("verified_fixes", []).append(filepath)
                    else:
                        remaining.append(filepath)
                state["pending_verification"] = remaining

    save_state(state, session_id=session_id)


def main():
    parser = argparse.ArgumentParser(description="Self-Healing Enforcer")
    parser.add_argument("--event", required=True, choices=["PreToolUse", "PostToolUse"])
    args = parser.parse_args()

    # Read tool call data from stdin (Claude Code hook protocol)
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        # If no data on stdin, nothing to enforce
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    if not tool_name:
        sys.exit(0)
    tool_input = data.get("tool_input", {})
    session_id = data.get("session_id", "main")

    state = load_state(session_id=session_id)
    state["_session_id"] = session_id

    if args.event == "PreToolUse":
        handle_pre_tool_use(tool_name, tool_input, state)
    elif args.event == "PostToolUse":
        handle_post_tool_use(tool_name, tool_input, state, session_id=session_id)


if __name__ == "__main__":
    main()
