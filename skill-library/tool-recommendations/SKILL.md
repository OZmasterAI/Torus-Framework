# /tool-recommendations — Smart Tool Alternative Suggestions

Analyze tool call patterns and recommend alternatives for frequently blocked tools.

## Steps

1. Load session state from LIVE_STATE.json
2. For each tool used this session, compute:
   - Total calls
   - Block count and block rate
   - Which gates blocked it most
3. For tools with block rate > 30%, suggest alternatives:
   - Edit blocked by Gate 01 → "Read the file first, then Edit"
   - Bash blocked by Gate 02 → "Use a safer command variant"
   - Write blocked by Gate 14 → "Run tests first to establish baseline"
   - Edit blocked by Gate 06 → "Call remember_this() to save verified fixes"
4. Build success rate profiles for all tools

## Output
```
Tool Profiles:
  Edit:  45 calls, 12 blocks (27% block rate) — gates: 01, 14, 06
  Bash:  30 calls, 3 blocks (10% block rate) — gates: 02, 03

Recommendations:
  Edit → Read target file before editing (Gate 01 fix)
  Edit → Run tests after changes (Gate 14 fix)
```

## Data Sources
- LIVE_STATE.json — tool call counts, gate block history
- `~/.claude/hooks/.audit_log.jsonl` — detailed block reasons
