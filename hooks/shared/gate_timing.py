"""Gate execution timing analytics.

Tracks gate execution times per tool type, identifies slow gates,
and provides timing reports for performance optimization.
"""
import json
import os
import time

TIMING_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".gate_timings.json")

# Threshold for classifying a gate execution as "slow" by default
DEFAULT_SLOW_THRESHOLD_MS = 50


def _load_timings():
    """Load timing data from the JSON file. Returns empty dict on missing/corrupt file."""
    try:
        with open(TIMING_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_timings(data):
    """Persist timing data to the JSON file atomically."""
    tmp_path = TIMING_FILE + ".tmp"
    try:
        with open(tmp_path, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, TIMING_FILE)
    except OSError:
        pass  # Non-fatal: timing loss is acceptable


# ---------------------------------------------------------------------------
# In-process timing cache.  Each enforcer invocation is a fresh process,
# so this cache lives for exactly one hook call.  Eliminates N load/save
# cycles (one per gate) down to 1 load + 1 save per invocation.
# ---------------------------------------------------------------------------
_timing_cache = None
_timing_dirty = False


def _reset_cache():
    """Invalidate the in-process cache.  Used by tests after changing TIMING_FILE."""
    global _timing_cache, _timing_dirty
    _timing_cache = None
    _timing_dirty = False


def _ensure_timings():
    """Return the cached timing data, loading from disk on first access."""
    global _timing_cache
    if _timing_cache is None:
        _timing_cache = _load_timings()
    return _timing_cache


def record_timing(gate_name, tool_name, elapsed_ms, blocked=False):
    """Record a gate execution timing.

    Mutates the in-process cache only.  Call flush_timings() to persist.

    Args:
        gate_name:  Short gate identifier, e.g. "gate_01_read_before_edit"
        tool_name:  The tool being checked, e.g. "Edit"
        elapsed_ms: Execution time in milliseconds (float)
        blocked:    Whether this execution resulted in a block
    """
    global _timing_dirty
    data = _ensure_timings()

    entry = data.setdefault(gate_name, {
        "count": 0,
        "total_ms": 0.0,
        "min_ms": float("inf"),
        "max_ms": 0.0,
        "slow_count": 0,
        "block_count": 0,
        "samples": [],          # Rolling last-N samples for p95
        "by_tool": {},
    })

    entry["count"] += 1
    entry["total_ms"] += elapsed_ms
    entry["min_ms"] = min(entry["min_ms"], elapsed_ms)
    entry["max_ms"] = max(entry["max_ms"], elapsed_ms)

    if elapsed_ms > DEFAULT_SLOW_THRESHOLD_MS:
        entry["slow_count"] += 1

    if blocked:
        entry["block_count"] += 1

    # Keep a rolling window of the last 200 samples for percentile calculation
    samples = entry.setdefault("samples", [])
    samples.append(elapsed_ms)
    if len(samples) > 200:
        entry["samples"] = samples[-200:]

    # Per-tool breakdown
    by_tool = entry.setdefault("by_tool", {})
    tool_entry = by_tool.setdefault(tool_name, {"count": 0, "total_ms": 0.0})
    tool_entry["count"] += 1
    tool_entry["total_ms"] += elapsed_ms

    _timing_dirty = True


def flush_timings():
    """Persist the cached timing data to disk if any records were added.

    Called once at the end of the enforcer gate loop (or before early exit).
    No-op if no record_timing() calls were made this invocation.
    """
    global _timing_dirty
    if _timing_dirty and _timing_cache is not None:
        _save_timings(_timing_cache)
        _timing_dirty = False


def _percentile(sorted_values, pct):
    """Compute pct-th percentile from a pre-sorted list. Returns 0.0 for empty list."""
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * pct / 100.0
    lo = int(k)
    hi = lo + 1
    if hi >= len(sorted_values):
        return sorted_values[-1]
    frac = k - lo
    return sorted_values[lo] + frac * (sorted_values[hi] - sorted_values[lo])


def get_gate_stats(gate_name=None):
    """Get timing statistics for a gate (or all gates).

    Args:
        gate_name: If provided, return stats for that gate only.
                   If None, return stats for all gates.

    Returns:
        dict mapping gate_name ->
            {avg_ms, p95_ms, max_ms, min_ms, count, slow_count, block_count, by_tool}
        For a single gate, returns that gate's stats dict directly (or None if not found).
    """
    data = _ensure_timings()

    def _compute(gate_key, entry):
        count = entry.get("count", 0)
        avg_ms = entry["total_ms"] / count if count else 0.0
        samples_sorted = sorted(entry.get("samples", []))
        p95_ms = _percentile(samples_sorted, 95)
        return {
            "avg_ms": round(avg_ms, 3),
            "p95_ms": round(p95_ms, 3),
            "max_ms": round(entry.get("max_ms", 0.0), 3),
            "min_ms": round(entry.get("min_ms", 0.0), 3),
            "count": count,
            "slow_count": entry.get("slow_count", 0),
            "block_count": entry.get("block_count", 0),
            "by_tool": entry.get("by_tool", {}),
        }

    if gate_name is not None:
        entry = data.get(gate_name)
        if entry is None:
            return None
        return _compute(gate_name, entry)

    return {k: _compute(k, v) for k, v in data.items()}


def get_slow_gates(threshold_ms=DEFAULT_SLOW_THRESHOLD_MS):
    """Return gates that frequently exceed threshold.

    A gate is considered "frequently slow" if its slow_count is > 0
    or its average execution time exceeds the threshold.

    Args:
        threshold_ms: Millisecond threshold. Gates whose avg_ms or p95_ms
                      exceed this are included.

    Returns:
        dict mapping gate_name -> stats dict (same shape as get_gate_stats)
        sorted by avg_ms descending.
    """
    all_stats = get_gate_stats()
    slow = {
        name: stats
        for name, stats in all_stats.items()
        if stats["avg_ms"] > threshold_ms or stats["p95_ms"] > threshold_ms
    }
    # Sort by avg_ms descending for easy identification of worst offenders
    return dict(sorted(slow.items(), key=lambda kv: kv[1]["avg_ms"], reverse=True))


def get_timing_report():
    """Generate a formatted timing report string.

    Returns:
        Multi-line string suitable for logging or display, covering all
        recorded gates ordered by avg_ms descending.
    """
    all_stats = get_gate_stats()
    if not all_stats:
        return "Gate Timing Report: no data recorded yet."

    lines = ["Gate Timing Report", "=" * 60]
    sorted_gates = sorted(all_stats.items(), key=lambda kv: kv[1]["avg_ms"], reverse=True)
    for name, stats in sorted_gates:
        slow_flag = " [SLOW]" if stats["avg_ms"] > DEFAULT_SLOW_THRESHOLD_MS else ""
        lines.append(
            f"{name}{slow_flag}\n"
            f"  count={stats['count']}  avg={stats['avg_ms']:.1f}ms"
            f"  p95={stats['p95_ms']:.1f}ms  max={stats['max_ms']:.1f}ms"
            f"  slow_hits={stats['slow_count']}  blocks={stats['block_count']}"
        )
    lines.append("=" * 60)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Adaptive Gate SLA — per-gate timeout enforcement
# ---------------------------------------------------------------------------

# SLA tiers: gates exceeding these thresholds get flagged or auto-skipped
SLA_WARN_MS = 50       # Flag as slow (informational)
SLA_DEGRADE_MS = 200   # Auto-skip with warning (non-Tier-1 only)
SLA_MIN_SAMPLES = 10   # Need at least this many samples before enforcing SLA

# Tier 1 safety gates are NEVER skipped by SLA (fail-closed)
_TIER1_GATES = {
    "gate_01_read_before_edit",
    "gate_02_no_destroy",
    "gate_03_test_before_deploy",
}


def check_gate_sla(gate_name):
    """Check if a gate meets its performance SLA.

    Returns a dict with SLA status:
        status: "ok" | "warn" | "degrade" | "unknown"
        skip: bool — True if gate should be auto-skipped (degrade + non-Tier-1)
        reason: str — human-readable explanation
        avg_ms: float — current average latency
        p95_ms: float — current p95 latency
    """
    stats = get_gate_stats(gate_name)
    if stats is None or stats["count"] < SLA_MIN_SAMPLES:
        return {
            "status": "unknown",
            "skip": False,
            "reason": f"Insufficient data ({stats['count'] if stats else 0}/{SLA_MIN_SAMPLES} samples)",
            "avg_ms": stats["avg_ms"] if stats else 0.0,
            "p95_ms": stats["p95_ms"] if stats else 0.0,
        }

    # Strip prefix for Tier 1 check
    short_name = gate_name.split(".")[-1] if "." in gate_name else gate_name
    is_tier1 = short_name in _TIER1_GATES

    avg = stats["avg_ms"]
    p95 = stats["p95_ms"]

    if p95 > SLA_DEGRADE_MS or avg > SLA_DEGRADE_MS:
        return {
            "status": "degrade",
            "skip": not is_tier1,  # Never skip Tier 1
            "reason": f"SLA breach: avg={avg:.1f}ms p95={p95:.1f}ms (threshold={SLA_DEGRADE_MS}ms)"
                      + (" [Tier 1: cannot skip]" if is_tier1 else " [auto-skipping]"),
            "avg_ms": avg,
            "p95_ms": p95,
        }

    if p95 > SLA_WARN_MS or avg > SLA_WARN_MS:
        return {
            "status": "warn",
            "skip": False,
            "reason": f"Slow: avg={avg:.1f}ms p95={p95:.1f}ms (warn threshold={SLA_WARN_MS}ms)",
            "avg_ms": avg,
            "p95_ms": p95,
        }

    return {
        "status": "ok",
        "skip": False,
        "reason": f"Healthy: avg={avg:.1f}ms p95={p95:.1f}ms",
        "avg_ms": avg,
        "p95_ms": p95,
    }


def get_sla_report():
    """Get SLA status for all tracked gates.

    Returns dict mapping gate_name -> SLA status dict (from check_gate_sla).
    Gates are sorted by avg_ms descending (slowest first).
    """
    all_stats = get_gate_stats()
    if not all_stats:
        return {}

    report = {}
    for gate_name in all_stats:
        report[gate_name] = check_gate_sla(gate_name)

    return dict(sorted(report.items(), key=lambda kv: kv[1]["avg_ms"], reverse=True))


def get_degraded_gates():
    """Return gate names that should be auto-skipped due to SLA breach.

    Only non-Tier-1 gates with sufficient samples and avg/p95 > SLA_DEGRADE_MS.
    """
    report = get_sla_report()
    return [name for name, sla in report.items() if sla["skip"]]
