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
import os
import sys
import time
from typing import Dict, List, Optional, Set

from shared.gate_result import GateResult

# ---------------------------------------------------------------------------
# Constants mirrored from enforcer.py (single source of truth kept there;
# gate_router reads them at import time so there is no duplication at runtime).
# ---------------------------------------------------------------------------

# Full ordered list of active gate modules (dormant / merged gates omitted).
GATE_MODULES: List[str] = [
    "gates.gate_01_read_before_edit",
    "gates.gate_02_no_destroy",
    "gates.gate_03_test_before_deploy",
    "gates.gate_04_memory_first",
    "gates.gate_05_proof_before_fixed",
    "gates.gate_06_save_fix",
    "gates.gate_07_critical_file_guard",
    # gate_08 DORMANT
    "gates.gate_09_strategy_ban",
    "gates.gate_10_model_enforcement",
    "gates.gate_11_rate_limit",
    # gate_12 MERGED into gate_06
    "gates.gate_13_workspace_isolation",
    "gates.gate_14_confidence_check",
    "gates.gate_15_causal_chain",
    "gates.gate_16_code_quality",
    "gates.gate_17_injection_defense",
]

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

_loaded: Dict[str, object] = {}  # module_name -> module


def _load_gate(module_name: str) -> Optional[object]:
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
    _stats["calls"] = _stats.get("calls", 0) + 1  # type: ignore[operator]

    applicable = get_applicable_gates(tool_name)
    total_possible = len(applicable)

    results: List[GateResult] = []
    short_circuited = False

    for module_name in applicable:
        if short_circuited:
            _stats["gates_skipped"] = _stats.get("gates_skipped", 0) + 1  # type: ignore[operator]
            continue

        mod = _load_gate(module_name)
        if mod is None:
            # Gate not loadable — count as skipped, do not block (non-Tier-1).
            _stats["gates_skipped"] = _stats.get("gates_skipped", 0) + 1  # type: ignore[operator]
            continue

        try:
            t_gate = time.time()
            result: GateResult = mod.check(  # type: ignore[attr-defined]
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

        _stats["gates_run"] = _stats.get("gates_run", 0) + 1  # type: ignore[operator]
        results.append(result)

        # Short-circuit: Tier 1 block or ask triggers immediate halt.
        if _tier_of(module_name) == 1 and (result.blocked or result.is_ask):
            _stats["tier1_blocks"] = _stats.get("tier1_blocks", 0) + 1  # type: ignore[operator]
            short_circuited = True

    # Count gates that were in the applicable list but never reached.
    gates_run_count = len(results)
    skipped_this_call = total_possible - gates_run_count
    _stats["gates_skipped"] = _stats.get("gates_skipped", 0) + skipped_this_call  # type: ignore[operator]

    elapsed_ms = (time.time() - t_start) * 1000
    timing_list = _stats.get("timing_ms", [])
    timing_list.append(elapsed_ms)  # type: ignore[union-attr]

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
    calls: int = _stats.get("calls", 0)  # type: ignore[assignment]
    gates_run: int = _stats.get("gates_run", 0)  # type: ignore[assignment]
    gates_skipped: int = _stats.get("gates_skipped", 0)  # type: ignore[assignment]
    timing: list = _stats.get("timing_ms", [])  # type: ignore[assignment]

    total_gates = gates_run + gates_skipped
    skip_rate = (gates_skipped / total_gates) if total_gates > 0 else 0.0
    avg_ms = (sum(timing) / len(timing)) if timing else 0.0
    last_ms = timing[-1] if timing else 0.0

    return {
        "calls": calls,
        "gates_run": gates_run,
        "gates_skipped": gates_skipped,
        "tier1_blocks": _stats.get("tier1_blocks", 0),
        "avg_routing_ms": round(avg_ms, 3),
        "last_routing_ms": round(last_ms, 3),
        "skip_rate": round(skip_rate, 4),
    }
