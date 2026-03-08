# /prp — Product Requirements Prompts

## When to use
When user says "prp", "create a prp", "blueprint", "structured plan",
or wants a comprehensive implementation blueprint for a complex feature.

## Commands
- `/prp new-project <description>` — Create requirements, roadmap, and first phase PRP
- `/prp generate <feature-description>` — Research and create a PRP for a single feature
- `/prp plan-phase <prp-name> <phase-N>` — Generate tasks for a phase, verify against requirements
- `/prp execute <prp-file>` — Implement a PRP (or use /loop for fresh-context execution)
- `/prp verify-phase <prp-name>` — 3-level verification: exists, substantive, wired
- `/prp list` — List existing PRPs
- `/prp status <prp-name>` — Show task pass/fail status from tasks.json

## New Project Flow
1. **MEMORY CHECK**: search_knowledge for similar projects, past PRPs
2. **GATHER REQUIREMENTS**: Ask user about goals, scope, constraints
3. **CREATE REQUIREMENTS.md**: Read ~/.claude/PRPs/templates/requirements.md, fill with R1..RN
4. **CREATE ROADMAP.md**: Read ~/.claude/PRPs/templates/roadmap.md, decompose into phases
5. **CREATE CONTEXT.md**: Read ~/.claude/PRPs/templates/context.md, fill with locked architectural decisions, constraints, naming conventions. These are injected into every executor prompt and cannot be overridden by tasks.
6. **PLAN FIRST PHASE**: Auto-run plan-phase flow for Phase 1
7. **SAVE**: Write to ~/.claude/PRPs/{project-name}/ directory
8. **REMEMBER**: remember_this() with project summary and tags

## Generate Flow (single feature PRP)
1. **MEMORY CHECK**: search_knowledge for similar features, past PRPs, known issues
2. **CODEBASE SCAN**: Explore relevant files, identify patterns to follow
3. **EXTERNAL RESEARCH**: WebSearch/WebFetch for library docs, API references (if needed)
4. **FILL TEMPLATE**: Read ~/.claude/PRPs/templates/base.md and fill every section
5. **SAVE**: Write to ~/.claude/PRPs/{feature-name}.md
5b. **GENERATE TASKS.JSON**: Extract tasks from `## Implementation Tasks`, create `~/.claude/PRPs/{feature-name}.tasks.json` with id, name, status, requirement_id, files, validate, done, depends_on per task
6. **REMEMBER**: remember_this() with the PRP summary and tags
7. **PRESENT**: Show the PRP to the user for review/adjustment

## Plan Phase Flow
1. **LOAD**: Read requirements.md and roadmap.md for the project
2. **IDENTIFY**: Determine which requirements belong to this phase
3. **RESEARCH**: search_knowledge + codebase scan for phase-specific context
4. **GENERATE PRP**: Create phase PRP using base.md template, with Requirement field on each task
5. **GENERATE TASKS.JSON**: Create tasks.json with milestone, phase, requirement_id fields
6. **PLAN VERIFY**: Run `python3 ~/.claude/scripts/prp-plan-verify.py <prp-name> <requirements-file> [--round N]`
   - Exit 0 → plan covers all requirements, proceed
   - Exit 1 → gaps found: revise tasks to cover uncovered requirements, re-run (max 2 rounds)
   - Exit 2 → error (bad args, missing files)
   - If still gaps after 2 rounds → flag to user with gap details
7. **SAVE + REMEMBER**

## Execute Flow
1. **LOAD**: Read the PRP file
2. **MEMORY CHECK**: search_knowledge for related fixes, gotchas since PRP was created
3. **IMPLEMENT**: Follow the task list in order, referencing docs and examples
4. **VALIDATE**: Run each validation gate from the PRP
5. **PROVE**: Show test output for every success criterion
6. **VERIFY**: Run `python3 ~/.claude/scripts/prp-phase-verify.py <prp-name> --auto-fix`
   - Exit 0 → all completed tasks pass 3-level verification, proceed to SAVE
   - Exit 1 → failures found: fix auto-generated tasks, then re-run verification
   - Do NOT skip this step — it catches stubs, missing files, and unwired code
7. **SAVE**: remember_this() with outcome + verification results, link back to PRP

## Verify Phase Flow
1. **RUN VERIFIER**: `python3 ~/.claude/scripts/prp-phase-verify.py <prp-name> [--auto-fix]`
   - Exit 0 → all completed tasks pass 3-level verification
   - Exit 1 → failures found, grouped by level:
     - **Level 1 (Missing)**: Files don't exist
     - **Level 2 (Stubs)**: TODO, FIXME, NotImplementedError, placeholder stubs remain
     - **Level 3 (Unwired)**: Files not imported/referenced by sibling files
   - `--auto-fix` creates fix tasks in tasks.json for each failure
2. **REVIEW**: Show pass/fail per task with specific issues from JSON output
3. **FIX OR DEFER**: Use auto-generated fix tasks, or defer with justification
4. **SAVE**: remember_this() with verification results

## List Flow
1. **SCAN**: Glob ~/.claude/PRPs/*.md (excluding templates/)
2. **DISPLAY**: Show each PRP with name, status, confidence, and creation date

## Status Flow
1. **LOAD TASKS**: Read ~/.claude/PRPs/{prp-name}.tasks.json via task_manager.py
2. **DISPLAY**: Show table with task id, name, status, requirement_id
3. **SUMMARY**: Show counts per status + requirement coverage

## Rules
- NEVER skip the "Known Gotchas" section — this is the highest-value part
- ALWAYS include executable validation commands
- ALWAYS check examples/ directory for existing patterns before proposing new ones
- ALWAYS run plan-check before marking a phase plan as ready
- If a PRP takes >3 minutes to generate, delegate research to sub-agents
- Tag memory saves with "type:prp" for easy retrieval
- Max 2 plan revision rounds — if still gaps after 2, flag to user
- **LEAN ORCHESTRATOR**: When executing via /loop, the orchestrator NEVER implements code itself — it only plans, dispatches tasks to fresh executor instances, and validates results. This keeps the orchestrator's context clean and gives each task fresh reasoning capacity.
