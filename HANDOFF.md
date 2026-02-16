# Session 97 — ChromaDB Backup + Watchdog

## What Was Done
- Implemented ChromaDB backup system across 5 files: `memory_server.py`, `chromadb_socket.py`, `gather.py`, `session_end.py`, `boot.py`
- Server-side `_backup_database()` uses `sqlite3.backup()` API (WAL-safe, atomic via .tmp + os.replace)
- Client-side `backup()` wrapper in chromadb_socket.py
- Wrap-up integration: `gather_backup()` reports backup status in JSON
- Session end safety net: `backup_database()` with mtime-skip (after flush, before increment)
- Boot watchdog: two-tier detection — <1KB = truncation, <80% of backup = shrinkage
- Deep audit (3 sonnet agents): fixed critical connection resource leak, 2 medium accepted
- User correction applied: changed watchdog from fixed 1MB threshold to relative 80%-of-backup comparison

## What's Next
1. Fix stats-cache.json `memory_count` gap (carried from Session 70)
2. Clean up stale hook registrations (TeammateIdle, TaskCompleted) from settings.json
3. Activate get_teammate_context() — add @mcp.tool() + @crash_proof
4. Add ChromaDB degraded mode guards in MCP tool bodies (HIGH from audit)
5. Privacy tags — `<private>` edge stripping in tracker.py/observation.py
6. Address remaining medium audit findings if desired (TOCTOU mtime, backup locking)

## Known Issues
- stats-cache.json lacks `memory_count` key — gather.py RED flag can fire when socket unreachable
- Plan mode exit loop — ExitPlanMode rejected twice can trap in loop
- gather.py UDS socket unreachable during wrap-up (non-blocking, uses fallback)
- Hybrid linking tests skip when MCP server is running (ChromaDB concurrent access segfault)
- Backup via UDS not testable from CLI (socket only available inside MCP process)

## Service Status
- Memory MCP: ACTIVE (445 memories in knowledge collection). Restart needed for backup dispatch.
- ChromaDB Backup: SHIPPED (sqlite3.backup + watchdog). Backup dispatch activates next session.
- Tests: 1043 passed, 0 failed
- Framework version: v2.4.5
- Gate enforcement: MECHANICAL (exit code 2)
- boot.py: Session start protocol + DB watchdog active
- Ramdisk: active at /run/user/1000/claude-hooks
- Auto-handoff: ACTIVE (session_end.py + user_prompt_capture.py)
- Hybrid Linking: ACTIVE and VERIFIED
