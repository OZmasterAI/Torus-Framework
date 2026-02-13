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
import time

# Add parent to path for shared imports
sys.path.insert(0, os.path.dirname(__file__))
from shared.state import load_state, save_state
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


# ── Gate Dependency Graph ────────────────────────────────────────
# Documents which state keys each gate reads/writes, useful for
# debugging state interactions and dashboard visualization.

GATE_DEPENDENCIES = {
    "gate_01_read_before_edit": {
        "reads": ["files_read"],
        "writes": [],
    },
    "gate_02_no_destroy": {
        "reads": [],
        "writes": [],
    },
    "gate_03_test_before_deploy": {
        "reads": ["last_test_run", "last_test_exit_code"],
        "writes": [],
    },
    "gate_04_memory_first": {
        "reads": ["memory_last_queried"],
        "writes": [],
    },
    "gate_05_proof_before_fixed": {
        "reads": ["pending_verification", "verification_scores"],
        "writes": [],
    },
    "gate_06_save_fix": {
        "reads": ["gate6_warn_count", "verified_fixes", "unlogged_errors", "error_pattern_counts", "pending_chain_ids"],
        "writes": ["gate6_warn_count"],
    },
    "gate_07_critical_file_guard": {
        "reads": ["memory_last_queried"],
        "writes": [],
    },
    "gate_08_temporal": {
        "reads": ["session_start", "memory_last_queried"],
        "writes": [],
    },
    "gate_09_strategy_ban": {
        "reads": ["current_strategy_id", "active_bans", "successful_strategies"],
        "writes": [],
    },
    "gate_10_model_enforcement": {
        "reads": [],
        "writes": [],
    },
    "gate_11_rate_limit": {
        "reads": ["tool_call_count", "session_start"],
        "writes": [],
    },
    "gate_12_plan_mode_save": {
        "reads": ["last_exit_plan_mode", "memory_last_queried"],
        "writes": [],
    },
}


def get_gate_dependencies():
    """Return the full gate dependency graph.

    Returns a dict mapping gate names to their state reads/writes.
    """
    return GATE_DEPENDENCIES


# ── Hot-Reload State ─────────────────────────────────────────────
# Track gate module file modification times for live reloading.
# Only check filesystem every RELOAD_CHECK_INTERVAL seconds.

RELOAD_CHECK_INTERVAL = 30  # seconds between mtime checks
_gate_mtimes = {}           # module_name -> last known mtime
_last_reload_check = 0.0    # timestamp of last mtime scan


def _get_gate_file_path(module_name):
    """Convert dotted module name to file path relative to hooks dir."""
    hooks_dir = os.path.dirname(__file__)
    parts = module_name.split(".")
    return os.path.join(hooks_dir, *parts) + ".py"


def _check_and_reload_gates():
    """Check if any gate files have been modified and reload them.

    Only checks filesystem every RELOAD_CHECK_INTERVAL seconds.
    Logs reloaded gates to audit trail.
    """
    global _last_reload_check, _gate_mtimes

    now = time.time()
    if now - _last_reload_check < RELOAD_CHECK_INTERVAL:
        return  # Too soon to check again

    _last_reload_check = now

    for module_name in GATE_MODULES:
        try:
            filepath = _get_gate_file_path(module_name)
            if not os.path.isfile(filepath):
                continue
            current_mtime = os.path.getmtime(filepath)
            stored_mtime = _gate_mtimes.get(module_name)

            if stored_mtime is not None and current_mtime > stored_mtime:
                # File has changed — reload the module
                if module_name in sys.modules:
                    mod = sys.modules[module_name]
                    importlib.reload(mod)
                    log_gate_decision(
                        module_name, "reload", "pass",
                        f"Gate reloaded (file modified, mtime {current_mtime:.0f})",
                        "",
                        severity="info",
                    )

            _gate_mtimes[module_name] = current_mtime
        except Exception:
            pass  # Reload failures are non-fatal


