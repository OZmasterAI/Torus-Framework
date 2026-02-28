"""Gate auto-pruning recommendation system — shared/gate_pruner.py

Analyzes .gate_effectiveness.json and .gate_timings.json to classify each
active gate as: keep | optimize | merge_candidate | dormant

Tier 1 gates (01, 02, 03) are ALWAYS marked "keep" and never flagged for removal.

Public API:
    analyze_gates()              -> dict[str, GateAnalysis]
    get_prune_recommendations()  -> list[PruneRecommendation]
    render_pruner_report()       -> str
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

_HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_EFFECTIVENESS_PATH = os.path.join(_HOOKS_DIR, ".gate_effectiveness.json")
_TIMINGS_PATH       = os.path.join(_HOOKS_DIR, ".gate_timings.json")
_QTABLE_PATH        = os.path.join(_HOOKS_DIR, ".gate_qtable.json")

# Tier 1 gates are mandatory safety rails — NEVER recommend removing them
_TIER1 = frozenset({
    "gate_01_read_before_edit",
    "gate_02_no_destroy",
    "gate_03_test_before_deploy",
})

# Thresholds
_LOW_BLOCK_RATE  = 0.005   # 0.5% block rate → low-value candidate
_MIN_EVALS       = 1000    # minimum evaluations for a reliable dormant verdict
_HIGH_LATENCY_MS = 10.0    # avg_ms above this with low value = latency drain
_HIGH_OVERRIDE   = 0.15    # overrides/blocks > 15% → gate too aggressive

KEEP            = "keep"
OPTIMIZE        = "optimize"
MERGE_CANDIDATE = "merge_candidate"
DORMANT         = "dormant"

_VERDICT_RANK = {DORMANT: 4, MERGE_CANDIDATE: 3, OPTIMIZE: 2, KEEP: 1}


# ── Data containers ────────────────────────────────────────────────────────────

@dataclass
class GateAnalysis:
    """Computed pruning metrics for one gate."""
    gate:          str
    tier1:         bool
    blocks:        int
    overrides:     int
    prevented:     int
    eval_count:    int    # timing-based evaluation count (best denominator)
    avg_ms:        float
    block_rate:    float  # blocks / eval_count (or 0 when eval_count < _MIN_EVALS)
    override_rate: float  # overrides / blocks (0 when blocks == 0)
    has_q_data:    bool
    verdict:       str    # keep | optimize | merge_candidate | dormant
    reasons:       List[str] = field(default_factory=list)


@dataclass
class PruneRecommendation:
    """Single ranked recommendation with context."""
    rank:    int
    gate:    str
    verdict: str
    reasons: List[str]
    avg_ms:  float
    blocks:  int
    prevented: int


# ── Loaders ───────────────────────────────────────────────────────────────────

def _load_json(path: str) -> dict:
    try:
        with open(path, "r") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


# ── Core analysis ─────────────────────────────────────────────────────────────

def analyze_gates() -> Dict[str, GateAnalysis]:
    """Analyze all known gates and assign a pruning verdict.

    Returns a dict keyed by short gate name (e.g. "gate_15_causal_chain").
    """
    eff     = _load_json(_EFFECTIVENESS_PATH)
    timings = _load_json(_TIMINGS_PATH)
    qtable  = _load_json(_QTABLE_PATH)

    # Collect all gate names from both sources
    all_gates = set(eff.keys()) | set(timings.keys())
    # Normalize full module keys from qtable (e.g. "gates.gate_15_causal_chain")
    for k in qtable:
        short = k.split(".")[-1] if "." in k else k
        all_gates.add(short)

    results: Dict[str, GateAnalysis] = {}

    for gate in sorted(all_gates):
        e_entry  = eff.get(gate, {})
        t_entry  = timings.get(gate, {})
        q_module = f"gates.{gate}"
        has_q    = q_module in qtable and bool(qtable[q_module])

        blocks    = int(e_entry.get("blocks", 0) or e_entry.get("block", 0))
        overrides = int(e_entry.get("overrides", 0))
        prevented = int(e_entry.get("prevented", 0))

        eval_count = int(t_entry.get("count", 0))
        total_ms   = float(t_entry.get("total_ms", 0.0))
        avg_ms     = total_ms / eval_count if eval_count > 0 else 0.0

        block_rate    = blocks / eval_count if eval_count >= _MIN_EVALS else 0.0
        override_rate = overrides / blocks  if blocks > 0              else 0.0

        is_tier1 = gate in _TIER1
        verdict, reasons = _classify(
            gate, is_tier1, blocks, overrides, prevented,
            eval_count, avg_ms, block_rate, override_rate,
        )

        results[gate] = GateAnalysis(
            gate=gate,
            tier1=is_tier1,
            blocks=blocks,
            overrides=overrides,
            prevented=prevented,
            eval_count=eval_count,
            avg_ms=avg_ms,
            block_rate=block_rate,
            override_rate=override_rate,
            has_q_data=has_q,
            verdict=verdict,
            reasons=reasons,
        )

    return results


def _classify(
    gate: str,
    is_tier1: bool,
    blocks: int,
    overrides: int,
    prevented: int,
    eval_count: int,
    avg_ms: float,
    block_rate: float,
    override_rate: float,
) -> Tuple[str, List[str]]:
    """Assign verdict and reasons for a single gate."""

    if is_tier1:
        return KEEP, ["Tier 1 safety rail — mandatory, never remove"]

    reasons: List[str] = []
    verdict = KEEP

    # Dormant: enough evaluations, very low block rate, nothing prevented
    if eval_count >= _MIN_EVALS and block_rate < _LOW_BLOCK_RATE and prevented == 0:
        verdict = DORMANT
        reasons.append(
            f"Block rate {block_rate:.2%} over {eval_count:,} evals — "
            f"below 0.5% threshold with 0 incidents prevented"
        )

    # Latency drain: high avg_ms with dormant/low-value classification
    if avg_ms > _HIGH_LATENCY_MS and verdict in (DORMANT, MERGE_CANDIDATE):
        reasons.append(f"High latency: {avg_ms:.1f}ms avg per evaluation")

    # Merge candidate: some activity but block rate suggests low standalone value
    if verdict == KEEP and eval_count >= _MIN_EVALS and block_rate < 0.02 and blocks < 50:
        verdict = MERGE_CANDIDATE
        reasons.append(
            f"Low standalone impact: {blocks} blocks ({block_rate:.2%}) — "
            "consider merging logic with a related gate"
        )

    # Optimize: override rate too high (gate is too aggressive)
    if override_rate > _HIGH_OVERRIDE and blocks > 20:
        if verdict == KEEP:
            verdict = OPTIMIZE
        reasons.append(
            f"Override rate {override_rate:.0%} ({overrides}/{blocks} blocks) — "
            "gate fires too aggressively, review thresholds"
        )

    # Zero blocks with evals → suspicious
    if blocks == 0 and eval_count >= _MIN_EVALS and verdict == KEEP:
        verdict = DORMANT
        reasons.append(f"Zero blocks recorded over {eval_count:,} evaluations")

    # Prevented incidents always boost toward keep
    if prevented > 0 and verdict != KEEP:
        reasons.append(f"Note: {prevented} incident(s) prevented — reconsider removal")

    if not reasons:
        reasons.append(f"{blocks:,} blocks, {block_rate:.2%} block rate — healthy")

    return verdict, reasons


# ── Public recommendation list ─────────────────────────────────────────────────

def get_prune_recommendations() -> List[PruneRecommendation]:
    """Return gates ranked by urgency of action (dormant first, keep last)."""
    analysis = analyze_gates()
    ranked = sorted(
        analysis.values(),
        key=lambda a: (_VERDICT_RANK.get(a.verdict, 0), -a.blocks),
        reverse=True,
    )
    return [
        PruneRecommendation(
            rank=i + 1,
            gate=a.gate,
            verdict=a.verdict,
            reasons=a.reasons,
            avg_ms=a.avg_ms,
            blocks=a.blocks,
            prevented=a.prevented,
        )
        for i, a in enumerate(ranked)
    ]


# ── Report rendering ───────────────────────────────────────────────────────────

def render_pruner_report() -> str:
    """Render a human-readable pruning recommendation report."""
    recs = get_prune_recommendations()
    if not recs:
        return "Gate Pruner: no gate data found."

    lines = [
        "=" * 72,
        "  GATE PRUNING RECOMMENDATIONS",
        "=" * 72,
        f"  {'#':>2}  {'Gate':<30}  {'Verdict':<16}  {'Blocks':>7}  {'AvgMs':>6}",
        "  " + "-" * 66,
    ]
    for r in recs:
        lines.append(
            f"  {r.rank:>2}  {r.gate:<30}  {r.verdict:<16}  "
            f"{r.blocks:>7,}  {r.avg_ms:>5.2f}ms"
        )
        for reason in r.reasons:
            lines.append(f"       → {reason}")

    dormant = [r for r in recs if r.verdict == DORMANT]
    optimize = [r for r in recs if r.verdict == OPTIMIZE]
    merge    = [r for r in recs if r.verdict == MERGE_CANDIDATE]

    lines += [
        "",
        "  " + "-" * 66,
        f"  Summary: {len(dormant)} dormant  |  {len(optimize)} optimize  |"
        f"  {len(merge)} merge-candidates",
        "=" * 72,
    ]
    return "\n".join(lines)


# ── CLI smoke test ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys as _sys

    print(render_pruner_report())
    print()

    analysis = analyze_gates()
    recs = get_prune_recommendations()

    errors: List[str] = []

    def _check(name: str, cond: bool, detail: str = "") -> None:
        label = "PASS" if cond else "FAIL"
        print(f"  {label}  {name}" + (f" -- {detail}" if detail else ""))
        if not cond:
            errors.append(name)

    _check("analyze_gates returns dict", isinstance(analysis, dict))
    _check("analyze_gates non-empty",    len(analysis) > 0)
    _check("get_prune_recommendations returns list", isinstance(recs, list))
    _check("recommendations non-empty", len(recs) > 0)
    _check("tier1 gates always keep",
           all(a.verdict == KEEP for g, a in analysis.items() if g in _TIER1),
           str({g: a.verdict for g, a in analysis.items() if g in _TIER1}))
    _check("ranks are sequential",
           [r.rank for r in recs] == list(range(1, len(recs) + 1)))
    _check("all verdicts are valid",
           all(r.verdict in (KEEP, OPTIMIZE, MERGE_CANDIDATE, DORMANT) for r in recs))
    _check("render returns str", isinstance(render_pruner_report(), str))

    print()
    if errors:
        print(f"FAILED: {len(errors)} test(s): {errors}")
        _sys.exit(1)
    else:
        print("ALL TESTS PASSED")
        _sys.exit(0)
