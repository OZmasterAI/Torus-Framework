# /analyze-errors — Recurring Error Deep Analysis

## When to use
When the user says "analyze error", "why failing", "pattern", "recurring", "diagnose", "root cause", or wants to understand why an error keeps happening, find patterns in failures, or build a prevention strategy.

Complements `/fix` (immediate resolution) by doing **historical pattern analysis** across all memory to find systemic causes and build prevention playbooks.

## Steps

### 1. DEEP QUERY
- `search_knowledge("[error pattern or message]", top_k=50)` — get all historical instances
- `search_knowledge("[error keywords]")` — catch keyword matches the semantic search may miss
- `search_knowledge("[error pattern]", mode="all")` — also includes auto-captured observations
- Collect every memory entry related to this error for comprehensive analysis

### 2. TIMELINE
Organize findings chronologically:
- Sort all occurrences by timestamp
- Build a progression view:
  ```
  Date       | Occurrence | Context              | Resolution
  -----------+------------+----------------------+------------------
  2026-01-15 | First seen | After deploying v2.1 | Manual fix
  2026-01-22 | Recurred   | Same endpoint        | Same manual fix
  2026-02-01 | Recurred   | Different trigger    | Attempted new fix
  2026-02-10 | Still open | Expanded scope       | Under investigation
  ```
- Assess trend: **getting worse**, **stable**, **improving**, or **resolved**
- Note any periodicity (daily, weekly, after deploys, after specific operations)

### 3. ROOT CAUSE
Read full entries with `get_memory(id)` for each occurrence. Classify the error:

| Category | Indicators | Examples |
|----------|-----------|----------|
| **Flaky test** | Passes sometimes, fails sometimes; no code change between runs | Race condition in async test, timing-dependent assertion |
| **Edge case** | Specific input triggers it; works for most inputs | Unicode in filenames, empty arrays, null values |
| **Environment** | Works locally, fails in CI; or vice versa | Missing env var, different Python version, disk space |
| **Race condition** | Intermittent; depends on timing/ordering | Concurrent writes, async callback ordering |
| **Integration failure** | External dependency changed or unavailable | API version mismatch, service downtime, schema change |
| **Regression** | Worked before, broke after specific commit | Side effect of refactor, dependency update |

For each classification:
- Identify the **trigger condition** (what makes it happen)
- Identify the **propagation path** (how the error surfaces)
- Identify the **root cause** (why the trigger leads to failure)

### 4. CORRELATE
Cross-reference with fix history:
- `query_fix_history("[error text]")` — find what strategies were tried
- Check **recommended** strategies (high confidence, worked before)
- Check **banned** strategies (tried and failed multiple times)
- Cross-reference with `search_knowledge("[error]", mode="all")` for the full history including observations
- Look for **error windows**: clusters of related errors that appear together
- Map the **causal chain**: Error A causes Error B which triggers Error C

### 5. PREVENTION
Based on the root cause analysis, recommend layered prevention:

**Immediate fixes:**
- Guard clauses for the specific trigger condition
- Input validation at the boundary where bad data enters
- Error handling that prevents cascade failures

**Test coverage gaps:**
- Identify missing test cases that would catch this error
- Propose specific test scenarios (edge cases, boundary values)
- Recommend test types: unit, integration, end-to-end, property-based

**Monitoring and detection:**
- Log patterns to watch for (early warning signals)
- Health checks or assertions that catch the error before it propagates
- Metrics to track (error rate, response time, resource usage)

**Documentation:**
- Known failure modes and their workarounds
- Environment requirements and prerequisites
- Debugging steps for when this error recurs

### 6. PLAYBOOK
Generate a structured diagnosis and resolution playbook:

```
## Error: [Error Name/Pattern]

### Quick Diagnosis
1. Check [first thing to verify]
2. Run `[diagnostic command]`
3. Look for [specific indicator]

### Quick Fixes (try in order)
1. [Most likely fix] — works when [condition]
2. [Alternative fix] — works when [other condition]
3. [Fallback] — if above don't work

### Permanent Fix
- Root cause: [explanation]
- Fix: [what to change and why]
- Files: [list of files to modify]
- Tests: [what tests to add/update]

### Prevention
- [ ] Add test for [edge case]
- [ ] Add validation for [input]
- [ ] Add monitoring for [metric]
```

### 7. SAVE
Save all findings to memory for future reference:
```
remember_this(
    "Error analysis: [error pattern]. Root cause: [classification]. "
    "Occurred [N] times since [date]. Trend: [trend]. "
    "Fix: [recommended fix]. Prevention: [key prevention step]",
    "analyzing recurring error [error pattern]",
    "type:learning,priority:high,error_pattern:[pattern],area:[area]"
)
```
- Tag with the specific error pattern for future correlation
- Include the playbook summary so future sessions can find it quickly
- If a new banned strategy was discovered, ensure it's recorded in fix history
