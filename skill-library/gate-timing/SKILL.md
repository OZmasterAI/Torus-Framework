# /gate-timing — Gate Execution Latency Analysis

Analyze per-gate execution timing to identify slow gates and latency patterns.

## Steps

1. Read gate timing data from `~/.claude/hooks/.gate_timing.json`
2. For each gate, compute:
   - Average execution time (ms)
   - P95 execution time (ms)
   - Call count
   - Trend (getting slower/faster/stable)
3. Identify slow gates (avg > 50ms or p95 > 200ms)
4. Optionally filter by specific gate name

## Output
```
Gate Timing Report:
  gate-01 (read-before-edit): avg=12ms, p95=28ms, calls=145 — FAST
  gate-17 (injection-defense): avg=67ms, p95=180ms, calls=89 — SLOW
  gate-14 (confidence-check): avg=8ms, p95=15ms, calls=200 — FAST

Slow gates (>50ms avg):
  gate-17: 67ms avg — consider optimizing pattern matching

Overall: 17 gates, 2 slow, avg pipeline latency: 43ms
```

## Parameters
- `gate_name`: Filter to a specific gate (optional)
- `window_minutes`: Time window to analyze (default: current session)

## Data Sources
- `~/.claude/hooks/.gate_timing.json` — per-gate timing records
- State files in ramdisk for live timing data
