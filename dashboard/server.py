#!/usr/bin/env python3
"""Self-Healing Claude Framework — Web UI Dashboard

Read-only monitoring dashboard served via Starlette + Uvicorn.
Visualizes audit logs, gate statistics, memory, session state, and health.

Start: python3 ~/.claude/dashboard/server.py
Browse: http://localhost:7777

IMPORTANT: This server NEVER writes to any framework files.
All access is strictly read-only.
"""

import asyncio
import json
import os
import glob as globmod
import time
from datetime import datetime, timezone
from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, RedirectResponse, PlainTextResponse
from starlette.routing import Route, Mount, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocketDisconnect

try:
    from sse_starlette.sse import EventSourceResponse
    SSE_AVAILABLE = True
except ImportError:
    SSE_AVAILABLE = False

import sys as _sys
_sys.path.insert(0, os.path.join(os.path.expanduser("~/.claude"), "hooks"))
from shared.chromadb_socket import (
    count as socket_count, query as socket_query, get as socket_get,
    is_worker_available, WorkerUnavailable,
)

# ── Standalone fallback ──────────────────────────────────────────
# When UDS socket is unavailable (MCP server not running), the dashboard
# can safely create its own PersistentClient since no other process holds one.
_standalone_client = None
_standalone_collections = {}

def _get_standalone_collection(name):
    """Lazy-init a read-only ChromaDB collection for standalone mode."""
    global _standalone_client
    if _standalone_client is None:
        import chromadb
        _standalone_client = chromadb.PersistentClient(path=MEMORY_DIR)
    if name not in _standalone_collections:
        _standalone_collections[name] = _standalone_client.get_or_create_collection(
            name=name, metadata={"hnsw:space": "cosine"}
        )
    return _standalone_collections[name]

def _standalone_count(collection="knowledge"):
    """Count via direct ChromaDB (standalone fallback)."""
    return _get_standalone_collection(collection).count()

def _standalone_query(collection, query_texts, n_results=5, include=None):
    """Query via direct ChromaDB (standalone fallback)."""
    col = _get_standalone_collection(collection)
    kwargs = {"query_texts": query_texts, "n_results": n_results}
    if include:
        kwargs["include"] = include
    return col.query(**kwargs)

def _standalone_get(collection, ids=None, limit=None, include=None):
    """Get via direct ChromaDB (standalone fallback)."""
    col = _get_standalone_collection(collection)
    kwargs = {}
    if ids is not None:
        kwargs["ids"] = ids
    if limit is not None:
        kwargs["limit"] = limit
    if include is not None:
        kwargs["include"] = include
    return col.get(**kwargs)

def safe_count(collection="knowledge"):
    """Count with UDS-first, standalone fallback."""
    try:
        return socket_count(collection)
    except (WorkerUnavailable, RuntimeError):
        return _standalone_count(collection)

def safe_query(collection, query_texts, n_results=5, include=None):
    """Query with UDS-first, standalone fallback."""
    try:
        return socket_query(collection, query_texts, n_results=n_results, include=include)
    except (WorkerUnavailable, RuntimeError):
        return _standalone_query(collection, query_texts, n_results=n_results, include=include)

def safe_get(collection, ids=None, limit=None, include=None):
    """Get with UDS-first, standalone fallback."""
    try:
        return socket_get(collection, ids=ids, limit=limit, include=include)
    except (WorkerUnavailable, RuntimeError):
        return _standalone_get(collection, ids=ids, limit=limit, include=include)

# ── Paths ────────────────────────────────────────────────────────
CLAUDE_DIR = os.path.expanduser("~/.claude")
HOOKS_DIR = os.path.join(CLAUDE_DIR, "hooks")
GATES_DIR = os.path.join(HOOKS_DIR, "gates")
AUDIT_DIR = os.path.join(HOOKS_DIR, "audit")
SKILLS_DIR = os.path.join(CLAUDE_DIR, "skills")
AGENTS_DIR = os.path.join(CLAUDE_DIR, "agents")
ARCHIVE_DIR = os.path.join(CLAUDE_DIR, "archive")
LIVE_STATE_FILE = os.path.join(CLAUDE_DIR, "LIVE_STATE.json")
SETTINGS_FILE = os.path.join(CLAUDE_DIR, "settings.json")
STATS_CACHE = os.path.join(CLAUDE_DIR, "stats-cache.json")
MEMORY_DIR = os.path.join(os.path.expanduser("~"), "data", "memory")
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
SNAPSHOT_FILE = os.path.join(HOOKS_DIR, ".statusline_snapshot.json")

# ── Toggle whitelist ─────────────────────────────────────────────
TOGGLE_KEYS = {
    "terminal_l2_always", "context_enrichment", "tg_l3_always",
    "tg_enrichment", "tg_bot_tmux", "gate_auto_tune", "chain_memory",
    "tg_session_notify", "tg_mirror_messages", "budget_degradation",
    "session_token_budget",
}

# Expected types per toggle (for POST validation)
TOGGLE_TYPES = {
    "terminal_l2_always": bool,
    "context_enrichment": bool,
    "tg_l3_always": bool,
    "tg_enrichment": bool,
    "tg_bot_tmux": bool,
    "gate_auto_tune": bool,
    "chain_memory": bool,
    "tg_session_notify": bool,
    "tg_mirror_messages": bool,
    "budget_degradation": bool,
    "session_token_budget": int,
}

# ── Chat session storage ─────────────────────────────────────────
chat_sessions = {}  # chat_id -> claude session_id

# ── Constants (mirrored from statusline.py) ──────────────────────
EXPECTED_GATES = 12
EXPECTED_SKILLS = 9
EXPECTED_HOOK_EVENTS = 13

# ── Gate name normalization ───────────────────────────────────────
# Historical audit logs may contain module-path gate names (e.g.,
# "gates.gate_01_read_before_edit") instead of canonical display names.
# This map normalizes at read-time so dashboards show consistent names
# without rewriting the source-of-truth JSONL files.
GATE_NAME_NORMALIZATION = {
    "gates.gate_01_read_before_edit": "GATE 1: READ BEFORE EDIT",
    "gates.gate_02_no_destroy": "GATE 2: NO DESTROY",
    "gates.gate_03_test_before_deploy": "GATE 3: TEST BEFORE DEPLOY",
    "gates.gate_04_memory_first": "GATE 4: MEMORY FIRST",
    "gates.gate_05_proof_before_fixed": "GATE 5: PROOF BEFORE FIXED",
    "gates.gate_06_save_fix": "GATE 6: SAVE VERIFIED FIX",
    "gates.gate_07_critical_file_guard": "GATE 7: CRITICAL FILE GUARD",
    "gates.gate_08_temporal": "GATE 8: TEMPORAL AWARENESS",
    "gates.gate_09_strategy_ban": "GATE 9: STRATEGY BAN",
    "gates.gate_10_model_enforcement": "GATE 10: MODEL COST GUARD",
    "gates.gate_11_rate_limit": "GATE 11: RATE LIMIT",
    "gates.gate_12_plan_mode_save": "GATE 12: PLAN MODE SAVE",
    "gates.gate_13_workspace_isolation": "GATE 13: WORKSPACE ISOLATION",
}


def normalize_gate_name(raw):
    """Normalize a gate name from module-path to canonical display name.

    Returns the canonical name if a mapping exists, otherwise returns
    the original value unchanged.
    """
    if not raw:
        return raw
    return GATE_NAME_NORMALIZATION.get(raw, raw)


# ── Helper functions (reimplemented from statusline.py) ──────────

def _read_json(path):
    """Safely read and parse a JSON file."""
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _read_latest_state():
    """Read the most recent session state file."""
    state_dir = HOOKS_DIR
    files = globmod.glob(os.path.join(state_dir, "state_*.json"))
    if not files:
        return None
    files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
    try:
        with open(files[0]) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


DORMANT_GATES = {"gate_08_temporal.py", "gate_12_plan_mode_save.py"}

def count_gates():
    if not os.path.isdir(GATES_DIR):
        return 0
    return len([f for f in os.listdir(GATES_DIR)
                if f.startswith("gate_") and f.endswith(".py") and f not in DORMANT_GATES])


