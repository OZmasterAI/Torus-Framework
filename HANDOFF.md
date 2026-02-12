# Session 23 — Framework v2.0: 10-Feature Upgrade + Gate 10 Redesign

## What Was Done

### Sprint 1: Tracker Separation (Feature 2)
- Extracted all PostToolUse logic from `enforcer.py` into new `tracker.py` (fail-open, always exits 0)
- Enforcer is now PreToolUse-only (~130 lines, down from 376)
- Updated `settings.json`: PostToolUse → tracker.py
- Added `last_exit_plan_mode` to default_state

### Sprint 2: Audit Trail + New Gates (Features 6, 3)
- Created `shared/audit_log.py` — JSONL audit trail to `~/.claude/hooks/audit/YYYY-MM-DD.jsonl`
- Created `gate_10_model_enforcement.py` — Advisory, reads `.model_lock` file or `MODEL_LOCK` env var
- Created `gate_11_rate_limit.py` — Blocking at >60 calls/min, warns >40/min, MIN_CALLS_FOR_RATE=20
- Created `gate_12_plan_mode_save.py` — Advisory, warns when plan mode exited without `remember_this()`
- Added audit logging to enforcer's `handle_pre_tool_use()`

### Sprint 3: New Hook Scripts (Features 1, 5, 7, 8)
- Created `auto_approve.py` — PermissionRequest hook, deny-before-allow security model
- Created `subagent_context.py` — SubagentStart hook, agent-type-specific context injection
- Created `pre_compact.py` — PreCompact hook, saves state snapshot before compaction
- Created `session_end.py` — SessionEnd hook, flushes capture queue + increments session counter
- Modified `memory_server.py`:
  - Ingestion filter: rejects content <20 chars + noise patterns (npm install, pip install, etc.)
  - Near-dedup: cosine distance <0.05 returns existing_id instead of saving duplicate
  - Observation promotion: error observations promoted to curated knowledge during compaction
- Registered 4 new hook events in settings.json (PermissionRequest, SubagentStart, PreCompact, SessionEnd)

### Sprint 4: Named Agents + Status Line (Features 4, 10)
- Created 4 agent definitions in `~/.claude/agents/`:
  - `researcher.md` (haiku, read-only)
  - `auditor.md` (sonnet, security review)
  - `builder.md` (opus, full implementation)
  - `stress-tester.md` (sonnet, testing focus)
- Created `statusline.py` — displays: `project | G:12 | M:207 | CTX:23% | 15min | $0.42`
- Added statusLine config to settings.json

### Session 23: Gate 10 Redesign
- Repurposed Gate 10 from passive `.model_lock` reminder → active **Model Cost Guard**
- **Step 1 (BLOCKING):** Task calls without explicit `model` parameter are blocked — prevents silent inheritance of parent's expensive model
- **Step 2 (ADVISORY):** Warns when model doesn't match agent-type recommendations:
  - Explore/Plan → haiku or sonnet (read-only, opus is overkill)
  - general-purpose → sonnet or opus (needs Edit/Write, haiku may lack capability)
  - Bash → haiku or sonnet (command execution doesn't need opus)
  - Unknown types → pass silently
- Added 15 new tests covering both steps (+15 from 398 → 413)

### Verification
| Check | Result |
|-------|--------|
| Tests | **413 passed, 0 failed** (up from 307) |
| Hook events | 8 registered (4 original + 4 new) |
| Gates | 12 active (9 blocking + 3 advisory); Gate 10 redesigned as two-step |
| Agent files | 4 created with YAML frontmatter |
| Status line | Producing formatted output |

## What's Next
1. **Test hooks live** — Start a fresh Claude Code session to verify all 8 hooks fire correctly
2. **Verify auto_approve** — Test PermissionRequest flow (safe commands auto-approved, dangerous denied)
3. **Verify statusline** — Check the status bar renders correctly in the Claude Code UI
4. **Consider**: FTS5 index persistence — revisit when memory count > 800 (currently ~207)
5. **Consider**: Add more deny patterns to auto_approve.py as edge cases are discovered

## Service Status
- Enforcer: active (PreToolUse, 12 gates, audit logging)
- Tracker: active (PostToolUse, fail-open)
- Boot: active (SessionStart, memory injection)
- Auto-Approve: active (PermissionRequest, deny-before-allow)
- SubagentContext: active (SubagentStart, context injection)
- PreCompact: active (PreCompact, state snapshots)
- SessionEnd: active (SessionEnd, queue flush)
- StatusLine: active (project status display)
- Memory MCP: active — 210 curated memories, 12 gates
- Tests: **413 passing, 0 failures**

## New Files Created (14)
| File | Lines | Purpose |
|------|-------|---------|
| `hooks/tracker.py` | ~280 | PostToolUse state tracker (fail-open) |
| `hooks/shared/audit_log.py` | ~46 | JSONL audit trail |
| `hooks/gates/gate_10_model_enforcement.py` | ~60 | Advisory model lock gate |
| `hooks/gates/gate_11_rate_limit.py` | ~58 | Blocking rate limit gate |
| `hooks/gates/gate_12_plan_mode_save.py` | ~44 | Advisory plan save gate |
| `hooks/auto_approve.py` | ~127 | PermissionRequest deny-before-allow |
| `hooks/subagent_context.py` | ~87 | SubagentStart context injection |
| `hooks/pre_compact.py` | ~91 | PreCompact state snapshots |
| `hooks/session_end.py` | ~92 | SessionEnd queue flush + counter |
| `hooks/statusline.py` | ~80 | Status line display |
| `agents/researcher.md` | ~25 | Read-only exploration agent (haiku) |
| `agents/auditor.md` | ~25 | Security review agent (sonnet) |
| `agents/builder.md` | ~25 | Full implementation agent (opus) |
| `agents/stress-tester.md` | ~25 | Testing agent (sonnet) |

## Key Memory IDs
- `3aee79491823bbad` — Framework v2.0 complete summary
- `d5a8c73bd530d041` — Sprint 3 completion details
- `210095f8ca4fd631` — Sprint 2 completion details
