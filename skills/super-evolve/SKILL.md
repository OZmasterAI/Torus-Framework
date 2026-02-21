---
skill: super-evolve
version: "1.0.0"
command: /super-evolve
type: meta
tier: critical
max_changes_per_invocation: 5
protected_gates: [1, 2, 3]
tags:
  - self-improvement
  - framework
  - meta
  - research
description: >
  Ultimate self-evolution skill. Merges evolve + self-improve into one comprehensive
  meta-skill with external research, area focus, dry-run mode, and expanded memory mining.
---

# /super-evolve — Ultimate Framework Self-Evolution

Merged from: `/evolve` + `/self-improve`

## When to use
When the user says "super-evolve", "super evolve", "full evolution", "deep improve",
or wants the most comprehensive version of autonomous framework improvement that combines
component scanning, deep memory mining, external research, and structured execution.

## Commands
- `/super-evolve` — Full evolution cycle (scan, research, execute, validate)
- `/super-evolve --quick` — Skip external research phase, memory-only analysis
- `/super-evolve --area <focus>` — Limit to a specific area (gates, memory, skills, docs, tests)
- `/super-evolve --dry-run` — Identify and rank improvements without implementing
- `/super-evolve --auto` — Skip user approval pause (use with caution)

## Hard Limits (read before executing anything)
- **Maximum 5 changes per invocation** — prevents scope creep and runaway edits
- **Gates 1, 2, and 3 are protected** — never modify without explicit user approval (Tier 1 safety)
- **enforcer.py, boot.py, memory_server.py** — never modify without querying search_knowledge first and getting explicit approval
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

Also read current state:
```
Read ~/.claude/LIVE_STATE.json       — current project, active PRPs, last test run
Read ~/.claude/ARCHITECTURE.md       — system architecture and design decisions
Read ~/.claude/CLAUDE.md             — behavioral rules, quality gates, conventions
```

Extract from LIVE_STATE.json:
- `framework_version` — current version number
- `what_was_done` — last session's work (avoid re-doing it)
- `test_results` — last known test pass rate

Build a component inventory table:

| Component | Type | Path | Description |
|-----------|------|------|-------------|
| gate_01   | Gate | hooks/gates/gate_01_read_before_edit.py | ... |
| ...       | ...  | ...  | ... |

---

## Phase 2: EVALUATE — Deep Multi-Source Analysis

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

### 2c. Deep memory mining (6 queries — expanded from evolve's 3)
Run all queries in parallel for speed:
- `search_knowledge("known issues bugs failures", top_k=30, mode="all")` — documented problems
- `search_knowledge("feature request improvement idea", top_k=30)` — queued improvements
- `search_knowledge("user correction preference decision", top_k=20)` — user corrections
- `search_knowledge("failed attempt strategy banned", top_k=20)` — failed approaches
- `search_knowledge("recurring pattern repeated warning", top_k=20)` — recurring issues
- `search_knowledge("performance latency bottleneck slow", top_k=20)` — performance issues

For each finding with relevance > 0.4, use `get_memory(id)` to retrieve full details.

**Fix history for recurring errors:**
```
query_fix_history("gate block")
query_fix_history("test failure")
query_fix_history("import error")
```

**Audit log analysis** — check recent logs for block patterns:
```bash
python3 -c "
import json, collections, pathlib, gzip
from datetime import date, timedelta

results = collections.Counter()
for delta in [0, 1]:
    d = (date.today() - timedelta(days=delta)).isoformat()
    for suffix in ['', '.gz']:
        p = pathlib.Path(f'~/.claude/hooks/audit/{d}.jsonl{suffix}').expanduser()
        if not p.exists():
            continue
        opener = gzip.open if suffix else open
        with opener(p, 'rt') as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    if entry.get('decision') == 'block':
                        results[entry.get('gate', 'unknown')] += 1
                except: pass

for gate, count in results.most_common():
    print(f'{count:4d}  {gate}')
"
```

### 2d. Skills audit
For each skill in `/home/crab/.claude/skills/`:
- Does it have a valid SKILL.md?
- Does it reference tools or scripts that still exist?
- Is it invokable (check for broken paths or commands)?

### 2e. External research (skip if --quick)
Search for recent developments relevant to findings from 2c:

