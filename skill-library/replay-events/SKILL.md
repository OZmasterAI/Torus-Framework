# /replay-events — Gate Pipeline Regression Testing

Replay historical tool events through the gate pipeline to detect regressions or improvements after gate modifications.

## Steps

1. Load recent events from `~/.claude/hooks/.event_capture.jsonl`
2. For each event, re-run through all applicable gates using the enforcer's dry-run mode
3. Compare current gate outcome vs original outcome:
   - **New block**: gate now blocks something it previously allowed (potential regression)
   - **New pass**: gate now allows something it previously blocked (potential improvement)
   - **Unchanged**: same outcome
4. Summarize results

## Output
```
Replayed: N events
Unchanged: X | New blocks: Y | New passes: Z

Changed events:
  [tool] Edit → was: allow, now: block (gate-01) — REGRESSION
  [tool] Bash → was: block, now: allow (gate-03) — IMPROVEMENT
```

## Filters
- `tool_filter`: Only replay events for a specific tool
- `gate_filter`: Only check specific gates
- `blocked_only`: Only replay events that were originally blocked

## Data Sources
- `~/.claude/hooks/.event_capture.jsonl` — captured tool events
- Enforcer dry-run via `preview_gates` analytics tool
