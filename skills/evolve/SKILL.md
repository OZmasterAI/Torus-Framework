---
skill: evolve
version: "1.0.0"
command: /evolve
type: meta
tier: critical
max_changes_per_invocation: 5
protected_gates: [1, 2, 3]
tags:
  - self-improvement
  - framework
  - meta
description: >
  Autonomous self-evolution skill. Analyzes and upgrades the Torus framework
  by scanning all components, evaluating health, diagnosing gaps, prioritizing
  improvements, executing changes, and validating results. This is the meta-skill
  that improves the framework that improves itself.
---

# /evolve — Autonomous Framework Self-Evolution

## When to use
When the user says "evolve", "self-improve", "upgrade the framework", "framework evolution",
"what needs improving", or wants the framework to autonomously identify and execute its own
highest-value improvements.

## Hard Limits (read before executing anything)
- **Maximum 5 changes per invocation** — prevents scope creep and runaway edits
- **Gates 1, 2, and 3 are protected** — never modify without explicit user approval (Tier 1 safety)
- Always run the full test suite BEFORE and AFTER each change
- Every change must be saved to memory with `type:feature,area:framework` tags
- If any gate test fails post-change, revert and report — do not continue

---

## Phase 1: SCAN — Inventory Every Framework Component

Collect the full component map. Run ALL of these:

```bash
# Gates
ls /home/crab/.claude/hooks/gates/

# Hook scripts (registered in settings.json)
python3 -c "import json; d=json.load(open('/home/crab/.claude/settings.json')); [print(h) for h in d.get('hooks', {})]"

# Skills
ls /home/crab/.claude/skills/

# MCP tools (registered servers)
python3 -c "import json; d=json.load(open('/home/crab/.claude/settings.json')); [print(s) for s in d.get('mcpServers', {}).keys()]"

# Scripts
ls /home/crab/.claude/scripts/ 2>/dev/null || echo "(no scripts dir)"

# Plugins
ls /home/crab/.claude/plugins/ 2>/dev/null || echo "(no plugins dir)"
```

Build a component inventory table:

| Component | Type | Path | Description |
|-----------|------|------|-------------|
| gate_01   | Gate | hooks/gates/gate_01_read_before_edit.py | ... |
| ...       | ...  | ...  | ... |

---

## Phase 2: EVALUATE — Assess Each Component

For each component in the inventory:

### 2a. Age check
```bash
# Last modified date for all gate files
stat -c "%n %y" /home/crab/.claude/hooks/gates/gate_*.py | sort -k2
```

### 2b. Test coverage check
```bash
# Count test cases per gate in test_framework.py
grep -c "gate_0[0-9]" /home/crab/.claude/hooks/test_framework.py 2>/dev/null || \
grep -c "gate_1[0-9]" /home/crab/.claude/hooks/test_framework.py 2>/dev/null || \
echo "test_framework.py not found or no gate tests"
```

### 2c. Memory query for known issues
- `search_knowledge("gate issues bugs warnings failures")` — find documented problems
- `search_knowledge("missing capability gap needed")` — find feature requests and gaps
- `search_knowledge("framework improvement upgrade enhancement")` — find queued improvements

For each finding with relevance > 0.4, use `get_memory(id)` to retrieve full details.

### 2d. Skills audit
For each skill in `/home/crab/.claude/skills/`:
- Does it have a valid SKILL.md?
- Does it reference tools or scripts that still exist?
- Is it invokable (check for broken paths or commands)?

Record findings in a structured evaluation table:

| Component | Age (days) | Test Count | Known Issues | Status |
|-----------|-----------|------------|--------------|--------|
| gate_01   | 30         | 12         | none         | HEALTHY |
| ...       | ...        | ...        | ...          | ...    |

---

## Phase 3: DIAGNOSE — Find Problems

Classify findings into three buckets:

### Stale Components
Components not modified in >30 days AND have open known issues. List them.

### Under-tested Gates
Gates with fewer than 5 test cases in test_framework.py. List them by name and current count.

### Missing Capabilities
Cross-reference the current component inventory against industry-standard agent framework capabilities:
- Rate limiting / backoff
- Structured logging with rotation
- Health check endpoints
- Self-healing (auto-restart on failure)
- Circuit breakers
- Observability (metrics, traces)
- Plugin hot-reload
- Graceful degradation fallbacks

Note which capabilities are absent or partially implemented.

Report findings:
```
DIAGNOSE REPORT
===============
Stale components (N): [list]
Under-tested gates (N): [list with counts]
Missing capabilities (N): [list]
Open memory issues (N): [list with memory IDs]
```

---

## Phase 4: PRIORITIZE — Rank by Effort-to-Impact Ratio

For each improvement candidate, assign:
- **Impact score** (1-5): How much does this improve reliability, safety, or capability?
- **Effort score** (1-5): How many files touched, test changes required, risk level?
- **Priority score** = Impact / Effort (higher = do first)

Scoring guidance:
- Impact 5: Fixes a safety hole or critical failure mode
- Impact 4: Adds a genuinely missing capability or fixes a Tier 1 gate issue
- Impact 3: Improves observability, test coverage, or developer experience
- Impact 2: Minor refinement, cleanup, or documentation
- Impact 1: Cosmetic
- Effort 1: Single file, < 20 lines, no test changes needed
- Effort 5: Multiple files, schema changes, requires test framework updates

Present the ranked list to the user:
```
PRIORITY RANKING
================
Rank 1: [improvement] — Impact:5 Effort:2 Score:2.5
Rank 2: [improvement] — Impact:4 Effort:2 Score:2.0
Rank 3: [improvement] — Impact:3 Effort:2 Score:1.5
...
```

