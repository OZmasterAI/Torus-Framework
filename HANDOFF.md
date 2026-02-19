# Session 152 — Web Dashboard Enhancement + Terminal Chat

## What Was Done
- **Phase 1: Server Infrastructure** — Added `/api/statusline-snapshot` (git branch enrichment), `POST /api/toggles/{key}` (11-key whitelist, atomic write), SSE `live_state_event` mtime tracking, CORS POST support
- **Phase 2: Statusline Metrics Bar** — Slim horizontal bar: model name (color-coded opus/sonnet/haiku), git branch, context% (5-tier color), cost, CMP, memory freshness, tokens, lines, budget tier badge
- **Phase 3: Interactive Toggles Panel** — 11 toggle pills with POST on click, optimistic UI with rollback, numeric cycling for session_token_budget (0/50k/100k/200k), SSE cross-tab refresh
- **Phase 4: Terminal Chat** — WebSocket handler spawning `claude -p` subprocess with `--resume` for session continuity, `--output-format stream-json`, `CLAUDECODE=0` env, token-by-token streaming, session management via sessionStorage UUID
- **New files**: `statusline.js`, `toggles.js`, `chat.js`
- **Modified**: `server.py`, `index.html`, `style.css`, `main.js`, `sse.js`
- All 1116 tests passing, dashboard verified working on localhost:7777
- **Gate review Q&A** — Reviewed all 17 gates (16 active, 1 dormant). Auto-tune has enough data for gates 04/05/06. Gate 14 assessed for tunability — decided against (too few fires, current 3-strike balanced). Gate 10 clarified: steps 1+2 always active, only budget tiers need toggle.

## What's Next
- Merge self-evolve-test-branch to main (many commits ahead)
- Enable gate_auto_tune — effectiveness data now accumulating
- Enable budget_degradation + set session_token_budget (4-tier ready)
- Test terminal chat end-to-end (WebSocket + claude -p subprocess)

## Known Issues
- Plan mode exit loop — platform limitation, mitigated by behavioral rule
- ChromaDB concurrent access — tests skip when MCP running, correct behavior
- Export test_framework.py uses _FRAMEWORK_ROOT — merge changes, don't copy
- Observations at 5,635 (over 5K cap) — will auto-compact on next ingest
- tmux routing shared session causes interference — use dedicated claude-bot
- TaskCompleted hook disabled — was firing premature quality warnings
- auto_commit Co-Authored-By hardcoded Opus 4.6 — wrong when on Sonnet
- UDS socket intermittently missing — gather.py warns but non-blocking

## Service Status
- Memory MCP: RUNNING (684 memories)
- Tests: 1116 passed, 0 failed
- Framework version: v2.5.0 (Torus)
- Gate enforcement: MECHANICAL (exit code 2) — 16 active gates (Gate 8 dormant)
- Ramdisk: active at /run/user/1000/claude-hooks
- Telegram bot: NOT RUNNING (configured, toggle OFF)
- Telegram mirror: configured (toggle OFF by default)
- Telegram notify: ON
- Web Dashboard: localhost:7777 (statusline + toggles + chat + SSE)
- GitHub: OZmasterAI/Torus-Framework (gh auth on OZmasterAI)
- Branch: self-evolve-test-branch
- Toggles: 11 total
