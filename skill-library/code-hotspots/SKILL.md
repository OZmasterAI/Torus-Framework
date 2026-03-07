# /code-hotspots — Identify High-Risk Files

Analyze gate block patterns from audit logs to find files that are repeatedly causing gate blocks.

## Steps

1. Read the audit log: `~/.claude/hooks/.audit_log.jsonl`
2. Parse entries from the last 7 days (configurable)
3. For each file path found in blocked tool inputs:
   - Count total blocks
   - Count unique gates that blocked it
   - Check edit streak from LIVE_STATE.json
4. Compute risk score: `block_count × unique_gates × edit_streak_factor`
5. Rank files from highest to lowest risk
6. Classify: critical (score > 10), high (> 5), medium (> 2), low

## Output
Present a ranked table:
| File | Blocks | Gates | Risk | Level |
Show top 20 files. Flag any critical/high files as needing immediate attention.

## Data Sources
- `~/.claude/hooks/.audit_log.jsonl` — gate block history
- `LIVE_STATE.json` — edit streaks
- `~/.claude/hooks/.gate_effectiveness.json` — per-gate stats
