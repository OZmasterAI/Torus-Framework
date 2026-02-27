# Torus-Framework Usage Guide

## What Is This?

**Claude Code** is Anthropic's CLI tool for working with Claude. **Torus-framework** is a customization layer built on top of it that adds persistent multi-tier memory, quality gates, session continuity, and enforced workflows.

```
┌─────────────────────────────────────────┐
│          torus-framework v2.6           │
│  (hooks, gates, memory, sessions)       │
│                                         │
│  ┌───────────────────────────────────┐  │
│  │       Claude Code v2.1.52        │  │
│  │    (Anthropic CLI — the engine)   │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

**Framework location:** `~/.claude/`

For deeper architectural details, see `ARCHITECTURE.md`.

---

## Launching

Always launch from the project directory:

```bash
cd ~/.claude && claude
```

This ensures:
- Session history appears in the welcome screen
- Git context is detected
- Relative paths work naturally

**Tip:** Add an alias to `~/.bashrc`:
```bash
alias cc='cd ~/.claude && claude'
```

---

## Session Lifecycle

Every session follows a predictable lifecycle managed by hooks:

```
Launch → boot.py runs → Handoff presented → You work → /wrap-up → session_end.py runs → Exit
```

### Session Start (automatic)
`boot.py` runs on every launch (20-step pipeline) and:
- Initializes the ramdisk for fast I/O (~544 MB/s tmpfs at `/run/user/{uid}/claude-hooks/`)
- Rotates and compresses audit logs
- Reads `HANDOFF.md` and `LIVE_STATE.json` from the previous session
- Injects recent memories from ChromaDB (L1)
- Pulls relevant Telegram message history (L2/L3 fallback)
- Writes the Gate 4 sideband timestamp so memory-first checks pass
- Resets per-session enforcement state
- Presents a summary: what was done, what's next, session number

You'll be asked: **"Continue or New task?"**
- **Continue** — pick up from where the last session left off
- **New task** — start fresh (handoff is archived, state is reset)

### During a Session
Work normally — ask Claude to fix bugs, add features, explore code, etc. The framework enforces quality automatically via 17 gates (see below). The tracker pipeline (17 steps, PostToolUse) records every action and the Mentor System evaluates quality signals in real time.

### Session End
Before ending a session, run:
```
/wrap-up
```
This generates a comprehensive handoff with:
- What was done (summary of changes)
- What's next (remaining work)
- Service status (memory, tests, gates)

The `session_end.py` hook also runs automatically on exit to flush observations and update metrics.

### Handoff Files
| File | Purpose | Format |
|---|---|---|
| `HANDOFF.md` | Human-readable session state | Markdown |
| `LIVE_STATE.json` | Machine-readable project state | JSON |

### Boot Flow (20 steps)
1. Bot session check
2. Ramdisk init
3. Audit log rotation
4. Load LIVE_STATE.json
5. Memory injection (ChromaDB UDS socket)
6. Telegram L2 memories
7. Gate auto-tuning
8. Error extraction
9. Tool activity summary
10. Test status
11. Verification quality
12. Session duration
13. Gate block stats
14. Dashboard generation (stderr)
15. Context injection (stdout)
16. State reset
17. Auto-tune overrides
18. Workspace claims cleanup
19. Capture queue flush
20. Auto-remember ingestion + sideband write

---

## Quality Gates

The framework enforces 17 quality gates that run **before every tool call** via the enforcer pipeline. Gates either **block** (exit code 2) or **warn** (advisory).

The enforcer has 3 modes: **daemon** (persistent process, ~5ms via UDS socket), **shim** (connects to daemon), and **inline** (fallback, ~134ms). Gates are Q-learning optimized — high-block-rate gates get promoted to run earlier.

### Tier 1 — Safety (Fail-Closed)
If these gates crash, the tool call is **blocked**.

| Gate | Name | What It Does |
|---|---|---|
| 1 | Read Before Edit | Must read a `.py` file before editing it |
| 2 | No Destroy | Blocks `rm -rf`, `DROP TABLE`, force push, `reset --hard` (47 patterns) |
| 3 | Test Before Deploy | Must run tests before deploying (scp, docker push, kubectl apply, npm publish) |

### Tier 2 — Quality (Fail-Open)
If these gates crash, a warning is logged but the tool call **proceeds**.

| Gate | Name | What It Does |
|---|---|---|
| 4 | Memory First | Blocks edits if memory not queried in last 5 min. Uses sideband file for verification |
| 5 | Proof Before Fixed | Blocks edits to new files when 3+ files are unverified |
| 6 | Save To Memory | Warns (then blocks) when verified fixes aren't saved to memory |
| 9 | Strategy Ban | Blocks fix strategies that failed 3+ times; auto-defers to PRP |
| 10 | Model Cost Guard | Enforces model selection within budget tier |
| 11 | Rate Limit | Blocks >60 tool calls/min (warns at >40). 120s rolling window |
| 13 | Workspace Isolation | Prevents concurrent file edits across agents (main session exempt) |
| 14 | Confidence Check | Progressive: warn 2x per file, block on 3rd unverified edit |
| 15 | Causal Chain | Blocks edits after test failure until `query_fix_history` is called |
| 16 | Code Quality | Catches debug prints, hardcoded secrets, broad excepts. 3 warnings → block |

### Tier 3 — Advanced
| Gate | Name | What It Does |
|---|---|---|
| 17 | Injection Defense | Detects prompt injection in tool inputs (base64, ROT13, homoglyphs, zero-width) |
| 18 | Canary Monitor | Passive monitoring — never blocks. Detects bursts and repeated sequences |
| 19 | Hindsight | Reads mentor signals; blocks on sustained poor quality (score < 0.3) |

---

## Memory System

The framework has a **three-tier memory architecture**. Search cascades through tiers automatically — you do not need to manually pick a tier.

```
L1: ChromaDB (curated, semantic)
 └── L2: Terminal History (FTS5, full-text, recent sessions)
      └── L3: Telegram (FTS5, message history fallback)
