# Torus Framework — Architecture Map

> **Version:** v3.0.0 | **Updated:** 2026-03-16 (Session 432)
> **Stats:** 194 Python files | ~92,816 lines | 19 active gates | 83 shared modules | 42 skills | 3,026 memories

## Overview

Torus is a self-improving quality framework for Claude Code. It wraps every tool call with gate enforcement (PreToolUse blocking), tracks outcomes via a mentor system (PostToolUse), persists knowledge via LanceDB memory, and orchestrates multi-agent work via teams and external scripts. The framework runs entirely through Claude Code's hook system — no modifications to Claude Code itself.

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
                    │   (20-step pipeline) │    │ (19 gates)  │  │  tracker_pkg   │
                    └──────────┬──────────┘    └─────┬───────┘  └───┬────────────┘
                               │                     │              │
              ┌────────────────▼─────────┐     ┌─────▼──────┐  ┌───▼──────────┐
              │  Context Injection        │     │  Gate      │  │  Mentor      │
              │  - LIVE_STATE.json        │     │  System    │  │  System      │
              │  - Memory L1 (LanceDB)    │     │  (T1/T2/T3)│  │  (Module A)  │
              │  - Terminal History L2    │     └─────┬──────┘  └───┬──────────┘
              │  - Telegram L3            │           │             │
              │  - Gate auto-tune         │           │             │
              └──────────────────────────┘     ┌─────▼──────┐  ┌───▼──────────┐
                                               │  Shared/   │  │  Observation │
                                               │  (83 mods) │  │  Capture     │
                                               └─────┬──────┘  └───┬──────────┘
                                                     │              │
                            ┌────────────────────────▼──────────────▼──────┐
                            │              MCP Servers                      │
                            │  memory_server.py (8 tools, LanceDB)         │
                            │  analytics_server.py (15 tools, read-only)   │
                            └──────────────────────────────────────────────┘
