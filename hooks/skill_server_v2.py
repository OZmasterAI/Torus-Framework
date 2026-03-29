#!/usr/bin/env python3
"""Torus Framework — Skill Library MCP Server v2

Upgrade of skill_server.py with SQLite-backed quality tracking,
BM25 + nomic embedding hybrid search, lineage, and health reporting.

SKILL.md files remain the source of truth for content.
SQLite (skills.db) tracks quality counters, lineage, and evolution history.

Reuses v1's proven filesystem utilities. v1 stays untouched as fallback.

Run standalone: python3 skill_server_v2.py
Used via MCP: registered via `claude mcp add`
"""

import argparse
import functools
import os
import sys
import traceback

from mcp.server.fastmcp import FastMCP

# ── Filesystem constants and utilities (same as v1) ──

_CLAUDE_DIR = os.path.join(os.path.expanduser("~"), ".claude")
_SKILL_LIBRARY = os.path.join(_CLAUDE_DIR, "skill-library")
_SKILLS_DIR = os.path.join(_CLAUDE_DIR, "skills")
_SKILL_DIRS = [_SKILL_LIBRARY, _SKILLS_DIR]
_STATE_DIR = os.path.join(_CLAUDE_DIR, "hooks", ".state")
_DB_PATH = os.path.join(_STATE_DIR, "skills.db")

# ── Transport config — streamable-http default, --stdio for pipe mode ──
_NET_HOST = os.environ.get("SKILLS_HOST", "127.0.0.1")
_NET_PORT = int(os.environ.get("SKILLS_PORT", "8743"))

_parser = argparse.ArgumentParser(add_help=False)
_parser.add_argument(
    "--http",
    action="store_true",
    default=True,
    help="Use streamable-http transport (default)",
)
_parser.add_argument(
    "--stdio",
    action="store_true",
    default=False,
    help="Use stdio transport (for subprocess/pipe mode)",
)
_parser.add_argument("--port", type=int, default=_NET_PORT)
_args, _ = _parser.parse_known_args()

if _args.stdio:
    _args.http = False

if _args.http:
    mcp = FastMCP("skills", host=_NET_HOST, port=_args.port)
else:
    mcp = FastMCP("skills")

# ── OAuth discovery stubs (Claude Code does RFC 9728/8414 probing) ──
if _args.http:
    from starlette.requests import Request
    from starlette.responses import Response

    @mcp.custom_route("/.well-known/oauth-authorization-server", methods=["GET"])
    async def _oauth_as_metadata(request: Request) -> Response:
        return Response(status_code=404)

    @mcp.custom_route("/.well-known/oauth-protected-resource", methods=["GET"])
    async def _oauth_protected_resource(request: Request) -> Response:
        return Response(status_code=404)

    @mcp.custom_route("/.well-known/openid-configuration", methods=["GET"])
    async def _openid_config(request: Request) -> Response:
        return Response(status_code=404)

    @mcp.custom_route("/register", methods=["POST"])
    async def _oauth_register(request: Request) -> Response:
        return Response(status_code=404)

    @mcp.custom_route("/authorize", methods=["GET"])
    async def _oauth_authorize(request: Request) -> Response:
        return Response(status_code=404)


# ── Lazy-loaded singletons ──
_db_conn = None
_search_engine = None


def _get_db():
    """Get or create the SQLite connection (lazy, singleton)."""
    global _db_conn
    if _db_conn is None:
        os.makedirs(_STATE_DIR, exist_ok=True)
        from shared.skill_db import init_db

        _db_conn = init_db(_DB_PATH)
    return _db_conn


def _get_search():
    """Get or create the hybrid search engine (lazy, singleton)."""
    global _search_engine
    if _search_engine is None:
        from shared.skill_search import HybridSearch

        _search_engine = HybridSearch()
        _index_all_skills()
    return _search_engine


def _index_all_skills():
    """Index all SKILL.md files into the search engine."""
    engine = _search_engine
    if engine is None:
        return
    for name in _all_available_skills():
        skill_dir, md_path = _find_skill(name)
        if md_path is None:
            continue
        try:
            with open(md_path, "r") as f:
                content = f.read()
            text = f"{name} {content[:300]}"
            engine.add(name, text)
        except Exception:
            pass


