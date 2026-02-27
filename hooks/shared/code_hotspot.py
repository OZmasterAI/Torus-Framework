"""Code Hotspot Analyzer — shared/code_hotspot.py

Identifies high-risk files by cross-referencing gate audit data with file
paths from tool_input.  Produces a ranked list of files by composite risk
score: block_count * churn_factor * error_density.

All functions are read-only, fail-open, and safe to call from any context.

Public API
----------
  extract_file_path(tool_input, tool_name)    -> str
  analyze_file_blocks(lookback_days, min_blocks) -> dict
  rank_files_by_risk(lookback_days, limit)    -> list[dict]
  export_hotspot_report(lookback_days)        -> str

Usage
-----
    from shared.code_hotspot import rank_files_by_risk, export_hotspot_report

    ranked = rank_files_by_risk(lookback_days=7)
    print(export_hotspot_report())
"""

from __future__ import annotations

import glob as _glob
import json
import os
import time
from collections import Counter, defaultdict
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

try:
    from shared.audit_log import AUDIT_DIR
except ImportError:
    AUDIT_DIR = os.path.join(os.path.expanduser("~"), ".claude", "hooks", "audit")


# ---------------------------------------------------------------------------
# File path extraction
# ---------------------------------------------------------------------------


def extract_file_path(tool_input: dict, tool_name: str = "") -> str:
    """Extract the primary file path from a tool_input dict.

    Handles Edit, Write, Read, NotebookEdit, Glob (path field), and
    Bash (heuristic: first quoted path argument).

    Parameters
    ----------
    tool_input : dict
        The tool_input dict from a hook payload or audit entry.
    tool_name : str
        Name of the tool (helps disambiguate).

    Returns
    -------
    str
        Extracted file path, or empty string if none found.
    """
    if not isinstance(tool_input, dict):
        return ""

    # Direct path fields (Edit, Write, Read, NotebookEdit)
    for key in ("file_path", "path", "notebook_path"):
        val = tool_input.get(key, "")
        if isinstance(val, str) and val.strip():
            return val.strip()

    # Bash: try to extract path from command
    command = tool_input.get("command", "")
    if isinstance(command, str) and command:
        import re
        # Match quoted paths or paths starting with /
        m = re.search(r'(?:^|\s)(/[^\s"\']+\.(?:py|js|ts|json|md|yaml|yml|sh))', command)
        if m:
            return m.group(1)

    return ""


# ---------------------------------------------------------------------------
# Audit log scanning
# ---------------------------------------------------------------------------


def _scan_audit_entries(lookback_days: int = 7) -> List[dict]:
    """Scan audit log files and return entries within the lookback window.

    Returns a list of parsed audit entry dicts.  Silently skips
    unparseable lines and missing files.
    """
    if not os.path.isdir(AUDIT_DIR):
        return []

    cutoff = time.time() - (lookback_days * 86400)
    entries = []

    audit_files = sorted(_glob.glob(os.path.join(AUDIT_DIR, "*.jsonl")), reverse=True)
    for af in audit_files[:lookback_days + 2]:
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

    return entries


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze_file_blocks(
    lookback_days: int = 7,
    min_blocks: int = 1,
) -> dict:
    """Analyze gate blocks per file from audit logs.

    Cross-references audit entries' file_path with block decisions
    to identify which files trigger the most gate enforcement.

    Parameters
    ----------
    lookback_days : int
        How far back to scan audit logs (default 7, max 30).
    min_blocks : int
        Minimum blocks to include a file in results (default 1).

    Returns
    -------
    dict with keys:
        file_blocks      : list[dict] — per-file block data
        total_blocks     : int
        total_files      : int
        analysis_window  : int (days)
    """
    lookback_days = max(1, min(30, lookback_days))
    entries = _scan_audit_entries(lookback_days)

    file_data: Dict[str, dict] = defaultdict(lambda: {
        "block_count": 0,
        "blocks_by_gate": Counter(),
        "blocks_by_tool": Counter(),
        "edit_count": 0,
        "recent_block_time": 0.0,
    })

    total_blocks = 0

    for entry in entries:
        tool_input = entry.get("tool_input", {})
        tool_name = entry.get("tool", "")
        decision = entry.get("decision", "")
        gate = entry.get("gate", "")

        fp = extract_file_path(tool_input, tool_name)
        if not fp:
            continue

        if decision == "block":
            data = file_data[fp]
            data["block_count"] += 1
            data["blocks_by_gate"][gate] += 1
            data["blocks_by_tool"][tool_name] += 1
            ts = entry.get("timestamp", entry.get("ts", 0))
            if isinstance(ts, (int, float)) and ts > data["recent_block_time"]:
                data["recent_block_time"] = ts
            total_blocks += 1

        # Count all edit attempts (for error density calculation)
        if tool_name in ("Edit", "Write", "NotebookEdit"):
            file_data[fp]["edit_count"] += 1

    # Filter and format
    file_blocks = []
    for fp, data in sorted(file_data.items(), key=lambda kv: kv[1]["block_count"], reverse=True):
        if data["block_count"] < min_blocks:
            continue
        file_blocks.append({
            "file_path": fp,
            "block_count": data["block_count"],
            "edit_count": data["edit_count"],
            "blocks_by_gate": dict(data["blocks_by_gate"]),
            "blocks_by_tool": dict(data["blocks_by_tool"]),
            "recent_block_time": data["recent_block_time"],
        })

    return {
        "file_blocks": file_blocks,
        "total_blocks": total_blocks,
        "total_files": len(file_blocks),
        "analysis_window": lookback_days,
    }


