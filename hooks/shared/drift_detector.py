"""Drift detection for gate effectiveness metrics.

Compares current gate fire rate vectors against baselines using cosine
similarity to detect meaningful shifts in gate behavior over time.
"""

import math
from typing import Dict


def cosine_similarity(vec_a: Dict[str, float], vec_b: Dict[str, float]) -> float:
    """Cosine similarity between two sparse vectors (0.0–1.0).

    Returns 1.0 for identical direction, 0.0 for orthogonal, and handles
    zero vectors by returning 0.0.
    """
    keys = set(vec_a) | set(vec_b)
    if not keys:
        return 1.0

    dot = sum(vec_a.get(k, 0.0) * vec_b.get(k, 0.0) for k in keys)
    mag_a = math.sqrt(sum(v * v for v in vec_a.values()))
    mag_b = math.sqrt(sum(v * v for v in vec_b.values()))

    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0

    # Clamp to [0, 1] to avoid float precision issues
    return max(0.0, min(1.0, dot / (mag_a * mag_b)))


def detect_drift(current: Dict[str, float], baseline: Dict[str, float]) -> float:
    """Drift score between 0.0 (identical) and 1.0 (completely different).

    Derived from cosine similarity: drift = 1 - similarity.
    """
    return 1.0 - cosine_similarity(current, baseline)


def should_alert(drift_score: float, threshold: float = 0.3) -> bool:
    """True if drift_score exceeds threshold, indicating significant drift."""
    return drift_score > threshold


def gate_drift_report(
    current: Dict[str, float],
    baseline: Dict[str, float],
) -> Dict:
    """Build a drift report comparing current gate fire rates to baseline.

    Returns:
        dict with keys:
          - drift_score: float 0–1
          - alert: bool (True if drift exceeds default threshold 0.3)
          - per_gate_deltas: dict mapping gate name → (current - baseline)
    """
    drift_score = detect_drift(current, baseline)
    alert = should_alert(drift_score)

    all_gates = set(current) | set(baseline)
    per_gate_deltas = {
        gate: current.get(gate, 0.0) - baseline.get(gate, 0.0)
        for gate in sorted(all_gates)
    }

    return {
        "drift_score": drift_score,
        "alert": alert,
        "per_gate_deltas": per_gate_deltas,
    }
