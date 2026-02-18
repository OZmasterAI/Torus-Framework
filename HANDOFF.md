# Session 140 — TGTMUX

## What Was Done
- Built TG bot tmux routing (tmux_runner.py): sends Telegram messages into dedicated `claude-bot` tmux session via `tmux send-keys`, polls `capture-pane` for END sentinel, returns clean response
- Fixed pane dump bug: initial `capture-pane -S -` grabbed full scrollback; switched to marker-based extraction (`TORUS_MSG_{timestamp}` anchors) — captures only between marker and sentinel
- Updated bot.py with tmux routing: reads `tg_bot_tmux` toggle from LIVE_STATE.json, routes via tmux when on + session alive, falls back to `claude -p` subprocess
- Built auto wrap-up via Haiku in session_end.py: when `/wrap-up` wasn't run, reads transcript JSONL, calls `claude -p --model haiku` to generate 3-5 bullet "What Was Done" summary
- Added 5th toggle to boot.py context injection: `TG bot tmux: ON/OFF`
- E2E tested: 3.5s response time via tmux (vs ~9s subprocess cold start)

## What's Next
- Install Telethon in venv instead of --break-system-packages
- Build cheap polling queue for between-session messages
- Monitor auto-remember queue — check if entries are useful
- Run deduplicate_sweep(dry_run=True) to audit corpus (600 memories)
- Sync changes to GitHub export repo
- Apply Haiku→Sonnet change to agents/researcher.md
- Dormant: agent team context tool (get_teammate_context())
- Dormant: privacy tags (<private> edge stripping)

## Known Issues
- Plan mode exit loop — platform limitation, mitigated by behavioral rule
- ChromaDB concurrent access — tests skip when MCP running, correct behavior
- Export test_framework.py uses _FRAMEWORK_ROOT — merge changes, don't copy
- Observations at 5,635 (over 5K cap) — will auto-compact on next ingest
- Telethon installed with --break-system-packages (should use venv)
- tmux routing: shared session mode (tmux_target=claude) causes interference — use dedicated claude-bot session

## Service Status
- Memory MCP: RUNNING (600 memories, 6 collections incl. quarantine)
- Tests: 1086 passed, 0 failed
- Framework version: v2.4.5 (Torus)
- Gate enforcement: MECHANICAL (exit code 2) — 15 active gates
- Ramdisk: active at /run/user/1000/claude-hooks
- Telegram: LIVE (Claude = "Hans" ***PHONE_REMOVED***, OZ = @***REDACTED***)
- TG bot tmux: ON (tmux_target=claude-bot, 3.5s response time)
- GitHub: OZmasterAI/Torus-Framework (gh auth on OZmasterAI)
- XRDP: WORKING (XFCE4, DBUS fix applied)
