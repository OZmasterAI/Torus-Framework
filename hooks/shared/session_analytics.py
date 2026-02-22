"""Session analytics for the Torus self-healing framework.

Analyses session patterns over time from multiple data sources:
- JSONL audit logs (hooks/audit/*.jsonl)
- Gate effectiveness counters (.gate_effectiveness.json)
- Observation capture queue (.capture_queue.jsonl)
- Per-session state files (state_<session_id>.json)

Public API:
  get_session_summary(session_id=None) -> Dict
      Returns a rich dict of per-session (or aggregate) metrics drawn from
      gate_effectiveness.json, capture_queue.jsonl, and state files.
  compare_sessions(session_a, session_b) -> Dict
      Returns field-by-field deltas between two session IDs (string IDs).
      Pass dicts directly to use the legacy compare_sessions_metrics() API.
  analyse_session(...)
      Full audit-log-based analysis (original API, preserved).

Audit log entries are JSONL with keys:
  id, timestamp, gate, tool, decision, reason, session_id, state_keys, severity
"""

import gzip
import json
import math
import os
import re
import glob as _glob
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


# ── File-system paths ────────────────────────────────────────────────────────

_HOOKS_DIR = os.path.join(os.path.expanduser("~"), ".claude", "hooks")
_GATE_EFFECTIVENESS_FILE = os.path.join(_HOOKS_DIR, ".gate_effectiveness.json")
_CAPTURE_QUEUE_FILE = os.path.join(_HOOKS_DIR, ".capture_queue.jsonl")

# State files live on the ramdisk when available, otherwise on disk
try:
    from shared.ramdisk import get_state_dir
    _STATE_DIR = get_state_dir()
except Exception:
    _STATE_DIR = _HOOKS_DIR


# ── Low-level data loaders ───────────────────────────────────────────────────


def _load_gate_effectiveness() -> Dict[str, Dict[str, int]]:
    """Load the persistent gate effectiveness counters.

    Reads ~/.claude/hooks/.gate_effectiveness.json.

    Returns:
        Dict mapping gate_name -> {"blocks": N, "overrides": N, "prevented": N}.
        Empty dict if file is missing or malformed.

    Example::

        {
          "gate_01_read_before_edit": {"blocks": 2211, "overrides": 0, "prevented": 1},
          "gate_04_memory_first":     {"blocks": 327,  "overrides": 0, "prevented": 1},
        }
    """
    try:
        with open(_GATE_EFFECTIVENESS_FILE) as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except (IOError, OSError, json.JSONDecodeError):
        pass
    return {}


