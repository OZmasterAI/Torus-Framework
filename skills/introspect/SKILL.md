---
name: introspect
description: Deep framework self-analysis tool. Enumerates all components, collects health metrics, compares against prior introspect results stored in memory, identifies gaps and missing coverage, and produces a prioritized improvement roadmap. Read-only — never modifies files.
---

# /introspect — Framework Deep Self-Analysis

## When to use
When the user says "introspect", "self-analysis", "framework health check", "what needs improvement",
"audit the framework", "what's missing", "framework inventory", or wants a structured assessment
of the Torus framework's current state.

## Hard Limits (read before executing anything)
- **Read-only** — never modify any files during introspection
- Always search memory for previous introspect results before starting
- Always save results to memory after completing the report
- Show raw numbers in all tables (no rounding percentages to hide detail)
- If any scan step fails, record the failure and continue — partial data is better than none

---

## Phase 1: SCAN — Enumerate All Framework Components

Collect a complete inventory. Run ALL of the following:

**Gates:**
```bash
ls /home/crab/.claude/hooks/gates/gate_*.py 2>/dev/null | sort
ls /home/crab/.claude/hooks/gates/gate_*.py 2>/dev/null | wc -l
```
For each gate file, extract its gate number and name:
```bash
python3 -c "
import os, re
gate_dir = os.path.expanduser('~/.claude/hooks/gates')
gates = sorted(f for f in os.listdir(gate_dir) if f.startswith('gate_') and f.endswith('.py'))
for g in gates:
    path = os.path.join(gate_dir, g)
    with open(path) as f:
        content = f.read()
    # Extract gate name from GATE_NAME constant or first docstring
    name_match = re.search(r'GATE_NAME\s*=\s*[\"\'](.*?)[\"\']', content)
    num_match = re.search(r'gate_(\d+)', g)
    lines = content.count('\n')
    name = name_match.group(1) if name_match else '(unnamed)'
    num = num_match.group(1) if num_match else '?'
    print(f'  Gate {num:>2}: {g:<30} {lines:>4} lines  name={name}')
"
```

**Skills:**
```bash
ls /home/crab/.claude/skills/*/SKILL.md 2>/dev/null
ls /home/crab/.claude/skills/*/SKILL.md 2>/dev/null | wc -l
```
For each skill, extract name and description:
```bash
python3 -c "
import os, re
skills_dir = os.path.expanduser('~/.claude/skills')
for skill in sorted(os.listdir(skills_dir)):
    skill_path = os.path.join(skills_dir, skill, 'SKILL.md')
    if os.path.exists(skill_path):
        with open(skill_path) as f:
            content = f.read()
        desc_match = re.search(r'^description:\s*>?\s*\n\s+(.*)', content, re.MULTILINE)
        inline_match = re.search(r'^description:\s+(.+)$', content, re.MULTILINE)
        desc = (desc_match or inline_match)
        desc_text = desc.group(1)[:60] if desc else '(no description)'
        lines = content.count('\n')
        print(f'  {skill:<20} {lines:>4} lines  {desc_text}')
"
```

**Agents:**
```bash
ls /home/crab/.claude/agents/*.md 2>/dev/null | sort
ls /home/crab/.claude/agents/*.md 2>/dev/null | wc -l
```
For each agent, extract its name:
```bash
python3 -c "
import os
agents_dir = os.path.expanduser('~/.claude/agents')
if os.path.isdir(agents_dir):
    agents = sorted(f for f in os.listdir(agents_dir) if f.endswith('.md'))
    for a in agents:
        path = os.path.join(agents_dir, a)
        lines = open(path).read().count('\n')
        print(f'  {a:<35} {lines:>4} lines')
else:
    print('  (agents/ directory not found)')
"
```

**Hook entries (from settings.json):**
```bash
python3 -c "
import json
with open('/home/crab/.claude/settings.json') as f:
    d = json.load(f)
hooks = d.get('hooks', {})
total = 0
for event, entries in hooks.items():
    count = len(entries) if isinstance(entries, list) else 1
    total += count
    print(f'  {event:<30} {count} hook(s)')
print(f'  Total hook entries: {total}')
"
```

**Shared modules:**
```bash
ls /home/crab/.claude/hooks/shared/*.py 2>/dev/null | sort
```
For each shared module, count lines and list exported functions:
```bash
python3 -c "
import os, ast
shared_dir = os.path.expanduser('~/.claude/hooks/shared')
if os.path.isdir(shared_dir):
    for mod in sorted(os.listdir(shared_dir)):
        if not mod.endswith('.py'):
            continue
        path = os.path.join(shared_dir, mod)
        with open(path) as f:
            content = f.read()
        lines = content.count('\n')
        try:
            tree = ast.parse(content)
            funcs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and not n.name.startswith('_')]
        except:
            funcs = []
        print(f'  {mod:<30} {lines:>4} lines  exports={len(funcs)} fns: {funcs[:5]}')
"
```

