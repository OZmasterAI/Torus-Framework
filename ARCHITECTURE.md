# Torus Framework — Architecture Document

**Version:** v2.5.1
**Location:** `~/.claude/`
**Last updated:** 2026-02-20 (Session 163)

---

## Table of Contents

1. [Overview](#overview)
2. [Design Philosophy](#design-philosophy)
3. [Directory Structure](#directory-structure)
4. [Core Pipeline](#core-pipeline)
5. [Session Lifecycle](#session-lifecycle)
6. [Gate System](#gate-system)
7. [Memory System](#memory-system)
8. [Shared Libraries](#shared-libraries)
9. [Agent Delegation](#agent-delegation)
10. [Integrations](#integrations)
11. [Skill System](#skill-system)
12. [Performance Layer](#performance-layer)
13. [Configuration](#configuration)
14. [Data Flow Diagram](#data-flow-diagram)

---

## Overview

Torus is a **self-healing AI development environment** layered on top of Claude Code. It wraps every tool call Claude makes with a gate enforcement pipeline, maintains a persistent cross-session memory corpus, and manages the full session lifecycle from boot to wrap-up.

The framework is not a separate application — it runs entirely through Claude Code's hook system. Hooks fire on events (PreToolUse, PostToolUse, SessionStart, etc.), enforce quality gates, track state, and feed a ChromaDB memory store. Claude Code itself never needs modification.

**Key numbers (Session 163):**
- 16 active gates (1 dormant — Gate 8 only)
- 857 curated memories, 5,635+ observations
- 1,113 tests passing, 3 failing (pre-existing)
- 28+ slash-command skills
- 8 custom agent types
- 9 enabled plugins (3 LSP + 6 workflow)
- Agent teams enabled
- 163 sessions over the project lifetime

---

## Design Philosophy

### 1. Mechanical enforcement over behavioral instruction
Rules in CLAUDE.md are injected as instructions, but instructions can be reasoned around. The gate system uses `sys.exit(2)` (Claude Code's mechanical block exit code) to enforce critical rules at the tool call level — no reasoning escape.

### 2. Fail-closed for safety, fail-open for quality
Tier 1 gates (1–3): if the gate crashes, the tool call is blocked. Gate 11 (Rate Limit) uses a Tier 1* designation — it blocks when firing normally but fails-open on crash. This is the safe default for destructive operations.
Tier 2+ gates: if the gate crashes, the tool call proceeds with a warning logged. Quality enforcement should not block work indefinitely.

### 3. Per-session state isolation
Each Claude session (main + any concurrent agent) gets its own state file keyed by `session_id`. Gate counters, file reads, and verification status cannot bleed across parallel agents.

### 4. Memory-first workflow
Every fix, decision, and discovery is saved to ChromaDB. At session start, the boot sequence queries relevant memories and injects them as context. Gate 4 enforces this within sessions (memory must be queried before editing). The result is a corpus that compounds across sessions.

### 5. Causal fix tracking
Errors are fingerprinted (variable parts stripped, FNV-1a hashed), fix strategies recorded on attempt, and outcomes captured on resolution. Gate 9 bans strategies that have failed 3+ times. Gate 15 blocks edits after test failure until fix history has been consulted.

### 6. Hot I/O on ramdisk
Audit logs, state files, and the capture queue are written to a systemd tmpfs (`/run/user/{uid}/claude-hooks`) — ~544 MB/s vs ~1.2 MB/s on disk. Audit writes are mirrored to disk asynchronously. State and capture queue are ephemeral (session-scoped).

---

## Directory Structure

```
~/.claude/
├── CLAUDE.md               # Master instructions, injected into every prompt (~1,321 tokens)
├── ARCHITECTURE.md         # This document
├── HANDOFF.md              # Session handoff: what was done, what's next
├── LIVE_STATE.json         # Machine-readable project state
├── settings.json           # Claude Code hook registrations + model defaults
├── mcp.json                # MCP server config → hooks/memory_server.py
│
├── hooks/                  # Core framework engine
│   ├── enforcer.py         # Central PreToolUse gate dispatcher (407 lines)
│   ├── tracker.py          # PostToolUse state tracker (773 lines)
│   ├── boot.py             # SessionStart boot sequence (779 lines)
│   ├── session_end.py      # SessionEnd handler + auto wrap-up (531 lines)
│   ├── memory_server.py    # ChromaDB MCP server + UDS gateway (3,942 lines)
│   ├── statusline.py       # Live telemetry renderer (847 lines)
│   ├── auto_commit.py      # Stage-on-edit + batch-commit-on-prompt (99 lines)
│   ├── auto_approve.py     # PermissionRequest deny-before-allow (136 lines)
│   ├── user_prompt_capture.py  # Correction/feature signal detection (160 lines)
│   ├── subagent_context.py # SubagentStart context injection (316 lines)
│   ├── pre_compact.py      # PreCompact enriched state snapshot (232 lines) (captures: tool_call_count, files_read, pending/verified counts, error_pattern_counts, pending_chain_ids, active_bans, gate6_warn_count, error_windows, tool_stats, edit_streak)
│   ├── event_logger.py     # SubagentStop/Notification/etc. logging (298 lines)
│   ├── test_framework.py   # Full test suite — 1,086 tests (10,302 lines)
│   ├── setup_ramdisk.sh    # Mount tmpfs at /run/user/{uid}/claude-hooks
│   │
│   ├── gates/              # 16 gate modules
│   │   ├── gate_01_read_before_edit.py
│   │   ├── gate_02_no_destroy.py
│   │   ├── gate_03_test_before_deploy.py
│   │   ├── gate_04_memory_first.py
│   │   ├── gate_05_proof_before_fixed.py
│   │   ├── gate_06_save_fix.py
│   │   ├── gate_07_critical_file_guard.py
│   │   ├── gate_08_temporal.py         # DORMANT
│   │   ├── gate_09_strategy_ban.py
│   │   ├── gate_10_model_enforcement.py
│   │   ├── gate_11_rate_limit.py
│   │   ├── gate_13_workspace_isolation.py
│   │   ├── gate_14_confidence_check.py
│   │   ├── gate_15_causal_chain.py
│   │   └── gate_16_code_quality.py
│   │
│   ├── shared/             # Shared libraries
│   │   ├── gate_result.py
│   │   ├── state.py
│   │   ├── audit_log.py
│   │   ├── error_normalizer.py
│   │   ├── observation.py
│   │   ├── secrets_filter.py
│   │   ├── chromadb_socket.py
│   │   └── ramdisk.py
│   │
│   ├── audit/              # Daily JSONL audit logs (rotated, compressed, 90-day retention)
│   ├── .disk_backup/       # Disk mirror of ramdisk audit logs
│   ├── state_{id}.json     # Per-agent gate enforcement state (ephemeral)
│   ├── .capture_queue.jsonl    # Pending ChromaDB observations
│   ├── .auto_remember_queue.jsonl
│   ├── .memory_last_queried    # Gate 4 sideband timestamp
│   ├── .file_claims.json       # Gate 13 cross-agent file locks
│   ├── .chromadb.sock          # UDS for hook→ChromaDB IPC
│   └── chroma.sqlite3          # ChromaDB persistent store
│
├── agents/                 # Agent persona configs (8 types)
│   ├── builder.md          # Opus — full implementation + causal chain
│   ├── auditor.md          # Sonnet — security review
│   ├── researcher.md       # Haiku — read-only exploration (cost-effective)
│   ├── stress-tester.md    # Sonnet — test suites
│   ├── code-reviewer.md    # Sonnet — code quality review + confidence scoring
│   ├── performance-analyzer.md  # Sonnet — bottleneck detection
│   ├── explorer.md         # Haiku — fast codebase exploration
│   └── test-writer.md      # Sonnet — test generation
│
├── integrations/
│   ├── telegram-bot/       # Telegram ↔ Claude Code bridge
│   └── terminal-history/   # Session JSONL → SQLite FTS5 indexer
│
├── skills/                 # 28+ slash-command skills (SKILL.md + optional scripts/)
├── plugins/                # 9 plugins (3 LSP + 6 workflow: feature-dev, pr-review-toolkit, code-review, hookify, skill-creator, code-simplifier)
├── rules/                  # Domain CLAUDE.md extensions
│   ├── framework.md
│   ├── hooks.md
│   └── memory.md
├── modes/                  # Named operating modes (coding, docs, debug, review) + modes/skill/SKILL.md (/mode skill)
├── teams/                  # Agent team configs with inbox-based IPC. Active: default/, eclipse-rebase/, framework-v2-4-1/ (4 agents)
├── PRPs/                   # /loop orchestrator runtime: task_manager.py, active task state, test-workspace, PRP templates
├── plans/                  # Ad-hoc planning docs
├── dashboard/              # Web dashboard server (port 7777)
└── archive/                # Archived HANDOFF files
```

---

## Core Pipeline

Every tool call Claude makes passes through this pipeline:

```
Claude decides to call a tool
         │
         ▼
  PreToolUse event fires
         │
         ▼
  enforcer.py receives JSON on stdin
  {session_id, tool_name, tool_input}
         │
         ├─ load_state(session_id)       ← per-agent state
         ├─ hot-reload gates if changed  ← file mtime check every 30s
         │
         ▼
  Run gates in order (1 → 16):
  ┌─────────────────────────────────┐
  │ gate.check(tool, input, state)  │
  │  → GateResult(blocked, msg, …)  │
  └─────────────────────────────────┘
  If blocked: sys.exit(2)  → tool call cancelled, message shown to Claude
  If warned:  continue, log warning
  If passed:  continue
         │
         ▼
  Tool executes
         │
         ▼
  PostToolUse event fires → tracker.py
  ├─ Track file reads (Gate 1 state)
  ├─ Track memory queries (Gate 4 sideband)
  ├─ Track test runs + exit codes (Gate 3, 5, 15 state)
  ├─ Track edits + verification status (Gate 5, 14 state)
  ├─ Detect errors in Bash output
  ├─ Auto-capture observations → .capture_queue.jsonl
  └─ Stage file for auto-commit (Edit/Write only)
```

**Auto-remember queue** (`.auto_remember_queue.jsonl`): rate-limited to 10 saves/session. Four triggers:
- Tests passed → queued
- Git commit detected → queued
- Error fix verified → immediate UDS write (critical=True)
- Heavy edit session (3+ edits same file) → queued
Consumed by boot.py on next SessionStart via atomic move-then-read protocol.

**Verification scoring:** Bash commands accumulate progressive confidence scores (10/30/50/70/100) per-file in `verification_scores`. Files reaching threshold 70 graduate from `pending_verification` to `verified_fixes`.

**Gate 13 claims:** tracker.py writes `.file_claims.json` on Edit/Write/NotebookEdit. Gate 13 only reads claims — it does not write them.

**Gate contract:** Every gate module exports `check(tool_name, tool_input, state, event_type) → GateResult`. Import via `from shared.gate_result import GateResult`. Never construct dicts.

**Exit codes:**
- `sys.exit(0)` — allow
- `sys.exit(2)` — block (only valid PreToolUse)
- `sys.exit(1)` — non-blocking error (tool proceeds, error logged)

---

## Session Lifecycle

```
Session opens
      │
      ▼
boot.py (SessionStart, 15s timeout)
  1. Read HANDOFF.md + LIVE_STATE.json
  2. Query memory for session context (satisfies Gate 4)
  3. Display session dashboard (number, status, next steps)
  4. Reset per-session enforcement state
  4b. ChromaDB watchdog — compares chroma.sqlite3 size vs backup; warns if < 1KB or < 80% of backup size
  5. Flush stale .capture_queue.jsonl → ChromaDB observations
  6. Flush .auto_remember_queue.jsonl → memory
  7. Auto-start dashboard server if not running (port 7777)
  8. Call on_session_start.py (telegram-bot hook, 10s timeout) — injects up to 3 TG results into dashboard
      │
      ▼
Active session
  ├─ enforcer.py fires on every PreToolUse
  ├─ tracker.py fires on every PostToolUse
  ├─ auto_commit.py stages edits (PostToolUse) + commits batches (UserPromptSubmit)
  ├─ user_prompt_capture.py detects correction signals (UserPromptSubmit)
  ├─ subagent_context.py injects context for each sub-agent (SubagentStart)
  └─ event_logger.py handles SubagentStop, Notifications, etc.
      │
      ▼
Session closes
      │
      ▼
session_end.py (SessionEnd, 30s timeout)
  1. Compute session metrics (tool call counts, files modified, errors)
  2. If /wrap-up was not run manually:
     → Auto wrap-up via Haiku: generates HANDOFF.md update + LIVE_STATE.json update
     If /wrap-up RAN within last 5 minutes (HANDOFF.md mtime check): only appends ## Session Metrics block.
     Full Haiku summarisation (from last 40 transcript turns) only fires when wrap-up was NOT run.
  3. Flush .capture_queue.jsonl → ChromaDB observations
  3b. Send UDS backup command → snapshot chroma.sqlite3 to backup file
  3c. Archive existing HANDOFF.md → archive/HANDOFF_YYYY-MM-DD_auto.md
  3d. Call on_session_end.py for telegram-bot and terminal-history (subprocess, 15s timeout each)
  4. Increment session_count in LIVE_STATE.json
  5. Compress completed audit day logs
```

**UserPromptSubmit auto-commit flow:**
```
Edit/Write fires → auto_commit.py stages: git add <file>
UserPromptSubmit fires → auto_commit.py commits: git commit -m "auto: update <files>"
Result: one tidy commit per user message, not one per edit
```

---

## Gate System

### Gate Table

| # | Name | Tier | Status | Watched Tools | Action |
|---|------|------|--------|---------------|--------|
| 1 | Read Before Edit | Tier 1 Safety | ACTIVE | Edit, Write, NotebookEdit | Block edits to code files unless Read first this session. Extensions: .py .js .ts .jsx .tsx .rs .go .java .c .cpp .rb .php .sh .sql .tf .ipynb. Exemptions: CLAUDE.md, HANDOFF.md, state.json, new files. Related-read: reading test_foo.py satisfies editing foo.py (stem matching). |
| 2 | No Destroy | Tier 1 Safety | ACTIVE | Bash | 28 patterns incl. eval, bash -c, pipe-to-shell, fork bombs. SAFE_EXCEPTIONS with regex overrides. shlex-based parsing for split flags. |
| 3 | Test Before Deploy | Tier 1 Safety | ACTIVE | Bash | No tests in 30min OR last test exit code non-zero = block. 28 deploy patterns. |
| 4 | Memory First | Tier 2 | ACTIVE | Edit, Write, NotebookEdit, Task | Block edits if memory not queried in last 5 minutes |
| 5 | Proof Before Fixed | Tier 2 | ACTIVE | Edit, Write, NotebookEdit | Cross-file: block if effective_unverified >= 3 (partial verification = 0.5 weight). Same-file: warn at 4th edit, block at 6th. Test files exempt. |
| 6 | Save Verified Fix | Tier 2 Advisory | ACTIVE | Edit, Write, Task, Bash | Advisory. WARN_THRESHOLD=2. 20-min stale decay. Also warns: unlogged errors, repair loop (3x same pattern in 10min), edit churn (3+ edits to same file). |
| 7 | Critical File Guard | Tier 3 | ACTIVE | Edit, Write, NotebookEdit | High-risk files (auth, payments, .env, CI/CD, nginx) need recent memory query |
| 8 | Temporal Awareness | Tier 3 | DORMANT | Edit, Write, NotebookEdit | High-risk hours (1–5 AM) + long session (>3h) warnings |
| 9 | Strategy Ban | Tier 2 | ACTIVE | Edit, Write, NotebookEdit | Ban at 3 failures (4 if strategy had prior success — success bonus). Warns at 1st failure. |
| 10 | Model Cost Guard | Tier 2 | ACTIVE | Task | Explicit model required. Mismatch warning suppressed after 3 uses of same agent_type:model pair. 10 agent types mapped. |
| 11 | Rate Limit | Tier 1* | ACTIVE | All | >60/min block, >40/min warn (120s rolling average, not burst). Internal save_state() call. |
| 12 | Plan Mode Save | Tier 2 Advisory | ACTIVE | Edit, Write, Bash, NotebookEdit | Warn (escalate to block after 3x) when plan mode exited without saving to memory |
| 13 | Workspace Isolation | Tier 2 | ACTIVE | Edit, Write, NotebookEdit | Cross-agent lock via .file_claims.json. Gate reads claims only — tracker.py writes them. 'main' session ID is sole exemption (literal string check). |
| 14 | Confidence Check | Tier 2 | ACTIVE | Edit, Write, NotebookEdit | Warn 2x per file, block on 3rd. Signal 3 (memory freshness) dormant. Session-wide signal dedup prevents repeat warnings. State key: confidence_warnings_per_file. |
| 15 | Causal Chain | Tier 2 | ACTIVE | Edit, Write, NotebookEdit | Requires BOTH recent_test_failure=True AND fixing_error=True. skills/ dir exempt. |
| 16 | Code Quality | Tier 2 Advisory | ACTIVE | Edit, Write, NotebookEdit | Advisory. Scans only new_string/diff, not full file. Only .py .js .ts .tsx .jsx .go .rs .java .rb .sh extensions. Clean edit resets counter. todo-fixme never escalates counter. |

*Gate 11 blocks mechanically (exit 2) when the rate limit is exceeded, but fails-open (exit 0) on internal crash — making it Tier 1 in behavior but not in crash safety.*

### Adding a new gate

1. Create `hooks/gates/gate_NN_name.py` with a `check()` function returning `GateResult`
2. Add entry to `GATE_MODULES` list in `enforcer.py`
3. Add to `GATE_TOOL_MAP` in `enforcer.py`
4. Add state reads/writes to `GATE_STATE_DEPS` if needed
5. Write tests in `test_framework.py` (both block and allow paths)
6. Add state defaults to `shared/state.py:default_state()` if new state fields added

### Dormanting a gate

Comment out the entry in `GATE_MODULES` in `enforcer.py`. The gate file stays in place; the comment should note re-enable instructions. Example: Gate 8.

### Enforcer internals

**Always-allowed tools (bypass all gates):**
`Read`, `Glob`, `Grep`, `WebFetch`, `WebSearch`, `AskUserQuestion`, `EnterPlanMode`, `ExitPlanMode`, `TaskCreate`, `TaskUpdate`, `TaskList`, `TaskGet`, `TeamCreate`, `TeamDelete`, `SendMessage`, `TaskStop`, and all MCP memory tools (prefixed `mcp__memory__` or `mcp_memory_`).

**Hot-reload:** Gate modules check file mtimes, but since enforcer.py is re-invoked per tool call (not a daemon), the 30s throttle resets each invocation — effectively every call checks mtimes.

**State saved after every gate run** (not just on block) because Gate 11 writes state internally and timing stats must be persisted. `gate_block_counts` tracked per-gate in state.

---

## Memory System

### Architecture

```
Claude Code session
      │
      │ MCP tool calls (search_knowledge, remember_this, etc.)
      ▼
memory_server.py (MCP server process)
      │
      ├─ knowledge collection    (curated, 619 entries)
      ├─ observations collection (auto-captured, 5,635 entries)
      ├─ fix_outcomes collection (causal chain records)
      ├─ quarantine collection   (deduplication targets)
      └─ web_pages collection    (/web skill index)
      │
      │ UDS socket (.chromadb.sock)
      ▼
hooks/ (enforcer, tracker, boot, session_end)
      │ read/write without spawning new processes
      ▼
chroma.sqlite3 (ChromaDB persistent store)
```

**Why UDS?** ChromaDB's Rust backend segfaults under concurrent process access. The UDS gateway runs as a single thread inside memory_server.py, serializing all hook-side reads/writes.

### MCP Tools

| Tool | Purpose |
|------|---------|
| `search_knowledge(query, top_k, mode, recency_weight, match_all)` | Semantic/keyword/hybrid/tag search. Auto-detects mode. |
| `remember_this(content, context, tags, force)` | Save memory. 3-way write: ChromaDB knowledge + FTS5 dual-write (sequential, not atomic) + fix_outcomes bridge (auto-triggered on `type:fix` tag). Noise filter (12 patterns) runs before dedup. Dedup uses SHA-256 ID: hard threshold (cosine < 0.10) silently rejects; soft zone (0.10–0.15) saves with `possible-dupe:` tag on new entry; `type:fix` uses stricter 0.03 threshold. Also performs bidirectional link creation via `resolves:` tags and citation extraction (`[source: URL]`). Retrieval count incremented on every search/get. |
| `get_memory(id)` | Fetch full memory by ID. Supports comma-separated batch. |
| `deduplicate_sweep(dry_run, threshold)` | Find and quarantine near-duplicate memories by cosine distance. |
| `record_attempt(error_text, strategy_id)` | Causal chain: log a fix attempt → returns `chain_id`. |
| `record_outcome(chain_id, outcome)` | Causal chain: log "success" or "failure" for an attempt. |
| `query_fix_history(error_text, top_k)` | Search fix_outcomes for strategies tried on similar errors. Also resets Gate 15 state. |
| `maintenance(action, ...)` | `promotions`, `stale`, `cluster`, `health`, `rebuild_tags`. |

### Search pipeline internals (search_knowledge)

Beyond the mode-routing described above, every `search_knowledge` call runs:
1. **Query alias expansion** — `torus` ↔ `megaman` auto-appended if only one present
2. **Tag co-occurrence expansion** — co-occurrence matrix (40% threshold) finds related tags; runs additional FTS5 tag search and terminal L2 tag search to augment results
3. **Keyword overlap reranker** — post-hoc boost (`+0.05 × matched_terms/total`) applied to all results regardless of mode
4. **Recency boost** — `raw + recency_weight × max(0, 1 - age_days/365)` (365-day decay)
5. **Observations search** — called in 4 contexts: `mode="observations"` (early return), `mode="all"` (1/3 budget), auto-fallback (0 knowledge results), `query_fix_history` fallback. Every call flushes the capture queue first.
6. **Linked memory fetch** — `resolves:`/`resolved_by:` tags and terminal L2 `linked_memory_ids` are batch-fetched from ChromaDB and appended (bypasses top_k cap)
7. **Observation compaction** — triggered inside observations flush: TTL digests (30-day) → knowledge collection; promotion of standalone errors/file churn/repeated commands; hard cap at 5000 (oldest deleted, no digest)

**Dormant MCP tools** (decorator removed, code present): `timeline`, `get_teammate_context`. Removed in session 183: `get_recent_activity`, `search_observations`, `get_session_sentiment`, `get_observation` (all strictly superseded by `search_knowledge` modes).

**Undocumented maintenance action:** `batch_rename` — bulk replaces "megaman"→"torus" across all memory content and tags; force-rebuilds FTS5 index.

### Memory tag conventions

```
type:    error | learning | fix | feature-request | correction | decision | auto-captured | preference
priority: critical | high | medium | low
area:    frontend | backend | infra | framework | testing | docs | git
outcome: success | failed
```

### Auto-capture pipeline

```
tracker.py PostToolUse
      │
      ├─ observation.py: tool call → compact text summary
      │   ├─ Bash: detects 30+ error patterns, captures stdout/exit code
      │   ├─ Edit/Write: records file + change summary
      │   └─ memory tools: records query/save events
      │
      ├─ secrets_filter.py: scrub before storage
      │
      └─ .capture_queue.jsonl: queue for batch ingest
            │
            ▼ (on SessionStart or SessionEnd)
      boot.py / session_end.py flush → ChromaDB observations collection
```

**Capturable tools:** Bash, Edit, Write, NotebookEdit, Read, Glob, Grep, Skill, WebSearch, WebFetch, Task, UserPrompt — all produce observations. Sentiment detection (frustration/confidence/exploration) and priority scoring (high/medium/low) are stored as metadata. Observation IDs use SHA-256 (not FNV-1a). Near-duplicate filtering checks last 20 queue entries before writing. Queue is capped at 500 lines every 50 tool calls (priority-aware: high-priority entries preserved first).

---

## Shared Libraries

| Module | Purpose |
|--------|---------|
| `gate_result.py` | `GateResult` dataclass: `blocked`, `message`, `gate_name`, `severity`, `duration_ms`, `metadata` |
| `state.py` | Atomic JSON state with `fcntl.flock`, per-agent isolation, schema v3, auto-migration v1→v2→v3, `default_state()` |
| `audit_log.py` | JSONL audit trail: rotate at 5MB using numbered chain (`.1` → `.1.gz` → `.10.gz`). Compressed archives written to disk backup only. Deletion is currently DORMANT (`_AUDIT_DELETE_ENABLED = False`). Also provides: `compact_audit_logs()` → daily summary.json; `get_block_summary(hours)` → blocked decisions by gate/tool; `get_recent_gate_activity(gate_name, minutes)` → pass/block/warn counts. |
| `error_normalizer.py` | Strip paths/UUIDs/timestamps/ports/addresses → stable FNV-1a fingerprint |
| `observation.py` | Tool call → compact ChromaDB summary; 28 error pattern detectors; observation IDs use SHA-256; sentiment detection (frustration/confidence/exploration); priority scoring (high/medium/low); context metadata dict per tool type |
| `secrets_filter.py` | Regex redaction (12 patterns, order matters — specific before generic): private keys, JWTs, Bearer tokens, AWS keys, GitHub tokens (ghp_/gho_/ghs_), SSH keys, Slack tokens (xoxb-/xoxp-), Anthropic API keys (sk-ant-), generic sk- keys, connection strings (mongodb/postgresql/redis/mysql/amqp), env var assignments (API_KEY/SECRET/TOKEN/etc.), long hex/base64 catch-all |
| `chromadb_socket.py` | UDS client for hook→ChromaDB. Operations: `ping`, `count`, `query`, `get`, `upsert`, `delete`, `auto_remember`, `flush_queue`, `backup`. 5s timeout. 3-retry backoff applies only to `is_worker_available()` — `request()` raises `WorkerUnavailable` immediately on failure. 10MB response cap. One-connection-per-request (no pooling). |
| `ramdisk.py` | tmpfs I/O layer: moves hot files to `/run/user/{uid}/claude-hooks`. Async disk mirror thread for audit logs. Graceful disk fallback. |

### State schema (v3) — key fields

```python
{
  # Gate 1: Read Before Edit
  "files_read": [],               # files Read this session

  # Gate 3: Test Before Deploy
  "last_test_run": 0,             # epoch timestamp
  "last_test_exit_code": None,    # also blocks Gate 3 if non-zero (failed tests)

  # Gate 4: Memory First
  "memory_last_queried": 0,       # epoch (also in sideband file)

  # Gate 5: Proof Before Fixed
  "pending_verification": [],     # files edited but not yet verified
  "verified_fixes": [],           # list of verified file paths (NOT an integer)
  "verification_scores": {},      # progressive per-file confidence score (0-100)

  # Gate 6: Save Verified Fix
  "unlogged_errors": [],          # errors detected but not yet saved to memory
  "error_pattern_counts": {},     # per-pattern error frequency
  "gate6_warn_count": 0,          # escalation counter (blocks on 5th warning)

  # Gate 9: Strategy Ban
  "current_strategy_id": None,
  "active_bans": [],              # banned strategy IDs (or dict with fail metadata)
  "successful_strategies": {},    # strategy success counts (success bonus: +1 retry threshold)

  # Gate 11: Rate Limit
  "rate_window_timestamps": [],   # rolling 120s window (NOT tool_call_timestamps)

  # Gate 12: Plan Mode Save
  "last_exit_plan_mode": 0,       # epoch timestamp

  # Gate 14: Confidence Check
  "confidence_warnings_per_file": {},  # per-file warning counts (NOT confidence_warnings)

  # Gate 15: Causal Chain
  "fix_history_queried": 0,       # epoch timestamp
  "recent_test_failure": False,   # test failure flag
  "fixing_error": False,          # ALSO required for Gate 15 to fire

  # Gate 16: Code Quality
  "code_quality_warnings_per_file": {},  # per-file warning counter

  # Causal fix chain
  "pending_chain_ids": [],
  "current_error_signature": "",

  # Subagent tracking
  "active_subagents": [],         # [{agent_id, agent_type, transcript_path, start_ts}]
  "subagent_total_tokens": 0,     # cumulative completed subagent tokens

  # Session metrics
  "tool_call_count": 0,
  "tool_stats": {},               # per-tool call stats
  "edit_streak": {},              # consecutive edits per file
  "session_start": 0,             # epoch (NOT session_start_time)

  # Additional fields
  "edits_locked": False,          # emergency edit lock
  "error_windows": [],            # windowed error tracking for velocity
  "skill_usage": {},              # skill invocation tracking
  "gate_block_counts": {},        # per-gate block counts
  "session_test_baseline": False, # has any test run this session (Gate 14)
}
```

**State rules:**
- New fields always go in `default_state()` with sensible defaults
- Read via `.get(key, default)` — never assume key exists
- State is per-session; team agents do not share state
- Never rename existing fields without a migration path

**State cap constants:** `MAX_FILES_READ=200`, `MAX_VERIFIED_FIXES=100`, `MAX_PENDING_VERIFICATION=50`, `MAX_UNLOGGED_ERRORS=20`, `MAX_ERROR_PATTERNS=50`, `MAX_ACTIVE_BANS=50`. These are enforced by `_validate_consistency()` on every state load, which also deduplicates list fields and ensures `pending_verification` and `verified_fixes` are disjoint.

---

## Agent Delegation

### Agent types

| Agent | Model | Tools | Use case |
|-------|-------|-------|----------|
| `builder` | opus | Read, Glob, Grep, Edit, Write, Bash, NotebookEdit + full memory tools incl. causal chain | Feature implementation, bug fixes, refactoring |
| `auditor` | sonnet | Read, Glob, Grep, Bash + search/get/remember memory tools | Security review, OWASP audit, credential scanning |
| `researcher` | haiku | Read, Glob, Grep, WebFetch, WebSearch + search/get memory tools | Codebase exploration, documentation lookup, research |
| `stress-tester` | sonnet | Read, Glob, Grep, Bash + search/get/remember/causal chain memory tools | Test suite execution, edge case hunting, benchmarking |
| `code-reviewer` | sonnet | Read, Glob, Grep, Bash + search/get/remember memory tools | Code quality review with confidence scoring (Bug/Quality/Convention/Security) |
| `performance-analyzer` | sonnet | Read, Glob, Grep, Bash + search/get/remember memory tools | Bottleneck detection: N+1 queries, O(n^2), memory leaks |
| `explorer` | haiku | Read, Glob, Grep + search/get memory tools | Fast codebase mapping, call chain tracing (no Bash, no Write) |
| `test-writer` | sonnet | Read, Glob, Grep, Write, Bash + search/get/remember memory tools | Test generation matching project conventions |

### Delegation rules (from CLAUDE.md)

```
2–5 steps, independent        → Sub-agents (parallel)
2–5 steps, dependent          → Sub-agents (lead orchestrates, memory bridges)
5–7 steps                     → Either (teams preferred)
7+ steps                      → Agent teams (real-time coordination)
Cross-session                 → Sub-agents + memory
```

### SubagentStart injection

`subagent_context.py` fires on every SubagentStart event. It reads:
- Agent type from stdin
- `LIVE_STATE.json` for project context
- Current session state for active work

It outputs tailored context so the sub-agent starts with full situational awareness. Edit/Write agents receive safety rules. Researchers receive read-only advisories.

### Gate 10: Model Cost Guard

Every Task tool call must include an explicit `model` parameter:
- `haiku` — research, search, read-only exploration
- `sonnet` — analysis, testing, moderate complexity
- `opus` — complex implementation, architectural decisions

Gate 10 blocks Task calls without a model param and warns on apparent mismatches (e.g. opus for a read-only Explore agent).

---

## Integrations

### Telegram Bot (`integrations/telegram-bot/`)

Bridges Telegram messages to Claude Code sessions. The user sends messages via Telegram; the bot routes them to an active Claude session and returns the response.

**Components:**
- `bot.py` — python-telegram-bot v21, long-polling loop
- `tmux_runner.py` — routes via `claude-bot` tmux session (active, 3.5s response time)
- `claude_runner.py` — alternative: `claude -p --resume <session_id>` direct invocation
- `db.py` — SQLite FTS5 for message history
- `sessions.py` — session ID persistence
- `config.py` — configuration loader
- `search.py` — standalone FTS5 search
- `hooks/on_session_start.py` / `on_session_end.py` — called by boot.py and session_end.py as subprocesses (10-15s timeout)
- `tests/` — test suite

**Routing mode:** controlled by `LIVE_STATE.json: tg_bot_tmux` boolean toggle (not config.json). Switches between tmux and subprocess mode per-message at runtime. `config.json` supplies the `tmux_target` value when tmux mode is active. Actual response timeout: `config.json: claude_timeout` (default 120s, not 3.5s). The shared-session mode causes interference; dedicated `claude-bot` tmux target is required.

**Known issue:** tmux pane dump bug — fixed by baseline diffing to extract only new output. Full scrollback capture causes copy-paste of entire pane history.

### Terminal History (`integrations/terminal-history/`)

Indexes all Claude Code JSONL session files into a SQLite FTS5 database for full-text search across session history.

- `indexer.py` — bulk JSONL parser, FTS5 ingest, mirrors to `~/data/memory/fts5_index.db`. Implements **inherit+derive tagging**: inherits tags from ChromaDB memories that overlap in time with the session, derives additional tags from keyword patterns in text. Creates `linked_memory_ids` field linking terminal records to ChromaDB knowledge IDs.
- `db.py` — schema, FTS5 init, `search()`, `search_by_tags()`, `get_context_by_timestamp()` (retrieves surrounding conversation context in ±30min window)
- `terminal_history.db` — live index (~6.8 MB)

---

## Skill System

28+ slash-command skills defined as `SKILL.md` instruction files in `skills/`. Invoked via `/skill-name`. Composable via `/chain`.

| Skill | Purpose |
|-------|---------|
| `/analyze-errors` | Historical error pattern analysis, prevention playbooks |
| `/audit` | 3-agent security + quality audit team |
| `/benchmark` | Framework performance metrics: tests, memory, gates, hook latencies |
| `/build` | Full quality loop: memory → tests → implement → verify → commit |
| `/chain` | Compose skills into sequential pipelines |
| `/commit` | Quick git commit with auto-generated message |
| `/deep-dive` | Broad memory context retrieval (top_k=50, multi-mode) |
| `/deploy` | Deployment workflow with Gate 3 enforcement |
| `/diagnose` | Gate effectiveness analysis: fire rates, timing, recommendations |
| `/document` | Auto-generate docstrings, README, API docs, architecture, changelog |
| `/explore` | Interactive codebase deep-dive |
| `/fix` | Auto-diagnose and fix: memory → context → causal chain → fix → verify |
| `/learn` | Learn from external sources: GATHER→ANALYZE→CROSS-REFERENCE→SYNTHESIZE→INTEGRATE→REMEMBER→TEACH |
| `/loop` | Torus Loop Orchestrator: runs PRP tasks via fresh Claude instances |
| `/super-prof-optimize` | Performance profiling + optimization (merged from /profile + /optimize) |
| `/prp` | Generate/list/view Product Requirements Prompts |
| `/ralph` | Autonomous loop: up to 10 build-verify cycles with circuit breakers |
| `/refactor` | Safe incremental refactoring |
| `/research` | Structured research with memory integration (quick/standard/deep/exhaustive tiers) |
| `/review` | Code quality and convention check |
| `/status` | Live project status report (uses `gather.py`) |
| `/super-evolve` | Ultimate self-evolution: merged /evolve + /self-improve (scan, research, execute, validate) |
| `/super-health` | Comprehensive diagnostics: merged /health + /health-report + /status (quick→deep→report) |
| `/test` | Run, write, and debug test suites |
| `/wave` | Torus Wave Orchestrator: parallel PRP task execution with file-overlap guard |
| `/web` | Web content management: index, search, list, delete |
| `/wrap-up` | Session end protocol: metrics → memory → HANDOFF.md → LIVE_STATE.json |
| `/browser` | Visual verification via agent-browser; screenshot-based UI testing |

---

## Performance Layer

### Ramdisk

Hot I/O files moved to `/run/user/{uid}/claude-hooks` (systemd tmpfs):

| File type | Ramdisk path | Disk backup |
|-----------|-------------|-------------|
| Audit logs (hot) | `/run/user/{uid}/claude-hooks/audit/YYYY-MM-DD.jsonl` | `hooks/.disk_backup/audit/` (async mirror — tmpfs write is synchronous, disk is async) |
| State files | `/run/user/{uid}/claude-hooks/state/state_{id}.json` | None (ephemeral) |
| Capture queue | `/run/user/{uid}/claude-hooks/capture_queue.jsonl` (no leading dot) | None (ephemeral) |

Throughput: ~544 MB/s ramdisk vs ~1.2 MB/s disk. The async mirror thread writes audit data to disk after every ramdisk write — zero data loss at full ramdisk speed.

On `ensure_ramdisk()`: creates 3 directories and calls `restore_from_backup()` (no-clobber restore of `.jsonl` files from disk backup). Availability check is cached per-process. `sync_to_backup()` available for systemd shutdown hooks. `ramdisk.py` is also a CLI tool: `python ramdisk.py sync|setup`.

Fallback: if tmpfs unavailable, all paths fall back to `hooks/` directory on disk.

### Gate hot-reload

`enforcer.py` checks gate file mtimes every 30 seconds. Modified gate files are reimported without restarting the hook process. Allows live gate development without hook restart.

### ChromaDB UDS gateway

Memory server runs a Unix Domain Socket thread at `.chromadb.sock`. All hook-side ChromaDB access goes through this socket — no subprocess spawning, no concurrent Rust backend access, no segfaults.

Socket protocol: JSON lines. Supported operations: `query`, `count`, `remember`, `flush_queue`, `backup`. Client: `shared/chromadb_socket.py` (5s timeout, 3-retry exponential backoff).

---

## Configuration

### `settings.json` — Hook registrations

| Event | Timeout | Handler |
|-------|---------|---------|
| `PreToolUse` | 5s | `enforcer.py --event PreToolUse` |
| `PostToolUse` | 3s | `tracker.py` |
| `PostToolUse` (Edit\|Write) | 3s | `auto_commit.py stage` |
| `SessionStart` | 15s | `boot.py` |
| `SessionEnd` | 30s | `session_end.py` |
| `UserPromptSubmit` | 3s | `user_prompt_capture.py` + `auto_commit.py commit` |
| `PermissionRequest` | 3s | `auto_approve.py` |
| `SubagentStart` | 3s | `subagent_context.py` |
| `PreCompact` | 3s | `pre_compact.py` — snapshots full gate state before context compression: tool_call_count, files_read, pending/verified counts, elapsed time, error_pattern_counts, pending_chain_ids, active_bans, gate6_warn_count, error_windows, tool_stats, edit_streak → written to `.capture_queue.jsonl` so gate context survives compaction |
| `SubagentStop` | 3,000ms | `event_logger.py --event SubagentStop` |
| `PostToolUseFailure` | 3,000ms | `event_logger.py --event PostToolUseFailure` |
| `Notification` | 3,000ms | `event_logger.py --event Notification` |
| `statusLine` | — | `statusline.py` — live telemetry: gate count, memory count (stats-cache.json TTL), git branch (/tmp 10s cache), tool call rate, context window %, cost, session age/number, error pressure + velocity, verification ratio, plan mode warns, subagent token counts (active + cumulative), active mode, most used tool, ramdisk health, model color-coded (dark orange = Opus). Memory count cached in stats-cache.json (60s TTL). Compression detection (CMP:N counter via /tmp/statusline-ctx-cache). Health score: 6-dimension weighted formula (gates 25%, hooks 20%, memory 15%, skills 15%, core files 15%, error pressure 10%). Memory freshness display (elapsed minutes since last query). Note: health formula uses EXPECTED_GATES=15 and EXPECTED_SKILLS=22 internally. |

Additional settings: `model: sonnet`, `effortLevel: medium`, `skipDangerousModePermissionPrompt: true`.

**Disabled hooks** (registered but dormant): `TeammateIdle` and `TaskCompleted` → `event_logger.py` (wired but inactive).

### `mcp.json` — MCP server

```json
{
  "mcpServers": {
    "memory": {
      "command": "/usr/bin/python3",
      "args": ["/home/crab/.claude/hooks/memory_server.py"],
      "cwd": "/home/crab"
    }
  }
}
```

### `CLAUDE.md` token budget

Current: ~1,321 tokens. Hard limit: 2,000 tokens. Every line is injected into every prompt — maximize density. Domain-specific rules go in `rules/` (path-scoped) not `CLAUDE.md` (always-injected).

---

## Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        Claude Code UI                           │
│  User message → UserPromptSubmit → PreToolUse → Tool → Post…   │
└────────┬────────────────────────────────────────────────────────┘
         │ hook events (JSON on stdin)
         │
    ┌────▼────────────────────────────────────────────────┐
    │                    Hook Layer                        │
    │                                                     │
    │  SessionStart ──► boot.py                           │
    │                   ├─ queries memory (MCP)           │
    │                   ├─ flushes capture queue (UDS)    │
    │                   └─ resets state                   │
    │                                                     │
    │  PreToolUse ────► enforcer.py                       │
    │                   ├─ runs gates 1–16 in order       │
    │                   ├─ reads per-session state        │
    │                   └─ exit(2) to block               │
    │                                                     │
    │  PostToolUse ───► tracker.py                        │
    │                   ├─ updates session state          │
    │                   ├─ queues observations            │
    │                   └─ stages files for commit        │
    │                                                     │
    │  UserPromptSubmit► auto_commit.py                   │
    │                   └─ git commit staged changes      │
    │                                                     │
    │  SessionEnd ────► session_end.py                    │
    │                   ├─ flushes capture queue          │
    │                   └─ updates HANDOFF + LIVE_STATE   │
    └────────────────────────┬────────────────────────────┘
                             │
              ┌──────────────┴──────────────┐
              │                             │
    ┌─────────▼──────────┐      ┌──────────▼──────────────┐
    │   State Layer       │      │     Memory Layer         │
    │                     │      │                          │
    │ state_{id}.json     │      │ memory_server.py (MCP)   │
    │ (per-agent, tmpfs)  │      │ ├─ knowledge collection  │
    │                     │      │ ├─ observations          │
    │ .file_claims.json   │      │ ├─ fix_outcomes          │
    │ (Gate 13 locks)     │      │ └─ quarantine            │
    │                     │      │         │                │
    │ .capture_queue.jsonl│      │    UDS socket            │
    │ (pending ingestion) │      │    (.chromadb.sock)      │
    └─────────────────────┘      └──────────────────────────┘
```

---

## Known Issues & Limitations

| Issue | Status | Mitigation |
|-------|--------|-----------|
| Plan mode exit loop | Platform limitation | Behavioral rule: max 1 ExitPlanMode per turn |
| ChromaDB concurrent access | Architecture | UDS gateway serializes access; tests skip when MCP running |
| Export test_framework.py uses `_FRAMEWORK_ROOT` | Known drift | Merge changes, never copy |
| Observations at 5,635 (over 5K cap) | Monitoring | Auto-compact on next ingest |
| tmux routing shared session interference | Fixed | Dedicated `claude-bot` tmux target required |
| `session_end.py` CAPTURE_QUEUE ramdisk path | Fixed (Session 144) | Now uses `_get_capture_queue()` — ramdisk-aware resolver |
| `subagent_context.py` STATE_DIR hardcoded to disk path | Known | May miss state files when ramdisk is active |
| `get_plan_mode_warns()` reads non-existent `gate12_warn_count` | Known | Always returns 0; plan mode warn count not displayed in statusline |
| Statusline health formula uses EXPECTED_GATES=15, EXPECTED_SKILLS=22 | Known | Should be 16 gates, 28 skills — health score slightly off |
| auto_commit Co-Authored-By hardcoded to "Opus 4.6" | Known | Wrong when running on Sonnet |

---

## Changelog

### v2.5.1 — 2026-02-20 (Session 163, Self-Sprint-2)
- **6 new agent types**: code-reviewer, performance-analyzer, explorer, test-writer (+ updated researcher to haiku)
- **6 new skills**: /learn, /self-improve, /evolve, /benchmark, /diagnose, /wave (promoted from hidden; /self-improve + /evolve later merged into /super-evolve)
- **6 new plugins enabled**: feature-dev, pr-review-toolkit, code-review, hookify, skill-creator, code-simplifier
- **Comprehensive .gitignore**: covers all runtime state, databases, audit logs, pycache, lock files
- **Agent teams**: fully enabled via CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS env var
- **Research integration**: patterns from Archon, Ralphy, ClawHub, Vercel, Claude docs, 10+ GitHub repos
- **Test improvements**: 1110 → 1113 passing (fixed researcher model test)

---

*Generated by Torus Framework — Session 163*
