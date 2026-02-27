"""Smart Gate Router — shared/gate_router.py

Routes tool calls through quality gates in priority-tier order, short-circuits
on Tier 1 blocks, and filters gates by tool type so irrelevant gates are never
invoked.

Priority tiers
--------------
Tier 1 (safety, gates 01-03): Always run first. If any of these blocks, Tier 2
and Tier 3 are skipped entirely.
Tier 2 (quality, gates 04-07): Run after Tier 1 passes.
Tier 3 (advisory/advanced, gates 09-17): Run last. Individual skips happen here
when a gate's tool-type filter does not match the current tool.

Stats tracking
--------------
Module-level counters accumulate across the process lifetime (one enforcer
invocation = one process, so counters reset per hook call by design). The dict
returned by get_routing_stats() is therefore valid for the lifetime of a single
enforcer run and is primarily useful for tests and intra-session diagnostics.

Usage
-----
    from shared.gate_router import get_applicable_gates, route_gates, get_routing_stats

    results = route_gates("Edit", tool_input, state)
    stats   = get_routing_stats()
"""

import importlib
import json
import os
import sys
import time
import types
from typing import Dict, List, Optional, Set

from shared.gate_result import GateResult

# ---------------------------------------------------------------------------
# Canonical gate list (single source of truth in shared/gate_registry.py)
# ---------------------------------------------------------------------------
from shared.gate_registry import GATE_MODULES

# Tier membership sets (module names).  gate_router only uses Tier 1 for
# short-circuit logic; Tier 2 / Tier 3 are used for labelling and stats.
TIER1: Set[str] = {
    "gates.gate_01_read_before_edit",
    "gates.gate_02_no_destroy",
    "gates.gate_03_test_before_deploy",
}

TIER2: Set[str] = {
    "gates.gate_04_memory_first",
    "gates.gate_05_proof_before_fixed",
    "gates.gate_06_save_fix",
    "gates.gate_07_critical_file_guard",
}

# Everything not in Tier 1 or Tier 2 is Tier 3.
TIER3: Set[str] = set(GATE_MODULES) - TIER1 - TIER2

# Tool-type filter: None = universal (applies to every tool).
GATE_TOOL_MAP: Dict[str, Optional[Set[str]]] = {
    "gates.gate_01_read_before_edit":    {"Edit", "Write", "NotebookEdit"},
    "gates.gate_02_no_destroy":          {"Bash"},
    "gates.gate_03_test_before_deploy":  {"Bash"},
    "gates.gate_04_memory_first":        {"Edit", "Write", "NotebookEdit", "Task"},
    "gates.gate_05_proof_before_fixed":  {"Edit", "Write", "NotebookEdit"},
    "gates.gate_06_save_fix":            {"Edit", "Write", "Task", "Bash", "NotebookEdit"},
    "gates.gate_07_critical_file_guard": {"Edit", "Write", "NotebookEdit"},
    "gates.gate_09_strategy_ban":        {"Edit", "Write", "NotebookEdit"},
    "gates.gate_10_model_enforcement":   {"Task"},
    "gates.gate_11_rate_limit":          None,  # universal
    "gates.gate_13_workspace_isolation": {"Edit", "Write", "NotebookEdit"},
    "gates.gate_14_confidence_check":    {"Edit", "Write", "NotebookEdit"},
    "gates.gate_15_causal_chain":        {"Edit", "Write", "NotebookEdit"},
    "gates.gate_16_code_quality":        {"Edit", "Write", "NotebookEdit"},
    "gates.gate_17_injection_defense":   {"WebFetch", "WebSearch"},
    "gates.gate_18_canary":              None,  # Universal — observes all tool calls
    "gates.gate_19_hindsight":           {"Edit", "Write", "NotebookEdit"},
}


# ---------------------------------------------------------------------------
# Module-level stats (reset each time the module is (re)loaded).
# ---------------------------------------------------------------------------

