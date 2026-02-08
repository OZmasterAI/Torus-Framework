# /status — Quick System Health Check

## When to use
When the user says "status", "check", "health", or wants a system overview.

## Steps
1. Read ~/.claude/LIVE_STATE.json for current project state
2. Read ~/.claude/HANDOFF.md for last session summary
3. Check gate enforcement state: Look for the most recent `state_*.json` file in `~/.claude/hooks/`, or use the current session's state file (`~/.claude/hooks/state_{session_id}.json`)
4. Count total memories: Use memory_stats() MCP tool if available, otherwise check ~/data/memory/ directory
5. Run boot dashboard: `python3 ~/.claude/hooks/boot.py` to show session info
6. Display a formatted dashboard showing:
   - Project name and version
   - Gate count and compliance status
   - Memory count
   - Active tasks
   - Last session summary
   - Any warnings or issues
