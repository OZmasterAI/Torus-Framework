# Torus Framework — Architecture Document

**Version:** v2.4.5
**Location:** `~/.claude/`
**Last updated:** 2026-02-19 (Session 143)

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

**Key numbers (Session 143):**
- 14 active gates (2 dormant/disabled)
- 619 curated memories, 5,635 observations
- 1,086 tests passing, 0 failing
- 23 slash-command skills
- 133 committed sessions over the project lifetime

---

## Design Philosophy

### 1. Mechanical enforcement over behavioral instruction
Rules in CLAUDE.md are injected as instructions, but instructions can be reasoned around. The gate system uses `sys.exit(2)` (Claude Code's mechanical block exit code) to enforce critical rules at the tool call level — no reasoning escape.

### 2. Fail-closed for safety, fail-open for quality
Tier 1 gates (1–3, 11): if the gate crashes, the tool call is blocked. This is the safe default for destructive operations.
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
│   ├── statusline.py       # Status line renderer (847 lines)
│   ├── auto_commit.py      # Stage-on-edit + batch-commit-on-prompt (99 lines)
│   ├── auto_approve.py     # PermissionRequest deny-before-allow (136 lines)
│   ├── user_prompt_capture.py  # Correction/feature signal detection (160 lines)
│   ├── subagent_context.py # SubagentStart context injection (316 lines)
│   ├── pre_compact.py      # PreCompact state snapshot (232 lines)
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
│   │   ├── gate_12_plan_mode_save.py
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
├── agents/                 # Agent persona configs
│   ├── builder.md          # Opus — full implementation
│   ├── auditor.md          # Sonnet — security review
│   ├── researcher.md       # Haiku — read-only exploration
│   └── stress-tester.md    # Sonnet — test suites
│
├── integrations/
│   ├── telegram-bot/       # Telegram ↔ Claude Code bridge
│   └── terminal-history/   # Session JSONL → SQLite FTS5 indexer
│
├── skills/                 # 23 slash-command skills (SKILL.md + optional scripts/)
├── plugins/                # LSP plugins (pyright, rust-analyzer, typescript)
├── rules/                  # Domain CLAUDE.md extensions
│   ├── framework.md
│   ├── hooks.md
│   └── memory.md
├── modes/                  # Named operating modes (coding, docs, debug, review)
├── teams/                  # Agent team configurations
├── PRPs/                   # Product Requirements Prompts
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
  5. Flush stale .capture_queue.jsonl → ChromaDB observations
  6. Flush .auto_remember_queue.jsonl → memory
  7. Auto-start dashboard server if not running (port 7777)
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
session_end.py (SessionEnd, 10s timeout)
  1. Compute session metrics (tool call counts, files modified, errors)
  2. If /wrap-up was not run manually:
     → Auto wrap-up via Haiku: generates HANDOFF.md update + LIVE_STATE.json update
  3. Flush .capture_queue.jsonl → ChromaDB observations
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
| 1 | Read Before Edit | Tier 1 Safety | ACTIVE | Edit, Write, NotebookEdit | Block edits to code files unless Read first this session |
| 2 | No Destroy | Tier 1 Safety | ACTIVE | Bash | Block `rm -rf`, `DROP TABLE`, `force push`, `reset --hard`, `mkfs`, `dd if=` |
| 3 | Test Before Deploy | Tier 1 Safety | ACTIVE | Bash | Block deploys (scp, rsync, docker push, kubectl apply, git push main) unless tests ran <30 min ago |
| 4 | Memory First | Tier 2 | TEMP DISABLED | Edit, Write, NotebookEdit, Task | Block edits if memory not queried in last 5 minutes |
| 5 | Proof Before Fixed | Tier 2 | ACTIVE | Edit, Write, NotebookEdit | Block edits to other files until previous edit verified (max 3 unverified) |
| 6 | Save Verified Fix | Tier 2 Advisory | ACTIVE | Edit, Write, Task, Bash | Warn (then block after 5x) when verified fix not saved to memory |
| 7 | Critical File Guard | Tier 3 | ACTIVE | Edit, Write, NotebookEdit | High-risk files (auth, payments, .env, CI/CD, nginx) need recent memory query |
| 8 | Temporal Awareness | Tier 3 | DORMANT | Edit, Write, NotebookEdit | High-risk hours (1–5 AM) + long session (>3h) warnings |
| 9 | Strategy Ban | Tier 2 | ACTIVE | Edit, Write, NotebookEdit | Block edits when current strategy has failed 3+ times |
| 10 | Model Cost Guard | Tier 2 | ACTIVE | Task | Require explicit model param on Task spawn; warn on mis-matched model for agent type |
| 11 | Rate Limit | Tier 1* | ACTIVE | All | Warn >40/min, block >60/min (rolling 120s window) |
| 12 | Plan Mode Save | Tier 2 Advisory | ACTIVE | Edit, Write, Bash, NotebookEdit | Warn (escalate to block after 3x) when plan mode exited without saving to memory |
| 13 | Workspace Isolation | Tier 2 | ACTIVE | Edit, Write, NotebookEdit | Block concurrent agents editing same file; stale claims (>2h) auto-cleared |
| 14 | Confidence Check | Tier 2 | ACTIVE | Edit, Write, NotebookEdit | Warn 2x per file, block on 3rd attempt without test baseline or verification |
| 15 | Causal Chain | Tier 2 | ACTIVE | Edit, Write, NotebookEdit | Block edits after test failure until `query_fix_history` called (within 5 min) |
| 16 | Code Quality | Tier 2 Advisory | ACTIVE | Edit, Write, NotebookEdit | Pattern-match for secrets, debug artifacts, convention violations; block after 4th per file |

### Adding a new gate

1. Create `hooks/gates/gate_NN_name.py` with a `check()` function returning `GateResult`
2. Add entry to `GATE_MODULES` list in `enforcer.py`
3. Add to `GATE_TOOL_MAP` in `enforcer.py`
4. Add state reads/writes to `GATE_STATE_DEPS` if needed
5. Write tests in `test_framework.py` (both block and allow paths)
6. Add state defaults to `shared/state.py:default_state()` if new state fields added

### Dormanting a gate

Comment out the entry in `GATE_MODULES` in `enforcer.py`. The gate file stays in place; the comment should note re-enable instructions. Example: Gate 8.

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
      └─ quarantine collection   (deduplication targets)
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
| `remember_this(content, context, tags, force)` | Save memory. FNV-1a dedup. Caps metadata at 500 chars. |
| `get_memory(id)` | Fetch full memory by ID. Supports comma-separated batch. |
| `deduplicate_sweep(dry_run, threshold)` | Find and quarantine near-duplicate memories by cosine distance. |
| `record_attempt(error_text, strategy_id)` | Causal chain: log a fix attempt → returns `chain_id`. |
| `record_outcome(chain_id, outcome)` | Causal chain: log "success" or "failure" for an attempt. |
| `query_fix_history(error_text, top_k)` | Search fix_outcomes for strategies tried on similar errors. Also resets Gate 15 state. |
| `maintenance(action, ...)` | `promotions`, `stale`, `cluster`, `health`, `rebuild_tags`. |

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

---

## Shared Libraries

| Module | Purpose |
|--------|---------|
| `gate_result.py` | `GateResult` dataclass: `blocked`, `message`, `gate_name`, `severity`, `duration_ms`, `metadata` |
| `state.py` | Atomic JSON state with `fcntl.flock`, per-agent isolation, schema v3, auto-migration v1→v2→v3, `default_state()` |
| `audit_log.py` | JSONL audit trail: rotate at 5MB, gzip, 90-day retention, ramdisk-aware |
| `error_normalizer.py` | Strip paths/UUIDs/timestamps/ports/addresses → stable FNV-1a fingerprint |
| `observation.py` | Tool call → compact ChromaDB summary; 30+ error pattern detectors; dedup via FNV-1a |
| `secrets_filter.py` | Regex redaction: private keys, JWTs, Bearer tokens, AWS keys, GitHub tokens, SSH keys, etc. |
| `chromadb_socket.py` | UDS client for hook→ChromaDB: `query`, `count`, `remember`, `flush_queue`, `backup`. 5s timeout, 3-retry exponential backoff. |
| `ramdisk.py` | tmpfs I/O layer: moves hot files to `/run/user/{uid}/claude-hooks`. Async disk mirror thread for audit logs. Graceful disk fallback. |

### State schema (v3) — key fields

```python
{
  # Gate 1: Read Before Edit
  "files_read": [],               # files Read this session

  # Gate 3: Test Before Deploy
  "last_test_run": 0,             # epoch timestamp
  "last_test_exit_code": None,

  # Gate 4: Memory First
  "memory_last_queried": 0,       # epoch (also in sideband file)

  # Gate 5: Proof Before Fixed
  "pending_edits": [],            # edits awaiting verification
  "unverified_edit_count": 0,

  # Gate 9: Strategy Ban
  "current_strategy_id": None,
  "strategy_fail_counts": {},

  # Gate 14: Confidence Check
  "confidence_warnings": {},      # per-file warning counts

  # Gate 15: Causal Chain
  "fix_history_queried": 0,       # epoch timestamp
  "last_test_failed": False,

  # Causal fix chain
  "pending_chain_ids": [],
  "verified_fixes": 0,

  # Tool call rate limiting (Gate 11)
  "tool_call_timestamps": [],     # rolling 120s window

  # Session metrics
  "tool_calls_total": 0,
  "edits_total": 0,
  "session_start_time": 0,
}
```

**State rules:**
- New fields always go in `default_state()` with sensible defaults
- Read via `.get(key, default)` — never assume key exists
- State is per-session; team agents do not share state
- Never rename existing fields without a migration path

---

## Agent Delegation

### Agent types

| Agent | Model | Tools | Use case |
|-------|-------|-------|----------|
| `builder` | opus | Read, Glob, Grep, Edit, Write, Bash, NotebookEdit + all memory tools | Feature implementation, bug fixes, refactoring |
| `auditor` | sonnet | Read, Glob, Grep, Bash + search/get/remember memory tools | Security review, OWASP audit, credential scanning |
| `researcher` | haiku | Read, Glob, Grep, WebFetch, WebSearch + search/get memory tools | Codebase exploration, documentation lookup, research |
| `stress-tester` | sonnet | Read, Glob, Grep, Bash + search/get/remember memory tools | Test suite execution, edge case hunting, benchmarking |

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

Bridges Telegram messages to Claude Code sessions. The user (@***REDACTED***) sends messages via Telegram; the bot routes them to an active Claude session and returns the response.

**Components:**
- `bot.py` — python-telegram-bot v21, long-polling loop
- `tmux_runner.py` — routes via `claude-bot` tmux session (active, 3.5s response time)
- `claude_runner.py` — alternative: `claude -p --resume <session_id>` direct invocation
- `db.py` — SQLite FTS5 for message history
- `sessions.py` — session ID persistence

**Routing mode:** tmux (configured via `config.json: tmux_target = "claude-bot"`). The shared-session mode causes interference; dedicated `claude-bot` tmux target is required.

**Known issue:** tmux pane dump bug — fixed by baseline diffing to extract only new output. Full scrollback capture causes copy-paste of entire pane history.

### Terminal History (`integrations/terminal-history/`)

Indexes all Claude Code JSONL session files into a SQLite FTS5 database for full-text search across session history.

- `indexer.py` — bulk JSONL parser, FTS5 ingest, mirrors to `~/data/memory/fts5_index.db`
- `db.py` — schema, FTS5 init, search interface
- `terminal_history.db` — live index (~6.8 MB)

---

## Skill System

23 slash-command skills defined as `SKILL.md` instruction files in `skills/`. Invoked via `/skill-name`. Composable via `/chain`.

| Skill | Purpose |
|-------|---------|
| `/analyze-errors` | Historical error pattern analysis, prevention playbooks |
| `/audit` | 3-agent security + quality audit team |
| `/build` | Full quality loop: memory → tests → implement → verify → commit |
| `/chain` | Compose skills into sequential pipelines |
| `/commit` | Quick git commit with auto-generated message |
| `/deep-dive` | Broad memory context retrieval (top_k=50, multi-mode) |
| `/deploy` | Deployment workflow with Gate 3 enforcement |
| `/document` | Auto-generate docstrings, README, API docs, architecture, changelog |
| `/explore` | Interactive codebase deep-dive |
| `/fix` | Auto-diagnose and fix: memory → context → causal chain → fix → verify |
| `/loop` | Torus Loop Orchestrator: runs PRP tasks via fresh Claude instances |
| `/profile` | Performance profiling and bottleneck identification |
| `/prp` | Generate/list/view Product Requirements Prompts |
| `/ralph` | Autonomous loop: up to 10 build-verify cycles with circuit breakers |
| `/refactor` | Safe incremental refactoring |
| `/research` | Structured research with memory integration |
| `/review` | Code quality and convention check |
| `/status` | Live project status report (uses `gather.py`) |
| `/test` | Run, write, and debug test suites |
| `/web` | Web content management: index, search, list, delete |
| `/wrap-up` | Session end protocol: metrics → memory → HANDOFF.md → LIVE_STATE.json |

---

## Performance Layer

### Ramdisk

Hot I/O files moved to `/run/user/{uid}/claude-hooks` (systemd tmpfs):

| File type | Ramdisk path | Disk backup |
|-----------|-------------|-------------|
| Audit logs (hot) | `ramdisk/audit/YYYY-MM-DD.jsonl` | `hooks/.disk_backup/audit/` (async mirror) |
| State files | `ramdisk/state_{id}.json` | None (ephemeral) |
| Capture queue | `ramdisk/.capture_queue.jsonl` | None (ephemeral) |

Throughput: ~544 MB/s ramdisk vs ~1.2 MB/s disk. The async mirror thread writes audit data to disk after every ramdisk write — zero data loss at full ramdisk speed.

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
| `PreToolUse` | 5,000ms | `enforcer.py --event PreToolUse` |
| `PostToolUse` | 3,000ms | `tracker.py` |
| `PostToolUse` (Edit\|Write) | 3,000ms | `auto_commit.py stage` |
| `SessionStart` | 15,000ms | `boot.py` |
| `SessionEnd` | 10,000ms | `session_end.py` |
| `UserPromptSubmit` | 3,000ms | `user_prompt_capture.py` + `auto_commit.py commit` |
| `PermissionRequest` | 3,000ms | `auto_approve.py` |
| `SubagentStart` | 3,000ms | `subagent_context.py` |
| `PreCompact` | 3,000ms | `pre_compact.py` |
| `SubagentStop` | 3,000ms | `event_logger.py --event SubagentStop` |
| `PostToolUseFailure` | 3,000ms | `event_logger.py --event PostToolUseFailure` |
| `Notification` | 3,000ms | `event_logger.py --event Notification` |
| `statusLine` | — | `statusline.py` |

Additional settings: `model: sonnet`, `effortLevel: medium`, `skipDangerousModePermissionPrompt: true`.

### `mcp.json` — MCP server

```json
{
  "mcpServers": {
    "memory": {
      "command": "python3",
      "args": ["hooks/memory_server.py"]
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

---

*Generated by Torus Framework — Session 143*
