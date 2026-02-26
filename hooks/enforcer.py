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

import hashlib
import importlib
import json
import os
import sys
import time

# Add parent to path for shared imports
sys.path.insert(0, os.path.dirname(__file__))
from shared.state import load_state, save_state, update_gate_effectiveness, get_live_toggle
from shared.gate_result import GateResult
from shared.audit_log import log_gate_decision
from shared.circuit_breaker import should_skip_gate, record_gate_result
from shared.gate_router import get_optimal_gate_order, update_qtable, flush_qtable
from shared.gate_timing import record_timing as _record_gate_timing, flush_timings as _flush_timings
from shared.security_profiles import should_skip_for_profile, get_gate_mode_for_profile
from shared.domain_registry import get_effective_gate_mode as _domain_gate_mode


# -- Gate Result Cache ----------------------------------------------------
# Lightweight TTL-based cache for non-blocking gate results.
# Avoids redundant gate evaluation when the same (gate, tool, input)
# tuple is seen within the TTL window (e.g. retried tool calls).
#
# Only non-blocking, non-ask results are cached. Blocked results always
# re-check so the agent can correct the condition and retry freely.
#
# Toggle: set GATE_CACHE_ENABLED = False to disable without code changes.
# Stats:  call get_gate_cache_stats() for hit/miss observability.

GATE_CACHE_ENABLED: bool = True
_GATE_CACHE_TTL_S: float = 60.0  # seconds (gates re-evaluate after TTL)

# key -> {"result": GateResult, "stored_at": float (monotonic)}
_gate_result_cache: dict = {}

# Per-process hit/miss counters for observability
_cache_hits: int = 0
_cache_misses: int = 0

# Fields included in cache key per tool -- only fields that affect gate
# decisions, to avoid spurious cache misses (e.g. new_string in Edit).
_CACHE_KEY_FIELDS: dict = {
    "Edit":         ("file_path", "old_string"),
    "Write":        ("file_path",),
    "NotebookEdit": ("notebook_path", "cell_number"),
    "Bash":         ("command",),
    "Task":         ("model", "subagent_type", "description"),
    "WebFetch":     ("url",),
    "WebSearch":    ("query",),
}
_CACHE_KEY_FIELDS_DEFAULT: tuple = ("file_path", "command", "url", "query")