def count_skills():
    if not os.path.isdir(SKILLS_DIR):
        return 0
    count = 0
    for entry in os.listdir(SKILLS_DIR):
        if os.path.isfile(os.path.join(SKILLS_DIR, entry, "SKILL.md")):
            count += 1
    return count


def count_hook_events():
    settings = _read_json(SETTINGS_FILE)
    if settings:
        return len(settings.get("hooks", {}))
    return 0


def get_error_pressure():
    pattern = os.path.join(HOOKS_DIR, "state_*.json")
    files = globmod.glob(pattern)
    if not files:
        return 0
    files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
    state = _read_json(files[0])
    if state:
        counts = state.get("error_pattern_counts", {})
        return sum(counts.values()) if counts else 0
    return 0


def get_memory_count():
    """Get curated memory count (cached). UDS-first, standalone fallback."""
    try:
        if os.path.exists(STATS_CACHE):
            cache = _read_json(STATS_CACHE)
            if cache and time.time() - cache.get("ts", 0) < 60:
                return cache.get("mem_count", 0)
    except Exception:
        pass
    try:
        cnt = safe_count("knowledge")
        try:
            tmp = STATS_CACHE + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"ts": time.time(), "mem_count": cnt}, f)
            os.replace(tmp, STATS_CACHE)
        except OSError:
            pass
        return cnt
    except Exception:
        return 0


def calculate_health(gate_count, mem_count):
    """Weighted health percentage (mirrors statusline.py:162-217)."""
    scores = {}
    scores["gates"] = (min(gate_count / max(EXPECTED_GATES, 1), 1.0), 25)

    hook_count = count_hook_events()
    scores["hooks"] = (min(hook_count / max(EXPECTED_HOOK_EVENTS, 1), 1.0), 20)

    if isinstance(mem_count, int) and mem_count > 0:
        scores["memory"] = (1.0, 15)
    else:
        scores["memory"] = (0.0, 15)

    skill_count = count_skills()
    scores["skills"] = (min(skill_count / max(EXPECTED_SKILLS, 1), 1.0), 15)

    core_files = [
        os.path.join(CLAUDE_DIR, "CLAUDE.md"),
        LIVE_STATE_FILE,
        os.path.join(HOOKS_DIR, "enforcer.py"),
    ]
    core_present = sum(1 for f in core_files if os.path.isfile(f))
    scores["core"] = (core_present / len(core_files), 15)

    errors = get_error_pressure()
    if errors == 0:
        scores["errors"] = (1.0, 10)
    elif errors <= 2:
        scores["errors"] = (0.7, 10)
    elif errors <= 5:
        scores["errors"] = (0.4, 10)
    else:
        scores["errors"] = (0.1, 10)

    total = sum(s * w for s, w in scores.values())
    max_total = sum(w for _, w in scores.values())
    health_pct = int(total / max_total * 100) if max_total > 0 else 0
    return health_pct, scores


def health_color_name(pct):
    if pct >= 100:
        return "cyan"
    if pct >= 90:
        return "green"
    if pct >= 75:
        return "orange"
    if pct >= 50:
        return "yellow"
    return "red"


# ── Audit log parsing ────────────────────────────────────────────

def parse_audit_line(line):
    """Parse a single JSONL line, normalizing both Type A and Type B schemas."""
    try:
        entry = json.loads(line.strip())
    except (json.JSONDecodeError, ValueError):
        return None

    # Type B: gate decision (has "gate" key)
    if "gate" in entry:
        return {
            "type": "gate",
            "timestamp": entry.get("timestamp", ""),
            "ts": _iso_to_epoch(entry.get("timestamp", "")),
            "gate": normalize_gate_name(entry.get("gate", "")),
            "tool": entry.get("tool", ""),
            "decision": entry.get("decision", ""),
            "reason": entry.get("reason", ""),
            "session_id": entry.get("session_id", ""),
            "state_keys": entry.get("state_keys", []),
            "severity": entry.get("severity", "info"),
        }

    # Type A: event (has "event" key)
    if "event" in entry:
        ts = entry.get("ts", 0)
        return {
            "type": "event",
            "timestamp": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else "",
            "ts": ts,
            "event": entry.get("event", ""),
            "data": entry.get("data", {}),
        }

    return None


def _iso_to_epoch(iso_str):
    """Convert ISO 8601 timestamp to epoch seconds."""
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.timestamp()
    except (ValueError, TypeError):
        return 0


def load_audit_entries(date_str=None, limit=200, offset=0):
    """Load and parse audit entries for a given date."""
    if not date_str:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filepath = os.path.join(AUDIT_DIR, f"{date_str}.jsonl")
    if not os.path.isfile(filepath):
        return [], 0

    entries = []
    try:
        with open(filepath) as f:
            for line in f:
                parsed = parse_audit_line(line)
                if parsed:
                    entries.append(parsed)
    except OSError:
        return [], 0

    total = len(entries)
    # Reverse chronological order
    entries.reverse()
    return entries[offset:offset + limit], total


def get_audit_dates():
    """List available audit log dates."""
    if not os.path.isdir(AUDIT_DIR):
        return []
    dates = []
    for f in sorted(os.listdir(AUDIT_DIR), reverse=True):
        if f.endswith(".jsonl"):
            dates.append(f.replace(".jsonl", ""))
    return dates


def aggregate_gate_stats(date_str=None):
    """Aggregate pass/block/warn counts per gate from audit log."""
    if not date_str:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filepath = os.path.join(AUDIT_DIR, f"{date_str}.jsonl")
    stats = {}
    if not os.path.isfile(filepath):
        return stats
    try:
        with open(filepath) as f:
            for line in f:
                parsed = parse_audit_line(line)
                if parsed and parsed["type"] == "gate":
                    gate = parsed["gate"]
                    decision = parsed["decision"]
                    if gate not in stats:
                        stats[gate] = {"pass": 0, "block": 0, "warn": 0, "total": 0}
                    if decision in stats[gate]:
                        stats[gate][decision] += 1
                    stats[gate]["total"] += 1
    except OSError:
        pass
    return stats


def aggregate_gate_perf(date_str=None):
    """Aggregate per-gate performance metrics including block rate and timing."""
    if not date_str:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filepath = os.path.join(AUDIT_DIR, f"{date_str}.jsonl")
    stats = {}
    if not os.path.isfile(filepath):
        return []
    try:
        with open(filepath) as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                except (json.JSONDecodeError, ValueError):
                    continue
                # Type B: has "gate" key
                gate = normalize_gate_name(entry.get("gate", ""))
                if not gate:
                    continue
                decision = entry.get("decision", "")
                if gate not in stats:
                    stats[gate] = {"pass": 0, "block": 0, "warn": 0, "total": 0,
                                   "durations": []}
                if decision in ("pass", "block", "warn"):
                    stats[gate][decision] += 1
                stats[gate]["total"] += 1
                duration = entry.get("gate_duration_ms")
                if duration is not None:
                    try:
                        stats[gate]["durations"].append(float(duration))
                    except (ValueError, TypeError):
                        pass
    except OSError:
        pass

    result = []
    for gate_name in sorted(stats.keys()):
        s = stats[gate_name]
        total = s["total"] or 1
        block_rate = round(s["block"] / total * 100, 1)
        avg_dur = None
        if s["durations"]:
            avg_dur = round(sum(s["durations"]) / len(s["durations"]), 2)
        result.append({
            "gate": gate_name,
            "pass": s["pass"],
            "block": s["block"],
            "warn": s["warn"],
            "total": s["total"],
            "block_rate": block_rate,
            "avg_duration_ms": avg_dur,
        })
    return result


