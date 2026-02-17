# Session 118 — RRF Hybrid Merge + Keyword Overlap Reranker

## What Was Done
- **RRF merge** — Replaced `_merge_results()` flat +0.1 bonus with Reciprocal Rank Fusion (k=60). Keyword and semantic engines now have equal weight; items in both score ~2x higher.
- **Keyword overlap reranker** — New `_rerank_keyword_overlap()` adds +0.05*(matched/total) boost based on exact query term matches in preview+tags. Works on all search modes including semantic-only.
- **Pipeline wiring** — Inserted reranker between tag expansion and recency boost in `search_knowledge()`.
- **Tests updated** — Replaced hardcoded merge test with relative-ordering check. Added 2 new reranker tests (boost + no-op). All 1043 tests pass.
- **GitHub export synced** — Committed and pushed `a6fc01e` to OZmasterAI/Torus-Framework (5 commits total).

## What's Next
- Apply Haiku→Sonnet change to agents/researcher.md (decided session 111, deferred)
- Sync Megaman→Torus rename to GitHub export
- Dormant: agent team context tool (`get_teammate_context()`)
- Dormant: privacy tags (`<private>` edge stripping)

## Known Issues
- Plan mode exit loop — platform limitation, mitigated by behavioral rule
- ChromaDB concurrent access — tests skip when MCP running, correct behavior
- Export test_framework.py uses _FRAMEWORK_ROOT relative paths — must merge changes, not copy
- Observations at 5,635 (over 5K cap) — will auto-compact on next ingest

## Service Status
- Memory MCP: RUNNING (496 memories, 5 collections)
- Tests: 1043 passed, 0 failed
- Framework version: v2.4.5 (Torus)
- Gate enforcement: MECHANICAL (exit code 2) — 13 active gates (Gate 8 dormant)
- Ramdisk: active at /run/user/1000/claude-hooks
- GitHub: OZmasterAI/Torus-Framework (gh auth on OZmasterAI, 5 commits)
- XRDP: WORKING (XFCE4, DBUS fix applied)