def _make_cache_key(gate_name: str, tool_name: str, tool_input: dict) -> str:
    """Build a stable 16-char hex cache key (first 64 bits of SHA-256)."""
    fields = _CACHE_KEY_FIELDS.get(tool_name, _CACHE_KEY_FIELDS_DEFAULT)
    relevant = {k: tool_input.get(k, "") for k in fields}
    raw = json.dumps((gate_name, tool_name, relevant), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _get_cached_gate_result(gate_name: str, tool_name: str, tool_input: dict):
    """Return a cached GateResult within TTL, or None on miss/expiry."""
    global _cache_hits, _cache_misses
    if not GATE_CACHE_ENABLED:
        _cache_misses += 1
        return None
    key = _make_cache_key(gate_name, tool_name, tool_input)
    entry = _gate_result_cache.get(key)
    if entry is None:
        _cache_misses += 1
        return None
    if time.monotonic() - entry["stored_at"] > _GATE_CACHE_TTL_S:
        del _gate_result_cache[key]
        _cache_misses += 1
        return None
    _cache_hits += 1
    return entry["result"]


def _store_gate_result(gate_name: str, tool_name: str, tool_input: dict, result) -> None:
    """Cache a non-blocking, non-ask GateResult for future lookups."""
    if not GATE_CACHE_ENABLED:
        return
    if result.blocked or getattr(result, "is_ask", False):
        return  # Never cache blocking/ask results
    key = _make_cache_key(gate_name, tool_name, tool_input)
    _gate_result_cache[key] = {"result": result, "stored_at": time.monotonic()}


def get_gate_cache_stats() -> dict:
    """Return a snapshot of cache observability counters.

    Keys: enabled, ttl_s, hits, misses, hit_rate, cached.
    """
    total = _cache_hits + _cache_misses
    return {
        "enabled": GATE_CACHE_ENABLED,
        "ttl_s": _GATE_CACHE_TTL_S,
        "hits": _cache_hits,
        "misses": _cache_misses,
        "hit_rate": (_cache_hits / total) if total > 0 else 0.0,
        "cached": len(_gate_result_cache),
    }


# Gate modules to load (in priority order — canonical list in shared/gate_registry.py)
from shared.gate_registry import GATE_MODULES

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

# MCP analytics tools are always allowed (read-only)
ANALYTICS_TOOL_PREFIX = "mcp__analytics__"


def is_memory_tool(tool_name):
    for prefix in MEMORY_TOOL_PREFIXES:
        if tool_name.startswith(prefix):
            return True
    return False


def is_analytics_tool(tool_name):
    return tool_name.startswith(ANALYTICS_TOOL_PREFIX)


def is_always_allowed(tool_name):
    return tool_name in ALWAYS_ALLOWED_TOOLS or is_memory_tool(tool_name) or is_analytics_tool(tool_name)


# Tools that bypass most gates but still run Gate 17 (injection defense)
_G17_SCAN_TOOLS = {"WebFetch", "WebSearch"}


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
        "reads": ["gate6_warn_count", "verified_fixes", "unlogged_errors", "error_pattern_counts", "pending_chain_ids", "last_exit_plan_mode", "memory_last_queried"],
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
    # "gate_12_plan_mode_save" — MERGED into gate_06_save_fix (refactor1)
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
    "gate_17_injection_defense": {
        "reads": ["injection_attempts"],
        "writes": ["injection_attempts"],
    },
    "gate_18_canary": {
        "reads": [
            "canary_tool_counts", "canary_seen_tools", "canary_total_calls",
            "canary_size_count", "canary_size_mean", "canary_size_m2",
            "canary_short_timestamps", "canary_long_timestamps", "canary_recent_seq",
        ],
        "writes": [
            "canary_tool_counts", "canary_seen_tools", "canary_total_calls",
            "canary_size_count", "canary_size_mean", "canary_size_m2",
            "canary_short_timestamps", "canary_long_timestamps", "canary_recent_seq",
        ],
    },
    "gate_19_hindsight": {
        "reads": [
            "mentor_last_verdict", "mentor_last_score", "mentor_escalation_count",
            "mentor_chain_score", "mentor_memory_match", "mentor_warned_this_cycle",
            "fixing_error",
        ],
        "writes": [],
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
    "gates.gate_06_save_fix": {"Edit", "Write", "Task", "Bash", "NotebookEdit"},
    "gates.gate_07_critical_file_guard": {"Edit", "Write", "NotebookEdit"},
    "gates.gate_09_strategy_ban": {"Edit", "Write", "NotebookEdit"},
    "gates.gate_10_model_enforcement": {"Task"},
    "gates.gate_11_rate_limit": None,  # Universal
    # "gates.gate_12_plan_mode_save": {"Edit", "Write", "Bash", "NotebookEdit"},  # MERGED into gate_06
    "gates.gate_13_workspace_isolation": {"Edit", "Write", "NotebookEdit"},
    "gates.gate_14_confidence_check": {"Edit", "Write", "NotebookEdit"},
    "gates.gate_15_causal_chain": {"Edit", "Write", "NotebookEdit"},
    "gates.gate_16_code_quality": {"Edit", "Write", "NotebookEdit"},
    "gates.gate_17_injection_defense": {"WebFetch", "WebSearch"},  # + MCP tools checked internally
    "gates.gate_18_canary": None,  # Universal — observes all tool calls
    "gates.gate_19_hindsight": {"Edit", "Write", "NotebookEdit"},
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


def handle_pre_tool_use(tool_name, tool_input, state):
    """Run all gates before a tool call. Block if any gate fails."""
    if is_always_allowed(tool_name):
        # WebFetch/WebSearch bypass most gates but still need G17 injection scanning
        if tool_name not in _G17_SCAN_TOOLS:
            return
        _ensure_gates_loaded()
        g17_key = "gates.gate_17_injection_defense"
        if g17_key in _loaded_gates:
            try:
                result = _loaded_gates[g17_key].check(tool_name, tool_input, state, event_type="PreToolUse")
                if result and result.blocked:
                    print(result.message, file=sys.stderr)
                    sys.exit(2)
            except Exception as e:
                print(f"[ENFORCER] G17 scan error: {e}", file=sys.stderr)
        return

    gates = _gates_for_tool(tool_name)

    # Q-learning: reorder gates (Tier 2 & 3 only) so high-block-probability
    # gates run first, enabling earlier exits.  Tier 1 gates always stay first.
    gate_names = [gate.__name__ for gate in gates]
    ordered_names = get_optimal_gate_order(tool_name, gate_names)
    # Rebuild the gates list in the Q-learning optimised order.
    name_to_gate = {gate.__name__: gate for gate in gates}
    gates = [name_to_gate[n] for n in ordered_names if n in name_to_gate]

    passed_gates = []  # accumulate module names of gates that passed (for qtable update)

    for gate in gates:
        gate_short = gate.__name__.split(".")[-1]
        # Domain + security profile: skip gates disabled by active domain or profile
        try:
            _effective_mode = _domain_gate_mode(gate_short, state)
        except Exception:
            _effective_mode = get_gate_mode_for_profile(gate_short, state)
        if _effective_mode == "disabled":
            continue
        # Circuit breaker: skip gates that have crashed too many times
        if should_skip_gate(gate_short):
            continue
        try:
            _cached = _get_cached_gate_result(gate_short, tool_name, tool_input)
            if _cached is not None:
                result = _cached
                elapsed_ms = 0.0
                record_gate_result(gate_short, success=True)
            else:
                t0 = time.time()
                result = gate.check(tool_name, tool_input, state, event_type="PreToolUse")
                elapsed_ms = (time.time() - t0) * 1000
                record_gate_result(gate_short, success=True)
                _store_gate_result(gate_short, tool_name, tool_input, result)
            gate_label = getattr(gate, "GATE_NAME", gate.__name__)
            session_id = state.get("_session_id", "")

            # Look up state key dependencies (gate_short set above circuit breaker check)
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
            if result.is_ask:
                # Graduated escalation: ask user for permission instead of blocking
                log_gate_decision(gate_label, tool_name, "ask", result.message, session_id, state_keys_read,
                                  severity=result.severity)
                hook_decision = result.to_hook_decision()
                # Q-learning: treat ask as a block (gate did something useful)
                update_qtable(gate.__name__, tool_name, blocked=True)
                try:
                    _record_gate_timing(gate_short, tool_name, elapsed_ms, blocked=True)
                except Exception:
                    pass  # Timing analytics are non-fatal
                print(json.dumps(hook_decision), file=sys.stdout)
                flush_qtable()
                _flush_timings()
                save_state(state, session_id=state.get("_session_id", "main"))
                sys.exit(0)
            elif result.blocked:
                # Domain + security profile: downgrade block to warn if mode says "warn"
                # Tier 1 safety gates are never downgraded regardless of profile/domain
                if _effective_mode == "warn" and gate.__name__ not in TIER1_SAFETY_GATES:
                    log_gate_decision(gate_label, tool_name, "warn",
                                      f"[profile:downgraded] {result.message}",
                                      session_id, state_keys_read, severity="warn")
                    passed_gates.append(gate.__name__)
                    try:
                        _record_gate_timing(gate_short, tool_name, elapsed_ms, blocked=False)
                    except Exception:
                        pass
                    continue
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
                # Q-learning: update qtable — this gate blocked
                update_qtable(gate.__name__, tool_name, blocked=True)
                # Update timing analytics with blocked=True for this execution
                try:
                    _record_gate_timing(gate_short, tool_name, elapsed_ms, blocked=True)
                except Exception:
                    pass  # Timing analytics are non-fatal
                print(result.message, file=sys.stderr)
                flush_qtable()
                _flush_timings()
                save_state(state, session_id=state.get("_session_id", "main"))
                sys.exit(2)
            elif result.message:
                log_gate_decision(gate_label, tool_name, "warn", result.message, session_id, state_keys_read,
                                  severity="warn")
                passed_gates.append(gate.__name__)
                try:
                    _record_gate_timing(gate_short, tool_name, elapsed_ms, blocked=False)
                except Exception:
                    pass  # Timing analytics are non-fatal
            else:
                log_gate_decision(gate_label, tool_name, "pass", "", session_id, state_keys_read,
                                  severity="info")
                passed_gates.append(gate.__name__)
                try:
                    _record_gate_timing(gate_short, tool_name, elapsed_ms, blocked=False)
                except Exception:
                    pass  # Timing analytics are non-fatal
        except Exception as e:
            record_gate_result(gate_short, success=False)
            gate_label = getattr(gate, "GATE_NAME", gate.__name__)
            deps = GATE_DEPENDENCIES.get(gate_short, {})
            state_keys_read = deps.get("reads", [])
            if gate.__name__ in TIER1_SAFETY_GATES:
                log_gate_decision(gate_label, tool_name, "block", f"crash: {e}", state.get("_session_id", ""), state_keys_read,
                                  severity="error")
                print(f"[ENFORCER] BLOCKED: Tier 1 safety gate '{gate_label}' crashed: {e}", file=sys.stderr)
                flush_qtable()
                _flush_timings()
                save_state(state, session_id=state.get("_session_id", "main"))
                sys.exit(2)
            log_gate_decision(gate_label, tool_name, "crash", f"crash: {e}", state.get("_session_id", ""), state_keys_read,
                              severity="warn")
            print(f"[ENFORCER] Warning: Gate error in {gate_label}: {e}", file=sys.stderr)

    # Q-learning: all gates passed — update qtable for each gate that ran and passed
    for gate_name in passed_gates:
        update_qtable(gate_name, tool_name, blocked=False)

    # Persist caches (single write each for all updates this invocation)
    flush_qtable()
    _flush_timings()

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

    # F4: Subagent mini-boot — refresh sideband timestamp on first encounter
    # of a new session_id. Gives subagents a fresh Gate 4 window at startup
    # without requiring a full SessionStart boot sequence.
    # Only triggers for UUID-pattern session IDs (real subagent sessions).
    # Main sessions must query memory explicitly (no boot pre-write); test sessions are excluded.
    if (not state.get("_sideband_refreshed")
            and len(session_id) >= 8 and session_id[8:9] == "-"
            and all(c in "0123456789abcdef" for c in session_id[:8])):
        try:
            from boot_pkg.memory import _write_sideband_timestamp
            _write_sideband_timestamp()
        except Exception:
            pass  # Best-effort — subagent can still query memory to refresh
        state["_sideband_refreshed"] = True
        save_state(state, session_id=session_id)

    # Sync security_profile from LIVE_STATE.json (source of truth for profile toggle)
    live_profile = get_live_toggle("security_profile")
    if live_profile:
        state["security_profile"] = live_profile

    handle_pre_tool_use(tool_name, tool_input, state)


if __name__ == "__main__":
    main()
