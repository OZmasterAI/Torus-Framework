# Session 73 — Dashboard Memory Graph Fix + Statusline CMP Reposition

## What Was Done
- **Fixed memory graph TDZ bug** in `dashboard/static/modules/panels/memory-graph.js` — `const radiusScale` was declared after its first use in `forceCollide()`, causing a Temporal Dead Zone crash. Moved declaration before D3 simulation setup. Verified with headless Puppeteer (SVG: 324 bytes → 97,673 bytes).
- **Repositioned CMP icon** in `hooks/statusline.py` — combined as single element: `📦62% CMP:N` (icon first, colored percentage, then count). Previously was `62% 📦CMP:N`.
- Comparative analysis of dormant features (get_teammate_context + modes) — get_teammate_context is higher-leverage (2x throughput / 2.5x cost), modes marginal for single-file tasks. Both remain dormant per user decision.
- Discussed auto-compaction at wrap-up — decided against it. Better as a separate manual `/compact` skill with soft warning at threshold.

## What's Next
1. Fix stats-cache.json `memory_count` gap (carried from Session 70)
2. Activate get_teammate_context() — add @mcp.tool() + @crash_proof
3. Citation URLs for memories
4. Privacy tags — `<private>` edge stripping in tracker.py/observation.py
5. Memory compaction planning — revisit at 500+ (currently 371)

## Known Issues
- stats-cache.json lacks `memory_count` key — gather.py RED flag can still fire when socket unreachable
- gather.py promotion_candidates/recent_learnings fail when UDS socket unreachable (only affects wrap-up)

## Service Status
- Memory MCP: 371 memories
- Tests: 981 passed, 0 failed
- Framework version: v2.4.2
- Ramdisk: active at /run/user/1000/claude-hooks
- Statusline: 2-line layout, 📦%CMP combined element, 5-tier context colors, model-based bracket colors
- Dashboard: memory graph fixed, 14 ES6 modules, cyberpunk theme
- Dormant features: get_teammate_context (transcript visibility), modes system
