"""Session analytics for the Torus self-healing framework.

Analyses session patterns over time from JSONL audit logs:
- Tool call frequency distribution per session
- Gate fire rate trends and spike detection
- Error frequency and recurring pattern identification
- Session productivity scoring
- Trend comparison against rolling history

Audit log entries are JSONL with keys:
  id, timestamp, gate, tool, decision, reason, session_id, state_keys, severity
"""

import gzip
import json
import math
import os
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple


# ── Audit log directory ──────────────────────────────────────────────────────

_DEFAULT_AUDIT_DIR = os.path.join(
    os.path.expanduser("~"), ".claude", "hooks", "audit"
)


# ── Parsing ──────────────────────────────────────────────────────────────────


def parse_audit_log(log_path: str) -> List[Dict]:
    """Parse a JSONL audit log file into a list of entry dicts.

    Handles both plain .jsonl files and gzip-compressed .jsonl.gz files.
    Silently skips malformed lines.

    Args:
        log_path: Absolute path to the JSONL (or .jsonl.gz) audit file.

    Returns:
        List of dicts, one per valid JSON line.  Empty list on any I/O error.
    """
    entries: List[Dict] = []
    try:
        if log_path.endswith(".gz"):
            opener = lambda p: gzip.open(p, "rt", encoding="utf-8", errors="replace")
        else:
            opener = lambda p: open(p, "r", encoding="utf-8", errors="replace")

        with opener(log_path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if isinstance(entry, dict):
                        entries.append(entry)
                except json.JSONDecodeError:
                    continue
    except (IOError, OSError, gzip.BadGzipFile):
        pass
    return entries


def parse_audit_dir(
    audit_dir: str = _DEFAULT_AUDIT_DIR,
    max_files: int = 30,
) -> List[Dict]:
    """Parse all JSONL audit files in a directory (most recent first).

    Args:
        audit_dir: Path to the audit directory.
        max_files: Maximum number of files to read (oldest are skipped).

    Returns:
        Combined list of entries from all processed files, chronological order.
    """
    if not os.path.isdir(audit_dir):
        return []

    files = []
    for fname in os.listdir(audit_dir):
        if fname.endswith(".jsonl") or fname.endswith(".jsonl.gz"):
            fpath = os.path.join(audit_dir, fname)
            try:
                mtime = os.path.getmtime(fpath)
                files.append((mtime, fpath))
            except OSError:
                continue

    # Sort ascending by mtime so chronological order is preserved
    files.sort(key=lambda t: t[0])
    files = files[-max_files:]  # keep newest N

    all_entries: List[Dict] = []
    for _, fpath in files:
        all_entries.extend(parse_audit_log(fpath))
    return all_entries


# ── Core metric functions ────────────────────────────────────────────────────


def tool_call_distribution(entries: List[Dict]) -> Dict[str, int]:
    """Compute how often each tool was called in the given entries.

    Args:
        entries: List of audit log entry dicts.

    Returns:
        Dict mapping tool_name -> call count, sorted descending.
    """
    counts: Counter = Counter()
    for entry in entries:
        tool = entry.get("tool") or entry.get("tool_name")
        if tool and isinstance(tool, str):
            counts[tool] += 1
    return dict(counts.most_common())


def gate_fire_rates(entries: List[Dict]) -> Dict[str, int]:
    """Count how many times each gate fired (any decision) across entries.

    Args:
        entries: List of audit log entry dicts.

    Returns:
        Dict mapping gate_name -> total fire count, sorted descending.
    """
    counts: Counter = Counter()
    for entry in entries:
        gate = entry.get("gate") or entry.get("gate_name")
        if gate and isinstance(gate, str):
            counts[gate] += 1
    return dict(counts.most_common())


def gate_block_rates(entries: List[Dict]) -> Dict[str, Dict[str, int]]:
    """Break down gate decisions into pass / warn / block counts.

    Args:
        entries: List of audit log entry dicts.

    Returns:
        Dict mapping gate_name -> {"pass": N, "warn": N, "block": N, "total": N}.
    """
    result: Dict[str, Dict[str, int]] = {}
    for entry in entries:
        gate = entry.get("gate") or entry.get("gate_name")
        decision = entry.get("decision", "unknown")
        if not gate or not isinstance(gate, str):
            continue
        if gate not in result:
            result[gate] = {"pass": 0, "warn": 0, "block": 0, "total": 0}
        if decision in ("pass", "warn", "block"):
            result[gate][decision] += 1
        result[gate]["total"] += 1
    return result


def error_frequency(entries: List[Dict]) -> Dict[str, int]:
    """Count recurring error patterns extracted from blocked/warn reasons.

    Normalises reason strings into coarse buckets so similar messages are
    grouped together (e.g. all "must Read … before editing" blocks share a
    key regardless of the specific file path involved).

    Args:
        entries: List of audit log entry dicts.

    Returns:
        Dict mapping normalised error pattern -> occurrence count, sorted desc.
    """
    # Patterns: (compiled_regex, canonical_label)
    _PATTERNS: List[Tuple] = [
        (re.compile(r"must Read .* before editing", re.I), "gate1:read-before-edit"),
        (re.compile(r"NO DESTROY.*blocked", re.I), "gate2:no-destroy"),
        (re.compile(r"rm\s*-rf|DROP TABLE|reset --hard|force.?push", re.I), "gate2:destructive-op"),
        (re.compile(r"deploy.*no tests|tests.*before deploy", re.I), "gate3:deploy-without-tests"),
        (re.compile(r"memory.*queried|query.*memory", re.I), "gate4:memory-first"),
        (re.compile(r"verify.*before|proof.*fixed|evidence.*fix", re.I), "gate5:proof-needed"),
        (re.compile(r"save.*memory|remember.*fix", re.I), "gate6:save-to-memory"),
        (re.compile(r"critical file|high.?risk file", re.I), "gate7:critical-file"),
        (re.compile(r"rate limit|too many tool calls|runaway", re.I), "gate11:rate-limit"),
        (re.compile(r"workspace.*claimed|file.*locked|concurrent edit", re.I), "gate13:workspace"),
        (re.compile(r"test.*fail|exit code [^0]", re.I), "test-failure"),
        (re.compile(r"traceback|exception|error:", re.I), "python-exception"),
        (re.compile(r"permission denied", re.I), "permission-denied"),
        (re.compile(r"file not found|no such file", re.I), "file-not-found"),
    ]

    counts: Counter = Counter()
    for entry in entries:
        decision = entry.get("decision", "pass")
        if decision not in ("block", "warn"):
            continue
        reason = entry.get("reason", "")
        if not reason or not isinstance(reason, str):
            continue
        matched = False
        for pattern, label in _PATTERNS:
            if pattern.search(reason):
                counts[label] += 1
                matched = True
                break
        if not matched:
            counts["other-block-or-warn"] += 1

    return dict(counts.most_common())


# ── Productivity scoring ─────────────────────────────────────────────────────


def session_productivity(
    entries: List[Dict],
    duration_minutes: float,
) -> Dict:
    """Compute a productivity score for the session represented by entries.

    Score is 0.0–100.0, built from four sub-metrics:

    1. edit_velocity   — Write/Edit/NotebookEdit calls per hour (capped at 30/h -> 25 pts)
    2. block_rate      — Fraction of gate checks that were NOT blocked (0-1 -> 25 pts)
    3. error_resolve   — Proportion of blocked decisions followed by a pass on the
                         same gate within the next 10 entries (0-1 -> 25 pts)
    4. memory_contrib  — search_knowledge + remember_this calls (capped 10 -> 25 pts)

    Args:
        entries:          Audit log entries for the session.
        duration_minutes: Session length in minutes (must be > 0).

    Returns:
        Dict with keys:
          - score: float  (0.0–100.0)
          - breakdown: dict with individual sub-scores and raw values
          - grade: str    ("A"–"F")
    """
    if duration_minutes <= 0:
        duration_minutes = 1.0

    hours = duration_minutes / 60.0

    # --- 1. edit_velocity (files modified per hour) ---
    edit_tools = {"Edit", "Write", "NotebookEdit"}
    edit_count = sum(
        1 for e in entries
        if (e.get("tool") or e.get("tool_name", "")) in edit_tools
        and e.get("decision", "pass") == "pass"
    )
    edits_per_hour = edit_count / hours
    edit_score = min(25.0, (edits_per_hour / 30.0) * 25.0)

    # --- 2. block_rate (lower blocks = better) ---
    total_decisions = len(entries)
    blocked = sum(1 for e in entries if e.get("decision") == "block")
    if total_decisions > 0:
        pass_fraction = (total_decisions - blocked) / total_decisions
    else:
        pass_fraction = 1.0
    block_score = pass_fraction * 25.0

    # --- 3. error_resolve (blocked -> pass recovery rate) ---
    resolve_score = _compute_resolve_score(entries) * 25.0

    # --- 4. memory_contrib ---
    memory_tools = {"mcp__memory__search_knowledge", "mcp__memory__remember_this",
                    "search_knowledge", "remember_this"}
    # In audit logs, memory tool calls appear as the tool name
    memory_calls = sum(
        1 for e in entries
        if (e.get("tool") or e.get("tool_name", "")) in memory_tools
    )
    memory_score = min(25.0, (memory_calls / 10.0) * 25.0)

    total_score = round(edit_score + block_score + resolve_score + memory_score, 2)

    grade_map = [
        (90, "A"), (80, "B"), (70, "C"), (60, "D"),
    ]
    grade = "F"
    for threshold, letter in grade_map:
        if total_score >= threshold:
            grade = letter
            break

    return {
        "score": total_score,
        "grade": grade,
        "breakdown": {
            "edit_velocity": {
                "raw_edits_per_hour": round(edits_per_hour, 2),
                "sub_score": round(edit_score, 2),
                "max": 25,
            },
            "block_rate": {
                "pass_fraction": round(pass_fraction, 4),
                "blocked_count": blocked,
                "total_decisions": total_decisions,
                "sub_score": round(block_score, 2),
                "max": 25,
            },
            "error_resolve": {
                "resolve_rate": round(resolve_score / 25.0, 4),
                "sub_score": round(resolve_score, 2),
                "max": 25,
            },
            "memory_contrib": {
                "memory_calls": memory_calls,
                "sub_score": round(memory_score, 2),
                "max": 25,
            },
        },
    }


def _compute_resolve_score(entries: List[Dict]) -> float:
    """Fraction of blocked gate events that recovered (pass) within 10 entries.

    Returns a float in [0.0, 1.0].  Returns 1.0 if there were no blocks
    (no errors to resolve -> perfect).
    """
    blocked_indices = [
        i for i, e in enumerate(entries) if e.get("decision") == "block"
    ]
    if not blocked_indices:
        return 1.0

    resolved = 0
    for idx in blocked_indices:
        gate = entries[idx].get("gate") or entries[idx].get("gate_name", "")
        # Look ahead up to 10 entries for a pass on the same gate
        window_end = min(len(entries), idx + 11)
        for j in range(idx + 1, window_end):
            e2 = entries[j]
            e2_gate = e2.get("gate") or e2.get("gate_name", "")
            if e2_gate == gate and e2.get("decision") == "pass":
                resolved += 1
                break

    return resolved / len(blocked_indices)


# ── Trend / comparison ───────────────────────────────────────────────────────


def compare_sessions(
    current: Dict,
    history: List[Dict],
    window: int = 10,
) -> Dict:
    """Compare current session metrics against rolling average of past sessions.

    Both `current` and each item in `history` should be productivity dicts as
    returned by `session_productivity()`, or at minimum contain a "score" key.

    Args:
        current: Metrics dict for the current session.
        history: List of metrics dicts for past sessions (oldest first).
        window:  Rolling window size for averaging (default 10).

    Returns:
        Dict with keys:
          - current_score: float
          - rolling_avg:   float (average score over the last `window` sessions)
          - delta:         float (current - rolling_avg)
          - trend:         "improving" | "declining" | "stable" | "insufficient_data"
          - spike_detected: bool (True if |delta| > 2 * rolling_stddev)
          - rolling_stddev: float
          - gate_trends:   dict mapping gate -> {"avg_fires": float, "current_fires": int, "delta": float}
    """
    recent = history[-window:]

    current_score = float(current.get("score", 0.0))

    if not recent:
        return {
            "current_score": current_score,
            "rolling_avg": 0.0,
            "delta": 0.0,
            "trend": "insufficient_data",
            "spike_detected": False,
            "rolling_stddev": 0.0,
            "gate_trends": {},
        }

    past_scores = [float(h.get("score", 0.0)) for h in recent]
    rolling_avg = sum(past_scores) / len(past_scores)
    rolling_stddev = _stddev(past_scores)
    delta = current_score - rolling_avg

    spike_detected = (rolling_stddev > 0) and (abs(delta) > 2 * rolling_stddev)

    if len(past_scores) < 2:
        trend = "insufficient_data"
    elif delta > 5.0:
        trend = "improving"
    elif delta < -5.0:
        trend = "declining"
    else:
        trend = "stable"

    # Gate-level trends (requires gate_fires key in each metrics dict)
    gate_trends = _compare_gate_trends(current, recent)

    return {
        "current_score": current_score,
        "rolling_avg": round(rolling_avg, 2),
        "delta": round(delta, 2),
        "trend": trend,
        "spike_detected": spike_detected,
        "rolling_stddev": round(rolling_stddev, 2),
        "gate_trends": gate_trends,
    }


def _stddev(values: List[float]) -> float:
    """Population standard deviation."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    return math.sqrt(sum((v - mean) ** 2 for v in values) / n)


def _compare_gate_trends(current: Dict, history: List[Dict]) -> Dict[str, Dict]:
    """Build per-gate trend dicts from gate_fires sub-dict (if present)."""
    current_fires: Dict[str, int] = current.get("gate_fires", {})
    if not current_fires:
        return {}

    # Collect all gate names across history
    all_gates: set = set(current_fires.keys())
    for h in history:
        all_gates.update(h.get("gate_fires", {}).keys())

    trends = {}
    n = len(history)
    for gate in sorted(all_gates):
        past_values = [float(h.get("gate_fires", {}).get(gate, 0)) for h in history]
        avg = sum(past_values) / n if n > 0 else 0.0
        cur = float(current_fires.get(gate, 0))
        trends[gate] = {
            "avg_fires": round(avg, 2),
            "current_fires": int(cur),
            "delta": round(cur - avg, 2),
        }

    return trends


# ── High-level convenience API ────────────────────────────────────────────────


def analyse_session(
    session_id: Optional[str] = None,
    audit_dir: str = _DEFAULT_AUDIT_DIR,
    duration_minutes: float = 60.0,
    history_sessions: Optional[List[Dict]] = None,
) -> Dict:
    """Full session analysis in a single call.

    Reads all available audit logs, optionally filters to a single session_id,
    computes all metrics, and returns a combined report.

    Args:
        session_id:        If given, filter entries to this session only.
        audit_dir:         Directory containing JSONL audit files.
        duration_minutes:  Session duration for productivity scoring.
        history_sessions:  Optional list of past session metric dicts for trend
                           comparison.  If None, trend comparison is skipped.

    Returns:
        Dict with keys:
          - tool_distribution: dict
          - gate_fire_rates:   dict
          - gate_block_rates:  dict
          - error_frequency:   dict
          - productivity:      dict (from session_productivity)
          - trend:             dict (from compare_sessions) or None
          - entry_count:       int
          - session_id:        str or None
    """
    all_entries = parse_audit_dir(audit_dir)

    if session_id:
        entries = [e for e in all_entries if e.get("session_id") == session_id]
    else:
        entries = all_entries

    productivity = session_productivity(entries, duration_minutes)
    # Attach gate fire counts for trend comparison
    productivity["gate_fires"] = gate_fire_rates(entries)

    trend = None
    if history_sessions is not None:
        trend = compare_sessions(productivity, history_sessions)

    return {
        "tool_distribution": tool_call_distribution(entries),
        "gate_fire_rates": gate_fire_rates(entries),
        "gate_block_rates": gate_block_rates(entries),
        "error_frequency": error_frequency(entries),
        "productivity": productivity,
        "trend": trend,
        "entry_count": len(entries),
        "session_id": session_id,
    }
