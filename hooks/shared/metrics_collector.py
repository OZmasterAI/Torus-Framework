"""Unified metrics collector for the Torus self-healing framework.

Collects counters, gauges, and histograms from gates, hooks, memory, and
sessions into a single in-process store, flushed to ramdisk for dashboards.

Persistence path: /dev/shm/claude-hooks/metrics.json (ramdisk, fast writes).
Fallback path: ~/.claude/hooks/.metrics_cache.json (disk, if /dev/shm unavailable).

Design constraints:
- Lock-free: each hook invocation is a separate process; no thread contention.
- Fail-open: all public functions swallow exceptions; never breaks gate enforcement.
- time.monotonic() for all timing measurements (wall-clock in metadata only).
- Aggregation windows: 1-minute, 5-minute, and session-level rollups.

Built-in metric names:
  gate.fires         counter  per-gate fire count
  gate.blocks        counter  per-gate block count
  gate.latency_ms    histogram per-gate execution time
  hook.duration_ms   histogram per hook-event execution time
  memory.total       gauge    total memories in store
  memory.queries     counter  memory query count
  session.tool_calls counter  total tool calls this session
  test.pass_rate     gauge    fraction of tests passing (0.0-1.0)
"""

import json
import os
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

# ── Path constants ─────────────────────────────────────────────────────────────

METRICS_RAMDISK_DIR = "/dev/shm/claude-hooks"
METRICS_RAMDISK_PATH = os.path.join(METRICS_RAMDISK_DIR, "metrics.json")
METRICS_DISK_FALLBACK = os.path.join(
    os.path.expanduser("~"), ".claude", "hooks", ".metrics_cache.json"
)

# ── Metric type constants ──────────────────────────────────────────────────────

TYPE_COUNTER = "counter"
TYPE_GAUGE = "gauge"
TYPE_HISTOGRAM = "histogram"

# Built-in metric definitions: {name: (type, description)}
BUILTIN_METRICS: Dict[str, tuple] = {
    "gate.fires":         (TYPE_COUNTER,   "Total gate fire events, per gate"),
    "gate.blocks":        (TYPE_COUNTER,   "Total gate block events, per gate"),
    "gate.latency_ms":    (TYPE_HISTOGRAM, "Gate execution latency in milliseconds"),
    "hook.duration_ms":   (TYPE_HISTOGRAM, "Hook event handling duration in milliseconds"),
    "memory.total":       (TYPE_GAUGE,     "Total memories stored in knowledge base"),
    "memory.queries":     (TYPE_COUNTER,   "Total memory query operations"),
    "session.tool_calls": (TYPE_COUNTER,   "Total tool calls in the current session"),
    "test.pass_rate":     (TYPE_GAUGE,     "Fraction of tests passing (0.0 to 1.0)"),
}

# ── Label key encoding ────────────────────────────────────────────────────────

def _label_key(labels: Optional[Dict[str, str]]) -> str:
    """Encode a labels dict into a stable string key for dict indexing.

    Returns "" for no labels. Labels are sorted for canonical ordering.
    """
    if not labels:
        return ""
    try:
        return ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
    except Exception:
        return ""


# ── In-process store (single-process, no locking needed) ──────────────────────

