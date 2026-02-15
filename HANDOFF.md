# Session 70 — Framework Analysis, gather.py Fix, Token Optimization

## What Was Done
- Fixed gather.py RED flag: added `_is_mcp_process_running()` process detection fallback + stats-cache count fallback in `gather_memory()` (wrap-up gather.py)
- Comprehensive session 40 vs 70 comparison: framework is cheaper (-36K tokens/session), more reliable (+59% tests), gained 4 skills, crash-proof MCP, ramdisk, auto-commit. Version stayed v2.4.1 — all operational maturity.
- Fixed modes.md token leak: moved `rules/modes.md` to `modes/README.md`. Global `~/.claude/rules/` files ignore `globs` frontmatter — was wasting ~70 tokens/prompt for nothing.
- Discovered stats-cache.json missing `memory_count` key — gather.py count fallback returns 0, still triggers RED risk level when socket is unreachable.

## What's Next
1. Fix stats-cache.json `memory_count` gap — statusline or boot.py should write `memory_count` to stats-cache so gather.py fallback works (quick fix)
2. Activate get_teammate_context() — add @mcp.tool() + @crash_proof (30-second change)
3. Citation URLs — add short link format to dashboard, teach agent to output clickable refs
4. Privacy tags — `<private>` edge stripping in tracker.py/observation.py before ChromaDB
5. Memory compaction planning — not needed yet at 354 memories, revisit at 500+

## Known Issues
- stats-cache.json lacks `memory_count` key — gather.py RED flag can still fire when socket unreachable (fallback returns 0)
- gather.py promotion_candidates and recent_learnings still fail when socket unreachable (lower priority — only affects wrap-up reports)

## Service Status
- Memory MCP: 354 memories
- Tests: 967 passed, 0 failed
- Ramdisk: active at /run/user/1000/claude-hooks
- Statusline: enabled
- Dormant features: get_teammate_context (transcript visibility)
