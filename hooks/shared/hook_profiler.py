"""Hook profiler — nanosecond-precision gate latency instrumentation.

Wraps any gate check() function with timing, appends per-call records to
/tmp/gate_latency.jsonl (newline-delimited JSON), and provides analysis
helpers (p50/p95/p99 per gate) and a formatted ASCII table report.

Usage — wrap a single gate::

    from shared.hook_profiler import profile
    wrapped_check = profile("gate_01_read_before_edit", original_check)
    result = wrapped_check(tool_name, tool_input, state)

Usage — monkey-patch every gate in enforcer.py::

    from shared.hook_profiler import decorate_enforcer
    import enforcer
    decorate_enforcer(enforcer)

Usage — analyse the log and print a report::

    from shared.hook_profiler import analyze, report
    stats = analyze()   # -> {gate_name: {p50_ns, p95_ns, p99_ns, ...}}
    print(report())
"""

import json
import os
import time
from typing import Any, Callable, Dict, List, Optional

LATENCY_LOG = "/tmp/gate_latency.jsonl"

# Type alias for readability
_CheckFn = Callable[..., Any]


# ── Core wrapper ─────────────────────────────────────────────────────────────

def profile(gate_name: str, check_fn: _CheckFn) -> _CheckFn:
    """Return a new callable that wraps *check_fn* with nanosecond timing.

    Each invocation appends one JSON record to LATENCY_LOG::

        {"gate": "gate_01_...", "tool": "Edit", "elapsed_ns": 123456,
         "blocked": true, "ts": 1740000000.123}

    Args:
        gate_name: Short gate identifier (e.g. ``"gate_01_read_before_edit"``).
        check_fn:  The original ``check(tool_name, tool_input, state, ...)``
                   callable from a gate module.

    Returns:
        A replacement callable with an identical signature.  Timing and logging
        are non-fatal — if the log write fails the gate result is still returned.
    """
    def _wrapped(*args, **kwargs):
        t0 = time.perf_counter_ns()
        result = check_fn(*args, **kwargs)
        elapsed_ns = time.perf_counter_ns() - t0

        # Derive tool_name from positional args (check(tool_name, tool_input, state, ...))
        tool_name = args[0] if args else kwargs.get("tool_name", "")
        blocked = bool(getattr(result, "blocked", False))

        _append_record(gate_name, str(tool_name), elapsed_ns, blocked)
        return result

    # Preserve module attributes so enforcer can still call getattr(gate, "GATE_NAME")
    _wrapped.__name__ = getattr(check_fn, "__name__", gate_name)
    _wrapped.__doc__ = getattr(check_fn, "__doc__", "")
    _wrapped._profiler_wrapped = True
    _wrapped._original_check = check_fn
    return _wrapped


def _append_record(gate_name: str, tool_name: str, elapsed_ns: int, blocked: bool) -> None:
    """Append one latency record to LATENCY_LOG.  Fails silently on I/O errors."""
    record = {
        "gate": gate_name,
        "tool": tool_name,
        "elapsed_ns": elapsed_ns,
        "blocked": blocked,
        "ts": time.time(),
    }
    try:
        with open(LATENCY_LOG, "a", buffering=1) as fh:  # line-buffered
            fh.write(json.dumps(record) + "\n")
    except OSError:
        pass  # Non-fatal: profiler must never break gate execution


# ── Analysis ─────────────────────────────────────────────────────────────────

def _read_records() -> List[Dict]:
    """Read all records from LATENCY_LOG.  Returns empty list on any error."""
    records = []
    try:
        with open(LATENCY_LOG, "r") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass  # Skip corrupt lines
    except FileNotFoundError:
        pass
    except OSError:
        pass
    return records


def _percentile(sorted_vals: List[float], pct: float) -> float:
    """Nearest-rank percentile from a sorted list.  Returns 0.0 for empty input."""
    if not sorted_vals:
        return 0.0
    n = len(sorted_vals)
    # Use nearest-rank method (1-indexed, clamp to valid range)
    rank = max(1, int(pct / 100.0 * n + 0.5))
    return sorted_vals[min(rank, n) - 1]


def analyze(gate_filter: Optional[str] = None) -> Dict[str, Dict]:
    """Read LATENCY_LOG and compute per-gate latency percentiles.

    Args:
        gate_filter: If provided, only return stats for gates whose name
                     contains this substring (case-insensitive).

    Returns:
        Dict mapping gate name to a stats dict::

            {
                "count":   int,          # total invocations
                "p50_ns":  float,        # 50th-percentile latency in ns
                "p95_ns":  float,        # 95th-percentile latency in ns
                "p99_ns":  float,        # 99th-percentile latency in ns
                "min_ns":  float,
                "max_ns":  float,
                "avg_ns":  float,
                "blocked_count": int,    # how many calls resulted in a block
            }
    """
    records = _read_records()

    # Group elapsed_ns values by gate name
    by_gate: Dict[str, List[int]] = {}
    blocked_by_gate: Dict[str, int] = {}

    for rec in records:
        gate = rec.get("gate", "unknown")
        if gate_filter and gate_filter.lower() not in gate.lower():
            continue
        elapsed = rec.get("elapsed_ns")
        if elapsed is None:
            continue
        by_gate.setdefault(gate, []).append(elapsed)
        if rec.get("blocked"):
            blocked_by_gate[gate] = blocked_by_gate.get(gate, 0) + 1

    stats: Dict[str, Dict] = {}
    for gate, samples in by_gate.items():
        samples_sorted = sorted(samples)
        n = len(samples_sorted)
        stats[gate] = {
            "count": n,
            "p50_ns": _percentile(samples_sorted, 50),
            "p95_ns": _percentile(samples_sorted, 95),
            "p99_ns": _percentile(samples_sorted, 99),
            "min_ns": float(samples_sorted[0]),
            "max_ns": float(samples_sorted[-1]),
            "avg_ns": float(sum(samples_sorted)) / n,
            "blocked_count": blocked_by_gate.get(gate, 0),
        }

    return stats


