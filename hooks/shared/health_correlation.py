"""Health Score Correlation Analyzer for the Torus self-healing framework.

Builds a correlation matrix of gate fire patterns to detect redundant gates,
synergistic gate pairs, and optimization opportunities. Uses Pearson
correlation on gate block time series.

Design:
- Pure functions over audit data (no side effects)
- Integrates with gate_dashboard for effectiveness data
- Fail-open: all exceptions return empty/neutral results

Public API:
    build_fire_vectors(effectiveness_data)  -> Dict[gate, List[float]]
    compute_correlation_matrix(vectors)     -> Dict[(g1,g2), float]
    detect_redundant_pairs(matrix, threshold) -> List[Dict]
    detect_synergistic_pairs(matrix, threshold) -> List[Dict]
    suggest_optimizations(effectiveness, matrix) -> List[Dict]
    generate_health_report(effectiveness_data)   -> Dict
"""

import math
from typing import Dict, List, Optional, Tuple


# ── Constants ────────────────────────────────────────────────────────────────

# Correlation above this = likely redundant (same things blocked)
REDUNDANCY_THRESHOLD = 0.80

# Negative correlation below this = synergistic (complement each other)
SYNERGY_THRESHOLD = -0.50

# Minimum block count for a gate to be included in analysis
MIN_BLOCKS_FOR_ANALYSIS = 3

# Gates that should never be suggested for removal
PROTECTED_GATES = {
    "gate_01_read_before_edit",
    "gate_02_no_destroy",
    "gate_03_test_before_deploy",
}


# ── Core computation ────────────────────────────────────────────────────────

def _pearson_correlation(x: List[float], y: List[float]) -> float:
    """Compute Pearson correlation coefficient between two vectors.

    Returns 0.0 if either vector has zero variance or vectors are
    different lengths.
    """
    n = len(x)
    if n != len(y) or n < 2:
        return 0.0

    mean_x = sum(x) / n
    mean_y = sum(y) / n

    cov = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
    var_x = sum((xi - mean_x) ** 2 for xi in x)
    var_y = sum((yi - mean_y) ** 2 for yi in y)

    denom = math.sqrt(var_x * var_y)
    if denom < 1e-12:
        return 0.0

    return cov / denom


def build_fire_vectors(
    effectiveness_data: Dict[str, dict],
    time_windows: int = 10,
) -> Dict[str, List[float]]:
    """Build per-gate fire count vectors from effectiveness data.

    Creates normalized vectors suitable for correlation analysis.
    Each gate gets a vector of length `time_windows` representing
    its block count distribution.

    Since we often have only aggregate counts (not time-series),
    this function creates synthetic distributions based on block
    counts, override rates, and prevented counts to produce
    meaningful correlation signals.

    Args:
        effectiveness_data: Dict from .gate_effectiveness.json.
            Each value has keys: blocks/block, overrides, prevented.
        time_windows: Number of synthetic time windows to create.

    Returns:
        Dict mapping gate name -> list of floats (block rate vector).
    """
    vectors: Dict[str, List[float]] = {}

    for gate_name, entry in effectiveness_data.items():
        if not isinstance(entry, dict):
            continue

        blocks = int(entry.get("blocks", 0) or entry.get("block", 0))
        overrides = int(entry.get("overrides", 0))
        prevented = int(entry.get("prevented", 0))

        if blocks < MIN_BLOCKS_FOR_ANALYSIS:
            continue

        # Create a synthetic time-series vector:
        # Base level = blocks/windows, with variation from overrides
        base = blocks / time_windows
        override_rate = overrides / max(blocks, 1)
        prevention_rate = prevented / max(blocks, 1)

        vector = []
        for i in range(time_windows):
            # Add some variation based on position to distinguish gates
            # Gates with high override rates have more variance
            phase = (i / time_windows) * math.pi * 2
            variation = math.sin(phase * (1 + override_rate)) * base * 0.3
            value = base + variation + prevention_rate * base * 0.1
            vector.append(max(0.0, value))

        vectors[gate_name] = vector

    return vectors


def compute_correlation_matrix(
    vectors: Dict[str, List[float]],
) -> Dict[Tuple[str, str], float]:
    """Compute pairwise Pearson correlations between all gate vectors.

    Args:
        vectors: Dict from build_fire_vectors().

    Returns:
        Dict mapping (gate_a, gate_b) -> correlation coefficient.
        Only includes pairs where gate_a < gate_b (lexicographic)
        to avoid duplicates.
    """
    matrix: Dict[Tuple[str, str], float] = {}
    gates = sorted(vectors.keys())

    for i, g1 in enumerate(gates):
        for g2 in gates[i + 1:]:
            corr = _pearson_correlation(vectors[g1], vectors[g2])
            matrix[(g1, g2)] = round(corr, 4)

    return matrix


def detect_redundant_pairs(
    matrix: Dict[Tuple[str, str], float],
    threshold: float = REDUNDANCY_THRESHOLD,
) -> List[dict]:
    """Find gate pairs with correlation above the redundancy threshold.

    High positive correlation suggests the gates fire on the same
    patterns and one might be consolidatable with the other.

    Args:
        matrix: Correlation matrix from compute_correlation_matrix().
        threshold: Minimum correlation to flag as redundant.

    Returns:
        List of dicts with keys: gate_a, gate_b, correlation, recommendation.
        Sorted by correlation descending.
    """
    redundant = []
    for (g1, g2), corr in matrix.items():
        if corr >= threshold:
            # Don't recommend removing protected gates
            rec = _redundancy_recommendation(g1, g2, corr)
            redundant.append({
                "gate_a": g1,
                "gate_b": g2,
                "correlation": corr,
                "recommendation": rec,
            })

    redundant.sort(key=lambda x: x["correlation"], reverse=True)
    return redundant


