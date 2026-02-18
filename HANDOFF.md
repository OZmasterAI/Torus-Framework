# Session 125 — Gate 3 Fix + Framework Comparison Research

## What Was Done
1. **Gate 3 fix**: Added `test_framework.py` detection to `_detect_test_framework()` in `gate_03_test_before_deploy.py`. Now correctly suggests `python3 test_framework.py` instead of falling back to `pytest`. Fixed existing test, added new test. 1082 tests passing (+1).
2. **Confirmed tracker is fine**: `tracker.py` line 497 already has `"test_framework.py"` in keyword list — substring matching covers all `python3` variants. No change needed.
3. **Sonnet 4.6 confirmed available**: Claude Code model alias `"sonnet"` auto-resolves to Sonnet 4.6 (released Feb 17). No settings changes needed.
4. **Deep framework comparison**: 6 parallel research agents analyzed awesome-claude-code, claude-simone, claude_code_agent_farm, Claude-Code-Workflow, claude-flow, SuperClaude. Compared all against Torus and vanilla Claude Code across 8 dimensions (token efficiency, cost, speed, consistency, learning, quality, memory, reliability). Full scoring saved to memory.

**Key research findings:**
- Torus scored 87/100, highest by 28+ points over all competitors
- Vanilla Claude Code (54) ties CCW and beats claude-flow (33)
- claude-flow intelligence layer is stub code (Issue #1154), metrics are hardcoded fakes (#1158)
- SuperClaude injects ~14,500 tokens/prompt (6.6x Torus), 4/5 ConfidenceChecker methods are stubs
- Pattern: everyone builds orchestration, almost nobody builds enforcement + memory

## What's Next
- Monitor auto-remember queue — check if entries are useful when retrieved
- Monitor dedup thresholds for auto-captured noise
- Run `deduplicate_sweep(dry_run=True)` to audit existing corpus
- Apply Haiku→Sonnet change to agents/researcher.md
- Sync changes to GitHub export repo
- Dormant: agent team context tool (`get_teammate_context()`)
- Dormant: privacy tags (`<private>` edge stripping)
- Explore: Claudeception (skill extraction, 1.5K stars), cipher (memory layer, 3.4K stars) for ideas

## Known Issues
- Plan mode exit loop — platform limitation, mitigated by behavioral rule
- ChromaDB concurrent access — tests skip when MCP running, correct behavior
- Export test_framework.py uses _FRAMEWORK_ROOT relative paths — must merge changes, not copy
- Observations at 5,635 (over 5K cap) — will auto-compact on next ingest

## Service Status
- Memory MCP: RUNNING (518 memories, 6 collections incl. quarantine)
- Tests: 1082 passed, 0 failed
- Framework version: v2.4.5 (Torus)
- Gate enforcement: MECHANICAL (exit code 2) — 15 active gates (Gate 8 dormant), tool-scoped dispatch
- Ramdisk: active at /run/user/1000/claude-hooks
- GitHub: OZmasterAI/Torus-Framework (gh auth on OZmasterAI, 7 commits)
- XRDP: WORKING (XFCE4, DBUS fix applied)
