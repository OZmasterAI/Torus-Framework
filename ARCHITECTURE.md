# Torus Framework — Architecture Map

> **Version:** v2.5.3 | **Updated:** 2026-02-24 (Session 223)
> **Stats:** 113 Python files | ~48,552 lines | 17 active gates | 50 shared modules | 33 skills

## Overview

Torus is a self-improving quality framework for Claude Code. It wraps every tool call with gate enforcement (PreToolUse blocking), tracks outcomes via a mentor system (PostToolUse), persists knowledge via ChromaDB memory, and orchestrates multi-agent work via teams and external scripts. The framework runs entirely through Claude Code's hook system — no modifications to Claude Code itself.

**Design principles:**
1. Mechanical enforcement over behavioral instruction (sys.exit(2) blocks, not just rules)
2. Fail-closed for safety (Tier 1), fail-open for quality (Tier 2+)
3. Per-session state isolation (agents can't bleed state)
4. Memory-first workflow (every fix/decision/discovery persisted)
5. Causal fix tracking (fingerprinted errors, strategy bans, outcome chains)
6. Hot I/O on ramdisk (~544 MB/s tmpfs vs ~1.2 MB/s disk)

## Component Diagram

```
                            ┌─────────────────────────────────────────────┐
                            │              Claude Code Session             │
                            └──────────┬──────────────┬──────────────┬────┘
                                       │              │              │
                    ┌──────────────────▼──┐    ┌─────▼──────┐  ┌───▼────────────┐
                    │   SessionStart       │    │ PreToolUse  │  │  PostToolUse   │
                    │   boot.py → boot_pkg │    │ enforcer →  │  │  tracker.py →  │
                    │   (20-step pipeline) │    │ (17 gates)  │  │  tracker_pkg   │
                    └──────────┬──────────┘    └─────┬───────┘  └───┬────────────┘
                               │                     │              │
              ┌────────────────▼─────────┐     ┌─────▼──────┐  ┌───▼──────────┐
              │  Context Injection        │     │  Gate      │  │  Mentor      │
              │  - LIVE_STATE.json        │     │  System    │  │  System      │
              │  - Memory L1 (ChromaDB)   │     │  (T1/T2/T3)│  │  (Module A)  │
              │  - Terminal History L2    │     └─────┬──────┘  └───┬──────────┘
              │  - Telegram L3            │           │             │
              │  - Gate auto-tune         │           │             │
              └──────────────────────────┘     ┌─────▼──────┐  ┌───▼──────────┐
                                               │  Shared/   │  │  Observation │
                                               │  (50 mods) │  │  Capture     │
                                               └─────┬──────┘  └───┬──────────┘
                                                     │              │
                            ┌────────────────────────▼──────────────▼──────┐
                            │              MCP Servers                      │
                            │  memory_server.py (6 tools, ChromaDB)        │
                            │  analytics_server.py (10 tools, read-only)   │
                            └──────────────────────────────────────────────┘
```

## Directory Layout

```
~/.claude/
├── CLAUDE.md                        # Master rules (~1,321 tokens, injected every prompt)
├── ARCHITECTURE.md                  # This document
├── HANDOFF.md                       # Session handoff (what was done, what's next)
├── LIVE_STATE.json                  # Machine-readable project state
├── config.json                      # Runtime toggles
├── settings.json                    # Hook registration + permissions
├── mcp.json                         # MCP server config
│
├── hooks/                           # Core framework (83 MB total)
│   ├── enforcer.py                  #   PreToolUse gate dispatcher (632 lines)
│   ├── enforcer_shim.py             #   Fast UDS proxy ~43ms (83 lines)
│   ├── enforcer_daemon.py           #   Persistent gate server (232 lines)
│   ├── boot.py                      #   SessionStart shim (42 lines)
│   ├── tracker.py                   #   PostToolUse shim (47 lines)
│   ├── session_end.py               #   SessionEnd handler (554 lines)
│   ├── statusline.py                #   2-line status display (1,061 lines)
│   ├── memory_server.py             #   Memory MCP server (4,188 lines)
│   ├── analytics_server.py          #   Analytics MCP server (379 lines)
│   ├── test_framework.py            #   Gate test suite (11,904 lines)
│   ├── fuzz_gates.py                #   Gate fuzzer (562 lines)
│   ├── subagent_context.py          #   SubagentStart context injection (336 lines)
│   ├── user_prompt_capture.py       #   UserPromptSubmit capture (160 lines)
│   ├── event_logger.py              #   Supplementary event logging (298 lines)
│   ├── auto_commit.py               #   Two-phase git auto-commit (148 lines)
│   ├── auto_approve.py              #   Benign tool auto-approval (136 lines)
│   ├── auto_format.py               #   Python auto-format ruff/black (92 lines)
│   ├── config_change.py             #   Hot-reload config.json (137 lines)
│   ├── pre_compact.py               #   PreCompact state snapshot (264 lines)
│   ├── integrity_check.py           #   SHA256 file verification (97 lines)
│   ├── failure_recovery.py          #   Tool failure triage (59 lines)
│   ├── tg_mirror.py                 #   Telegram mirror (127 lines)
│   ├── stop_cleanup.py              #   Stop event cleanup (46 lines)
│   ├── setup_ramdisk.sh             #   One-time tmpfs setup (116 lines)
│   │
│   ├── gates/                       # Quality gates (17 active, 348 KB)
│   ├── shared/                      # Infrastructure modules (50 files, 1.7 MB, ~19,458 lines)
│   ├── boot_pkg/                    # Boot pipeline (6 files, 848 lines)
│   ├── tracker_pkg/                 # Tracker pipeline (10 files, 1,537 lines)
│   ├── benchmarks/                  # Performance benchmarks
│   │   ├── benchmark_gates.py       #   Gate latency benchmarks (458 lines)
│   │   └── benchmark_io.py          #   I/O latency benchmarks (162 lines)
│   ├── audit/                       # Audit log archive (rotated, compressed)
│   ├── .disk_backup/                # Disk mirror of ramdisk audit logs
│   │
│   ├── .audit_trail.jsonl           # 46.3 MB audit trail
│   ├── .capture_queue.jsonl         # PostToolUse observation queue
│   ├── .auto_remember_queue.jsonl   # Memory ingestion queue
│   ├── .gate_effectiveness.json     # Historical gate effectiveness
│   ├── .gate_qtable.json            # Q-learning gate routing
│   ├── .gate_timings.json           # Per-gate latency stats (89.5 KB)
│   ├── .circuit_breaker_state.json  # Per-service failure tracking
│   ├── .file_claims.json            # Workspace isolation claims
│   ├── .integrity_hashes.json       # SHA256 framework verification
│   ├── .memory_last_queried         # Gate 4 sideband timestamp
│   ├── .enforcer.sock               # Enforcer daemon UDS socket
│   ├── .chromadb.sock               # ChromaDB UDS socket
│   ├── .enforcer.pid                # Daemon process ID
│   └── state_*.json                 # Per-agent session state (43 files)
│
├── skills/                          # 33 skill definitions
├── agents/                          # 6 agent definitions
├── teams/                           # 4 team definitions
├── plugins/                         # 9 installed plugins
├── scripts/                         # External orchestrators
│   ├── torus-loop.sh                #   Sequential task executor (261 lines)
│   └── torus-wave.py                #   Parallel wave orchestrator (477 lines)
├── integrations/
│   ├── telegram-bot/                # Telegram bot integration
│   └── terminal-history/            # Terminal history FTS5 indexer
└── rules/                           # Additional CLAUDE.md rules
    ├── hooks.md                     # Hook/gate development rules
    ├── memory.md                    # Memory MCP rules
    └── framework.md                 # Framework core rules
```

---

## Gate System

### Tier 1 — Safety (Fail-Closed: crash = block)

| # | Name | Lines | Watched Tools | Purpose |
|---|------|-------|---------------|---------|
| 1 | READ BEFORE EDIT | 118 | Edit, Write, NotebookEdit | Must Read file before editing. Guards: .py/.js/.ts/.tsx/.jsx/.rs/.go/.java/.c/.cpp/.rb/.php/.sh/.sql/.tf/.ipynb. Stem matching: reading test_foo.py satisfies foo.py |
| 2 | NO DESTROY | 312 | Bash | Blocks rm -rf, DROP TABLE, force push, reset --hard, mkfs, dd, fork bombs. 47 patterns. Shlex tokenization. Safe exceptions with regex |
| 3 | TEST BEFORE DEPLOY | 131 | Bash | Blocks scp, docker push, kubectl apply, npm publish, terraform unless tests ran in last 30 min with exit code 0 |

### Tier 2 — Quality (Fail-Open: crash = warn + continue)

| # | Name | Lines | Watched Tools | Purpose |
|---|------|-------|---------------|---------|
| 4 | MEMORY FIRST | 82 | Edit, Write, NotebookEdit, Task | Blocks if memory not queried in last 5 min. Sideband: .memory_last_queried. Read-only subagents exempt |
| 5 | PROOF BEFORE FIXED | 110 | Edit, Write, NotebookEdit | Blocks edits to OTHER files when 3+ files unverified. Warns at 4th same-file edit, blocks at 6th |
| 6 | SAVE TO MEMORY | 238 | Edit, Write, Task, Bash | Advisory → blocking. Warns unsaved fixes (threshold: 2). Escalates after 5 warnings. Merged old Gate 12. 20-min stale decay |
| 7 | CRITICAL FILE GUARD | 100 | Edit, Write, NotebookEdit | Extra checks for high-risk files (settings.json, CLAUDE.md, enforcer.py, etc.). Requires explicit confirmation for critical modifications |
| 9 | STRATEGY BAN | 175 | Edit, Write, NotebookEdit | Blocks strategies that failed 3+ times (4 if prior success). Auto-defers to PRP |
| 10 | MODEL COST GUARD | 267 | Task | Enforces explicit model param. 4-tier budget degradation (NORMAL/LOW_COMPUTE/CRITICAL/DEAD). Role-based profiles |
| 11 | RATE LIMIT | 82 | All (except analytics) | Blocks >60 calls/min, warns >40/min. 120s rolling window. MAX_WINDOW_ENTRIES=200 |
| 13 | WORKSPACE ISOLATION | 112 | Edit, Write, NotebookEdit | Prevents concurrent file edits across agents. fcntl.flock on .file_claims.json. Main session exempt |
| 14 | CONFIDENCE CHECK | 121 | Edit, Write, NotebookEdit | Progressive: warn 2x per file → block on 3rd. Checks test baseline, pending verification |
| 15 | CAUSAL CHAIN | 79 | Edit, Write, NotebookEdit | Blocks Edit after test failure until query_fix_history called. Requires both recent_test_failure AND fixing_error |
| 16 | CODE QUALITY | 154 | Edit, Write, NotebookEdit | Catches secrets, debug prints, broad excepts, TODOs. Progressive: warn 3x per file → block. Clean edit resets |

### Tier 3 — Advanced

| # | Name | Lines | Watched Tools | Purpose |
|---|------|-------|---------------|---------|
| 17 | INJECTION DEFENSE | 771 | WebFetch, WebSearch, MCP tools | 6 injection categories. Pre+PostToolUse. Base64/ROT13/hex/homoglyph/zero-width detection |
| 18 | CANARY MONITOR | 216 | All (advisory only) | Never blocks. Detects bursts (3x baseline), repeated sequences (5+), new tools. Welford online stats |
| 19 | HINDSIGHT | 92 | Edit, Write, NotebookEdit | Reads mentor signals. Blocks on sustained poor quality (score < 0.3) or 2+ consecutive escalations |

### Dormant

| # | Name | Status |
|---|------|--------|
| 8 | TEMPORAL | Never instantiated |
| 12 | PLAN MODE SAVE | Merged into Gate 6 |

### Gate Dispatch

- Gates run in priority order from `shared/gate_registry.GATE_MODULES`
- Q-learning optimization reorders Tier 2+ by historical block probability
- Tool-scoped dispatch reduces unnecessary evaluations
- Tier 1 crash = block; Tier 2+ crash = warn + continue
- Result caching for non-blocking gates (60s TTL)
- Always-allowed tools bypass all gates: Read, Glob, Grep, WebFetch, WebSearch, AskUserQuestion, EnterPlanMode, ExitPlanMode, TaskCreate/Update/List/Get, TeamCreate/Delete, SendMessage, TaskStop, all `mcp__memory__*` and `mcp__analytics__*` tools

---

## Shared Modules (50 files, ~19,458 lines)

### State Management (3 modules, ~1,277 lines)

| Module | Lines | Purpose |
|--------|-------|---------|
| state.py | 700 | load_state/save_state/default_state, atomic writes, fcntl.flock, per-session isolation, schema versioning |
| state_migrator.py | 347 | Schema migration/validation, get_schema_diff |
| ramdisk.py | 230 | Hybrid tmpfs for hot I/O. Async disk mirror. Graceful fallback |

### Gate Execution (4 modules, ~775 lines)

| Module | Lines | Purpose |
|--------|-------|---------|
| gate_result.py | 70 | GateResult class (block/ask/warn/allow) |
| gate_registry.py | 28 | GATE_MODULES canonical list (single source of truth) |
| gate_router.py | 456 | Priority routing, Q-learning, short-circuit, tool-type filtering |
| gate_timing.py | 221 | Per-gate latency stats, percentile analysis |

### Audit & Logging (3 modules, ~902 lines)

| Module | Lines | Purpose |
|--------|-------|---------|
| audit_log.py | 537 | JSONL trail with rotation (5MB), compaction, cleanup, block summaries |
| observation.py | 284 | Compress tool calls for ChromaDB auto-capture. Priority scoring. Sentiment detection |
| secrets_filter.py | 81 | Scrub API keys/tokens/connection strings before storage (12 patterns) |

### Error Handling (2 modules, ~546 lines)

| Module | Lines | Purpose |
|--------|-------|---------|
| error_normalizer.py | 52 | Strip paths/UUIDs/timestamps → stable FNV-1a fingerprint |
| error_pattern_analyzer.py | 494 | Recurring error analysis, correlations, prevention suggestions |

### Performance & Monitoring (4 modules, ~1,808 lines)

| Module | Lines | Purpose |
|--------|-------|---------|
| metrics_collector.py | 643 | Counters/gauges/histograms with ramdisk persistence and rollups |
| health_monitor.py | 542 | 0-100 health score across gates, memory, state, ramdisk, audit |
| hook_profiler.py | 306 | Nanosecond gate latency instrumentation |
| hook_cache.py | 317 | 3-layer cache: modules, state, results with configurable TTL |

### Anomaly & Drift Detection (2 modules, ~566 lines)

| Module | Lines | Purpose |
|--------|-------|---------|
| anomaly_detector.py | 496 | Rate spikes, single-gate dominance, session behavioral drift |
| drift_detector.py | 70 | Cosine similarity gate effectiveness drift detection |

### Analysis & Correlation (3 modules, ~2,614 lines)

| Module | Lines | Purpose |
|--------|-------|---------|
| gate_correlator.py | 822 | Co-occurrence matrix, gate chains, redundancy, optimal ordering |
| session_analytics.py | 1,030 | Rich session analysis from audit logs, gate effectiveness |
| tool_patterns.py | 762 | Markov chain tool sequences, workflow templates, anomaly detection |

### Security & Validation (4 modules, ~1,015 lines)

| Module | Lines | Purpose |
|--------|-------|---------|
| exemptions.py | 53 | Tiered file exemption: base/standard/full |
| security_profiles.py | 187 | Configurable postures: strict/balanced/permissive/refactor |
| config_validator.py | 320 | Validate settings.json, LIVE_STATE.json, gates, skills |
| consensus_validator.py | 455 | Cross-reference signals for critical operations |

### Resilience & Recovery (3 modules, ~1,734 lines)

| Module | Lines | Purpose |
|--------|-------|---------|
| circuit_breaker.py | 679 | CLOSED/OPEN/HALF_OPEN per-service failure tracking |
| rate_limiter.py | 450 | Token bucket with presets: TOOL_RATE, GATE_RATE, API_RATE |
| retry_strategy.py | 605 | Exponential/linear/constant/fibonacci backoff + jitter |

### Memory & Persistence (3 modules, ~1,393 lines)

| Module | Lines | Purpose |
|--------|-------|---------|
| memory_maintenance.py | 847 | Health analysis, age scoring, cleanup candidates (read-only) |
| chromadb_socket.py | 153 | UDS client for ChromaDB (avoids Rust segfaults). 5s timeout |
| experience_archive.py | 393 | CSV-based fix pattern learning, success rates |

### Inter-Agent Communication (3 modules, ~1,312 lines)

| Module | Lines | Purpose |
|--------|-------|---------|
| agent_channel.py | 125 | SQLite WAL inter-agent messaging |
| event_bus.py | 479 | Pub/sub with ramdisk ring buffer persistence |
| event_replay.py | 708 | Replay hook events through gates for regression testing |

### Registry & Catalog (4 modules, ~2,047 lines)

| Module | Lines | Purpose |
|--------|-------|---------|
| plugin_registry.py | 656 | Scan plugins, resolve metadata, categorize |
| capability_registry.py | 475 | Agent capability mapping, ACL enforcement, model recommendation |
| skill_mapper.py | 483 | Skill dependency graph, health analysis, reuse detection |
| skill_health.py | 433 | Validate skill structure (SKILL.md, metadata, scripts) |

### Visualization & Reporting (3 modules, ~1,448 lines)

| Module | Lines | Purpose |
|--------|-------|---------|
| gate_dashboard.py | 439 | Gate effectiveness dashboard, ranked metrics, recommendations |
| gate_graph.py | 469 | Dependency graph, circular dep detection, impact analysis |
| pipeline_optimizer.py | 540 | Optimal gate ordering, parallelization suggestions |

### Testing & Quality (2 modules, ~1,344 lines)

| Module | Lines | Purpose |
|--------|-------|---------|
| test_generator.py | 533 | Auto-generate test stubs for gates and shared modules |
| mutation_tester.py | 811 | Mutation testing: kill rate, test gap detection |

### Utility (2 modules, ~253 lines)

| Module | Lines | Purpose |
|--------|-------|---------|
| tool_fingerprint.py | 174 | SHA256 MCP tool supply chain verification |
| chain_sdk.py | 79 | Skill chain monitoring wrapper (elapsed, tokens, tool calls) |

---

## Hook Pipeline

```
SessionStart ─→ boot.py ─→ boot_pkg/orchestrator.py (378 lines)
                            ├── maintenance.py: audit rotation, state reset
                            ├── memory.py: ChromaDB injection via UDS, sideband write
                            └── context.py: error/test/verification/duration extraction

UserPromptSubmit ─→ user_prompt_capture.py (capture to queues)
                 ─→ user_prompt_check.sh (pre-flight)
                 ─→ auto_commit.py commit (batch staged changes)

PreToolUse ─→ enforcer_shim.py ─→ enforcer_daemon.py (~43ms fast path, ~5ms socket)
              (fallback: inline enforcer.py ~134ms)
              └── gates/ (17 active, priority-ordered, Q-learning optimized)

PostToolUse ─→ tracker.py ─→ tracker_pkg/orchestrator.py (537 lines)
                              ├── errors.py: error detection, 60s dedup
                              ├── observations.py: capture to .capture_queue.jsonl
                              ├── verification.py: test pass/fail classification
                              ├── auto_remember.py: high-value event capture
                              ├── outcome_chains.py: causal chain tracking
                              ├── mentor.py: Module A deterministic verdicts (0.0-1.0)
                              ├── mentor_memory.py: pattern/frequency learning
                              └── mentor_analytics.py: effectiveness metrics
            ─→ auto_commit.py stage (git add edited files)
            ─→ auto_format.py (ruff/black, 3s timeout)
SubagentStart ─→ subagent_context.py (inject LIVE_STATE + session state)

SubagentStop ─→ event_logger.py (log subagent completion)

PermissionRequest ─→ auto_approve.py (auto-approve benign tools)

PreCompact ─→ pre_compact.py (snapshot gate state before context compression)

SessionEnd ─→ session_end.py (flush queues, update LIVE_STATE, increment session_count)

Stop ─→ tg_mirror.py (mirror final response to Telegram)
     ─→ stop_cleanup.py (flush I/O, close handles, shutdown daemons)

PostToolUseFailure ─→ event_logger.py (log failure)
                   ─→ failure_recovery.py (triage and recover)

Notification ─→ event_logger.py (log notification)

ConfigChange ─→ config_change.py (hot-reload config.json)
```

### Boot Flow (22 steps)
1. Bot session check → 2. Ramdisk init → 3. Audit rotation → 4. Load LIVE_STATE → 5. Time warnings → 6. Gate count → 7. UDS check/daemon start → 8. ChromaDB watchdog → 9. Memory injection (ChromaDB socket) → 10. Telegram L3 search → 11. Gate auto-tuning → 12. Error extraction → 13. Tool activity → 14. Test status → 15. Verification quality → 16. Session duration → 17. Gate block stats → 18. Dashboard (stderr) → 19. Context injection (stdout) → 20. State reset → 21. Capture queue flush → 22. Auto-remember ingestion + sideband write

### PostToolUse Flow (17 steps)
1. Increment tool_call_count → 2. Token estimation → 3. Resolve gate blocks → 4. Auto-expire fixing_error → 5. Track reads → 6. Track edits → 7. Write file claims → 8. Track memory queries → 9. Error detection → 10. Observation capture → 11. Verification scoring → 12. Auto-remember → 13. Outcome chains → 14. Mentor evaluation → 15. Generate verdict → 16. Gate effectiveness → 17. Save state

---

## MCP Servers

### Memory Server (memory_server.py — 4,188 lines)

- **Embedding:** nomic-ai/nomic-embed-text-v2-moe (768-dim, 8192 tokens)
- **Storage:** ~/data/memory/ (ChromaDB SQLite)
- **Collections:** "knowledge" (curated, from remember_this) + "observations" (auto-captured) + "fix_outcomes" (causal chains) + "web_pages" (indexed URLs) + "quarantine" (dedup victims)
- **3-tier memory classification:** Tier 1 (high-value, boosted in search), Tier 2 (standard), Tier 3 (low-priority, penalized)
- **UDS gateway:** .chromadb.sock (serializes all hook-side access)

| Tool | Parameters | Purpose |
|------|-----------|---------|
| search_knowledge | query, top_k=15, mode, recency_weight=0.15, match_all | Modes: keyword, semantic, hybrid, tags, observations, all. Tag co-occurrence expansion. Keyword reranker. Recency boost (365-day decay) |
| remember_this | content, context, tags, force | Dedup cosine > 0.85. FNV1a hash IDs. Noise filter (12 patterns). 3-way write: ChromaDB + FTS5 + fix_outcomes bridge |
| get_memory | id | Full memory retrieval. Supports comma-separated batch |
| record_attempt | error_text, strategy_id | Start causal chain → returns chain_id |
| record_outcome | chain_id, outcome | Complete chain (success/failure) |
| query_fix_history | error_text, top_k=10 | Strategy success/failure lookup. Resets Gate 15 state |

**Dormant:** deduplicate_sweep, delete_memory, timeline, maintenance, get_teammate_transcripts

### Analytics Server (analytics_server.py — 379 lines)

Lightweight, read-only, lazy-loaded. No ChromaDB dependency.

| Tool | Parameters | Purpose |
|------|-----------|---------|
| framework_health | session_id | 0-100 health score, per-component status, suggestions |
| session_summary | session_id | Tool distribution, gate effectiveness, error rates |
| gate_dashboard | — | Ranked gates by block rate, coverage, recommendations |
| gate_timing | gate_name | Per-gate latency stats, slow gate detection |
| detect_anomalies | session_id | Bursts, high block rates, error spikes, memory gaps |
| skill_health | — | Total/healthy/broken counts, script issues |
| all_metrics | — | Counters/gauges/histograms + 1m/5m rollups |
| telegram_search | query, limit | FTS5 search over Telegram message history |
| terminal_history_search | query, limit | FTS5 search over terminal/conversation history |
| web_search | query, n_results | ChromaDB semantic search over indexed web pages |

---

## Skills Catalog (33 skills)

| Category | Skills |
|----------|--------|
| Dev Workflow (6) | fix, commit, test, review, refactor, document |
| Research (6) | research, explore, deep-dive, analyze-errors, learn, teach |
| Framework Ops (6) | diagnose, super-health, introspect, status, wrap-up, audit |
| Quality/Security (2) | security-scan, benchmark |
| Build/Deploy (3) | build, deploy, report |
| Orchestration (5) | prp, wave, loop, chain, sprint |
| Advanced (5) | web, browser, ralph, super-evolve, super-prof-optimize |

Skills with scripts/: security-scan, status, super-health, web, wrap-up
User-invocable: benchmark, learn, introspect, security-scan, super-evolve, keybindings-help

---

## Agent Definitions (6 agents)

| Agent | Model | Capabilities |
|-------|-------|-------------|
| researcher | haiku | Read-only exploration: Glob, Grep, Read, WebFetch, WebSearch, memory |
| builder | sonnet | Full implementation: Edit, Write, Bash, NotebookEdit, memory, causal chain |
| debugger | sonnet | Diagnosis + fix: Edit, Write, Bash, causal chain tracking, log analysis |
| stress-tester | sonnet | Test execution + verification: Bash, memory |
| perf-analyzer | sonnet | Performance profiling: Read-only + Bash for benchmarks |
| security | sonnet | Security audit: Read-only + Bash for scanning |

### Delegation Rules

```
2-5 steps, independent   → Sub-agents (parallel)
2-5 steps, dependent     → Sub-agents (lead orchestrates, memory bridges)
5-7 steps                → Either (teams preferred)
7+ steps                 → Agent teams (real-time coordination)
Cross-session            → Sub-agents + memory
```

---

## Teams (4 definitions)

| Team | Purpose | Members |
|------|---------|---------|
| default | Inactive legacy | 2 (shutdown) |
| eclipse-rebase | Rebase ProjectDawn to Eclipse L2 | 5 (lead + 4 specialized) |
| framework-v2-4-1 | v2.4.1 sprint: dashboard, statusline | 1 builder |
| sprint-team | Self-improvement sprint | 10 (builders + researchers) |

---

## Plugins (9 installed)

| Category | Plugins |
|----------|---------|
| LSP (3) | pyright-lsp, rust-analyzer-lsp, typescript-lsp |
| Dev (5) | feature-dev, pr-review-toolkit, code-review, hookify, skill-creator |
| Quality (1) | code-simplifier |

---

## External Orchestration

| Script | Lines | Purpose |
|--------|-------|---------|
| torus-loop.sh | 261 | Sequential fresh-context task executor. Spawns fresh Claude per task from PRP's tasks.json. Memory MCP bridges knowledge |
| torus-wave.py | 477 | Parallel wave orchestrator. Groups tasks into waves with file-overlap guards. Spawns parallel `claude -p` processes |

**PRP System (Parallel Research Projects):**
/prp skill → task_manager.py → torus-loop.sh (sequential) or torus-wave.py (parallel) → Memory MCP cross-instance continuity → Gate 9 auto-defer feedback loop

---

## Integration Points

| System | Location | Protocol |
|--------|----------|----------|
| Telegram Bot | integrations/telegram-bot/ | Bot API, SQLite msg_log.db (532KB) |
| Terminal History | integrations/terminal-history/ | FTS5, SQLite terminal_history.db (19.8MB) |
| ChromaDB | ~/data/memory/ | UDS socket (.chromadb.sock) |
| Enforcer Daemon | hooks/.enforcer.sock | UDS socket (JSON-over-newline) |
| Ramdisk | /run/user/{uid}/claude-hooks/ | tmpfs + async disk mirror backup |
| Git Auto-Commit | hooks/auto_commit.py | Two-phase: stage (PostToolUse) → commit (UserPromptSubmit) |

---

## Config Reference (config.json)

| Toggle | Value | Purpose |
|--------|-------|---------|
| context_enrichment | true | Inject context from memory/integrations at boot |
| gate_auto_tune | true | Self-evolving gate effectiveness thresholds |
| enforcer_daemon | true | Use persistent UDS server (~43ms vs ~134ms) |
| budget_degradation | false | 4-tier model downgrade based on budget |
| model_profile | "efficient" | Role-based model selection |
| security_profile | "balanced" | Gate strictness posture |
| chain_memory | true | Persist causal chains to memory |
| mentor_all | true | Enable all mentor system modules |
| mentor_tracker | false | Mentor Module A tracker verdicts |
| mentor_hindsight_gate | false | Gate 19 mentor-driven blocking |
| tg_session_notify | true | Telegram session notifications |
| tg_mirror_messages | true | Mirror Claude responses to Telegram |
| terminal_l2_always | false | Always include terminal L2 in search |
| tg_enrichment | false | Telegram context enrichment |
| tg_l3_always | false | Always include Telegram L3 in search |
| tg_bot_tmux | false | Run Telegram bot in tmux session |
| session_token_budget | — | Token budget per session |
| mentor_outcome_chains | true | Track mentor outcome chains |
| mentor_memory | true | Mentor pattern/frequency learning |
| search_routing | "default" | Search mode routing strategy |

---

## Data Files

| File | Size | Purpose |
|------|------|---------|
| .audit_trail.jsonl | 46.3 MB | Complete tool call audit trail |
| .capture_queue.jsonl | ~572 KB | PostToolUse observation queue |
| .auto_remember_queue.jsonl | ~23 KB | Memory ingestion queue |
| .gate_effectiveness.json | — | Historical gate effectiveness metrics |
| .gate_qtable.json | — | Q-learning gate routing optimization |
| .gate_timings.json | 89.5 KB | Per-gate latency statistics |
| .circuit_breaker_state.json | — | Per-service failure tracking |
| .file_claims.json | — | Workspace isolation claims (Gate 13) |
| .integrity_hashes.json | — | SHA256 framework file verification |
| .settings_snapshot.json | 6.7 KB | Config snapshot at session start |
| state_*.json | 43 files | Per-agent session state |

---

## Framework Statistics

| Metric | Value |
|--------|-------|
| Python files (hooks/) | 113 |
| Total lines (hooks/) | ~48,552 |
| Active gates | 17 (+ 2 dormant) |
| Shared modules | 50 |
| Top-level hooks | 25 |
| Boot pipeline files | 6 (848 lines) |
| Tracker pipeline files | 10 (1,537 lines) |
| Skills | 33 |
| Plugins | 9 (3 LSP + 5 dev + 1 quality) |
| Agent definitions | 6 |
| Teams | 4 |
| MCP servers | 2 (16 active tools) |
| External orchestrators | 2 |
| Integrations | 2 |
| Session state files | 43 |
| Total memories | ~1,345 |
| Largest file | test_framework.py (11,904 lines) |

---

*Generated by Torus Framework — Session 223 (2026-02-24)*
