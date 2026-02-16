# Session 90 — Exit Code Fix + Gate 6 Deadlock Repair

## What Was Done
- **CRITICAL FIX**: Changed all 7 `sys.exit(1)` → `sys.exit(2)` in enforcer.py
  - Claude Code hook protocol: exit(1) = non-blocking error, exit(2) = mechanical BLOCK
  - Gates were relying on LLM behavioral compliance for 89 sessions
  - Verified via official docs + live subprocess tests
- **GATE 6 DEADLOCK FIX**: exit(2) exposed latent deadlock in gate 6
  - Removed `save_state()` from inside gate 6 (raced with remember_this() resets)
  - Tracker now clears `verified_fixes` when `remember_this()` is called
  - `/tmp` paths excluded from `verified_fixes` tracking at insertion time
  - `ESCALATION_THRESHOLD` raised from 2 → 5
  - 5 test paths updated from `/tmp/` to `/home/test/`
- Updated docs: `rules/hooks.md`, `CLAUDE.md` (exit code corrections)
- AKIRA feature adoption: 1/4 implemented (exit codes), 3/4 skipped (constants, BGE-M3, test splitting)
- 1034 tests pass, 0 failures

## Key Learnings
- Exit(2) fix was right but underestimated blast radius — activated dormant enforcement that exposed gate 6 bug
- Gates should be pure checkers, not state mutators — enforcer owns state persistence
- Always test gate blocking paths under real conditions before deploying enforcement changes

## What's Next
1. Fix stats-cache.json `memory_count` gap (carried from Session 70)
2. Clean up stale hook registrations (TeammateIdle, TaskCompleted) from settings.json
3. Activate get_teammate_context() — add @mcp.tool() + @crash_proof
4. Add ChromaDB degraded mode guards in MCP tool bodies (HIGH from audit)
5. Privacy tags — `<private>` edge stripping in tracker.py/observation.py
6. Start using `[source: URL]` and `[ref: URL]` markers in remember_this() calls

## Known Issues
- stats-cache.json lacks `memory_count` key — gather.py RED flag can fire when socket unreachable
- Plan mode exit loop — ExitPlanMode rejected twice can trap in loop
- gather.py UDS socket unreachable during wrap-up (non-blocking, uses fallback)

## Service Status
- Memory MCP: 420 memories
- Tests: 1034 passed, 0 failed
- Framework version: v2.4.4
- Gate enforcement: MECHANICAL (exit code 2) — fully tested with deadlock fix
- Ramdisk: active at /run/user/1000/claude-hooks
- Statusline: 2-line layout, session number field, 5-tier context colors
- Dashboard: memory graph fixed, 14 ES6 modules, cyberpunk theme
- Agent Teams: DISABLED (sub-agents via Task tool still available)
- Auto-handoff: ACTIVE (session_end.py + user_prompt_capture.py)
- Citation URLs: ACTIVE (server-side, fail-open, zero token cost)
