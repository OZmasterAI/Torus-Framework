# Session 30 — Sub-agent Safety Rules + Batch Memory + Framework Comparison

## What Was Done

### Sub-agent Safety Rules (3 commits)
- Injected `EDIT_AGENT_RULES` into SubagentStart hook for agents that can edit files
- Rules: "Read before edit, no destructive commands, extra caution with critical files"
- `BASH_AGENT_RULES` added for Bash agents (no destructive commands only)
- Covers Gates 1, 2, 4, 7 gap — gates don't fire for sub-agents, hook injection is their only protection
- Fixed phantom builder entry bug (empty agent_id guard)
- Commits: `90fe760`, `631a566`, `305da27`, `51dbb46`

### Batch Memory Fetch
- Extended `get_memory(id)` to accept comma-separated IDs for batch retrieval
- Single ID: backward compatible, returns single entry
- Multiple IDs: returns `{"memories": [...], "count": N}`
- ChromaDB natively supports batch — near-identical performance to single fetch
- Zero new MCP tool overhead (same tool, extended behavior)
- Commit: `71628c7`

### Framework Comparison (Megaman vs AKIRA vs claude-mem)
- Megaman: ~1,321 tok CLAUDE.md, 15 MCP tools, 12 gates, 18 skills
- AKIRA: ~4,200 tok (est.), 13 gates, 6 named agents, separate tracker architecture
- claude-mem: ~1,300 tok, 5 MCP tools, 0 gates, memory-only plugin
- We already had 95% of claude-mem's 3-layer retrieval pattern — batch fetch was the only gap
- External worker process for ChromaDB segfault isolation: DEFERRED (adequate workarounds for now)

### CLAUDE.md Section-by-Section Review (continued from session 29)
- Analyzed: Behavioral Rules, Session Start, Frustration Signals, Memory Tag Conventions, Causal Chain Workflow
- Deleted 3 rules redundant with built-in tool descriptions (Rules 3, 5, 6)
- Kept 4 unique rules (prove it works, save to memory, protect main context, plan mode discipline)
- Moved deleted rules to SubagentStart hook injection (zero main context cost)

## What's Next
1. **Save deferred worker decision to memory** — MCP connection broke this session, memory not saved
2. **Fix ChromaDB segfault** — Systemic issue, consider external worker when multi-agent usage increases
3. **Write tests** for v2.0.2 features (recency boost, suggest_promotions, markdown renderer)
4. **Auto-start dashboard** — Consider adding to SessionStart hook
5. **Memory graph visualization** — D3.js network of related memories

## Known Issues
- ChromaDB/SQLite segfault: affects test_framework.py, concurrent multi-agent MCP access
- MCP server requires restart for code changes (pkill + auto-restart on next tool call)
- MCP connection breaks if server killed mid-session (reconnects on next session start)

## Service Status
- Enforcer: active (PreToolUse, 12 gates, audit logging)
- Tracker: active (PostToolUse, fail-open)
- Boot: active (SessionStart, memory injection)
- Auto-Approve: active (PermissionRequest, deny-before-allow)
- SubagentContext: active (SubagentStart, context injection + subagent tracking + safety rules)
- EventLogger: active (SubagentStop, token parsing + state cleanup)
- PreCompact: active (PreCompact, state snapshots)
- SessionEnd: active (SessionEnd, queue flush)
- StatusLine: active (subprocess-isolated ChromaDB, HP 100%, SA:/ST: subagent display)
- **Dashboard: available** (`python3 ~/.claude/dashboard/server.py` → localhost:7777)
- Memory MCP: active — 274 curated memories, **15 MCP tools** (gateway), 12 gates
- Skills: **18 total**
- Tests: 553+ passing, test_framework.py segfaults under full load (ChromaDB issue)

## Commits This Session
- `90fe760` — Inject safety rules into sub-agents via SubagentStart hook
- `631a566` — Add destructive command rule to Bash sub-agents
- `305da27` — Add critical file guard rule to sub-agent injection
- `51dbb46` — Fix phantom subagent entries from empty agent_id
- `71628c7` — Add batch fetch to get_memory via comma-separated IDs

## MCP Tools (15)
Core: search_knowledge, remember_this, deep_query, get_memory (now with batch), get_recent_activity
Tags: search_by_tags
Observations: search_observations, get_observation, get_session_sentiment
Timeline: timeline
Causal Chain: record_attempt, record_outcome, query_fix_history
Stats: memory_stats
**Gateway: maintenance** (dispatches: promotions, stale, cluster, health, rebuild_tags)