class _MetricsStore:
    """In-process metrics store.

    One instance per process (hook invocation). Loaded from disk on first
    access, flushed back on explicit flush() or at module unload.
    """

    def __init__(self):
        self._data: Dict[str, Any] = {}   # Raw metric storage
        self._loaded = False
        self._session_start = time.monotonic()
        self._wall_start = time.time()
        # Timed histogram observations for rollup: {metric: {label_key: [(ts, value)]}}
        self._timed_obs: Dict[str, Dict[str, List[tuple]]] = defaultdict(
            lambda: defaultdict(list)
        )

    def _load(self):
        """Load persisted metrics from ramdisk or disk fallback. Called once."""
        if self._loaded:
            return
        self._loaded = True
        path = _metrics_path()
        if path and os.path.exists(path):
            try:
                with open(path) as f:
                    stored = json.load(f)
                self._data = stored.get("metrics", {})
            except (OSError, json.JSONDecodeError, ValueError):
                self._data = {}
        else:
            self._data = {}

    # ── Counter ───────────────────────────────────────────────────────────────

    def inc(self, metric: str, value: int = 1, labels: Optional[Dict] = None) -> None:
        """Increment a counter metric."""
        self._load()
        lk = _label_key(labels)
        key = f"{metric}|{lk}"
        entry = self._data.setdefault(key, {
            "metric": metric,
            "type": TYPE_COUNTER,
            "labels": labels or {},
            "value": 0,
            "updated_at": time.time(),
        })
        entry["value"] = entry.get("value", 0) + value
        entry["updated_at"] = time.time()

    # ── Gauge ─────────────────────────────────────────────────────────────────

    def set_gauge(self, metric: str, value: float, labels: Optional[Dict] = None) -> None:
        """Set a gauge metric to an exact value."""
        self._load()
        lk = _label_key(labels)
        key = f"{metric}|{lk}"
        self._data[key] = {
            "metric": metric,
            "type": TYPE_GAUGE,
            "labels": labels or {},
            "value": value,
            "updated_at": time.time(),
        }

    # ── Histogram ─────────────────────────────────────────────────────────────

    def observe(self, metric: str, value: float, labels: Optional[Dict] = None) -> None:
        """Record a histogram observation."""
        self._load()
        lk = _label_key(labels)
        now = time.time()

        # Store timed observation for rollup
        self._timed_obs[metric][lk].append((now, value))

        # Update aggregate stats in _data
        key = f"{metric}|{lk}"
        entry = self._data.get(key)
        if entry is None:
            entry = {
                "metric": metric,
                "type": TYPE_HISTOGRAM,
                "labels": labels or {},
                "count": 0,
                "sum": 0.0,
                "min": value,
                "max": value,
                "updated_at": now,
            }
            self._data[key] = entry
        else:
            entry["min"] = min(entry.get("min", value), value)
            entry["max"] = max(entry.get("max", value), value)

        entry["count"] = entry.get("count", 0) + 1
        entry["sum"] = entry.get("sum", 0.0) + value
        entry["updated_at"] = now

    # ── Query ─────────────────────────────────────────────────────────────────

    def get_metric(self, metric: str, labels: Optional[Dict] = None) -> dict:
        """Return the current state of a single metric (with computed avg).

        Returns {} if the metric does not exist.
        """
        self._load()
        lk = _label_key(labels)
        key = f"{metric}|{lk}"
        entry = self._data.get(key)
        if entry is None:
            return {}
        result = dict(entry)
        # Compute avg for histograms
        if result.get("type") == TYPE_HISTOGRAM:
            count = result.get("count", 0)
            result["avg"] = result["sum"] / count if count > 0 else 0.0
        return result

    def get_all_metrics(self) -> dict:
        """Return all metrics as a nested dict keyed by metric name.

        Structure:
          {
            "gate.fires": {
              "": {counter entry, no labels},
              "gate=gate_01": {counter entry},
              ...
            },
            ...
          }
        """
        self._load()
        result: Dict[str, Dict[str, dict]] = {}
        for raw_key, entry in self._data.items():
            metric = entry.get("metric", raw_key.split("|")[0])
            lk = raw_key.split("|", 1)[1] if "|" in raw_key else ""
            if metric not in result:
                result[metric] = {}
            item = dict(entry)
            if item.get("type") == TYPE_HISTOGRAM:
                count = item.get("count", 0)
                item["avg"] = item["sum"] / count if count > 0 else 0.0
            result[metric][lk] = item
        return result

    # ── Rollup ────────────────────────────────────────────────────────────────

    def rollup(self, window_seconds: int = 60) -> dict:
        """Compute aggregate statistics for histogram metrics within a time window.

        For counters and gauges, returns their current values.
        For histograms, computes count/sum/min/max/avg over the window.

        Args:
            window_seconds: Lookback window in seconds (default 60 = 1-minute).

        Returns:
            dict keyed by "metric|label_key" with windowed aggregates.
        """
        self._load()
        cutoff = time.time() - window_seconds
        result = {}

        # Histograms: compute from timed observations within the window
        for metric, label_map in self._timed_obs.items():
            for lk, obs_list in label_map.items():
                windowed = [v for ts, v in obs_list if ts >= cutoff]
                if not windowed:
                    continue
                agg = {
                    "metric": metric,
                    "type": TYPE_HISTOGRAM,
                    "window_seconds": window_seconds,
                    "count": len(windowed),
                    "sum": sum(windowed),
                    "min": min(windowed),
                    "max": max(windowed),
                    "avg": sum(windowed) / len(windowed),
                }
                result[f"{metric}|{lk}"] = agg

        # Counters and gauges: include current value from _data
        for raw_key, entry in self._data.items():
            if entry.get("type") in (TYPE_COUNTER, TYPE_GAUGE):
                result[raw_key] = {
                    "metric": entry.get("metric", raw_key),
                    "type": entry["type"],
                    "window_seconds": window_seconds,
                    "value": entry.get("value", 0),
                    "labels": entry.get("labels", {}),
                }

        return result

    # ── Persistence ───────────────────────────────────────────────────────────

    def flush(self) -> bool:
        """Persist all in-memory metrics to ramdisk (or fallback disk path).

        Returns True on success, False on failure.
        """
        self._load()
        path = _metrics_path()
        if path is None:
            return False
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            payload = {
                "flushed_at": time.time(),
                "session_start_wall": self._wall_start,
                "metrics": self._data,
            }
            tmp = path + f".tmp.{os.getpid()}"
            with open(tmp, "w") as f:
                json.dump(payload, f, separators=(",", ":"))
            os.replace(tmp, path)
            return True
        except (OSError, TypeError, ValueError):
            return False


