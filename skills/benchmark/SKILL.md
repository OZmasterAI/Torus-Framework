---
name: benchmark
description: Measure and track framework performance metrics over time. Collects test pass rates, memory counts, gate fire rates, hook latencies, and session metrics. Compares against previous baselines stored in memory to detect regressions or improvements. Saves results with type:benchmark tags for longitudinal tracking.
---

# /benchmark — Framework Performance Benchmarking

## When to use
When the user says "benchmark", "measure performance", "track metrics", "how fast are the gates",
"regression check", "baseline", or wants to quantify framework health over time.

## Commands
- `/benchmark` — Full benchmark run (measure + baseline + profile + analyze + report + save)
- `/benchmark --quick` — Skip profiling (measure + baseline + report only, faster)
- `/benchmark --profile-only` — Skip baseline comparison, run timing tests only
- `/benchmark --save-only` — Save current state as a new baseline without running profiling

---

## Steps

### 1. MEASURE — Collect current metrics

Gather the following metrics from live framework state:

**Test suite:**
```bash
python3 /home/crab/.claude/hooks/test_framework.py 2>&1 | tail -10
```
Extract: total tests, pass count, fail count, pass rate %.

**Memory system:**
```bash
cat /home/crab/.claude/stats-cache.json
```
Returns: `{"ts": <epoch>, "mem_count": <N>}`. Also note memory count from `search_knowledge("*", top_k=1)` result header (`total_memories` field).

**Framework state:**
```bash
python3 -c "
import json
with open('/home/crab/.claude/LIVE_STATE.json') as f:
    s = json.load(f)
print(json.dumps({
    'session_count': s.get('session_count'),
    'framework_version': s.get('framework_version'),
    'feature': s.get('feature'),
}, indent=2))
"
```

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
    print(json.dumps({
        'total_events': total,
        'passed': passed,
        'warned': warned,
        'blocked': blocked,
        'block_rate_pct': round(blocked/total*100, 1) if total else 0,
        'top_gates': dict(by_gate.most_common(5)),
    }, indent=2))
"
```

**Session metrics** (from LIVE_STATE `session_metrics` field if present):
Parse duration, tool call counts, error count, subagent count from the session_metrics string.

**Gate file count:**
```bash
ls /home/crab/.claude/hooks/gates/gate_*.py 2>/dev/null | wc -l
```

**Memory MCP status:**
```bash
pgrep -f memory_server.py > /dev/null && echo "RUNNING" || echo "DOWN"
```

**Ramdisk status:**
```bash
mountpoint -q /run/user/1000/claude-hooks && echo "MOUNTED" || echo "NOT MOUNTED"
```

**Framework metrics (via Analytics MCP):**
Call `mcp__analytics__all_metrics()` to get current counters, gauges, and histograms from gates, hooks, memory, and sessions.
Call `mcp__analytics__gate_dashboard()` to get gate effectiveness rankings, block rates, and coverage.
Include the gate rankings and top blocked gates in the step 5 report under GATE ACTIVITY.

Record all collected values in a structured dict for step 4 comparison.

---

### 2. BASELINE — Retrieve previous benchmark from memory

```python
search_knowledge("benchmark framework metrics baseline", top_k=10, mode="hybrid")
```

Look for results tagged `type:benchmark`. For each hit with relevance > 0.3:
```python
get_memory(id)  # retrieve full content
```

Extract the most recent prior benchmark's key figures:
- `prev_test_count`, `prev_pass_rate`, `prev_mem_count`, `prev_block_rate`, `prev_session_count`
- `prev_hook_latency_p50_us`, `prev_hook_latency_p99_us` (if available)
- `prev_date` — when it was recorded

If no prior benchmark exists in memory, note "First benchmark — no baseline available" and skip step 4 analysis.

---

### 3. PROFILE — Measure hook and memory latencies

Skip this step if `--quick` flag is used.

**Hook execution time (enforcer overhead per tool call):**
```bash
python3 -c "
import time, subprocess, statistics

N = 20
latencies = []
for _ in range(N):
    t0 = time.perf_counter_ns()
    subprocess.run(
        ['python3', '/home/crab/.claude/hooks/enforcer.py', '--event', 'PreToolUse'],
        input='{\"tool_name\": \"Bash\", \"tool_input\": {\"command\": \"echo hi\"}}',
        capture_output=True, text=True
    )
    t1 = time.perf_counter_ns()
    latencies.append((t1 - t0) / 1_000)  # microseconds

s = sorted(latencies)
print(f'Enforcer latency ({N} runs):')
print(f'  mean: {statistics.mean(latencies):.0f} us')
print(f'  p50:  {statistics.median(latencies):.0f} us')
print(f'  p95:  {s[int(N*0.95)]:.0f} us')
print(f'  p99:  {s[min(int(N*0.99), N-1)]:.0f} us')
"
```

**Memory query latency:**
```bash
python3 -c "
import time, subprocess, statistics

N = 5
latencies = []
for _ in range(N):
    t0 = time.perf_counter_ns()
    # Use the memory MCP search via CLI if available, or ChromaDB direct query
    import sys, os
    sys.path.insert(0, os.path.expanduser('~/.claude/hooks'))
    try:
        import chromadb
        client = chromadb.PersistentClient(path=os.path.expanduser('~/.claude/hooks'))
        coll = client.get_or_create_collection('knowledge', metadata={'hnsw:space': 'cosine'})
        coll.query(query_texts=['benchmark test query'], n_results=5)
        t1 = time.perf_counter_ns()
        latencies.append((t1 - t0) / 1_000_000)  # milliseconds
    except Exception as e:
        print(f'ChromaDB direct access skipped (MCP running): {e}')
        break

