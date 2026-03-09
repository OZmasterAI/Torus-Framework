# /session-metrics — Current Session Operational Metrics

Report real-time operational metrics for the active session.

## Steps

1. Read session state from LIVE_STATE.json or ramdisk state files
2. Compute metrics:
   - Session duration (minutes)
   - Total tool calls and rate per minute
   - Gate block count and block rate
   - Error count and error rate
   - Memory query gap (seconds since last memory query)
   - Top 5 most-used tools
3. Flag anomalies:
   - Block rate > 20% — too many gate blocks
   - Error rate > 15% — high error frequency
   - Memory gap > 300s — haven't queried memory recently

## Output
```
Session Metrics (42min elapsed):
  Tool calls: 156 (3.7/min)
  Gate blocks: 12 (7.7% block rate)
  Errors: 5 (3.2% error rate)
  Memory gap: 45s

Top tools: Edit (45), Bash (38), Read (32), Grep (21), Write (10)

Status: HEALTHY (no anomalies)
```

## Data Sources
- LIVE_STATE.json — session state
- Ramdisk state files — real-time counters