# ── Module-level singleton ────────────────────────────────────────────────────

_store = _MetricsStore()


# ── Path helper ───────────────────────────────────────────────────────────────

def _metrics_path() -> Optional[str]:
    """Return the best available metrics persistence path.

    Prefers /dev/shm/claude-hooks/metrics.json (ramdisk).
    Falls back to ~/.claude/hooks/.metrics_cache.json (disk).
    """
    # Try ramdisk: directory already exists or we can create it
    try:
        if os.path.isdir(METRICS_RAMDISK_DIR):
            return METRICS_RAMDISK_PATH
        os.makedirs(METRICS_RAMDISK_DIR, exist_ok=True)
        return METRICS_RAMDISK_PATH
    except (OSError, PermissionError):
        pass
    # Fallback to disk
    return METRICS_DISK_FALLBACK


# ── Public API ────────────────────────────────────────────────────────────────

def inc(metric: str, value: int = 1, labels: Optional[Dict] = None) -> None:
    """Increment a counter metric.

    Args:
        metric: Metric name (e.g., "gate.fires").
        value:  Amount to increment by (default 1).
        labels: Optional dict of label key/value pairs, e.g. {"gate": "gate_01"}.
    """
    try:
        _store.inc(metric, value, labels)
    except Exception:
        pass


def set_gauge(metric: str, value: float, labels: Optional[Dict] = None) -> None:
    """Set a gauge metric to a point-in-time value.

    Args:
        metric: Metric name (e.g., "memory.total").
        value:  Current value.
        labels: Optional label dict.
    """
    try:
        _store.set_gauge(metric, value, labels)
    except Exception:
        pass


def observe(metric: str, value: float, labels: Optional[Dict] = None) -> None:
    """Record a histogram observation (e.g., a latency sample).

    Args:
        metric: Metric name (e.g., "gate.latency_ms").
        value:  Observed value.
        labels: Optional label dict.
    """
    try:
        _store.observe(metric, value, labels)
    except Exception:
        pass


def get_metric(metric: str, labels: Optional[Dict] = None) -> dict:
    """Return the current state of a single metric.

    Args:
        metric: Metric name.
        labels: Optional label dict (must match exactly).

    Returns:
        dict with keys depending on type:
          counter:   {metric, type, labels, value, updated_at}
          gauge:     {metric, type, labels, value, updated_at}
          histogram: {metric, type, labels, count, sum, min, max, avg, updated_at}
        Returns {} if the metric does not exist.
    """
    try:
        return _store.get_metric(metric, labels)
    except Exception:
        return {}