def load_audit_entries_filtered(gate=None, decision=None, tool=None, severity=None, hours=24, limit=200):
    """Load audit entries with optional filters across recent JSONL files."""
    cutoff = time.time() - (hours * 3600)
    entries = []
    if not os.path.isdir(AUDIT_DIR):
        return entries

    # Gather relevant audit files (sorted newest first)
    files = sorted(
        [f for f in os.listdir(AUDIT_DIR) if f.endswith(".jsonl")],
        reverse=True,
    )

    for fname in files:
        filepath = os.path.join(AUDIT_DIR, fname)
        try:
            with open(filepath) as f:
                for line in f:
                    parsed = parse_audit_line(line)
                    if not parsed:
                        continue
                    # Time filter
                    if parsed.get("ts", 0) and parsed["ts"] < cutoff:
                        continue
                    # Gate filter
                    if gate and parsed.get("gate", "") != gate:
                        continue
                    # Decision filter
                    if decision and parsed.get("decision", "") != decision:
                        continue
                    # Tool filter
                    if tool and parsed.get("tool", "") != tool:
                        continue
                    # Severity filter
                    if severity and parsed.get("severity", "") != severity:
                        continue
                    entries.append(parsed)
        except OSError:
            continue

    # Most recent first, limited
    entries.sort(key=lambda e: e.get("ts", 0), reverse=True)
    return entries[:limit]


# ── API Endpoints ────────────────────────────────────────────────

async def api_health(request):
    gate_count = count_gates()
    mem_count = get_memory_count()
    health_pct, dimensions = calculate_health(gate_count, mem_count)
    dim_details = {}
    for name, (score, weight) in dimensions.items():
        dim_details[name] = {
            "score": round(score, 3),
            "weight": weight,
            "weighted": round(score * weight, 1),
        }
    live = _read_json(LIVE_STATE_FILE) or {}
    return JSONResponse({
        "health_pct": health_pct,
        "color": health_color_name(health_pct),
        "dimensions": dim_details,
        "project": live.get("project", "unknown"),
        "session_count": live.get("session_count", 0),
        "status": live.get("status", "unknown"),
        "gate_count": gate_count,
        "mem_count": mem_count,
    })


async def api_health_score(request):
    """Lightweight health score endpoint for external monitoring."""
    import glob as glob_mod
    hooks_dir = os.path.join(CLAUDE_DIR, "hooks")

    # Dimension 1: Gates (25%) — count gate files
    gates_dir = os.path.join(hooks_dir, "gates")
    gate_count = len(glob_mod.glob(os.path.join(gates_dir, "gate_*.py"))) if os.path.isdir(gates_dir) else 0
    expected_gates = 12
    gates_score = min(100, int(gate_count / expected_gates * 100))

    # Dimension 2: Hooks (20%) — check key hook files exist
    hook_files = ["enforcer.py", "tracker.py", "boot.py", "statusline.py", "pre_compact.py"]
    hooks_present = sum(1 for f in hook_files if os.path.isfile(os.path.join(hooks_dir, f)))
    hooks_score = min(100, int(hooks_present / len(hook_files) * 100))

    # Dimension 3: Memory (15%) — check memory directory
    memory_dir = os.path.join(os.path.expanduser("~"), "data", "memory")
    memory_score = 100 if os.path.isdir(memory_dir) else 0

    # Dimension 4: Skills (15%) — check skills directory
    skills_dir = os.path.join(CLAUDE_DIR, "skills")
    skill_count = len(os.listdir(skills_dir)) if os.path.isdir(skills_dir) else 0
    skills_score = min(100, int(skill_count / max(1, 5) * 100))  # expect ~5 skills

    # Dimension 5: Core (15%) — check critical shared modules
    core_files = ["shared/state.py", "shared/gate_result.py", "shared/audit_log.py"]
    core_present = sum(1 for f in core_files if os.path.isfile(os.path.join(hooks_dir, f)))
    core_score = min(100, int(core_present / len(core_files) * 100))

    # Dimension 6: Errors (10%) — check recent error patterns
    state = _read_latest_state()
    error_counts = state.get("error_pattern_counts", {}) if state else {}
    total_errors = sum(error_counts.values()) if error_counts else 0
    errors_score = max(0, 100 - total_errors * 20)  # -20 per error pattern

    # Weighted average
    health_pct = int(
        gates_score * 0.25 +
        hooks_score * 0.20 +
        memory_score * 0.15 +
        skills_score * 0.15 +
        core_score * 0.15 +
        errors_score * 0.10
    )
    health_pct = max(0, min(100, health_pct))

    dimensions = {
        "gates": gates_score,
        "hooks": hooks_score,
        "memory": memory_score,
        "skills": skills_score,
        "core": core_score,
        "errors": errors_score,
    }

    return JSONResponse({
        "health_pct": health_pct,
        "dimensions": dimensions,
        "timestamp": time.time(),
    })


async def api_live_state(request):
    state = _read_json(LIVE_STATE_FILE)
    if state is None:
        return JSONResponse({"error": "LIVE_STATE.json not found"}, status_code=404)
    return JSONResponse(state)


async def api_session(request):
    pattern = os.path.join(HOOKS_DIR, "state_*.json")
    files = globmod.glob(pattern)
    if not files:
        return JSONResponse({"error": "No session state found"}, status_code=404)
    files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
    state = _read_json(files[0])
    if state is None:
        return JSONResponse({"error": "Failed to read session state"}, status_code=500)
    state["_file"] = os.path.basename(files[0])
    return JSONResponse(state)


async def api_audit(request):
    date_str = request.query_params.get("date", "")
    limit = min(int(request.query_params.get("limit", "200")), 1000)
    offset = int(request.query_params.get("offset", "0"))
    entries, total = load_audit_entries(date_str or None, limit, offset)
    return JSONResponse({
        "entries": entries,
        "total": total,
        "limit": limit,
        "offset": offset,
        "date": date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    })


async def api_audit_dates(request):
    return JSONResponse({"dates": get_audit_dates()})


async def api_gates(request):
    date_str = request.query_params.get("date", "")
    stats = aggregate_gate_stats(date_str or None)
    # Sort by gate number
    sorted_stats = dict(sorted(stats.items(), key=lambda x: x[0]))
    return JSONResponse({"gates": sorted_stats, "date": date_str or "today"})