_stats: Dict[str, object] = {
    "calls": 0,          # total route_gates() calls
    "gates_run": 0,      # total individual gate invocations
    "gates_skipped": 0,  # gates skipped (tool-filter or short-circuit)
    "tier1_blocks": 0,   # times Tier 1 caused a short-circuit
    "timing_ms": [],     # list[float] — per-call total routing time
}


def _get_stat_int(key: str) -> int:
    """Safely retrieve and cast an int stat, defaulting to 0."""
    val = _stats.get(key, 0)
    if isinstance(val, int):
        return val
    return 0


def _set_stat_int(key: str, value: int) -> None:
    """Safely set an int stat."""
    _stats[key] = value


def _get_stat_list(key: str) -> List[float]:
    """Safely retrieve and cast a list stat, defaulting to empty list."""
    val = _stats.get(key, [])
    if isinstance(val, list):
        return val
    return []


def _reset_stats() -> None:
    """Reset all routing stats.  Useful in tests."""
    _stats["calls"] = 0
    _stats["gates_run"] = 0
    _stats["gates_skipped"] = 0
    _stats["tier1_blocks"] = 0
    _stats["timing_ms"] = []


# ---------------------------------------------------------------------------
# Gate module cache (loaded lazily, never reloaded by this module — enforcer
# owns the hot-reload lifecycle).
# ---------------------------------------------------------------------------

_loaded: Dict[str, types.ModuleType] = {}  # module_name -> module


def _load_gate(module_name: str) -> Optional[types.ModuleType]:
    """Import and cache a gate module.  Returns None on failure."""
    if module_name in _loaded:
        return _loaded[module_name]
    try:
        # Re-use already-imported module from sys.modules if available.
        if module_name in sys.modules:
            mod = sys.modules[module_name]
        else:
            mod = importlib.import_module(module_name)
        if hasattr(mod, "check"):
            _loaded[module_name] = mod
            return mod
    except ImportError:
        pass
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_applicable_gates(tool_name: str) -> List[str]:
    """Return gate module names that apply to *tool_name*, in priority order.

    Gates are ordered Tier 1 → Tier 2 → Tier 3, preserving the original
    GATE_MODULES ordering within each tier.  Gates whose tool-type filter
    does not include *tool_name* are excluded.

    Parameters
    ----------
    tool_name:
        The name of the Claude Code tool being dispatched (e.g. ``"Edit"``).

    Returns
    -------
    list[str]
        Ordered list of gate module name strings.
    """
    result: List[str] = []
    for module_name in GATE_MODULES:
        watched = GATE_TOOL_MAP.get(module_name)
        if watched is None or tool_name in watched:
            result.append(module_name)
    return result


def _tier_of(module_name: str) -> int:
    """Return numeric tier (1, 2, or 3) for a gate module name."""
    if module_name in TIER1:
        return 1
    if module_name in TIER2:
        return 2
    return 3


