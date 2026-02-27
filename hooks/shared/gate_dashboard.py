"""Gate effectiveness dashboard for the Torus self-healing framework.

Reads .gate_effectiveness.json for fire/block counts and .capture_queue.jsonl
for tool call data, then computes per-gate metrics, ranks gates by value, and
provides human-readable dashboard rendering and actionable recommendations.

Public API:
    get_gate_metrics()       -> dict[gate_name, GateMetrics]
    rank_gates_by_value()    -> list[(gate_name, GateMetrics)]
    render_dashboard()       -> str
    get_recommendations()    -> list[str]
"""

import json
import math
import os
from dataclasses import dataclass
from typing import Dict, List, Tuple

# ── Path constants ─────────────────────────────────────────────────────────────

_HOOKS_DIR = os.path.dirname(os.path.dirname(__file__))  # hooks/
EFFECTIVENESS_FILE = os.path.join(_HOOKS_DIR, ".gate_effectiveness.json")
CAPTURE_QUEUE_FILE = os.path.join(_HOOKS_DIR, ".capture_queue.jsonl")

# Human-readable display labels keyed by normalised gate key
_GATE_LABELS: Dict[str, str] = {
    "gate_01_read_before_edit":    "G01 Read-Before-Edit",
    "gate_02_no_destroy":          "G02 No-Destroy",
    "gate_03_test_before_deploy":  "G03 Test-Before-Deploy",
    "gate_04_memory_first":        "G04 Memory-First",
    "gate_05_proof_before_fixed":  "G05 Proof-Before-Fixed",
    "gate_06_save_fix":            "G06 Save-Fix",
    "gate_07_critical_file_guard": "G07 Critical-File-Guard",
    "gate_09_strategy_ban":        "G09 Strategy-Ban",
    "gate_10_model_enforcement":   "G10 Model-Enforcement",
    "gate_11_rate_limit":          "G11 Rate-Limit",
    "gate_13_workspace_isolation": "G13 Workspace-Isolation",
    "gate_14_confidence_check":    "G14 Confidence-Check",
    "gate_15_causal_chain":        "G15 Causal-Chain",
    "gate_16_code_quality":        "G16 Code-Quality",
    "gate_17_injection_defense":   "G17 Injection-Defense",
}

# Tool names that are subject to gate enforcement (not always-allowed)
_GATED_TOOLS = {"Edit", "Write", "Bash", "NotebookEdit"}

# Tier 1 gates that are mandatory safety rails (affects recommendation text)
_TIER1_GATES = {"gate_01_read_before_edit", "gate_02_no_destroy", "gate_03_test_before_deploy"}


# ── Data container ────────────────────────────────────────────────────────────

@dataclass
class GateMetrics:
    """Computed effectiveness metrics for a single gate.

    Attributes:
        blocks:           Total block events recorded in effectiveness file.
        overrides:        Times a block was overridden by the user.
        prevented:        Harmful actions prevented (from effectiveness file).
        fires:            Approximated total evaluations (= blocks, conservative).
        block_rate:       Fraction of gated tool calls that this gate blocked.
        coverage:         Fraction of total tool calls this gate touched.
        effectiveness:    Log-scaled impact score penalised by override rate.
        value_score:      Final ranking score: 40% coverage + 40% effectiveness
                          + 20% prevented-incidents bonus.
        tool_calls_total: Total non-prompt tool calls from the capture queue
                          (denominator for coverage computation).
    """
    blocks: int = 0
    overrides: int = 0
    prevented: int = 0
    fires: int = 0
    block_rate: float = 0.0
    coverage: float = 0.0
    effectiveness: float = 0.0
    value_score: float = 0.0
    tool_calls_total: int = 0


# ── File loaders ──────────────────────────────────────────────────────────────

