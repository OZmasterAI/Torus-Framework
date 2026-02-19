# /build — Full Factory Loop

## When to use
When the user says "build", "implement", "create", or wants the full quality workflow for a non-trivial feature or fix.

## The Loop (mandatory order — do not skip steps)

### 1. MEMORY CHECK
- `search_knowledge("[what you're about to build]")` — check for prior art, known issues, past decisions
- `query_fix_history("[relevant errors]")` if fixing something — see what's been tried before
- If memory returns relevant entries, use `get_memory(id)` for full details

### 2. PLAN
- Enter Plan Mode (`EnterPlanMode` tool)
- Explore the codebase: read relevant files, understand existing patterns
- Write a clear plan with:
  - Files to create/modify
  - Approach and rationale
  - Success criteria (what "done" looks like)
- Exit Plan Mode for user approval before proceeding
- Save the plan to memory: `remember_this("Plan: [summary]", "planning [feature]", "type:decision")`

### 3. TESTS FIRST
- Define success criteria before writing implementation code
- If the project has a test framework, write test stubs or assertions first
- If no test framework, define manual verification steps
- These tests should FAIL initially (proving they test the right thing)

### 4. BUILD
- Implement piece by piece, not all at once
- After each significant piece:
  - Run tests or verify the piece works
  - If something breaks, stop and fix before continuing
  - Do NOT accumulate multiple unverified changes
- Follow existing code patterns and conventions in the project

### 5. PROVE IT
- Run the full test suite — show actual output
- Never say "fixed" or "done" without evidence
- If tests fail, go back to step 4
- Show the user proof: test output, curl responses, screenshots, etc.

### 6. SHIP
- Save to memory: `remember_this("[what was built and how]", "[context]", "type:feature,outcome:success")`
- If the user wants a commit, invoke the `/commit` skill
- Update LIVE_STATE.json if this was significant work

## Kill Rule
If after 15 minutes of trying, the approach isn't working:
- STOP building
- Save what you learned to memory
- Present the user with:
  - What was tried
  - Why it's not working
  - Alternative approaches to consider
- Let the user decide the next move