**Additional framework files:**
```bash
python3 -c "
import os
files = {
    'enforcer.py': '~/.claude/hooks/enforcer.py',
    'boot.py': '~/.claude/hooks/boot.py',
    'test_framework.py': '~/.claude/hooks/test_framework.py',
    'state.py': '~/.claude/hooks/shared/state.py',
    'CLAUDE.md': '~/.claude/CLAUDE.md',
    'ARCHITECTURE.md': '~/.claude/ARCHITECTURE.md',
    'settings.json': '~/.claude/settings.json',
}
for name, path in files.items():
    full = os.path.expanduser(path)
    if os.path.exists(full):
        lines = open(full).read().count('\n')
        size = os.path.getsize(full)
        print(f'  {name:<30} {lines:>4} lines  {size:>6} bytes')
    else:
        print(f'  {name:<30} NOT FOUND')
"
```

Record all counts: `gate_count`, `skill_count`, `agent_count`, `hook_entry_count`, `shared_module_count`.

---

## Phase 2: MEASURE — Collect Health Metrics

**Test suite:**
```bash
python3 /home/crab/.claude/hooks/test_framework.py 2>&1 | tail -20
```
Extract: `total_tests`, `passed`, `failed`, `pass_rate_pct`.

**Per-gate test coverage:**
```bash
python3 -c "
import re, os
test_path = os.path.expanduser('~/.claude/hooks/test_framework.py')
content = open(test_path).read()
# Find which gate numbers appear in the test file
gate_refs = set(re.findall(r'gate_(\d+)', content))
gate_test_fns = re.findall(r'def (test_gate_\w+|test.*gate.*\w+)', content, re.IGNORECASE)
print('Gate numbers referenced in tests:', sorted(gate_refs))
print('Test functions:', gate_test_fns[:20])
"
```
List which gate numbers have NO test functions — these are untested gates.

**Memory system:**
```bash
cat /home/crab/.claude/stats-cache.json 2>/dev/null || echo '{}'
```
Extract `mem_count`. Also run `search_knowledge("introspect framework analysis", top_k=1)` for the total_memories field.

**Gate fire rates from today's audit log:**
```bash
python3 -c "
import json, os, collections
from datetime import date
log = os.path.expanduser(f'~/.claude/hooks/audit/{date.today()}.jsonl')
if not os.path.exists(log):
    print('No audit log for today')
else:
    entries = [json.loads(l) for l in open(log) if l.strip()]
    total = len(entries)
    by_gate = collections.Counter(e.get('gate','?') for e in entries)
    blocked = sum(1 for e in entries if e.get('decision') == 'block')
    warned = sum(1 for e in entries if e.get('decision') == 'warn')
    passed = sum(1 for e in entries if e.get('decision') == 'pass')
    # Gates that never fired today
    gate_dir = os.path.expanduser('~/.claude/hooks/gates')
    all_gates = set(re.search(r'gate_(\d+)', f).group(1) for f in os.listdir(gate_dir) if f.startswith('gate_') and f.endswith('.py'))
    import re
    silent_gates = all_gates - set(str(k) for k in by_gate.keys() if str(k).isdigit())
    print(json.dumps({
        'total_events': total,
        'passed': passed,
        'warned': warned,
        'blocked': blocked,
        'block_rate_pct': round(blocked/total*100, 2) if total else 0,
        'top_5_gates': dict(by_gate.most_common(5)),
        'silent_today': sorted(silent_gates),
    }, indent=2))
" 2>&1
```

**LIVE_STATE snapshot:**
```bash
python3 -c "
import json
with open('/home/crab/.claude/LIVE_STATE.json') as f:
    s = json.load(f)
print(json.dumps({k: s.get(k) for k in ['session_count','framework_version','feature']}, indent=2))
"
```

**Git branch and recent commits:**
```bash
git -C /home/crab/.claude log --oneline -5
git -C /home/crab/.claude branch --show-current
```

---

## Phase 3: COMPARE — Retrieve Previous Introspect Results

Search memory for prior runs:
```python
search_knowledge("introspect framework self-analysis health check", top_k=10, mode="hybrid")
```

For hits with relevance > 0.3 and tags containing `introspect`:
```python
get_memory(id)
```

Extract from the most recent prior introspect:
- `prev_gate_count`, `prev_skill_count`, `prev_agent_count`
- `prev_test_count`, `prev_pass_rate`
- `prev_mem_count`
- `prev_gap_count` — number of gaps identified
- `prev_date` — when it was run

**Calculate deltas:**

