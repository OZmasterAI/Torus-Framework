# Session 124 — Memory Ingestion Levers (1 + 2scoped + 4)

## What Was Done
Implemented the full memory ingestion levers plan from sessions 122-123. Three levers across 6 files:

**Lever 1 (Behavioral):** CLAUDE.md save rule expanded to include `failed-approach/user-preference`. Tag conventions expanded with `type:auto-captured`, `type:preference`.

**Lever 4 (Auto-Remember Hooks):**
- `memory_server.py`: Extracted `_check_dedup()` helper; added `auto_remember` UDS dispatch method
- `chromadb_socket.py`: Added `remember()` wrapper
- `tracker.py`: `_auto_remember_event()` with rate limit (10/session), 4 triggers:
  - A: Test pass → queue | B: Git commit → queue | C: Error fix → critical UDS | D: Heavy edits (3+) → queue
- `boot.py`: Auto-remember queue ingestion at session start (atomic read+clear via `os.replace`)

**Lever 2 Scoped (Observation Promotion):**
- Replaced single error-based promotion with 3 scoped criteria in `_compact_observations`:
  1. Standalone errors (never fixed in same session)
  2. Cross-session file churn (5+ sessions)
  3. Repeated command patterns (3+ occurrences, excludes tests/commits)
- `_promote_observation()` helper to avoid code duplication

**Tests:** 1081 passed, 0 failed (+13 new tests)

**Analysis:** Provided before/after comparison across token cost, speed, consistency, learning, quality, memory, and reliability. Also analyzed Gate 6 blocking impact — decided to leave as-is (advisory + escalation at 5).

**GitHub sync:** Synced all 5 files to export repo, pushed to GitHub (`14733dd`).

## What's Next
- Monitor auto-remember queue in practice — check if entries are useful when retrieved
- Monitor dedup thresholds — tune if auto-captured memories create too much noise
- Run `deduplicate_sweep(dry_run=True)` to audit existing corpus for duplicates
- Apply Haiku→Sonnet change to agents/researcher.md (decided session 111, deferred)
- Add `python3 test_framework.py` to tracker's recognized test keywords
- Dormant: agent team context tool (`get_teammate_context()`)
- Dormant: privacy tags (`<private>` edge stripping)

## Known Issues
- Plan mode exit loop — platform limitation, mitigated by behavioral rule
- ChromaDB concurrent access — tests skip when MCP running, correct behavior
- Export test_framework.py uses _FRAMEWORK_ROOT relative paths — must merge changes, not copy
- Observations at 5,635 (over 5K cap) — will auto-compact on next ingest
- Gate 3 doesn't recognize `python3 test_framework.py` as test run (tracker keyword mismatch)

## Service Status
- Memory MCP: RUNNING (511 memories, 6 collections incl. quarantine)
- Tests: 1081 passed, 0 failed
- Framework version: v2.4.5 (Torus)
- Gate enforcement: MECHANICAL (exit code 2) — 15 active gates (Gate 8 dormant), tool-scoped dispatch
- Ramdisk: active at /run/user/1000/claude-hooks
- GitHub: OZmasterAI/Torus-Framework (gh auth on OZmasterAI, 7 commits, up to date)
- XRDP: WORKING (XFCE4, DBUS fix applied)
