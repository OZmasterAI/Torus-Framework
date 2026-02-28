"""Gate health aggregator — unified dashboard for gate system monitoring.

Combines data from gate_timing, gate_router, and circuit_breaker to
produce a single health report with an overall health score.

Usage:
    from shared.gate_health import get_gate_health_report, format_health_dashboard

    report = get_gate_health_report()
    print(format_health_dashboard())
"""

from shared.gate_timing import (
    get_gate_stats,
    get_slow_gates,
    get_sla_report,
    get_degraded_gates,
    SLA_WARN_MS,
    SLA_DEGRADE_MS,
)
from shared.gate_router import get_routing_stats


def _get_circuit_breaker_data():
    """Safely get circuit breaker status (returns empty dict on failure)."""
    try:
        from shared.circuit_breaker import get_all_gate_states
        return get_all_gate_states()
    except (ImportError, Exception):
        return {}


def get_gate_health_report():
    """Aggregate all gate health data into a single report.

    Returns dict with:
        routing_stats: Gate router stats (calls, skip_rate, avg_routing_ms)
        gate_timings: Per-gate timing summary
        slow_gates: Gates exceeding warn threshold
        degraded_gates: Gates auto-skipped by SLA
        sla_report: Full SLA status per gate
        circuit_breakers: Circuit breaker states
        health_score: 0-100 composite score
        gate_count: Total gates with timing data
    """
    gate_timings = get_gate_stats() or {}
    slow = get_slow_gates()
    degraded = get_degraded_gates()
    sla = get_sla_report()
    routing = get_routing_stats()
    breakers = _get_circuit_breaker_data()

    # Compute health score (0-100)
    total_gates = len(gate_timings) if gate_timings else 1
    degraded_pct = len(degraded) / total_gates if total_gates > 0 else 0
    slow_pct = len(slow) / total_gates if total_gates > 0 else 0

    # Error rate from routing stats
    total_calls = routing.get("calls", 0)
    tier1_blocks = routing.get("tier1_blocks", 0)
    error_rate = tier1_blocks / total_calls if total_calls > 0 else 0

    # Open circuit breakers count
    open_breakers = sum(1 for s in breakers.values() if s.get("state") == "OPEN")
    breaker_penalty = min(open_breakers * 10, 30)

    health_score = max(0, min(100, int(
        100
        - degraded_pct * 40
        - slow_pct * 20
        - error_rate * 40
        - breaker_penalty
    )))

    return {
        "routing_stats": routing,
        "gate_timings": gate_timings,
        "slow_gates": list(slow.keys()),
        "degraded_gates": degraded,
        "sla_report": sla,
        "circuit_breakers": breakers,
        "health_score": health_score,
        "gate_count": len(gate_timings),
    }


def format_health_dashboard():
    """Format a compact ASCII health dashboard.

    Returns multi-line string suitable for display or logging.
    """
    report = get_gate_health_report()
    score = report["health_score"]
    routing = report["routing_stats"]
    timings = report["gate_timings"]

    # Score indicator
    if score >= 90:
        indicator = "HEALTHY"
    elif score >= 70:
        indicator = "DEGRADED"
    elif score >= 50:
        indicator = "WARNING"
    else:
        indicator = "CRITICAL"

    lines = [
        f"Gate Health Dashboard  [{indicator}]  Score: {score}/100",
        "=" * 55,
        "",
        f"Routing: {routing.get('calls', 0)} calls, "
        f"avg {routing.get('avg_routing_ms', 0):.1f}ms, "
        f"skip rate {routing.get('skip_rate', 0):.1%}, "
        f"T1 blocks {routing.get('tier1_blocks', 0)}",
        "",
    ]

    # Gate timing summary (top 10 by avg_ms)
    if timings:
        lines.append("Gate Performance (top 10 by avg_ms):")
        sorted_gates = sorted(
            timings.items(),
            key=lambda kv: kv[1].get("avg_ms", 0),
            reverse=True,
        )[:10]
        for name, stats in sorted_gates:
            avg = stats.get("avg_ms", 0)
            p95 = stats.get("p95_ms", 0)
            count = stats.get("count", 0)
            flag = ""
            if avg > SLA_DEGRADE_MS:
                flag = " [DEGRADE]"
            elif avg > SLA_WARN_MS:
                flag = " [SLOW]"
            short_name = name.split(".")[-1] if "." in name else name
            lines.append(
                f"  {short_name:<35} avg={avg:6.1f}ms  "
                f"p95={p95:6.1f}ms  n={count}{flag}"
            )
        lines.append("")

    # Degraded gates
    degraded = report["degraded_gates"]
    if degraded:
        lines.append(f"Auto-skipped gates ({len(degraded)}):")
        for g in degraded:
            lines.append(f"  - {g}")
        lines.append("")

    # Circuit breakers
    breakers = report["circuit_breakers"]
    open_breakers = {k: v for k, v in breakers.items() if v.get("state") != "CLOSED"}
    if open_breakers:
        lines.append(f"Circuit breakers ({len(open_breakers)} non-closed):")
        for name, state in open_breakers.items():
            lines.append(f"  - {name}: {state.get('state', '?')}")
        lines.append("")

    lines.append("=" * 55)
    return "\n".join(lines)