def _load_capture_queue(max_entries: int = 5000) -> List[Dict]:
    """Load observation entries from the capture queue JSONL.

    Reads ~/.claude/hooks/.capture_queue.jsonl.  Each line is a JSON object
    with at minimum a "metadata" dict containing "session_id", "tool_name",
    "timestamp", "sentiment", "has_error", and "exit_code".

    Args:
        max_entries: Maximum number of lines to read (tail of file).

    Returns:
        List of entry dicts; empty list on any I/O error.
    """
    entries: List[Dict] = []
    try:
        with open(_CAPTURE_QUEUE_FILE, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        # Take the tail if there are more lines than max_entries
        if len(lines) > max_entries:
            lines = lines[-max_entries:]
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    entries.append(obj)
            except json.JSONDecodeError:
                continue
    except (IOError, OSError):
        pass
    return entries


def _load_all_state_files() -> Dict[str, Dict]:
    """Enumerate and load all per-session state JSON files.

    Checks the ramdisk state directory first, then the disk fallback.
    Silently skips files that cannot be parsed.

    Returns:
        Dict mapping session_id -> state_dict.  The session_id is derived
        from the filename (state_<session_id>.json).
    """
    result: Dict[str, Dict] = {}
    dirs_to_check = [_STATE_DIR]
    # Always include the disk directory in case ramdisk != disk
    disk_dir = _HOOKS_DIR
    if disk_dir != _STATE_DIR:
        dirs_to_check.append(disk_dir)

    seen_sessions: set = set()
    for directory in dirs_to_check:
        pattern = os.path.join(directory, "state_*.json")
        for fpath in _glob.glob(pattern):
            # Skip lock and tmp files
            if fpath.endswith(".lock") or ".tmp." in fpath:
                continue
            basename = os.path.basename(fpath)
            # Extract session_id from filename: state_<session_id>.json
            session_id = basename[len("state_"):-len(".json")]
            if session_id in seen_sessions:
                continue  # ramdisk copy takes precedence
            try:
                with open(fpath) as fh:
                    state = json.load(fh)
                if isinstance(state, dict):
                    result[session_id] = state
                    seen_sessions.add(session_id)
            except (IOError, OSError, json.JSONDecodeError):
                continue
    return result


def _state_session_metrics(session_id: str, state: Dict) -> Dict[str, Any]:
    """Extract per-session metric fields from a loaded state dict.

    Args:
        session_id: The session identifier string.
        state:      The loaded state dict.

    Returns:
        A flat metrics dict with the following keys:

        session_id          - str
        session_start       - float (Unix timestamp)
        session_start_iso   - str (ISO 8601)
        duration_minutes    - float (minutes since session_start; 0 if not started)
        total_tool_calls    - int
        tool_distribution   - dict {tool_name: count}
        blocks_this_session - int  (sum of gate_effectiveness blocks added since start)
        warnings_this_session - int (gate6_warn_count)
        files_read_count    - int
        files_edited_count  - int
        memory_queries      - int  (from tool_call_counts for memory search tools)
        memory_saves        - int  (from tool_call_counts for remember_this)
        gate_effectiveness  - dict (gate_effectiveness field, may be empty)
        security_profile    - str
        pending_verification_count - int
        active_bans_count   - int
        subagent_count      - int
        auto_remember_count - int
        last_test_exit_code - int or None
    """
    now = time.time()
    session_start = float(state.get("session_start", 0))
    duration_minutes = (now - session_start) / 60.0 if session_start > 0 else 0.0

    tool_counts: Dict[str, int] = state.get("tool_call_counts", {})
    total_calls = int(state.get("total_tool_calls", 0)) or sum(tool_counts.values())

    # Memory tool names used in state tracking
    _MEM_SEARCH_TOOLS = {
        "mcp__memory__search_knowledge", "search_knowledge",
    }
    _MEM_SAVE_TOOLS = {
        "mcp__memory__remember_this", "remember_this",
    }
    memory_queries = sum(v for k, v in tool_counts.items() if k in _MEM_SEARCH_TOOLS)
    memory_saves = sum(v for k, v in tool_counts.items() if k in _MEM_SAVE_TOOLS)

    iso_start = ""
    if session_start > 0:
        try:
            iso_start = datetime.fromtimestamp(session_start, tz=timezone.utc).isoformat()
        except (OSError, ValueError, OverflowError):
            pass

    bans = state.get("active_bans", {})
    bans_count = len(bans) if isinstance(bans, dict) else 0

    subagents = state.get("active_subagents", [])
    subagent_count = len(subagents) if isinstance(subagents, list) else 0

    return {
        "session_id": session_id,
        "session_start": session_start,
        "session_start_iso": iso_start,
        "duration_minutes": round(duration_minutes, 2),
        "total_tool_calls": total_calls,
        "tool_distribution": dict(tool_counts),
        "warnings_this_session": int(state.get("gate6_warn_count", 0)),
        "files_read_count": len(state.get("files_read", [])),
        "files_edited_count": len(state.get("files_edited", [])),
        "memory_queries": memory_queries,
        "memory_saves": memory_saves,
        "gate_effectiveness": state.get("gate_effectiveness", {}),
        "security_profile": state.get("security_profile", "balanced"),
        "pending_verification_count": len(state.get("pending_verification", [])),
        "active_bans_count": bans_count,
        "subagent_count": subagent_count,
        "auto_remember_count": int(state.get("auto_remember_count", 0)),
        "last_test_exit_code": state.get("last_test_exit_code"),
    }


# ── get_session_summary ──────────────────────────────────────────────────────


def get_session_summary(
    session_id: Optional[str] = None,
    include_capture_queue: bool = True,
) -> Dict[str, Any]:
    """Return a consolidated per-session (or aggregate) metrics snapshot.

    Data is pulled from three sources:

    1. **.gate_effectiveness.json** — cumulative gate fire/block/prevented counts
       across all sessions (since these are never reset).
    2. **.capture_queue.jsonl** — observation entries; used for sentiment
       distribution, error-rate, and per-session tool call counts derived
       from the queue metadata.
    3. **state_<session_id>.json** — per-session state; used for tool_distribution,
       total_tool_calls, warnings, files read/edited, memory usage, etc.

    Args:
        session_id:
            If given, restrict state-file and capture-queue metrics to this
            session only.  Pass ``None`` to return aggregate figures across all
            live sessions.
        include_capture_queue:
            Whether to parse the capture queue (can be slow for large queues).
            Defaults to True.

    Returns:
        Dict with the following top-level keys:

        session_id (str|None)
            The queried session ID, or None for aggregate.

        state (dict|None)
            Extracted metrics from the session state file.  Contains:
            total_tool_calls, tool_distribution, warnings_this_session,
            files_read_count, files_edited_count, memory_queries, memory_saves,
            gate_effectiveness, security_profile, pending_verification_count,
            active_bans_count, subagent_count, auto_remember_count,
            last_test_exit_code, duration_minutes, session_start_iso.
            ``None`` if no matching state file found.

        all_sessions (list[dict])
            List of state-metric dicts for every discovered session (only
            populated when session_id is None).

        gate_effectiveness (dict)
            Cumulative gate effectiveness counters from the persistent JSON
            file.  Keys are gate names; values are {blocks, overrides,
            prevented}.

        top_fired_gates (list[dict])
            Top 10 gates by block count from gate_effectiveness, each entry:
            {"gate": str, "blocks": int, "overrides": int, "prevented": int}.

        capture_queue_stats (dict)
            Metrics derived from capture queue entries for the target session
            (or all sessions when session_id is None):

            entry_count    - total observations in queue (scoped to session)
            tool_distribution - {tool_name: count} from queue metadata
            error_rate     - fraction of entries with has_error == "true"
            sentiment_counts - {sentiment_label: count}
            sessions_in_queue - number of distinct session IDs in queue

            Populated as an empty dict when ``include_capture_queue=False``.

        blocks_total (int)
            Total blocks across all gates from gate_effectiveness.

        generated_at (str)
            ISO 8601 timestamp of when this summary was generated.
    """
    now = time.time()
    generated_at = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()

    # --- 1. Gate effectiveness (global, cumulative) ---
    gate_eff = _load_gate_effectiveness()
    blocks_total = sum(v.get("blocks", 0) for v in gate_eff.values())

    # Top-fired gates sorted by blocks descending
    sorted_gates = sorted(
        [
            {
                "gate": gname,
                "blocks": gdata.get("blocks", 0),
                "overrides": gdata.get("overrides", 0),
                "prevented": gdata.get("prevented", 0),
            }
            for gname, gdata in gate_eff.items()
        ],
        key=lambda x: x["blocks"],
        reverse=True,
    )[:10]

    # --- 2. State files ---
    all_states = _load_all_state_files()
    all_session_metrics: List[Dict] = []
    for sid, sdata in all_states.items():
        # Skip test fixtures (state_test-* files)
        if sid.startswith("test-"):
            continue
        all_session_metrics.append(_state_session_metrics(sid, sdata))

    # Find the specific session if requested
    target_state_metrics: Optional[Dict] = None
    if session_id is not None:
        target_state = all_states.get(session_id)
        if target_state is not None:
            target_state_metrics = _state_session_metrics(session_id, target_state)
    else:
        # For aggregate, pick the most recently started session as "current"
        if all_session_metrics:
            target_state_metrics = max(
                all_session_metrics, key=lambda m: m["session_start"]
            )

    # --- 3. Capture queue ---
    cq_stats: Dict[str, Any] = {}
    if include_capture_queue:
        queue_entries = _load_capture_queue()
        if session_id:
            scoped = [
                e for e in queue_entries
                if e.get("metadata", {}).get("session_id") == session_id
            ]
        else:
            scoped = queue_entries

        tool_ctr: Counter = Counter()
        sentiment_ctr: Counter = Counter()
        error_count = 0
        distinct_sessions: set = set()
        for entry in scoped:
            meta = entry.get("metadata", {})
            tool_name = meta.get("tool_name", "unknown")
            if tool_name:
                tool_ctr[tool_name] += 1
            sentiment = meta.get("sentiment", "neutral")
            if sentiment:
                sentiment_ctr[sentiment] += 1
            if meta.get("has_error", "false") == "true":
                error_count += 1
            sid_ = meta.get("session_id", "")
            if sid_:
                distinct_sessions.add(sid_)

        total_scoped = len(scoped)
        cq_stats = {
            "entry_count": total_scoped,
            "tool_distribution": dict(tool_ctr.most_common()),
            "error_rate": round(error_count / total_scoped, 4) if total_scoped else 0.0,
            "sentiment_counts": dict(sentiment_ctr.most_common()),
            "sessions_in_queue": len(distinct_sessions),
        }

    return {
        "session_id": session_id,
        "state": target_state_metrics,
        "all_sessions": all_session_metrics if session_id is None else [],
        "gate_effectiveness": gate_eff,
        "top_fired_gates": sorted_gates,
        "capture_queue_stats": cq_stats,
        "blocks_total": blocks_total,
        "generated_at": generated_at,
    }


# ── compare_sessions ─────────────────────────────────────────────────────────


def compare_sessions(
    session_a: Any,
    session_b: Any,
    window: int = 10,
) -> Dict[str, Any]:
    """Compare two sessions and return field-by-field deltas.

    Two calling conventions are supported:

    **Session-ID mode** (new):
        Pass two session-ID strings.  State files are loaded from disk/ramdisk,
        metrics are extracted, and deltas are computed.

        Example::

            compare_sessions("0eae7019-...", "83f262b3-...")

    **Legacy metrics-dict mode** (backward-compatible):
        Pass a metrics dict as ``session_a`` and a list of historical dicts
        as ``session_b``.  Delegates to :func:`compare_sessions_metrics`.

        Example::

            compare_sessions(current_metrics_dict, [hist1, hist2, ...])

    Args:
        session_a: Session ID string, or current-session metrics dict.
        session_b: Session ID string, or list of historical metrics dicts.
        window:    Rolling window for legacy mode (default 10).

    Returns:
        In session-ID mode:

        Dict with keys:
          - session_a_id:     str
          - session_b_id:     str
          - session_a_metrics: dict  (state metrics for session A)
          - session_b_metrics: dict  (state metrics for session B)
          - deltas:           dict  {field: {"a": val_a, "b": val_b, "delta": b - a}}
            Numeric fields compared: total_tool_calls, warnings_this_session,
            files_read_count, files_edited_count, memory_queries, memory_saves,
            pending_verification_count, active_bans_count, subagent_count,
            auto_remember_count, duration_minutes.
          - gate_effectiveness_delta: dict {gate: {"a_blocks": N, "b_blocks": N, "delta": N}}
            (uses state.gate_effectiveness if present; otherwise empty)
          - summary: str  Human-readable one-liner.

        In legacy mode: result of compare_sessions_metrics().
    """
    # Detect legacy mode: session_b is a list (of history dicts)
    if isinstance(session_b, list):
        return compare_sessions_metrics(session_a, session_b, window=window)

    # Session-ID mode
    sid_a = str(session_a)
    sid_b = str(session_b)

    all_states = _load_all_state_files()

    def _get_metrics(sid: str) -> Optional[Dict]:
        state = all_states.get(sid)
        if state is None:
            return None
        return _state_session_metrics(sid, state)

    m_a = _get_metrics(sid_a)
    m_b = _get_metrics(sid_b)

    _NUMERIC_FIELDS = [
        "total_tool_calls",
        "warnings_this_session",
        "files_read_count",
        "files_edited_count",
        "memory_queries",
        "memory_saves",
        "pending_verification_count",
        "active_bans_count",
        "subagent_count",
        "auto_remember_count",
        "duration_minutes",
    ]

    deltas: Dict[str, Dict] = {}
    if m_a is not None and m_b is not None:
        for field in _NUMERIC_FIELDS:
            val_a = m_a.get(field, 0) or 0
            val_b = m_b.get(field, 0) or 0
            try:
                delta = round(float(val_b) - float(val_a), 4)
            except (TypeError, ValueError):
                delta = None
            deltas[field] = {"a": val_a, "b": val_b, "delta": delta}

    # Gate-level delta (from state.gate_effectiveness, which is per-session not global)
    gate_eff_delta: Dict[str, Dict] = {}
    if m_a is not None and m_b is not None:
        ge_a: Dict = m_a.get("gate_effectiveness", {})
        ge_b: Dict = m_b.get("gate_effectiveness", {})
        all_gates = set(ge_a.keys()) | set(ge_b.keys())
        for gate in sorted(all_gates):
            a_blocks = ge_a.get(gate, {}).get("blocks", 0)
            b_blocks = ge_b.get(gate, {}).get("blocks", 0)
            gate_eff_delta[gate] = {
                "a_blocks": a_blocks,
                "b_blocks": b_blocks,
                "delta": b_blocks - a_blocks,
            }

    # Build human-readable summary
    if m_a is None and m_b is None:
        summary = f"Neither session '{sid_a}' nor '{sid_b}' found."
    elif m_a is None:
        summary = f"Session '{sid_a}' not found; session '{sid_b}' has {m_b.get('total_tool_calls', 0)} tool calls."
    elif m_b is None:
        summary = f"Session '{sid_b}' not found; session '{sid_a}' has {m_a.get('total_tool_calls', 0)} tool calls."
    else:
        call_delta = deltas.get("total_tool_calls", {}).get("delta", 0)
        sign = "+" if call_delta >= 0 else ""
        summary = (
            f"Session '{sid_b}' vs '{sid_a}': "
            f"{sign}{call_delta} tool calls, "
            f"{sign}{deltas.get('memory_queries', {}).get('delta', 0)} memory queries, "
            f"{sign}{deltas.get('warnings_this_session', {}).get('delta', 0)} warnings."
        )

    return {
        "session_a_id": sid_a,
        "session_b_id": sid_b,
        "session_a_metrics": m_a,
        "session_b_metrics": m_b,
        "deltas": deltas,
        "gate_effectiveness_delta": gate_eff_delta,
        "summary": summary,
    }

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


def compare_sessions_metrics(
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
