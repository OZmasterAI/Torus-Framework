# /self-improve — Framework Self-Improvement

---
name: self-improve
description: Meta-skill for systematically identifying, implementing, and verifying improvements to the Torus framework itself. Analyzes current state, searches memory for known issues and feature requests, researches external best practices, then plans and executes concrete improvements.
tools:
  - search_knowledge
  - remember_this
  - query_fix_history
  - record_attempt
  - record_outcome
  - WebSearch
  - WebFetch
  - Read
  - Glob
  - Grep
  - Edit
  - Write
  - Bash
---

## When to use
When user says "self-improve", "improve the framework", "make yourself better",
"what can we improve", "framework improvements", or wants to proactively evolve
the Torus framework's capabilities, gates, skills, or processes.

## Commands
- `/self-improve` — Full improvement cycle (recommended, takes 10-20 min)
- `/self-improve --quick` — Skip research phase, use memory only (~5 min)
- `/self-improve --area <focus>` — Limit to a specific area (gates, memory, skills, docs, tests)
- `/self-improve --dry-run` — Identify and rank improvements without implementing

## Steps

### 1. INTROSPECT — Read Current State

Load the framework's live context before forming any opinion about what to improve:

```
Read ~/.claude/LIVE_STATE.json       — current project, active PRPs, last test run
Read ~/.claude/ARCHITECTURE.md       — system architecture and design decisions
Read ~/.claude/CLAUDE.md             — behavioral rules, quality gates, conventions
```

Extract from LIVE_STATE.json:
- `framework_version` — current version number
- `what_was_done` — last session's work (avoid re-doing it)
- `test_results` — last known test pass rate
- `active_prp` — any in-flight feature work

If ARCHITECTURE.md doesn't exist at that path, try `~/.claude/docs/ARCHITECTURE.md`.

### 2. ANALYZE — Mine Memory and Logs for Signals

Run all queries in parallel for speed:

**Memory queries:**
```
search_knowledge("known issues bugs failures", top_k=30, mode="all")
search_knowledge("feature request improvement idea", top_k=30)
search_knowledge("gate block warning repeated", top_k=20)
search_knowledge("test failure flaky regression", top_k=20)
```

**Audit log analysis** — check today's and yesterday's logs for block patterns:
```bash
# Count gate blocks in today's audit log
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

**Fix history for recurring errors:**
```
query_fix_history("gate block")
query_fix_history("test failure")
query_fix_history("import error")
```

**Skill gap check** — identify triggers not covered by existing skills:
```bash
ls ~/.claude/skills/
```

### 3. RESEARCH — External Best Practices

Skip this step if `--quick` flag is given.

Search for recent developments relevant to what was found in Step 2:

**Core research queries (adapt based on findings):**
- `WebSearch("Claude Code agent SDK best practices 2025")`
- `WebSearch("Claude Code hooks quality gates patterns")`
- `WebSearch("agentic coding workflow improvements")`
- `WebSearch("LLM agent self-improvement framework patterns")`

**Targeted research** — if Step 2 revealed specific gaps, research those directly:
- Memory system issues → search ChromaDB, vector DB best practices
- Gate false positives → search hook/linter tuning patterns
- Test coverage gaps → search testing strategies for AI agent frameworks
- Performance issues → search profiling and optimization for Python hook systems

Fetch 1-2 most relevant pages with WebFetch for deeper context.
Save significant findings: `remember_this(finding, context, "type:learning,area:framework")`

### 4. IDENTIFY — Rank Improvement Opportunities

Synthesize Steps 1-3 into a concrete ranked list. Use this scoring rubric:

| Dimension | Weight | Question |
|-----------|--------|----------|
| Impact | 40% | How much does this improve day-to-day workflow or reliability? |
| Effort | 30% | How many files/gates/tests need to change? (lower = better) |
| Risk | 20% | Could this break existing behavior? (lower risk = higher score) |
| Novelty | 10% | Is this new capability vs. fixing existing behavior? |

**Output format** — present a ranked table before proceeding:

```
Rank | Area      | Opportunity                        | Impact | Effort | Risk | Score
-----|-----------|-------------------------------------|--------|--------|------|------
  1  | gates     | Gate 6 triggering too aggressively  | High   | Low    | Low  |  9/10
  2  | skills    | Missing /rollback skill              | Medium | Low    | Low  |  7/10
  3  | memory    | search_knowledge timeout handling   | Medium | Medium | Low  |  6/10
