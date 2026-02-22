"""Pipeline Optimizer — shared/pipeline_optimizer.py

Analyzes gate fire frequency from .gate_effectiveness.json to suggest the
optimal gate execution ordering and identify parallelization opportunities,
thereby reducing mean enforcer latency.

Design rationale
----------------
The enforcer already uses Q-learning (gate_router.py) for real-time per-tool
ordering.  This module operates at a higher level: it analyzes the *aggregate*
block frequencies from .gate_effectiveness.json (the persistent, cross-session
ledger) to produce:

  1. A recommended static ordering per tool — gates that block most often run
     first, enabling the maximum number of early-exits over the session.

  2. A parallelization plan — gates that share no state-key writes can run
     concurrently.  Their combined latency equals the slowest member rather
     than the sum.

  3. A latency-savings estimate — how many milliseconds could be saved per
     enforcer invocation if the recommended ordering and parallelization were
     adopted, based on average execution times from gate_timing.py.

Public API
----------
  get_optimal_order(tool_name)   -> list[str]
  estimate_savings(tool_name)    -> dict
  get_pipeline_analysis()        -> dict   (full cross-tool report)

All functions are read-only and safe to call from any context.  Failures are
fail-open: any I/O or data error returns a safe fallback value.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_EFFECTIVENESS_PATH = os.path.join(_HOOKS_DIR, ".gate_effectiveness.json")
_QTABLE_PATH = os.path.join(_HOOKS_DIR, ".gate_qtable.json")
_TIMINGS_PATH = os.path.join(_HOOKS_DIR, ".gate_timings.json")

# ---------------------------------------------------------------------------
# Gate metadata (mirrored from enforcer.py — single source of truth there)
# ---------------------------------------------------------------------------

# Canonical gate list (from shared/gate_registry.py)
from shared.gate_registry import GATE_MODULES as _GATE_MODULES

# Short name -> full module name
_SHORT_TO_MODULE: Dict[str, str] = {m.split(".")[-1]: m for m in _GATE_MODULES}
# Full module name -> short name
_MODULE_TO_SHORT: Dict[str, str] = {m: m.split(".")[-1] for m in _GATE_MODULES}

# Tier 1 gates always execute first; their order is fixed (safety contract)
_TIER1: Set[str] = {
    "gates.gate_01_read_before_edit",
    "gates.gate_02_no_destroy",
    "gates.gate_03_test_before_deploy",
}

# Per-gate: which tools it watches.  None = watches all tools (universal).
_GATE_TOOL_MAP: Dict[str, Optional[Set[str]]] = {
    "gates.gate_01_read_before_edit":    {"Edit", "Write", "NotebookEdit"},
    "gates.gate_02_no_destroy":          {"Bash"},
    "gates.gate_03_test_before_deploy":  {"Bash"},
    "gates.gate_04_memory_first":        {"Edit", "Write", "NotebookEdit", "Task"},
    "gates.gate_05_proof_before_fixed":  {"Edit", "Write", "NotebookEdit"},
    "gates.gate_06_save_fix":            {"Edit", "Write", "Task", "Bash", "NotebookEdit"},
    "gates.gate_07_critical_file_guard": {"Edit", "Write", "NotebookEdit"},
    "gates.gate_09_strategy_ban":        {"Edit", "Write", "NotebookEdit"},
    "gates.gate_10_model_enforcement":   {"Task"},
    "gates.gate_11_rate_limit":          None,
    "gates.gate_13_workspace_isolation": {"Edit", "Write", "NotebookEdit"},
    "gates.gate_14_confidence_check":    {"Edit", "Write", "NotebookEdit"},
    "gates.gate_15_causal_chain":        {"Edit", "Write", "NotebookEdit"},
    "gates.gate_16_code_quality":        {"Edit", "Write", "NotebookEdit"},
    "gates.gate_17_injection_defense":   {"WebFetch", "WebSearch"},
}

# State keys each gate reads and writes (from enforcer.GATE_DEPENDENCIES).
# Used for parallelization safety: two gates are parallelizable if no gate's
# *writes* overlap with another gate's *reads or writes* in the same group.
_GATE_STATE_DEPS: Dict[str, Dict[str, List[str]]] = {
    "gate_01_read_before_edit":   {"reads": ["files_read"],              "writes": []},
    "gate_02_no_destroy":         {"reads": [],                          "writes": []},
    "gate_03_test_before_deploy": {"reads": ["last_test_run", "last_test_exit_code"], "writes": []},
    "gate_04_memory_first":       {"reads": ["memory_last_queried"],     "writes": []},
    "gate_05_proof_before_fixed": {"reads": ["pending_verification", "verification_scores"], "writes": []},
    "gate_06_save_fix":           {
        "reads":  ["gate6_warn_count", "verified_fixes", "unlogged_errors",
                   "error_pattern_counts", "pending_chain_ids", "last_exit_plan_mode",
                   "memory_last_queried"],
        "writes": ["gate6_warn_count"],
    },
    "gate_07_critical_file_guard": {"reads": ["memory_last_queried"],   "writes": []},
    "gate_09_strategy_ban":        {"reads": ["current_strategy_id", "active_bans", "successful_strategies"], "writes": []},
    "gate_10_model_enforcement":   {"reads": [],                        "writes": ["model_agent_usage"]},
    "gate_11_rate_limit":          {"reads": ["tool_call_count", "session_start"], "writes": []},
    "gate_13_workspace_isolation": {"reads": [],                        "writes": []},
    "gate_14_confidence_check":    {
        "reads":  ["session_test_baseline", "pending_verification",
                   "memory_last_queried", "confidence_warnings_per_file"],
        "writes": ["confidence_warnings_per_file", "confidence_warned_signals"],
    },
    "gate_15_causal_chain":   {"reads": ["recent_test_failure", "fix_history_queried", "fixing_error"], "writes": []},
    "gate_16_code_quality":   {"reads": ["code_quality_warnings_per_file"], "writes": ["code_quality_warnings_per_file"]},
    "gate_17_injection_defense": {"reads": ["injection_attempts"], "writes": ["injection_attempts"]},
}

# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------


def _load_json(path: str) -> dict:
    """Load JSON file; return empty dict on any failure."""
    try:
        with open(path, "r") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def _load_effectiveness() -> Dict[str, Dict[str, int]]:
    """Return gate effectiveness data keyed by short gate name."""
    raw = _load_json(_EFFECTIVENESS_PATH)
    # Normalize: .gate_effectiveness.json uses short gate names as keys
    return raw


def _load_timings() -> Dict[str, dict]:
    """Return gate timing data keyed by short gate name."""
    return _load_json(_TIMINGS_PATH)


def _load_qtable() -> Dict[str, Dict[str, float]]:
    """Return Q-table keyed by full module name -> tool -> q-value."""
    return _load_json(_QTABLE_PATH)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _gates_for_tool(tool_name: str) -> List[str]:
    """Return full module names of gates that apply to tool_name, in order."""
    result: List[str] = []
    for module in _GATE_MODULES:
        watched = _GATE_TOOL_MAP.get(module)
        if watched is None or tool_name in watched:
            result.append(module)
    return result


def _block_rate(short_name: str, effectiveness: Dict[str, dict]) -> float:
    """Return the historical block rate for a gate (0.0 if no data)."""
    entry = effectiveness.get(short_name, {})
    blocks = entry.get("blocks", 0) + entry.get("block", 0)  # handle both key variants
    return float(blocks)


def _avg_ms(short_name: str, timings: Dict[str, dict]) -> float:
    """Return average execution time in ms for a gate (0.0 if no data)."""
    entry = timings.get(short_name, {})
    count = entry.get("count", 0)
    if count == 0:
        return 0.0
    return entry.get("total_ms", 0.0) / count


def _are_parallelizable(gate_a: str, gate_b: str) -> bool:
    """Return True if gate_a and gate_b can run concurrently without state conflicts.

    Two gates are safe to parallelize when neither gate's *writes* overlap with
    the other gate's *reads* or *writes*.  Gates with no state writes and no
    shared reads are trivially parallelizable.
    """
    deps_a = _GATE_STATE_DEPS.get(gate_a, {"reads": [], "writes": []})
    deps_b = _GATE_STATE_DEPS.get(gate_b, {"reads": [], "writes": []})

    writes_a = set(deps_a.get("writes", []))
    writes_b = set(deps_b.get("writes", []))
    reads_a = set(deps_a.get("reads", []))
    reads_b = set(deps_b.get("reads", []))

    # Write-read conflict: a writes something b reads
    if writes_a & reads_b:
        return False
    # Write-read conflict: b writes something a reads
    if writes_b & reads_a:
        return False
    # Write-write conflict: both write the same key
    if writes_a & writes_b:
        return False

    return True


def _identify_parallel_groups(short_names: List[str]) -> List[List[str]]:
    """Greedily partition gate short names into parallelizable groups.

    Each group can run concurrently.  Gates are assigned to the first group
    where they conflict with no existing member.  This is a greedy bin-packing
    approximation, not an optimal solution, but it's fast and good enough for
    the small gate counts involved.

    Parameters
    ----------
    short_names:
        Ordered list of gate short names (e.g. "gate_04_memory_first").

    Returns
    -------
    list[list[str]]
        List of groups; each group is a list of gate short names that can
        execute concurrently.  Groups are ordered by execution sequence —
        all gates in group N complete before group N+1 starts.
    """
    groups: List[List[str]] = []

    for gate in short_names:
        placed = False
        for group in groups:
            if all(_are_parallelizable(gate, member) for member in group):
                group.append(gate)
                placed = True
                break
        if not placed:
            groups.append([gate])

    return groups


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_optimal_order(tool_name: str) -> List[str]:
    """Return gates in recommended execution order for *tool_name*.

    Ordering rules
    --------------
    1. Tier 1 gates (01, 02, 03) are always placed first in their original
       order — this is a hard safety contract.
    2. Remaining (Tier 2 + 3) gates are sorted by *descending* historical
       block count so that high-block-probability gates run first, maximising
       the chance of an early exit.
    3. Gates with no recorded block history are sorted to the end (treated as
       block_rate = 0).

    Parameters
    ----------
    tool_name : str
        The Claude Code tool name, e.g. "Edit" or "Bash".

    Returns
    -------
    list[str]
        Ordered list of short gate names (e.g. "gate_01_read_before_edit").
    """
    applicable_modules = _gates_for_tool(tool_name)
    effectiveness = _load_effectiveness()

    tier1 = [m for m in applicable_modules if m in _TIER1]
    non_tier1 = [m for m in applicable_modules if m not in _TIER1]

    # Sort non-Tier-1 by descending block count
    non_tier1_sorted = sorted(
        non_tier1,
        key=lambda m: _block_rate(_MODULE_TO_SHORT[m], effectiveness),
        reverse=True,
    )

    ordered_modules = tier1 + non_tier1_sorted
    return [_MODULE_TO_SHORT[m] for m in ordered_modules]


def estimate_savings(tool_name: str) -> dict:
    """Estimate per-invocation latency savings for *tool_name*.

    The estimate compares two scenarios:

    - **Baseline**: gates run in the current static order (GATE_MODULES order),
      no parallelization.
    - **Optimized**: gates run in `get_optimal_order()` sequence with
      parallelization applied to compatible groups.

    Early-exit savings are estimated using the *block rate* from
    .gate_effectiveness.json: if a gate has historically blocked P% of the
    time, the expected savings from running it first (vs. its current position)
    is proportional to P * (sum of avg_ms for all gates that would have been
    skipped).

    Returns
    -------
    dict with keys:
        tool_name              : str
        applicable_gates       : list[str]    short gate names (current order)
        optimal_order          : list[str]    short gate names (recommended)
        parallel_groups        : list[list[str]]
        baseline_sequential_ms : float        sum of avg_ms (current order)
        optimized_sequential_ms: float        sum of avg_ms (optimal order, no parallelization)
        optimized_parallel_ms  : float        estimated ms with parallelization
        estimated_saving_ms    : float        baseline - optimized_parallel
        saving_pct             : float        estimated_saving_ms / baseline (0–1)
        gate_block_rates       : dict         short_name -> block_count
        notes                  : list[str]    human-readable observations
    """
    applicable_modules = _gates_for_tool(tool_name)
    if not applicable_modules:
        return {
            "tool_name": tool_name,
            "applicable_gates": [],
            "optimal_order": [],
            "parallel_groups": [],
            "baseline_sequential_ms": 0.0,
            "optimized_sequential_ms": 0.0,
            "optimized_parallel_ms": 0.0,
            "estimated_saving_ms": 0.0,
            "saving_pct": 0.0,
            "gate_block_rates": {},
            "notes": [f"No gates apply to tool '{tool_name}'"],
        }

    effectiveness = _load_effectiveness()
    timings = _load_timings()

    current_short = [_MODULE_TO_SHORT[m] for m in applicable_modules]
    optimal_short = get_optimal_order(tool_name)

    # Baseline: sequential in current order
    baseline_ms = sum(_avg_ms(g, timings) for g in current_short)

    # Optimized sequential (same gates, better order — latency unchanged but
    # early-exits happen sooner, reducing *expected* cost)
    optimized_seq_ms = sum(_avg_ms(g, timings) for g in optimal_short)

    # Parallelization: non-Tier-1 gates only (Tier-1 must run sequentially)
    tier1_short = [_MODULE_TO_SHORT[m] for m in applicable_modules if m in _TIER1]
    non_tier1_short = [g for g in optimal_short if g not in tier1_short]

    parallel_groups = _identify_parallel_groups(non_tier1_short)

    # Parallel execution time = sum of max(avg_ms) per group + sequential tier1
    tier1_ms = sum(_avg_ms(g, timings) for g in tier1_short)
    parallel_groups_ms = sum(
        max((_avg_ms(g, timings) for g in group), default=0.0)
        for group in parallel_groups
    )
    optimized_parallel_ms = tier1_ms + parallel_groups_ms

    estimated_saving_ms = max(0.0, baseline_ms - optimized_parallel_ms)
    saving_pct = (estimated_saving_ms / baseline_ms) if baseline_ms > 0 else 0.0

    # Block rates for all applicable gates
    gate_block_rates = {
        g: int(_block_rate(g, effectiveness)) for g in current_short
    }

    # Human-readable notes
    notes: List[str] = []
    if not timings:
        notes.append("No timing data recorded yet — savings are estimated as 0ms until gates have run")

    # Identify the highest-blocking gate and its current position
    if gate_block_rates:
        top_gate = max(gate_block_rates, key=gate_block_rates.get)  # type: ignore[arg-type]
        top_pos = current_short.index(top_gate) if top_gate in current_short else -1
        opt_pos = optimal_short.index(top_gate) if top_gate in optimal_short else -1
        if top_pos > opt_pos and opt_pos >= 0:
            notes.append(
                f"Moving '{top_gate}' from position {top_pos + 1} to "
                f"{opt_pos + 1} could save skipping {top_pos - opt_pos} gate(s) "
                f"on early exits ({gate_block_rates[top_gate]} historical blocks)"
            )

    parallelizable_count = sum(len(g) for g in parallel_groups if len(g) > 1)
    if parallelizable_count > 0:
        notes.append(
            f"{parallelizable_count} of {len(non_tier1_short)} non-Tier-1 gates "
            f"are parallelizable across {len(parallel_groups)} group(s)"
        )
    else:
        notes.append("No non-Tier-1 gates are currently parallelizable (state write conflicts)")

    if saving_pct > 0.15:
        notes.append(
            f"Significant latency reduction possible: ~{estimated_saving_ms:.1f}ms "
            f"({saving_pct * 100:.0f}%) per invocation for '{tool_name}'"
        )
    elif saving_pct > 0:
        notes.append(
            f"Minor latency reduction possible: ~{estimated_saving_ms:.1f}ms "
            f"({saving_pct * 100:.1f}%) per invocation for '{tool_name}'"
        )

    return {
        "tool_name": tool_name,
        "applicable_gates": current_short,
        "optimal_order": optimal_short,
        "parallel_groups": parallel_groups,
        "baseline_sequential_ms": round(baseline_ms, 3),
        "optimized_sequential_ms": round(optimized_seq_ms, 3),
        "optimized_parallel_ms": round(optimized_parallel_ms, 3),
        "estimated_saving_ms": round(estimated_saving_ms, 3),
        "saving_pct": round(saving_pct, 4),
        "gate_block_rates": gate_block_rates,
        "notes": notes,
    }


def get_pipeline_analysis() -> dict:
    """Return a full pipeline analysis across all common tools.

    Covers "Edit", "Write", "Bash", "NotebookEdit", "Task", "WebFetch", and
    "WebSearch".  For each tool the analysis from ``estimate_savings()`` is
    included.

    Additionally, a cross-tool summary is included:
      - top_blocking_gates: gates sorted by total block count across all tools
      - parallelizable_pairs: list of (gate_a, gate_b) that share no state conflicts
      - total_estimated_saving_ms: sum of saving_ms over all tools

    Returns
    -------
    dict with keys:
        per_tool        : dict[tool_name -> estimate_savings() result]
        top_blocking_gates : list[dict] — [{gate, blocks, rank}]
        parallelizable_pairs : list[tuple[str, str]]
        total_estimated_saving_ms : float
        summary : str  — human-readable one-paragraph summary
    """
    tools = ["Edit", "Write", "Bash", "NotebookEdit", "Task", "WebFetch", "WebSearch"]
    effectiveness = _load_effectiveness()

    per_tool: Dict[str, dict] = {}
    for tool in tools:
        per_tool[tool] = estimate_savings(tool)

    # Cross-tool block frequency ranking
    all_blocks: Dict[str, int] = {}
    for short_name in _GATE_STATE_DEPS:
        entry = effectiveness.get(short_name, {})
        blocks = entry.get("blocks", 0) + entry.get("block", 0)
        if blocks > 0:
            all_blocks[short_name] = blocks

    top_blocking = [
        {"gate": g, "blocks": b, "rank": i + 1}
        for i, (g, b) in enumerate(
            sorted(all_blocks.items(), key=lambda kv: kv[1], reverse=True)
        )
    ]

    # All unique short gate names
    all_gate_shorts = list(_GATE_STATE_DEPS.keys())

    # Enumerate parallelizable pairs (upper triangle only)
    parallelizable_pairs: List[Tuple[str, str]] = []
    for i, ga in enumerate(all_gate_shorts):
        for gb in all_gate_shorts[i + 1 :]:
            if _are_parallelizable(ga, gb):
                parallelizable_pairs.append((ga, gb))

    total_saving = sum(per_tool[t]["estimated_saving_ms"] for t in tools)

    # Summary paragraph
    if top_blocking:
        top_gate = top_blocking[0]["gate"]
        top_cnt = top_blocking[0]["blocks"]
        summary = (
            f"Pipeline analysis complete. "
            f"Highest-blocking gate: '{top_gate}' ({top_cnt} blocks). "
            f"{len(parallelizable_pairs)} gate pair(s) are parallelizable. "
            f"Total estimated latency saving across all tools: {total_saving:.1f}ms per invocation cycle."
        )
    else:
        summary = (
            "Pipeline analysis complete. No block history found in "
            ".gate_effectiveness.json — run the enforcer to populate statistics."
        )

    return {
        "per_tool": per_tool,
        "top_blocking_gates": top_blocking,
        "parallelizable_pairs": [(a, b) for a, b in parallelizable_pairs],
        "total_estimated_saving_ms": round(total_saving, 3),
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# CLI entry point (python -m shared.pipeline_optimizer)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    tool_arg = sys.argv[1] if len(sys.argv) > 1 else None

    if tool_arg and tool_arg not in ("all", "--all"):
        result = estimate_savings(tool_arg)
        print(f"Pipeline analysis for tool: {result['tool_name']}")
        print(f"  Current order  : {result['applicable_gates']}")
        print(f"  Optimal order  : {result['optimal_order']}")
        print(f"  Parallel groups: {result['parallel_groups']}")
        print(f"  Baseline ms    : {result['baseline_sequential_ms']:.2f}")
        print(f"  Optimized ms   : {result['optimized_parallel_ms']:.2f}")
        print(f"  Saving         : {result['estimated_saving_ms']:.2f}ms  ({result['saving_pct'] * 100:.1f}%)")
        print(f"  Block rates    : {result['gate_block_rates']}")
        print("  Notes:")
        for note in result["notes"]:
            print(f"    - {note}")
    else:
        analysis = get_pipeline_analysis()
        print(analysis["summary"])
        print()
        print(f"Top blocking gates:")
        for entry in analysis["top_blocking_gates"][:5]:
            print(f"  #{entry['rank']} {entry['gate']}: {entry['blocks']} blocks")
        print()
        print(f"Parallelizable pairs ({len(analysis['parallelizable_pairs'])}):")
        for a, b in analysis["parallelizable_pairs"][:10]:
            print(f"  {a} || {b}")
        if len(analysis["parallelizable_pairs"]) > 10:
            print(f"  ... and {len(analysis['parallelizable_pairs']) - 10} more")
        print()
        print(f"Total estimated saving: {analysis['total_estimated_saving_ms']:.2f}ms")