```

### L1 — ChromaDB (Primary Curated Memory)

The main memory store. ~1,341 entries. Accessed via MCP tools (`search_knowledge`, `remember_this`, etc.).

- **Embedding model:** nomic-ai/nomic-embed-text-v2-moe (768-dim, 8192 token context)
- **Storage:** `~/data/memory/` (ChromaDB SQLite)
- **Access:** UDS socket (`.chromadb.sock`) — serializes all hook-side access to prevent segfaults
- **Collections:**
  - `knowledge` — curated memories: fixes, decisions, discoveries
  - `observations` — auto-captured tool call patterns (flushed from `.capture_queue.jsonl` on SessionStart/SessionEnd)
- **Search modes:** keyword, semantic, hybrid, tags, observations, all, code
- **Dedup:** cosine similarity > 0.85 blocks duplicate writes
- **Scoring:** FNV-1a hash IDs; recency boost with 365-day decay; tag co-occurrence expansion

### L2 — Terminal History (Full-Text Search)

FTS5 full-text search over all past session JSONL transcripts. Always-on — every session is indexed automatically on exit.

- **Location:** `integrations/terminal-history/terminal_history.db` (19.8 MB SQLite)
- **Access:** Analytics MCP tool `terminal_history_search(query, limit)`
- **Index:** ~3,500+ records across all past sessions
- **Relevance weight:** 0.25 (higher than L3 — local conversations are high-value)
- **Trigger:** Cascades in when L1 returns results below the 0.3 threshold

### L3 — Telegram Message History

FTS5 search over the Telegram bot's message log. Useful for things discussed outside active sessions.

- **Location:** `integrations/telegram-bot/msg_log.db`
- **Access:** Analytics MCP tool `telegram_search(query, limit)`
- **Relevance weight:** 0.2
- **Trigger:** Cascades in when L1+L2 still fall short

### L3 — Observations (Auto-Captured Patterns)

Compressed tool call patterns are auto-captured on every PostToolUse event, queued to `.capture_queue.jsonl`, and flushed into the ChromaDB `observations` collection on SessionStart and SessionEnd. No manual interaction needed.

### Memory Tools (MCP — L1)

| Tool | Purpose |
|---|---|
| `search_knowledge(query)` | Semantic search (7 modes). Triggers L2/L3 cascade if L1 results are weak |
| `remember_this(content, context, tags)` | Save a new memory with automatic dedup check |
| `get_memory(id)` | Retrieve full memory by ID (supports comma-separated batch) |
| `query_fix_history(error_text)` | Find what strategies worked or failed for a given error |
| `record_attempt(error_text, strategy_id)` | Log a fix attempt; returns `chain_id` |
| `record_outcome(chain_id, outcome)` | Log whether the fix succeeded or failed |

### The Memory-First Rule
Gate 4 enforces: **always search memory before editing code**. This prevents re-discovering things that were already learned and avoids repeating failed fix strategies. The sideband file `hooks/.memory_last_queried` is written by `boot.py` and updated by every `search_knowledge` call.

### Causal Chain Workflow
When fixing errors, the framework enforces a 5-step process:
1. `query_fix_history("error text")` — check what's been tried before
2. `record_attempt("error text", "strategy-name")` — log what you're about to try
3. Fix and verify with tests
4. `record_outcome(chain_id, "success" | "failure")` — log the result
5. `remember_this(...)` — save the fix for future reference

Gate 15 enforces step 1 — you cannot edit after a test failure until you call `query_fix_history`.

---

## Tracker Pipeline and Mentor System

After every tool call, `tracker.py` runs a 17-step PostToolUse pipeline:

1. Increment tool_call_count
2. Token estimation (Bash: 2000, Edit: 1500, Read: 800)
3. Resolve gate blocks
4. Auto-expire `fixing_error` state (30 min)
5. Track file reads
6. Track file edits
7. Write file claims (workspace isolation)
8. Track memory queries
9. Error detection (60s dedup window)
10. Observation capture (queue to `.capture_queue.jsonl`)
11. Verification scoring
12. Auto-remember (high-value events)
13. Outcome chains (causal chain tracking)
14. Mentor evaluation
15. Generate verdict
16. Gate effectiveness tracking
17. Save state

### Mentor System (Module A)
`tracker_pkg/mentor.py` — deterministic signal analysis. **No LLM calls.**

For every tool call, it:
- Classifies Bash calls (test run / file operation / search)
- Parses exit codes and stdout patterns
- Evaluates edit operations for unverified file count
- Generates a 0.0–1.0 quality score with a verdict: `proceed` / `advise` / `warn` / `escalate`

Gate 19 (Hindsight) reads these verdicts and blocks on sustained poor quality. The mentor system also includes Module D (outcome chains) and Module E (memory-backed pattern learning).

---

## MCP Servers

### Memory MCP (`memory_server.py` — 4,188 lines)
- **Purpose:** Persistent knowledge storage and retrieval
- **Backend:** ChromaDB with UDS socket (`.chromadb.sock`)
- **Tools:** 6 (search_knowledge, remember_this, get_memory, record_attempt, record_outcome, query_fix_history)

### Analytics MCP (`analytics_server.py` — 379 lines)
- **Purpose:** Read-only framework analytics — lazy-loaded, no ChromaDB dependency
- **Tools:** 10

| Tool | Purpose |
|---|---|
| `framework_health` | 0-100 health score, per-component status |
| `session_summary` | Tool distribution, gate effectiveness, error rates |
| `gate_dashboard` | Ranked gates by block rate and coverage |
| `gate_timing` | Per-gate latency stats |
| `detect_anomalies` | Bursts, high block rates, error spikes, memory gaps |
| `skill_health` | Total/healthy/broken skill counts |
| `all_metrics` | Counters, gauges, histograms + rollups |
| `telegram_search` | FTS5 search over Telegram message history (L3) |
| `terminal_history_search` | FTS5 search over session transcripts (L2) |
| `web_search` | ChromaDB semantic search over indexed web pages |

---

## Slash Commands (Skills)

Type these during a session to trigger specialized workflows. **34 skills** available:

| Category | Commands |
|---|---|
| **Dev Workflow** | `/fix`, `/commit`, `/test`, `/review`, `/refactor`, `/document` |
| **Research** | `/research`, `/explore`, `/deep-dive`, `/analyze-errors`, `/learn`, `/teach` |
| **Framework Ops** | `/diagnose`, `/health-report`, `/super-health`, `/introspect`, `/status`, `/wrap-up`, `/audit` |
| **Quality** | `/security-scan`, `/benchmark` |
| **Build/Deploy** | `/build`, `/deploy`, `/report` |
| **Orchestration** | `/prp`, `/wave`, `/loop`, `/chain`, `/sprint` |
| **Advanced** | `/web`, `/browser`, `/ralph`, `/super-evolve`, `/super-prof-optimize` |

Skills with associated scripts: `health-report`, `security-scan`, `status`, `super-health`, `web`, `wrap-up`.

---

## Hooks

Hooks are shell commands that run in response to Claude Code events. Registered in `~/.claude/settings.json`.

| Event | Hook | What It Does |
|---|---|---|
| **SessionStart** | `boot.py` | 20-step boot: ramdisk init, memory inject, context extraction, state reset |
| **SessionStart** | `integrity_check.py` | SHA256 integrity verification of framework files |
| **PreToolUse** | `enforcer_shim.py` | Run 17 quality gates via daemon (~5ms UDS) |
| **PostToolUse** | `tracker.py` | 17-step pipeline: errors, observations, mentor verdicts |
| **PostToolUse** (Edit/Write) | `auto_commit.py stage` | Auto-stage changed files |
| **PostToolUse** (Edit/Write) | `auto_format.py` | Auto-format edited Python files (ruff/black, 3s timeout) |
| **UserPromptSubmit** | `user_prompt_capture.py` | Capture user prompts to queues |
| **UserPromptSubmit** | `auto_commit.py commit` | Batch-commit staged changes |
| **PermissionRequest** | `auto_approve.py` | Auto-approve safe operations |
| **SubagentStart** | `subagent_context.py` | Inject LIVE_STATE + session context into sub-agents |
| **PreCompact** | `pre_compact.py` | Snapshot gate state before context compression |
| **SessionEnd** | `session_end.py` | Flush observations, update LIVE_STATE, backup ChromaDB |
| **Stop** | `tg_mirror.py` | Mirror response to Telegram |
| **Stop** | `stop_cleanup.py` | Flush I/O, close handles, shutdown daemons |
| **PostToolUseFailure** | `failure_recovery.py` | Error recovery triage |
| **ConfigChange** | `config_change.py` | Hot-reload `config.json` toggles |

---

## Key Files

```
~/.claude/
├── CLAUDE.md              # Global instructions (injected every prompt, <2K tokens)
├── HANDOFF.md             # Session handoff state
├── LIVE_STATE.json        # Machine-readable project state
├── ARCHITECTURE.md        # Full framework architecture reference
├── config.json            # Runtime toggles (mentor, ramdisk, Telegram, etc.)
├── settings.json          # Hook registration, permissions, config
├── mcp.json               # MCP server config (memory + analytics)
├── rules/                 # Domain-specific rules (scoped, not always-injected)
│   ├── framework.md       # Shared module and state rules
│   ├── hooks.md           # Gate contract and exit codes
│   └── memory.md          # ChromaDB and MCP rules
├── hooks/                 # All hook scripts and gates (113 Python files, ~48K lines)
│   ├── enforcer_shim.py   # Gate dispatcher (UDS to daemon, ~5ms)
│   ├── enforcer_daemon.py # Persistent gate executor
│   ├── enforcer.py        # Inline fallback (632 lines, ~134ms)
│   ├── boot.py            # SessionStart shim → boot_pkg/
│   ├── boot_pkg/          # Boot pipeline (6 files, 848 lines)
│   ├── tracker.py         # PostToolUse shim → tracker_pkg/
│   ├── tracker_pkg/       # Tracker pipeline + Mentor System (10 files, 1,537 lines)
│   ├── session_end.py     # Session end handler (554 lines)
│   ├── memory_server.py   # Memory MCP server (4,188 lines)
│   ├── analytics_server.py# Analytics MCP server (379 lines)
│   ├── test_framework.py  # Gate test suite (11,904 lines)
│   ├── gates/             # 17 gate modules
│   ├── shared/            # 50 shared utility modules (~19,458 lines)
│   ├── .audit_trail.jsonl # Full tool call audit trail (46.3 MB)
│   ├── .capture_queue.jsonl # Observation queue (flushed each session)
│   ├── .chromadb.sock     # ChromaDB UDS socket
│   └── .enforcer.sock     # Enforcer daemon UDS socket
├── skills/                # 34 slash command definitions
├── agents/                # 6 agent type definitions
├── teams/                 # 4 team configurations
├── plugins/               # 9 plugins (3 LSP, 5 dev, 1 quality)
├── scripts/
│   ├── torus-loop.sh      # Sequential task executor (261 lines)
│   └── torus-wave.py      # Parallel wave orchestrator (477 lines)
└── integrations/
    ├── telegram-bot/      # Telegram bot (SQLite msg_log.db, 532 KB)
    └── terminal-history/  # FTS5 session indexer (terminal_history.db, 19.8 MB)
