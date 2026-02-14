# Session 29 — CLAUDE.md Token Optimization + Subagent Visibility (v2.4.2)

## What Was Done

### Subagent Visibility (v2.4.2)
- Added live subagent tracking to statusline: `SA:researcher(12k),builder(8k)`
- `subagent_context.py` — Records active subagent in session state on SubagentStart
- `event_logger.py` — Removes subagent on SubagentStop, parses transcript tokens, accumulates totals
- `statusline.py` — New `get_subagent_status()` reads transcript JSONL for live token counts
- `shared/state.py` — Added `active_subagents`, `subagent_total_tokens`, `subagent_history` fields
- Committed as `feb37a6` (v2.4.2)

### Plan Mode Loop Fix
- Added Behavioral Rule #7 (plan mode discipline) to CLAUDE.md
- Prevents: implementing code while in plan mode, repeated ExitPlanMode calls

### CLAUDE.md Token Optimization
- Reduced from ~1,666 tokens to ~1,321 tokens (-345 tokens, -20.7%)
- Renamed "Self-Healing Claude Framework" → "Megaman-Framework"
- Deleted 3 behavioral rules redundant with built-in tool descriptions
- Deleted Agent Delegation team workflow (duplicated by TeamCreate tool desc)
- Compressed: Session Start steps, Memory Tag Conventions, Causal Chain Workflow
- Added Gates 10 (MODEL COST GUARD), 11 (RATE LIMIT), 12 (PLAN MODE SAVE)
- Saves ~17,250 tokens per 50-call session

### Token Usage Comparison (v2.0.1 vs v2.4.2)
- v2.0.1: 13 MCP tools, 9 skills, 7,788 lines hook code
- v2.4.2: 15 MCP tools, 18 skills, ~9,000+ lines hook code
- Fixed overhead: ~756 tok (tool schemas) + ~1,321 tok (CLAUDE.md) = ~2,077 tok/call
- +4.9% overhead vs v2.0.1 with doubled capabilities

## What's Next
1. **Implement Gates 10, 11, 12** — Added to CLAUDE.md but enforcer.py not yet updated
2. **Fix ChromaDB segfault** — Systemic issue: crashes test_framework.py, statusline subprocess
3. **Write tests** for v2.0.2 features (recency boost, suggest_promotions, markdown renderer)
4. **Auto-start dashboard** — Consider adding to SessionStart hook
5. **Memory graph visualization** — D3.js network of related memories

## Service Status
- Enforcer: active (PreToolUse, 12 gates, audit logging)
- Tracker: active (PostToolUse, fail-open)
- Boot: active (SessionStart, memory injection)
- Auto-Approve: active (PermissionRequest, deny-before-allow)
- SubagentContext: active (SubagentStart, context injection + subagent tracking)
- EventLogger: active (SubagentStop, token parsing + state cleanup)
- PreCompact: active (PreCompact, state snapshots)
- SessionEnd: active (SessionEnd, queue flush)
- StatusLine: active (subprocess-isolated ChromaDB, HP 100%, SA:/ST: subagent display)
- **Dashboard: available** (`python3 ~/.claude/dashboard/server.py` → localhost:7777)
- Memory MCP: active — 271 curated memories, **15 MCP tools** (gateway), 12 gates
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
