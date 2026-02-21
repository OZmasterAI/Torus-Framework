"""Anomaly detection for gate fire rate monitoring.

Detects gates firing at statistically unusual rates and single-gate
dominance (stuck loops), then determines whether escalation is needed.

Also provides session-level behavioral drift detection: analyzes tool call
patterns, gate block rates, error frequencies, and memory query gaps to
surface anomalous session behavior.
"""

import math
import time
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


# ---------------------------------------------------------------------------
# Session-level behavioral drift detection
# ---------------------------------------------------------------------------

# Thresholds for deviation detection
_TOOL_RATE_SIGMA_THRESHOLD = 3.0      # std devs above mean = unusual tool call burst
_TOOL_DOMINANCE_RATIO = 0.7           # single tool > 70% of all calls = dominant
_BLOCK_RATE_HIGH_THRESHOLD = 0.5      # >50 % of tool calls blocked = anomalous
_ERROR_RATE_HIGH_THRESHOLD = 0.3      # >30 % of tool calls produce errors = anomalous
_MEMORY_GAP_SECONDS = 600             # 10 min without a memory query = suspicious


def check_tool_dominance(tool_stats: Dict[str, int]) -> Optional[Dict]:
    """Check if a single tool dominates tool call usage.

    Flags when a single tool accounts for more than _TOOL_DOMINANCE_RATIO
    (70%) of all tool calls, indicating a possible runaway loop or
    over-reliance on one tool.

    Args:
        tool_stats: Dict mapping tool name -> call count.

    Returns:
        Dict with keys:
          - tool: str — name of the dominant tool
          - count: int — number of calls for that tool
          - ratio: float — fraction of total calls (0.0–1.0)
          - total: int — total tool calls across all tools
        or None if no single tool exceeds the dominance threshold.
    """
    if not tool_stats:
        return None

    total = sum(tool_stats.values())
    if total == 0:
        return None

    dominant_tool = max(tool_stats, key=lambda t: tool_stats[t])
    count = tool_stats[dominant_tool]
    ratio = count / total

    if ratio > _TOOL_DOMINANCE_RATIO:
        return {
            "tool": dominant_tool,
            "count": count,
            "ratio": ratio,
            "total": total,
        }

    return None


def get_session_baseline(state: Dict) -> Dict[str, float]:
    """Extract behavioral baseline from session state.

    Derives observable metrics from the raw session state that can be
    compared against expected behavior or historical baselines.

    Args:
        state: Session state dict (as returned by shared.state.load_state).

    Returns:
        Dict with keys:
          - tool_call_rate: average tool calls per minute (0.0 if <1 min elapsed)
          - gate_block_rate: fraction of tool calls that were gate-blocked (0.0–1.0)
          - error_rate: fraction of tool calls that produced logged errors (0.0–1.0)
          - memory_query_interval: seconds since last memory query (float)
    """
    now = time.time()
    session_start = state.get("session_start", now)
    elapsed_seconds = max(now - session_start, 1.0)
    elapsed_minutes = elapsed_seconds / 60.0

    total_tool_calls = max(state.get("total_tool_calls", 0), 1)

    # Tool call rate: calls / minute
    tool_call_rate = total_tool_calls / elapsed_minutes

    # Gate block rate: count outcomes with a resolved_by != None or derive from
    # gate_block_outcomes list (each entry represents one block event).
    gate_block_outcomes: List[Dict] = state.get("gate_block_outcomes", [])
    gate_block_rate = len(gate_block_outcomes) / total_tool_calls

    # Error rate: fraction of tool calls that generated unlogged errors
    unlogged_errors: List = state.get("unlogged_errors", [])
    error_rate = len(unlogged_errors) / total_tool_calls

    # Memory query gap: seconds since last memory query
    memory_last_queried = state.get("memory_last_queried", 0.0)
    if memory_last_queried and memory_last_queried > 0:
        memory_query_interval = now - memory_last_queried
    else:
        # Never queried — treat as entire session duration
        memory_query_interval = elapsed_seconds

    return {
        "tool_call_rate": tool_call_rate,
        "gate_block_rate": gate_block_rate,
        "error_rate": error_rate,
        "memory_query_interval": memory_query_interval,
    }


