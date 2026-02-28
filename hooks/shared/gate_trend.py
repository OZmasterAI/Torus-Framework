"""Gate performance trend tracker.

Tracks gate latency snapshots over time and computes per-gate trends
(rising, falling, stable). Used by analytics MCP to surface performance
regressions before they become SLA violations.

Usage:
    from shared.gate_trend import snapshot_gate_stats, get_trend_report

    # Called periodically (e.g., every boot or every N minutes)
    snapshot_gate_stats()

    # Get per-gate trend analysis
    report = get_trend_report()
"""

import json
import os
import time

# Snapshot storage (ramdisk preferred, disk fallback)
_RAMDISK_PATH = "/dev/shm/claude-hooks/gate_trend.json"
_DISK_FALLBACK = os.path.join(
    os.path.expanduser("~"), ".claude", "hooks", ".gate_trend.json"
)

# Configuration
MAX_SNAPSHOTS = 50      # Keep last 50 snapshots
SNAPSHOT_INTERVAL = 300  # Minimum seconds between snapshots (5 min)
TREND_THRESHOLD = 0.2   # 20% change = meaningful trend


def _trend_path():
    """Return the best available persistence path."""
    if os.path.isdir(os.path.dirname(_RAMDISK_PATH)):
        return _RAMDISK_PATH
    return _DISK_FALLBACK


def _load_snapshots():
    """Load snapshot history from disk. Returns empty list on error."""
    path = _trend_path()
    try:
        if os.path.isfile(path):
            with open(path, "r") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
    except (OSError, json.JSONDecodeError):
        pass
    return []


def _save_snapshots(snapshots):
    """Atomically write snapshots to disk."""
    path = _trend_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(snapshots, f)
        os.replace(tmp, path)
    except OSError:
        pass


def snapshot_gate_stats():
    """Take a snapshot of current gate timing stats.

    Reads from gate_timing module and appends a timestamped snapshot.
    Rate-limited to SNAPSHOT_INTERVAL seconds between snapshots.

    Returns:
        True if snapshot was taken, False if skipped (too recent).
    """
    snapshots = _load_snapshots()

    # Rate limit
    if snapshots:
        last_ts = snapshots[-1].get("timestamp", 0)
        if time.time() - last_ts < SNAPSHOT_INTERVAL:
            return False

    try:
        from shared.gate_timing import get_all_gate_stats
        stats = get_all_gate_stats()
    except ImportError:
        return False

    if not stats:
        return False

    # Build snapshot: gate_name -> avg_ms
    snapshot = {
        "timestamp": time.time(),
        "gates": {},
    }
    for gate_name, gate_stats in stats.items():
        if isinstance(gate_stats, dict) and gate_stats.get("count", 0) > 0:
            snapshot["gates"][gate_name] = {
                "avg_ms": gate_stats.get("avg_ms", 0),
                "p95_ms": gate_stats.get("p95_ms", 0),
                "count": gate_stats.get("count", 0),
            }

    snapshots.append(snapshot)

    # Trim to max
    if len(snapshots) > MAX_SNAPSHOTS:
        snapshots = snapshots[-MAX_SNAPSHOTS:]

    _save_snapshots(snapshots)
    return True


def compute_gate_trend(gate_name, snapshots=None):
    """Compute the performance trend for a specific gate.

    Args:
        gate_name: Gate to analyze.
        snapshots: Optional pre-loaded snapshots. If None, loads from disk.

    Returns:
        Dict with: direction (rising/falling/stable), magnitude,
        first_avg_ms, last_avg_ms, data_points.
    """
    if snapshots is None:
        snapshots = _load_snapshots()

    # Extract avg_ms values for this gate across snapshots
    values = []
    for snap in snapshots:
        gate_data = snap.get("gates", {}).get(gate_name)
        if gate_data and isinstance(gate_data, dict):
            values.append(gate_data.get("avg_ms", 0))

    if len(values) < 2:
        return {
            "direction": "stable",
            "magnitude": 0.0,
            "first_avg_ms": values[0] if values else 0,
            "last_avg_ms": values[-1] if values else 0,
            "data_points": len(values),
        }

    first = values[0]
    last = values[-1]
    denom = max(abs(first), 0.001)
    magnitude = (last - first) / denom

    if magnitude > TREND_THRESHOLD:
        direction = "rising"
    elif magnitude < -TREND_THRESHOLD:
        direction = "falling"
    else:
        direction = "stable"

    return {
        "direction": direction,
        "magnitude": round(magnitude, 3),
        "first_avg_ms": round(first, 2),
        "last_avg_ms": round(last, 2),
        "data_points": len(values),
    }


def get_trend_report():
    """Generate a trend report for all tracked gates.

    Returns:
        Dict with: snapshot_count, gates (dict of gate_name -> trend),
        rising_gates (list), falling_gates (list).
    """
    snapshots = _load_snapshots()

    # Collect all gate names across snapshots
    all_gates = set()
    for snap in snapshots:
        all_gates.update(snap.get("gates", {}).keys())

    gates = {}
    rising = []
    falling = []

    for gate_name in sorted(all_gates):
        trend = compute_gate_trend(gate_name, snapshots)
        gates[gate_name] = trend
        if trend["direction"] == "rising":
            rising.append(gate_name)
        elif trend["direction"] == "falling":
            falling.append(gate_name)

    return {
        "snapshot_count": len(snapshots),
        "gates": gates,
        "rising_gates": rising,
        "falling_gates": falling,
        "total_gates": len(all_gates),
    }


def format_trend_report():
    """Format trend report as readable text."""
    report = get_trend_report()
    lines = [
        "Gate Performance Trends",
        "=" * 55,
        f"Snapshots: {report['snapshot_count']}  |  Gates: {report['total_gates']}",
        "",
    ]

    if report["rising_gates"]:
        lines.append("RISING (getting slower):")
        for g in report["rising_gates"]:
            t = report["gates"][g]
            lines.append(
                f"  {g:<40} {t['first_avg_ms']:.1f}ms -> {t['last_avg_ms']:.1f}ms "
                f"({t['magnitude']:+.0%})"
            )
        lines.append("")

    if report["falling_gates"]:
        lines.append("FALLING (getting faster):")
        for g in report["falling_gates"]:
            t = report["gates"][g]
            lines.append(
                f"  {g:<40} {t['first_avg_ms']:.1f}ms -> {t['last_avg_ms']:.1f}ms "
                f"({t['magnitude']:+.0%})"
            )
        lines.append("")

    stable = [g for g, t in report["gates"].items() if t["direction"] == "stable"]
    if stable:
        lines.append(f"STABLE: {len(stable)} gate(s)")

    lines.append("=" * 55)
    return "\n".join(lines)
