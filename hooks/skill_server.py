#!/usr/bin/env python3
"""Torus Framework — Skill Library MCP Server

On-demand skill loader. Skills live in ~/.claude/skill-library/ and are loaded
only when invoked, costing zero tokens in the system prompt.

Run standalone: python3 skill_server.py
Used via MCP: registered via `claude mcp add`
"""

import functools
import json
import os
import sys
import traceback
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

_SKILL_LIBRARY = os.path.join(os.path.expanduser("~"), ".claude", "skill-library")
_USAGE_LOG = os.path.join(_SKILL_LIBRARY, ".usage_log.jsonl")

mcp = FastMCP("skills")


def crash_proof(fn):
    """Wrap MCP tool handler so exceptions return error dicts instead of crashing."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            tb = traceback.format_exc()
            print(f"[Skill MCP] {fn.__name__} error: {e}\n{tb}", file=sys.stderr)
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


def _log_usage(skill_name: str):
    """Append invocation to usage log."""
    entry = {
        "skill": skill_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": os.environ.get("SESSION_ID", "unknown"),
    }
    try:
        with open(_USAGE_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


@mcp.tool()
@crash_proof
def list_skills() -> dict:
    """List all skills in the skill library with one-line descriptions.

    Returns skill names, descriptions, and estimated token counts.
    Use this to discover available skills before invoking one.
    """
    skills = []
    if not os.path.isdir(_SKILL_LIBRARY):
        return {"skills": [], "count": 0}

    for name in sorted(os.listdir(_SKILL_LIBRARY)):
        skill_dir = os.path.join(_SKILL_LIBRARY, name)
        if not os.path.isdir(skill_dir) or name.startswith("."):
            continue
        md_path = os.path.join(skill_dir, "SKILL.md")
        tokens_est = 0
        if os.path.exists(md_path):
            chars = os.path.getsize(md_path)
            tokens_est = int(chars / 3.8)
        skills.append({
            "name": name,
            "description": _get_description(skill_dir),
            "tokens_est": tokens_est,
        })

    return {"skills": skills, "count": len(skills)}


@mcp.tool()
@crash_proof
def invoke_skill(name: str) -> dict:
    """Load a skill's full instructions for execution.

    Args:
        name: Skill name (directory name in skill-library).

    Returns the complete SKILL.md content. Follow the instructions returned.
    """
    skill_dir = os.path.join(_SKILL_LIBRARY, name)
    md_path = os.path.join(skill_dir, "SKILL.md")

    if not os.path.exists(md_path):
        available = [d for d in os.listdir(_SKILL_LIBRARY)
                     if os.path.isdir(os.path.join(_SKILL_LIBRARY, d))
                     and not d.startswith(".")]
        return {
            "error": f"Skill '{name}' not found",
            "available": sorted(available),
        }

    with open(md_path, "r") as f:
        content = f.read()

    _log_usage(name)

    return {
        "name": name,
        "content": content,
        "tokens_est": int(len(content) / 3.8),
    }


_SELF_IMPROVE_SKILLS = {
    "sprint": "Multi-agent self-improvement sprint — find and fix framework weaknesses",
    "audit": "Full project audit — verify all gates, tests, shared modules",
    "diagnose": "Gate effectiveness analysis — which gates block too much or too little",
    "analyze-errors": "Recurring error deep analysis — find patterns in repeated failures",
    "benchmark": "Performance baseline — measure gate latency, memory search speed",
    "introspect": "Deep self-analysis — examine reasoning patterns and blind spots",
    "super-evolve": "Evolution cycle — identify and implement framework improvements",
    "super-health": "Comprehensive health diagnostic — full system check",
    "super-prof-optimize": "Performance profiling and optimization — find and fix bottlenecks",
    "code-hotspots": "Identify high-risk files from gate block patterns in audit logs",
    "generate-test-stubs": "Auto-generate test stubs for a Python module using AST analysis",
    "replay-events": "Replay historical tool events through gate pipeline for regression testing",
    "tool-recommendations": "Suggest alternative tools for frequently blocked tools",
    "gate-health-correlation": "Detect gate redundancy and synergy from fire patterns",
    "causal-chain-analysis": "Analyze fix outcomes to detect patterns and suggest improvements",
}


@mcp.tool()
@crash_proof
def self_improve(action: str) -> dict:
    """Run a self-improvement skill. Actions: sprint (multi-agent improvement), audit (full project audit), diagnose (gate effectiveness), analyze-errors (recurring errors), benchmark (performance baseline), introspect (deep self-analysis), super-evolve (evolution cycle), super-health (health diagnostic), super-prof-optimize (profiling & optimization), code-hotspots (high-risk files), generate-test-stubs (auto-generate tests), replay-events (gate regression testing), tool-recommendations (blocked tool alternatives), gate-health-correlation (gate redundancy analysis), causal-chain-analysis (fix outcome patterns)

    Args:
        action: One of: sprint, audit, diagnose, analyze-errors, benchmark, introspect, super-evolve, super-health, super-prof-optimize, code-hotspots, generate-test-stubs, replay-events, tool-recommendations, gate-health-correlation, causal-chain-analysis
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
    """Show skill invocation history from the usage log.

    Returns counts per skill and recent invocations.
    """
    if not os.path.exists(_USAGE_LOG):
        return {"total": 0, "counts": {}, "recent": []}

    counts = {}
    recent = []
    with open(_USAGE_LOG, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                skill = entry.get("skill", "unknown")
                counts[skill] = counts.get(skill, 0) + 1
                recent.append(entry)
            except json.JSONDecodeError:
                continue

    return {
        "total": sum(counts.values()),
        "counts": dict(sorted(counts.items(), key=lambda x: -x[1])),
        "recent": recent[-10:],
    }


if __name__ == "__main__":
    mcp.run()