def load_gates():
    """Dynamically load all available gate modules, with hot-reload support."""
    # Check for modified gate files before loading
    _check_and_reload_gates()

    gates = []
    for module_name in GATE_MODULES:
        try:
            mod = importlib.import_module(module_name)
            if hasattr(mod, "check"):
                gates.append(mod)
                # Record initial mtime if not yet tracked
                if module_name not in _gate_mtimes:
                    try:
                        filepath = _get_gate_file_path(module_name)
                        _gate_mtimes[module_name] = os.path.getmtime(filepath)
                    except OSError:
                        pass
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
            t0 = time.time()
            result = gate.check(tool_name, tool_input, state, event_type="PreToolUse")
            elapsed_ms = (time.time() - t0) * 1000
            gate_label = getattr(gate, "GATE_NAME", gate.__name__)
            session_id = state.get("_session_id", "")

            # Look up state key dependencies for this gate
            gate_short = gate.__name__.split(".")[-1]  # e.g., "gate_01_read_before_edit"
            deps = GATE_DEPENDENCIES.get(gate_short, {})
            state_keys_read = deps.get("reads", [])

            # Update gate timing stats
            timing = state.setdefault("gate_timing_stats", {})
            entry = timing.setdefault(gate_short, {"count": 0, "total_ms": 0.0, "min_ms": 999999, "max_ms": 0.0})
            entry["count"] += 1
            entry["total_ms"] += elapsed_ms
            entry["min_ms"] = min(entry["min_ms"], elapsed_ms)
            entry["max_ms"] = max(entry["max_ms"], elapsed_ms)

            if elapsed_ms > 100:
                log_gate_decision(gate_label, tool_name, "slow",
                                  f"gate took {elapsed_ms:.0f}ms (>100ms threshold)", session_id, state_keys_read,
                                  severity="warn")
            if result.blocked:
                log_gate_decision(gate_label, tool_name, "block", result.message, session_id, state_keys_read,
                                  severity=result.severity)
                # Track gate block counts for diagnostics
                block_counts = state.setdefault("gate_block_counts", {})
                block_counts[gate_short] = block_counts.get(gate_short, 0) + 1
                print(result.message, file=sys.stderr)
                save_state(state, session_id=state.get("_session_id", "main"))
                sys.exit(1)
            elif result.message:
                log_gate_decision(gate_label, tool_name, "warn", result.message, session_id, state_keys_read,
                                  severity="warn")
            else:
                log_gate_decision(gate_label, tool_name, "pass", "", session_id, state_keys_read,
                                  severity="info")
        except Exception as e:
            if gate.__name__ in TIER1_SAFETY_GATES:
                # Tier 1 safety gates MUST fail-closed — if we can't verify safety, block
                # Look up state keys for crashed gate too
                gate_short = gate.__name__.split(".")[-1]
                deps = GATE_DEPENDENCIES.get(gate_short, {})
                state_keys_read = deps.get("reads", [])
                log_gate_decision(gate.__name__, tool_name, "block", f"crash: {e}", state.get("_session_id", ""), state_keys_read,
                                  severity="error")
                print(f"[ENFORCER] BLOCKED: Tier 1 safety gate '{gate.__name__}' crashed: {e}", file=sys.stderr)
                save_state(state, session_id=state.get("_session_id", "main"))
                sys.exit(1)
            # Non-safety gate errors should not block work — log and continue
            gate_short = gate.__name__.split(".")[-1]
            deps = GATE_DEPENDENCIES.get(gate_short, {})
            state_keys_read = deps.get("reads", [])
            log_gate_decision(gate.__name__, tool_name, "crash", f"crash: {e}", state.get("_session_id", ""), state_keys_read,
                              severity="warn")
            print(f"[ENFORCER] Warning: Gate error in {gate.__name__}: {e}", file=sys.stderr)

    # Save timing stats after all gates complete (normal path)
    save_state(state, session_id=state.get("_session_id", "main"))


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