```

## Directory Layout

```
torus-framework/
~/.claude/
├── CLAUDE.md                         Main rules (~587 tokens, every prompt)
  ├── ARCHITECTURE.md                   Full architecture documentation
  ├── USAGE_GUIDE.md                    User guide
  ├── README.md                         GitHub README
  ├── LICENSE                           MIT License
  ├── install.sh                        Installation script
  ├── LIVE_STATE.json                   Session handoff state
  ├── config.json                       Runtime toggles + API keys
  ├── config.example.json               Config template
  ├── settings.json                     Hook registration + permissions
  ├── settings.local.json               Machine-specific overrides
  ├── mcp.json                          MCP server config
  ├── mcp.example.json                  MCP config template
  ├── keybindings.json                  Custom keybindings
  ├── shorten_batch.py                  Batch processing utility
  │
  ├── rules/                            Claude Code auto-loaded rules (~750 tokens/prompt)
  │   ├── framework.md                  Gate contract, tiers, state schema (~400 tokens)
  │   ├── hooks.md                      Hook & gate development rules (~200 tokens)
  │   └── memory.md                     Memory MCP rules (~150 tokens)
  │
  ├── hooks/                            Core framework
  │   ├── enforcer.py                   PreToolUse gate dispatcher (651 lines)
  │   ├── enforcer_shim.py              Fast UDS proxy ~5ms (113 lines)
  │   ├── enforcer_daemon.py            Persistent gate server (232 lines)
  │   ├── memory_server.py              LanceDB memory MCP server (4,627 lines)
  │   ├── summarizer_daemon.py          OpenRouter LLM worker, model racing
  │   ├── boot.py                       SessionStart shim (42 lines)
  │   ├── tracker.py                    PostToolUse shim (47 lines)
  │   ├── session_end.py                SessionEnd handler, fast + background
  │   ├── user_prompt_capture.py        UserPromptSubmit handler
  │   ├── pre_compact.py                PreCompact handler
  │   ├── post_compact.py               PostCompact injection handler
  │   ├── statusline.py                 2-line status display
  │   ├── auto_commit.py                PostToolUse auto-staging + commit
  │   ├── auto_format.py                PostToolUse auto-formatting
  │   ├── auto_approve.py               PermissionRequest handler
  │   ├── subagent_context.py           SubagentStart context injection
  │   ├── context_threshold_stop.py     Stop hook context warning
  │   ├── stop_cleanup.py               Stop hook state capture
  │   ├── integrity_check.py            SessionStart integrity verification
  │   ├── tg_mirror.py                  Telegram message mirroring
  │   ├── tg_mirror_user.py             Telegram user message mirroring
  │   ├── tts_signal.py                 TTS notification signal
  │   ├── tgbot_response.py             Telegram bot response hook
  │   ├── config_change.py              ConfigChange handler
  │   ├── event_logger.py               Generic event logger
  │   ├── failure_recovery.py           PostToolUseFailure handler
  │   ├── analytics_server.py           Health scoring + analytics
  │   ├── working-memory.md             Machine-generated working memory (injected, not auto-loaded)
  │   ├── working-summary.md            LLM-written session summary (injected, not auto-loaded)
  │   │
  │   ├── gates/                        19 quality gates
  │   │   ├── gate_01_read_before_edit.py   T1 fail-closed
  │   │   ├── gate_02_no_destroy.py         T1 fail-closed
  │   │   ├── gate_03_safety_net.py         T1 fail-closed
  │   │   ├── gate_04_memory_first.py       Memory freshness check
  │   │   ├── gate_05_proof_before_fixed.py Verification required
  │   │   ├── gate_06_save_to_memory.py     Save findings to memory
  │   │   ├── gate_07_critical_file_guard.py Protected file list
  │   │   ├── gate_09_strategy_ban.py       Failed strategy prevention
  │   │   ├── gate_10_model_profile.py      Model selection enforcement
  │   │   ├── gate_11_rate_limit.py         Tool call rate limiting
  │   │   ├── gate_13_workspace_isolation.py Worktree file claims
  │   │   ├── gate_14_confidence_check.py   Test baseline required
  │   │   ├── gate_15_context_enrichment.py Context injection
  │   │   ├── gate_16_code_quality.py       Ruff AST linting
  │   │   ├── gate_17_injection_defense.py  Prompt injection detection
  │   │   ├── gate_18_budget_guard.py       Token budget enforcement
  │   │   ├── gate_19_hindsight_gate.py     Mentor escalation
  │   │   ├── gate_20_self_check.py         Gate self-consistency
  │   │   └── gate_21_working_summary.py    Summary write enforcement
  │   │
  │   ├── shared/                       ~73 shared modules
  │   │   ├── state.py                  State management (ramdisk + disk)
  │   │   ├── gate_result.py            GateResult dataclass
  │   │   ├── gate_router.py            Q-learning gate reordering
  │   │   ├── gate_registry.py          Gate metadata registry
  │   │   ├── circuit_breaker.py        Gate circuit breakers
  │   │   ├── ramdisk.py                Ramdisk fast-path I/O
  │   │   ├── memory_socket.py          UDS memory server client
  │   │   ├── memory_classification.py  Reference/working classifier + daemon bridge
  │   │   ├── lance_collection.py       LanceDB collection wrapper
  │   │   ├── scoring_engine.py         Memory relevance scoring
  │   │   ├── search_pipeline.py        Multi-stage search pipeline
  │   │   ├── search_helpers.py         Search utility functions
  │   │   ├── write_pipeline.py         Memory write pipeline
  │   │   ├── tag_index.py              Tag co-occurrence index
  │   │   ├── cluster_store.py          Memory clustering
  │   │   ├── working_memory_writer.py  3-layer working memory writer
  │   │   ├── operation_tracker.py      Per-session operation tracking
  │   │   ├── audit_log.py              Audit trail logging
  │   │   ├── error_normalizer.py       Error pattern normalization
  │   │   ├── observation.py            Auto-observation capture
  │   │   ├── metrics_collector.py      Performance metrics
  │   │   ├── health_monitor.py         System health monitoring
  │   │   ├── anomaly_detector.py       Anomaly detection
  │   │   ├── gate_correlator.py        Cross-gate correlation
  │   │   ├── gate_dashboard.py         Gate effectiveness dashboard
  │   │   ├── gate_pruner.py            Gate effectiveness analysis
  │   │   ├── gate_helpers.py           Shared gate utilities
  │   │   ├── pipeline_optimizer.py     Gate ordering optimization
  │   │   ├── session_analytics.py      Session metrics analysis
  │   │   ├── health_correlation.py     Health score correlation
  │   │   ├── code_hotspot.py           File edit frequency tracking
  │   │   ├── secrets_filter.py         Secret detection + redaction
  │   │   ├── chain_sdk.py              Causal chain SDK
  │   │   ├── chain_refinement.py       Chain analysis refinement
  │   │   ├── ltp_tracker.py            Long-term potentiation
  │   │   ├── knowledge_graph.py        Memory graph enrichment
  │   │   └── tool_fingerprint.py       MCP tool supply-chain security
  │   │
  │   ├── boot_pkg/                     Session start pipeline
  │   │   ├── orchestrator.py           Boot orchestrator (daemon start, injection)
  │   │   ├── context.py                Context extraction
  │   │   ├── memory.py                 Boot memory injection
  │   │   └── util.py                   detect_project, LIVE_STATE, state helpers
  │   │
  │   ├── tracker_pkg/                  PostToolUse pipeline
  │   │   ├── orchestrator.py           Tracker orchestrator
  │   │   ├── verification.py           Gate block outcome resolution
  │   │   ├── observations.py           Auto-observation capture
  │   │   ├── auto_remember.py          Auto-save to memory
  │   │   ├── errors.py                 Error tracking
  │   │   └── mentor.py                 Deterministic mentoring
  │   │
  │   ├── scripts/                      Utility scripts
  │   │   ├── backfill_memory_type.py
  │   │   └── backfill_state_type.py
  │   │
  │   ├── tests/                        Test suite (~1400+ tests)
  │   │   ├── test_framework.py         Main gate + shared module tests
  │   │   ├── test_integration.py       Integration tests
  │   │   ├── test_shared_core.py       Core shared module tests
  │   │   ├── test_shared_deep.py       Deep shared module tests
  │   │   ├── test_working_memory_writer.py
  │   │   ├── test_operation_tracker.py
  │   │   ├── test_context_warning.py
  │   │   ├── test_scoring_engine.py
  │   │   ├── test_memory_type.py
  │   │   ├── test_state_type.py
  │   │   └── ...
  │   │
  │   └── benchmarks/                   Performance benchmarks
  │
  ├── skills/                           Core skills (Claude-invocable)
  │   ├── brainstorm/
  │   ├── commit/
  │   ├── implement/
  │   ├── review/
  │   ├── test/
  │   ├── working-summary/
  │   ├── wrap-up/
  │   ├── writing-plans/
  │   ├── benchmark -> ../skill-library/benchmark
  │   ├── learn -> ../skill-library/learn
  │   └── super-evolve -> ../skill-library/super-evolve
  │
  ├── skill-library/                    Extended skill library (~30 skills)
  │   ├── analyze-errors/
  │   ├── audit/
  │   ├── benchmark/
  │   ├── build/
  │   ├── causal-chain-analysis/
  │   ├── chain/
  │   ├── code-hotspots/
  │   ├── deep-dive/
  │   ├── deploy/
  │   ├── diagnose/
  │   ├── experiment/
  │   ├── explore/
  │   ├── fix/
  │   ├── learn/
  │   ├── ralph/
  │   ├── research/
  │   ├── sprint/
  │   ├── status/
  │   ├── super-evolve/
  │   ├── super-health/
  │   └── ...
  │
  ├── toroidal/                         Toroidal memory + session capture
  │   ├── session_capture_hook.py       SessionStart capture
  │   ├── idle_prompt_hook.sh           Idle prompt handler
  │   └── sessions.json                 Active session registry
  │
  ├── teams/                            Agent team orchestration
  │   ├── sprint-team/                  Sprint team config + inboxes
  │   │   ├── config.json
  │   │   └── inboxes/
  │   └── evolution-swarm-268/          Evolution swarm config
  │       └── inboxes/
  │
  ├── channels/                         Cross-agent message passing
  │   └── dead-letter/                  Undeliverable messages
  │
  ├── agents/                           Worktree sprint agents (runtime)
  │   ├── sprint-features/              Feature development worktree
  │   ├── sprint-gates/                 Gate improvement worktree
  │   ├── sprint-memory/                Memory system worktree
  │   ├── sprint-refactor/              Refactoring worktree
  │   └── sprint-tests/                 Test writing worktree
  │
  ├── integrations/                     External integrations
  │   ├── model-router/                 OpenRouter multi-model MCP
  │   ├── telegram-bot/                 Telegram bot + mirroring
  │   ├── terminal-history/             FTS5 session search
  │   ├── voice-web/                    Voice web interface
  │   └── tts-voices/                   Piper TTS voices
  │
  ├── data/                             Runtime data storage
  │   ├── memory/                       LanceDB memory database
  │   └── research/                     Research artifacts
  │
  ├── PRPs/                             Prompt-Response Pairs (validation)
  │   ├── templates/
  │   └── test-workspace/
  │
  ├── docs/                             Documentation
  │   └── plans/
  │
  ├── dormant/                          Archived/inactive features
  │   ├── agents/
  │   ├── gates/
  │   ├── skills/
  │   ├── modes/
  │   └── teams/
  │
  ├── scripts/                          Shell/Python utilities
  └── examples/                         Usage examples
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
| 10 | MODEL PROFILE ENFORCEMENT | 326 | Task, Agent | Enforces model profiles via agent frontmatter patching. 5 profiles (quality/balanced/efficient/lean/budget) map roles to models. Auto-patches .md frontmatter at spawn time. Atomic writes (tempfile + os.rename) |
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
- PostCompact hook injects working-memory and working-summary after compaction
- Always-allowed tools bypass all gates: Read, Glob, Grep, WebFetch, WebSearch, AskUserQuestion, EnterPlanMode, ExitPlanMode, TaskCreate/Update/List/Get, TeamCreate/Delete, SendMessage, TaskStop, all `mcp__memory__*` and `mcp__analytics__*` tools

