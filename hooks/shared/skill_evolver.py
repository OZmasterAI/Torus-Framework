#!/usr/bin/env python3
"""Skill evolution engine for Skill MCP v2 — FIX type (Phase 3).

Ported from OpenSpace evolver.py. Uses claude -p via ClaudePClient.
Iteration logic: up to 5 LLM calls with nudge, 3 apply-retry attempts.
Records lineage in SQLite and updates SKILL.md on disk.
"""

import os
import sqlite3
import uuid
from datetime import datetime, timezone

from shared.skill_db import (
    get_skill_record,
    add_lineage_parent,
)

# Constants from OpenSpace evolver.py
EVOLUTION_COMPLETE = "<EVOLUTION_COMPLETE>"
EVOLUTION_FAILED = "<EVOLUTION_FAILED>"
MAX_ITERATIONS = 5
MAX_ATTEMPTS = 3
_SKILL_CONTENT_MAX_CHARS = 12_000

# ── FIX prompt (ported from OpenSpace skill_engine_prompts.py) ──

_FIX_PROMPT = """You are a skill editor. Your job is to **fix** an existing skill that has
been identified as broken, outdated, or incomplete.

A skill is a directory containing ``SKILL.md`` (the main instruction file)
and optionally auxiliary files (scripts, configs, examples, etc.).

## Current Skill Content

{current_content}

## What needs fixing

{direction}

## Execution failure context

These are recent task executions where this skill was involved:

{failure_context}

## Tool issue details

{tool_issue_summary}

## Skill health metrics

{metric_summary}

## Instructions

1. Analyze the failure context and identify the root cause in the skill's
   instructions (wrong parameters, outdated API, missing error handling, etc.).
2. Fix the affected files to address the identified issues.
3. Preserve the overall structure and YAML frontmatter format.
4. Keep name and description in frontmatter; update description only if
   the skill's purpose has changed.
5. Be surgical -- fix what's broken without unnecessary rewrites.

## Output format

Your output MUST have exactly two parts:

**Part 1** -- A summary line on the very first line:

CHANGE_SUMMARY: <one-sentence description of what you fixed>

**Part 2** -- The full updated SKILL.md content.

## Self-Assessment

**If your edit is satisfactory** -- include <EVOLUTION_COMPLETE> on the last line.
**If you cannot produce a satisfactory edit** -- output ONLY:
<EVOLUTION_FAILED>
Reason: <brief explanation>
"""