| Metric | Previous | Current | Delta | Direction |
|---|---|---|---|---|
| Gates | prev | curr | curr-prev | + = more coverage |
| Skills | prev | curr | curr-prev | + = more capability |
| Agents | prev | curr | curr-prev | + = more roles |
| Tests | prev | curr | curr-prev | + = better coverage |
| Pass rate | prev% | curr% | delta% | + = more stable |
| Memories | prev | curr | curr-prev | + = more context |
| Gaps found | prev | curr | curr-prev | - = fewer gaps is better |

If no prior introspect: note "First introspect run — no prior baseline" and mark all as `[NEW]`.

---

## Phase 4: GAPS — Identify Missing Coverage

**4a. Untested gates:**
Cross-reference gates found in Phase 1 vs gate numbers covered in `test_framework.py`.
List each gate that has zero test functions referencing it.

**4b. Skills without associated tests:**
```bash
python3 -c "
import os, re
skills_dir = os.path.expanduser('~/.claude/skills')
test_path = os.path.expanduser('~/.claude/hooks/test_framework.py')
test_content = open(test_path).read()
for skill in sorted(os.listdir(skills_dir)):
    if os.path.exists(os.path.join(skills_dir, skill, 'SKILL.md')):
        if skill not in test_content:
            print(f'  SKILL NOT IN TESTS: {skill}')
        else:
            print(f'  skill covered: {skill}')
"
```

**4c. Agents without matching skills:**
```bash
python3 -c "
import os, re
agents_dir = os.path.expanduser('~/.claude/agents')
skills_dir = os.path.expanduser('~/.claude/skills')
if not os.path.isdir(agents_dir):
    print('(no agents dir)')
else:
    skill_names = set(os.listdir(skills_dir)) if os.path.isdir(skills_dir) else set()
    for agent_file in sorted(os.listdir(agents_dir)):
        if not agent_file.endswith('.md'):
            continue
        agent_name = agent_file.replace('.md', '')
        matched = [s for s in skill_names if agent_name in s or s in agent_name]
        if not matched:
            print(f'  AGENT WITHOUT SKILL: {agent_name}')
        else:
            print(f'  agent matched: {agent_name} -> {matched}')
"
```

**4d. Orphaned/unreferenced files:**
```bash
python3 -c "
import os, json
# Check if any gate files are not referenced in settings.json enforcer config
settings = json.load(open(os.path.expanduser('~/.claude/settings.json')))
hooks_str = json.dumps(settings.get('hooks', {}))
gate_dir = os.path.expanduser('~/.claude/hooks/gates')
for f in sorted(os.listdir(gate_dir)):
    if f.startswith('gate_') and f.endswith('.py'):
        # Gates are loaded dynamically by enforcer, not listed in settings.json hooks
        pass

# Check for .py files in hooks/ that are not imported anywhere
hooks_dir = os.path.expanduser('~/.claude/hooks')
all_py = [f for f in os.listdir(hooks_dir) if f.endswith('.py')]
enforcer = open(os.path.join(hooks_dir, 'enforcer.py')).read()
for f in sorted(all_py):
    module = f.replace('.py','')
    if module not in enforcer and f not in ['enforcer.py','boot.py','test_framework.py']:
        print(f'  POSSIBLY ORPHANED: {f} (not imported in enforcer.py)')
    else:
        print(f'  referenced: {f}')
" 2>&1 | head -30
```

**4e. Missing documentation:**
```bash
python3 -c "
import os
# Check which gates lack docstrings
gate_dir = os.path.expanduser('~/.claude/hooks/gates')
import ast
for f in sorted(os.listdir(gate_dir)):
    if f.startswith('gate_') and f.endswith('.py'):
        path = os.path.join(gate_dir, f)
        content = open(path).read()
        try:
            tree = ast.parse(content)
            has_module_doc = (ast.get_docstring(tree) is not None)
            check_fn = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'check'), None)
            has_check_doc = check_fn and ast.get_docstring(check_fn) is not None
            if not has_module_doc or not has_check_doc:
                print(f'  MISSING DOCS: {f}  module_doc={has_module_doc} check_doc={has_check_doc}')
        except:
            print(f'  PARSE ERROR: {f}')
"
```

Summarize gap count: `total_gaps = untested_gates + skills_without_tests + agents_without_skills + orphaned_files + undocumented_gates`.

---

## Phase 5: RECOMMEND — Prioritized Improvement Roadmap

Based on findings from Phases 1-4, produce a prioritized table:

```
  IMPROVEMENT ROADMAP
  ===================

  Priority | Item                              | Effort  | Rationale
  ---------|-----------------------------------|---------|-----------------------------
  HIGH     | Add tests for gate N (untested)   | small   | No coverage = invisible bugs
  HIGH     | Document check() in gate N        | small   | Violates gate contract rules
  MEDIUM   | Create skill for agent X          | medium  | Agent has no /command entry point
  MEDIUM   | Add test for skill Y              | small   | Skill behavior unverifiable
  LOW      | Archive orphaned file Z           | small   | Dead code accumulates risk
  LOW      | Expand gate N to cover edge case  | medium  | Gap identified in audit logs
```