---

## Shared Modules (83 files, ~30,000+ lines)

### State Management (3 modules, ~1,277 lines)

| Module | Lines | Purpose |
|--------|-------|---------|
| state.py | 700 | load_state/save_state/default_state, atomic writes, fcntl.flock, per-session isolation, schema versioning |
| state_migrator.py | 347 | Schema migration/validation, get_schema_diff |
| ramdisk.py | 230 | Hybrid tmpfs for hot I/O. Async disk mirror. Graceful fallback |

### Gate Execution (5 modules, ~1,008 lines)

| Module | Lines | Purpose |
|--------|-------|---------|
| gate_result.py | 70 | GateResult class (block/ask/warn/allow) |
| gate_registry.py | 28 | GATE_MODULES canonical list (single source of truth) |
| gate_router.py | 456 | Priority routing, Q-learning, short-circuit, tool-type filtering |
| gate_timing.py | 221 | Per-gate latency stats, percentile analysis |
| gate_helpers.py | 233 | Gate evaluation helper utilities |

### Audit & Logging (3 modules, ~902 lines)

| Module | Lines | Purpose |
|--------|-------|---------|
| audit_log.py | 537 | JSONL trail with rotation (5MB), compaction, cleanup, block summaries |
| observation.py | 284 | Compress tool calls for LanceDB auto-capture. Priority scoring. Sentiment detection |
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
| memory_socket.py | 195 | UDS client for memory server / LanceDB (avoids segfaults). 5s timeout |
| memory_classification.py | ~400 | Reference/working/unclassified classifier + daemon semantic bridge |
| lance_collection.py | ~200 | LanceDB collection wrapper with SQL injection prevention |
| scoring_engine.py | ~300 | Multi-factor memory relevance scoring |
| search_pipeline.py | ~400 | Multi-stage search: BM25 → semantic → hybrid → rerank |
| search_helpers.py | ~150 | Search utility functions |
| write_pipeline.py | ~300 | Memory write pipeline: dedup, classify, cluster, store |
| tag_index.py | ~200 | Tag co-occurrence SQLite index |
| cluster_store.py | ~250 | Memory clustering via embedding similarity |
| experience_archive.py | 393 | CSV-based fix pattern learning, success rates |
| model_profiles.py | 101 | 5 model profiles (quality/balanced/efficient/lean/budget), role→model mappings, get_model_for_agent() API |