def crash_proof(fn):
    """Wrap MCP tool handler so exceptions return error dicts instead of crashing."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            tb = traceback.format_exc()
            print(f"[Skill MCP v2] {fn.__name__} error: {e}\n{tb}", file=sys.stderr)
            return {"error": f"{fn.__name__} failed: {type(e).__name__}: {e}"}

    return wrapper


def _get_description(skill_path: str) -> str:
    """Extract first non-heading, non-empty line from SKILL.md as description."""
    md_path = os.path.join(skill_path, "SKILL.md")
    if not os.path.exists(md_path):
        return "(no SKILL.md)"
    with open(md_path, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                return line[:120]
    return "(no description)"


def _find_skill(name: str):
    """Return (skill_dir, md_path) for the named skill, searching both directories."""
    for base in _SKILL_DIRS:
        skill_dir = os.path.join(base, name)
        md_path = os.path.join(skill_dir, "SKILL.md")
        if os.path.exists(md_path):
            return skill_dir, md_path
    return None, None


def _all_available_skills():
    """Return sorted list of all skill names across both directories (deduplicated)."""
    seen = set()
    names = []
    for base in _SKILL_DIRS:
        if not os.path.isdir(base):
            continue
        for d in sorted(os.listdir(base)):
            if d.startswith("."):
                continue
            if os.path.isdir(os.path.join(base, d)) and d not in seen:
                seen.add(d)
                names.append(d)
    return sorted(names)


def _ensure_skill_in_db(name: str) -> str:
    """Ensure skill exists in SQLite, return skill_id."""
    from shared.skill_db import get_or_create_skill

    conn = _get_db()
    skill_dir, _ = _find_skill(name)
    desc = _get_description(skill_dir) if skill_dir else ""
    path = skill_dir or ""
    return get_or_create_skill(conn, name, desc, path)


# ── MCP Tools: Reimplemented (same names as v1, SQLite backing) ──


@mcp.tool()
@crash_proof
def list_skills() -> dict:
    """List all skills in the skill library with one-line descriptions and quality stats.

    Returns skill names, descriptions, token estimates, and quality metrics from SQLite.
    Searches both skill-library/ and skills/ directories.
    Use this to discover available skills before invoking one.
    """
    from shared.skill_db import get_skill_by_name, computed_rates

    conn = _get_db()
    skills = []
    seen = set()

    for base in _SKILL_DIRS:
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            if name.startswith(".") or name in seen:
                continue
            skill_dir = os.path.join(base, name)
            if not os.path.isdir(skill_dir):
                continue
            seen.add(name)
            md_path = os.path.join(skill_dir, "SKILL.md")
            tokens_est = 0
            if os.path.exists(md_path):
                chars = os.path.getsize(md_path)
                tokens_est = int(chars / 3.8)

            # Pull quality stats from SQLite if available
            rec = get_skill_by_name(conn, name)
            quality = {}
            if rec and rec["total_selections"] > 0:
                rates = computed_rates(rec)
                quality = {
                    "selections": rec["total_selections"],
                    "effective_rate": round(rates["effective_rate"], 2),
                    "completion_rate": round(rates["completion_rate"], 2),
                    "applied_rate": round(rates["applied_rate"], 2),
                    "generation": rec["lineage_generation"],
                }

            entry = {
                "name": name,
                "description": _get_description(skill_dir),
                "tokens_est": tokens_est,
            }
            if quality:
                entry["quality"] = quality
            skills.append(entry)

    skills.sort(key=lambda s: s["name"])
    return {"skills": skills, "count": len(skills)}


@mcp.tool()
@crash_proof
def invoke_skill(name: str) -> dict:
    """Load a skill's full instructions for execution.

    Args:
        name: Skill name (directory name in skill-library or skills).

    Searches both skill-library/ and skills/ directories.
    Returns the complete SKILL.md content. Follow the instructions returned.
    Records the selection in SQLite for quality tracking.
    """
    from shared.skill_db import record_selection

    skill_dir, md_path = _find_skill(name)

    if md_path is None:
        return {
            "error": f"Skill '{name}' not found",
            "available": _all_available_skills(),
        }

    with open(md_path, "r") as f:
        content = f.read()

    # Record selection in SQLite
    skill_id = _ensure_skill_in_db(name)
    record_selection(_get_db(), skill_id)

    return {
        "name": name,
        "content": content,
        "tokens_est": int(len(content) / 3.8),
    }


_SELF_IMPROVE_SKILLS = {
    "sprint": "Multi-agent self-improvement sprint -- find and fix framework weaknesses",
    "audit": "Full project audit -- verify all gates, tests, shared modules",
    "diagnose": "Gate effectiveness analysis -- which gates block too much or too little",
    "analyze-errors": "Recurring error deep analysis -- find patterns in repeated failures",
    "benchmark": "Performance baseline -- measure gate latency, memory search speed",
    "introspect": "Deep self-analysis -- examine reasoning patterns and blind spots",
    "super-evolve": "Evolution cycle -- identify and implement framework improvements",
    "super-health": "Comprehensive health diagnostic -- full system check",
    "super-prof-optimize": "Performance profiling and optimization -- find and fix bottlenecks",
    "code-hotspots": "Identify high-risk files from gate block patterns in audit logs",
    "generate-test-stubs": "Auto-generate test stubs for a Python module using AST analysis",
    "replay-events": "Replay historical tool events through gate pipeline for regression testing",
    "tool-recommendations": "Suggest alternative tools for frequently blocked tools",
    "gate-health-correlation": "Detect gate redundancy and synergy from fire patterns",
    "causal-chain-analysis": "Analyze fix outcomes to detect patterns and suggest improvements",
    "gate-timing": "Gate execution latency analysis -- per-gate timing stats and slow gate detection",
    "session-metrics": "Current session operational metrics -- tool calls, block rate, error rate",
    "experiment": "Autoresearch-style experiment loop -- metric-driven optimization with worktrees",
}


@mcp.tool()
@crash_proof
def self_improve(action: str) -> dict:
    """Run a self-improvement skill. Actions: sprint, audit, diagnose, analyze-errors, benchmark, introspect, super-evolve, super-health, super-prof-optimize, code-hotspots, generate-test-stubs, replay-events, tool-recommendations, gate-health-correlation, causal-chain-analysis, gate-timing, session-metrics, experiment

    Args:
        action: One of the self-improvement action names listed above.
    """
    if action not in _SELF_IMPROVE_SKILLS:
        return {
            "error": f"Unknown action '{action}'",
            "available": {k: v for k, v in _SELF_IMPROVE_SKILLS.items()},
        }
    return invoke_skill(action)


@mcp.tool()
@crash_proof
def skill_usage() -> dict:
    """Show skill usage statistics from SQLite quality counters.

    Returns selection counts, quality rates, and recent activity per skill.
    """
    from shared.skill_db import get_all_skill_records, computed_rates

    conn = _get_db()
    records = get_all_skill_records(conn)

    counts = {}
    details = []
    for rec in records:
        if rec["total_selections"] > 0:
            rates = computed_rates(rec)
            counts[rec["name"]] = rec["total_selections"]
            details.append(
                {
                    "name": rec["name"],
                    "selections": rec["total_selections"],
                    "applied_rate": round(rates["applied_rate"], 2),
                    "completion_rate": round(rates["completion_rate"], 2),
                    "effective_rate": round(rates["effective_rate"], 2),
                    "last_updated": rec["last_updated"],
                }
            )

    details.sort(key=lambda d: -d["selections"])
    return {
        "total": sum(counts.values()),
        "counts": dict(sorted(counts.items(), key=lambda x: -x[1])),
        "details": details[:20],
    }


# ── MCP Tools: New in v2 ──


@mcp.tool()
@crash_proof
def search_skills(query: str, top_k: int = 5) -> dict:
    """Search skills by semantic meaning and keywords.

    Uses BM25 keyword matching + nomic embedding semantic search.
    Returns ranked results with relevance scores.

    Args:
        query: What you're looking for (natural language).
        top_k: Number of results to return (default 5).
    """
    engine = _get_search()
    results = engine.search(query, top_k=top_k)

    skills = []
    for name, score in results:
        skill_dir, _ = _find_skill(name)
        desc = _get_description(skill_dir) if skill_dir else "(not found)"
        skills.append(
            {
                "name": name,
                "description": desc,
                "relevance": round(score, 3),
            }
        )

    return {"query": query, "results": skills, "count": len(skills)}


@mcp.tool()
@crash_proof
def record_outcome(
    skill: str, success: bool, context: str = "", analyze: bool = False
) -> dict:
    """Record the outcome of a skill execution for quality tracking.

    Call this after a skill has been used to track whether it worked.
    Updates SQLite counters used for health monitoring and evolution triggers.

    Args:
        skill: Skill name that was used.
        success: Whether the skill achieved its goal.
        context: Brief description of what happened (optional).
        analyze: If True, run LLM post-task analysis (stores judgments, updates counters).
    """
    from shared.skill_db import record_outcome as db_record_outcome

    skill_id = _ensure_skill_in_db(skill)
    conn = _get_db()
    db_record_outcome(conn, skill_id, applied=True, completed=success)

    result = {
        "skill": skill,
        "success": success,
        "context": context,
        "recorded": True,
    }

    if analyze:
        analysis = _run_analysis(skill, success, context)
        if analysis:
            result["analysis"] = {
                "task_completed": analysis.get("task_completed"),
                "execution_note": analysis.get("execution_note", ""),
                "evolution_suggestions": analysis.get("evolution_suggestions", []),
            }
        else:
            result["analysis"] = {"error": "Analysis failed or unavailable"}

    # Check triggers after recording outcome
    triggered = _check_and_report_triggers(skill_id)
    if triggered:
        result["trigger"] = triggered

    return result


def _run_analysis(skill_name: str, success: bool, context: str) -> dict | None:
    """Run post-task analysis via LLM. Returns parsed analysis or None."""
    try:
        from shared.skill_analyzer import analyze_task
        from shared.skill_llm_backend import ClaudePClient

        _, md_path = _find_skill(skill_name)
        if md_path is None:
            return None

        with open(md_path, "r") as f:
            skill_content = f.read()

        conn = _get_db()
        client = ClaudePClient()
        return analyze_task(
            conn=conn,
            llm_client=client,
            skill_name=skill_name,
            skill_content=skill_content,
            success=success,
            context=context,
        )
    except Exception as e:
        print(f"[Skill MCP v2] analysis failed: {e}", file=sys.stderr)
        return None


def _check_and_report_triggers(skill_id: str) -> dict | None:
    """Check if a skill is eligible for evolution. Returns info dict or None."""
    try:
        from shared.skill_triggers import is_evolution_eligible
        from shared.skill_db import get_skill_record, computed_rates

        conn = _get_db()
        if not is_evolution_eligible(conn, skill_id):
            return None

        rec = get_skill_record(conn, skill_id)
        rates = computed_rates(rec)
        return {
            "skill_id": skill_id,
            "name": rec["name"],
            "evolution_type": "FIX",
            "completion_rate": round(rates["completion_rate"], 3),
            "fallback_rate": round(rates["fallback_rate"], 3),
            "message": f"Skill '{rec['name']}' is degraded and eligible for FIX evolution. "
            f"Use trigger_evolution(skill='{rec['name']}') to run it.",
        }
    except Exception as e:
        print(f"[Skill MCP v2] trigger check failed: {e}", file=sys.stderr)
        return None


def _run_evolution(skill_name: str, direction: str = "") -> dict:
    """Execute FIX evolution on a skill. Returns result dict."""
    try:
        from shared.skill_evolver import evolve_skill
        from shared.skill_triggers import is_evolution_eligible
        from shared.skill_db import get_skill_by_name, computed_rates
        from shared.skill_llm_backend import ClaudePClient

        conn = _get_db()
        rec = get_skill_by_name(conn, skill_name)
        if rec is None:
            return {"success": False, "error": f"Skill '{skill_name}' not in SQLite"}

        skill_id = rec["skill_id"]
        if not is_evolution_eligible(conn, skill_id):
            return {
                "success": False,
                "error": f"Skill '{skill_name}' not eligible for evolution",
            }

        skill_dir, md_path = _find_skill(skill_name)
        if md_path is None:
            return {
                "success": False,
                "error": f"Skill '{skill_name}' SKILL.md not found",
            }

        rates = computed_rates(rec)
        metric_summary = (
            f"completion_rate={rates['completion_rate']:.2f}, "
            f"fallback_rate={rates['fallback_rate']:.2f}, "
            f"effective_rate={rates['effective_rate']:.2f}, "
            f"selections={rec['total_selections']}"
        )

        # Gather failure context from recent analyses
        failure_rows = conn.execute(
            """SELECT execution_note, tool_issues FROM execution_analyses
               WHERE task_id IN (
                   SELECT DISTINCT ea.task_id FROM execution_analyses ea
                   JOIN skill_judgments sj ON sj.analysis_id = ea.id
                   WHERE sj.skill_id = ? AND ea.task_completed = 0
               )
               ORDER BY timestamp DESC LIMIT 5""",
            (skill_id,),
        ).fetchall()
        failure_context = (
            "\n".join(f"- {r['execution_note']}" for r in failure_rows)
            if failure_rows
            else ""
        )

        tool_issues = ""
        if failure_rows:
            import json

            all_issues = []
            for r in failure_rows:
                try:
                    issues = json.loads(r["tool_issues"])
                    all_issues.extend(issues)
                except (json.JSONDecodeError, TypeError):
                    pass
            tool_issues = "\n".join(f"- {i}" for i in all_issues[:10])

        client = ClaudePClient()
        return evolve_skill(
            conn=conn,
            llm_client=client,
            skill_id=skill_id,
            skill_name=skill_name,
            skill_dir=skill_dir,
            direction=direction or f"Fix degraded skill (metrics: {metric_summary})",
            failure_context=failure_context,
            tool_issues=tool_issues,
            metric_summary=metric_summary,
        )
    except Exception as e:
        print(f"[Skill MCP v2] evolution failed: {e}", file=sys.stderr)
        return {"success": False, "error": str(e)}


@mcp.tool()
@crash_proof
def trigger_evolution(
    skill: str, direction: str = "", evolution_type: str = "FIX"
) -> dict:
    """Trigger evolution on a degraded skill.

    Checks if the skill meets evolution thresholds, then runs the appropriate
    evolver (claude -p, up to 5 iterations).

    FIX: Repair in-place. DERIVED: Create specialized variant (parent stays).

    Args:
        skill: Skill name to evolve.
        direction: Optional specific direction (auto-detected if empty).
        evolution_type: "FIX" (default) or "DERIVED".
    """
    if evolution_type == "DERIVED":
        return _run_derived_evolution(skill, direction)
    return _run_evolution(skill, direction)


def _run_derived_evolution(skill_name: str, direction: str = "") -> dict:
    """Execute DERIVED evolution on a skill. Returns result dict."""
    try:
        from shared.skill_evolver import evolve_derived
        from shared.skill_triggers import is_evolution_eligible
        from shared.skill_db import get_skill_by_name, computed_rates
        from shared.skill_llm_backend import ClaudePClient

        conn = _get_db()
        rec = get_skill_by_name(conn, skill_name)
        if rec is None:
            return {"success": False, "error": f"Skill '{skill_name}' not in SQLite"}

        skill_id = rec["skill_id"]
        if not is_evolution_eligible(conn, skill_id):
            return {"success": False, "error": f"Skill '{skill_name}' not eligible"}

        skill_dir, md_path = _find_skill(skill_name)
        if md_path is None:
            return {"success": False, "error": f"Skill '{skill_name}' not found"}

        rates = computed_rates(rec)
        metric_summary = (
            f"applied_rate={rates['applied_rate']:.2f}, "
            f"completion_rate={rates['completion_rate']:.2f}, "
            f"selections={rec['total_selections']}"
        )

        client = ClaudePClient()
        return evolve_derived(
            conn=conn,
            llm_client=client,
            parent_skill_id=skill_id,
            parent_skill_name=skill_name,
            parent_skill_dir=skill_dir,
            direction=direction
            or f"Specialize degraded skill (metrics: {metric_summary})",
            execution_insights="",
            metric_summary=metric_summary,
            skill_library_dir=_SKILL_LIBRARY,
        )
    except Exception as e:
        print(f"[Skill MCP v2] derived evolution failed: {e}", file=sys.stderr)
        return {"success": False, "error": str(e)}


@mcp.tool()
@crash_proof
def capture_skill(
    direction: str, category: str = "workflow", context: str = ""
) -> dict:
    """Capture a novel pattern into a brand-new skill.

    Creates a new SKILL.md in skill-library/ from observed patterns.
    Uses claude -p to generate the skill content.

    Args:
        direction: Description of the pattern to capture.
        category: One of "workflow", "tool_guide", "reference".
        context: Execution context where the pattern was observed.
    """
    try:
        from shared.skill_evolver import evolve_captured
        from shared.skill_llm_backend import ClaudePClient

        conn = _get_db()
        client = ClaudePClient()
        return evolve_captured(
            conn=conn,
            llm_client=client,
            direction=direction,
            category=category,
            execution_highlights=context,
            skill_library_dir=_SKILL_LIBRARY,
        )
    except Exception as e:
        print(f"[Skill MCP v2] capture failed: {e}", file=sys.stderr)
        return {"success": False, "error": str(e)}


@mcp.tool()
@crash_proof
def skill_lineage(skill: str) -> dict:
    """Show evolution history for a skill: parents, children, generation.

    Args:
        skill: Skill name to trace lineage for.
    """
    from shared.skill_db import get_skill_by_name, get_skill_lineage

    conn = _get_db()
    rec = get_skill_by_name(conn, skill)
    if not rec:
        return {"error": f"Skill '{skill}' not found in SQLite (invoke it first)"}

    lineage = get_skill_lineage(conn, rec["skill_id"])
    return {
        "skill": skill,
        "skill_id": rec["skill_id"],
        "generation": rec["lineage_generation"],
        "origin": rec["lineage_origin"],
        "parents": [
            {"name": p["name"], "generation": p["lineage_generation"]}
            for p in lineage["parents"]
        ],
        "children": [
            {"name": c["name"], "generation": c["lineage_generation"]}
            for c in lineage["children"]
        ],
    }


@mcp.tool()
@crash_proof
def skill_health() -> dict:
    """Show health status of all tracked skills.

    Returns computed quality rates and flags degraded skills
    (completion_rate < 35% or fallback_rate > 40%).
    Skills with < 5 selections show as 'insufficient_data'.
    """
    from shared.skill_db import get_skill_health

    conn = _get_db()
    health = get_skill_health(conn)

    degraded = [h for h in health if h["status"] == "degraded"]
    ok = [h for h in health if h["status"] == "ok"]
    insufficient = [h for h in health if h["status"] == "insufficient_data"]

    return {
        "total_tracked": len(health),
        "ok": len(ok),
        "degraded": len(degraded),
        "insufficient_data": len(insufficient),
        "degraded_skills": [
            {
                "name": h["name"],
                "effective_rate": round(h["effective_rate"], 2),
                "fallback_rate": round(h["fallback_rate"], 2),
            }
            for h in degraded
        ],
        "all": [
            {
                "name": h["name"],
                "status": h["status"],
                "selections": h["total_selections"],
                "effective_rate": round(h["effective_rate"], 2),
            }
            for h in health
        ],
    }


if __name__ == "__main__":
    import threading

    # Phase 1 (main thread): index all skills into BM25 immediately.
    # add() no longer blocks on embedding model, so this is fast.
    _get_search()

    # Phase 2 (background): load embedding model for semantic search.
    # BM25 search works immediately; hybrid activates when model is ready.
    def _warmup_embeddings():
        try:
            from shared.skill_search import _get_embedding_model

            _get_embedding_model()
        except Exception:
            pass

    threading.Thread(target=_warmup_embeddings, daemon=True).start()

    _mode = "stdio" if _args.stdio else "streamable-http"
    if _args.http:
        print(
            f"[Skill MCP v2] Starting {_mode} on {_NET_HOST}:{_args.port}",
            file=sys.stderr,
        )
    mcp.run(transport=_mode)
