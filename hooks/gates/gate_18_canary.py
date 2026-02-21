"""Gate 18: CANARY MONITOR (Advisory only — never blocks)

A passive observability gate that records every tool call it sees and
computes running statistics to surface anomalous patterns.

Detects:
  1. Sudden tool call bursts  — spike in calls/min above rolling baseline
  2. Unusual tool sequences   — repeated back-to-back identical tool/input pairs
  3. New (never-seen) tools   — tools that have never appeared before in this session

All anomalies are written to stderr as warnings.  The gate NEVER returns
blocked=True.  It is purely additive telemetry.

Telemetry is written to /tmp/gate_canary.jsonl, one JSON line per call.
Statistics are maintained in the session state under the "canary_*" keys.

Gate contract: check(tool_name, tool_input, state, event_type="PreToolUse")
Returns: GateResult(blocked=False, ...)
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.gate_result import GateResult

GATE_NAME = "GATE 18: CANARY"

# Where telemetry lines are written
CANARY_LOG = "/tmp/gate_canary.jsonl"

# Burst detection: if calls/min in the last BURST_WINDOW_SECONDS exceeds
# BURST_THRESHOLD_MULTIPLIER × the rolling baseline, flag it.
BURST_WINDOW_SECONDS = 60          # rolling window for rate calculation
BURST_BASELINE_WINDOW = 300        # longer window for baseline (5 min)
BURST_THRESHOLD_MULTIPLIER = 3.0   # 3× baseline = burst
BURST_MIN_CALLS = 5                # need at least this many calls to detect a burst

# Repeated sequence detection: flag if the same (tool, input_hash) pair
# appears this many times in a row without any other tool in between.
REPEAT_SEQUENCE_THRESHOLD = 5


# ── Helpers ──────────────────────────────────────────────────────────────────

def _input_size(tool_input):
    """Return byte-length of JSON-serialised tool_input."""
    try:
        return len(json.dumps(tool_input, default=str))
    except Exception:
        return 0


def _input_hash(tool_input):
    """Stable 8-char hex fingerprint of tool_input for repeat-detection."""
    try:
        raw = json.dumps(tool_input, sort_keys=True, default=str)
    except Exception:
        raw = str(tool_input)
    # Simple FNV-1a (32-bit) — no hashlib needed
    h = 2166136261
    for ch in raw.encode("utf-8", errors="replace"):
        h = ((h ^ ch) * 16777619) & 0xFFFFFFFF
    return format(h, "08x")


def _append_to_log(record):
    """Append a JSON record to the canary log file (best-effort, atomic line)."""
    try:
        line = json.dumps(record, default=str) + "\n"
        with open(CANARY_LOG, "a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception:
        pass  # Never let telemetry break the gate


def _calls_per_minute(timestamps, window_seconds):
    """Return calls/minute within the last window_seconds from a timestamp list."""
    if not timestamps:
        return 0.0
    now = time.time()
    cutoff = now - window_seconds
    recent = [t for t in timestamps if t >= cutoff]
    if not recent:
        return 0.0
    elapsed_min = max(window_seconds / 60.0, 1e-6)
    return len(recent) / elapsed_min


# ── Main check ───────────────────────────────────────────────────────────────

def check(tool_name, tool_input, state, event_type="PreToolUse"):
    """Record every tool call and emit warnings when anomalies are detected.

    Never blocks — always returns GateResult(blocked=False).
    """
    now = time.time()
    warnings = []

    # ── 1. Update running state ──────────────────────────────────────────────

    # Per-tool call counts
    tool_counts = state.get("canary_tool_counts", {})
    tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1
    state["canary_tool_counts"] = tool_counts

    # Unique tools seen (stored as a list for JSON-serialisability)
    seen_tools = set(state.get("canary_seen_tools", []))
    is_new_tool = tool_name not in seen_tools
    seen_tools.add(tool_name)
    state["canary_seen_tools"] = sorted(seen_tools)

    # Total call counter
    total_calls = state.get("canary_total_calls", 0) + 1
    state["canary_total_calls"] = total_calls

    # Input-size running stats (Welford online mean/M2)
    size = _input_size(tool_input)
    n_sizes = state.get("canary_size_count", 0) + 1
    mean_size = state.get("canary_size_mean", 0.0)
    m2_size = state.get("canary_size_m2", 0.0)
    delta = size - mean_size
    mean_size += delta / n_sizes
    m2_size += delta * (size - mean_size)
    state["canary_size_count"] = n_sizes
    state["canary_size_mean"] = mean_size
    state["canary_size_m2"] = m2_size

    # Burst-detection: keep two rings of timestamps
    short_ts = state.get("canary_short_timestamps", [])
    long_ts = state.get("canary_long_timestamps", [])
    short_ts.append(now)
    long_ts.append(now)
    # Trim to relevant windows (keep a bit extra to avoid off-by-one on boundary)
    short_ts = [t for t in short_ts if t >= now - BURST_WINDOW_SECONDS * 2]
    long_ts = [t for t in long_ts if t >= now - BURST_BASELINE_WINDOW * 2]
    state["canary_short_timestamps"] = short_ts
    state["canary_long_timestamps"] = long_ts

    # Repeat-sequence tracking: remember (tool, input_hash) of last N calls
    seq_key = (tool_name, _input_hash(tool_input))
    recent_seq = state.get("canary_recent_seq", [])  # list of [tool, hash] pairs
    recent_seq.append([tool_name, seq_key[1]])
    # Keep only the last REPEAT_SEQUENCE_THRESHOLD + 1 entries
    if len(recent_seq) > REPEAT_SEQUENCE_THRESHOLD + 1:
        recent_seq = recent_seq[-(REPEAT_SEQUENCE_THRESHOLD + 1):]
    state["canary_recent_seq"] = recent_seq

    # ── 2. Compute statistics ────────────────────────────────────────────────

    unique_tools = len(seen_tools)
    avg_input_size = mean_size  # running mean

    current_rate = _calls_per_minute(short_ts, BURST_WINDOW_SECONDS)
    baseline_rate = _calls_per_minute(long_ts, BURST_BASELINE_WINDOW)

    # ── 3. Anomaly detection ─────────────────────────────────────────────────

    # 3a. New tool never seen before
    if is_new_tool and total_calls > 1:
        warnings.append(
            f"new tool observed: '{tool_name}' (unique tools seen: {unique_tools})"
        )

    # 3b. Sudden burst
    if (
        total_calls >= BURST_MIN_CALLS
        and baseline_rate > 0
        and current_rate >= baseline_rate * BURST_THRESHOLD_MULTIPLIER
    ):
        warnings.append(
            f"tool call burst: {current_rate:.1f} calls/min "
            f"(baseline {baseline_rate:.1f}, {BURST_THRESHOLD_MULTIPLIER:.0f}× threshold)"
        )

    # 3c. Repeated identical (tool, input) sequence
    if len(recent_seq) >= REPEAT_SEQUENCE_THRESHOLD:
        tail = recent_seq[-REPEAT_SEQUENCE_THRESHOLD:]
        if all(entry == tail[0] for entry in tail):
            warnings.append(
                f"repeated identical call: '{tool_name}' called "
                f"{REPEAT_SEQUENCE_THRESHOLD}+ times in a row with the same input"
            )

    # ── 4. Write telemetry line ──────────────────────────────────────────────

    record = {
        "ts": now,
        "tool": tool_name,
        "event_type": event_type,
        "input_size": size,
        "total_calls": total_calls,
        "unique_tools": unique_tools,
        "avg_input_size": round(avg_input_size, 1),
        "rate_per_min": round(current_rate, 2),
        "baseline_rate_per_min": round(baseline_rate, 2),
        "anomalies": warnings,
    }
    _append_to_log(record)

    # ── 5. Emit warnings to stderr ───────────────────────────────────────────

    if warnings:
        for w in warnings:
            print(f"[{GATE_NAME}] WARNING: {w}", file=sys.stderr)
        msg = f"[{GATE_NAME}] Anomalies detected: " + "; ".join(warnings)
        return GateResult(
            blocked=False,
            gate_name=GATE_NAME,
            message=msg,
            severity="warn",
        )

    return GateResult(blocked=False, gate_name=GATE_NAME)