def _load_effectiveness() -> Dict[str, dict]:
    """Load raw gate effectiveness data.

    Returns:
        dict keyed by gate name with block/override/prevented counts.
        Returns {} on missing or corrupt file.
    """
    try:
        with open(EFFECTIVENESS_FILE, "r") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _load_capture_queue() -> List[dict]:
    """Load all metadata records from .capture_queue.jsonl.

    Silently skips corrupt or empty lines.

    Returns:
        list of metadata dicts, one per captured tool call observation.
    """
    records: List[dict] = []
    try:
        with open(CAPTURE_QUEUE_FILE, "r") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    meta = obj.get("metadata")
                    if isinstance(meta, dict):
                        records.append(meta)
                except (json.JSONDecodeError, AttributeError):
                    continue
    except (FileNotFoundError, OSError):
        pass
    return records


# ── Core computation ──────────────────────────────────────────────────────────

def _normalise_key(raw_key: str) -> str:
    """Strip whitespace from a gate key."""
    return raw_key.strip()


def get_gate_metrics() -> Dict[str, GateMetrics]:
    """Compute per-gate effectiveness metrics.

    Combines data from .gate_effectiveness.json (blocks, overrides, prevented)
    and .capture_queue.jsonl (tool call volume for coverage/block_rate).

    Block counts in the effectiveness file sometimes use the key 'block' (older
    format) instead of 'blocks'; both are handled transparently.

    Returns:
        dict mapping normalised gate key -> GateMetrics.
    """
    raw = _load_effectiveness()
    queue = _load_capture_queue()

    # Queue-level denominators
    gated_tool_count = sum(
        1 for m in queue if m.get("tool_name", "") in _GATED_TOOLS
    )
    total_tool_count = sum(
        1 for m in queue
        if m.get("tool_name", "") not in {"UserPrompt", "PreCompact"}
    )

    metrics: Dict[str, GateMetrics] = {}

    for raw_key, entry in raw.items():
        key = _normalise_key(raw_key)

        # Support both 'blocks' (current) and 'block' (legacy) keys
        blocks = int(entry.get("blocks", 0) or entry.get("block", 0))
        overrides = int(entry.get("overrides", 0))
        prevented = int(entry.get("prevented", 0))

        # fires: blocks is a conservative lower bound (passes are not tracked per-gate)
        fires = blocks

        # block_rate: blocks relative to gated tool calls
        block_rate = min(1.0, blocks / gated_tool_count) if gated_tool_count > 0 else 0.0

        # coverage: blocks relative to all tracked tool calls
        coverage = min(1.0, blocks / total_tool_count) if total_tool_count > 0 else 0.0

        # effectiveness: log-scaled, penalised by override ratio
        if total_tool_count > 0 and blocks > 0:
            override_ratio = min(1.0, overrides / blocks)
            effectiveness = (
                math.log1p(blocks) / math.log1p(total_tool_count)
                * (1.0 - override_ratio)
            )
        else:
            effectiveness = 0.0

        # prevented_bonus: log-scaled contribution from confirmed prevented incidents
        prevented_bonus = (
            min(1.0, math.log1p(prevented) / math.log1p(10))
            if prevented > 0 else 0.0
        )

        # value_score: blended ranking score
        value_score = 0.40 * coverage + 0.40 * effectiveness + 0.20 * prevented_bonus

        metrics[key] = GateMetrics(
            blocks=blocks,
            overrides=overrides,
            prevented=prevented,
            fires=fires,
            block_rate=block_rate,
            coverage=coverage,
            effectiveness=effectiveness,
            value_score=value_score,
            tool_calls_total=total_tool_count,
        )

    return metrics


def rank_gates_by_value() -> List[Tuple[str, GateMetrics]]:
    """Return all gates sorted by value_score descending.

    Returns:
        list of (gate_key, GateMetrics) tuples, highest-value first.
    """
    metrics = get_gate_metrics()
    return sorted(metrics.items(), key=lambda kv: kv[1].value_score, reverse=True)


# ── Rendering ─────────────────────────────────────────────────────────────────

def _label(gate_key: str) -> str:
    """Return a short display label for a gate key."""
    return _GATE_LABELS.get(gate_key, gate_key)