def compare_to_baseline(
    current_metrics: Dict[str, float],
    baseline: Dict[str, float],
) -> List[Dict]:
    """Compare current session metrics to a baseline and return deviations.

    Computes the absolute and relative deviation for each metric.  A
    deviation is reported when the absolute difference exceeds a per-metric
    threshold *or* the relative change is large enough to be meaningful.

    Args:
        current_metrics: Dict from get_session_baseline() or equivalent.
        baseline:        Historical baseline dict (same schema).

    Returns:
        List of dicts, each with keys:
          - metric: str — name of the metric
          - current: float
          - baseline: float
          - delta: float (current - baseline)
          - relative_change: float ((current - baseline) / max(baseline, 1e-9))
          - severity: "warning" | "critical"
    """
    deviations: List[Dict] = []

    # Per-metric thresholds: (relative_change_threshold, severity)
    thresholds = {
        "tool_call_rate":        (0.5, "warning"),   # >50 % change in call rate
        "gate_block_rate":       (0.3, "critical"),  # >30 % change in block rate
        "error_rate":            (0.25, "critical"), # >25 % change in error rate
        "memory_query_interval": (0.5, "warning"),   # >50 % increase in gap
    }

    for metric, (rel_threshold, severity) in thresholds.items():
        current_val = current_metrics.get(metric, 0.0)
        baseline_val = baseline.get(metric, 0.0)
        delta = current_val - baseline_val
        denom = max(abs(baseline_val), 1e-9)
        relative_change = delta / denom

        if abs(relative_change) >= rel_threshold:
            deviations.append(
                {
                    "metric": metric,
                    "current": current_val,
                    "baseline": baseline_val,
                    "delta": delta,
                    "relative_change": relative_change,
                    "severity": severity,
                }
            )

    return deviations


def detect_behavioral_anomaly(state: Dict) -> List[Tuple[str, str, str]]:
    """Analyze session state for behavioral anomalies.

    Checks:
    - Unusual tool call patterns (>3 std devs from mean across recent windows)
    - Gate block rate anomalies (>50 % of calls blocked)
    - Error frequency spikes (>30 % of calls produce errors)
    - Memory query gaps (>10 min without a memory check)

    Args:
        state: Session state dict (as returned by shared.state.load_state).

    Returns:
        List of (anomaly_type, severity, description) tuples.
        anomaly_type: one of "tool_call_burst", "high_block_rate",
                      "high_error_rate", "memory_query_gap"
        severity: "warning" | "critical"
        description: human-readable explanation
    """
    anomalies: List[Tuple[str, str, str]] = []
    metrics = get_session_baseline(state)

    # --- 1. Unusual tool call patterns ---
    # Two detection methods (either triggers):
    #   a) Statistical: sigma above mean exceeds threshold (many-tool scenarios)
    #   b) Dominance: single tool > _TOOL_DOMINANCE_RATIO of total (few-tool)
    tool_call_counts: Dict[str, int] = state.get("tool_call_counts", {})
    if len(tool_call_counts) >= 2:
        counts = list(tool_call_counts.values())
        mean_count = sum(counts) / len(counts)
        std_count = _stddev([float(c) for c in counts])
        max_count = max(counts)

        # Method a: sigma-based detection
        sigma_triggered = False
        sigma = 0.0
        if std_count > 0:
            sigma = (max_count - mean_count) / std_count
            sigma_triggered = sigma > _TOOL_RATE_SIGMA_THRESHOLD

        # Method b: ratio-based dominance detection via check_tool_dominance
        dominance = check_tool_dominance(tool_call_counts)
        ratio_triggered = dominance is not None

        if sigma_triggered or ratio_triggered:
            dominant_tool = max(tool_call_counts, key=lambda t: tool_call_counts[t])
            desc_parts = []
            if sigma_triggered:
                desc_parts.append(f"{sigma:.1f}σ above mean {mean_count:.1f}")
            if ratio_triggered and dominance:
                desc_parts.append(f"{dominance['ratio']:.0%} of all calls")
            anomalies.append(
                (
                    "tool_call_burst",
                    "warning",
                    f"Tool '{dominant_tool}' called {max_count} times "
                    f"({', '.join(desc_parts)}) — "
                    "possible runaway loop",
                )
            )

    # --- 2. Gate block rate ---
    block_rate = metrics["gate_block_rate"]
    if block_rate > _BLOCK_RATE_HIGH_THRESHOLD:
        anomalies.append(
            (
                "high_block_rate",
                "critical",
                f"Gate block rate is {block_rate:.1%} of all tool calls "
                f"(threshold {_BLOCK_RATE_HIGH_THRESHOLD:.0%}) — "
                "agent may be stuck in a blocked pattern",
            )
        )

    # --- 3. Error frequency spikes ---
    error_rate = metrics["error_rate"]
    if error_rate > _ERROR_RATE_HIGH_THRESHOLD:
        anomalies.append(
            (
                "high_error_rate",
                "critical",
                f"Error rate is {error_rate:.1%} of all tool calls "
                f"(threshold {_ERROR_RATE_HIGH_THRESHOLD:.0%}) — "
                "frequent failures suggest a systemic issue",
            )
        )

    # --- 4. Memory query gap ---
    gap = metrics["memory_query_interval"]
    if gap > _MEMORY_GAP_SECONDS:
        minutes = gap / 60
        anomalies.append(
            (
                "memory_query_gap",
                "warning",
                f"No memory query for {minutes:.1f} min "
                f"(threshold {_MEMORY_GAP_SECONDS // 60} min) — "
                "agent may be operating without long-term context",
            )
        )

    return anomalies