def get_all_metrics() -> dict:
    """Return all metrics as a nested dict.

    Structure:
        {
            "<metric_name>": {
                "<label_key>": {metric entry},
                ...
            }
        }

    Returns {} on error.
    """
    try:
        return _store.get_all_metrics()
    except Exception:
        return {}


def flush() -> bool:
    """Persist all in-memory metrics to ramdisk or fallback disk path.

    Safe to call frequently — uses an atomic tmp-then-replace write.
    Returns True on success, False if persistence failed.
    """
    try:
        return _store.flush()
    except Exception:
        return False


def rollup(window_seconds: int = 60) -> dict:
    """Compute aggregate statistics for a time window.

    Histograms are computed from in-process observations within the window.
    Counters and gauges return their current values.

    Args:
        window_seconds: Lookback window in seconds.
                        60   = 1-minute rollup
                        300  = 5-minute rollup
                        86400 = session-level (24h)

    Returns:
        dict keyed by "metric|label_key" with aggregate data.
        Returns {} on error.
    """
    try:
        return _store.rollup(window_seconds)
    except Exception:
        return {}


# ── Convenience: timing context manager ───────────────────────────────────────

class timed:
    """Context manager that records elapsed time as a histogram observation.

    Uses time.monotonic() for accuracy (immune to wall-clock adjustments).

    Usage:
        with timed("gate.latency_ms", labels={"gate": "gate_01"}):
            result = gate.check(...)
    """

    def __init__(self, metric: str, labels: Optional[Dict] = None):
        self.metric = metric
        self.labels = labels
        self._start: float = 0.0

    def __enter__(self):
        self._start = time.monotonic()
        return self

    def __exit__(self, *_):
        elapsed_ms = (time.monotonic() - self._start) * 1000.0
        observe(self.metric, elapsed_ms, self.labels)


# ── Convenience: built-in metric helpers ──────────────────────────────────────

def record_gate_fire(gate_name: str) -> None:
    """Record a gate.fires increment for the given gate."""
    inc("gate.fires", labels={"gate": gate_name})


def record_gate_block(gate_name: str) -> None:
    """Record a gate.blocks increment for the given gate."""
    inc("gate.blocks", labels={"gate": gate_name})


def record_gate_latency(gate_name: str, latency_ms: float) -> None:
    """Record a gate.latency_ms histogram observation."""
    observe("gate.latency_ms", latency_ms, labels={"gate": gate_name})


def record_hook_duration(event_type: str, duration_ms: float) -> None:
    """Record a hook.duration_ms histogram observation."""
    observe("hook.duration_ms", duration_ms, labels={"event": event_type})


def record_memory_query() -> None:
    """Increment the memory.queries counter."""
    inc("memory.queries")


def set_memory_total(count: int) -> None:
    """Set the memory.total gauge."""
    set_gauge("memory.total", float(count))


def record_tool_call() -> None:
    """Increment the session.tool_calls counter."""
    inc("session.tool_calls")


def set_test_pass_rate(rate: float) -> None:
    """Set the test.pass_rate gauge (clamped to 0.0-1.0)."""
    set_gauge("test.pass_rate", max(0.0, min(1.0, rate)))


# ── Export for dashboard consumption ─────────────────────────────────────────

def export_json() -> str:
    """Export all metrics as a JSON string for dashboard consumption.

    Includes:
    - All current metrics (counters, gauges, histograms with aggregates)
    - 1-minute rollup
    - 5-minute rollup
    - Session-level rollup (24-hour window covers any session)

    Returns a compact JSON string, or '{}' on error.
    """
    try:
        payload = {
            "exported_at": time.time(),
            "metrics": get_all_metrics(),
            "rollup_1m": rollup(60),
            "rollup_5m": rollup(300),
            "rollup_session": rollup(86400),
        }
        return json.dumps(payload, separators=(",", ":"))
    except Exception:
        return "{}"


