# Session 151 Handoff

## What Was Done
- **tg_session_notify toggle** — Gates session-end Telegram notifications (was always-on). Added to session_end.py, statusline, TUI, boot.py
- **tg_mirror_messages toggle + Stop hook** — Mirrors ALL Claude responses to Telegram in real-time via `tg_mirror.py` Stop hook. Reads new assistant turns from transcript JSONL, sends via Bot API. Cursor tracking prevents re-sending
- **Mirror first-run fix** — Fixed bug where enabling Mirror replayed entire transcript history. Now skips to end on first activation
- **Toggle reorder** — Budget moved below Mirror per user preference. New order: L2, Enrich, TG, TGe, Bot, Tune, Chain, Notify, Mirror, Budget, TokBgt
- **Safety guard for app.py** — Added CLAUDECODE env var check at `__main__`, exits with error instead of launching Textual from Claude's Bash tool
- Tests: 1116 passed, 0 failed

## What's Next
- Merge self-evolve-test-branch to main (many commits ahead)
- Enable gate_auto_tune — effectiveness data now accumulating
- Enable budget_degradation + set session_token_budget (4-tier ready)

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
- Memory MCP: RUNNING (678 memories)
- Tests: 1116 passed, 0 failed
- Framework version: v2.5.0 (Torus)
- Gate enforcement: MECHANICAL (exit code 2) — 16 active gates (Gate 8 dormant)
- Ramdisk: active at /run/user/1000/claude-hooks
- Telegram bot: NOT RUNNING (configured, toggle OFF)
- Telegram mirror: configured (toggle OFF by default)
- Telegram notify: ON
- GitHub: OZmasterAI/Torus-Framework (gh auth on OZmasterAI)
- Branch: self-evolve-test-branch
- Toggles: 11 total (was 9)
