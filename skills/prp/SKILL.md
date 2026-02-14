# /prp — Product Requirements Prompts

## When to use
When user says "prp", "create a prp", "blueprint", "structured plan",
or wants a comprehensive implementation blueprint for a complex feature.

## Commands
- `/prp generate <feature-description>` — Research and create a PRP
- `/prp execute <prp-file>` — Implement a PRP
- `/prp list` — List existing PRPs
- `/prp status <prp-name>` — Show task pass/fail status from tasks.json

## Generate Flow
1. **MEMORY CHECK**: search_knowledge for similar features, past PRPs, known issues
2. **CODEBASE SCAN**: Explore relevant files, identify patterns to follow
3. **EXTERNAL RESEARCH**: WebSearch/WebFetch for library docs, API references (if needed)
4. **FILL TEMPLATE**: Read ~/.claude/PRPs/templates/base.md and fill every section
5. **SAVE**: Write to ~/.claude/PRPs/{feature-name}.md
5b. **GENERATE TASKS.JSON**: Extract tasks from `## Implementation Tasks`, create `~/.claude/PRPs/{feature-name}.tasks.json` with id, name, status, files, validate, depends_on per task
6. **REMEMBER**: remember_this() with the PRP summary and tags
7. **PRESENT**: Show the PRP to the user for review/adjustment

## Execute Flow
1. **LOAD**: Read the PRP file
2. **MEMORY CHECK**: search_knowledge for related fixes, gotchas since PRP was created
3. **IMPLEMENT**: Follow the task list in order, referencing docs and examples
4. **VALIDATE**: Run each validation gate from the PRP
5. **PROVE**: Show test output for every success criterion
6. **SAVE**: remember_this() with outcome, link back to PRP

## List Flow
1. **SCAN**: Glob ~/.claude/PRPs/*.md (excluding templates/)
2. **DISPLAY**: Show each PRP with name, status, confidence, and creation date

## Status Flow
1. **LOAD TASKS**: Read ~/.claude/PRPs/{prp-name}.tasks.json via task_manager.py
2. **DISPLAY**: Show table with task id, name, status (pending/in_progress/passed/failed)
3. **SUMMARY**: Show counts per status

## Rules
- NEVER skip the "Known Gotchas" section — this is the highest-value part
- ALWAYS include executable validation commands
- ALWAYS check examples/ directory for existing patterns before proposing new ones
- If a PRP takes >3 minutes to generate, delegate research to sub-agents
- Tag memory saves with "type:prp" for easy retrieval