Effort scale:
- **small** — < 30 min, single file, < 50 lines
- **medium** — 30-120 min, 2-3 files, existing patterns to follow
- **large** — > 2 hours, architecture decision, cross-cutting concern

Sort by: HIGH priority first, then by effort (small → medium → large within priority).

---

## Output Format

Present the full introspect report:

```
============================================================
  TORUS FRAMEWORK INTROSPECT REPORT
  Date: {today}   Branch: {branch}   Session: #{session_count}
============================================================

  COMPONENT INVENTORY
  -------------------
  Gates (gate_*.py):       {gate_count}   {trend vs prev}
  Skills (*/SKILL.md):     {skill_count}  {trend vs prev}
  Agents (agents/*.md):    {agent_count}  {trend vs prev}
  Hook entries (settings): {hook_entry_count}
  Shared modules:          {shared_module_count}

  Gate list:
    {gate_num}: {gate_name}  ({lines} lines)
    ...

  Skill list:
    {skill_name}: {description[:50]}
    ...

  Agent list:
    {agent_name}.md  ({lines} lines)
    ...

  HEALTH METRICS
  --------------
  Tests total:    {total_tests}   {trend}
  Tests passing:  {passed} / {total_tests}  ({pass_rate}%)  {trend}
  Tests failing:  {failed}
  Memory count:   {mem_count}   {trend}
  Gate events today: {total_events}  ({blocked} blocked, {blocked_pct}% block rate)
  Silent gates today: {silent_today}

  DELTA vs PREVIOUS INTROSPECT ({prev_date or "N/A"})
  ---------------------------------------------------
  Gates:      {prev_gate_count} → {gate_count}   ({delta:+d})
  Skills:     {prev_skill_count} → {skill_count}  ({delta:+d})
  Agents:     {prev_agent_count} → {agent_count}  ({delta:+d})
  Tests:      {prev_test_count} → {total_tests}   ({delta:+d})
  Pass rate:  {prev_pass_rate}% → {pass_rate}%    ({delta:+.1f}%)
  Memories:   {prev_mem_count} → {mem_count}      ({delta:+d})
  Gaps found: {prev_gap_count} → {total_gaps}     ({delta:+d})

  GAPS IDENTIFIED
  ---------------
  Untested gates:           {list or "None"}
  Skills without tests:     {list or "None"}
  Agents without skills:    {list or "None"}
  Possibly orphaned files:  {list or "None"}
  Undocumented gates:       {list or "None"}
  Total gaps: {total_gaps}

  IMPROVEMENT ROADMAP
  -------------------
  {Priority table from Phase 5}

============================================================
```

Trend indicators:
- `[+N]` = grew by N since last introspect
- `[-N]` = shrank by N since last introspect
- `[=]` = unchanged
- `[NEW]` = first introspect, no prior baseline

---

## Phase 6: SAVE — Store Results in Memory

After displaying the report, always save:

```python
remember_this(
    content=(
        f"Introspect {today} — Branch={branch} Session=#{session_count}: "
        f"gate_count={gate_count} skill_count={skill_count} agent_count={agent_count} "
        f"shared_modules={shared_module_count} hook_entries={hook_entry_count} "
        f"test_count={total_tests} pass_rate={pass_rate}% "
        f"mem_count={mem_count} "
        f"total_gaps={total_gaps} "
        f"untested_gates={untested_gate_list} "
        f"silent_gates={silent_today} "
        f"top_recommendations={top_3_recommendations}"
    ),
    context=f"/introspect run on {today}",
    tags="type:benchmark,area:framework,introspect,priority:medium"
)
```

If gaps were found that are HIGH priority:
```python
remember_this(
    content=f"HIGH-priority gaps found on {today}: {high_priority_items}. "
            f"Recommend addressing before next evolve run.",
    context="/introspect gap alert",
    tags="type:benchmark,area:framework,introspect,priority:high"
)
```

After saving, confirm: "Introspect complete. {total_gaps} gaps found. Results saved — next run will compare against today's baseline."

---

## Rules
- **Read-only** — never write or modify any file during introspection
- Always call `search_knowledge("introspect framework self-analysis", top_k=10)` BEFORE scanning — prior results inform comparison
- Show raw numbers everywhere — no hiding detail behind summaries
- If a scan step fails (missing dir, parse error), record it as a gap and continue
- A gate with zero test references is always HIGH priority regardless of other factors
- Silent gates (never fired today) are noted but not automatically flagged — they may be correct-path gates
- The saved memory entry must be parseable (key=value format) so the next introspect can extract deltas
- Never claim "no gaps" without explicitly checking all five gap categories (4a–4e)
