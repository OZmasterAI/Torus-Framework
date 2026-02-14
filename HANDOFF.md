# Session 52 — Crash-Proof MCP Server + Dashboard Cache Fix

## What Was Done

### Crash-proof MCP server (memory_server.py)
- Added `@crash_proof` decorator wrapping all 15 `@mcp.tool()` handlers
- Decorator catches exceptions, logs full traceback to stderr, returns `{"error": "..."}` dict
- Hardened `_init_chromadb()` with try/except and `_chromadb_degraded` flag
- Wrapped `mcp.run()` entry point with fatal error handler
- Updated test_framework.py to handle new decorator stacking (3-line lookback for `@mcp.tool()`)

### Fixed dashboard Live Metrics "Loading..." forever
- Root cause: browser serving stale cached `app.js` from before `renderLiveMetrics()` was added
- Server logs confirmed: no `/api/live-metrics` request ever made by browser
- Added `?v=2` cache-busting to `<script>` and `<link>` tags in index.html
- Added `NoCacheStaticWrapper` ASGI middleware for `Cache-Control: no-cache` on `/static/` paths
- Key learning: Starlette `BaseHTTPMiddleware` does NOT intercept `Mount` sub-apps — must use raw ASGI wrapper

### Diagnosed UDS socket missing issue
- Socket file `/home/crab/.claude/hooks/.chromadb.sock` missing from filesystem
- Socket still listening per `ss` (kernel holds it) but new connections fail
- Dashboard falls back to standalone ChromaDB PersistentClient (concurrent access risk)
- Self-heals on next session start when MCP server recreates socket

## What's Next
1. **UDS socket**: Will self-heal on next session — verify socket file exists after restart
2. **Real-world loop test**: Run megaman-loop on a substantial PRP (5+ tasks)
3. **Dashboard gate name normalization**: Safety net for historical audit entries
4. **Backlog**: inject_memories cleanup, dashboard auto-start, stale X sessions cron

## Service Status
- Memory MCP: 329 memories, crash-proofed
- Tests: 1036 passed, 1 pre-existing failure
- Dashboard: running with cache-busting, Live Metrics operational
- UDS socket: missing file (operational risk) — will self-heal next session