def route_gates(
    tool_name: str,
    tool_input: dict,
    state: dict,
    event_type: str = "PreToolUse",
) -> List[GateResult]:
    """Run applicable gates in priority order, short-circuiting after Tier 1 blocks.

    Algorithm
    ---------
    1. Build the ordered list of applicable gates via ``get_applicable_gates``.
    2. Run gates in order.  Timing is recorded per-call.
    3. If any **Tier 1** gate returns ``blocked=True`` (or ``is_ask=True``),
       remaining gates are skipped and the results list is returned immediately.
    4. Stats are updated: ``gates_run``, ``gates_skipped``, ``tier1_blocks``.

    Parameters
    ----------
    tool_name:
        Claude Code tool name.
    tool_input:
        The ``tool_input`` dict from the hook payload.
    state:
        Per-session state dict (may be mutated by gates).
    event_type:
        Hook event type forwarded to each gate (default ``"PreToolUse"``).

    Returns
    -------
    list[GateResult]
        Results for every gate that was *actually run*.  Skipped gates are not
        represented.  Callers can inspect ``result.blocked`` or ``result.is_ask``
        on any entry to decide whether to halt further processing.
    """
    t_start = time.time()
    _set_stat_int("calls", _get_stat_int("calls") + 1)

    applicable = get_applicable_gates(tool_name)
    total_possible = len(applicable)

    results: List[GateResult] = []
    short_circuited = False

    for module_name in applicable:
        if short_circuited:
            _set_stat_int("gates_skipped", _get_stat_int("gates_skipped") + 1)
            continue

        mod = _load_gate(module_name)
        if mod is None:
            # Gate not loadable — count as skipped, do not block (non-Tier-1).
            _set_stat_int("gates_skipped", _get_stat_int("gates_skipped") + 1)
            continue

        try:
            t_gate = time.time()
            result: GateResult = mod.check(
                tool_name, tool_input, state, event_type=event_type
            )
            result.duration_ms = (time.time() - t_gate) * 1000
        except Exception as exc:
            tier = _tier_of(module_name)
            if tier == 1:
                # Tier 1 crash → fail-closed
                result = GateResult(
                    blocked=True,
                    message=f"[gate_router] Tier 1 gate '{module_name}' crashed: {exc}",
                    gate_name=module_name,
                    severity="critical",
                )
            else:
                # Non-Tier-1 crash → fail-open (warn, do not block)
                result = GateResult(
                    blocked=False,
                    message=f"[gate_router] Gate '{module_name}' crashed (non-fatal): {exc}",
                    gate_name=module_name,
                    severity="warn",
                )

        _set_stat_int("gates_run", _get_stat_int("gates_run") + 1)
        results.append(result)

        # Short-circuit: Tier 1 block or ask triggers immediate halt.
        if _tier_of(module_name) == 1 and (result.blocked or result.is_ask):
            _set_stat_int("tier1_blocks", _get_stat_int("tier1_blocks") + 1)
            short_circuited = True

    # Count gates that were in the applicable list but never reached.
    gates_run_count = len(results)
    skipped_this_call = total_possible - gates_run_count
    _set_stat_int("gates_skipped", _get_stat_int("gates_skipped") + skipped_this_call)

    elapsed_ms = (time.time() - t_start) * 1000
    timing_list = _get_stat_list("timing_ms")
    timing_list.append(elapsed_ms)
    _stats["timing_ms"] = timing_list

    return results


def get_routing_stats() -> dict:
    """Return a snapshot of cumulative routing statistics.

    Keys
    ----
    calls : int
        Total ``route_gates()`` invocations since module load.
    gates_run : int
        Total individual gate ``check()`` calls executed.
    gates_skipped : int
        Total gates skipped (tool-filter mismatch or short-circuit).
    tier1_blocks : int
        Number of times a Tier 1 gate triggered a short-circuit.
    avg_routing_ms : float
        Mean time spent in ``route_gates()`` across all calls (0.0 if no
        calls yet).
    last_routing_ms : float
        Routing time of the most recent call (0.0 if no calls yet).
    skip_rate : float
        Fraction of applicable gates skipped (0.0–1.0); 0.0 if nothing run.
    """
    calls: int = _get_stat_int("calls")
    gates_run: int = _get_stat_int("gates_run")
    gates_skipped: int = _get_stat_int("gates_skipped")
    tier1_blocks: int = _get_stat_int("tier1_blocks")
    timing: List[float] = _get_stat_list("timing_ms")

    total_gates = gates_run + gates_skipped
    skip_rate = (gates_skipped / total_gates) if total_gates > 0 else 0.0
    avg_ms = (sum(timing) / len(timing)) if timing else 0.0
    last_ms = timing[-1] if timing else 0.0

    return {
        "calls": calls,
        "gates_run": gates_run,
        "gates_skipped": gates_skipped,
        "tier1_blocks": tier1_blocks,
        "avg_routing_ms": round(avg_ms, 3),
        "last_routing_ms": round(last_ms, 3),
        "skip_rate": round(skip_rate, 4),
    }


# ---------------------------------------------------------------------------
# Q-learning gate ordering — reorders Tier 2/3 gates by learned block probability.
# ---------------------------------------------------------------------------