**Core research queries (adapt based on findings):**
- `WebSearch("Claude Code agent SDK best practices 2025")`
- `WebSearch("Claude Code hooks quality gates patterns")`
- `WebSearch("agentic coding workflow improvements")`
- `WebSearch("LLM agent self-improvement framework patterns")`

**Targeted research** — if 2c revealed specific gaps, research those directly:
- Memory system issues -> search ChromaDB, vector DB best practices
- Gate false positives -> search hook/linter tuning patterns
- Test coverage gaps -> search testing strategies for AI agent frameworks
- Performance issues -> search profiling and optimization for Python hook systems

Fetch 1-2 most relevant pages with WebFetch for deeper context.
Save significant findings: `remember_this(finding, context, "type:learning,area:framework")`

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

## Phase 4: PRIORITIZE — Rank by Impact/Effort/Risk/Novelty

For each improvement candidate, assign scores using this weighted rubric:

| Dimension | Weight | Question |
|-----------|--------|----------|
| Impact | 40% | How much does this improve day-to-day workflow or reliability? |
| Effort | 30% | How many files/gates/tests need to change? (lower effort = higher score) |
| Risk | 20% | Could this break existing behavior? (lower risk = higher score) |
| Novelty | 10% | Is this new capability vs. fixing existing behavior? (new = bonus) |

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
Rank | Area      | Opportunity                        | Impact | Effort | Risk | Novelty | Score
-----|-----------|-------------------------------------|--------|--------|------|---------|------
  1  | gates     | Gate 6 triggering too aggressively  | 5      | 2      | Low  | No      |  9/10
  2  | skills    | Missing /rollback skill              | 4      | 2      | Low  | Yes     |  8/10
  3  | memory    | search_knowledge timeout handling   | 3      | 2      | Low  | No      |  6/10
```

**Pause here.** Ask the user: "Proceed with top 3 improvements? (Y/N) Or specify which ones."

If `--dry-run`: stop here and present the full ranked list.
If `--area <focus>`: filter the list to that area only.
If `--auto`: skip pause and proceed with top 3.

---

## Phase 5: EXECUTE — Implement Approved Improvements

For EACH approved improvement, run this full sub-loop:

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
- For gate changes: always update `hooks/test_framework.py` with matching tests
- For skill changes: the SKILL.md format must be preserved
- For CLAUDE.md changes: keep total token count under 2,000 (count with `wc -w`)

### 5f. Test after change
```bash
python3 /home/crab/.claude/hooks/test_framework.py 2>&1 | tail -10
```

Compare to baseline from 5a:
- Pass count must be >= baseline
- No new failures
- If tests regress: revert immediately, record failure, skip to next improvement

### 5g. Causal chain discipline (if any test fails)
```
1. query_fix_history("error text")
2. record_attempt("error text", "strategy-name")
3. Fix and re-run tests
4. record_outcome(chain_id, "success"|"failure")
5. remember_this(fix description, ...)
```

### 5h. Record to memory
```python
remember_this(
  "[Improvement N]: [what was changed and why]. Files: [list]. Tests: [before] -> [after].",
  "super-evolve skill execution",
  "type:feature,area:framework,outcome:success,evolve"
)
```

### 5i. Progress update
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
## [date] — /super-evolve run
- [improvement 1 summary]
- [improvement 2 summary]
- [improvement 3 summary]
```

### 6b. Update LIVE_STATE.json
Read the current state, then update:
- `last_evolve_run`: today's date (ISO 8601)
- `evolve_changes_applied`: increment by count of changes made this run
- `framework_version`: if a version field exists, increment the patch number

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
SUPER-EVOLUTION COMPLETE
========================
Scan:      N components inventoried
Research:  N external sources consulted (or "skipped — --quick mode")
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
- If the test suite was already failing before this skill started, document the pre-existing failures and do not count them as regressions
- Use `record_attempt` / `record_outcome` for causal chain tracking on any change that fails
- If Step 2 finds no signals (no blocks, no failures, no feature requests), report "framework is healthy" and stop — do not manufacture improvements
- Scope creep: if a discovered improvement is clearly larger than a session can handle, create a PRP for it instead

## Kill Rule
If 2 consecutive improvements cause test regressions that cannot be cleanly reverted:
- STOP the evolution run immediately
- Report what happened
- Save findings to memory: `remember_this("[what went wrong]", "super-evolve kill rule triggered", "type:error,area:framework,priority:high")`
- Do not attempt further changes — let the user decide next steps
