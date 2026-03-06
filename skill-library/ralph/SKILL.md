# /ralph — Autonomous Execution Loop

## When to use
When the user says "ralph", "autonomous", "auto-pilot", or wants extended unattended execution on a well-defined task.

## Safety Circuit Breakers (non-negotiable)
Before entering the loop, state these limits to the user:
- **Max iterations**: 10 build-verify cycles (then stop and report)
- **Error ceiling**: 3 consecutive failures on the same step triggers a full stop
- **No destructive actions**: Gate 2 still enforced — no rm -rf, force push, reset --hard
- **No deploys**: Autonomous mode NEVER deploys. Use `/deploy` manually.
- **Memory saves**: Save to memory every 3 iterations or after any significant discovery
- **User can interrupt**: Remind the user they can stop you at any time

## The Autonomous Loop

### Phase 0: SETUP
1. Confirm the task is clearly defined. If ambiguous, ask for clarification BEFORE entering the loop.
2. `search_knowledge("[task description]")` — check for relevant history
3. State your plan and circuit breaker limits to the user
4. Get explicit user approval: "Starting autonomous mode. I'll work through up to 10 iterations. Ready?"

### Phase 1: PLAN (iteration 0)
1. Enter Plan Mode, explore the codebase, write the plan
2. Break the task into ordered sub-tasks (numbered checklist)
3. Exit Plan Mode for user approval
4. Save plan to memory

### Phase 2: EXECUTE (iterations 1-N)
For each sub-task in order:
1. **Check**: Is this sub-task still relevant? (Prior steps may have changed things)
2. **Build**: Implement the sub-task
3. **Test**: Run relevant tests or verification
3b. **Visual Verify** (if UI task): Run `/browser verify <url>` — screenshot must confirm correctness before marking done
4. **Record**: If tests pass, mark sub-task done. If tests fail:
   - Increment failure counter
   - `record_attempt("[error]", "[strategy]")` — log the attempt
   - Try an alternative approach
   - If 3 consecutive failures: STOP (see Phase 3)
5. **Save**: Every 3 iterations: `remember_this("[progress so far]", "ralph autonomous", "type:learning")`
6. **Next**: Move to next sub-task

### Phase 3: STOP CONDITIONS (any triggers full stop)
- All sub-tasks complete (success)
- 10 iterations reached (report progress, ask user)
- 3 consecutive failures on same step (report blocker, ask user)
- Encountered a situation requiring human judgment (ambiguous requirement, risky action, etc.)

### Phase 4: REPORT
Always end with a summary:
- Sub-tasks completed: X/Y
- Tests passing: show output
- Iterations used: N/10
- Failures encountered: list with strategies tried
- Screenshots taken: list paths (if any)
- What's left (if incomplete): ordered remaining tasks
- Save final state to memory: `remember_this("[ralph session summary]", "autonomous execution", "type:learning,outcome:[success|partial|blocked]")`

## What Ralph NEVER Does
- Deploy to production
- Push to remote repositories
- Delete files or branches without user confirmation
- Skip tests to move faster
- Continue past circuit breaker limits
- Make architectural decisions without user approval
