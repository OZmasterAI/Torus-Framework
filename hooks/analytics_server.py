#!/usr/bin/env python3
"""Torus Framework — Analytics MCP Server

Lightweight read-only MCP server exposing framework analytics as tool calls.
Wraps shared analytics modules (health_monitor, session_analytics, gate_dashboard,
gate_timing, anomaly_detector, metrics_collector, skill_health) so Claude and
subagents can query them directly instead of multi-line Bash Python scripts.

No ChromaDB, no embedding models — near-instant startup.

Run standalone: python3 analytics_server.py
Used via MCP: configured in .claude/mcp.json
"""

import functools
import glob as _glob
import os
import sys
import traceback

from mcp.server.fastmcp import FastMCP

# Ensure hooks/ is on sys.path so shared.* imports work
_HOOKS_DIR = os.path.dirname(__file__)
if _HOOKS_DIR not in sys.path:
    sys.path.insert(0, _HOOKS_DIR)

mcp = FastMCP("analytics")

# ── Crash-proof decorator ────────────────────────────────────────────────────

def crash_proof(fn):
    """Wrap MCP tool handler so exceptions return error dicts instead of crashing the server."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            tb = traceback.format_exc()
            print(f"[Analytics MCP] {fn.__name__} error: {e}\n{tb}", file=sys.stderr)
            return {"error": f"{fn.__name__} failed: {type(e).__name__}: {e}"}
    return wrapper


# ── Lazy import guard ────────────────────────────────────────────────────────

_initialized = False


def _ensure_initialized():
    """Lazy-import shared modules on first tool call."""
    global _initialized
    if _initialized:
        return
    # Imports are done inside each tool via this guard to keep startup fast.
    # The shared modules themselves handle their own path setup.
    _initialized = True


# ── Session auto-detection ───────────────────────────────────────────────────

def _detect_session_id() -> str:
    """Auto-detect the current session ID from the most recent state_*.json file.

    Checks ramdisk state directory first, then falls back to hooks/ directory.
    Returns the session_id extracted from the filename, or "default" if none found.
    """
    try:
        from shared.ramdisk import get_state_dir
        state_dir = get_state_dir()
    except Exception:
        state_dir = _HOOKS_DIR

    candidates = []

    # Check primary state dir
    for fpath in _glob.glob(os.path.join(state_dir, "state_*.json")):
        if fpath.endswith(".lock") or ".tmp." in fpath:
            continue
        basename = os.path.basename(fpath)
        sid = basename[len("state_"):-len(".json")]
        if sid.startswith("test-"):
            continue
        try:
            mtime = os.path.getmtime(fpath)
            candidates.append((mtime, sid))
        except OSError:
            continue

    # Also check hooks dir if different
    if state_dir != _HOOKS_DIR:
        for fpath in _glob.glob(os.path.join(_HOOKS_DIR, "state_*.json")):
            if fpath.endswith(".lock") or ".tmp." in fpath:
                continue
            basename = os.path.basename(fpath)
            sid = basename[len("state_"):-len(".json")]
            if sid.startswith("test-"):
                continue
            if any(s == sid for _, s in candidates):
                continue
            try:
                mtime = os.path.getmtime(fpath)
                candidates.append((mtime, sid))
            except OSError:
                continue

    if not candidates:
        return "default"

    # Return the session_id with the most recent mtime
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _resolve_session_id(session_id: str) -> str:
    """Resolve empty session_id to auto-detected value."""
    if session_id:
        return session_id
    return _detect_session_id()


def _import_search_fts(integration_name: str):
    """Import search_fts from an integration's db.py without module name collision."""
    import importlib.util
    db_path = os.path.join(
        os.path.expanduser("~"), ".claude", "integrations", integration_name, "db.py"
    )
    spec = importlib.util.spec_from_file_location(f"db_{integration_name}", db_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.search_fts


def _import_from_db(integration_name: str, func_name: str):
    """Import a named function from an integration's db.py."""
    import importlib.util
    db_path = os.path.join(
        os.path.expanduser("~"), ".claude", "integrations", integration_name, "db.py"
    )
    spec = importlib.util.spec_from_file_location(f"db_{integration_name}_{func_name}", db_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, func_name)


# ── Tools ────────────────────────────────────────────────────────────────────

@mcp.tool()
@crash_proof
def framework_health(session_id: str = "") -> dict:
    """Full framework health check: overall score 0-100, per-component status, degraded list, suggestions.

    Args:
        session_id: Session ID for state lookup. Empty string auto-detects current session.
    """
    _ensure_initialized()
    from shared.health_monitor import full_health_check
    sid = _resolve_session_id(session_id)
    return full_health_check(sid)


@mcp.tool()
@crash_proof
def session_summary(session_id: str = "") -> dict:
    """Session analytics: tool distribution, gate effectiveness, error rates, capture queue stats.

    Args:
        session_id: Session ID to analyze. Empty string uses the most recent session.
    """
    _ensure_initialized()
    from shared.session_analytics import get_session_summary
    sid = _resolve_session_id(session_id) if session_id else None
    return get_session_summary(session_id=sid)


@mcp.tool()
@crash_proof
def gate_dashboard() -> dict:
    """Gate effectiveness dashboard: ranked gates, block rates, coverage, recommendations.

    Returns dashboard text, ranked gates with metrics, and actionable recommendations.
    """
    _ensure_initialized()
    from shared.gate_dashboard import render_dashboard, get_recommendations, rank_gates_by_value
    from dataclasses import asdict

    dashboard_text = render_dashboard()
    recommendations = get_recommendations()
    ranked = rank_gates_by_value()

    ranked_dicts = [
        {"gate": gate_key, **asdict(metrics)}
        for gate_key, metrics in ranked
    ]

    return {
        "dashboard": dashboard_text,
        "ranked_gates": ranked_dicts,
        "recommendations": recommendations,
    }


@mcp.tool()
@crash_proof
def gate_timing(gate_name: str = "") -> dict:
    """Gate execution timing: per-gate latency stats, slow gates, formatted report.

    Args:
        gate_name: Specific gate to query (e.g. "gate_01_read_before_edit").
                   Empty string returns all gates.
    """
    _ensure_initialized()
    from shared.gate_timing import get_gate_stats, get_slow_gates, get_timing_report

    stats = get_gate_stats(gate_name if gate_name else None)
    slow = get_slow_gates()
    report = get_timing_report()

    return {
        "stats": stats,
        "slow_gates": slow,
        "report": report,
    }


@mcp.tool()
@crash_proof
def detect_anomalies(session_id: str = "") -> dict:
    """Detect behavioral anomalies: tool call bursts, high block rates, error spikes, memory gaps.

    Args:
        session_id: Session ID to analyze. Empty string auto-detects current session.
    """
    _ensure_initialized()
    from shared.anomaly_detector import detect_behavioral_anomaly
    from shared.state import load_state

    sid = _resolve_session_id(session_id)
    state = load_state(session_id=sid)

    anomalies = detect_behavioral_anomaly(state)

    return {
        "session_id": sid,
        "anomaly_count": len(anomalies),
        "anomalies": [
            {"type": atype, "severity": severity, "description": desc}
            for atype, severity, desc in anomalies
        ],
    }


@mcp.tool()
@crash_proof
def skill_health() -> dict:
    """Skill health check: total/healthy/broken counts, errors, script issues.

    Scans all skills in the skills/ directory and validates structure and scripts.
    """
    _ensure_initialized()
    from shared.skill_health import check_all_skills
    return check_all_skills()


@mcp.tool()
@crash_proof
def all_metrics() -> dict:
    """Current framework metrics plus 1-minute and 5-minute rollups.

    Returns counters, gauges, and histograms from gates, hooks, memory, and sessions.
    """
    _ensure_initialized()
    from shared.metrics_collector import get_all_metrics, rollup

    current = get_all_metrics()
    rollup_1m = rollup(60)
    rollup_5m = rollup(300)

    return {
        "current": current,
        "rollup_1m": rollup_1m,
        "rollup_5m": rollup_5m,
    }


# ── Search Tools ──────────────────────────────────────────────────────────────

# DORMANT: uncomment @mcp.tool() to reactivate
# @mcp.tool()
@crash_proof
def telegram_search(query: str, limit: int = 10) -> dict:
    """Search Telegram message history via FTS5 full-text search.

    Args:
        query: Search query (FTS5 MATCH syntax). Empty returns no results.
        limit: Max results to return (1-50, default 10).
    """
    if not query or not query.strip():
        return {"results": [], "count": 0, "source": "telegram_fts"}

    limit = max(1, min(50, limit))
    search_fts = _import_search_fts("telegram-bot")
    db_path = os.path.join(
        os.path.expanduser("~"), ".claude", "integrations", "telegram-bot", "msg_log.db"
    )
    results = search_fts(db_path, query, limit=limit)
    return {"results": results, "count": len(results), "source": "telegram_fts"}


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