if latencies:
    print(f'Memory query latency ({N} runs):')
    print(f'  mean: {statistics.mean(latencies):.1f} ms')
    print(f'  p50:  {statistics.median(latencies):.1f} ms')
"
```

**Gate timing (via Analytics MCP):**
Call `mcp__analytics__gate_timing()` to get per-gate latency stats (p50, p95, p99) and identify slow gates.
Use this alongside (not instead of) the enforcer subprocess timing above — MCP data covers real session history while subprocess timing measures cold-start overhead.

**I/O benchmark** (if ramdisk is mounted):
```bash
python3 /home/crab/.claude/hooks/benchmarks/benchmark_io.py 2>&1 | grep -E "(Mean|p50|p95|p99|Speedup|Total|SUMMARY)" | head -20
```
Extract: tmpfs mean latency, disk mean latency, speedup factor.

---

### 4. ANALYZE — Identify regressions and improvements

Compare current metrics against baseline. For each metric, calculate delta and classify:

| Metric | Direction | Threshold for flag |
|---|---|---|
| Test pass rate | Higher = better | Flag if drops > 1% |
| Test count | Higher = better | Flag if drops (tests removed) |
| Memory count | Higher = better | Flag if drops > 10 (memories deleted) |
| Block rate | Context-dependent | Flag if jumps > 5% (gate storm) or drops to 0% (gates silent) |
| Hook latency p50 | Lower = better | Flag if rises > 20% |
| Hook latency p99 | Lower = better | Flag if rises > 50% (tail latency spike) |
| Session count | Increasing | Informational only |

Produce a classification for each metric:
- **IMPROVED** — metric moved in a positive direction beyond noise threshold
- **REGRESSION** — metric moved in a negative direction beyond threshold
- **STABLE** — within noise bounds
- **NEW** — no prior baseline to compare against

---

### 5. REPORT — Display structured results with trend indicators

Present the report in this format:

```
============================================================
  TORUS FRAMEWORK BENCHMARK REPORT
  Date: {today}   Session: #{session_count}
============================================================

  TEST SUITE
  ----------
  Total tests:   {test_count}   {IMPROVED/REGRESSION/STABLE/NEW} vs {prev_test_count} prev
  Pass rate:     {pass_rate}%  {trend_arrow}
  Failures:      {fail_count}

  MEMORY SYSTEM
  -------------
  Total memories: {mem_count}   {trend_arrow} vs {prev_mem_count} prev
  MCP status:     {RUNNING/DOWN}

  GATE ACTIVITY (today)
  ---------------------
  Total events:  {total_events}
  Passed:        {passed} ({pass_pct}%)
  Warned:        {warned} ({warn_pct}%)
  Blocked:       {blocked} ({block_rate}%)   {trend_arrow} vs {prev_block_rate}% prev
  Top gates:
    {gate_name}: {count} events
    ...

  HOOK PERFORMANCE
  ----------------
  Enforcer p50:  {p50} us   {trend_arrow} vs {prev_p50} us prev
  Enforcer p99:  {p99} us   {trend_arrow}
  Memory query:  {mem_latency} ms avg

  I/O PERFORMANCE
  ---------------
  tmpfs write:   {tmpfs_mean} us mean
  disk write:    {disk_mean} us mean
  Speedup:       {speedup}x

  REGRESSIONS
  -----------
  {list regressions, or "None detected"}

  IMPROVEMENTS
  ------------
  {list improvements, or "None detected"}

  FRAMEWORK STATE
  ---------------
  Version:       {framework_version}
  Gates active:  {gate_count}
  Feature:       {feature}
  Branch:        {branch from git}

============================================================
```

Trend arrows:
- `[+]` = improved since last benchmark
- `[-]` = regression since last benchmark
- `[=]` = stable
- `[?]` = no prior baseline

---

### 6. SAVE — Store results in memory

After displaying the report, always save:

```python
remember_this(
    content=(
        f"Benchmark {today} — Session #{session_count}: "
        f"tests={test_count} pass_rate={pass_rate}% "
        f"mem_count={mem_count} "
        f"block_rate={block_rate}% "
        f"enforcer_p50={enforcer_p50}us enforcer_p99={enforcer_p99}us "
        f"mem_query={mem_query_ms}ms "
        f"regressions=[{regression_list}] "
        f"improvements=[{improvement_list}]"
    ),
    context="/benchmark run on {today}",
    tags="type:benchmark,area:framework,area:testing,priority:medium"
)
```

Also save a separate entry if any regressions were found:
```python
if regressions:
    remember_this(
        content=f"REGRESSION detected on {today}: {regression_summary}. "
                f"Prior baseline from {prev_date}. "
                f"Investigate: {top_regression}",
        context="/benchmark regression alert",
        tags="type:benchmark,type:error,area:framework,priority:high,outcome:failed"
    )
```

---

## Rules
- ALWAYS query memory for prior benchmarks before running profiling — avoids redundant work
- NEVER block on ChromaDB direct access if MCP is running — use the skip path
- NEVER claim a regression is confirmed without showing the specific delta (numbers, not just "worse")
- If profiling reveals p99 > 2 seconds for the enforcer, escalate to the user immediately — that exceeds the 5s hook timeout budget
- Skip I/O benchmark if ramdisk is not mounted (log a warning, do not fail)
- `--quick` mode skips step 3 (profiling) entirely — still runs steps 1, 2, 4, 5, 6
- `--save-only` skips steps 3 and 4 — just saves current MEASURE data as a new baseline
- The saved memory entry is the source of truth for the next benchmark's baseline — make it parseable (use key=value format in content)
- If this is the first benchmark (no prior memory), mark all metrics as NEW and save a clean baseline
- After saving, confirm: "Benchmark saved. Next run will compare against today's baseline."
