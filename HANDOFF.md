# Session 28 — Stale Count Fixes (v2.4.1)

## What Was Done

### Stale Count Fixes
- Fixed `LIVE_STATE.json` → `curated_memories`: 225 → 268 (actual ChromaDB count)
- Fixed `LIVE_STATE.json` → `skills_count`: 11 → 18 (actual skill directories)
- Fixed `statusline.py` → `EXPECTED_SKILLS`: 9 → 18 (HP skills dimension now accurate)
- Updated `known_issues` to reflect EXPECTED_SKILLS fix

### Committed Accumulated Session 27 Work (v2.4.1)
- MCP gateway consolidation (19 → 15 tools, ~690 tokens/req savings)
- ChromaDB segfault subprocess isolation in statusline
- TC:/T:/A: statusline fields for tool tracking and session age
- Dashboard `/api/tool-usage` endpoint
- State schema update (`tool_call_counts`, `total_tool_calls`)
- 26 new tests (gateway: 14, tool-usage/statusline/state: 12)

### Commit
- `4cda6ad` — v2.4.1: MCP gateway, segfault isolation, stale count fixes

## What's Next
1. **Fix ChromaDB segfault** — Systemic issue: crashes test_framework.py, statusline subprocess, subagent MCP access
2. **Write tests** for v2.0.2 features (recency boost, suggest_promotions, markdown renderer)
3. **Auto-start dashboard** — Consider adding to SessionStart hook
4. **Memory graph visualization** — D3.js network of related memories
5. **Skill usage analytics** — Track which skills are called and how often
6. **Session comparison view** — Side-by-side diff of handoff sessions
7. **FTS5 persistence** — Revisit when memory count > 800

## Service Status
- Enforcer: active (PreToolUse, 12 gates, audit logging)
- Tracker: active (PostToolUse, fail-open)
- Boot: active (SessionStart, memory injection)
- Auto-Approve: active (PermissionRequest, deny-before-allow)
- SubagentContext: active (SubagentStart, context injection)
- PreCompact: active (PreCompact, state snapshots)
- SessionEnd: active (SessionEnd, queue flush)
- StatusLine: active (subprocess-isolated ChromaDB, HP 100%)
- **Dashboard: available** (`python3 ~/.claude/dashboard/server.py` → localhost:7777)
- Memory MCP: active — 268 curated memories, **15 MCP tools** (gateway), 12 gates
- Skills: **18 total**
- Tests: 553+ passing, test_framework.py segfaults under full load (ChromaDB issue)

## MCP Tools (15)
Core: search_knowledge, remember_this, deep_query, get_memory, get_recent_activity
Tags: search_by_tags
Observations: search_observations, get_observation, get_session_sentiment
Timeline: timeline
Causal Chain: record_attempt, record_outcome, query_fix_history
Stats: memory_stats
**Gateway: maintenance** (dispatches: promotions, stale, cluster, health, rebuild_tags)
