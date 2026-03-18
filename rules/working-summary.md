# Working Summary (Claude-written at context threshold)

## Goal
Build two custom agent frameworks (Go + TS) from scratch. Custom loop, hooks, DAG conversations, providers. No pi-agent-core, no pi-ai.

## Approach
Phase-by-phase. Go first (complete except memory), then TS (in progress). Plans at /home/crab/projects/research/custom-agent-plan-go.md and custom-agent-plan-ts.md.

## Progress
### Completed
**Go** (`/home/crab/projects/go_sdk_agent/`) — 21 files, 4,385 lines, all phases 1-2-4-5:
- types, hooks(12), DAG(SQLite WAL), ReAct loop, 6 tools, Anthropic+OpenRouter providers, router
- tokenizer, compaction(DAG-native), smart routing, Bubble Tea TUI, Telegram, startup menu
- MCP(progressive disclosure), skills, sub-agents(goroutines), OAuth PKCE, prompt caching
- Fixes: import cycle, tool_calls format, tool_result format, OAuth headers, cache_control limit, maxTokens cap

**TS** (`/home/crab/projects/ts_sdk_agent/`) — 16 files, 1,779 lines:
- types, hooks, DAG(better-sqlite3), loop, tools(6), tokenizer, compaction, providers, config, OAuth, REPL entry
- Working with OpenRouter + Anthropic OAuth

### In Progress
- TS TUI — Claude Code style with pi-tui. User wants it to look like Claude Code, NOT like Torus-pi-core's simplified version.

### Remaining (TS)
- TUI (interactive.ts + components), Telegram, startup menu, MCP, skills, sub-agents
- Phase 3 (memory) for both — deferred

## Key Files
- Go: `cmd/main.go`(183), `internal/core/loop.go`(224), `internal/providers/anthropic.go`(261), `internal/ui/tui.go`(417), `internal/features/mcp.go`(531)
- TS: `src/core/loop.ts`(147), `src/core/dag.ts`(285), `src/index.ts`(86), `src/providers/anthropic.ts`(204)

## Decisions & Rationale
- OAuth needs: `anthropic-beta: oauth-2025-04-20`, `user-agent: claude-cli/*`, `x-app: cli`, system prefix "You are Claude Code"
- tool_result: Anthropic=role:"user"+tool_result blocks, OpenAI=role:"tool"+tool_call_id
- SOUL.md renamed to TORUS.md
- maxTokens capped at 64000 for Anthropic provider

## User Corrections
- No sub-agents for building — do it yourself
- TUI must look like Claude Code, not Torus-pi-core
- Memory report IS about Herm (don't contradict)

## Next Steps
1. Finish TS TUI (Claude Code style)
2. TS: Telegram, startup, MCP, skills, sub-agents
3. Phase 3 (memory) — both Go + TS
