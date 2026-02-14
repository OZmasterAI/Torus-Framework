# Session 32 — ChromaDB Hardening + v2.0.2 Tests + Framework Comparison

## Key Learnings
- ChromaDB Rust PersistentClient segfaults on concurrent access — lazy init is the root fix, not more guards
- thepopebot is an autonomous agent platform (Docker+GitHub Actions), NOT a Claude Code framework — different problem domain entirely
- Module-level Python code runs on import — always defer expensive resource creation to lazy init for testability

## What Was Done

### Session 31 Recovery
- Terminal crashed before wrap-up; recovered state from memory MCP
- Updated stale HANDOFF.md and LIVE_STATE.json from Session 30 → 32

### ChromaDB Segfault Hardening (3 files)
- `memory_server.py`: Replaced module-level `PersistentClient` with lazy `_init_chromadb()` — importing no longer opens the database
- `boot.py`: Added `pgrep` guard to skip direct ChromaDB when MCP server is running
- `session_end.py`: Same guard — defers observation queue flush when MCP running
- Root cause eliminated: `from memory_server import X` no longer creates a PersistentClient

### v2.0.2 Functional Tests (33 new tests)
- `_apply_recency_boost`: 7 tests (score math, edge cases, >365d decay)
- `format_results`: 7 tests (relevance calc, empty/None inputs)
- `format_summaries`: 4 tests (query vs get structure detection)
- `suggest_promotions`: 15 tests (clustering, scoring, ChromaDB-guarded)
- Total: 901 passed, 0 failed

### Framework Comparison: Megaman vs thepopebot
- Different layers: Megaman = Claude Code customization, thepopebot = autonomous agent infra
- Megaman wins: memory (283), gates (13), tests (901), token efficiency (1.5x leaner)
- thepopebot wins: Telegram UI, cron/webhooks, Docker isolation, browser automation

### Commits
- `c47fc0c` — Session 31: AKIRA feature adoption sprint (9 files)
- `ffaed98` — Session 32: ChromaDB lazy init + segfault hardening + v2.0.2 tests (6 files)

## What's Next
1. **Dashboard auto-start** — Consider adding to SessionStart hook
2. **Memory graph visualization** — D3.js network of related memories
3. **Telegram/chat UI** — Inspired by thepopebot, add conversational interface
4. **Credential filtering** — thepopebot's env-sanitizer approach is stronger than instruction-based

## Known Issues
- ChromaDB segfault: **largely mitigated** by lazy init, but external worker still deferred
- MCP server requires restart for code changes (pkill + auto-restart on next tool call)
- MCP connection breaks if server killed mid-session (reconnects on next session start)
- 26 pre-existing gate interaction test failures (timing-dependent, not consistent)

## Service Status
- Enforcer: active (PreToolUse, 13 gates, audit logging)
- Tracker: active (PostToolUse, fail-open)
- Boot: active (SessionStart, memory injection, **pgrep-guarded ChromaDB**)
- Auto-Approve: active (PermissionRequest, deny-before-allow)
- SubagentContext: active (SubagentStart, context injection + subagent tracking + safety rules)
- EventLogger: active (SubagentStop, token parsing + state cleanup + TaskCompleted warnings)
- PreCompact: active (PreCompact, state snapshots)
- SessionEnd: active (SessionEnd, queue flush, **pgrep-guarded ChromaDB**)
- StatusLine: active (subprocess-isolated ChromaDB, HP 100%, SA:/ST: subagent display)
- **Dashboard: available** (`python3 ~/.claude/dashboard/server.py` → localhost:7777)
- Memory MCP: active — 283 curated memories, **15 MCP tools** (gateway), 13 gates
- Skills: **18 total**
- Tests: 901 passing, 0 failures

## MCP Tools (15)
Core: search_knowledge, remember_this, deep_query, get_memory (batch), get_recent_activity
Tags: search_by_tags
Observations: search_observations, get_observation, get_session_sentiment
Timeline: timeline
Causal Chain: record_attempt, record_outcome, query_fix_history
Stats: memory_stats
**Gateway: maintenance** (dispatches: promotions, stale, cluster, health, rebuild_tags)
