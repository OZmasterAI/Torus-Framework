# /implement — Execute Implementation

## When to use
When the user says "implement", "build", "create", or the Loop reaches the implementation step.

## Steps

### 0. CHECK ORCHESTRATOR MODE
- Read config.json `orchestrator` flag
- If `true` AND a `PRPs/<feature-slug>.tasks.json` exists (check `PRPs/` then `~/.claude/PRPs/`):
  - Read tasks.json and create a Claude Code task (TaskCreate) for each task entry
  - Tell the user: "Orchestrator mode is on. Launching torus-loop.sh with N tasks"
  - Run in background: `bash ~/.claude/scripts/torus-loop.sh <feature-slug>`
  - Poll `task_manager.py status <feature-slug>` every 30s to check progress
  - Update Claude Code tasks (TaskUpdate) as they pass/fail/skip
  - When done, report results from `PRPs/<feature-slug>.activity.md`
  - Skip to step 4 (SAVE)
- If `true` but no tasks.json exists:
  - Ask: "No tasks.json found. Run /writing-plans first to generate one?"
- If `false`: continue with inline execution below

### 1. CONTEXT
- search_knowledge("[task]") — check for prior art, known gotchas
- Read docs/plans/<feature>-impl.md if exists
- If no plan and task is non-trivial, ask: "Run /writing-plans first?"

### 2. EXECUTE
- Create a Claude Code task (TaskCreate) for each task from the plan or verbal description
- Work through tasks in order. For each task:
  - Mark it in_progress (TaskUpdate)
  - Write the test first (must fail initially)
  - Write the implementation, follow existing code patterns
  - Run test — confirm it passes
  - If fail: fix and retry (max 3 attempts per task)
  - Mark completed or note failure (TaskUpdate)
- Do NOT accumulate multiple unverified changes

### 3. PROVE
- Run full test suite, show actual output
- Never say "done" without evidence

### 4. SAVE
- remember_this("[what was built]", "[context]", "type:feature,outcome:success")

## Circuit breakers
- 3 consecutive failures on same task → stop, report, let user decide
- Kill rule: 15 min stuck → stop and present alternatives