_QTABLE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".gate_qtable.json")
_Q_ALPHA = 0.1      # learning rate
_Q_REWARD_BLOCK = 1.0   # reward when gate blocks
_Q_REWARD_PASS = -0.1   # reward when gate passes (no block)


def _load_qtable() -> Dict[str, Dict[str, float]]:
    """Load Q-table from disk.  Returns empty dict if file missing or corrupt."""
    try:
        with open(_QTABLE_PATH) as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _save_qtable(qtable: Dict[str, Dict[str, float]]) -> None:
    """Persist Q-table to disk.  Fail-open — errors are silently swallowed."""
    try:
        with open(_QTABLE_PATH, "w") as f:
            json.dump(qtable, f, indent=2)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# In-process Q-table cache.  Each enforcer invocation is a fresh process,
# so this cache lives for exactly one hook call.  The cache eliminates N
# load/save cycles (one per gate) down to 1 load + 1 save per invocation.
# ---------------------------------------------------------------------------
_qtable_cache: Optional[Dict[str, Dict[str, float]]] = None
_qtable_dirty: bool = False


def _ensure_qtable() -> Dict[str, Dict[str, float]]:
    """Return the cached Q-table, loading from disk on first access."""
    global _qtable_cache
    if _qtable_cache is None:
        _qtable_cache = _load_qtable()
    return _qtable_cache


def get_optimal_gate_order(tool_name: str, gate_names: List[str]) -> List[str]:
    """Return gate_names reordered for optimal early-exit performance.

    Tier 1 gates (safety gates 01-03) are always kept first in their original
    order.  Tier 2 and Tier 3 gates are reordered by descending Q-value for
    the given tool — gates with higher learned block probability run first,
    enabling earlier short-circuits.

    Gates with no Q-table entry are treated as Q=0.0.

    Parameters
    ----------
    tool_name:
        The tool being dispatched (e.g. ``"Edit"``).
    gate_names:
        List of gate module ``__name__`` strings in their current order.

    Returns
    -------
    list[str]
        Reordered gate names (same elements, different order).
    """
    qtable = _ensure_qtable()

    tier1_gates = [n for n in gate_names if n in TIER1]
    non_tier1 = [n for n in gate_names if n not in TIER1]

    # Sort non-Tier-1 gates by descending Q-value (higher = more likely to block = run first).
    def _q_value(gate_name: str) -> float:
        return qtable.get(gate_name, {}).get(tool_name, 0.0)

    non_tier1_sorted = sorted(non_tier1, key=_q_value, reverse=True)
    return tier1_gates + non_tier1_sorted


def update_qtable(gate_name: str, tool_name: str, blocked: bool) -> None:
    """Update the Q-table entry for (gate_name, tool_name) using a Q-learning step.

    Mutates the in-process cache only.  Call flush_qtable() to persist.

    Update rule:  Q = Q + α * (reward − Q)
    where reward is _Q_REWARD_BLOCK (1.0) if blocked, _Q_REWARD_PASS (-0.1) otherwise.

    Parameters
    ----------
    gate_name:
        Module ``__name__`` of the gate (e.g. ``"gates.gate_01_read_before_edit"``).
    tool_name:
        The tool that triggered the gate.
    blocked:
        True if the gate blocked the tool call, False if it passed.
    """
    global _qtable_dirty
    qtable = _ensure_qtable()
    if gate_name not in qtable:
        qtable[gate_name] = {}

    current_q = qtable[gate_name].get(tool_name, 0.0)
    reward = _Q_REWARD_BLOCK if blocked else _Q_REWARD_PASS
    qtable[gate_name][tool_name] = current_q + _Q_ALPHA * (reward - current_q)
    _qtable_dirty = True


def flush_qtable() -> None:
    """Persist the cached Q-table to disk if any updates were made.

    Called once at the end of the enforcer gate loop (or before early exit).
    No-op if no update_qtable() calls were made this invocation.
    """
    global _qtable_dirty
    if _qtable_dirty and _qtable_cache is not None:
        _save_qtable(_qtable_cache)
        _qtable_dirty = False
