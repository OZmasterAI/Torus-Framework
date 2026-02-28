"""Prometheus-compatible metrics export for the Torus framework.

Reads from metrics_collector (ramdisk/disk) and health_monitor, formats
as Prometheus text exposition format or plain dict.
Default output: /tmp/torus_metrics.prom

Usage:
    from shared.metrics_exporter import export_prometheus, export_json
    text = export_prometheus()                       # write + return text
    text = export_prometheus("/var/lib/node_exp/torus.prom")
    data = export_json()                             # dict for JSON consumers
"""

import os
import sys
import time
from typing import Optional

_HOOKS_DIR = os.path.join(os.path.expanduser("~"), ".claude", "hooks")
if _HOOKS_DIR not in sys.path:
    sys.path.insert(0, _HOOKS_DIR)

DEFAULT_OUTPUT_PATH = "/tmp/torus_metrics.prom"

# (prom_name, help_text, prom_type, source_metric, scale)
# scale converts source units → Prometheus units (ms → s = 0.001)
_DEFS = [
    ("torus_gate_blocks_total",        "Total gate block events per gate",              "counter",   "gate.blocks",        1.0),
    ("torus_gate_fires_total",         "Total gate fire events per gate",               "counter",   "gate.fires",         1.0),
    ("torus_gate_latency_seconds",     "Gate execution latency in seconds",             "histogram", "gate.latency_ms",    0.001),
    ("torus_memory_count",             "Total memories stored (table label injected)",  "gauge",     "memory.total",       1.0),
    ("torus_memory_queries_total",     "Total memory query operations",                 "counter",   "memory.queries",     1.0),
    ("torus_session_tool_calls_total", "Total tool calls in current session",           "counter",   "session.tool_calls", 1.0),
    ("torus_test_pass_rate",           "Fraction of tests passing (0.0–1.0)",           "gauge",     "test.pass_rate",     1.0),
]


# ── Label formatting ──────────────────────────────────────────────────────────

def _ls(labels: dict) -> str:
    """Format labels dict as Prometheus label set string: {k="v",...}"""
    if not labels:
        return ""
    return "{" + ",".join(f'{k}="{v}"' for k, v in sorted(labels.items())) + "}"


# ── Per-type emitters ─────────────────────────────────────────────────────────

def _emit_counter(lines: list, name: str, help_: str, entries: dict, scale: float) -> None:
    lines += [f"# HELP {name} {help_}", f"# TYPE {name} counter"]
    for entry in entries.values():
        lines.append(f"{name}{_ls(entry.get('labels', {}))} {entry.get('value', 0) * scale}")


def _emit_gauge(lines: list, name: str, help_: str, entries: dict, scale: float,
                inject_labels: Optional[dict] = None) -> None:
    lines += [f"# HELP {name} {help_}", f"# TYPE {name} gauge"]
    for entry in entries.values():
        labels = {**entry.get("labels", {}), **(inject_labels or {})}
        lines.append(f"{name}{_ls(labels)} {entry.get('value', 0.0) * scale}")


def _emit_histogram(lines: list, name: str, help_: str, entries: dict, scale: float) -> None:
    lines += [f"# HELP {name} {help_}", f"# TYPE {name} histogram"]
    for entry in entries.values():
        base_labels = entry.get("labels", {})
        count = entry.get("count", 0)
        total = entry.get("sum", 0.0) * scale
        inf_ls = _ls({**base_labels, "le": "+Inf"})
        base_ls = _ls(base_labels)
        lines += [
            f"{name}_bucket{inf_ls} {count}",
            f"{name}_sum{base_ls} {total}",
            f"{name}_count{base_ls} {count}",
        ]


def _zero_metric(lines: list, name: str, help_: str, mtype: str) -> None:
    lines += [f"# HELP {name} {help_}", f"# TYPE {name} {mtype}"]
    if mtype == "histogram":
        lines += [f'{name}_bucket{{le="+Inf"}} 0', f"{name}_sum 0", f"{name}_count 0"]
    else:
        lines.append(f"{name} 0")


# ── Public API ────────────────────────────────────────────────────────────────