async def api_memories_search(request):
    query = request.query_params.get("q", "")
    limit = min(int(request.query_params.get("limit", "20")), 100)
    offset = int(request.query_params.get("offset", "0"))
    try:
        if not query:
            cnt = safe_count("knowledge")
            results = safe_get("knowledge", limit=min(limit, cnt), include=["metadatas"])
            entries = []
            ids = results.get("ids", [])
            metas = results.get("metadatas", [])
            for i, mid in enumerate(ids):
                meta = metas[i] if i < len(metas) else {}
                entries.append({
                    "id": mid, "preview": meta.get("preview", ""),
                    "tags": meta.get("tags", ""), "timestamp": meta.get("timestamp", ""),
                })
            return JSONResponse({"results": entries, "total": cnt, "query": ""})

        cnt = safe_count("knowledge")
        actual_k = min(limit + offset, cnt)
        if actual_k == 0:
            return JSONResponse({"results": [], "total": 0, "query": query})
        results = safe_query("knowledge", [query], n_results=actual_k,
                             include=["metadatas", "distances"])
        entries = []
        ids = results.get("ids", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        for i, mid in enumerate(ids):
            meta = metas[i] if i < len(metas) else {}
            dist = distances[i] if i < len(distances) else 1.0
            entries.append({
                "id": mid, "preview": meta.get("preview", ""),
                "tags": meta.get("tags", ""), "timestamp": meta.get("timestamp", ""),
                "relevance": round(1 - dist, 3),
            })
        sliced = entries[offset:offset + limit]
        return JSONResponse({"results": sliced, "total": cnt, "query": query})
    except Exception as e:
        return JSONResponse({"error": str(e), "results": []}, status_code=500)


async def api_memory_detail(request):
    mem_id = request.path_params["id"]
    try:
        result = safe_get("knowledge", ids=[mem_id], include=["documents", "metadatas"])
        if not result or not result.get("documents") or not result["documents"]:
            return JSONResponse({"error": "Not found"}, status_code=404)
        meta = result["metadatas"][0] if result.get("metadatas") else {}
        return JSONResponse({
            "id": mem_id, "content": result["documents"][0],
            "context": meta.get("context", ""), "tags": meta.get("tags", ""),
            "timestamp": meta.get("timestamp", ""),
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def api_memories_stats(request):
    stats = {}
    for name in ("knowledge", "observations", "fix_outcomes"):
        try:
            stats[name] = safe_count(name)
        except Exception:
            stats[name] = -1
    return JSONResponse(stats)


async def api_memories_tags(request):
    """Get tag frequency distribution from knowledge collection."""
    try:
        cnt = safe_count("knowledge")
        if cnt == 0:
            return JSONResponse({"tags": {}})
        results = safe_get("knowledge", limit=min(cnt, 500), include=["metadatas"])
        tag_freq = {}
        metas = results.get("metadatas", [])
        for meta in metas:
            if meta and meta.get("tags"):
                for tag in meta["tags"].split(","):
                    tag = tag.strip()
                    if tag:
                        tag_freq[tag] = tag_freq.get(tag, 0) + 1
        sorted_tags = dict(sorted(tag_freq.items(), key=lambda x: -x[1]))
        return JSONResponse({"tags": sorted_tags, "total_memories": cnt})
    except Exception as e:
        return JSONResponse({"tags": {}, "error": str(e)}, status_code=500)


async def api_memories_graph(request):
    """Build a tag co-occurrence graph from knowledge collection."""
    try:
        cnt = safe_count("knowledge")
        if cnt == 0:
            return JSONResponse({"nodes": [], "edges": []})
        results = safe_get("knowledge", limit=min(cnt, 500), include=["metadatas"])
        metas = results.get("metadatas", [])
        tag_freq = {}
        co_occur = {}
        for meta in metas:
            if not meta or not meta.get("tags"):
                continue
            tags = [t.strip() for t in meta["tags"].split(",") if t.strip()]
            for tag in tags:
                tag_freq[tag] = tag_freq.get(tag, 0) + 1
            for i in range(len(tags)):
                for j in range(i + 1, len(tags)):
                    pair = tuple(sorted([tags[i], tags[j]]))
                    co_occur[pair] = co_occur.get(pair, 0) + 1
        sorted_tags = sorted(tag_freq.items(), key=lambda x: -x[1])[:50]
        top_tag_set = {t for t, _ in sorted_tags}
        nodes = [{"id": tag, "label": tag, "count": cnt_val} for tag, cnt_val in sorted_tags]
        edges = [
            {"source": pair[0], "target": pair[1], "weight": weight}
            for pair, weight in co_occur.items()
            if pair[0] in top_tag_set and pair[1] in top_tag_set
        ]
        return JSONResponse({"nodes": nodes, "edges": edges})
    except Exception as e:
        return JSONResponse({"nodes": [], "edges": [], "error": str(e)}, status_code=500)


async def api_memory_health(request):
    """Memory health report (UDS-first, standalone fallback)."""
    try:
        mem_count = safe_count("knowledge")
        obs_count = safe_count("observations")
    except Exception as e:
        return JSONResponse({"error": str(e), "health_score": 0}, status_code=500)

    now = time.time()
    if mem_count == 0:
        return JSONResponse({
            "total_memories": 0, "total_observations": obs_count,
            "added_24h": 0, "added_7d": 0, "added_30d": 0,
            "stale_count": 0, "top_tags": [], "avg_retrieval_count": 0,
            "growth_rate_per_day": 0, "health_score": 0, "health_label": "empty",
            "score_breakdown": {"recent_activity": 0, "retrieval_rate": 0, "tag_diversity": 0},
        })

    try:
        all_data = safe_get("knowledge", limit=mem_count, include=["metadatas"])
    except Exception as e:
        return JSONResponse({"error": str(e), "health_score": 0}, status_code=500)

    metas = all_data.get("metadatas", [])
    cutoff_24h = now - 86400
    cutoff_7d = now - 7 * 86400
    cutoff_30d = now - 30 * 86400
    cutoff_stale = now - 60 * 86400
    added_24h = added_7d = added_30d = stale_count = 0
    tag_freq = {}
    total_retrieval = 0
    retrieval_entries = 0

    for meta in metas:
        if not meta:
            continue
        session_time = meta.get("session_time")
        if session_time is not None:
            try:
                st = float(session_time)
                if st >= cutoff_24h: added_24h += 1
                if st >= cutoff_7d: added_7d += 1
                if st >= cutoff_30d: added_30d += 1
                rc = int(meta.get("retrieval_count", 0))
                if st < cutoff_stale and rc <= 2: stale_count += 1
            except (ValueError, TypeError):
                pass
        tags_str = meta.get("tags", "")
        if tags_str:
            for tag in tags_str.split(","):
                tag = tag.strip()
                if tag:
                    tag_freq[tag] = tag_freq.get(tag, 0) + 1
        rc = int(meta.get("retrieval_count", 0))
        total_retrieval += rc
        retrieval_entries += 1

    top_tags = sorted(tag_freq.items(), key=lambda x: -x[1])[:10]
    top_tags_list = [{"tag": t, "count": c} for t, c in top_tags]
    avg_retrieval = round(total_retrieval / max(retrieval_entries, 1), 2)
    unique_tags = len(tag_freq)

    if added_7d >= 10: recent_score = 1.0
    elif added_7d >= 5: recent_score = 0.8
    elif added_7d >= 2: recent_score = 0.6
    elif added_7d >= 1: recent_score = 0.4
    else: recent_score = 0.1

    if avg_retrieval >= 3.0: retrieval_score = 1.0
    elif avg_retrieval >= 1.5: retrieval_score = 0.8
    elif avg_retrieval >= 0.5: retrieval_score = 0.5
    elif avg_retrieval >= 0.1: retrieval_score = 0.3
    else: retrieval_score = 0.1

    if unique_tags >= 20: diversity_score = 1.0
    elif unique_tags >= 10: diversity_score = 0.7
    elif unique_tags >= 5: diversity_score = 0.5
    elif unique_tags >= 2: diversity_score = 0.3
    else: diversity_score = 0.1

    health_score = int(recent_score * 40 + retrieval_score * 30 + diversity_score * 30)
    health_score = max(0, min(100, health_score))
    health_label = "healthy" if health_score > 70 else ("moderate" if health_score > 40 else "needs attention")
    growth_rate = round(added_30d / 30, 2)

    return JSONResponse({
        "total_memories": mem_count, "total_observations": obs_count,
        "added_24h": added_24h, "added_7d": added_7d, "added_30d": added_30d,
        "stale_count": stale_count, "top_tags": top_tags_list,
        "unique_tags": unique_tags, "avg_retrieval_count": avg_retrieval,
        "growth_rate_per_day": growth_rate, "health_score": health_score,
        "health_label": health_label,
        "score_breakdown": {
            "recent_activity": round(recent_score * 40, 1),
            "retrieval_rate": round(retrieval_score * 30, 1),
            "tag_diversity": round(diversity_score * 30, 1),
        },
    })


async def api_observations_recent(request):
    """Return last 50 observations from capture queue and/or ChromaDB."""
    results = []

    # First try capture queue file for most recent data
    capture_queue = os.path.join(HOOKS_DIR, ".capture_queue.jsonl")
    if os.path.isfile(capture_queue):
        try:
            with open(capture_queue) as f:
                lines = f.readlines()
            for line in reversed(lines[-100:]):
                try:
                    obs = json.loads(line.strip())
                    meta = obs.get("metadata", {})
                    results.append({
                        "timestamp": meta.get("timestamp", ""),
                        "tool": meta.get("tool_name", "Unknown"),
                        "summary": (obs.get("document", ""))[:150],
                        "sentiment": meta.get("sentiment", ""),
                        "priority": meta.get("priority", "low"),
                        "has_error": meta.get("has_error", "false"),
                        "session_time": meta.get("session_time", 0),
                    })
                except (json.JSONDecodeError, KeyError):
                    continue
        except OSError:
            pass

    # Supplement from ChromaDB observations if we need more
    if len(results) < 50:
        try:
            obs_count = safe_count("observations")
            if obs_count > 0:
                needed = min(50 - len(results), obs_count)
                obs_data = safe_get("observations", limit=needed, include=["documents", "metadatas"])
                docs = obs_data.get("documents", [])
                metas = obs_data.get("metadatas", [])
                for i, doc in enumerate(docs):
                    meta = metas[i] if i < len(metas) else {}
                    results.append({
                        "timestamp": meta.get("timestamp", ""),
                        "tool": meta.get("tool_name", "Unknown"),
                        "summary": (doc or "")[:150],
                        "sentiment": meta.get("sentiment", ""),
                        "priority": meta.get("priority", "low"),
                        "has_error": meta.get("has_error", "false"),
                        "session_time": meta.get("session_time", 0),
                    })
        except Exception:
            pass

    results.sort(key=lambda x: float(x.get("session_time", 0) or 0), reverse=True)
    results = results[:50]
    return JSONResponse({"observations": results, "total": len(results)})


async def api_components(request):
    """Inventory of framework components: gates, hooks, skills, agents, plugins."""
    # Gates
    gates = []
    if os.path.isdir(GATES_DIR):
        for f in sorted(os.listdir(GATES_DIR)):
            if f.startswith("gate_") and f.endswith(".py"):
                path = os.path.join(GATES_DIR, f)
                # Read first docstring line
                desc = ""
                try:
                    with open(path) as fh:
                        for line in fh:
                            if line.strip().startswith('"""') or line.strip().startswith("'''"):
                                desc = line.strip().strip("\"'").strip()
                                break
                except OSError:
                    pass
                gates.append({"file": f, "description": desc})

    # Hook events
    settings = _read_json(SETTINGS_FILE) or {}
    hooks = []
    for event_name, handlers in settings.get("hooks", {}).items():
        for handler in handlers:
            for hook in handler.get("hooks", []):
                hooks.append({
                    "event": event_name,
                    "command": hook.get("command", ""),
                    "timeout": hook.get("timeout", 0),
                })

    # Skills
    skills = []
    if os.path.isdir(SKILLS_DIR):
        for entry in sorted(os.listdir(SKILLS_DIR)):
            skill_file = os.path.join(SKILLS_DIR, entry, "SKILL.md")
            if os.path.isfile(skill_file):
                desc = ""
                purpose = ""
                try:
                    with open(skill_file) as fh:
                        for line in fh:
                            stripped = line.strip()
                            # First # heading becomes description
                            if not desc and stripped.startswith("# "):
                                desc = stripped.lstrip("# ").strip()
                            # First non-empty, non-heading line becomes purpose
                            elif desc and not purpose and stripped and not stripped.startswith("#"):
                                purpose = stripped[:150]
                                break
                except OSError:
                    pass
                skills.append({
                    "name": entry,
                    "description": desc,
                    "purpose": purpose,
                })

    # Agents
    agents = []
    if os.path.isdir(AGENTS_DIR):
        for f in sorted(os.listdir(AGENTS_DIR)):
            if f.endswith(".md"):
                path = os.path.join(AGENTS_DIR, f)
                desc = ""
                try:
                    with open(path) as fh:
                        for line in fh:
                            line = line.strip()
                            if line and not line.startswith("---") and not line.startswith("#"):
                                desc = line[:120]
                                break
                except OSError:
                    pass
                agents.append({"file": f, "name": f.replace(".md", ""), "description": desc})

    # Plugins — read installed_plugins.json for rich plugin discovery
    plugins = []
    plugins_dir = os.path.join(CLAUDE_DIR, "plugins")
    installed_plugins_file = os.path.join(plugins_dir, "installed_plugins.json")
    installed_data = _read_json(installed_plugins_file)
    if installed_data and isinstance(installed_data.get("plugins"), dict):
        for plugin_key, installs in installed_data["plugins"].items():
            # plugin_key is like "pyright-lsp@claude-plugins-official"
            name = plugin_key.split("@")[0] if "@" in plugin_key else plugin_key
            marketplace = plugin_key.split("@")[1] if "@" in plugin_key else ""
            for install_info in (installs if isinstance(installs, list) else [installs]):
                version = install_info.get("version", "unknown")
                install_path = install_info.get("installPath", "")
                scope = install_info.get("scope", "unknown")

                # Determine status by checking if install path exists
                status = "inactive"
                file_count = 0
                if install_path and os.path.isdir(install_path):
                    status = "active"
                    try:
                        file_count = sum(
                            1 for f in os.listdir(install_path)
                            if os.path.isfile(os.path.join(install_path, f))
                        )
                    except OSError:
                        status = "error"
                elif install_path:
                    status = "error"  # path specified but doesn't exist

                plugins.append({
                    "name": name,
                    "version": version,
                    "status": status,
                    "description": f"{scope} plugin from {marketplace}" if marketplace else scope,
                    "file_count": file_count,
                    "marketplace": marketplace,
                })
    else:
        # Fallback to old method
        plugins = [{"name": p, "version": "unknown", "status": "active",
                     "description": "", "file_count": 0, "marketplace": ""}
                    for p in settings.get("enabledPlugins", {}).keys()]

    return JSONResponse({
        "gates": gates,
        "hooks": hooks,
        "skills": skills,
        "agents": agents,
        "plugins": plugins,
        "counts": {
            "gates": len(gates),
            "hooks": len(hooks),
            "skills": len(skills),
            "agents": len(agents),
            "plugins": len(plugins),
        },
    })


async def api_skill_usage(request):
    """Skill invocation counts and recent usage from session state."""
    pattern = os.path.join(HOOKS_DIR, "state_*.json")
    files = globmod.glob(pattern)
    skill_usage = {}
    recent_skills = []
    if files:
        files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
        state = _read_json(files[0]) or {}
        skill_usage = state.get("skill_usage", {})
        recent_skills = state.get("recent_skills", [])

    # Enrich with SKILL.md descriptions
    skill_details = []
    for name, count in sorted(skill_usage.items(), key=lambda x: -x[1]):
        desc = ""
        skill_file = os.path.join(SKILLS_DIR, name, "SKILL.md")
        if os.path.isfile(skill_file):
            try:
                with open(skill_file) as fh:
                    for line in fh:
                        stripped = line.strip()
                        if stripped.startswith("# "):
                            desc = stripped.lstrip("# ").strip()
                            break
            except OSError:
                pass
        # Find last used timestamp from recent_skills
        last_used = None
        for entry in reversed(recent_skills):
            if entry.get("name") == name:
                last_used = entry.get("timestamp")
                break
        skill_details.append({
            "name": name,
            "count": count,
            "description": desc,
            "last_used": last_used,
        })

    return JSONResponse({
        "skills": skill_details,
        "recent": recent_skills[-10:],
        "total_invocations": sum(skill_usage.values()),
    })


async def api_errors(request):
    """Error pattern counts + active bans from session state."""
    pattern = os.path.join(HOOKS_DIR, "state_*.json")
    files = globmod.glob(pattern)
    if not files:
        return JSONResponse({"error_patterns": {}, "active_bans": []})
    files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
    state = _read_json(files[0]) or {}
    return JSONResponse({
        "error_patterns": state.get("error_pattern_counts", {}),
        "active_bans": state.get("active_bans", []),
        "tool_call_count": state.get("tool_call_count", 0),
        "session_id": state.get("_session_id", ""),
    })


async def api_tool_stats(request):
    """Return per-tool call statistics from current session state."""
    state = _read_latest_state()
    tool_stats = state.get("tool_stats", {}) if state else {}
    tool_call_count = state.get("tool_call_count", 0) if state else 0
    # Sort by count descending
    sorted_stats = sorted(tool_stats.items(), key=lambda x: x[1].get("count", 0), reverse=True)
    return JSONResponse({
        "tool_stats": {name: info for name, info in sorted_stats},
        "total_calls": tool_call_count,
    })


async def get_tool_usage(request):
    """Return tool usage statistics from current session state."""
    try:
        import glob
        # Find most recent state_*.json
        pattern = os.path.join(HOOKS_DIR, "state_*.json")
        files = glob.glob(pattern)
        if not files:
            return JSONResponse({
                "total_calls": 0,
                "tool_counts": {},
                "top_tool": None,
            })
        files.sort(key=lambda f: os.path.getmtime(f), reverse=True)

        # Read latest state
        state = _read_json(files[0])
        if not state:
            return JSONResponse({
                "total_calls": 0,
                "tool_counts": {},
                "top_tool": None,
            })

        # Extract tool_call_counts and total_tool_calls
        tool_call_counts = state.get("tool_call_counts", {})
        total_tool_calls = state.get("total_tool_calls", 0)

        # Sort by count descending
        sorted_counts = dict(sorted(tool_call_counts.items(), key=lambda x: x[1], reverse=True))

        # Determine top tool
        top_tool = None
        if sorted_counts:
            top_tool = next(iter(sorted_counts))

        return JSONResponse({
            "total_calls": total_tool_calls,
            "tool_counts": sorted_counts,
            "top_tool": top_tool,
        })
    except Exception:
        return JSONResponse({
            "total_calls": 0,
            "tool_counts": {},
            "top_tool": None,
        })


async def api_gate_timing(request):
    """Return per-gate execution timing stats."""
    state = _read_latest_state()
    timing = state.get("gate_timing_stats", {}) if state else {}
    # Compute avg_ms for each gate
    enriched = {}
    for gate_name, stats in timing.items():
        entry = dict(stats)  # copy
        count = entry.get("count", 0)
        total = entry.get("total_ms", 0.0)
        entry["avg_ms"] = round(total / count, 2) if count > 0 else 0.0
        enriched[gate_name] = entry
    return JSONResponse({"gate_timing_stats": enriched})


async def api_edit_streak(request):
    """Edit streak hotspots: files edited >= 3 times in current session."""
    state = _read_latest_state()
    edit_streak = state.get("edit_streak", {}) if state else {}
    total_files = len(edit_streak)

    # Filter to hotspots (count >= 3)
    hotspots = []
    for path, count in edit_streak.items():
        if isinstance(count, int) and count >= 3:
            hotspots.append({
                "file": os.path.basename(path),
                "path": path,
                "count": count,
            })
    # Sort by count descending
    hotspots.sort(key=lambda x: x["count"], reverse=True)

    num_hotspots = len(hotspots)
    if num_hotspots == 0:
        risk_level = "safe"
    elif num_hotspots <= 2:
        risk_level = "warning"
    else:
        risk_level = "critical"

    return JSONResponse({
        "hotspots": hotspots,
        "total_files": total_files,
        "risk_level": risk_level,
    })


async def api_gate_deps(request):
    """Gate dependency graph: which state keys each gate reads/writes."""
    try:
        import importlib
        import sys as _sys
        _hooks_in_path = HOOKS_DIR in _sys.path
        if not _hooks_in_path:
            _sys.path.insert(0, HOOKS_DIR)
        try:
            import enforcer as _enforcer_mod
            importlib.reload(_enforcer_mod)
            deps = _enforcer_mod.get_gate_dependencies()
        finally:
            if not _hooks_in_path:
                _sys.path.remove(HOOKS_DIR)
        return JSONResponse({"dependencies": deps})
    except Exception as e:
        return JSONResponse({"error": str(e), "dependencies": {}})


async def api_gate_perf(request):
    """Per-gate performance metrics: pass/block/warn counts, block rate, avg duration."""
    date_str = request.query_params.get("date", "")
    perf = aggregate_gate_perf(date_str or None)
    return JSONResponse({"gates": perf, "date": date_str or "today"})


async def api_audit_query(request):
    """Filtered audit log query with gate, decision, tool, severity, hours params."""
    gate = request.query_params.get("gate", "") or None
    decision = request.query_params.get("decision", "") or None
    tool = request.query_params.get("tool", "") or None
    severity = request.query_params.get("severity", "") or None
    try:
        hours = int(request.query_params.get("hours", "24"))
    except (ValueError, TypeError):
        hours = 24
    hours = max(1, min(hours, 168))  # 1h to 7 days
    entries = load_audit_entries_filtered(
        gate=gate, decision=decision, tool=tool, severity=severity, hours=hours, limit=200,
    )
    return JSONResponse({
        "entries": entries,
        "total": len(entries),
        "filters": {"gate": gate, "decision": decision, "tool": tool, "severity": severity, "hours": hours},
    })


async def api_history_compare(request):
    """Compare two archived handoff files side-by-side."""
    file_a = request.query_params.get("a", "")
    file_b = request.query_params.get("b", "")
    if not file_a or not file_b:
        return JSONResponse({"error": "Both 'a' and 'b' params required"}, status_code=400)
    # Security: prevent path traversal
    for fname in (file_a, file_b):
        if "/" in fname or "\\" in fname or ".." in fname:
            return JSONResponse({"error": "Invalid filename"}, status_code=400)

    def parse_sections(content):
        sections = {}
        current_header = None
        current_lines = []
        for line in content.split("\n"):
            if line.startswith("## "):
                if current_header is not None:
                    sections[current_header] = "\n".join(current_lines).strip()
                current_header = line[3:].strip()
                current_lines = []
            else:
                current_lines.append(line)
        if current_header is not None:
            sections[current_header] = "\n".join(current_lines).strip()
        return sections

    results = {}
    for key, fname in [("a", file_a), ("b", file_b)]:
        path = os.path.join(ARCHIVE_DIR, fname)
        if not os.path.isfile(path):
            return JSONResponse({"error": f"File not found: {fname}"}, status_code=404)
        try:
            with open(path) as f:
                content = f.read()
            results[key] = {"filename": fname, "sections": parse_sections(content)}
        except OSError as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    # Compute diff
    keys_a = set(results["a"]["sections"].keys())
    keys_b = set(results["b"]["sections"].keys())
    added = sorted(keys_b - keys_a)
    removed = sorted(keys_a - keys_b)
    changed = sorted(
        k for k in keys_a & keys_b
        if results["a"]["sections"][k] != results["b"]["sections"][k]
    )

    return JSONResponse({
        "a": results["a"],
        "b": results["b"],
        "diff": {
            "added_sections": added,
            "removed_sections": removed,
            "changed_sections": changed,
        },
    })


async def api_history(request):
    """List archived handoff files."""
    if not os.path.isdir(ARCHIVE_DIR):
        return JSONResponse({"files": []})
    files = []
    for f in sorted(os.listdir(ARCHIVE_DIR), reverse=True):
        if f.startswith("HANDOFF_") and f.endswith(".md"):
            path = os.path.join(ARCHIVE_DIR, f)
            stat = os.stat(path)
            files.append({
                "filename": f,
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
    return JSONResponse({"files": files})


async def api_history_detail(request):
    """Read a single archived handoff file."""
    filename = request.path_params["filename"]
    # Security: prevent path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        return JSONResponse({"error": "Invalid filename"}, status_code=400)
    path = os.path.join(ARCHIVE_DIR, filename)
    if not os.path.isfile(path):
        return JSONResponse({"error": "Not found"}, status_code=404)
    try:
        with open(path) as f:
            content = f.read()
        return JSONResponse({"filename": filename, "content": content})
    except OSError as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def api_stream(request):
    """SSE endpoint: streams new audit events + periodic health pings.

    Also streams:
    - gate_event: real-time gate decisions from audit log
    - memory_event: when new memories are saved (count changes)
    - error_event: when error pressure changes
    """
    if not SSE_AVAILABLE:
        return PlainTextResponse("SSE not available (sse-starlette not installed)", status_code=503)

    async def event_generator():
        # Track file position for new events
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        filepath = os.path.join(AUDIT_DIR, f"{today}.jsonl")
        file_pos = 0
        if os.path.isfile(filepath):
            file_pos = os.path.getsize(filepath)

        # Track memory count for change detection
        last_mem_count = get_memory_count()
        # Track error pressure for change detection
        last_error_pressure = get_error_pressure()
        # Track LIVE_STATE.json mtime for toggle changes
        last_live_state_mtime = 0
        try:
            last_live_state_mtime = os.path.getmtime(LIVE_STATE_FILE)
        except OSError:
            pass

        ping_counter = 0
        while True:
            if await request.is_disconnected():
                break

            # Check for new audit events
            current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if current_date != today:
                # Date rolled over
                today = current_date
                filepath = os.path.join(AUDIT_DIR, f"{today}.jsonl")
                file_pos = 0

            if os.path.isfile(filepath):
                current_size = os.path.getsize(filepath)
                if current_size > file_pos:
                    try:
                        with open(filepath) as f:
                            f.seek(file_pos)
                            new_lines = f.read()
                            file_pos = f.tell()
                        for line in new_lines.strip().split("\n"):
                            if line.strip():
                                parsed = parse_audit_line(line)
                                if parsed:
                                    yield {
                                        "event": "audit",
                                        "data": json.dumps(parsed),
                                    }
                                    # Also emit gate_event for gate decisions
                                    if parsed.get("type") == "gate":
                                        yield {
                                            "event": "gate_event",
                                            "data": json.dumps({
                                                "gate": parsed.get("gate", ""),
                                                "decision": parsed.get("decision", ""),
                                                "tool": parsed.get("tool", ""),
                                                "reason": parsed.get("reason", ""),
                                                "timestamp": parsed.get("timestamp", ""),
                                            }),
                                        }
                    except OSError:
                        pass

            # Check for memory count changes (every loop iteration)
            try:
                current_mem_count = get_memory_count()
                if current_mem_count > last_mem_count:
                    yield {
                        "event": "memory_event",
                        "data": json.dumps({
                            "new_count": current_mem_count,
                            "previous_count": last_mem_count,
                            "delta": current_mem_count - last_mem_count,
                            "ts": time.time(),
                        }),
                    }
                    last_mem_count = current_mem_count
            except Exception:
                pass

            # Check for error pressure changes
            try:
                current_error_pressure = get_error_pressure()
                if current_error_pressure > last_error_pressure:
                    yield {
                        "event": "error_event",
                        "data": json.dumps({
                            "error_pressure": current_error_pressure,
                            "previous": last_error_pressure,
                            "delta": current_error_pressure - last_error_pressure,
                            "ts": time.time(),
                        }),
                    }
                    last_error_pressure = current_error_pressure
            except Exception:
                pass

            # Check for LIVE_STATE.json changes (toggle updates)
            try:
                current_live_state_mtime = os.path.getmtime(LIVE_STATE_FILE)
                if current_live_state_mtime > last_live_state_mtime:
                    last_live_state_mtime = current_live_state_mtime
                    live_data = _read_json(LIVE_STATE_FILE)
                    if live_data:
                        yield {
                            "event": "live_state_event",
                            "data": json.dumps(live_data),
                        }
            except OSError:
                pass

            # Health ping every 10 seconds (5 loops x 2s)
            ping_counter += 1
            if ping_counter >= 5:
                ping_counter = 0
                gate_count = count_gates()
                mem_count = get_memory_count()
                health_pct, _ = calculate_health(gate_count, mem_count)
                yield {
                    "event": "health",
                    "data": json.dumps({
                        "health_pct": health_pct,
                        "color": health_color_name(health_pct),
                        "ts": time.time(),
                    }),
                }

            await asyncio.sleep(2)

    return EventSourceResponse(event_generator())


async def api_gate_state_conflicts(request):
    """Analyze gate dependencies for potential state key conflicts."""
    import sys
    try:
        sys.path.insert(0, HOOKS_DIR)
        from enforcer import get_gate_dependencies
        deps = get_gate_dependencies()
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    # Find state keys written by multiple gates
    write_map = {}
    read_map = {}
    for gate, spec in deps.items():
        for key in spec.get("writes", []):
            write_map.setdefault(key, []).append(gate)
        for key in spec.get("reads", []):
            read_map.setdefault(key, []).append(gate)

    # Keys written by multiple gates = potential conflicts
    write_conflicts = {k: v for k, v in write_map.items() if len(v) > 1}

    # Keys read by many gates = high-impact keys
    hot_keys = {k: {"readers": v, "writers": write_map.get(k, [])}
                for k, v in read_map.items() if len(v) >= 3}

    return JSONResponse({
        "write_conflicts": write_conflicts,
        "hot_keys": hot_keys,
        "total_gates": len(deps),
        "total_state_keys": len(set(list(write_map.keys()) + list(read_map.keys()))),
    })


async def api_activity_trend(request):
    """Gate activity bucketed into 30-minute intervals for the last 24 hours."""
    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")
    yesterday = datetime.fromtimestamp(now.timestamp() - 86400, tz=timezone.utc)
    yesterday_str = yesterday.strftime("%Y-%m-%d")
    cutoff = now.timestamp() - 86400

    # Collect gate entries from today and yesterday
    gate_entries = []
    for date_str in dict.fromkeys([yesterday_str, today_str]):
        filepath = os.path.join(AUDIT_DIR, f"{date_str}.jsonl")
        if not os.path.isfile(filepath):
            continue
        try:
            with open(filepath) as f:
                for line in f:
                    parsed = parse_audit_line(line)
                    if parsed and parsed["type"] == "gate" and parsed.get("ts", 0) >= cutoff:
                        gate_entries.append(parsed)
        except OSError:
            continue

    # Bucket into 30-min intervals
    bucket_size = 1800  # 30 minutes in seconds
    bucket_start = int(cutoff // bucket_size) * bucket_size
    buckets_map = {}
    for ts in range(bucket_start, int(now.timestamp()) + bucket_size, bucket_size):
        buckets_map[ts] = {"pass": 0, "block": 0, "warn": 0, "total": 0}

    for entry in gate_entries:
        ts = entry.get("ts", 0)
        bucket_key = int(ts // bucket_size) * bucket_size
        if bucket_key in buckets_map:
            decision = entry.get("decision", "")
            if decision in ("pass", "block", "warn"):
                buckets_map[bucket_key][decision] += 1
            buckets_map[bucket_key]["total"] += 1

    buckets = []
    for ts in sorted(buckets_map.keys()):
        b = buckets_map[ts]
        b["time"] = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        buckets.append(b)

    return JSONResponse({"buckets": buckets})


async def api_live_metrics(request):
    """Consolidated live metrics endpoint — single state read, single response."""
    # Health data
    gate_count = count_gates()
    mem_count = get_memory_count()
    health_pct, _ = calculate_health(gate_count, mem_count)

    # Session state — single read
    state = _read_latest_state() or {}

    # Tool stats
    tool_stats = state.get("tool_stats", {})
    total_tool_calls = state.get("tool_call_count", 0) or state.get("total_tool_calls", 0)

    # Error data
    error_patterns = state.get("error_pattern_counts", {})
    error_pressure = sum(error_patterns.values()) if error_patterns else 0
    active_bans = state.get("active_bans", [])

    # Verification data
    pending_verification = state.get("pending_verification", [])
    verified_fixes = state.get("verified_fixes", [])
    pending_count = len(pending_verification) if isinstance(pending_verification, list) else 0
    verified_count = len(verified_fixes) if isinstance(verified_fixes, list) else 0
    total_fixes = pending_count + verified_count
    verification_ratio = round(verified_count / total_fixes, 2) if total_fixes > 0 else 0.0

    # Plan mode warnings
    gate12_warn_count = state.get("gate12_warn_count", 0)

    # Session age
    session_start = state.get("session_start", 0)
    session_age_min = 0
    if session_start:
        try:
            session_age_min = int((time.time() - float(session_start)) / 60)
        except (ValueError, TypeError):
            pass

    # Subagent data
    active_subagents = state.get("active_subagents", [])
    subagent_total_tokens = state.get("subagent_total_tokens", 0)

    # Skill usage
    skill_usage = state.get("skill_usage", {})
    recent_skills = state.get("recent_skills", [])

    # Edit streak hotspots
    edit_streak = state.get("edit_streak", {})
    hotspots = {path: count for path, count in edit_streak.items()
                if isinstance(count, int) and count >= 3}

    # Live state
    live = _read_json(LIVE_STATE_FILE) or {}

    return JSONResponse({
        "health": {
            "hp": health_pct,
            "color": health_color_name(health_pct),
            "gates": gate_count,
            "memories": mem_count,
        },
        "session": {
            "project": live.get("project", "unknown"),
            "session_count": live.get("session_count", 0),
            "status": live.get("status", "unknown"),
            "age_min": session_age_min,
        },
        "tools": {
            "total_calls": total_tool_calls,
            "stats": {name: info.get("count", 0) if isinstance(info, dict) else info
                      for name, info in sorted(tool_stats.items(),
                                               key=lambda x: (x[1].get("count", 0) if isinstance(x[1], dict) else x[1]),
                                               reverse=True)},
        },
        "errors": {
            "pressure": error_pressure,
            "patterns": error_patterns,
            "active_bans": active_bans,
        },
        "verification": {
            "pending": pending_count,
            "verified": verified_count,
            "ratio": verification_ratio,
        },
        "plan_mode_warns": gate12_warn_count,
        "subagents": {
            "active": active_subagents if isinstance(active_subagents, list) else [],
            "total_tokens": subagent_total_tokens,
        },
        "skills": {
            "usage": skill_usage,
            "recent": recent_skills[-5:] if isinstance(recent_skills, list) else [],
        },
        "hotspots": {os.path.basename(p): c for p, c in
                     sorted(hotspots.items(), key=lambda x: -x[1])[:10]},
    })


async def api_statusline_snapshot(request):
    """Read the statusline bridge snapshot file, enriched with git branch."""
    data = _read_json(SNAPSHOT_FILE) or {}
    # Add git branch from cache file
    try:
        with open("/tmp/statusline-git-cache") as f:
            data["branch"] = f.read().strip() or None
    except (FileNotFoundError, OSError):
        data["branch"] = None
    return JSONResponse(data)


async def api_toggle_write(request):
    """Write a single toggle value to LIVE_STATE.json (atomic)."""
    key = request.path_params["key"]
    if key not in TOGGLE_KEYS:
        return JSONResponse({"error": f"Unknown toggle key: {key}"}, status_code=400)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    if "value" not in body:
        return JSONResponse({"error": "Missing 'value' field"}, status_code=400)

    value = body["value"]
    expected_type = TOGGLE_TYPES.get(key)
    if expected_type and not isinstance(value, expected_type):
        return JSONResponse(
            {"error": f"Expected {expected_type.__name__} for '{key}', got {type(value).__name__}"},
            status_code=400,
        )
    try:
        with open(LIVE_STATE_FILE) as f:
            data = json.load(f)
        data[key] = value
        tmp = LIVE_STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, LIVE_STATE_FILE)
        return JSONResponse({"ok": True, "key": key, "value": value})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def api_chat_ws(websocket):
    """WebSocket handler for terminal chat using claude -p subprocess."""
    await websocket.accept()
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "text": "Invalid JSON"})
                continue

            chat_id = msg.get("chat_id", "")
            text = msg.get("text", "").strip()
            if not text:
                await websocket.send_json({"type": "error", "text": "Empty message"})
                continue

            # Build claude command
            cmd = ["claude", "-p", text, "--output-format", "stream-json",
                   "--dangerously-skip-permissions"]
            session_id = chat_sessions.get(chat_id)
            if session_id:
                cmd.extend(["--resume", session_id])

            env = os.environ.copy()
            env["CLAUDECODE"] = "0"  # prevent hook interference

            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                )
                buffer = b""
                while True:
                    chunk = await proc.stdout.read(4096)
                    if not chunk:
                        break
                    buffer += chunk
                    # Process complete JSON lines
                    while b"\n" in buffer:
                        line_bytes, buffer = buffer.split(b"\n", 1)
                        line = line_bytes.decode("utf-8", errors="replace").strip()
                        if not line:
                            continue
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        etype = event.get("type", "")
                        if etype == "assistant" and "message" in event:
                            # Extract text content blocks
                            for block in event["message"].get("content", []):
                                if block.get("type") == "text":
                                    await websocket.send_json({
                                        "type": "token",
                                        "text": block["text"],
                                    })
                        elif etype == "content_block_delta":
                            delta = event.get("delta", {})
                            if delta.get("type") == "text_delta":
                                await websocket.send_json({
                                    "type": "token",
                                    "text": delta["text"],
                                })
                        elif etype == "result":
                            # Extract session_id for resume
                            sid = event.get("session_id", "")
                            if sid and chat_id:
                                chat_sessions[chat_id] = sid
                            # Also extract final text if present
                            result_text = event.get("result", "")
                            if result_text:
                                await websocket.send_json({
                                    "type": "token",
                                    "text": result_text,
                                })
                            await websocket.send_json({
                                "type": "done",
                                "session_id": sid,
                            })

                await proc.wait()
                # If no 'done' was sent yet (e.g. process exited early)
                stderr_out = await proc.stderr.read()
                if proc.returncode != 0:
                    err_text = stderr_out.decode("utf-8", errors="replace").strip()
                    await websocket.send_json({
                        "type": "error",
                        "text": err_text or f"claude exited with code {proc.returncode}",
                    })
            except Exception as e:
                await websocket.send_json({
                    "type": "error",
                    "text": str(e),
                })
    except WebSocketDisconnect:
        pass


async def index_redirect(request):
    return RedirectResponse(url="/static/index.html")


# ── App setup ────────────────────────────────────────────────────

routes = [
    Route("/", index_redirect),
    Route("/api/health", api_health),
    Route("/api/health/score", api_health_score),
    Route("/api/live-state", api_live_state),
    Route("/api/session", api_session),
    Route("/api/audit", api_audit),
    Route("/api/audit/dates", api_audit_dates),
    Route("/api/gates", api_gates),
    Route("/api/gate-perf", api_gate_perf),
    Route("/api/gate-timing", api_gate_timing),
    Route("/api/edit-streak", api_edit_streak),
    Route("/api/gate-deps", api_gate_deps),
    Route("/api/gate-state-conflicts", api_gate_state_conflicts),
    Route("/api/activity-trend", api_activity_trend),
    Route("/api/audit/query", api_audit_query),
    Route("/api/history/compare", api_history_compare),
    Route("/api/memory-health", api_memory_health),
    Route("/api/observations/recent", api_observations_recent),
    Route("/api/memories", api_memories_search),
    Route("/api/memories/stats", api_memories_stats),
    Route("/api/memories/tags", api_memories_tags),
    Route("/api/memories/graph", api_memories_graph),
    Route("/api/memories/{id}", api_memory_detail),
    Route("/api/components", api_components),
    Route("/api/skill-usage", api_skill_usage),
    Route("/api/errors", api_errors),
    Route("/api/tool-stats", api_tool_stats),
    Route("/api/tool-usage", get_tool_usage),
    Route("/api/history", api_history),
    Route("/api/history/{filename}", api_history_detail),
    Route("/api/live-metrics", api_live_metrics),
    Route("/api/statusline-snapshot", api_statusline_snapshot),
    Route("/api/toggles/{key}", api_toggle_write, methods=["POST"]),
    Route("/api/stream", api_stream),
    WebSocketRoute("/ws/chat", api_chat_ws),
    Mount("/static", StaticFiles(directory=STATIC_DIR), name="static"),
]

app = Starlette(routes=routes)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Prevent browser from serving stale JS/CSS — force revalidation on every request.
# Static files still benefit from 304 Not Modified via ETag/If-Modified-Since.
# Uses raw ASGI wrapper around the Starlette app since BaseHTTPMiddleware
# doesn't intercept Mount sub-apps (StaticFiles).

class NoCacheStaticWrapper:
    """ASGI wrapper that adds Cache-Control headers to /static/ responses."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path", "").startswith("/static/"):
            async def send_with_cache_header(message):
                if message["type"] == "http.response.start":
                    headers = list(message.get("headers", []))
                    headers.append((b"cache-control", b"no-cache, must-revalidate"))
                    message = {**message, "headers": headers}
                await send(message)
            await self.app(scope, receive, send_with_cache_header)
        else:
            await self.app(scope, receive, send)

wrapped_app = NoCacheStaticWrapper(app)

if __name__ == "__main__":
    import uvicorn
    print("Dashboard starting at http://localhost:7777")
    uvicorn.run(wrapped_app, host="127.0.0.1", port=7777, log_level="info")