_NUDGE_TEMPLATE = """Iteration {iteration}/{max_iterations} complete. Your previous output did not include a termination token.

If your edit is ready, output it now with CHANGE_SUMMARY on the first line and <EVOLUTION_COMPLETE> on the last line.
If you cannot fix this skill, output only <EVOLUTION_FAILED> with a reason.

Previous attempt:
{previous_output}
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid8() -> str:
    return uuid.uuid4().hex[:8]


def build_fix_prompt(
    current_content: str,
    direction: str,
    failure_context: str = "",
    tool_issue_summary: str = "",
    metric_summary: str = "",
) -> str:
    """Build the FIX evolution prompt with task-specific data."""
    return _FIX_PROMPT.format(
        current_content=current_content[:_SKILL_CONTENT_MAX_CHARS],
        direction=direction or "(no specific direction)",
        failure_context=failure_context or "(no failure context available)",
        tool_issue_summary=tool_issue_summary or "(no tool issues reported)",
        metric_summary=metric_summary or "(no metrics available)",
    )


def parse_evolution_response(response: str) -> dict:
    """Parse LLM evolution response for termination tokens and content.

    Returns dict with:
        complete: True if EVOLUTION_COMPLETE found
        failed: True if EVOLUTION_FAILED found
        change_summary: extracted summary line
        content: the SKILL.md content (without summary line and tokens)
    """
    text = response.strip()

    if EVOLUTION_FAILED in text:
        return {"complete": False, "failed": True, "change_summary": "", "content": ""}

    complete = EVOLUTION_COMPLETE in text

    # Extract CHANGE_SUMMARY
    change_summary = ""
    lines = text.split("\n")
    content_start = 0
    for i, line in enumerate(lines):
        if line.startswith("CHANGE_SUMMARY:"):
            change_summary = line.split(":", 1)[1].strip()
            content_start = i + 1
            break

    # Extract content: everything between summary and EVOLUTION_COMPLETE
    content_lines = []
    for line in lines[content_start:]:
        if EVOLUTION_COMPLETE in line:
            continue
        content_lines.append(line)

    content = "\n".join(content_lines).strip()

    return {
        "complete": complete,
        "failed": False,
        "change_summary": change_summary,
        "content": content,
    }


def evolve_skill(
    conn: sqlite3.Connection,
    llm_client,
    skill_id: str,
    skill_name: str,
    skill_dir: str,
    direction: str,
    failure_context: str = "",
    tool_issues: str = "",
    metric_summary: str = "",
) -> dict:
    """Run FIX evolution on a skill.

    Iteration loop:
    1. Send FIX prompt
    2. Check for EVOLUTION_COMPLETE or EVOLUTION_FAILED
    3. If neither, send nudge and retry (up to MAX_ITERATIONS)
    4. On success: write SKILL.md, record lineage in SQLite

    Returns dict with success, change_summary, new_skill_id, iterations.
    """
    md_path = os.path.join(skill_dir, "SKILL.md")
    if not os.path.exists(md_path):
        return {"success": False, "error": f"SKILL.md not found at {md_path}"}

    with open(md_path) as f:
        original_content = f.read()

    # Build initial prompt
    prompt = build_fix_prompt(
        current_content=original_content,
        direction=direction,
        failure_context=failure_context,
        tool_issue_summary=tool_issues,
        metric_summary=metric_summary,
    )

    last_response = ""
    for iteration in range(1, MAX_ITERATIONS + 1):
        if iteration == 1:
            current_prompt = prompt
        else:
            current_prompt = _NUDGE_TEMPLATE.format(
                iteration=iteration,
                max_iterations=MAX_ITERATIONS,
                previous_output=last_response[:2000],
            )

        response = llm_client.complete(current_prompt, max_tokens=4000)
        last_response = response
        parsed = parse_evolution_response(response)

        if parsed["failed"]:
            return {
                "success": False,
                "iterations": iteration,
                "reason": "LLM declared EVOLUTION_FAILED",
            }

        if parsed["complete"] and parsed["content"]:
            # Success — apply the evolution
            return _apply_evolution(
                conn=conn,
                skill_id=skill_id,
                skill_name=skill_name,
                skill_dir=skill_dir,
                md_path=md_path,
                original_content=original_content,
                new_content=parsed["content"],
                change_summary=parsed["change_summary"],
                iterations=iteration,
            )

    # Exhausted iterations
    return {
        "success": False,
        "iterations": MAX_ITERATIONS,
        "reason": "Max iterations exhausted without EVOLUTION_COMPLETE",
    }


def _apply_evolution(
    conn: sqlite3.Connection,
    skill_id: str,
    skill_name: str,
    skill_dir: str,
    md_path: str,
    original_content: str,
    new_content: str,
    change_summary: str,
    iterations: int,
) -> dict:
    """Write evolved SKILL.md and record lineage in SQLite."""
    now = _now_iso()
    old_rec = get_skill_record(conn, skill_id)
    old_gen = old_rec["lineage_generation"] if old_rec else 0
    new_gen = old_gen + 1
    new_skill_id = f"{skill_name}__v{new_gen}_{_uuid8()}"

    # Write new SKILL.md
    with open(md_path, "w") as f:
        f.write(new_content)

    # Create new skill record in SQLite
    conn.execute(
        """INSERT INTO skill_records
           (skill_id, name, description, path, is_active, category,
            lineage_origin, lineage_generation, lineage_change_summary,
            lineage_content_diff, lineage_content_snapshot,
            lineage_created_at, lineage_created_by,
            total_selections, total_applied, total_completions, total_fallbacks,
            first_seen, last_updated)
           VALUES (?, ?, ?, ?, 1, ?, 'evolved_fix', ?, ?, ?, ?, ?, ?,
                   0, 0, 0, 0, ?, ?)""",
        (
            new_skill_id,
            skill_name,
            old_rec.get("description", "") if old_rec else "",
            skill_dir,
            old_rec.get("category", "workflow") if old_rec else "workflow",
            new_gen,
            change_summary,
            "",  # content_diff (could compute later)
            new_content[:500],  # snapshot
            now,
            "skill_evolver_v2",
            now,
            now,
        ),
    )

    # Record lineage parent
    add_lineage_parent(conn, new_skill_id, skill_id)

    # Deactivate old skill record
    conn.execute(
        "UPDATE skill_records SET is_active = 0, last_updated = ? WHERE skill_id = ?",
        (now, skill_id),
    )
    conn.commit()

    return {
        "success": True,
        "new_skill_id": new_skill_id,
        "change_summary": change_summary,
        "iterations": iterations,
        "generation": new_gen,
    }