def rank_files_by_risk(
    lookback_days: int = 7,
    limit: int = 50,
    risk_threshold: float = 0.0,
) -> list:
    """Rank files by composite risk score (highest risk first).

    Risk = block_count * churn_factor * error_density

    Where:
    - block_count: number of gate blocks on this file
    - churn_factor: edit attempts / average edits (clamped 0.5–3.0)
    - error_density: blocks / total edit attempts (0.0–1.0)

    Parameters
    ----------
    lookback_days : int
        Analysis window (default 7).
    limit : int
        Max files to return (default 50).
    risk_threshold : float
        Only include files with risk_score >= threshold.

    Returns
    -------
    list[dict]
        Ranked list with rank, file_path, risk_score, risk_level,
        block_count, churn_factor, error_density, edit_count.
    """
    analysis = analyze_file_blocks(lookback_days)
    file_blocks = analysis["file_blocks"]

    if not file_blocks:
        return []

    # Compute average edits across all files
    edit_counts = [fb["edit_count"] for fb in file_blocks if fb["edit_count"] > 0]
    avg_edits = (sum(edit_counts) / len(edit_counts)) if edit_counts else 1.0

    ranked = []
    for fb in file_blocks:
        block_count = fb["block_count"]
        edit_count = max(fb["edit_count"], 1)

        # Churn: how much this file is edited relative to average
        churn_factor = max(0.5, min(3.0, edit_count / max(avg_edits, 1.0)))

        # Error density: blocks as fraction of edit attempts
        error_density = min(1.0, block_count / max(edit_count, 1))

        risk_score = round(block_count * churn_factor * error_density, 2)

        if risk_score < risk_threshold:
            continue

        # Risk level classification
        if risk_score >= 10.0:
            risk_level = "critical"
        elif risk_score >= 5.0:
            risk_level = "high"
        elif risk_score >= 2.0:
            risk_level = "medium"
        else:
            risk_level = "low"

        ranked.append({
            "file_path": fb["file_path"],
            "risk_score": risk_score,
            "risk_level": risk_level,
            "block_count": block_count,
            "churn_factor": round(churn_factor, 2),
            "error_density": round(error_density, 3),
            "edit_count": fb["edit_count"],
            "blocks_by_gate": fb["blocks_by_gate"],
        })

    # Sort by risk_score descending
    ranked.sort(key=lambda r: r["risk_score"], reverse=True)

    # Add rank numbers
    for i, r in enumerate(ranked[:limit]):
        r["rank"] = i + 1

    return ranked[:limit]


def export_hotspot_report(lookback_days: int = 7) -> str:
    """Export file risk analysis as formatted text report.

    Parameters
    ----------
    lookback_days : int
        Analysis window.

    Returns
    -------
    str
        Multi-line text table of ranked files by risk.
    """
    ranked = rank_files_by_risk(lookback_days, limit=20)

    lines = [
        f"File Hotspot Report ({lookback_days} days)",
        "=" * 90,
        f"{'Rank':<5} {'Risk':>6} {'Level':<9} {'Blocks':>7} {'Edits':>6} "
        f"{'Churn':>6} {'ErrDen':>7}  File",
        "-" * 90,
    ]

    if not ranked:
        lines.append("  (no file blocks found in audit logs)")
    else:
        for r in ranked:
            # Shorten file path for display
            fp = r["file_path"]
            if len(fp) > 45:
                fp = "..." + fp[-42:]
            lines.append(
                f"{r['rank']:<5} {r['risk_score']:>6.1f} {r['risk_level']:<9} "
                f"{r['block_count']:>7} {r['edit_count']:>6} "
                f"{r['churn_factor']:>6.2f} {r['error_density']:>7.3f}  {fp}"
            )

    lines.append("-" * 90)

    critical = sum(1 for r in ranked if r["risk_level"] == "critical")
    high = sum(1 for r in ranked if r["risk_level"] == "high")
    if critical or high:
        lines.append(f"Critical: {critical}  |  High: {high}  |  Total ranked: {len(ranked)}")
    else:
        lines.append(f"Total ranked: {len(ranked)}  (no critical or high risk files)")

    lines.append("=" * 90)
    return "\n".join(lines)