```

---

## Agent Types (6) and Teams (4)

### Agent Definitions

| Agent | Model | Role |
|---|---|---|
| `researcher` | haiku | Read-only exploration: Glob, Grep, Read, WebFetch, memory |
| `builder` | sonnet | Full implementation: Edit, Write, Bash, NotebookEdit, memory, causal chain |
| `debugger` | sonnet | Diagnosis and fix: Edit, Write, Bash, causal chain, log analysis |
| `stress-tester` | sonnet | Test execution and verification |
| `perf-analyzer` | sonnet | Performance profiling (read-only + Bash for benchmarks) |
| `security` | sonnet | Security audit (read-only + Bash scanning) |

### Delegation Rules

```
2-5 steps, independent   → Sub-agents (parallel)
2-5 steps, dependent     → Sub-agents (lead orchestrates, memory bridges)
5-7 steps                → Either (teams preferred)
7+ steps                 → Agent teams (real-time coordination)
Cross-session            → Sub-agents + memory
```

### Team Definitions

| Team | Purpose |
|---|---|
| `default` | Inactive legacy |
| `eclipse-rebase` | Rebase ProjectDawn to Eclipse L2 (5 members) |
| `framework-v2-4-1` | v2.4.1 sprint: dashboard, statusline |
| `sprint-team` | Self-improvement sprint (10 builders + researchers) |

---

## Infrastructure Highlights

### Ramdisk (Hybrid I/O)
All hot I/O runs on a tmpfs ramdisk at `/run/user/{uid}/claude-hooks/` — approximately 544 MB/s vs ~1.2 MB/s on disk. This covers:
- Audit logs
- Per-session state files
- Observation capture queue

Audit logs get an async disk mirror via daemon thread. State files and the capture queue are ephemeral (ramdisk only). Graceful fallback everywhere via `is_ramdisk_available()`. Setup: `bash hooks/setup_ramdisk.sh`.

### Enforcer Daemon
The enforcer runs as a persistent UDS server so gate evaluation costs ~5ms instead of ~134ms for the inline fallback. Gates are Q-learning optimized — the system reorders them based on historical block probability to short-circuit expensive checks.

### Circuit Breakers and Resilience
`shared/circuit_breaker.py` tracks per-service failure state (CLOSED/OPEN/HALF_OPEN). `shared/retry_strategy.py` provides exponential/fibonacci backoff with jitter. Rate limiting uses a token bucket model (`shared/rate_limiter.py`).

---

## Rules Files vs CLAUDE.md

- **`CLAUDE.md`** — Injected into **every** prompt. Keep it lean (<2,000 tokens). Only put universal rules here.
- **`rules/*.md`** — Scoped by file path patterns. Only injected when working on matching files.

---

## Common Workflows

### Starting a new feature
1. Launch: `cd ~/.claude && claude`
2. Say "New task" at the handoff prompt
3. Describe what you want to build
4. Claude will search memory (L1), plan, implement, test, and save

### Fixing a bug
1. Describe the error or paste the traceback
2. The causal chain kicks in: memory is searched for past fixes
3. If a strategy failed before, Gate 9 blocks it from being tried again
4. Fix is verified with tests before being marked done

### Searching memory across tiers
- **L1 (ChromaDB):** `search_knowledge("your query")` — semantic search, 7 modes
- **L2 (Terminal history):** `terminal_history_search("query")` via Analytics MCP — FTS5 over past sessions
- **L3 (Telegram):** `telegram_search("query")` via Analytics MCP — FTS5 over message history
- The cascade triggers automatically in `search_knowledge` when L1 results fall below the 0.3 relevance threshold

### Ending a session cleanly
1. Type `/wrap-up` before ending
2. Review the generated handoff
3. Exit — `session_end.py` saves metrics, flushes observations, and backs up ChromaDB
4. Next session picks up right where you left off

---

## Troubleshooting

**Gate blocked my tool call**
→ Read the gate message — it tells you exactly what's required (e.g., "read the file first", "query memory first"). Satisfy the requirement and retry.

**Memory search returns nothing relevant**
→ Try different search terms or use `mode: "keyword"` for exact matches. L2 terminal history is also available via `terminal_history_search` for past-session context.

**Session handoff is stale**
→ Run `/wrap-up` before ending sessions. If you forgot, `session_end.py` writes basic metrics automatically.

**ChromaDB segfault in tests**
→ Known issue — ChromaDB cannot handle concurrent access. Tests skip automatically when the MCP server is running.

**Plan mode exit loop**
→ Known issue — if `ExitPlanMode` is rejected twice, you can get stuck. Ask Claude to stop and adjust the plan before trying again.

**Gate 4 fires even though I searched memory**
→ The sideband file `hooks/.memory_last_queried` must be updated within 5 minutes. If the ramdisk is not mounted, the sideband write may fail. Run `bash hooks/setup_ramdisk.sh` to reinitialize.

**Mentor verdicts showing `escalate`**
→ The Mentor System (Module A) in `tracker_pkg/mentor.py` has flagged sustained quality issues. Check test results and unverified file count. Run `/health-report` for a detailed breakdown.