```

**Ask the user to confirm** which items to implement before proceeding.
If `--dry-run` flag is set, stop here and present the full ranked list.
If `--area <focus>` was given, filter the list to that area only.

### 5. IMPLEMENT — Build Each Improvement

For each approved improvement, follow The Loop in order:

#### Per-improvement protocol:
```
a. PLAN     — Describe the change in 2-3 sentences. What file(s)? What changes?
b. READ     — Read every file to be modified (Gate 1 compliance)
c. TEST     — Run existing tests to establish a baseline before touching anything:
              python3 ~/.claude/hooks/test_framework.py 2>&1 | tail -20
d. BUILD    — Make the minimal change needed. Prefer edits over rewrites.
e. VERIFY   — Run tests again. Compare pass counts. Show diff in results.
f. SAVE     — remember_this() with what was changed and why.
```

**Important constraints:**
- Only modify one logical concern per improvement (no bundling unrelated changes)
- For gate changes: always update `hooks/test_framework.py` with matching tests
- For skill changes: the SKILL.md format must be preserved (plain markdown, no code execution in SKILL.md itself)
- For CLAUDE.md changes: keep total token count under 2,000 (count with `wc -w`)
- For enforcer.py or gate files: extra care — query `search_knowledge("enforcer gate [name]")` first

**Causal chain discipline** — if a test fails during implementation:
```
1. query_fix_history("error text")
2. record_attempt("error text", "strategy-name")
3. Fix and re-run tests
4. record_outcome(chain_id, "success"|"failure")
5. remember_this(fix description, ...)
```

### 6. VERIFY — Full Regression Check

After all improvements are implemented, run the complete test suite:

```bash
python3 ~/.claude/hooks/test_framework.py 2>&1 | tee /tmp/self-improve-test-results.txt
tail -30 /tmp/self-improve-test-results.txt
```

Parse the output for:
- Total tests run vs. total tests passed
- Any new failures that did not exist before Step 5 started
- Any gate-specific failures

**Pass threshold:** 100% of previously-passing tests must still pass.
If any regression is found:
1. Identify which improvement caused it (bisect if needed)
2. Revert that specific change using Edit to restore the original content
3. Record the failed strategy: `record_outcome(chain_id, "failure")`
4. Re-run the full suite to confirm regression is cleared
5. Remove that improvement from the session's outcome report

### 7. REPORT — Summarize and Save

Generate a structured session report:

```
## Self-Improve Session — {date}

### Improvements Implemented ({N} total)
| # | Area   | Change                         | Tests Delta |
|---|--------|--------------------------------|-------------|
| 1 | gates  | Gate 6 threshold tuned         | +3 tests    |
| 2 | skills | Added /rollback skill          | +0 tests    |

### Improvements Deferred (not implemented)
| # | Reason              | Opportunity                     |
|---|---------------------|---------------------------------|
| 1 | Risk too high       | Rewrite audit log parser        |

### Test Results
Before: {N} passed / {M} total
After:  {N+delta} passed / {M+delta} total

### Key Learnings
- [Finding 1]
- [Finding 2]
```

Save the report to memory:
```
remember_this(
    "Self-improve session {date}: {N} improvements implemented in {areas}. "
    "Tests: {before} → {after}. Key changes: {summary}",
    "self-improve skill execution",
    "type:feature,priority:high,area:framework,self-improvement,outcome:success"
)
```

Update LIVE_STATE.json `what_was_done` field with a one-line summary of the session.

## Rules
- NEVER implement without user confirmation of the ranked list (Step 4)
- NEVER bundle more than one logical concern per improvement
- NEVER modify `enforcer.py`, `boot.py`, or `memory_server.py` without querying `search_knowledge` for those files first (Gate 7 compliance)
- ALWAYS run baseline tests before any change and final tests after all changes
- ALWAYS save each completed improvement to memory before moving to the next
- If the full test suite takes >60 seconds, run only the relevant gate's tests for intermediate checks, then run full suite at Step 6
- If Step 2 finds no signals (no blocks, no failures, no feature requests), report "framework is healthy" and stop — do not manufacture improvements
- Scope creep: if a discovered improvement is clearly larger than a session can handle, create a PRP for it instead (`/prp generate <description>`)
- The skill itself is a valid improvement target — if the skill's steps are unclear or produce poor results, improve this SKILL.md as one of the session's improvements
