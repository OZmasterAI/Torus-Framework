# /writing-plans — TDD Implementation Plan Generator

## When to use
When the user says "writing-plans", "write plan", "implementation plan",
"TDD plan", or has chosen a design option from /brainstorm and wants a
concrete implementation plan with exact code.

## Prerequisites
- A design decision should exist (from /brainstorm, or user's own description)
- If no design doc exists, ask: "What are we implementing? Should we
  /brainstorm first?"

## Steps

### 1. LOAD CONTEXT
- Check docs/plans/ for a recent design doc matching the topic
- search_knowledge("[feature]") for relevant decisions and patterns
- Read the files that will be modified (understand current state)

### 2. DEFINE SUCCESS CRITERIA
Before writing any plan:
- What does "done" look like? (specific, testable)
- What existing tests must still pass?
- What new tests need to exist?

### 3. GENERATE TDD TASK LIST
Break the implementation into ordered tasks. Each task:

- **Task N: [imperative title]**
  - **Test first**: Exact test code or assertion to write (must fail initially)
  - **Implementation**: Exact code changes with file paths and line references
  - **Verify**: Command to run to prove this task works
  - **Depends on**: Which prior tasks must complete first

Rules:
- Tasks should be small enough to implement in one shot (1-3 edits each)
- Every task has a test-first step (even if it's just a Bash verification)
- Code snippets must be real — no pseudocode, no "implement X here" placeholders
- Reference actual function names, file paths, and line numbers from exploration

### 4. WRITE PLAN FILE
Write the implementation plan to docs/plans/<feature-slug>-impl.md:

  # Implementation Plan: <Feature Name>
  ## Design Decision: <chosen option from brainstorm>
  ## Success Criteria
  ## Tasks
  ### Task 1: ...
  ### Task 2: ...
  ...
  ## Verification (end-to-end)
  ## Rollback (if something goes wrong)

### 5. PRESENT FOR APPROVAL
Show the task list inline. Ask: "Ready to build? Run /build to execute."

### 6. SAVE TO MEMORY
- remember_this("Plan: [feature] — [N tasks, key files]",
  "[context]", "type:decision,area:[relevant]")

## Output
- Implementation plan saved to docs/plans/<feature-slug>-impl.md
- Task list presented inline for user review
- User approves, then runs /build (or implements manually)