**Pause here.** Ask the user: "Proceed with top 3 improvements? (Y/N) Or specify which ones."

Do NOT continue without explicit user confirmation or the `/evolve --auto` flag.

---

## Phase 5: EXECUTE — Implement Top 3 Improvements

For EACH of the top 3 approved improvements, run this full sub-loop:

### 5a. Pre-change baseline
```bash
python3 /home/crab/.claude/hooks/test_framework.py 2>&1 | tail -5
```
Record: `N tests passed, M failed` as the baseline.

### 5b. Memory check for this specific change
- `search_knowledge("[improvement description]")`
- `query_fix_history("[relevant error or area]")`
- If a prior attempt failed, use `get_memory(id)` to understand why before proceeding

### 5c. Plan the change
Document before touching any file:
- File(s) to modify
- Exact change to make
- How to verify it worked
- Rollback approach if tests fail

### 5d. Gate protection check
- If the change involves `gate_01`, `gate_02`, or `gate_03`: STOP.
  Present the change to the user and require explicit "yes, modify Tier 1 gate" approval.
- If the change involves `enforcer.py`: STOP. Require explicit approval.
- If the change involves `memory_server.py`: STOP. Require explicit approval.

### 5e. Implement
- Read each file before editing (Gate 1 compliance)
- Make the smallest change that achieves the goal
- Do not bundle unrelated changes

### 5f. Test after change
```bash
python3 /home/crab/.claude/hooks/test_framework.py 2>&1 | tail -10
```

Compare to baseline from 5a:
- Pass count must be >= baseline
- No new failures
- If tests regress: revert immediately, record failure, skip to next improvement

### 5g. Record to memory
```python
remember_this(
  "[Improvement N]: [what was changed and why]. Files: [list]. Tests: [before] -> [after].",
  "evolve skill execution",
  "type:feature,area:framework,outcome:success,evolve"
)
```

### 5h. Progress update
After each improvement, report:
```
Improvement N/3: COMPLETE
  Change: [description]
  Files:  [list]
  Tests:  [before] -> [after]
  Status: VERIFIED
```

---

## Phase 6: UPGRADE — Update Framework Metadata

After all improvements are executed and verified:

### 6a. Update ARCHITECTURE.md (if it exists)
```bash
ls /home/crab/.claude/ARCHITECTURE.md 2>/dev/null
```
If present, append a dated entry to the changelog section:
```markdown
## [date] — /evolve run
- [improvement 1 summary]
- [improvement 2 summary]
- [improvement 3 summary]
```

### 6b. Update LIVE_STATE.json
Read the current state, then update:
- `last_evolve_run`: today's date (ISO 8601)
- `evolve_changes_applied`: increment by count of changes made this run
- `framework_version`: if a version field exists, increment the patch number

```bash
python3 -c "
import json, datetime
state = json.load(open('/home/crab/.claude/LIVE_STATE.json'))
state['last_evolve_run'] = datetime.date.today().isoformat()
state['evolve_changes_applied'] = state.get('evolve_changes_applied', 0) + N
json.dump(state, open('/home/crab/.claude/LIVE_STATE.json', 'w'), indent=2)
print('LIVE_STATE.json updated')
"
```

---

## Phase 7: VALIDATE — Full Suite Verification

Run the complete test suite one final time:
```bash
python3 /home/crab/.claude/hooks/test_framework.py 2>&1
```

Report the final gate-by-gate status:
```
FINAL VALIDATION
================
Tests: N passed, M failed (baseline was B passed)
Net change: +X tests passing

Gate status:
  Gate 01 (Read Before Edit)    PASS
  Gate 02 (No Destroy)          PASS
  Gate 03 (Test Before Deploy)  PASS
  ...
```

If any gate fails:
1. Identify which improvement caused the regression (bisect by reverting one at a time)
2. Revert that specific change
3. Re-run the full suite
4. Report the reverted change to the user with an explanation

Only declare success when all gates pass.

---

## Evolution Session Summary

After completing all 7 phases, present:

```
EVOLUTION COMPLETE
==================
Scan:      N components inventoried
Diagnose:  N problems found
Execute:   N/3 improvements applied (N reverted due to test failure)
Validate:  N tests passing (was M before)

Changes applied:
  1. [description] — [files changed]
  2. [description] — [files changed]
  3. [description] — [files changed]

Memory saved: N entries with type:feature,area:framework tags
LIVE_STATE.json: updated
```

Suggest next steps:
- If there are remaining improvements from the priority list, name them: "Next run could tackle: [list]"
- If the framework looks fully healthy, say so

---

## Rules
- This skill is the **meta-skill** — it improves the framework that improves itself. Extra caution applies.
- ALWAYS run tests before AND after each individual change (not just at the end)
- NEVER modify Gate 1, 2, or 3 without explicit user approval (Tier 1 safety gates)
- NEVER modify `enforcer.py`, `memory_server.py`, or `settings.json` without explicit approval
- Maximum 5 changes per invocation — quality over quantity
- Save every verified change to memory with `type:feature,area:framework,evolve` tags
- If the test suite was already failing before `/evolve` started, document the pre-existing failures and do not count them as regressions caused by evolution changes
- Use `record_attempt` / `record_outcome` for causal chain tracking on any change that fails

## Kill Rule
If 2 consecutive improvements cause test regressions that cannot be cleanly reverted:
- STOP the evolution run immediately
- Report what happened
- Save findings to memory: `remember_this("[what went wrong]", "evolve kill rule triggered", "type:error,area:framework,priority:high")`
- Do not attempt further changes — let the user decide next steps
