# /implement — Execute Implementation

## When to use
When the user says "implement", "build", "create", or the Loop reaches the implementation step.

## Steps

### 1. CONTEXT
- search_knowledge("[task]") — check for prior art, known gotchas
- Read docs/plans/<feature>-impl.md if exists
- If no plan and task is non-trivial, ask: "Run /writing-plans first?"

### 2. EXECUTE
For each task (from plan or verbal description):
- Write the test first (must fail initially)
- Write the implementation, follow existing code patterns
- Run test — confirm it passes
- If fail: fix and retry (max 3 attempts per task)
- Do NOT accumulate multiple unverified changes

### 3. PROVE
- Run full test suite, show actual output
- Never say "done" without evidence

### 4. SAVE
- remember_this("[what was built]", "[context]", "type:feature,outcome:success")

## Circuit breakers
- 3 consecutive failures on same task → stop, report, let user decide
- Kill rule: 15 min stuck → stop and present alternatives
