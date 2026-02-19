#!/usr/bin/env python3
"""Self-Healing Claude Framework — Enforcer

Central dispatcher for all quality gates. Runs as a Claude Code hook
on PreToolUse events. Checks gates BEFORE a tool executes and can block
via sys.exit(2) (Claude Code's mechanical block exit code).

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
from shared.state import load_state, save_state, update_gate_effectiveness
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
    # "gates.gate_08_temporal",  # DORMANT — re-enable by uncommenting
    "gates.gate_09_strategy_ban",
    "gates.gate_10_model_enforcement",
    "gates.gate_11_rate_limit",
    "gates.gate_12_plan_mode_save",
    "gates.gate_13_workspace_isolation",
    "gates.gate_14_confidence_check",
    "gates.gate_15_causal_chain",
    "gates.gate_16_code_quality",
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
    "TeamCreate", "TeamDelete", "SendMessage", "TaskStop",
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
    # "gate_08_temporal": {  # DORMANT
    #     "reads": ["session_start", "memory_last_queried"],
    #     "writes": [],
    # },
    "gate_09_strategy_ban": {
        "reads": ["current_strategy_id", "active_bans", "successful_strategies"],
        "writes": [],
    },
    "gate_10_model_enforcement": {
        "reads": [],
        "writes": ["model_agent_usage"],
    },
    "gate_11_rate_limit": {
        "reads": ["tool_call_count", "session_start"],
        "writes": [],
    },
    "gate_12_plan_mode_save": {
        "reads": ["last_exit_plan_mode", "memory_last_queried"],
        "writes": [],
    },
    "gate_13_workspace_isolation": {
        "reads": [],
        "writes": [],
    },
    "gate_14_confidence_check": {
        "reads": ["session_test_baseline", "pending_verification", "memory_last_queried", "confidence_warnings_per_file"],
        "writes": ["confidence_warnings_per_file", "confidence_warned_signals"],
    },
    "gate_15_causal_chain": {
        "reads": ["recent_test_failure", "fix_history_queried", "fixing_error"],
        "writes": [],
    },
    "gate_16_code_quality": {
        "reads": ["code_quality_warnings_per_file"],
        "writes": ["code_quality_warnings_per_file"],
    },
}


def get_gate_dependencies():
    """Return the full gate dependency graph.

    Returns a dict mapping gate names to their state reads/writes.
    """
    return GATE_DEPENDENCIES


# ── Tool-Scoped Gate Dispatch ─────────────────────────────────────
# Maps gate module name → set of tools it watches.
# None = watches all tools (universal gate).
GATE_TOOL_MAP = {
    "gates.gate_01_read_before_edit": {"Edit", "Write", "NotebookEdit"},
    "gates.gate_02_no_destroy": {"Bash"},
    "gates.gate_03_test_before_deploy": {"Bash"},
    "gates.gate_04_memory_first": {"Edit", "Write", "NotebookEdit", "Task"},
    "gates.gate_05_proof_before_fixed": {"Edit", "Write", "NotebookEdit"},
    "gates.gate_06_save_fix": {"Edit", "Write", "Task", "Bash"},
    "gates.gate_07_critical_file_guard": {"Edit", "Write", "NotebookEdit"},
    "gates.gate_09_strategy_ban": {"Edit", "Write", "NotebookEdit"},
    "gates.gate_10_model_enforcement": {"Task"},
    "gates.gate_11_rate_limit": None,  # Universal
    "gates.gate_12_plan_mode_save": {"Edit", "Write", "Bash", "NotebookEdit"},
    "gates.gate_13_workspace_isolation": {"Edit", "Write", "NotebookEdit"},
    "gates.gate_14_confidence_check": {"Edit", "Write", "NotebookEdit"},
    "gates.gate_15_causal_chain": {"Edit", "Write", "NotebookEdit"},
    "gates.gate_16_code_quality": {"Edit", "Write", "NotebookEdit"},
}


# ── Gate Cache & Hot-Reload State ────────────────────────────────
# Loaded gate modules are cached after first import.
# Hot-reload checks filesystem every RELOAD_CHECK_INTERVAL seconds.

RELOAD_CHECK_INTERVAL = 30  # seconds between mtime checks
_gate_mtimes = {}           # module_name -> last known mtime
_last_reload_check = 0.0    # timestamp of last mtime scan
_loaded_gates = {}           # module_name -> module (cached after first load)
_gates_loaded = False        # True after first successful full load


def _get_gate_file_path(module_name):
    """Convert dotted module name to file path relative to hooks dir."""
    hooks_dir = os.path.dirname(__file__)
    parts = module_name.split(".")
    return os.path.join(hooks_dir, *parts) + ".py"


def _check_and_reload_gates():
    """Check if any gate files have been modified and reload them.

    Only checks filesystem every RELOAD_CHECK_INTERVAL seconds.
    Logs reloaded gates to audit trail. Updates _loaded_gates cache directly.
    """
    global _last_reload_check, _gate_mtimes, _loaded_gates

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
                    # Update cache directly
                    if hasattr(mod, "check"):
                        _loaded_gates[module_name] = mod
                    log_gate_decision(
                        module_name, "reload", "pass",
                        f"Gate reloaded (file modified, mtime {current_mtime:.0f})",
                        "",
                        severity="info",
                    )

            _gate_mtimes[module_name] = current_mtime
        except Exception:
            pass  # Reload failures are non-fatal


def _ensure_gates_loaded():
    """Load all gate modules once. Called on first use and after hot-reload."""
    global _loaded_gates, _gates_loaded

    # Check for modified gate files (respects RELOAD_CHECK_INTERVAL)
    _check_and_reload_gates()

    if _gates_loaded:
        return

    for module_name in GATE_MODULES:
        try:
            mod = importlib.import_module(module_name)
            if hasattr(mod, "check"):
                _loaded_gates[module_name] = mod
                # Record initial mtime if not yet tracked
                if module_name not in _gate_mtimes:
                    try:
                        filepath = _get_gate_file_path(module_name)
                        _gate_mtimes[module_name] = os.path.getmtime(filepath)
                    except OSError:
                        pass
        except ImportError as e:
            if module_name not in TIER1_SAFETY_GATES:
                print(f"[ENFORCER] Warning: Gate '{module_name}' failed to load: {e}", file=sys.stderr)

    # Verify all Tier 1 safety gates loaded successfully (fail-closed)
    loaded_names = set(_loaded_gates.keys())
    missing_tier1 = TIER1_SAFETY_GATES - loaded_names
    if missing_tier1:
        print(
            f"[ENFORCER] BLOCKED: Tier 1 safety gate(s) failed to load: {', '.join(sorted(missing_tier1))}",
            file=sys.stderr,
        )
        sys.exit(2)

    _gates_loaded = True


def _gates_for_tool(tool_name):
    """Return only gate modules that watch this tool, in priority order."""
    _ensure_gates_loaded()
    result = []
    for module_name in GATE_MODULES:  # Preserves priority order
        mod = _loaded_gates.get(module_name)
        if mod is None:
            continue
        watched = GATE_TOOL_MAP.get(module_name)
        if watched is None or tool_name in watched:
            result.append(mod)
    return result


def load_gates():
    """Legacy wrapper — returns all loaded gates. Kept for backward compatibility."""
    _ensure_gates_loaded()
    return [_loaded_gates[m] for m in GATE_MODULES if m in _loaded_gates]


def handle_pre_tool_use(tool_name, tool_input, state):
    """Run all gates before a tool call. Block if any gate fails."""
    if is_always_allowed(tool_name):
        return

    gates = _gates_for_tool(tool_name)
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
                # Track gate effectiveness (self-evolving) — persistent across sessions
                update_gate_effectiveness(gate_short, "blocks")
                # Record block outcome for later resolution tracking
                file_path = tool_input.get("file_path", "") or tool_input.get("notebook_path", "") or tool_input.get("command", "")[:100]
                outcomes = state.setdefault("gate_block_outcomes", [])
                outcomes.append({"gate": gate_short, "tool": tool_name, "file": file_path, "timestamp": time.time(), "resolved_by": None})
                if len(outcomes) > 100:
                    state["gate_block_outcomes"] = outcomes[-100:]
                print(result.message, file=sys.stderr)
                save_state(state, session_id=state.get("_session_id", "main"))
                sys.exit(2)
            elif result.message:
                log_gate_decision(gate_label, tool_name, "warn", result.message, session_id, state_keys_read,
                                  severity="warn")
            else:
                log_gate_decision(gate_label, tool_name, "pass", "", session_id, state_keys_read,
                                  severity="info")
        except Exception as e:
            gate_label = getattr(gate, "GATE_NAME", gate.__name__)
            if gate.__name__ in TIER1_SAFETY_GATES:
                # Tier 1 safety gates MUST fail-closed — if we can't verify safety, block
                # Look up state keys for crashed gate too
                gate_short = gate.__name__.split(".")[-1]
                deps = GATE_DEPENDENCIES.get(gate_short, {})
                state_keys_read = deps.get("reads", [])
                log_gate_decision(gate_label, tool_name, "block", f"crash: {e}", state.get("_session_id", ""), state_keys_read,
                                  severity="error")
                print(f"[ENFORCER] BLOCKED: Tier 1 safety gate '{gate_label}' crashed: {e}", file=sys.stderr)
                save_state(state, session_id=state.get("_session_id", "main"))
                sys.exit(2)
            # Non-safety gate errors should not block work — log and continue
            gate_short = gate.__name__.split(".")[-1]
            deps = GATE_DEPENDENCIES.get(gate_short, {})
            state_keys_read = deps.get("reads", [])
            log_gate_decision(gate_label, tool_name, "crash", f"crash: {e}", state.get("_session_id", ""), state_keys_read,
                              severity="warn")
            print(f"[ENFORCER] Warning: Gate error in {gate_label}: {e}", file=sys.stderr)

    # Save timing stats after all gates complete (normal path)
    save_state(state, session_id=state.get("_session_id", "main"))


def main():
    # Read tool call data from stdin (Claude Code hook protocol)
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        # Fail-closed: malformed input must not bypass gates
        print("[ENFORCER] BLOCKED: Malformed or missing JSON input", file=sys.stderr)
        sys.exit(2)

    tool_name = data.get("tool_name", "")
    if not tool_name:
        # Fail-closed: missing tool_name must not bypass gates
        print("[ENFORCER] BLOCKED: Missing or empty tool_name", file=sys.stderr)
        sys.exit(2)

    tool_input = data.get("tool_input", {})

    # Fail-closed for write-like tools with missing/empty tool_input
    if tool_name in ("Bash", "Edit", "Write", "NotebookEdit"):
        if not tool_input:
            print(f"[ENFORCER] BLOCKED: Missing or empty tool_input for {tool_name}", file=sys.stderr)
            sys.exit(2)

    session_id = data.get("session_id", "main")

    state = load_state(session_id=session_id)
    state["_session_id"] = session_id

    handle_pre_tool_use(tool_name, tool_input, state)


if __name__ == "__main__":
    main()
