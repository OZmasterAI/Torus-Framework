# /chain — Skill Composition Pipeline

## When to use
When the user says "chain", "pipeline", "then", "sequence", "workflow", "run all", or wants to compose multiple skills into a sequential execution pipeline.

Examples:
- `/chain explore -> refactor -> test -> commit`
- `/chain review -> fix -> test`
- `/chain research -> build -> test -> deploy`

## Steps

### 1. PARSE CHAIN
- Parse skill names from the chain string by splitting on `->` or `→`
- Trim whitespace from each skill name, strip any leading `/` prefix
- Validate each skill exists in `~/.claude/skills/` (check for `SKILL.md`)
- If any skill is missing, report which ones and abort
- Maximum chain length: 6 skills (reject longer chains with explanation)
- Show execution plan to user:
  ```
  Chain: /skill_1 → /skill_2 → /skill_3
  Steps: 3 | Mode: stop-on-failure
  ```
- Wait for user confirmation before starting

### 2. MEMORY CHECK
- `search_knowledge("chain execution")` — find prior chain runs and lessons learned
- `search_knowledge("[first skill in chain]")` — check for known issues with lead skill
- Note any past chain failures or gotchas to watch for during execution

### 3. EXECUTE SEQUENTIALLY
For each skill in the chain (N = current, M = total):

**Announce:**
```
━━━ Step N/M: Running /skill_name ━━━
```

**Execute:**
- Follow that skill's SKILL.md steps faithfully
- Memory context flows naturally — each skill's `remember_this` calls are visible to subsequent skills via `search_knowledge`

**On failure** (tests fail, errors, tool failures):
- STOP the chain immediately
- Show what failed and why
- Ask the user:
  - **Continue** — skip this skill, proceed to the next one
  - **Retry** — re-run the current skill
  - **Abort** — stop the chain entirely

**On success:**
- Mark the skill as complete and proceed to the next one

### 4. CHECKPOINT
After each skill completes successfully:
- `remember_this("Chain step N/M: /skill_name completed — [brief outcome]", "chain execution", "type:learning,area:framework")`
- This creates a breadcrumb trail that later skills (and future sessions) can reference

### 5. SUMMARY
After the chain finishes (all skills complete or chain aborted), display results:

```
Chain Results
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  /skill_1 .... OK
  /skill_2 .... OK
  /skill_3 .... FAILED (reason)
  /skill_4 .... SKIPPED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Completed: 2/4 | Failed: 1 | Skipped: 1
```

### 6. SAVE
- `remember_this("Chain [skill_1 -> skill_2 -> ...]: [N/M completed]. Outcomes: [brief per-skill results]", "chain pipeline execution", "type:learning,area:framework")`
- Include which skills succeeded, which failed, and why
- Tag failures with relevant error patterns for future `query_fix_history` lookups