# ── Report ────────────────────────────────────────────────────────────────────

def _ns_to_us(ns: float) -> str:
    """Format nanoseconds as microseconds with 1 decimal place."""
    return f"{ns / 1_000:.1f}"


def report(gate_filter: Optional[str] = None) -> str:
    """Return a formatted ASCII table of gate latency statistics.

    Rows are sorted by p95 descending (worst offenders first).

    Args:
        gate_filter: Optional substring filter applied to gate names.

    Returns:
        Multi-line string ready for print() or logging.
    """
    stats = analyze(gate_filter=gate_filter)
    if not stats:
        return "Hook Profiler: no latency data in " + LATENCY_LOG

    # Sort by p95 descending
    rows = sorted(stats.items(), key=lambda kv: kv[1]["p95_ns"], reverse=True)

    # Column widths
    name_w = max(len("Gate"), max(len(g) for g in stats)) + 2
    col_w = 10

    header = (
        f"{'Gate':<{name_w}}"
        f"{'count':>{col_w}}"
        f"{'p50 (us)':>{col_w}}"
        f"{'p95 (us)':>{col_w}}"
        f"{'p99 (us)':>{col_w}}"
        f"{'avg (us)':>{col_w}}"
        f"{'max (us)':>{col_w}}"
        f"{'blocks':>{col_w}}"
    )
    sep = "-" * len(header)

    lines = [
        "Hook Profiler — Gate Latency Report",
        f"Log: {LATENCY_LOG}",
        sep,
        header,
        sep,
    ]

    for gate, s in rows:
        lines.append(
            f"{gate:<{name_w}}"
            f"{s['count']:>{col_w}}"
            f"{_ns_to_us(s['p50_ns']):>{col_w}}"
            f"{_ns_to_us(s['p95_ns']):>{col_w}}"
            f"{_ns_to_us(s['p99_ns']):>{col_w}}"
            f"{_ns_to_us(s['avg_ns']):>{col_w}}"
            f"{_ns_to_us(s['max_ns']):>{col_w}}"
            f"{s['blocked_count']:>{col_w}}"
        )

    lines.append(sep)
    lines.append(f"Total gates tracked: {len(rows)}")
    return "\n".join(lines)


# ── Enforcer monkey-patcher ───────────────────────────────────────────────────

def decorate_enforcer(enforcer_module) -> int:
    """Monkey-patch all loaded gate check() functions in *enforcer_module*.

    Iterates over ``enforcer_module._loaded_gates`` (the live cache populated
    by ``_ensure_gates_loaded()``) and replaces each gate module's ``check``
    attribute with a profiled wrapper.  Also patches the dict entry so future
    dispatches use the wrapped version.

    Must be called *after* ``enforcer_module._ensure_gates_loaded()`` has run
    (i.e. after the first tool call reaches the enforcer), otherwise
    ``_loaded_gates`` will be empty.

    Args:
        enforcer_module: The imported ``enforcer`` module object.

    Returns:
        Number of gates successfully wrapped.

    Example::

        import enforcer
        enforcer._ensure_gates_loaded()
        from shared.hook_profiler import decorate_enforcer
        n = decorate_enforcer(enforcer)
        print(f"Profiling {n} gates")
    """
    loaded_gates: Dict = getattr(enforcer_module, "_loaded_gates", {})
    if not loaded_gates:
        # Try triggering a load — safe no-op if already loaded
        ensure_fn = getattr(enforcer_module, "_ensure_gates_loaded", None)
        if ensure_fn:
            try:
                ensure_fn()
            except SystemExit:
                pass  # Enforcer may exit(2) if Tier 1 gates missing; absorb here

        loaded_gates = getattr(enforcer_module, "_loaded_gates", {})

    wrapped_count = 0
    for module_name, gate_mod in loaded_gates.items():
        original_check = getattr(gate_mod, "check", None)
        if original_check is None:
            continue
        if getattr(original_check, "_profiler_wrapped", False):
            # Already wrapped — skip to avoid double-wrapping
            continue

        # Derive a short gate name from the module name (e.g. "gate_01_read_before_edit")
        gate_short = module_name.split(".")[-1]
        wrapped = profile(gate_short, original_check)

        # Patch on the module object and in the cache dict
        try:
            gate_mod.check = wrapped
            wrapped_count += 1
        except (AttributeError, TypeError):
            pass  # Some gate modules may use __slots__ or be immutable — skip

    return wrapped_count
