#!/usr/bin/env python3
"""Post-task skill analyzer for Skill MCP v2.

Ported from OpenSpace analyzer.py prompts. Evaluates how a skill was used
during task execution, stores judgments in SQLite, and updates quality counters.
"""

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone

# Constants from OpenSpace evolver.py
_ANALYSIS_NOTE_MAX_CHARS = 500

# ── Analysis prompt (adapted from OpenSpace skill_engine_prompts.py) ──

_ANALYSIS_PROMPT = """You are an expert analyst evaluating a Claude Code skill execution.
Your job is to assess how the skill was used and surface actionable insights.

## Task Context

**Skill**: {skill_name}
**Skill applied**: The skill was invoked for this task.
**Agent self-reported status**: {execution_status}

## Skill Content

{skill_content}

## Execution Context

{context}

## Analysis Instructions

1. Task completion assessment (independent of the agent's self-report)
2. Skill assessment: was the skill actually applied? Did the agent follow its instructions?
3. Tool issues: any tools that failed or behaved unexpectedly?
4. Evolution suggestions: should this skill be fixed, derived, or is there a new pattern to capture?

## Output format

Return exactly one JSON object (no markdown fences, no extra text):
{{
  "task_completed": true,
  "execution_note": "2-3 sentence overview of what happened",
  "tool_issues": ["tool_name -- symptom; probable cause"],
  "skill_judgments": [
    {{"skill_id": "{skill_id}", "skill_applied": true, "note": "How the skill was used"}}
  ],
  "evolution_suggestions": [
    {{"type": "fix|derived|captured", "target_skills": ["{skill_name}"], "category": "workflow", "direction": "What should change"}}
  ]
}}

Rules:
- task_completed: YOUR independent assessment, not the agent's self-report
- skill_applied: true if the agent followed the skill's instructions, false if ignored
- evolution_suggestions: empty array if the skill worked well; include entries only for real issues
- tool_issues: empty array if no tools failed
"""


def build_analysis_prompt(
    skill_name: str,
    skill_content: str,
    success: bool,
    context: str,
    skill_id: str = "",
) -> str:
    """Build the analysis prompt with task-specific data injected."""
    execution_status = "success" if success else "failure"
    return _ANALYSIS_PROMPT.format(
        skill_name=skill_name,
        skill_content=skill_content[:12000],
        execution_status=execution_status,
        context=context or "(no context provided)",
        skill_id=skill_id or skill_name,
    )


def parse_analysis_response(response: str) -> dict:
    """Parse LLM analysis response, extracting JSON from plain or fenced output.

    Returns a valid analysis dict even on parse failure (with defaults).
    """
    # Try direct JSON parse first
    try:
        return json.loads(response.strip())
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code fence
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", response, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try finding JSON object in the response
    brace_match = re.search(r"\{.*\}", response, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    # Fallback: return safe defaults
    return {
        "task_completed": False,
        "execution_note": f"Failed to parse analysis response (got {len(response)} chars)",
        "tool_issues": [],
        "skill_judgments": [],
        "evolution_suggestions": [],
    }


def store_analysis(
    conn: sqlite3.Connection,
    task_id: str,
    analysis: dict,
) -> int | None:
    """Store analysis results in SQLite and update skill counters.

    Writes to execution_analyses and skill_judgments tables.
    Updates skill_records counters based on judgments.

    Returns the analysis row ID, or None if task_id already exists.
    """
    now = datetime.now(timezone.utc).isoformat()

    # Insert execution_analyses
    try:
        cur = conn.execute(
            """INSERT INTO execution_analyses
               (task_id, timestamp, task_completed, execution_note,
                tool_issues, candidate_for_evolution, evolution_suggestions,
                analyzed_by, analyzed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                task_id,
                now,
                1 if analysis.get("task_completed") else 0,
                analysis.get("execution_note", "")[:_ANALYSIS_NOTE_MAX_CHARS],
                json.dumps(analysis.get("tool_issues", [])),
                1 if analysis.get("evolution_suggestions") else 0,
                json.dumps(analysis.get("evolution_suggestions", [])),
                "skill_analyzer_v2",
                now,
            ),
        )
        analysis_id = cur.lastrowid
    except sqlite3.IntegrityError:
        # Duplicate task_id
        return None

    task_completed = analysis.get("task_completed", False)

    # Insert skill_judgments and update counters
    for judgment in analysis.get("skill_judgments", []):
        skill_id = judgment.get("skill_id", "")
        skill_applied = judgment.get("skill_applied", False)
        note = judgment.get("note", "")[:_ANALYSIS_NOTE_MAX_CHARS]

        # Store judgment
        try:
            conn.execute(
                """INSERT INTO skill_judgments (analysis_id, skill_id, skill_applied, note)
                   VALUES (?, ?, ?, ?)""",
                (analysis_id, skill_id, 1 if skill_applied else 0, note),
            )
        except sqlite3.IntegrityError:
            continue

        # Update counters (OpenSpace logic)
        applied_inc = 1 if skill_applied else 0
        completed_inc = 1 if (skill_applied and task_completed) else 0
        fallback_inc = 1 if (not skill_applied and not task_completed) else 0

        conn.execute(
            """UPDATE skill_records SET
               total_applied     = total_applied + ?,
               total_completions = total_completions + ?,
               total_fallbacks   = total_fallbacks + ?,
               last_updated      = ?
               WHERE skill_id = ?""",
            (applied_inc, completed_inc, fallback_inc, now, skill_id),
        )

    conn.commit()
    return analysis_id


def analyze_task(
    conn: sqlite3.Connection,
    llm_client,
    skill_name: str,
    skill_content: str,
    success: bool,
    context: str = "",
    task_id: str | None = None,
) -> dict | None:
    """Full analysis pipeline: build prompt, call LLM, parse, store.

    Args:
        conn: SQLite connection.
        llm_client: Object with .complete(prompt) method.
        skill_name: Name of the skill that was used.
        skill_content: Full SKILL.md content.
        success: Whether the task succeeded (agent self-report).
        context: Brief description of what happened.
        task_id: Unique task identifier (auto-generated if None).

    Returns:
        Parsed analysis dict, or None on failure.
    """
    if task_id is None:
        task_id = f"task-{uuid.uuid4().hex[:12]}"

    # Look up skill_id from DB
    row = conn.execute(
        "SELECT skill_id FROM skill_records WHERE name = ?", (skill_name,)
    ).fetchone()
    skill_id = row["skill_id"] if row else skill_name

    prompt = build_analysis_prompt(
        skill_name=skill_name,
        skill_content=skill_content,
        success=success,
        context=context,
        skill_id=skill_id,
    )

    response = llm_client.complete(prompt, max_tokens=2000)
    analysis = parse_analysis_response(response)

    store_analysis(conn, task_id=task_id, analysis=analysis)
    return analysis
