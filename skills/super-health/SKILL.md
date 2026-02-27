# /super-health — Comprehensive Framework Health Diagnostic

Merged from: `/health` + `/health-report` + `/status`

## When to use
When the user says "super-health", "super health", "full health", "deep diagnostics",
"comprehensive status", or wants the most thorough health check combining quick diagnostics,
deep metrics, and operational overview in one skill.

## Commands
- `/super-health` — Full comprehensive diagnostic (all checks + deep metrics)
- `/super-health --quick` — Quick dashboard only (like /status — fast, pre-formatted)
- `/super-health --repair` — Run diagnostic and auto-fix common issues
- `/super-health --brief` — Summary-only version (no detailed metrics)
- `/super-health --export` — Save report to disk as markdown + JSON

## Flow

### 1. QUICK DASHBOARD (always runs first)
Run the quick status gather:
```bash
python3 ~/.claude/skills/status/scripts/gather.py
```
Display the pre-formatted dashboard output to the user immediately.
If `--quick` flag is set, stop here.

### 2. DEEP DIAGNOSTICS
Run the health check script:
```bash
python3 ~/.claude/skills/super-health/scripts/check.py
```
If `--repair` flag is given:
```bash
python3 ~/.claude/skills/super-health/scripts/check.py --repair
```

This checks:
1. **Memory MCP**: process running (pgrep) + ChromaDB accessible
2. **Gates**: all gate files present + importable
3. **State**: valid JSON, correct schema version
4. **Ramdisk**: mounted, writable
5. **File claims**: stale claims (>2 hours old)
6. **Audit logs**: today's log exists, not oversized (>5MB)
7. **Deferred items**: count from Gate 9 deferrals
8. **PRPs**: any active PRPs with stuck tasks

### 3. COMPREHENSIVE METRICS
Gather deep metrics for the full report:

- Read `.gate_effectiveness.json` for gate block/override/prevent statistics
- Check circuit_breaker state summary (ok/degraded/tripped + trip counts)
- Count and verify all gates are present and importable
- Query memory MCP for knowledge count
- Read `LIVE_STATE.json` for known_issues, test counts, framework_version
- Read `stats-cache.json` for test results
- Check git branch + recent commits:
  ```bash
  git -C ~/.claude log --oneline -5
  git -C ~/.claude branch --show-current
  ```

### 4. ANALYZE
- Compute gate effectiveness score (blocks prevented vs total blocks)
- Calculate component health: gates, memory, state, ramdisk, audit
- Summarize test results: total, passed, failed, failure rate %
- Extract known issues and count by category
- Determine overall framework status: **healthy**, **degraded**, or **unhealthy**

### 5. FORMAT REPORT
Generate markdown with sections:
```
## Torus Framework Health Report

### Quick Dashboard
[pre-formatted status from Step 1]

### Executive Summary
Overall status: HEALTHY | DEGRADED | UNHEALTHY
Framework version: vX.Y.Z
Branch: [current branch]
Recent commits: [last 5]

### Component Status
  - Gates (N total, status per gate)
  - Memory MCP (connected, knowledge count)
  - State Files (validation status)
  - Ramdisk (mounted, writable)
  - Circuit Breakers (state, trip count)
  - File Claims (stale count)
  - Audit Logs (size, today's entry)
  - Gate 9 Deferrals (count)
  - Active PRPs (stuck tasks)

### Test Results
Total: N | Passed: N | Failed: N | Rate: N%
Historical trend: [if available]

### Gate Effectiveness Metrics
| Gate | Blocks | Overrides | Prevents | Effectiveness |
|------|--------|-----------|----------|---------------|

### Known Issues & Status
| Issue | Category | Status |
|-------|----------|--------|

### Recommendations
- [Prioritized list of suggested fixes]
```

### 6. DISPLAY & SAVE
- Print formatted markdown report to stdout
- If `--brief`: show only Executive Summary + Component Status
- If `--export`: save to `FRAMEWORK_HEALTH_REPORT_<timestamp>.md`

## Rules
- ALWAYS run check.py for core diagnostics — don't manually inspect state files
- ALWAYS read .gate_effectiveness.json for gate metrics
- ALWAYS include raw numbers, not just percentages
- Display both operational status AND strategic insights
- Never modify files — report generation is read-only (except --repair mode)
- For --repair, only perform safe operations (delete stale claims, reset corrupt state)
- NEVER modify gate files, enforcer.py, or settings.json
- Format report for clarity: use headers, bullet points, status icons
