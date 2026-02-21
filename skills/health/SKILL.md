# /health — Framework Health Diagnostic

## When to use
When user says "health", "check health", "status check", "diagnostics",
or wants to verify the Torus framework is working correctly.

## Commands
- `/health` — Run full diagnostic and show report
- `/health --repair` — Run diagnostic and fix common issues

## Flow
1. Run `python3 ~/.claude/skills/health/scripts/check.py` (or `--repair` flag)
2. Display the results to the user
3. If issues found, suggest fixes

## What it checks
1. Memory MCP: process running (pgrep) + ChromaDB accessible
2. Gates: all gate files present + importable
3. State: valid JSON, correct schema version
4. Ramdisk: mounted, writable
5. File claims: stale claims (>2 hours old)
6. Audit logs: today's log exists, not oversized (>5MB)
7. Deferred items: count from Gate 9 deferrals
8. PRPs: any active PRPs with stuck tasks

## Rules
- ALWAYS run the check.py script — don't manually inspect files
- For --repair, only perform safe operations (delete stale claims, reset corrupt state)
- NEVER modify gate files, enforcer.py, or settings.json
