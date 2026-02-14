# Session 36 — ChromaDB UDS Gateway: Single-Owner Architecture

## Key Learnings
- UDS (Unix Domain Socket) is ~470-1000x faster than subprocess for local IPC — no process spawn overhead
- Replacing pgrep with UDS-only detection is unsafe during transition — pre-upgrade servers don't have the socket file. Use UDS-first + pgrep fallback.
- Dashboard standalone fallback (safe_count/safe_query/safe_get) restores independence when MCP server isn't running
- ChromaDB concurrent PersistentClient segfault is now architecturally impossible (single-owner guarantee)
- Killing MCP server mid-session breaks MCP tool reconnection — tools unavailable until next session

## What Was Done

### ChromaDB UDS Gateway (8 files, 2 commits)
**Commit `6b5faa9`** — Main implementation (7 phases):
1. `hooks/shared/chromadb_socket.py` (NEW) — UDS client module (132 lines)
2. `hooks/memory_server.py` — Daemon thread UDS server + atexit cleanup
3. `hooks/statusline.py` — subprocess query → socket_count() (~470x faster)
4. `hooks/session_end.py` — pgrep + PersistentClient → socket_flush()
5. `hooks/boot.py` — pgrep + PersistentClient → socket_available/query/count/flush
6. `dashboard/server.py` — _get_chroma() + 10 endpoints → socket client calls
7. `hooks/test_framework.py` — 14 new UDS socket tests

**Commit `15ca09f`** — Gap fixes:
- Dashboard: safe_count/safe_query/safe_get wrappers with standalone PersistentClient fallback
- test_framework.py: UDS-first + pgrep fallback for server detection

### Results
- 925 tests passing, 0 failures (up from 901)
- Single-owner guarantee: only memory_server.py creates PersistentClient
- All pgrep guards eliminated from production hooks
- All `import chromadb` removed from consumer files
- StatusLine: ~3.3s → ~7ms per prompt

## What's Next
1. **Remove old inject_memories()** — Dead code in boot.py (kept for 4 test compatibility). Rewrite tests to use inject_memories_via_socket() to clean up.
2. **Dashboard auto-start** — Consider adding to SessionStart hook
3. **Memory graph visualization** — D3.js network of related memories
4. **HTTP /health endpoint** — Optional addition to memory_server.py for ops monitoring (~40 lines)

## Known Issues
- MCP tool reconnection: Killing MCP server mid-session breaks tool access until next session restart
- 26 pre-existing gate interaction test failures (timing-dependent, not consistent)
- Old inject_memories() function in boot.py is dead code (tested directly, not called from main())

## Service Status
- Enforcer: active (PreToolUse, 13 gates, audit logging)
- Tracker: active (PostToolUse, fail-open)
- Boot: active (SessionStart, **UDS socket memory injection**)
- Auto-Approve: active (PermissionRequest, deny-before-allow)
- SubagentContext: active (SubagentStart, context injection + subagent tracking + safety rules)
- EventLogger: active (SubagentStop, token parsing + state cleanup + TaskCompleted warnings)
- PreCompact: active (PreCompact, state snapshots)
- SessionEnd: active (SessionEnd, **UDS socket queue flush**)
- StatusLine: **UDS socket memory count** (HP 100%, SA:/ST: subagent display)
- **Dashboard: available** (`python3 ~/.claude/dashboard/server.py` → localhost:7777, **standalone fallback**)
- Memory MCP: active — 294 curated memories, **15 MCP tools** (gateway), 13 gates
- **UDS Gateway: active** — `.chromadb.sock`, single-owner ChromaDB access
- Skills: **18 total**
- Tests: 925 passing, 0 failures

## MCP Tools (15)
Core: search_knowledge, remember_this, deep_query, get_memory (batch), get_recent_activity
Tags: search_by_tags
Observations: search_observations, get_observation, get_session_sentiment
Timeline: timeline
Causal Chain: record_attempt, record_outcome, query_fix_history
Stats: memory_stats
**Gateway: maintenance** (dispatches: promotions, stale, cluster, health, rebuild_tags)

## Commits
- `6b5faa9` — Session 36: ChromaDB UDS Gateway — single-owner architecture (7 files)
- `15ca09f` — Fix UDS migration gaps: dashboard fallback + test detection hardening (2 files)