def export_prometheus(output_path: Optional[str] = None) -> str:
    """Format current metrics as Prometheus text and write to output_path.

    Args:
        output_path: File to write. Default: /tmp/torus_metrics.prom

    Returns:
        Prometheus text exposition format string.
    """
    if output_path is None:
        output_path = DEFAULT_OUTPUT_PATH

    try:
        from shared.metrics_collector import get_all_metrics
        all_m = get_all_metrics()
    except Exception:
        all_m = {}

    lines: list = [
        "# Torus Framework Metrics",
        f"# Generated {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        "",
    ]

    for prom_name, help_text, mtype, src, scale in _DEFS:
        entries = all_m.get(src, {})
        inject = {"table": "knowledge"} if src == "memory.total" else None
        if not entries:
            _zero_metric(lines, prom_name, help_text, mtype)
        elif mtype == "counter":
            _emit_counter(lines, prom_name, help_text, entries, scale)
        elif mtype == "gauge":
            _emit_gauge(lines, prom_name, help_text, entries, scale, inject)
        elif mtype == "histogram":
            _emit_histogram(lines, prom_name, help_text, entries, scale)
        lines.append("")

    # Health score
    lines += ["# HELP torus_health_score Framework health score (0-100)", "# TYPE torus_health_score gauge"]
    try:
        from shared.health_monitor import full_health_check
        lines.append(f"torus_health_score {full_health_check('default').get('overall_score', 0)}")
    except Exception:
        lines.append("torus_health_score 0")
    lines.append("")

    # Errors: aggregate gate blocks across all gates
    lines += ["# HELP torus_errors_total Total gate blocks (all gates combined)", "# TYPE torus_errors_total counter"]
    total_blocks = sum(e.get("value", 0) for e in all_m.get("gate.blocks", {}).values())
    lines.append(f"torus_errors_total {total_blocks}")
    lines.append("")

    text = "\n".join(lines) + "\n"

    try:
        with open(output_path, "w") as fh:
            fh.write(text)
    except (OSError, IOError):
        pass  # fail-open — still return text

    return text


def export_json() -> dict:
    """Return current metrics as a structured dict for JSON consumers.

    Keys mirror the Prometheus metric names from export_prometheus().
    Returns a dict with "exported_at" (Unix timestamp) and "metrics" sub-dict.
    """
    try:
        from shared.metrics_collector import get_all_metrics
        all_m = get_all_metrics()
    except Exception:
        all_m = {}

    def _counter_by_gate(src: str) -> dict:
        return {e.get("labels", {}).get("gate", lk or "unlabeled"): e.get("value", 0)
                for lk, e in all_m.get(src, {}).items()}

    gate_latency = {}
    for lk, e in all_m.get("gate.latency_ms", {}).items():
        gate = e.get("labels", {}).get("gate", lk or "unlabeled")
        gate_latency[gate] = {
            "count": e.get("count", 0),
            "sum_seconds": e.get("sum", 0.0) / 1000.0,
            "avg_seconds": e.get("avg", 0.0) / 1000.0,
        }

    gate_blocks = _counter_by_gate("gate.blocks")

    mem_val = next((e.get("value", 0) for e in all_m.get("memory.total", {}).values()), 0)
    tc_val  = next((e.get("value", 0) for e in all_m.get("session.tool_calls", {}).values()), 0)

    try:
        from shared.health_monitor import full_health_check
        health_score = full_health_check("default").get("overall_score", 0)
    except Exception:
        health_score = 0

    return {
        "exported_at": time.time(),
        "metrics": {
            "torus_gate_blocks_total":        gate_blocks,
            "torus_gate_fires_total":         _counter_by_gate("gate.fires"),
            "torus_gate_latency_seconds":     gate_latency,
            "torus_memory_count":             {"knowledge": mem_val},
            "torus_memory_queries_total":     next((e.get("value", 0) for e in all_m.get("memory.queries", {}).values()), 0),
            "torus_session_tool_calls_total": tc_val,
            "torus_errors_total":             sum(gate_blocks.values()),
            "torus_health_score":             health_score,
        },
    }