### Inter-Agent Communication (3 modules, ~1,312 lines)

| Module | Lines | Purpose |
|--------|-------|---------|
| agent_channel.py | 125 | SQLite WAL inter-agent messaging |
| event_bus.py | 479 | Pub/sub with ramdisk ring buffer persistence |
| event_replay.py | 708 | Replay hook events through gates for regression testing |

### Registry & Catalog (5 modules, ~2,371 lines)

| Module | Lines | Purpose |
|--------|-------|---------|
| plugin_registry.py | 656 | Scan plugins, resolve metadata, categorize |
| capability_registry.py | 475 | Agent capability mapping, ACL enforcement, model recommendation |
| skill_mapper.py | 483 | Skill dependency graph, health analysis, reuse detection |
| skill_health.py | 433 | Validate skill structure (SKILL.md, metadata, scripts) |
| domain_registry.py | 324 | Domain-specific knowledge registry and routing |

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

### Gate Analysis (6 modules, ~1,228 lines)

| Module | Lines | Purpose |
|--------|-------|---------|
| gate_trend.py | 237 | Gate block rate trend analysis over time |
| gate_health.py | 160 | Per-gate health scoring and degradation detection |
| gate_correlation.py | 132 | Gate co-firing correlation analysis |
| gate_dependency_graph.py | 387 | Gate dependency DAG, topological sort, impact analysis |
| gate_pruner.py | 312 | Identify redundant or low-value gates for removal |
| health_correlation.py | 354 | Cross-component health correlation and root cause analysis |