# ── Module smoke test ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    # Reset persisted state so each run starts clean
    for _p in (METRICS_RAMDISK_PATH, METRICS_DISK_FALLBACK):
        try:
            if os.path.exists(_p):
                os.remove(_p)
        except OSError:
            pass

    print("metrics_collector smoke test")
    errors = []

    def check(name, condition, detail=""):
        if condition:
            print(f"  PASS  {name}")
        else:
            print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))
            errors.append(name)

    # Counter
    inc("gate.fires", labels={"gate": "gate_01"})
    inc("gate.fires", labels={"gate": "gate_01"})
    inc("gate.blocks", labels={"gate": "gate_01"})

    fires = get_metric("gate.fires", labels={"gate": "gate_01"})
    check("counter inc x2", fires.get("value") == 2, f"got {fires.get('value')}")
    check("counter type", fires.get("type") == TYPE_COUNTER)

    blocks = get_metric("gate.blocks", labels={"gate": "gate_01"})
    check("counter inc x1", blocks.get("value") == 1, f"got {blocks.get('value')}")

    # Gauge
    set_gauge("memory.total", 865.0)
    set_gauge("test.pass_rate", 0.97)
    mem = get_metric("memory.total")
    check("gauge set", mem.get("value") == 865.0, f"got {mem.get('value')}")
    check("gauge type", mem.get("type") == TYPE_GAUGE)

    # Histogram
    for ms in [2.1, 3.5, 1.8, 4.2, 2.9]:
        observe("gate.latency_ms", ms, labels={"gate": "gate_01"})

    lat = get_metric("gate.latency_ms", labels={"gate": "gate_01"})
    check("histogram count", lat.get("count") == 5, f"got {lat.get('count')}")
    check("histogram min", abs(lat.get("min", 0) - 1.8) < 0.001)
    check("histogram max", abs(lat.get("max", 0) - 4.2) < 0.001)
    check("histogram avg > 0", lat.get("avg", 0) > 0)
    check("histogram type", lat.get("type") == TYPE_HISTOGRAM)

    # timed context manager
    with timed("gate.latency_ms", labels={"gate": "gate_02"}):
        time.sleep(0.001)
    lat2 = get_metric("gate.latency_ms", labels={"gate": "gate_02"})
    check("timed ctx manager", lat2.get("count") == 1, f"got {lat2.get('count')}")

    # Convenience helpers
    record_gate_fire("gate_03")
    g3 = get_metric("gate.fires", labels={"gate": "gate_03"})
    check("record_gate_fire", g3.get("value") == 1)

    record_memory_query()
    mq = get_metric("memory.queries")
    check("record_memory_query", mq.get("value") == 1)

    record_tool_call()
    record_tool_call()
    tc = get_metric("session.tool_calls")
    check("record_tool_call x2", tc.get("value") == 2)

    set_test_pass_rate(1.5)  # Should clamp to 1.0
    tpr = get_metric("test.pass_rate")
    check("test.pass_rate clamped", tpr.get("value") == 1.0, f"got {tpr.get('value')}")

    # Rollups
    r1 = rollup(60)
    check("rollup(60) non-empty", len(r1) > 0, f"got {len(r1)}")
    r5 = rollup(300)
    check("rollup(300) non-empty", len(r5) > 0)

    # get_all_metrics
    all_m = get_all_metrics()
    check("get_all_metrics has gate.fires", "gate.fires" in all_m)
    check("get_all_metrics has memory.total", "memory.total" in all_m)

    # Flush
    ok = flush()
    check("flush returns True", ok, f"flush returned {ok}")

    # export_json
    exported = export_json()
    parsed = json.loads(exported)
    check("export_json has metrics", "metrics" in parsed)
    check("export_json has rollup_1m", "rollup_1m" in parsed)
    check("export_json has rollup_5m", "rollup_5m" in parsed)
    check("export_json has rollup_session", "rollup_session" in parsed)

    # Missing metric returns {}
    missing = get_metric("nonexistent.metric")
    check("missing metric returns {}", missing == {})

    print()
    if errors:
        print(f"FAILED: {len(errors)} test(s) failed: {errors}")
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")
        sys.exit(0)
