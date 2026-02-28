"""Gate result correlation analyzer.

Identifies correlations between gate block events to find redundant
gates and optimization opportunities.

Usage:
    from shared.gate_correlation import analyze_correlations, format_correlation_report

    correlations = analyze_correlations(days=7)
    print(format_correlation_report(correlations))
"""

import gzip
import json
import os
from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, List, Tuple


AUDIT_DIRS = [
    os.path.join(os.path.expanduser("~"), ".claude", "hooks", "audit"),
    "/run/user/1000/claude-hooks/audit",
]


def _read_audit_entries(days=7):
    """Read audit log entries from the last N days."""
    entries = []
    for delta in range(days):
        d = (date.today() - timedelta(days=delta)).isoformat()
        for audit_dir in AUDIT_DIRS:
            for suffix in ["", ".gz"]:
                path = os.path.join(audit_dir, f"{d}.jsonl{suffix}")
                if not os.path.isfile(path):
                    continue
                try:
                    opener = gzip.open if suffix else open
                    with opener(path, "rt") as f:
                        for line in f:
                            try:
                                entries.append(json.loads(line))
                            except json.JSONDecodeError:
                                continue
                except Exception:
                    continue
    return entries


def analyze_correlations(days=7):
    """Analyze gate block co-occurrence from audit logs.

    Returns dict with:
        pairs: list of (gate_a, gate_b, co_occurrence_pct, count)
        gate_block_counts: dict of gate_name -> block_count
        total_events: total audit entries analyzed
    """
    entries = _read_audit_entries(days)

    # Group blocks by session+timestamp (approximate same tool call)
    # Use (session_id, timestamp_truncated) as key
    call_groups = defaultdict(set)  # group_key -> set of gates that blocked
    gate_blocks = defaultdict(int)

    for entry in entries:
        if entry.get("decision") != "block":
            continue
        gate = entry.get("gate", "")
        session = entry.get("session_id", "unknown")
        ts = entry.get("timestamp", "")[:19]  # Truncate to second

        group_key = f"{session}_{ts}"
        call_groups[group_key].add(gate)
        gate_blocks[gate] += 1

    # Build co-occurrence counts
    co_occurrence = defaultdict(int)
    for group_key, gates in call_groups.items():
        gates_list = sorted(gates)
        for i in range(len(gates_list)):
            for j in range(i + 1, len(gates_list)):
                pair = (gates_list[i], gates_list[j])
                co_occurrence[pair] += 1

    # Calculate percentages
    pairs = []
    for (gate_a, gate_b), count in sorted(co_occurrence.items(), key=lambda x: x[1], reverse=True):
        # Percentage relative to the less common gate
        min_blocks = min(gate_blocks.get(gate_a, 1), gate_blocks.get(gate_b, 1))
        pct = (count / min_blocks * 100) if min_blocks > 0 else 0
        pairs.append({
            "gate_a": gate_a,
            "gate_b": gate_b,
            "co_occurrence_pct": round(pct, 1),
            "count": count,
        })

    return {
        "pairs": pairs[:20],  # Top 20
        "gate_block_counts": dict(gate_blocks),
        "total_events": len(entries),
        "days_analyzed": days,
    }


def format_correlation_report(data):
    """Format correlation analysis as readable report."""
    lines = [
        "Gate Block Correlation Report",
        f"Period: {data.get('days_analyzed', 0)} days, {data.get('total_events', 0)} events",
        "=" * 60,
    ]

    blocks = data.get("gate_block_counts", {})
    if blocks:
        lines.append("\nBlock counts per gate:")
        for gate, count in sorted(blocks.items(), key=lambda x: x[1], reverse=True)[:10]:
            lines.append(f"  {gate:<40} {count:>4} blocks")

    pairs = data.get("pairs", [])
    if pairs:
        lines.append("\nCo-occurrence pairs (gates that block together):")
        for p in pairs[:10]:
            lines.append(
                f"  {p['gate_a']} + {p['gate_b']}: "
                f"{p['co_occurrence_pct']:.0f}% co-occurrence ({p['count']} times)"
            )
    elif not blocks:
        lines.append("\nNo block events found in audit logs.")

    lines.append("=" * 60)
    return "\n".join(lines)