### Memory Analysis (3 modules, ~478 lines)

| Module | Lines | Purpose |
|--------|-------|---------|
| memory_decay.py | 166 | Time-based memory relevance decay scoring |
| search_cache.py | 119 | LRU search result caching with TTL |
| verify_memory_maintenance.py | 193 | Memory health verification and maintenance checks |

### Session Analysis (2 modules, ~573 lines)

| Module | Lines | Purpose |
|--------|-------|---------|
| session_replay.py | 418 | Replay past sessions for debugging and analysis |
| session_compressor.py | 155 | Session transcript compression for storage efficiency |

### Working Memory (2 modules, ~650 lines)

| Module | Lines | Purpose |
|--------|-------|---------|
| working_memory_writer.py | ~400 | 3-layer working memory: status, operations, expanded context |
| operation_tracker.py | ~250 | Per-session operation tracking with FIFO eviction |

### Code Quality Analysis (2 modules, ~657 lines)

| Module | Lines | Purpose |
|--------|-------|---------|
| code_hotspot.py | 344 | Identify frequently-edited code regions and churn patterns |
| tool_recommendation.py | 313 | Suggest optimal tools based on task context and history |

### Infrastructure Extensions (4 modules, ~1,462 lines)

| Module | Lines | Purpose |
|--------|-------|---------|
| hot_reload.py | 571 | Live config/module reload without restart |
| rules_validator.py | 144 | Validate rules/*.md files for correctness |
| chain_refinement.py | 548 | Causal chain strategy refinement and learning |
| metrics_exporter.py | 199 | Export metrics in Prometheus/JSON format |

---

## Hook Pipeline

```
SessionStart ─→ boot.py ─→ boot_pkg/orchestrator.py (378 lines)
                            ├── maintenance.py: audit rotation, state reset, agent model sync
                            ├── memory.py: LanceDB injection via UDS, sideband write
                            └── context.py: error/test/verification/duration extraction

UserPromptSubmit ─→ user_prompt_capture.py (capture + context drop injection)
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

PreCompact ─→ pre_compact.py (expand working memory before compaction)
PostCompact ─→ post_compact.py (inject working-memory + working-summary after compaction)

SessionEnd ─→ session_end.py (flush queues, update LIVE_STATE, increment session_count)

Stop ─→ tg_mirror.py (mirror final response to Telegram)
     ─→ tts_signal.py (strip markdown, write TTS signal for voice-web)
     ─→ stop_cleanup.py (flush I/O, close handles, shutdown daemons)

PostToolUseFailure ─→ event_logger.py (log failure)
                   ─→ failure_recovery.py (triage and recover)

Notification ─→ event_logger.py (log notification)

ConfigChange ─→ config_change.py (hot-reload config.json)
```

### Boot Flow (22 steps)
1. Bot session check → 2. Ramdisk init → 3. Audit rotation → 4. Load LIVE_STATE → 5. Time warnings → 6. Gate count → 7. UDS check/daemon start → 8. LanceDB watchdog → 9. Memory injection (LanceDB socket) → 10. Telegram L3 search → 11. Gate auto-tuning → 12. Error extraction → 13. Tool activity → 14. Test status → 15. Verification quality → 16. Session duration → 17. Gate block stats → 18. Dashboard (stderr) → 19. Context injection (stdout) → 20. State reset → 21. Capture queue flush → 22. Auto-remember ingestion + sideband write

### PostToolUse Flow (17 steps)
1. Increment tool_call_count → 2. Token estimation → 3. Resolve gate blocks → 4. Auto-expire fixing_error → 5. Track reads → 6. Track edits → 7. Write file claims → 8. Track memory queries → 9. Error detection → 10. Observation capture → 11. Verification scoring → 12. Auto-remember → 13. Outcome chains → 14. Mentor evaluation → 15. Generate verdict → 16. Gate effectiveness → 17. Save state

---

## MCP Servers

### Memory Server (memory_server.py — 4,627 lines)

- **Embedding:** nomic-ai/nomic-embed-text-v2-moe (768-dim, 8192 tokens)
- **Storage:** ~/data/memory/lancedb/ (LanceDB, flat scan; ChromaDB backup at ~/data/memory/chroma.sqlite3)
- **Tables:** "knowledge" (1,402, curated, from remember_this) + "observations" (4,579, auto-captured) + "fix_outcomes" (264, causal chains) + "web_pages" (indexed URLs) + "quarantine" (2, dedup victims)
- **Search:** BM25 FTS (~19ms keyword), semantic (~30ms flat scan), hybrid; tags in separate SQLite tags.db
- **3-tier memory classification:** Tier 1 (high-value, boosted in search), Tier 2 (standard), Tier 3 (low-priority, penalized)
- **UDS gateway:** .chromadb.sock (legacy name, serializes all hook-side LanceDB access)

**8 active tools, 5 dormant.**

| Tool | Parameters | Purpose |
|------|-----------|---------|
| search_knowledge | query, top_k=15, mode, recency_weight=0.15, match_all | Modes: keyword, semantic, hybrid, tags, observations, all. Tag co-occurrence expansion. Keyword reranker. Recency boost (365-day decay) |
| remember_this | content, context, tags, force | Dedup cosine > 0.85. FNV1a hash IDs. Noise filter (12 patterns). 3-way write: LanceDB + tags.db (SQLite BM25 FTS) + fix_outcomes bridge |
| get_memory | id | Full memory retrieval. Supports comma-separated batch |
| record_attempt | error_text, strategy_id | Start causal chain → returns chain_id |
| record_outcome | chain_id, outcome | Complete chain (success/failure) |
| query_fix_history | error_text, top_k=10 | Strategy success/failure lookup. Resets Gate 15 state |
| fuzzy_search | query, top_k=10, table | Typo-tolerant search with edit-distance expansion. Exact match 2x boost |
| health_check | — | Server uptime, table counts, last write, embedding status, disk usage |

**Dormant:** deduplicate_sweep, delete_memory, timeline, maintenance, get_teammate_transcripts

### Analytics Server (analytics_server.py — 2,481 lines)

Comprehensive framework analytics — lazy-loaded, no LanceDB dependency. **15 active tools** (trimmed from 50 to reduce context overhead).

| Category | Tools |
|----------|-------|
| **Framework Health (2)** | framework_health, all_metrics |
| **Gate Analysis (3)** | gate_dashboard, gate_timing, preview_gates |
| **Session (2)** | session_summary, session_metrics |
| **Audit & Errors (3)** | audit_trail, error_clusters, fix_effectiveness |
| **Memory & Infra (2)** | memory_health, circuit_states |
| **Skills & Observations (2)** | skill_health, query_observations |
| **Behavioral (1)** | rw_ratio |

### Summarizer Daemon (summarizer_daemon.py)

- **Protocol:** JSON-over-newline on Unix socket (.summarizer.sock)
- **Models:** OpenRouter free tier (nemotron-3-super, arcee-trinity) with model racing
- **Handlers:** summarize (session summaries), classify (memory type classification)
- **Auto-start:** boot.py launches on session start if not running

---

## Skills Catalog (36 skills)

| Category | Skills |
|----------|--------|
| Dev Workflow (6) | fix, commit, test, review, refactor, document |
| Research (6) | research, explore, deep-dive, analyze-errors, learn, teach |
| Framework Ops (6) | diagnose, super-health, introspect, status, wrap-up, audit |
| Quality/Security (2) | security-scan, benchmark |
| Build/Deploy (3) | build, deploy, report |
| Orchestration (5) | prp, wave, loop, chain, sprint |
| Advanced (5) | web, browser, ralph, super-evolve, super-prof-optimize |
| Creative (3) | brainstorm, writing-plans, domain |

Skills with scripts/: security-scan, status, super-health, web, wrap-up
User-invocable: benchmark, learn, introspect, security-scan, super-evolve, keybindings-help

---

## Agent Definitions (8 agents)

| Agent | Model (balanced profile) | Capabilities |
|-------|-------|-------------|
| researcher | sonnet | Read-only exploration: Glob, Grep, Read, WebFetch, WebSearch, memory |
| builder | sonnet | Full implementation: Edit, Write, Bash, NotebookEdit, memory, causal chain |
| debugger | sonnet | Diagnosis + fix: Edit, Write, Bash, causal chain tracking, log analysis |
| explore | sonnet | Fast codebase exploration: Read, Glob, Grep, memory (custom, gate 10 controlled) |
| plan | opus | Software architect: Read, Glob, Grep, Bash, memory (custom, gate 10 controlled) |
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

## Teams (5 definitions)

| Team | Purpose | Members |
|------|---------|---------|
| default | Inactive legacy | 2 (shutdown) |
| eclipse-rebase | Rebase ProjectDawn to Eclipse L2 | 5 (lead + 4 specialized) |
| framework-v2-4-1 | v2.4.1 sprint: dashboard, statusline | 1 builder |
| sprint-team | Self-improvement sprint | 10 (builders + researchers) |
| evolution-swarm-268 | Self-evolution swarm | — |

---

## Plugins (0 installed)

Plugin directory cleared. No plugins currently installed.

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
| Voice-Web | integrations/voice-web/ | WebSocket, Piper/edge-tts, multi-session tabs |
| Telegram Bot | integrations/telegram-bot/ | Bot API, SQLite msg_log.db (532KB) |
| Terminal History | integrations/terminal-history/ | FTS5, SQLite terminal_history.db (19.8MB) |
| LanceDB | ~/data/memory/lancedb/ | UDS socket (.chromadb.sock, legacy name) |
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
| session_summary_mode | "daemon+haiku" | Session end summary: haiku, daemon, or daemon+haiku |
| memory_classify_mode | "per_save" | Memory classification: tags_only, per_save, batch_end, batch_start |
| context_window_override | 1000000 | Override context window for 1M token recalculation |
| openrouter_api_key | — | OpenRouter API key(s) for summarizer daemon |
| summarizer_models | [...] | Model list with per-model API key overrides |

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
| Python files (hooks/) | 194 |
| Total lines (hooks/) | ~92,816 |
| Active gates | 19 (+ 2 dormant) |
| Shared modules | 83 |
| Top-level hooks | 28 |
| Boot pipeline files | 6 (1,241 lines) |
| Tracker pipeline files | 10 (1,552 lines) |
| Skills | 42 |
| Plugins | 0 |
| Agent definitions | 8 |
| Teams | 5 |
| MCP servers | 4 (memory, analytics, skills, model-router) |
| External orchestrators | 2 |
| Integrations | 3 |
| Session state files | 43 |
| Total memories | 3,026 |
| Largest file | hooks/tests/ (13 files, 29,417 lines) |

---

*Generated by Torus Framework — Session 432 (2026-03-16)*
