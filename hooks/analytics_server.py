#!/usr/bin/env python3
"""Torus Framework — Analytics MCP Server

Lightweight read-only MCP server exposing framework analytics as tool calls.
Wraps shared analytics modules (health_monitor, session_analytics, gate_dashboard,
gate_timing, anomaly_detector, metrics_collector, skill_health) so Claude and
subagents can query them directly instead of multi-line Bash Python scripts.

No embedding models — near-instant startup.

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
def gate_health() -> dict:
    """Unified gate health report: health score, SLA status, degraded gates, routing stats.

    Combines data from gate_timing, gate_router, and circuit_breaker into
    a single health dashboard with a numeric health score (0-100).
    """
    _ensure_initialized()
    from shared.gate_health import get_gate_health_report, format_health_dashboard

    report = get_gate_health_report()
    dashboard = format_health_dashboard()

    return {
        "health_score": report["health_score"],
        "gate_count": report["gate_count"],
        "degraded_gates": report["degraded_gates"],
        "slow_gates": report["slow_gates"],
        "routing_stats": report["routing_stats"],
        "dashboard": dashboard,
    }


@mcp.tool()
@crash_proof
def gate_sla(gate_name: str = "") -> dict:
    """Check SLA compliance for gates: latency thresholds, auto-skip status.

    Args:
        gate_name: Specific gate to check. Empty returns all gates.
    """
    _ensure_initialized()
    from shared.gate_timing import check_gate_sla, get_sla_report

    if gate_name:
        return check_gate_sla(gate_name)
    return get_sla_report()


@mcp.tool()
@crash_proof
def gate_correlations(days: int = 7) -> dict:
    """Analyze gate block co-occurrence patterns from audit logs.

    Identifies which gates tend to block together — useful for finding
    redundant gates and optimization opportunities.

    Args:
        days: Number of days of audit logs to analyze (default 7).
    """
    _ensure_initialized()
    try:
        from shared.gate_correlation import analyze_correlations, format_correlation_report
        data = analyze_correlations(days=days)
        report = format_correlation_report(data)
        return {"data": data, "report": report}
    except ImportError:
        return {"error": "gate_correlation module not available"}


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
def session_metrics(session_id: str = "") -> dict:
    """Current session metrics: tool calls, gate blocks, error rate, memory gaps, duration.

    Reads real-time session state and returns operational metrics for the active session.

    Args:
        session_id: Session ID to analyze. Empty string auto-detects current session.
    """
    _ensure_initialized()
    import time
    from shared.state import load_state
    from shared.anomaly_detector import get_session_baseline

    sid = _resolve_session_id(session_id)
    state = load_state(session_id=sid)
    metrics = get_session_baseline(state)

    session_start = state.get("session_start", 0)
    elapsed_min = round((time.time() - session_start) / 60, 1) if session_start else 0

    tool_stats = state.get("tool_stats", {})
    top_tools = sorted(tool_stats.items(), key=lambda x: x[1].get("count", 0), reverse=True)[:5]

    return {
        "session_id": sid,
        "duration_minutes": elapsed_min,
        "total_tool_calls": state.get("tool_call_count", 0),
        "tool_call_rate_per_min": round(metrics.get("tool_call_rate", 0), 2),
        "gate_block_rate": round(metrics.get("gate_block_rate", 0), 3),
        "error_rate": round(metrics.get("error_rate", 0), 3),
        "memory_query_gap_seconds": round(metrics.get("memory_query_interval", 0), 1),
        "top_tools": [{"tool": name, "count": info.get("count", 0)} for name, info in top_tools],
        "gate_block_count": len(state.get("gate_block_outcomes", [])),
        "error_count": len(state.get("unlogged_errors", [])),
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
def gate_trends() -> dict:
    """Gate latency trends over time: rising, falling, stable per gate.

    Shows which gates are getting slower (rising) or faster (falling).
    Takes a new snapshot if enough time has passed since the last one.
    """
    _ensure_initialized()
    from shared.gate_trend import snapshot_gate_stats, get_trend_report, format_trend_report

    snapshot_gate_stats()  # Take snapshot if rate limit allows
    report = get_trend_report()
    text = format_trend_report()

    return {
        "report": text,
        "snapshot_count": report["snapshot_count"],
        "rising_gates": report["rising_gates"],
        "falling_gates": report["falling_gates"],
        "gates": report["gates"],
    }


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


@mcp.tool()
@crash_proof
def gate_dependencies() -> dict:
    """Gate dependency graph: state conflicts, parallel-safe gates, hotspots, mermaid diagram.

    Analyzes which gates read/write which state keys to identify conflicts
    and opportunities for parallelization.
    """
    _ensure_initialized()
    from shared.gate_dependency_graph import (
        find_state_conflicts,
        find_parallel_safe_gates,
        get_state_hotspots,
        generate_mermaid_diagram,
        format_dependency_report,
        detect_cycles,
        recommend_gate_ordering,
    )

    return {
        "conflicts": find_state_conflicts(),
        "parallel_safety": find_parallel_safe_gates(),
        "hotspots": get_state_hotspots()[:15],
        "mermaid_diagram": generate_mermaid_diagram(),
        "report": format_dependency_report(),
        "cycles": detect_cycles(),
        "recommended_ordering": recommend_gate_ordering(),
    }


@mcp.tool()
@crash_proof
def memory_health() -> dict:
    """Memory subsystem health: LanceDB table sizes, disk usage, tag index status.

    Quick health check for the memory infrastructure without modifying anything.
    """
    _ensure_initialized()
    import glob as _mh_glob

    lance_dir = os.path.join(os.path.expanduser("~"), "data", "memory", "lancedb")
    tags_db = os.path.join(os.path.expanduser("~"), "data", "memory", "tags.db")
    result = {
        "lance_dir": lance_dir,
        "lance_exists": os.path.isdir(lance_dir),
        "tables": {},
        "tags_db_exists": os.path.isfile(tags_db),
        "total_size_mb": 0,
    }

    if result["lance_exists"]:
        # Get total disk usage
        total_bytes = 0
        for dirpath, dirnames, filenames in os.walk(lance_dir):
            for f in filenames:
                try:
                    total_bytes += os.path.getsize(os.path.join(dirpath, f))
                except OSError:
                    pass
        result["total_size_mb"] = round(total_bytes / (1024 * 1024), 2)

        # Count rows per table
        try:
            import lancedb
            db = lancedb.connect(lance_dir)
            for table_name in db.table_names():
                try:
                    tbl = db.open_table(table_name)
                    result["tables"][table_name] = {
                        "row_count": tbl.count_rows(),
                    }
                except Exception:
                    result["tables"][table_name] = {"error": "cannot open"}
        except ImportError:
            result["tables"] = {"error": "lancedb not installed"}
        except Exception as e:
            result["tables"] = {"error": str(e)}

    if result["tags_db_exists"]:
        try:
            result["tags_db_size_kb"] = round(os.path.getsize(tags_db) / 1024, 1)
        except OSError:
            pass

    # Migration marker
    marker = os.path.join(lance_dir, ".migration_complete")
    result["migration_complete"] = os.path.isfile(marker)

    return result


@mcp.tool()
@crash_proof
def memory_dedup_report(table: str = "knowledge", threshold: float = 0.85) -> dict:
    """Scan memory for duplicate entries without executing compaction.

    Reports how many duplicate clusters exist and estimated savings.
    Uses cosine similarity to detect near-duplicates.

    Args:
        table: LanceDB table to scan (knowledge, observations, fix_outcomes)
        threshold: Cosine similarity threshold (0.0-1.0, default 0.85)
    """
    _ensure_initialized()
    try:
        from scripts.memory_compactor import scan_duplicates, compact
        clusters = scan_duplicates(table, threshold)
        result = compact(clusters, table, dry_run=True)

        return {
            "table": table,
            "threshold": threshold,
            "clusters": result.get("clusters", 0),
            "removable_entries": result.get("compacted", 0),
            "survivors": result.get("survivors", 0),
            "actions": result.get("actions", [])[:10],
            "hint": "Run `python3 scripts/memory_compactor.py --execute` to compact",
        }
    except ImportError:
        return {"error": "memory_compactor module not available"}
    except Exception as e:
        return {"error": f"Scan failed: {e}"}


@mcp.tool()
@crash_proof
def stale_memory_report(table: str = "knowledge", days: int = 90) -> dict:
    """Scan memory for stale entries that should be demoted.

    Identifies old, low-value memories using a staleness scoring model.
    Does not modify anything — reporting only.

    Args:
        table: LanceDB table to scan (default: knowledge)
        days: Age threshold in days (default: 90)
    """
    _ensure_initialized()
    try:
        from scripts.stale_memory_archiver import scan_stale, archive_stale
        stale = scan_stale(table, days)
        result = archive_stale(stale, table, dry_run=True)

        return {
            "table": table,
            "age_threshold_days": days,
            "stale_count": len(stale),
            "top_stale": stale[:10],
            "hint": "Run `python3 scripts/stale_memory_archiver.py --execute` to demote",
        }
    except ImportError:
        return {"error": "stale_memory_archiver module not available"}
    except Exception as e:
        return {"error": f"Scan failed: {e}"}


@mcp.tool()
@crash_proof
def circuit_states() -> dict:
    """Circuit breaker states for all tracked services and gates.

    Shows per-service: state (CLOSED/OPEN/HALF_OPEN), failure counts, total stats.
    Also shows per-gate circuit breaker: crash counts, skip counts, state.
    """
    _ensure_initialized()
    from shared.circuit_breaker import get_all_states, get_all_gate_states

    services = get_all_states()
    gates = get_all_gate_states()

    open_services = [s for s, r in services.items() if r.get("state") == "OPEN"]
    open_gates = [g for g, r in gates.items() if r.get("state") == "OPEN"]

    return {
        "services": services,
        "gates": gates,
        "open_services": open_services,
        "open_gates": open_gates,
        "total_services": len(services),
        "total_gates": len(gates),
    }


@mcp.tool()
@crash_proof
def audit_status() -> dict:
    """Audit log disk usage and rotation status.

    Shows total files, disk usage, files needing compression, files eligible
    for deletion based on default thresholds (compress >7 days, delete >30 days).
    """
    _ensure_initialized()
    from scripts.audit_rotation import scan_audit_files

    files = scan_audit_files()
    total_size = sum(f["size_bytes"] for f in files)
    needs_compress = [f for f in files if f["ext"] == ".jsonl" and f["age_days"] > 7]
    needs_delete = [f for f in files if f["ext"] == ".jsonl.gz" and f["age_days"] > 30]

    return {
        "total_files": len(files),
        "total_size_mb": round(total_size / (1024 * 1024), 2),
        "needs_compression": len(needs_compress),
        "needs_deletion": len(needs_delete),
        "oldest_file": files[0]["filename"] if files else None,
        "newest_file": files[-1]["filename"] if files else None,
        "hint": "Run `python3 scripts/audit_rotation.py --execute` to rotate",
    }


@mcp.tool()
@crash_proof
def framework_summary() -> dict:
    """High-level framework status: health, gates, circuits, skills in one view.

    Aggregates framework_health, gate_health, circuit_states, and skill_health
    into a single summary for quick status checks.
    """
    _ensure_initialized()
    summary = {}

    # Framework health
    try:
        from shared.health_monitor import full_health_check
        sid = _resolve_session_id("")
        health = full_health_check(sid)
        summary["health_score"] = health.get("overall_score", "?")
        summary["health_status"] = health.get("status", "unknown")
    except Exception:
        summary["health_score"] = "unavailable"

    # Gate health
    try:
        from shared.gate_health import get_gate_health_report
        gate_report = get_gate_health_report()
        summary["gate_health_score"] = gate_report.get("health_score", "?")
        summary["gates_tracked"] = gate_report.get("gate_count", 0)
        summary["gates_degraded"] = len(gate_report.get("degraded_gates", []))
    except Exception:
        summary["gate_health_score"] = "unavailable"

    # Circuit breaker
    try:
        from shared.circuit_breaker import get_all_states, get_all_gate_states
        services = get_all_states()
        gates = get_all_gate_states()
        summary["circuits_open"] = len([s for s, r in services.items() if r.get("state") == "OPEN"])
        summary["gate_circuits_open"] = len([g for g, r in gates.items() if r.get("state") == "OPEN"])
    except Exception:
        summary["circuits_open"] = "unavailable"

    # Skill health
    try:
        from shared.skill_health import check_all_skills
        skills = check_all_skills()
        summary["skills_total"] = skills.get("total", 0)
        summary["skills_healthy"] = skills.get("healthy", 0)
        summary["skills_broken"] = skills.get("broken", 0)
    except Exception:
        summary["skills_total"] = "unavailable"

    return summary


# ── Dry-Run Simulator ────────────────────────────────────────────────────────

@mcp.tool()
@crash_proof
def preview_gates(tool_name: str, tool_input: str = "{}") -> dict:
    """Dry-run all gates for a tool call without actually blocking.

    Shows which gates would fire, which would block, and why.
    Useful for understanding gate behavior before committing to an action.

    Args:
        tool_name: Tool to simulate (e.g. "Edit", "Bash", "Write", "Task")
        tool_input: JSON string of tool input (e.g. '{"file_path": "/etc/passwd"}')
    """
    import importlib
    import json as _json

    _ensure_initialized()

    # Parse tool_input
    try:
        parsed_input = _json.loads(tool_input) if isinstance(tool_input, str) else tool_input
    except _json.JSONDecodeError:
        parsed_input = {}

    # Import gate infrastructure
    try:
        from shared.state import load_state
        state = load_state(_detect_session_id())
    except Exception:
        state = {}

    # Gate registry
    GATE_TOOL_MAP = {
        "gates.gate_01_read_before_edit": {"Edit", "Write", "NotebookEdit"},
        "gates.gate_02_no_destroy": {"Bash"},
        "gates.gate_03_test_before_deploy": {"Bash"},
        "gates.gate_04_memory_first": {"Edit", "Write", "NotebookEdit", "Task"},
        "gates.gate_05_proof_before_fixed": {"Edit", "Write", "NotebookEdit"},
        "gates.gate_06_save_fix": {"Edit", "Write", "Task", "Bash", "NotebookEdit"},
        "gates.gate_07_critical_file_guard": {"Edit", "Write", "NotebookEdit"},
        "gates.gate_09_strategy_ban": {"Edit", "Write", "NotebookEdit"},
        "gates.gate_10_model_enforcement": {"Task"},
        "gates.gate_11_rate_limit": None,
        "gates.gate_13_workspace_isolation": {"Edit", "Write", "NotebookEdit"},
        "gates.gate_14_confidence_check": {"Edit", "Write", "NotebookEdit"},
        "gates.gate_15_causal_chain": {"Edit", "Write", "NotebookEdit"},
        "gates.gate_16_code_quality": {"Edit", "Write", "NotebookEdit"},
        "gates.gate_17_injection_defense": {"WebFetch", "WebSearch"},
        "gates.gate_18_canary": None,
        "gates.gate_19_hindsight": {"Edit", "Write", "NotebookEdit"},
    }

    results = []
    would_block = False

    for module_name, watched_tools in GATE_TOOL_MAP.items():
        # Check if this gate watches the given tool
        if watched_tools is not None and tool_name not in watched_tools:
            continue

        gate_short = module_name.split(".")[-1]
        entry = {"gate": gate_short, "status": "skip", "message": ""}

        try:
            mod = importlib.import_module(module_name)
            if not hasattr(mod, "check"):
                entry["status"] = "no_check"
                results.append(entry)
                continue

            result = mod.check(tool_name, parsed_input, state, event_type="PreToolUse")
            if result and getattr(result, "blocked", False):
                entry["status"] = "WOULD_BLOCK"
                entry["message"] = getattr(result, "message", "")[:200]
                would_block = True
            else:
                entry["status"] = "pass"
                msg = getattr(result, "message", "")
                if msg:
                    entry["message"] = msg[:200]
        except Exception as e:
            entry["status"] = "error"
            entry["message"] = f"{type(e).__name__}: {str(e)[:150]}"

        results.append(entry)

    return {
        "tool_name": tool_name,
        "would_block": would_block,
        "gates_checked": len(results),
        "blocking_gates": [r["gate"] for r in results if r["status"] == "WOULD_BLOCK"],
        "passing_gates": [r["gate"] for r in results if r["status"] == "pass"],
        "gate_details": results,
    }


# ── Audit Trail Viewer ──────────────────────────────────────────────────────

@mcp.tool()
@crash_proof
def audit_trail(gate: str = "", tool: str = "", outcome: str = "",
                hours: int = 24, limit: int = 50) -> dict:
    """Query audit trail with filtering by gate, tool, outcome, and time range.

    Args:
        gate: Filter by gate name substring (e.g. "gate_01", "gate_17")
        tool: Filter by tool name (e.g. "Edit", "Bash")
        outcome: Filter by decision: "block", "allow", or "" for all
        hours: Look back this many hours (default 24, max 168)
        limit: Max entries to return (default 50, max 200)
    """
    import json as _json
    import time as _time

    _ensure_initialized()

    hours = max(1, min(168, hours))
    limit = max(1, min(200, limit))
    cutoff = _time.time() - (hours * 3600)

    # Find audit files
    try:
        from shared.audit_log import AUDIT_DIR
        audit_dir = AUDIT_DIR
    except ImportError:
        audit_dir = os.path.join(os.path.dirname(__file__), "audit")

    if not os.path.isdir(audit_dir):
        return {"entries": [], "count": 0, "error": "audit directory not found"}

    # Collect matching entries from recent audit files
    entries = []
    audit_files = sorted(_glob.glob(os.path.join(audit_dir, "*.jsonl")), reverse=True)

    for af in audit_files[:7]:  # Max 7 days of files
        try:
            with open(af) as f:
                for line in f:
                    try:
                        entry = _json.loads(line.strip())
                    except _json.JSONDecodeError:
                        continue

                    # Time filter
                    ts = entry.get("timestamp", entry.get("ts", 0))
                    if isinstance(ts, str):
                        continue  # Skip non-numeric timestamps
                    if ts < cutoff:
                        continue

                    # Gate filter
                    if gate and gate.lower() not in entry.get("gate", "").lower():
                        continue

                    # Tool filter
                    if tool and tool.lower() != entry.get("tool", "").lower():
                        continue

                    # Outcome filter
                    if outcome and entry.get("decision", "") != outcome:
                        continue

                    entries.append(entry)
                    if len(entries) >= limit:
                        break
        except OSError:
            continue

        if len(entries) >= limit:
            break

    # Summary stats
    block_count = sum(1 for e in entries if e.get("decision") == "block")
    allow_count = sum(1 for e in entries if e.get("decision") == "allow")
    gates_seen = set(e.get("gate", "unknown") for e in entries)

    return {
        "entries": entries[-limit:],
        "count": len(entries),
        "blocks": block_count,
        "allows": allow_count,
        "gates_seen": sorted(gates_seen),
        "hours_searched": hours,
    }


# ── Error Clustering ─────────────────────────────────────────────────────────

@mcp.tool()
@crash_proof
def error_clusters(hours: int = 48, top_n: int = 10) -> dict:
    """Analyze error patterns from recent audit logs and group by root cause.

    Shows common error patterns, their frequency, co-occurrences, and
    prevention suggestions. Useful for identifying systemic issues.

    Args:
        hours: Look back this many hours (default 48, max 168)
        top_n: Number of top patterns to return (default 10, max 30)
    """
    import json as _json
    import time as _time

    _ensure_initialized()

    hours = max(1, min(168, hours))
    top_n = max(1, min(30, top_n))
    cutoff = _time.time() - (hours * 3600)

    # Collect error entries from audit logs
    try:
        from shared.audit_log import AUDIT_DIR
        audit_dir = AUDIT_DIR
    except ImportError:
        audit_dir = os.path.join(os.path.dirname(__file__), "audit")

    if not os.path.isdir(audit_dir):
        return {"patterns": [], "total_errors": 0, "error": "audit directory not found"}

    error_entries = []
    audit_files = sorted(_glob.glob(os.path.join(audit_dir, "*.jsonl")), reverse=True)

    for af in audit_files[:7]:
        try:
            with open(af) as f:
                for line in f:
                    try:
                        entry = _json.loads(line.strip())
                    except _json.JSONDecodeError:
                        continue
                    ts = entry.get("timestamp", entry.get("ts", 0))
                    if isinstance(ts, (int, float)) and ts >= cutoff:
                        if entry.get("decision") == "block" or entry.get("error"):
                            error_entries.append(entry)
        except OSError:
            continue

    # Analyze with error_pattern_analyzer
    try:
        from shared.error_pattern_analyzer import (
            analyze_errors, top_patterns as ep_top, suggest_prevention,
        )
        analysis = analyze_errors(error_entries)
        top = ep_top(error_entries, n=top_n)

        patterns = []
        for pattern_name, count in top:
            suggestion = suggest_prevention(pattern_name)
            patterns.append({
                "pattern": pattern_name,
                "count": count,
                "suggestion": suggestion,
            })

        return {
            "patterns": patterns,
            "total_errors": analysis.get("total_errors", len(error_entries)),
            "categories": analysis.get("category_breakdown", {}),
            "root_causes": analysis.get("root_cause_breakdown", {}),
            "hours_searched": hours,
        }
    except ImportError:
        # Fallback: simple gate-based grouping
        from collections import Counter
        gate_counts = Counter(e.get("gate", "unknown") for e in error_entries)
        patterns = [{"pattern": g, "count": c, "suggestion": ""} for g, c in gate_counts.most_common(top_n)]
        return {
            "patterns": patterns,
            "total_errors": len(error_entries),
            "hours_searched": hours,
        }


# ── Tool Pattern Predictions ─────────────────────────────────────────────────

@mcp.tool()
@crash_proof
def tool_predictions(recent_tools: str = "", top_k: int = 5) -> dict:
    """Predict next likely tool calls and detect unusual sequences.

    Uses Markov chain analysis of past tool call patterns to predict what
    tool the agent will likely use next. Also detects anomalous sequences.

    Args:
        recent_tools: Comma-separated list of recent tool names (e.g. "Read,Edit,Bash")
        top_k: Number of top predictions to return (default 5)
    """
    _ensure_initialized()

    tools_list = [t.strip() for t in recent_tools.split(",") if t.strip()] if recent_tools else []
    top_k = max(1, min(20, top_k))

    result = {}

    try:
        from shared.tool_patterns import (
            predict_next_tool, detect_unusual_sequence,
            get_workflow_templates, summarize_patterns,
        )

        # Predictions
        if tools_list:
            predictions = predict_next_tool(tools_list, top_k=top_k)
            result["predictions"] = [{"tool": t, "probability": round(p, 3)} for t, p in predictions]

            # Anomaly detection
            anomaly = detect_unusual_sequence(tools_list)
            if anomaly:
                result["anomaly"] = {
                    "detected": True,
                    "score": round(anomaly.score, 3),
                    "reason": anomaly.reason,
                    "unusual_transitions": anomaly.unusual_transitions[:5],
                }
            else:
                result["anomaly"] = {"detected": False}
        else:
            result["predictions"] = []
            result["anomaly"] = {"detected": False}

        # Workflow templates
        templates = get_workflow_templates(max_templates=5)
        result["workflows"] = [
            {"tools": t.tools, "count": t.count, "label": t.label}
            for t in templates
        ]

        # Summary stats
        summary = summarize_patterns()
        result["vocabulary_size"] = summary.get("vocabulary_size", 0)
        result["sequence_count"] = summary.get("sequence_count", 0)

    except ImportError:
        result["error"] = "tool_patterns module not available"

    return result


# ── Pruning Recommendations ─────────────────────────────────────────────────

@mcp.tool()
@crash_proof
def gate_pruning() -> dict:
    """Get gate pruning recommendations based on effectiveness analysis.

    Analyzes gate block rates, override rates, and latency to recommend
    which gates to keep, optimize, or consider merging/removing.
    """
    _ensure_initialized()

    try:
        from shared.gate_pruner import analyze_gates, get_prune_recommendations

        analysis = analyze_gates()
        recommendations = get_prune_recommendations()

        gates = {}
        for name, a in analysis.items():
            gates[name] = {
                "verdict": a.verdict,
                "avg_ms": round(a.avg_ms, 1),
                "blocks": a.blocks,
                "prevented": a.prevented,
                "block_rate": round(a.block_rate, 3),
                "reasons": a.reasons[:3],
            }

        recs = []
        for r in recommendations[:10]:
            recs.append({
                "rank": r.rank,
                "gate": r.gate,
                "verdict": r.verdict,
                "reasons": r.reasons[:3],
            })

        return {
            "gates": gates,
            "recommendations": recs,
            "total_analyzed": len(analysis),
        }
    except ImportError:
        return {"error": "gate_pruner module not available"}


# ── Domain Management ────────────────────────────────────────────────────────

@mcp.tool()
@crash_proof
def domain_info() -> dict:
    """List all knowledge domains with active domain and profile details.

    Shows registered domains, which is active, graduation status,
    and mastery availability. Wraps domain_registry.py.
    """
    _ensure_initialized()

    try:
        from shared.domain_registry import (
            list_domains, get_active_domain, load_domain_profile,
        )

        domains = list_domains()
        active = get_active_domain()

        # Enrich with profile details for active domain
        active_profile = None
        if active:
            profile = load_domain_profile(active)
            active_profile = {
                "name": active,
                "description": profile.get("description", ""),
                "security_profile": profile.get("security_profile", "balanced"),
                "memory_tags": profile.get("memory_tags", []),
                "token_budget": profile.get("token_budget", 800),
                "graduated": profile.get("graduation", {}).get("graduated", False),
            }

        return {
            "domains": domains,
            "active_domain": active,
            "active_profile": active_profile,
            "total_domains": len(domains),
        }
    except ImportError:
        return {"error": "domain_registry module not available"}


# ── Gate Drift Detection ─────────────────────────────────────────────────────

@mcp.tool()
@crash_proof
def gate_drift(hours: int = 24) -> dict:
    """Detect drift in gate fire-rate patterns compared to a rolling baseline.

    Compares current gate effectiveness ratios against the average from the
    specified lookback window.  Returns per-gate deltas, overall drift score,
    and whether an alert threshold (0.3) is exceeded.

    Args:
        hours: Lookback window for baseline computation (default 24, max 168).
    """
    import json as _json
    import time as _time

    _ensure_initialized()
    hours = max(1, min(168, hours))

    try:
        from shared.drift_detector import gate_drift_report
    except ImportError:
        return {"error": "drift_detector module not available"}

    # Build current fire-rate vector from gate effectiveness
    try:
        from shared.state import load_gate_effectiveness
        eff = load_gate_effectiveness()
    except (ImportError, Exception):
        eff = {}

    if not eff:
        return {"drift_score": 0.0, "alert": False, "message": "no effectiveness data",
                "per_gate_deltas": {}}

    current = {}
    baseline = {}
    for gate, stats in eff.items():
        prevented = stats.get("prevented", 0)
        overrides = stats.get("overrides", 0)
        total = prevented + overrides
        if total > 0:
            current[gate] = prevented / total

    # Build baseline from audit trail (last N hours block rate)
    try:
        from shared.audit_log import AUDIT_DIR
        audit_dir = AUDIT_DIR
    except ImportError:
        audit_dir = os.path.join(os.path.dirname(__file__), "audit")

    gate_blocks = {}
    gate_totals = {}
    cutoff = _time.time() - (hours * 3600)
    if os.path.isdir(audit_dir):
        audit_files = sorted(_glob.glob(os.path.join(audit_dir, "*.jsonl")), reverse=True)
        for af in audit_files[:7]:
            try:
                with open(af) as f:
                    for line in f:
                        try:
                            entry = _json.loads(line.strip())
                        except _json.JSONDecodeError:
                            continue
                        ts = entry.get("timestamp", entry.get("ts", 0))
                        if isinstance(ts, (int, float)) and ts >= cutoff:
                            g = entry.get("gate", "")
                            if g:
                                gate_totals[g] = gate_totals.get(g, 0) + 1
                                if entry.get("decision") == "block":
                                    gate_blocks[g] = gate_blocks.get(g, 0) + 1
            except OSError:
                continue

    for g, total in gate_totals.items():
        if total > 0:
            baseline[g] = gate_blocks.get(g, 0) / total

    if not baseline:
        baseline = {g: 0.5 for g in current}

    report = gate_drift_report(current, baseline)
    report["current_vector"] = current
    report["baseline_vector"] = baseline
    report["hours"] = hours
    return report


# ── Skill Dependency Analysis ────────────────────────────────────────────────

@mcp.tool()
@crash_proof
def skill_dependencies() -> dict:
    """Analyze skill dependencies and shared module usage patterns.

    Scans ~/.claude/skills/, parses scripts for shared module imports,
    identifies missing dependencies and reuse opportunities.  Returns
    per-skill health status (healthy/degraded/unhealthy) with coverage
    percentages and actionable recommendations.
    """
    _ensure_initialized()

    try:
        from shared.skill_mapper import SkillMapper
    except ImportError:
        return {"error": "skill_mapper module not available"}

    mapper = SkillMapper()
    health = mapper.get_skill_health()
    deps = mapper.get_dependency_graph()
    needing = mapper.get_skills_needing_dependencies()
    reuse = mapper.get_skills_with_reuse_opportunities()
    usage = mapper.get_shared_module_usage()

    health_summary = {}
    for name, h in health.items():
        health_summary[name] = {
            "status": h.status,
            "coverage_pct": round(h.coverage_pct, 1),
            "script_count": h.script_count,
            "shared_modules": h.shared_module_count,
            "missing_deps": h.missing_dependencies,
            "reuse_opportunities": h.reuse_opportunities[:3],
        }

    total = len(health)
    healthy = sum(1 for h in health.values() if h.status == "healthy")
    degraded = sum(1 for h in health.values() if h.status == "degraded")
    unhealthy = sum(1 for h in health.values() if h.status == "unhealthy")

    return {
        "total_skills": total,
        "healthy": healthy,
        "degraded": degraded,
        "unhealthy": unhealthy,
        "skills": health_summary,
        "dependency_graph": deps,
        "skills_needing_deps": needing,
        "top_shared_modules": dict(sorted(usage.items(), key=lambda x: x[1], reverse=True)[:10]),
    }


# ── Gate Correlation Engine (Advanced) ────────────────────────────────────────

@mcp.tool()
@crash_proof
def gate_correlation_report(tool_filter: str = "", days: int = 7) -> dict:
    """Advanced gate correlation analysis: co-occurrence, chains, redundancy, ordering.

    Uses the GateCorrelator engine to perform 4 analyses on audit logs:
    1. Co-occurrence matrix — which gates fire together
    2. Gate chains — directional A→B firing patterns within time windows
    3. Redundant gates — gates with >85% Jaccard similarity (candidates for merging)
    4. Optimal ordering — fastest-reject-first gate ordering recommendations

    Args:
        tool_filter: Optional tool name to focus analysis (e.g. "Edit", "Bash"). Empty = all.
        days: Number of days of audit data to analyze (default 7, max 30).
    """
    _ensure_initialized()

    try:
        from shared.gate_correlator import GateCorrelator
    except ImportError:
        return {"error": "gate_correlator module not available"}

    days = max(1, min(30, days))
    correlator = GateCorrelator()
    report = correlator.full_report(target_tool=tool_filter or None)

    return report


# ── Pipeline Performance Analysis ────────────────────────────────────────────

@mcp.tool()
@crash_proof
def pipeline_analysis(tool_name: str = "") -> dict:
    """Analyze gate pipeline execution efficiency and parallelization opportunities.

    Estimates latency savings from optimized gate ordering and parallel execution.
    Shows per-tool gate applicability, block rates, and parallel groupings.

    Args:
        tool_name: Specific tool to analyze (e.g. "Edit"). Empty = full cross-tool report.
    """
    _ensure_initialized()

    try:
        from shared.pipeline_optimizer import get_pipeline_analysis, estimate_savings
    except ImportError:
        return {"error": "pipeline_optimizer module not available"}

    if tool_name:
        savings = estimate_savings(tool_name)
        return {"tool": tool_name, "analysis": savings}

    return get_pipeline_analysis()


# ── Behavioral Anomaly Summary ───────────────────────────────────────────────

@mcp.tool()
@crash_proof
def anomaly_summary(session_id: str = "") -> dict:
    """Detect behavioral anomalies in the current or specified session.

    Checks for: tool call bursts, high gate block rates, elevated error rates,
    memory query gaps, single-tool dominance, and stuck gate loops.

    Args:
        session_id: Session to analyze. Empty = auto-detect current session.
    """
    _ensure_initialized()

    try:
        from shared.anomaly_detector import detect_behavioral_anomaly, check_tool_dominance
        from shared.state import load_state
    except ImportError:
        return {"error": "anomaly_detector or state module not available"}

    sid = session_id or _guess_session_id()
    state = load_state(session_id=sid)

    anomalies = detect_behavioral_anomaly(state)
    tool_stats = state.get("tool_stats", {})
    tool_counts = {t: s.get("count", 0) for t, s in tool_stats.items() if isinstance(s, dict)}
    dominance = check_tool_dominance(tool_counts)

    results = []
    for atype, severity, description in anomalies:
        results.append({"type": atype, "severity": severity, "description": description})

    return {
        "session_id": sid,
        "anomaly_count": len(results),
        "anomalies": results,
        "tool_dominance": dominance,
        "tool_call_count": state.get("tool_call_count", 0),
    }


# ── Event Bus Stats ──────────────────────────────────────────────────────────

@mcp.tool()
@crash_proof
def event_stats(event_type: str = "", limit: int = 20) -> dict:
    """Query the event bus for recent events and aggregate statistics.

    Shows event publication counts by type, handler errors, buffer usage,
    and optionally filters recent events by type.

    Args:
        event_type: Filter recent events by type (e.g. "GATE_BLOCKED"). Empty = all.
        limit: Max recent events to return (default 20, max 100).
    """
    _ensure_initialized()

    try:
        from shared.event_bus import get_stats, get_recent
    except ImportError:
        return {"error": "event_bus module not available"}

    limit = max(1, min(100, limit))
    stats = get_stats()
    recent = get_recent(event_type=event_type or None, limit=limit)

    return {
        "stats": stats,
        "recent_events": recent,
        "recent_count": len(recent),
        "filter": event_type or "all",
    }


# ── Session Replay ───────────────────────────────────────────────────────────

@mcp.tool()
@crash_proof
def session_replay(lookback_hours: int = 1, gate_filter: str = "",
                   tool_filter: str = "", format: str = "text") -> dict:
    """Replay the session timeline showing gate decisions chronologically.

    Builds a timeline from audit logs showing every gate fire, block, and
    warning.  Supports text, mermaid, and stats export formats.  Also
    detects anomalous patterns like consecutive blocks and gate thrashing.

    Args:
        lookback_hours: Hours of history to replay (default 1, max 168).
        gate_filter: Only show events matching this gate name substring.
        tool_filter: Only show events for this tool name.
        format: Output format - "text", "mermaid", "stats", or "patterns".
    """
    _ensure_initialized()

    try:
        from shared.session_replay import (
            build_timeline, export_text, export_mermaid,
            get_timeline_stats, detect_patterns,
        )
    except ImportError:
        return {"error": "session_replay module not available"}

    lookback_hours = max(1, min(168, lookback_hours))

    if format == "mermaid":
        return {"mermaid": export_mermaid(lookback_hours)}
    elif format == "stats":
        return get_timeline_stats(lookback_hours)
    elif format == "patterns":
        return detect_patterns(lookback_hours)
    else:
        timeline = build_timeline(lookback_hours, gate_filter, tool_filter)
        text = export_text(lookback_hours)
        patterns = detect_patterns(lookback_hours)
        return {
            "text_timeline": text,
            "event_count": timeline["event_count"],
            "duration_seconds": timeline["duration_seconds"],
            "block_count": timeline["event_types"].get("BLOCK", 0),
            "gates_seen": timeline["gates_seen"],
            "tools_seen": timeline["tools_seen"],
            "patterns": patterns["patterns"],
            "healthy": patterns["healthy"],
        }


# ── Code Hotspot Analysis ────────────────────────────────────────────────────

@mcp.tool()
@crash_proof
def code_hotspots(lookback_days: int = 7, limit: int = 20) -> dict:
    """Identify high-risk files by analyzing gate block patterns from audit logs.

    Cross-references gate blocks with file paths to compute a composite risk
    score per file: block_count * churn_factor * error_density.  Returns files
    ranked from highest to lowest risk.

    Args:
        lookback_days: Days of audit data to analyze (default 7, max 30).
        limit: Max files to return (default 20, max 50).
    """
    _ensure_initialized()

    try:
        from shared.code_hotspot import rank_files_by_risk, analyze_file_blocks
    except ImportError:
        return {"error": "code_hotspot module not available"}

    lookback_days = max(1, min(30, lookback_days))
    limit = max(1, min(50, limit))

    ranked = rank_files_by_risk(lookback_days=lookback_days, limit=limit)
    analysis = analyze_file_blocks(lookback_days=lookback_days)

    critical = sum(1 for r in ranked if r["risk_level"] == "critical")
    high = sum(1 for r in ranked if r["risk_level"] == "high")

    return {
        "ranked_files": ranked,
        "total_blocks": analysis["total_blocks"],
        "total_files_blocked": analysis["total_files"],
        "critical_count": critical,
        "high_count": high,
        "lookback_days": lookback_days,
    }


# ── Test Stub Generator ─────────────────────────────────────────────────────

@mcp.tool()
@crash_proof
def generate_test_stubs(module_path: str) -> dict:
    """Auto-generate test stubs for a Python module using AST analysis.

    Scans the given module file, detects public functions and their types
    (gate_check, shared_util, skill_entry), and generates ready-to-run
    test code matching the test_framework.py style.

    Args:
        module_path: Path to the Python module to scan (absolute or relative to hooks/).
    """
    _ensure_initialized()

    try:
        from shared.test_generator import scan_module, generate_tests
    except ImportError:
        return {"error": "test_generator module not available"}

    # Resolve relative paths
    hooks_dir = os.path.dirname(__file__)
    if not os.path.isabs(module_path):
        module_path = os.path.join(hooks_dir, module_path)

    if not os.path.isfile(module_path):
        return {"error": f"file not found: {module_path}"}

    scan_result = scan_module(module_path)
    functions = []
    for func_name, args, docstring, func_type in scan_result:
        functions.append({
            "name": func_name,
            "args": args,
            "docstring": docstring,
            "type": func_type,
        })

    generated_code = generate_tests(scan_result, module_path)

    return {
        "module": os.path.basename(module_path),
        "functions_found": len(functions),
        "functions": functions,
        "generated_test_code": generated_code,
        "code_lines": len(generated_code.splitlines()),
    }


# ── Gate Router Stats ────────────────────────────────────────────────────────

@mcp.tool()
@crash_proof
def routing_stats() -> dict:
    """Get gate routing statistics including tier membership, tool-gate mapping,
    and Q-learning optimization state.

    Returns tier composition, per-tool gate applicability, and the current
    Q-table entries showing learned gate-blocking probabilities.
    """
    _ensure_initialized()

    try:
        from shared.gate_router import (
            get_applicable_gates, get_routing_stats,
            TIER1, TIER2, TIER3, GATE_TOOL_MAP,
        )
    except ImportError:
        return {"error": "gate_router module not available"}

    stats = get_routing_stats()

    # Build tool → applicable gate count map
    tools = ["Edit", "Write", "Bash", "Read", "Task", "Glob", "Grep",
             "WebFetch", "WebSearch", "NotebookEdit"]
    tool_gates = {}
    for t in tools:
        applicable = get_applicable_gates(t)
        tool_gates[t] = {"count": len(applicable), "gates": applicable}

    # Load Q-table if available
    import json as _json
    qtable_path = os.path.join(os.path.dirname(__file__), ".gate_qtable.json")
    qtable = {}
    try:
        if os.path.isfile(qtable_path):
            with open(qtable_path) as f:
                qtable = _json.load(f)
    except (OSError, _json.JSONDecodeError):
        pass

    return {
        "routing_stats": stats,
        "tiers": {
            "tier1_safety": sorted(TIER1),
            "tier2_quality": sorted(TIER2),
            "tier3_advisory": sorted(TIER3),
        },
        "tool_gate_mapping": tool_gates,
        "qtable_entries": len(qtable),
        "qtable": qtable,
    }


# ── Framework Pulse Dashboard ────────────────────────────────────────────────

@mcp.tool()
@crash_proof
def framework_pulse(lookback_hours: int = 1) -> dict:
    """Comprehensive framework health pulse — one call to rule them all.

    Aggregates data from session replay, code hotspots, gate trends,
    anomaly detection, and circuit breakers into a single dashboard view.
    Use this for a quick "how is the framework doing?" check.

    Args:
        lookback_hours: Hours of recent activity to analyze (default 1).
    """
    _ensure_initialized()
    pulse = {"lookback_hours": lookback_hours}

    # 1. Session replay stats
    try:
        from shared.session_replay import get_timeline_stats, detect_patterns
        pulse["session"] = get_timeline_stats(lookback_hours)
        patterns = detect_patterns(lookback_hours)
        pulse["patterns"] = patterns["patterns"]
        pulse["healthy"] = patterns["healthy"]
    except Exception:
        pulse["session"] = {"error": "unavailable"}
        pulse["healthy"] = True
        pulse["patterns"] = []

    # 2. Code hotspots (top 5)
    try:
        from shared.code_hotspot import rank_files_by_risk
        hotspots = rank_files_by_risk(lookback_days=max(1, lookback_hours // 24 + 1), limit=5)
        pulse["hotspots"] = [{
            "file": h["file_path"],
            "risk": h["risk_score"],
            "level": h["risk_level"],
            "blocks": h["block_count"],
        } for h in hotspots]
    except Exception:
        pulse["hotspots"] = []

    # 3. Gate trends
    try:
        from shared.gate_trend import get_trend_report
        report = get_trend_report()
        pulse["gate_trends"] = {
            "rising": report.get("rising_gates", []),
            "falling": report.get("falling_gates", []),
            "total_gates": report.get("total_gates", 0),
            "snapshots": report.get("snapshot_count", 0),
        }
    except Exception:
        pulse["gate_trends"] = {"rising": [], "falling": [], "total_gates": 0}

    # 4. Circuit breaker states
    try:
        from shared.circuit_breaker import get_all_gate_states
        gate_states = get_all_gate_states()
        open_circuits = [g for g, s in gate_states.items() if s != "CLOSED"]
        pulse["circuits"] = {
            "total": len(gate_states),
            "open": open_circuits,
            "all_closed": len(open_circuits) == 0,
        }
    except Exception:
        pulse["circuits"] = {"total": 0, "open": [], "all_closed": True}

    # 5. Overall health score (0-100)
    score = 100
    if not pulse.get("healthy", True):
        score -= 20
    if pulse.get("patterns"):
        score -= min(30, len(pulse["patterns"]) * 10)
    if pulse.get("circuits", {}).get("open"):
        score -= len(pulse["circuits"]["open"]) * 15
    if pulse.get("gate_trends", {}).get("rising"):
        score -= len(pulse["gate_trends"]["rising"]) * 5
    hotspot_critical = sum(1 for h in pulse.get("hotspots", []) if h.get("level") == "critical")
    score -= hotspot_critical * 10
    pulse["health_score"] = max(0, min(100, score))

    return pulse


# ── Cache Health ─────────────────────────────────────────────────────────────

@mcp.tool()
@crash_proof
def cache_health() -> dict:
    """Hook invocation cache performance — hits, misses, evictions per layer.

    Shows module cache (imported gates), state cache (session data),
    and result cache (GateResult dedup) metrics. Useful for diagnosing
    slow hook invocations or cache thrashing.
    """
    _ensure_initialized()
    from shared.hook_cache import cache_stats, evict_expired

    stats = cache_stats()
    expired = evict_expired()

    # Compute hit rates
    module_total = stats.get("module_hits", 0) + stats.get("module_misses", 0)
    state_total = stats.get("state_hits", 0) + stats.get("state_misses", 0)
    result_total = stats.get("result_hits", 0) + stats.get("result_misses", 0)

    return {
        "module_cache": {
            "hits": stats.get("module_hits", 0),
            "misses": stats.get("module_misses", 0),
            "cached": stats.get("module_cached", 0),
            "hit_rate": round(stats.get("module_hits", 0) / max(module_total, 1), 3),
        },
        "state_cache": {
            "hits": stats.get("state_hits", 0),
            "misses": stats.get("state_misses", 0),
            "evictions": stats.get("state_evictions", 0),
            "cached": stats.get("state_cached", 0),
            "hit_rate": round(stats.get("state_hits", 0) / max(state_total, 1), 3),
        },
        "result_cache": {
            "hits": stats.get("result_hits", 0),
            "misses": stats.get("result_misses", 0),
            "evictions": stats.get("result_evictions", 0),
            "cached": stats.get("result_cached", 0),
            "hit_rate": round(stats.get("result_hits", 0) / max(result_total, 1), 3),
        },
        "just_expired": expired,
    }


@mcp.tool()
@crash_proof
def gate_sla_status(threshold_ms: int = 50) -> dict:
    """Gate latency SLA compliance — identifies degraded/slow gates.

    Checks all tracked gates against performance SLA thresholds.
    Gates exceeding thresholds are flagged for investigation.
    Tier 1 safety gates are never auto-skipped even when degraded.

    Args:
        threshold_ms: Custom slow-gate threshold in milliseconds (default 50).
    """
    _ensure_initialized()
    from shared.gate_timing import get_sla_report, get_degraded_gates, get_slow_gates

    sla_report = get_sla_report()
    degraded = get_degraded_gates()
    slow = get_slow_gates(threshold_ms=threshold_ms)

    # Categorize
    ok_gates = [g for g, s in sla_report.items() if s["status"] == "ok"]
    warn_gates = [g for g, s in sla_report.items() if s["status"] == "warn"]
    degrade_gates = [g for g, s in sla_report.items() if s["status"] == "degrade"]
    unknown_gates = [g for g, s in sla_report.items() if s["status"] == "unknown"]

    return {
        "total_gates": len(sla_report),
        "ok": len(ok_gates),
        "warn": len(warn_gates),
        "degraded": len(degrade_gates),
        "unknown": len(unknown_gates),
        "auto_skip_gates": degraded,
        "slow_gates": {g: {"avg_ms": s["avg_ms"], "p95_ms": s["p95_ms"]}
                       for g, s in slow.items()},
        "warn_gates_detail": {g: sla_report[g] for g in warn_gates},
        "degraded_gates_detail": {g: sla_report[g] for g in degrade_gates},
    }


@mcp.tool()
@crash_proof
def replay_events(
    tool_filter: str = "",
    gate_filter: str = "",
    blocked_only: bool = False,
    limit: int = 10,
) -> dict:
    """Replay captured tool events through the gate pipeline for regression testing.

    Re-runs historical events from the capture queue through all applicable gates,
    comparing current gate behavior against the original outcome to detect
    regressions or improvements after gate modifications.

    Args:
        tool_filter: Filter by exact tool name (e.g., "Edit", "Bash").
        gate_filter: Filter by gate name substring.
        blocked_only: If true, only replay events that were originally blocked.
        limit: Maximum events to replay (default 10, max 50).
    """
    _ensure_initialized()
    from shared.event_replay import replay_all, summarise_replay

    limit = max(1, min(50, limit))
    results = replay_all(
        gate_name=gate_filter or None,
        tool_name=tool_filter or None,
        blocked=True if blocked_only else None,
    )
    results = results[:limit]
    summary = summarise_replay(results)

    # Build per-event detail
    events_detail = []
    for item in results[:20]:  # Cap detail output
        diff = item.get("diff", {})
        event_meta = item.get("event", {}).get("_replay_meta", {})
        replayed = item.get("replayed", {})
        events_detail.append({
            "tool": event_meta.get("tool_name", ""),
            "original": event_meta.get("exit_code", ""),
            "replayed_outcome": replayed.get("final_outcome", ""),
            "gates_run": replayed.get("gates_run", 0),
            "changed": diff.get("changed", False),
            "summary": diff.get("summary", ""),
        })

    return {
        "total_replayed": summary["total"],
        "changed": summary["changed"],
        "unchanged": summary["unchanged"],
        "new_blocks": summary["new_blocks"],
        "new_passes": summary["new_passes"],
        "events": events_detail,
    }


# ── Fix Strategy Effectiveness ────────────────────────────────────────────────

@mcp.tool()
@crash_proof
def fix_effectiveness(error_type: str = "") -> dict:
    """Query historical fix outcomes and surface strategy recommendations with confidence.

    Analyzes the experience archive to rank fix strategies by success rate,
    compute confidence intervals based on sample size, and identify the
    best strategy for a given error type.

    Args:
        error_type: Filter by error type substring (e.g. "ImportError"). Empty = all.
    """
    _ensure_initialized()
    from shared.experience_archive import (
        query_best_strategy, get_success_rate, get_archive_stats,
        ARCHIVE_PATH, _read_rows,
    )

    stats = get_archive_stats()
    result = {
        "total_fix_attempts": stats["total_rows"],
        "unique_errors": stats["unique_errors"],
        "unique_strategies": stats["unique_strategies"],
        "overall_success_rate": stats["overall_success_rate"],
    }

    if error_type:
        best = query_best_strategy(error_type)
        result["error_type"] = error_type
        result["best_strategy"] = best
        if best:
            result["best_strategy_success_rate"] = round(get_success_rate(best), 3)

        # Build per-strategy breakdown for this error type
        rows = _read_rows(ARCHIVE_PATH)
        needle = error_type.lower()
        strat_stats = {}
        for row in rows:
            et = row.get("error_type", "")
            if needle not in et.lower():
                continue
            strat = row.get("fix_strategy", "").strip()
            if not strat:
                continue
            if strat not in strat_stats:
                strat_stats[strat] = {"total": 0, "successes": 0}
            strat_stats[strat]["total"] += 1
            if row.get("outcome") == "success":
                strat_stats[strat]["successes"] += 1

        strategies = []
        for name, s in strat_stats.items():
            rate = s["successes"] / s["total"] if s["total"] > 0 else 0.0
            # Confidence: low (<3 attempts), medium (3-9), high (10+)
            confidence = "high" if s["total"] >= 10 else ("medium" if s["total"] >= 3 else "low")
            strategies.append({
                "strategy": name,
                "total": s["total"],
                "successes": s["successes"],
                "success_rate": round(rate, 3),
                "confidence": confidence,
            })
        strategies.sort(key=lambda x: (-x["success_rate"], -x["total"]))
        result["strategies"] = strategies
    else:
        result["top_strategies"] = stats["top_strategies"]

    return result


# ── Observation Query ─────────────────────────────────────────────────────────

@mcp.tool()
@crash_proof
def query_observations(
    error_only: bool = False,
    priority: str = "",
    tool_name: str = "",
    limit: int = 20,
) -> dict:
    """Search auto-captured tool observations by error, priority, or tool type.

    Observations are compressed summaries of tool calls captured during sessions.
    Use this to find error patterns, track tool usage, and analyze agent behavior.

    Args:
        error_only: If true, only return observations with errors.
        priority: Filter by priority level: "high", "medium", or "low".
        tool_name: Filter by tool name (e.g. "Bash", "Edit").
        limit: Max results (default 20, max 100).
    """
    _ensure_initialized()
    limit = max(1, min(100, limit))

    # Read observations from LanceDB
    try:
        import lancedb
        lance_dir = os.path.join(os.path.expanduser("~"), "data", "memory", "lancedb")
        db = lancedb.connect(lance_dir)
        tbl = db.open_table("observations")

        # Build filter
        filters = []
        if error_only:
            filters.append("metadata LIKE '%\"has_error\": \"true\"%' OR metadata LIKE '%has_error%true%'")
        if priority:
            filters.append(f"metadata LIKE '%\"priority\": \"{priority}\"%'")
        if tool_name:
            filters.append(f"metadata LIKE '%\"tool_name\": \"{tool_name}\"%'")

        import json as _json

        if filters:
            # LanceDB SQL filter
            try:
                where_clause = " AND ".join(filters)
                rows = tbl.search().where(where_clause).limit(limit).to_list()
            except Exception:
                # Fallback: scan and filter in Python
                all_rows = tbl.search().limit(500).to_list()
                rows = []
                for r in all_rows:
                    meta_str = r.get("metadata", "{}")
                    try:
                        meta = _json.loads(meta_str) if isinstance(meta_str, str) else meta_str
                    except (ValueError, TypeError):
                        meta = {}
                    if error_only and meta.get("has_error") != "true":
                        continue
                    if priority and meta.get("priority") != priority:
                        continue
                    if tool_name and meta.get("tool_name") != tool_name:
                        continue
                    rows.append(r)
                    if len(rows) >= limit:
                        break
        else:
            rows = tbl.search().limit(limit).to_list()

        # Format results
        observations = []
        sentiment_counts = {}
        for r in rows[:limit]:
            meta_str = r.get("metadata", "{}")
            try:
                meta = _json.loads(meta_str) if isinstance(meta_str, str) else meta_str
            except (ValueError, TypeError):
                meta = {}
            sentiment = meta.get("sentiment", "")
            if sentiment:
                sentiment_counts[sentiment] = sentiment_counts.get(sentiment, 0) + 1
            observations.append({
                "id": r.get("id", ""),
                "document": str(r.get("text", r.get("document", "")))[:200],
                "tool_name": meta.get("tool_name", ""),
                "priority": meta.get("priority", ""),
                "has_error": meta.get("has_error", "false"),
                "error_pattern": meta.get("error_pattern", ""),
                "sentiment": sentiment,
            })

        return {
            "total": len(observations),
            "observations": observations,
            "sentiment_breakdown": sentiment_counts,
            "filters_applied": {
                "error_only": error_only,
                "priority": priority,
                "tool_name": tool_name,
            },
        }
    except ImportError:
        return {"error": "lancedb not installed", "total": 0, "observations": []}
    except Exception as e:
        return {"error": str(e), "total": 0, "observations": []}


# ── Domain Context Inspector ──────────────────────────────────────────────────

@mcp.tool()
@crash_proof
def inspect_domain() -> dict:
    """Inspect active domain context: mastery, behavior, gate overrides, token budget.

    Shows what domain knowledge is being injected, how much token budget
    is consumed, which gates are overridden, and graduation status.
    Useful for debugging unexpected gate behavior or context injection issues.
    """
    _ensure_initialized()

    try:
        from shared.domain_registry import (
            get_active_domain, load_domain_profile,
            load_domain_mastery, load_domain_behavior,
            get_domain_token_budget, list_domains,
        )
    except ImportError:
        return {"error": "domain_registry module not available"}

    active = get_active_domain()
    domains = list_domains()

    result = {
        "active_domain": active,
        "total_domains": len(domains),
        "domains": domains,
    }

    if active:
        profile = load_domain_profile(active)
        mastery = load_domain_mastery(active)
        behavior = load_domain_behavior(active)
        budget = get_domain_token_budget(active)

        mastery_chars = len(mastery)
        behavior_chars = len(behavior)
        token_estimate = (mastery_chars + behavior_chars) // 4  # ~4 chars/token

        result["active_detail"] = {
            "description": profile.get("description", ""),
            "security_profile": profile.get("security_profile", "balanced"),
            "mastery": {
                "length_chars": mastery_chars,
                "token_estimate": mastery_chars // 4,
                "preview": mastery[:200] if mastery else "",
            },
            "behavior": {
                "length_chars": behavior_chars,
                "token_estimate": behavior_chars // 4,
                "preview": behavior[:200] if behavior else "",
            },
            "gate_overrides": {
                "disabled_gates": profile.get("disabled_gates", []),
                "gate_modes": profile.get("gate_modes", {}),
            },
            "auto_detect": profile.get("auto_detect", {}),
            "graduation": profile.get("graduation", {}),
            "token_budget": budget,
            "total_token_usage": token_estimate,
            "over_budget": token_estimate > budget,
            "memory_tags": profile.get("memory_tags", []),
        }

    return result


# ── Framework Health Score ───────────────────────────────────────────────────

@mcp.tool()
@crash_proof
def framework_health_score() -> dict:
    """Compute an overall framework health score (0-100) from multiple signals.

    Aggregates:
    - Test pass rate (from metrics)
    - Gate block rate (from gate effectiveness)
    - Circuit breaker states (from circuit_breaker)
    - Memory system freshness (from sideband file)
    - Pending verification count (from latest state)

    Returns a composite score with per-component breakdown and recommendations.
    """
    _ensure_initialized()
    import json as _json

    scores = {}
    recommendations = []

    # 1. Test pass rate (40% weight)
    try:
        from shared.metrics_collector import get_metric
        tpr = get_metric("test.pass_rate")
        rate = tpr.get("value", 0.0) if tpr else 0.0
        scores["test_pass_rate"] = {
            "value": round(rate, 3),
            "score": min(100, int(rate * 100)),
            "weight": 40,
        }
        if rate < 0.95:
            recommendations.append("Test pass rate below 95% — run tests and fix failures")
    except Exception:
        scores["test_pass_rate"] = {"value": 0, "score": 0, "weight": 40}

    # 2. Circuit breaker health (20% weight)
    try:
        from shared.circuit_breaker import get_all_states, get_all_gate_states
        svc_states = get_all_states()
        gate_states = get_all_gate_states()
        open_count = sum(1 for r in svc_states.values() if r.get("state") == "OPEN")
        open_gates = sum(1 for r in gate_states.values() if r.get("state") == "OPEN")
        total = len(svc_states) + len(gate_states)
        healthy = total - open_count - open_gates if total > 0 else 1
        cb_score = int(100 * (healthy / max(1, total)))
        scores["circuit_breakers"] = {
            "open_services": open_count,
            "open_gates": open_gates,
            "total_tracked": total,
            "score": cb_score,
            "weight": 20,
        }
        if open_count + open_gates > 0:
            recommendations.append(f"{open_count + open_gates} circuit(s) OPEN — investigate failures")
    except Exception:
        scores["circuit_breakers"] = {"score": 100, "weight": 20}

    # 3. Memory system freshness (20% weight)
    try:
        _sideband = os.path.join(_HOOKS_DIR, ".memory_last_queried")
        if os.path.exists(_sideband):
            import time as _time
            with open(_sideband) as f:
                sb_data = _json.load(f)
            age_sec = _time.time() - sb_data.get("timestamp", 0)
            # Fresh = within 5 min, stale > 30 min
            if age_sec < 300:
                mem_score = 100
            elif age_sec < 1800:
                mem_score = max(50, 100 - int((age_sec - 300) / 15))
            else:
                mem_score = max(0, 50 - int((age_sec - 1800) / 60))
        else:
            mem_score = 0
        scores["memory_freshness"] = {
            "age_seconds": int(age_sec) if os.path.exists(_sideband) else -1,
            "score": mem_score,
            "weight": 20,
        }
        if mem_score < 50:
            recommendations.append("Memory system stale — query search_knowledge()")
    except Exception:
        scores["memory_freshness"] = {"score": 50, "weight": 20}

    # 4. Gate effectiveness (20% weight)
    try:
        eff_path = os.path.join(_HOOKS_DIR, ".gate_effectiveness.json")
        if os.path.exists(eff_path):
            with open(eff_path) as f:
                eff = _json.load(f)
            total_blocks = sum(v.get("blocks", 0) + v.get("block", 0) for v in eff.values())
            total_overrides = sum(v.get("overrides", 0) + v.get("override", 0) for v in eff.values())
            total_prevented = sum(v.get("prevented", 0) for v in eff.values())
            # High prevention = good, high override = concerning
            if total_blocks > 0:
                prevention_rate = total_prevented / max(1, total_blocks)
                override_rate = total_overrides / max(1, total_blocks)
                gate_score = min(100, int(80 + prevention_rate * 20 - override_rate * 40))
            else:
                gate_score = 80
        else:
            gate_score = 80
        scores["gate_effectiveness"] = {
            "score": max(0, gate_score),
            "weight": 20,
        }
    except Exception:
        scores["gate_effectiveness"] = {"score": 80, "weight": 20}

    # Compute weighted average
    total_weight = sum(s.get("weight", 0) for s in scores.values())
    weighted_sum = sum(s.get("score", 0) * s.get("weight", 0) for s in scores.values())
    overall = int(weighted_sum / max(1, total_weight))

    grade = "A" if overall >= 90 else "B" if overall >= 75 else "C" if overall >= 60 else "D" if overall >= 40 else "F"

    return {
        "overall_score": overall,
        "grade": grade,
        "components": scores,
        "recommendations": recommendations,
    }


# ── Session Context Snapshot ─────────────────────────────────────────────────

@mcp.tool()
@crash_proof
def session_context_snapshot() -> dict:
    """Generate a compressed snapshot of the current session state.

    Combines session compressor output with key decisions and handoff data.
    Useful for mid-session status checks and context preservation.
    """
    _ensure_initialized()
    import json as _json

    # Load current state from ramdisk
    state = {}
    try:
        from shared.ramdisk import get_state_dir
        state_dir = get_state_dir()
        import glob as _glob2
        state_files = sorted(_glob2.glob(os.path.join(state_dir, "state_*.json")),
                            key=os.path.getmtime, reverse=True)
        if state_files:
            with open(state_files[0]) as f:
                state = _json.load(f)
    except Exception:
        pass

    from shared.session_compressor import (
        compress_session_context, extract_key_decisions, format_handoff,
    )

    compressed = compress_session_context(state)
    decisions = extract_key_decisions(state)
    handoff = format_handoff(state, decisions)

    # Extract key counters
    files_edited = len(state.get("files_edited", []))
    pending = len(state.get("pending_verification", []))
    verified = len(state.get("verified_fixes", []))
    chains = len(state.get("pending_chain_ids", []))
    bans = state.get("active_bans", [])

    return {
        "compressed_context": compressed,
        "decisions": decisions,
        "handoff": handoff,
        "counters": {
            "files_edited": files_edited,
            "pending_verification": pending,
            "verified_fixes": verified,
            "open_chains": chains,
            "active_bans": bans,
            "gate6_warns": state.get("gate6_warn_count", 0),
        },
    }


# ── Tool Recommendation ───────────────────────────────────────────────────────

@mcp.tool()
@crash_proof
def tool_recommendations(tool_name: str = "") -> dict:
    """Analyze tool call patterns and recommend alternatives for blocked tools.

    When a tool has a high block rate, suggests equivalent tools with better
    success rates or intermediate steps (e.g., Read before Edit).

    Args:
        tool_name: Specific tool to get recommendation for. If empty, returns
                   overview stats for all tools.

    Returns:
        Dict with recommendation details or summary statistics.
    """
    _ensure_initialized()
    import json as _json

    # Load current state from ramdisk
    state = {}
    try:
        from shared.ramdisk import get_state_dir
        state_dir = get_state_dir()
        import glob as _glob3
        state_files = sorted(_glob3.glob(os.path.join(state_dir, "state_*.json")),
                            key=os.path.getmtime, reverse=True)
        if state_files:
            with open(state_files[0]) as f:
                state = _json.load(f)
    except Exception:
        pass

    from shared.tool_recommendation import (
        build_tool_profile, recommend_alternative,
        get_recommendation_stats, should_recommend,
    )

    if not tool_name:
        # Return overview stats
        stats = get_recommendation_stats(state)
        profiles = build_tool_profile(state)
        profile_data = {}
        for name, p in profiles.items():
            if p.call_count > 0:
                profile_data[name] = {
                    "calls": p.call_count,
                    "blocks": p.block_count,
                    "success_rate": round(p.success_rate, 3),
                    "block_rate": round(p.block_rate, 3),
                }
        return {
            "stats": stats,
            "profiles": profile_data,
        }

    # Get recommendation for specific tool
    rec = recommend_alternative(tool_name, state)
    needs_rec = should_recommend(tool_name, state)

    profiles = build_tool_profile(state)
    profile = profiles.get(tool_name)

    result = {
        "tool": tool_name,
        "needs_recommendation": needs_rec,
        "profile": None,
        "recommendation": None,
    }

    if profile:
        result["profile"] = {
            "calls": profile.call_count,
            "blocks": profile.block_count,
            "success_rate": round(profile.success_rate, 3),
            "block_rate": round(profile.block_rate, 3),
        }

    if rec:
        result["recommendation"] = {
            "suggested_tool": rec.suggested_tool,
            "reason": rec.reason,
            "confidence": round(rec.confidence, 3),
            "improvement": round(rec.suggested_success - rec.original_success, 3),
        }

    return result


# ── Health Correlation ────────────────────────────────────────────────────────

@mcp.tool()
@crash_proof
def gate_correlation_report() -> dict:
    """Analyze gate fire patterns to detect redundancy and synergy.

    Builds a Pearson correlation matrix of gate block patterns, identifies
    redundant gate pairs (r>0.8) and synergistic pairs (r<-0.5), then
    generates optimization recommendations.

    Returns:
        Dict with gates_analyzed, redundant_pairs, synergistic_pairs,
        optimizations, and overall_diversity score.
    """
    _ensure_initialized()
    import json as _json

    # Load gate effectiveness data
    eff_path = os.path.join(_HOOKS_DIR, ".gate_effectiveness.json")
    effectiveness = {}
    try:
        if os.path.exists(eff_path):
            with open(eff_path) as f:
                effectiveness = _json.load(f)
    except Exception:
        pass

    if not effectiveness:
        return {
            "gates_analyzed": 0,
            "message": "No gate effectiveness data available",
        }

    from shared.health_correlation import generate_health_report
    return generate_health_report(effectiveness)


@mcp.tool()
@crash_proof
def causal_chain_analysis() -> dict:
    """Analyze causal chain fix outcomes to detect patterns and suggest improvements.

    Cross-references fix_outcomes data from memory to identify recurring failures,
    ineffective strategies, and suggest better approaches. Reports overall chain
    health with a composite score (0-100).

    Returns:
        Dict with strategy_effectiveness, recurring_failures, chain_health
        (score, trend, recommendations), and a one-line summary.
    """
    _ensure_initialized()
    from shared.chain_refinement import analyze_outcomes

    # Load fix outcomes from memory's LanceDB table
    outcomes = []
    try:
        import lancedb
        db_path = os.path.join(os.path.expanduser("~"), "data", "memory", "lancedb")
        db = lancedb.connect(db_path)
        if "fix_outcomes" in db.table_names():
            tbl = db.open_table("fix_outcomes")
            rows = tbl.to_pandas().to_dict("records")
            outcomes = rows
    except Exception:
        pass

    if not outcomes:
        return {
            "total_outcomes": 0,
            "message": "No fix_outcomes data available in LanceDB",
            "chain_health": {"health_score": 50.0, "recommendations": ["Start tracking fix outcomes"]},
        }

    result = analyze_outcomes(outcomes)
    # Serialize dataclasses for JSON transport
    from dataclasses import asdict
    health = asdict(result["chain_health"])
    effectiveness = {k: asdict(v) for k, v in result["strategy_effectiveness"].items()}
    recurring = [asdict(p) for p in result["recurring_failures"]]

    return {
        "total_outcomes": len(outcomes),
        "strategy_effectiveness": effectiveness,
        "recurring_failures": recurring,
        "chain_health": health,
        "summary": result["summary"],
    }


# ── R:W Ratio & Frustration ───────────────────────────────────────────────────

@mcp.tool()
@crash_proof
def rw_ratio(session_id: str = "") -> dict:
    """Read:Write ratio for current session. Rating: good (>=4), fair (>=2), poor (<2)."""
    _ensure_initialized()
    from shared.session_analytics import compute_rw_ratio
    from shared.state import load_state
    sid = _resolve_session_id(session_id)
    state = load_state(session_id=sid)
    return compute_rw_ratio(state)


@mcp.tool()
@crash_proof
def frustration_report(session_id: str = "") -> dict:
    """Session frustration: band (calm/friction/frustrated), trend (rising/falling/stable)."""
    _ensure_initialized()
    from shared.session_analytics import aggregate_frustration
    sid = _resolve_session_id(session_id) if session_id else None
    return aggregate_frustration(session_id=sid)


@mcp.tool()
@crash_proof
def skill_invocation_report(session_id: str = "") -> dict:
    """Skill usage this session: which skills invoked and how many times."""
    _ensure_initialized()
    from shared.state import load_state
    sid = _resolve_session_id(session_id)
    state = load_state(session_id=sid)
    return {
        "skill_usage": state.get("skill_usage", {}),
        "recent_skills": state.get("recent_skills", [])[-10:],
        "total_invocations": sum(state.get("skill_usage", {}).values()),
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