def render_dashboard() -> str:
    """Render a human-readable gate effectiveness dashboard.

    Columns: Rank, Gate label, Blocks, BlockRate, Coverage, Effectiveness, ValueScore.
    Rows are sorted by value_score descending (highest-value gate first).

    Returns:
        Multi-line string suitable for terminal output or logging.
        Returns a short notice if the effectiveness file is absent.
    """
    ranked = rank_gates_by_value()
    if not ranked:
        return "Gate Dashboard: no effectiveness data found at " + EFFECTIVENESS_FILE

    queue = _load_capture_queue()
    gated_count = sum(1 for m in queue if m.get("tool_name", "") in _GATED_TOOLS)
    total_count = len(queue)

    lines = [
        "=" * 80,
        "  GATE EFFECTIVENESS DASHBOARD",
        "=" * 80,
        f"  Observations in queue: {total_count:,}  |  Gated tool calls: {gated_count:,}",
        "",
        f"  {'#':>2}  {'Gate':<28}  {'Blocks':>8}  {'BlkRate':>8}"
        f"  {'Cover':>6}  {'Effect':>8}  {'Value':>7}",
        "  " + "-" * 74,
    ]

    for rank, (key, m) in enumerate(ranked, 1):
        label = _label(key)
        lines.append(
            f"  {rank:>2}  {label:<28}  {m.blocks:>8,}  "
            f"{m.block_rate:>7.1%}  "
            f"{m.coverage:>5.1%}  "
            f"{m.effectiveness:>8.4f}  "
            f"{m.value_score:>7.4f}"
        )

    lines.append("  " + "-" * 74)
    lines.append("")

    # Incidents prevented section (shown only when any gate has prevented > 0)
    if any(m.prevented > 0 for _, m in ranked):
        lines.append("  Confirmed Incidents Prevented:")
        for key, m in ranked:
            if m.prevented > 0:
                lines.append(f"    {_label(key):<28}  {m.prevented} incident(s)")
        lines.append("")

    lines.append("=" * 80)
    return "\n".join(lines)


# ── Recommendations ───────────────────────────────────────────────────────────

def get_recommendations() -> List[str]:
    """Generate actionable recommendations based on gate metrics.

    Checks for:
    - Elevated override rates (gate too aggressive)
    - Legacy 'block' key vs 'blocks' key inconsistency in effectiveness file
    - High block counts with zero confirmed-prevented incidents
    - Gates with very low block counts (possibly dormant or misconfigured)
    - Top-performing gate summary
    - System-wide totals

    Returns:
        list of human-readable strings, highest-priority issues first.
        Returns a single-item list with a notice if effectiveness file is absent.
    """
    metrics = get_gate_metrics()
    if not metrics:
        return [
            "No gate effectiveness data found. Run at least one session to populate "
            + EFFECTIVENESS_FILE
        ]

    recs: List[Tuple[int, str]] = []  # (priority, message)

    total_blocks = sum(m.blocks for m in metrics.values())
    total_prevented = sum(m.prevented for m in metrics.values())
    raw = _load_effectiveness()

    # Priority 30: Elevated override rate -- gate may be too aggressive
    for key, m in metrics.items():
        if m.blocks > 10 and m.overrides > 0:
            override_rate = m.overrides / m.blocks
            if override_rate > 0.10:
                recs.append((
                    30,
                    f"{_label(key)}: {override_rate:.0%} override rate "
                    f"({m.overrides} overrides / {m.blocks:,} blocks). "
                    "Gate may be firing too aggressively -- review thresholds."
                ))

    # Priority 25: Legacy 'block' key instead of 'blocks' in effectiveness file
    for raw_key, entry in raw.items():
        if int(entry.get("blocks", 0)) == 0 and int(entry.get("block", 0)) > 0:
            alt = int(entry.get("block", 0))
            recs.append((
                25,
                f"{_label(_normalise_key(raw_key))}: effectiveness file uses legacy 'block' "
                f"key (value={alt}) instead of 'blocks'. Normalise key for consistent tracking."
            ))

    # Priority 20: High block count but zero confirmed incidents prevented
    for key, m in metrics.items():
        if m.blocks > 100 and m.prevented == 0 and key not in _TIER1_GATES:
            recs.append((
                20,
                f"{_label(key)}: {m.blocks:,} blocks recorded but 0 confirmed incidents "
                "prevented. Consider auditing block quality or adding 'prevented' tracking."
            ))

    # Priority 10: Suspiciously low block count (possible misconfiguration)
    # Gates expected to be rare by design are excluded
    _rare_by_design = {
        "gate_10_model_enforcement",
        "gate_14_confidence_check",
        "gate_15_causal_chain",
    }
    for key, m in metrics.items():
        if key in _rare_by_design:
            continue
        if m.blocks < 5:
            recs.append((
                10,
                f"{_label(key)}: only {m.blocks} total blocks -- gate may be dormant or "
                "conditions too rare. Verify it is correctly registered in enforcer.py."
            ))

    # Priority 5: Top gate celebration
    ranked = rank_gates_by_value()
    if ranked:
        top_key, top_m = ranked[0]
        recs.append((
            5,
            f"Top gate by value score: {_label(top_key)} "
            f"(score={top_m.value_score:.4f}, {top_m.blocks:,} blocks, "
            f"{top_m.prevented} prevented). Provides the most measurable protection."
        ))

    # Priority 1: System summary
    recs.append((
        1,
        f"System totals: {total_blocks:,} blocks across {len(metrics)} active gate(s), "
        f"{total_prevented} incident(s) confirmed prevented."
    ))

    # Sort highest-priority first, return messages only
    recs.sort(key=lambda x: x[0], reverse=True)
    return [msg for _, msg in recs]


