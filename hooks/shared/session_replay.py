"""Session Replay — shared/session_replay.py

Records and replays a timeline of significant events during a session:
gate fires, blocks, memory queries, test runs, errors.  Provides export
in multiple formats (JSON, text summary, mermaid sequence diagram).

Uses existing audit log data — no new runtime data collection needed.

Public API
----------
  build_timeline(lookback_hours, gate_filter, tool_filter) -> dict
  export_text(lookback_hours)       -> str
  export_mermaid(lookback_hours)    -> str
  get_timeline_stats(lookback_hours) -> dict
  detect_patterns(lookback_hours)   -> dict

Usage
-----
    from shared.session_replay import build_timeline, export_text

    timeline = build_timeline(lookback_hours=1)
    print(export_text(lookback_hours=1))
"""

from __future__ import annotations

import glob as _glob
import json
import os
import time
from collections import Counter
from datetime import datetime
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

try:
    from shared.audit_log import AUDIT_DIR
except ImportError:
    AUDIT_DIR = os.path.join(os.path.expanduser("~"), ".claude", "hooks", "audit")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_audit_entries(lookback_hours: int = 1) -> List[dict]:
    """Load audit entries within the lookback window, sorted by timestamp."""
    if not os.path.isdir(AUDIT_DIR):
        return []

    cutoff = time.time() - (lookback_hours * 3600)
    entries = []

    audit_files = sorted(_glob.glob(os.path.join(AUDIT_DIR, "*.jsonl")), reverse=True)
    for af in audit_files[:max(2, lookback_hours // 24 + 2)]:
        try:
            with open(af) as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                    except (json.JSONDecodeError, ValueError):
                        continue
                    ts = entry.get("timestamp", entry.get("ts", 0))
                    if isinstance(ts, (int, float)) and ts >= cutoff:
                        entries.append(entry)
        except OSError:
            continue

    entries.sort(key=lambda e: e.get("timestamp", e.get("ts", 0)))
    return entries


def _format_ts(ts: float) -> str:
    """Format a unix timestamp as HH:MM:SS."""
    try:
        return datetime.fromtimestamp(ts).strftime("%H:%M:%S")
    except (OSError, ValueError, OverflowError):
        return "??:??:??"


def _classify_event(entry: dict) -> str:
    """Classify an audit entry into an event type."""
    decision = entry.get("decision", "")
    if decision == "block":
        return "BLOCK"
    elif decision == "allow":
        return "PASS"
    elif decision == "warn":
        return "WARN"
    return "EVENT"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_timeline(
    lookback_hours: int = 1,
    gate_filter: str = "",
    tool_filter: str = "",
) -> dict:
    """Build a session timeline from audit log entries.

    Parameters
    ----------
    lookback_hours : int
        How far back to scan (default 1 hour, max 168).
    gate_filter : str
        Only include entries matching this gate name substring.
    tool_filter : str
        Only include entries matching this tool name.

    Returns
    -------
    dict with:
        events           : list[dict] — chronological event list
        event_count      : int
        duration_seconds : float
        event_types      : dict — counts per event type
        gates_seen       : list[str]
        tools_seen       : list[str]
    """
    lookback_hours = max(1, min(168, lookback_hours))
    entries = _load_audit_entries(lookback_hours)

    events = []
    type_counts = Counter()
    gates_seen = set()
    tools_seen = set()

    for entry in entries:
        gate = entry.get("gate", "")
        tool = entry.get("tool", "")

        # Apply filters
        if gate_filter and gate_filter.lower() not in gate.lower():
            continue
        if tool_filter and tool_filter.lower() != tool.lower():
            continue

        ts = entry.get("timestamp", entry.get("ts", 0))
        event_type = _classify_event(entry)
        type_counts[event_type] += 1
        if gate:
            gates_seen.add(gate)
        if tool:
            tools_seen.add(tool)

        events.append({
            "timestamp": ts,
            "time": _format_ts(ts),
            "type": event_type,
            "gate": gate,
            "tool": tool,
            "decision": entry.get("decision", ""),
            "message": entry.get("message", "")[:200],
            "duration_ms": entry.get("duration_ms", 0),
        })

    duration = 0.0
    if len(events) >= 2:
        duration = events[-1]["timestamp"] - events[0]["timestamp"]

    return {
        "events": events,
        "event_count": len(events),
        "duration_seconds": round(duration, 1),
        "event_types": dict(type_counts),
        "gates_seen": sorted(gates_seen),
        "tools_seen": sorted(tools_seen),
    }


def export_text(lookback_hours: int = 1) -> str:
    """Export session timeline as readable text.

    Parameters
    ----------
    lookback_hours : int
        How far back to scan.

    Returns
    -------
    str
        Multi-line text timeline.
    """
    timeline = build_timeline(lookback_hours)
    events = timeline["events"]

    lines = [
        f"Session Timeline ({lookback_hours}h lookback)",
        "=" * 80,
    ]

    if not events:
        lines.append("  (no events found in audit logs)")
    else:
        for ev in events:
            symbol = {
                "BLOCK": "BLOCK",
                "WARN": " WARN",
                "PASS": " pass",
                "EVENT": "event",
            }.get(ev["type"], ev["type"])

            gate_short = ev["gate"].split(":")[-1].strip() if ev["gate"] else ""
            msg = ev["message"][:60] if ev["message"] else ""

            line = f"[{ev['time']}] {symbol:<6} {ev['tool']:<12} {gate_short:<30}"
            if msg:
                line += f" {msg}"
            lines.append(line)

    lines.append("=" * 80)
    lines.append(
        f"Events: {timeline['event_count']}  |  "
        f"Duration: {timeline['duration_seconds']:.0f}s  |  "
        f"Blocks: {timeline['event_types'].get('BLOCK', 0)}  |  "
        f"Gates: {len(timeline['gates_seen'])}"
    )

    return "\n".join(lines)


def export_mermaid(lookback_hours: int = 1, limit: int = 30) -> str:
    """Export session timeline as Mermaid sequence diagram.

    Parameters
    ----------
    lookback_hours : int
        How far back to scan.
    limit : int
        Max events to include (default 30).

    Returns
    -------
    str
        Mermaid sequence diagram markdown.
    """
    timeline = build_timeline(lookback_hours)
    events = timeline["events"][:limit]

    if not events:
        return "```mermaid\nsequenceDiagram\n    Note over Claude: No events found\n```"

    lines = ["```mermaid", "sequenceDiagram"]
    lines.append("    participant C as Claude")
    lines.append("    participant G as Gates")
    lines.append("    participant T as Tools")

    for ev in events:
        tool = ev["tool"] or "unknown"
        gate = ev["gate"].split(":")[-1].strip()[:25] if ev["gate"] else "unknown"

        if ev["type"] == "BLOCK":
            lines.append(f"    C->>G: {tool}")
            lines.append(f"    G--xC: BLOCK ({gate})")
        elif ev["type"] == "WARN":
            lines.append(f"    C->>G: {tool}")
            lines.append(f"    Note over G: WARN: {gate}")
            lines.append(f"    G->>T: allow")
        else:
            lines.append(f"    C->>G: {tool}")
            lines.append(f"    G->>T: pass")

    lines.append("```")
    return "\n".join(lines)


def get_timeline_stats(lookback_hours: int = 1) -> dict:
    """Get summary statistics about a session's timeline.

    Parameters
    ----------
    lookback_hours : int
        How far back to scan.

    Returns
    -------
    dict with:
        total_events        : int
        duration_minutes    : float
        events_per_minute   : float
        block_count         : int
        block_rate          : float (0.0-1.0)
        most_active_gate    : str
        most_blocked_gate   : str
        most_used_tool      : str
        gate_count          : int
    """
    timeline = build_timeline(lookback_hours)
    events = timeline["events"]

    gate_fire_counts = Counter()
    gate_block_counts = Counter()
    tool_counts = Counter()

    for ev in events:
        if ev["gate"]:
            gate_fire_counts[ev["gate"]] += 1
        if ev["tool"]:
            tool_counts[ev["tool"]] += 1
        if ev["type"] == "BLOCK" and ev["gate"]:
            gate_block_counts[ev["gate"]] += 1

    total = len(events)
    duration_min = timeline["duration_seconds"] / 60.0 if timeline["duration_seconds"] > 0 else 0.0
    block_count = timeline["event_types"].get("BLOCK", 0)

    return {
        "total_events": total,
        "duration_minutes": round(duration_min, 1),
        "events_per_minute": round(total / max(duration_min, 0.1), 1),
        "block_count": block_count,
        "block_rate": round(block_count / max(total, 1), 3),
        "most_active_gate": gate_fire_counts.most_common(1)[0][0] if gate_fire_counts else "",
        "most_blocked_gate": gate_block_counts.most_common(1)[0][0] if gate_block_counts else "",
        "most_used_tool": tool_counts.most_common(1)[0][0] if tool_counts else "",
        "gate_count": len(timeline["gates_seen"]),
    }


def detect_patterns(lookback_hours: int = 1) -> dict:
    """Detect anomalous patterns in the session timeline.

    Checks for:
    - Consecutive blocks on the same gate (possible infinite loop)
    - Rapid repeated blocks (>3 blocks within 30 seconds)
    - Single gate dominating blocks (>70% of all blocks)

    Parameters
    ----------
    lookback_hours : int
        How far back to scan.

    Returns
    -------
    dict with:
        patterns  : list[dict] — detected anomaly patterns
        healthy   : bool — True if no concerning patterns found
        summary   : str — human-readable summary
    """
    timeline = build_timeline(lookback_hours)
    events = timeline["events"]
    patterns = []

    # 1. Consecutive blocks on same gate
    prev_block_gate = ""
    consecutive_count = 0
    for ev in events:
        if ev["type"] == "BLOCK":
            if ev["gate"] == prev_block_gate:
                consecutive_count += 1
                if consecutive_count >= 3:
                    patterns.append({
                        "type": "consecutive_blocks",
                        "severity": "warn",
                        "gate": ev["gate"],
                        "count": consecutive_count,
                        "description": f"Gate '{ev['gate']}' blocked {consecutive_count} times consecutively",
                    })
            else:
                prev_block_gate = ev["gate"]
                consecutive_count = 1
        else:
            prev_block_gate = ""
            consecutive_count = 0

    # 2. Rapid blocks (>3 within 30 seconds)
    block_events = [ev for ev in events if ev["type"] == "BLOCK"]
    for i in range(len(block_events)):
        window_end = block_events[i]["timestamp"] + 30
        count_in_window = sum(
            1 for j in range(i, len(block_events))
            if block_events[j]["timestamp"] <= window_end
        )
        if count_in_window > 3:
            patterns.append({
                "type": "rapid_blocks",
                "severity": "warn",
                "count": count_in_window,
                "window_seconds": 30,
                "description": f"{count_in_window} blocks within 30 seconds — possible thrashing",
            })
            break  # Only report once

    # 3. Single gate dominance
    if block_events:
        gate_blocks = Counter(ev["gate"] for ev in block_events)
        total_blocks = len(block_events)
        for gate, count in gate_blocks.most_common(1):
            ratio = count / total_blocks
            if ratio > 0.7 and count >= 3:
                patterns.append({
                    "type": "gate_dominance",
                    "severity": "info",
                    "gate": gate,
                    "ratio": round(ratio, 2),
                    "description": f"Gate '{gate}' accounts for {ratio:.0%} of all blocks",
                })

    healthy = len(patterns) == 0
    summary = "No concerning patterns detected." if healthy else (
        f"{len(patterns)} pattern(s) detected: " +
        ", ".join(p["type"] for p in patterns)
    )

    return {
        "patterns": patterns,
        "healthy": healthy,
        "summary": summary,
    }
