# /status — Quick System Health Check

## When to use
When the user says "status", "check", "health", or wants a system overview.

## Steps
1. Run `python3 ~/.claude/skills/status/scripts/gather.py`
2. Display the output to the user exactly as-is (it's a pre-formatted dashboard)
3. If the script fails or returns an error, fall back to manual gathering:
   - Read ~/.claude/LIVE_STATE.json for current project state
   - Read `what_was_done` from ~/.claude/LIVE_STATE.json for last session summary
   - Check maintenance(action="health") for memory count and health score
   - Run `python3 ~/.claude/hooks/boot.py` for session info
   - Display a summary of the gathered data
