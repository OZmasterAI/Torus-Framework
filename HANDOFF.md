# Session 149 — Self-Evolve Architecture Diagram + Memory Layer Deep-Dive

## What Was Done
- Created updated `Torus-Self-Evolve-Diagram.md` on Desktop — reflects current framework state
  - 4 new toggles, corrected values, new Self-Evolve Features section, TUI Dashboard, gate effectiveness stats
  - Changelog section documenting all differences from original diagram
- Created `torus-self-evolve-diagram.html` on Desktop — interactive HTML version
  - Cyan-themed Self-Evolve layer, hero stats bar, per-gate block/override counts, NEW badges, collapsible sections
- Discussed memory layer architecture with user:
  - L2 enrichment ±30min = context window around matched memory timestamps (not a rolling window)
  - L3 Telegram search triggers based on `tg_l3_always` toggle; enrichment only runs if L3 returned results
  - Session-end Telegram notifications work WITHOUT bot running (raw Bot API in on_session_end.py hook)
  - Bot toggle (`tg_bot_tmux`) only controls interactive two-way chat, not push notifications

## What's Next
- Merge self-evolve-test-branch to main (4+ commits ahead)
- Add safety guard to app.py (refuse to run inside Claude Bash tool)
- Enable gate_auto_tune — effectiveness data now accumulating
- Enable budget_degradation + set session_token_budget
- Consider adding `tg_session_notify` toggle to control session-end Telegram messages independently

## Known Issues
- Plan mode exit loop — platform limitation, mitigated by behavioral rule
- ChromaDB concurrent access — tests skip when MCP running, correct behavior
- Export test_framework.py uses _FRAMEWORK_ROOT — merge changes, don't copy
- Observations at 5,635 (over 5K cap) — will auto-compact on next ingest
- tmux routing shared session causes interference — use dedicated claude-bot
- TaskCompleted hook disabled — was firing premature quality warnings
- auto_commit Co-Authored-By hardcoded "Opus 4.6" — wrong when on Sonnet

## Service Status
- Memory MCP: RUNNING (667 memories)
- Tests: 1103 passed, 0 failed
- Framework version: v2.4.5 (Torus)
- Gate enforcement: MECHANICAL (exit code 2) — 15 active gates (Gate 8 dormant)
- Gate effectiveness: 431 blocks / 8 overrides (98.2% enforcement)
- Ramdisk: active at /run/user/1000/claude-hooks
- Telegram bot: NOT RUNNING (configured, toggle OFF — session-end notifications still active)
- GitHub: OZmasterAI/Torus-Framework (gh auth on OZmasterAI)
- Branch: self-evolve-test-branch

## Session Metrics
- **Files Created**: 2 (Desktop: Torus-Self-Evolve-Diagram.md, torus-self-evolve-diagram.html)
- **Memories Saved**: 2
- **Tests**: not run this session (1103 passed last session)
- **Errors**: 0
