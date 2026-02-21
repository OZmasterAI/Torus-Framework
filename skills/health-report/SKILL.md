# /health-report — Comprehensive Framework Health Report

## When to use
When user says "health report", "framework status", "full diagnostics", "comprehensive health",
or wants to understand the overall health of the Torus framework at a deep level.

## Commands
- `/health-report` — Generate full comprehensive health report
- `/health-report --brief` — Summary-only version (no detailed metrics)
- `/health-report --export` — Save report to disk as markdown + JSON

## Flow

### 1. GATHER DATA
- Run health_monitor's full_health_check(session_id="main")
- Read .gate_effectiveness.json for gate block/override/prevent statistics
- Check circuit_breaker.py for gate state summary
- Count and verify all 17 gates are present
- Query memory MCP for knowledge count
- Read LIVE_STATE.json for known_issues, test counts, service_status
- Read stats-cache.json for test results

### 2. ANALYZE
- Compute gate effectiveness score (blocks prevented vs total blocks)
- Calculate component health: gates, memory, state, ramdisk, audit
- Summarize test results: total, passed, failed, failure rate %
- Extract known issues and count by category
- Determine overall framework status: healthy, degraded, unhealthy

### 3. FORMAT REPORT
Generate markdown with sections:
```
## Torus Framework Health Report
### Executive Summary
### Component Status
  - Gates (17 total, status per gate)
  - Memory MCP (connected, knowledge count)
  - State Files (validation status)
  - Ramdisk (mounted, writable)
  - Circuit Breakers (state, trip count)
### Test Results
### Gate Effectiveness Metrics
### Known Issues & Status
### Recommendations
```

### 4. DISPLAY
Print formatted markdown report to stdout
Optionally save to file: `FRAMEWORK_HEALTH_REPORT_<timestamp>.md`

## What it checks
1. **Gates**: All 17 gates present, importable, callable check() function
2. **Memory MCP**: Process running, ChromaDB accessible, knowledge count
3. **State**: Valid JSON files, correct schema versions
4. **Ramdisk**: Mounted, writable
5. **Circuit Breakers**: All states (ok, degraded, tripped), trip counts
6. **Test Results**: Total, passed, failed, historical trend
7. **Gate Effectiveness**: Block counts, override counts, prevention counts
8. **Known Issues**: Active issues, categorized, status tracking

## Rules
- ALWAYS use health_monitor.full_health_check() for core checks
- ALWAYS read .gate_effectiveness.json for gate metrics
- ALWAYS include raw numbers, not just percentages
- Display both operational status (healthy/degraded/unhealthy) AND strategic insights
- Never modify files — report generation is read-only
- Format report for clarity: use headers, bullet points, status icons
