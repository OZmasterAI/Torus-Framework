"""Anomaly detection for gate fire rate monitoring.

Detects gates firing at statistically unusual rates and single-gate
dominance (stuck loops), then determines whether escalation is needed.
"""

import math
from typing import Dict, List, Optional, Tuple


def compute_baseline(
    history: List[Dict[str, float]], window: int = 10
) -> Dict[str, float]:
    """Compute average gate fire rates from recent history.

    Args:
        history: List of dicts mapping gate name -> fire rate per snapshot.
                 Most recent entries should appear last.
        window:  Maximum number of most-recent snapshots to average over.

    Returns:
        Dict mapping gate name -> mean fire rate across the window.
        Gates absent from a snapshot are treated as 0.0 for that snapshot.
    """
    if not history:
        return {}

    window_data = history[-window:]
    all_gates: set = set()
    for snapshot in window_data:
        all_gates.update(snapshot.keys())

    baseline: Dict[str, float] = {}
    n = len(window_data)
    for gate in all_gates:
        total = sum(snapshot.get(gate, 0.0) for snapshot in window_data)
        baseline[gate] = total / n

    return baseline


def _stddev(values: List[float]) -> float:
    """Population standard deviation of a list of floats."""
    n = len(values)
    if n == 0:
        return 0.0
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    return math.sqrt(variance)


def detect_anomalies(
    current: Dict[str, float],
    baseline: Dict[str, float],
    threshold_sigma: float = 2.0,
) -> List[Dict]:
    """Find gates whose current fire rate is anomalously high.

    A gate is anomalous if its current rate exceeds
    (baseline_mean + threshold_sigma * baseline_stddev) across all gates,
    where the stddev is computed over all baseline values.

    Args:
        current:         Dict mapping gate name -> current fire rate.
        baseline:        Dict mapping gate name -> mean fire rate (from compute_baseline).
        threshold_sigma: Number of standard deviations above the mean to flag.

    Returns:
        List of dicts, each with keys:
          - gate: str
          - current_rate: float
          - baseline_rate: float
          - delta: float  (current - baseline)
          - sigma: float  (how many stddevs above baseline mean)
    """
    if not baseline:
        return []

    baseline_values = list(baseline.values())
    mean_all = sum(baseline_values) / len(baseline_values)
    std_all = _stddev(baseline_values)

    anomalies = []
    for gate, rate in current.items():
        baseline_rate = baseline.get(gate, 0.0)
        threshold = mean_all + threshold_sigma * std_all
        if rate > threshold and rate > baseline_rate:
            sigma = (rate - mean_all) / std_all if std_all > 0 else float("inf")
            anomalies.append(
                {
                    "gate": gate,
                    "current_rate": rate,
                    "baseline_rate": baseline_rate,
                    "delta": rate - baseline_rate,
                    "sigma": sigma,
                }
            )

    # Sort descending by delta for easy inspection
    anomalies.sort(key=lambda x: x["delta"], reverse=True)
    return anomalies


def detect_stuck_loop(
    recent_gates: List[str],
    window: int = 20,
    threshold: float = 0.7,
) -> Optional[str]:
    """Detect if a single gate is dominating recent activity.

    Args:
        recent_gates: Ordered list of gate names that fired recently
                      (most recent last).
        window:       Number of most-recent gate firings to examine.
        threshold:    Fraction of the window a single gate must occupy
                      to be considered dominant (0.0–1.0).

    Returns:
        The name of the dominant gate if one exceeds the threshold,
        otherwise None.
    """
    if not recent_gates:
        return None

    window_gates = recent_gates[-window:]
    n = len(window_gates)
    if n == 0:
        return None

    counts: Dict[str, int] = {}
    for gate in window_gates:
        counts[gate] = counts.get(gate, 0) + 1

    dominant_gate = max(counts, key=lambda g: counts[g])
    fraction = counts[dominant_gate] / n
    if fraction >= threshold:
        return dominant_gate

    return None


def should_escalate(
    anomalies: List[Dict],
    stuck_gate: Optional[str],
) -> Tuple[bool, str]:
    """Determine whether the anomaly situation warrants user notification.

    Escalation rules (any one is sufficient):
    1. A stuck loop was detected (single gate dominates recent firings).
    2. Any anomaly has a delta >= 5.0 (very large spike).
    3. Three or more gates are simultaneously anomalous.

    Args:
        anomalies:  Output of detect_anomalies().
        stuck_gate: Output of detect_stuck_loop() (None if no loop).

    Returns:
        (should_escalate: bool, reason: str)
    """
    if stuck_gate is not None:
        return True, f"Stuck loop detected: gate '{stuck_gate}' is dominating recent activity"

    if len(anomalies) >= 3:
        gates = ", ".join(a["gate"] for a in anomalies[:3])
        return True, f"Multiple simultaneous anomalies ({len(anomalies)} gates): {gates}"

    for anomaly in anomalies:
        if anomaly["delta"] >= 5.0:
            return (
                True,
                f"Large spike on gate '{anomaly['gate']}': "
                f"+{anomaly['delta']:.1f} above baseline",
            )

    if anomalies:
        return False, f"Minor anomalies detected on {len(anomalies)} gate(s) — monitoring"

    return False, "No anomalies detected"