# ── Module smoke test ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys as _sys

    print(render_dashboard())
    print()
    print("Recommendations:")
    for i, rec in enumerate(get_recommendations(), 1):
        print(f"  {i}. {rec}")
    print()

    # Validation checks
    metrics = get_gate_metrics()
    ranked = rank_gates_by_value()
    errors: List[str] = []

    def _check(name: str, cond: bool, detail: str = "") -> None:
        if cond:
            print(f"  PASS  {name}")
        else:
            print(f"  FAIL  {name}" + (f" -- {detail}" if detail else ""))
            errors.append(name)

    _check("get_gate_metrics returns dict", isinstance(metrics, dict))
    _check("metrics non-empty", len(metrics) > 0, f"got {len(metrics)}")
    _check("rank_gates_by_value returns list", isinstance(ranked, list))
    _check("ranked length matches metrics", len(ranked) == len(metrics))
    if len(ranked) >= 2:
        _check(
            "ranked descending by value_score",
            ranked[0][1].value_score >= ranked[-1][1].value_score,
        )
    dash = render_dashboard()
    _check("render_dashboard returns non-empty str",
           isinstance(dash, str) and len(dash) > 50)
    _check("render_dashboard contains header",
           "GATE EFFECTIVENESS DASHBOARD" in dash)
    recs = get_recommendations()
    _check("get_recommendations returns list", isinstance(recs, list))
    _check("get_recommendations non-empty", len(recs) > 0)

    if "gate_01_read_before_edit" in metrics:
        m01 = metrics["gate_01_read_before_edit"]
        _check("gate_01 blocks > 0", m01.blocks > 0, f"got {m01.blocks}")
        _check("gate_01 block_rate in [0,1]", 0.0 <= m01.block_rate <= 1.0)
        _check("gate_01 coverage in [0,1]", 0.0 <= m01.coverage <= 1.0)
        _check("gate_01 value_score >= 0", m01.value_score >= 0.0)
        _check("gate_01 effectiveness >= 0", m01.effectiveness >= 0.0)
    else:
        _check("gate_01 present in metrics", False, "key missing")

    print()
    if errors:
        print(f"FAILED: {len(errors)} test(s): {errors}")
        _sys.exit(1)
    else:
        print("ALL TESTS PASSED")
        _sys.exit(0)