_DEFAULT_EMA_ALPHA = 0.3


def compute_ema(values, alpha=_DEFAULT_EMA_ALPHA):
    """Compute Exponential Moving Average. Returns list same length as input."""
    if not values:
        return []
    alpha = max(0.01, min(1.0, alpha))
    ema = [values[0]]
    for v in values[1:]:
        ema.append(alpha * v + (1.0 - alpha) * ema[-1])
    return ema


def detect_trend(values, alpha=_DEFAULT_EMA_ALPHA, threshold=0.2):
    """Detect rising/falling/stable trend via EMA comparison."""
    if len(values) < 2:
        return {"direction": "stable", "magnitude": 0.0, "ema_first": values[0] if values else 0.0, "ema_last": values[0] if values else 0.0}
    ema = compute_ema(values, alpha)
    first, last = ema[0], ema[-1]
    denom = max(abs(first), 1e-9)
    magnitude = (last - first) / denom
    direction = "rising" if magnitude > threshold else ("falling" if magnitude < -threshold else "stable")
    return {"direction": direction, "magnitude": magnitude, "ema_first": first, "ema_last": last}


def anomaly_consensus(signals, quorum=2):
    """Aggregate anomaly signals into a consensus verdict (maker-checker pattern)."""
    if not signals:
        return {"consensus": False, "triggered_count": 0, "total_count": 0, "max_severity": "info", "summary": "No signals provided", "triggered_signals": []}
    severity_rank = {"info": 0, "warning": 1, "critical": 2}
    triggered = [s for s in signals if s.get("triggered", False)]
    triggered_count = len(triggered)
    total_count = len(signals)
    max_sev = "info"
    triggered_names = []
    for s in triggered:
        triggered_names.append(s.get("name", "unknown"))
        sev = s.get("severity", "info")
        if severity_rank.get(sev, 0) > severity_rank.get(max_sev, 0):
            max_sev = sev
    consensus = triggered_count >= quorum
    if consensus:
        summary = f"Consensus reached: {triggered_count}/{total_count} detectors triggered (quorum={quorum}). Signals: {', '.join(triggered_names)}"
    elif triggered_count > 0:
        summary = f"Below quorum: {triggered_count}/{total_count} triggered (need {quorum}). Signals: {', '.join(triggered_names)}"
    else:
        summary = f"All clear: 0/{total_count} detectors triggered"
    return {"consensus": consensus, "triggered_count": triggered_count, "total_count": total_count, "max_severity": max_sev, "summary": summary, "triggered_signals": triggered_names}