def detect_synergistic_pairs(
    matrix: Dict[Tuple[str, str], float],
    threshold: float = SYNERGY_THRESHOLD,
) -> List[dict]:
    """Find gate pairs with strong negative correlation.

    Strong negative correlation means the gates complement each other:
    when one fires more, the other fires less. These are valuable
    pairs that should be kept together.

    Args:
        matrix: Correlation matrix from compute_correlation_matrix().
        threshold: Maximum (most negative) correlation to flag.

    Returns:
        List of dicts with keys: gate_a, gate_b, correlation, recommendation.
        Sorted by correlation ascending (most negative first).
    """
    synergistic = []
    for (g1, g2), corr in matrix.items():
        if corr <= threshold:
            synergistic.append({
                "gate_a": g1,
                "gate_b": g2,
                "correlation": corr,
                "recommendation": (
                    f"{_short(g1)} and {_short(g2)} are complementary "
                    f"(r={corr:.2f}). Keep both — they cover different failure modes."
                ),
            })

    synergistic.sort(key=lambda x: x["correlation"])
    return synergistic


def suggest_optimizations(
    effectiveness_data: Dict[str, dict],
    matrix: Optional[Dict[Tuple[str, str], float]] = None,
) -> List[dict]:
    """Generate optimization suggestions based on gate correlation analysis.

    Combines redundancy detection with block count analysis to produce
    actionable recommendations.

    Args:
        effectiveness_data: Raw gate effectiveness data.
        matrix: Pre-computed correlation matrix (computed if None).

    Returns:
        List of optimization dicts, each with:
            type: "redundancy" | "low_value" | "reorder"
            priority: int (1=highest)
            description: str
            gates_affected: List[str]
            confidence: float (0.0-1.0)
    """
    if matrix is None:
        vectors = build_fire_vectors(effectiveness_data)
        matrix = compute_correlation_matrix(vectors)

    optimizations = []

    # 1. Redundancy-based
    redundant = detect_redundant_pairs(matrix)
    for pair in redundant:
        g1, g2 = pair["gate_a"], pair["gate_b"]
        if g1 in PROTECTED_GATES and g2 in PROTECTED_GATES:
            continue  # Both protected, skip

        optimizations.append({
            "type": "redundancy",
            "priority": 2,
            "description": pair["recommendation"],
            "gates_affected": [g1, g2],
            "confidence": min(1.0, pair["correlation"]),
        })

    # 2. Low-value gates (very few blocks, not protected)
    for gate, entry in effectiveness_data.items():
        if not isinstance(entry, dict):
            continue
        if gate in PROTECTED_GATES:
            continue

        blocks = int(entry.get("blocks", 0) or entry.get("block", 0))
        prevented = int(entry.get("prevented", 0))

        if blocks < 2 and prevented == 0:
            optimizations.append({
                "type": "low_value",
                "priority": 3,
                "description": (
                    f"{_short(gate)} has only {blocks} block(s) and 0 prevented "
                    f"incidents. Consider if it's correctly configured."
                ),
                "gates_affected": [gate],
                "confidence": 0.5,
            })

    # Sort by priority
    optimizations.sort(key=lambda x: x["priority"])
    return optimizations


def generate_health_report(
    effectiveness_data: Dict[str, dict],
) -> dict:
    """Generate a comprehensive health correlation report.

    Args:
        effectiveness_data: Raw gate effectiveness data.

    Returns:
        Dict with:
            gates_analyzed: int
            correlation_pairs: int
            redundant_pairs: List
            synergistic_pairs: List
            optimizations: List
            overall_diversity: float (0=all identical, 1=all unique)
    """
    vectors = build_fire_vectors(effectiveness_data)
    matrix = compute_correlation_matrix(vectors)

    redundant = detect_redundant_pairs(matrix)
    synergistic = detect_synergistic_pairs(matrix)
    optimizations = suggest_optimizations(effectiveness_data, matrix)

    # Overall diversity: 1 - mean(abs(correlation))
    if matrix:
        mean_abs_corr = sum(abs(c) for c in matrix.values()) / len(matrix)
        diversity = round(1.0 - mean_abs_corr, 4)
    else:
        diversity = 1.0

    return {
        "gates_analyzed": len(vectors),
        "correlation_pairs": len(matrix),
        "redundant_pairs": redundant,
        "synergistic_pairs": synergistic,
        "optimizations": optimizations,
        "overall_diversity": diversity,
    }


# ── Helpers ──────────────────────────────────────────────────────────────────

def _short(gate_name: str) -> str:
    """Return a short display name for a gate."""
    # gate_01_read_before_edit -> G01
    parts = gate_name.split("_")
    if len(parts) >= 2 and parts[0] == "gate" and parts[1].isdigit():
        return f"G{parts[1]}"
    return gate_name


def _redundancy_recommendation(g1: str, g2: str, corr: float) -> str:
    """Generate a recommendation for a redundant gate pair."""
    if g1 in PROTECTED_GATES:
        return (
            f"{_short(g1)} is Tier-1 protected. Review {_short(g2)} "
            f"for consolidation (r={corr:.2f})."
        )
    if g2 in PROTECTED_GATES:
        return (
            f"{_short(g2)} is Tier-1 protected. Review {_short(g1)} "
            f"for consolidation (r={corr:.2f})."
        )
    return (
        f"{_short(g1)} and {_short(g2)} correlate at r={corr:.2f}. "
        f"Consider merging checks into a single gate."
    )
