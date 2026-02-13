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
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles

try:
    from sse_starlette.sse import EventSourceResponse
    SSE_AVAILABLE = True
except ImportError:
    SSE_AVAILABLE = False

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

# ── Constants (mirrored from statusline.py) ──────────────────────
EXPECTED_GATES = 12
EXPECTED_SKILLS = 9
EXPECTED_HOOK_EVENTS = 13

# ── Lazy ChromaDB client ─────────────────────────────────────────
_chroma_client = None
_chroma_collections = {}


def _get_chroma():
    """Lazily initialize a read-only ChromaDB client."""
    global _chroma_client, _chroma_collections
    if _chroma_client is not None:
        return _chroma_client, _chroma_collections
    try:
        import chromadb
        _chroma_client = chromadb.PersistentClient(path=MEMORY_DIR)
        for name in ("knowledge", "observations", "fix_outcomes"):
            try:
                _chroma_collections[name] = _chroma_client.get_or_create_collection(
                    name=name, metadata={"hnsw:space": "cosine"}
                )
            except Exception:
                pass
        return _chroma_client, _chroma_collections
    except Exception:
        return None, {}


# ── Helper functions (reimplemented from statusline.py) ──────────

def _read_json(path):
    """Safely read and parse a JSON file."""
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def count_gates():
    if not os.path.isdir(GATES_DIR):
        return 0
    return len([f for f in os.listdir(GATES_DIR)
                if f.startswith("gate_") and f.endswith(".py")])


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
    """Get curated memory count via ChromaDB (cached)."""
    try:
        if os.path.exists(STATS_CACHE):
            cache = _read_json(STATS_CACHE)
            if cache and time.time() - cache.get("ts", 0) < 60:
                return cache.get("mem_count", 0)
    except Exception:
        pass
    _, cols = _get_chroma()
    if "knowledge" in cols:
        try:
            return cols["knowledge"].count()
        except Exception:
            pass
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
            "gate": entry.get("gate", ""),
            "tool": entry.get("tool", ""),
            "decision": entry.get("decision", ""),
            "reason": entry.get("reason", ""),
            "session_id": entry.get("session_id", ""),
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

    _, cols = _get_chroma()
    if "knowledge" not in cols:
        return JSONResponse({"error": "ChromaDB not available", "results": []})

    col = cols["knowledge"]
    try:
        count = col.count()
        if not query:
            # Return recent entries
            results = col.get(limit=min(limit, count), include=["metadatas"])
            entries = []
            ids = results.get("ids", [])
            metas = results.get("metadatas", [])
            for i, mid in enumerate(ids):
                meta = metas[i] if i < len(metas) else {}
                entries.append({
                    "id": mid,
                    "preview": meta.get("preview", ""),
                    "tags": meta.get("tags", ""),
                    "timestamp": meta.get("timestamp", ""),
                })
            return JSONResponse({"results": entries, "total": count, "query": ""})

        actual_k = min(limit + offset, count)
        if actual_k == 0:
            return JSONResponse({"results": [], "total": 0, "query": query})

        results = col.query(
            query_texts=[query], n_results=actual_k,
            include=["metadatas", "distances"],
        )
        entries = []
        ids = results.get("ids", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        for i, mid in enumerate(ids):
            meta = metas[i] if i < len(metas) else {}
            dist = distances[i] if i < len(distances) else 1.0
            entries.append({
                "id": mid,
                "preview": meta.get("preview", ""),
                "tags": meta.get("tags", ""),
                "timestamp": meta.get("timestamp", ""),
                "relevance": round(1 - dist, 3),
            })
        sliced = entries[offset:offset + limit]
        return JSONResponse({"results": sliced, "total": count, "query": query})
    except Exception as e:
        return JSONResponse({"error": str(e), "results": []})


async def api_memory_detail(request):
    mem_id = request.path_params["id"]
    _, cols = _get_chroma()
    if "knowledge" not in cols:
        return JSONResponse({"error": "ChromaDB not available"}, status_code=503)
    try:
        result = cols["knowledge"].get(ids=[mem_id], include=["documents", "metadatas"])
        if not result or not result.get("documents") or not result["documents"]:
            return JSONResponse({"error": "Not found"}, status_code=404)
        meta = result["metadatas"][0] if result.get("metadatas") else {}
        return JSONResponse({
            "id": mem_id,
            "content": result["documents"][0],
            "context": meta.get("context", ""),
            "tags": meta.get("tags", ""),
            "timestamp": meta.get("timestamp", ""),
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def api_memories_stats(request):
    _, cols = _get_chroma()
    stats = {}
    for name in ("knowledge", "observations", "fix_outcomes"):
        if name in cols:
            try:
                stats[name] = cols[name].count()
            except Exception:
                stats[name] = -1
        else:
            stats[name] = -1
    return JSONResponse(stats)


async def api_memories_tags(request):
    """Get tag frequency distribution from ChromaDB knowledge collection."""
    _, cols = _get_chroma()
    if "knowledge" not in cols:
        return JSONResponse({"tags": {}})
    try:
        col = cols["knowledge"]
        count = col.count()
        if count == 0:
            return JSONResponse({"tags": {}})
        results = col.get(limit=min(count, 500), include=["metadatas"])
        tag_freq = {}
        metas = results.get("metadatas", [])
        for meta in metas:
            if meta and meta.get("tags"):
                for tag in meta["tags"].split(","):
                    tag = tag.strip()
                    if tag:
                        tag_freq[tag] = tag_freq.get(tag, 0) + 1
        sorted_tags = dict(sorted(tag_freq.items(), key=lambda x: -x[1]))
        return JSONResponse({"tags": sorted_tags, "total_memories": count})
    except Exception as e:
        return JSONResponse({"tags": {}, "error": str(e)})


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

    # Plugins
    plugins = list(settings.get("enabledPlugins", {}).keys())

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
    """SSE endpoint: streams new audit events + periodic health pings."""
    if not SSE_AVAILABLE:
        return PlainTextResponse("SSE not available (sse-starlette not installed)", status_code=503)

    async def event_generator():
        # Track file position for new events
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        filepath = os.path.join(AUDIT_DIR, f"{today}.jsonl")
        file_pos = 0
        if os.path.isfile(filepath):
            file_pos = os.path.getsize(filepath)

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


async def index_redirect(request):
    return RedirectResponse(url="/static/index.html")


# ── App setup ────────────────────────────────────────────────────

routes = [
    Route("/", index_redirect),
    Route("/api/health", api_health),
    Route("/api/live-state", api_live_state),
    Route("/api/session", api_session),
    Route("/api/audit", api_audit),
    Route("/api/audit/dates", api_audit_dates),
    Route("/api/gates", api_gates),
    Route("/api/memories", api_memories_search),
    Route("/api/memories/stats", api_memories_stats),
    Route("/api/memories/tags", api_memories_tags),
    Route("/api/memories/{id}", api_memory_detail),
    Route("/api/components", api_components),
    Route("/api/errors", api_errors),
    Route("/api/history", api_history),
    Route("/api/history/{filename}", api_history_detail),
    Route("/api/stream", api_stream),
    Mount("/static", StaticFiles(directory=STATIC_DIR), name="static"),
]

app = Starlette(routes=routes)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

if __name__ == "__main__":
    import uvicorn
    print("Dashboard starting at http://localhost:7777")
    uvicorn.run(app, host="127.0.0.1", port=7777, log_level="info")
