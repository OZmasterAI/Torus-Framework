# Torus-Framework Usage Guide

## What Is This?

**Claude Code** is Anthropic's CLI tool for working with Claude. **Torus-framework** is a customization layer built on top of it that adds persistent memory, quality gates, session continuity, and enforced workflows.

```
┌─────────────────────────────────────────┐
│          torus-framework v2.5.3         │
│  (hooks, gates, memory, sessions)       │
│                                         │
│  ┌───────────────────────────────────┐  │
│  │       Claude Code v2.1.52        │  │
│  │    (Anthropic CLI — the engine)   │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

**Framework location:** `~/.claude/`

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
- Reads `HANDOFF.md` and `LIVE_STATE.json` from the previous session
- Initializes ramdisk for fast I/O
- Injects recent memories from ChromaDB
- Resets per-session enforcement state
- Presents a summary: what was done, what's next, session number

You'll be asked: **"Continue or New task?"**
- **Continue** — pick up from where the last session left off
- **New task** — start fresh (handoff is archived, state is reset)

### During a Session
Work normally — ask Claude to fix bugs, add features, explore code, etc. The framework enforces quality automatically via 17 gates (see below).

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

---

## Quality Gates

The framework enforces 17 quality gates that run **before every tool call** via the enforcer pipeline. Gates either **block** (exit code 2) or **warn** (advisory).

The enforcer has 3 modes: **daemon** (persistent process, ~5ms via UDS socket), **shim** (connects to daemon), and **inline** (fallback, ~134ms).

### Tier 1 — Safety (Fail-Closed)
If these gates crash, the tool call is **blocked**.

| Gate | Name | What It Does |
|---|---|---|
| 1 | Read Before Edit | Must read a `.py` file before editing it |
| 2 | No Destroy | Blocks `rm -rf`, `DROP TABLE`, force push, `reset --hard` |
| 3 | Test Before Deploy | Must run tests before deploying |

### Tier 2 — Quality (Fail-Open)
If these gates crash, a warning is logged but the tool call **proceeds**.

| Gate | Name | What It Does |
|---|---|---|
| 4 | Memory First | Must query memory before editing files |
| 5 | Proof Before Fixed | Must verify changes before making more |
| 6 | Save To Memory | Warns when verified fixes aren't saved to memory |
| 9 | Strategy Ban | Blocks fix strategies that have failed multiple times |
| 10 | Model Cost Guard | Blocks expensive model usage without justification |
| 11 | Rate Limit | Blocks runaway tool-call loops (rolling window) |
| 13 | Workspace Isolation | Prevents concurrent file edits across agents |
| 14 | Confidence Check | Progressive readiness enforcement (3-strike escalation) |
| 15 | Causal Chain | Blocks edits after test failure until fix history is queried |
| 16 | Code Quality | Blocks repeated bad patterns (debug prints, hardcoded secrets, broad excepts) |

### Tier 3 — Advanced
| Gate | Name | What It Does |
|---|---|---|
| 17 | Injection Defense | Detects prompt injection attempts in tool inputs |
| 18 | Canary Monitor | Passive monitoring, never blocks |
| 19 | Hindsight | Post-action analysis and feedback |

---

## Memory System

The framework includes a persistent memory system powered by ChromaDB (nomic-embed-text-v2-moe, 768-dim embeddings), exposed via MCP.

### Collections
| Collection | Contents |
|---|---|
| `knowledge` | Curated memories — fixes, decisions, discoveries (~1,300+ entries) |
| `observations` | Auto-captured patterns from sessions |

### Memory Tools (MCP)
- **`search_knowledge(query)`** — Semantic search (7 modes: keyword, semantic, hybrid, tags, observations, all, code)
- **`remember_this(content, context, tags)`** — Save a new memory with dedup check
- **`get_memory(id)`** — Retrieve full memory by ID
- **`query_fix_history(error_text)`** — Find what strategies worked/failed for an error
- **`record_attempt(error_text, strategy_id)`** — Log a fix attempt (causal chain)
- **`record_outcome(chain_id, outcome)`** — Log whether the fix worked

### The Memory-First Rule
Gate 4 enforces: **always search memory before editing code**. This prevents re-discovering things that were already learned and avoids repeating failed strategies.

### Causal Chain Workflow
When fixing errors, the framework enforces a 5-step process:
1. `query_fix_history("error text")` — check what's been tried before
2. `record_attempt("error text", "strategy-name")` — log what you're about to try
3. Fix and verify with tests
4. `record_outcome(chain_id, "success" | "failure")` — log the result
5. `remember_this(...)` — save the fix for future reference

---

## MCP Servers

### Memory MCP (4,188 lines)
- **Purpose**: Persistent knowledge storage and retrieval
- **Backend**: ChromaDB with UDS socket (`.chromadb.sock`)
- **Tools**: 6 (search_knowledge, remember_this, get_memory, record_attempt, record_outcome, query_fix_history)

### Analytics MCP (379 lines)
- **Purpose**: Read-only framework analytics
- **Tools**: 10 (framework_health, session_summary, gate_dashboard, gate_timing, detect_anomalies, skill_health, all_metrics, telegram_search, terminal_history_search, web_search)
- No ChromaDB dependency, near-instant startup

---

## Slash Commands (Skills)

Type these during a session to trigger specialized workflows. 34 skills available:

| Category | Commands |
|---|---|
| **Dev Workflow** | `/fix`, `/commit`, `/test`, `/review`, `/refactor`, `/document` |
| **Research** | `/research`, `/explore`, `/deep-dive`, `/analyze-errors`, `/learn`, `/teach` |
| **Framework Ops** | `/diagnose`, `/health-report`, `/super-health`, `/introspect`, `/status`, `/wrap-up`, `/audit` |
| **Quality** | `/security-scan`, `/benchmark` |
| **Build/Deploy** | `/build`, `/deploy`, `/report` |
| **Orchestration** | `/prp`, `/wave`, `/loop`, `/chain`, `/sprint` |
| **Advanced** | `/web`, `/browser`, `/ralph`, `/super-evolve`, `/super-prof-optimize` |

---

## Hooks

Hooks are shell commands that run in response to Claude Code events. Registered in `~/.claude/settings.json`.

| Event | Hook | What It Does |
|---|---|---|
| **SessionStart** | `boot.py` | 20-step boot: ramdisk, memory inject, context, state reset |
| **SessionStart** | `integrity_check.py` | SHA256 integrity verification |
| **PreToolUse** | `enforcer_shim.py` | Run 17 quality gates via daemon (~5ms) |
| **PostToolUse** | `tracker.py` | 17-step pipeline: errors, observations, mentor verdicts |
| **PostToolUse** (Edit/Write) | `auto_commit.py stage` | Auto-stage changed files |
| **PostToolUse** (Edit/Write) | `auto_format.py` | Auto-format edited files |
| **UserPromptSubmit** | `user_prompt_capture.py` | Capture user prompts |
| **UserPromptSubmit** | `auto_commit.py commit` | Batch-commit staged changes |
| **PermissionRequest** | `auto_approve.py` | Auto-approve safe operations |
| **SubagentStart** | `subagent_context.py` | Inject LIVE_STATE + session context into sub-agents |
| **PreCompact** | `pre_compact.py` | Pre-compaction handling |
| **SessionEnd** | `session_end.py` | Flush observations, update LIVE_STATE, backup DB |
| **Stop** | `tg_mirror.py` | Mirror to Telegram |
| **Stop** | `stop_cleanup.py` | Cleanup on stop |
| **PostToolUseFailure** | `failure_recovery.py` | Error recovery handling |
| **ConfigChange** | `config_change.py` | React to settings changes |

---

## Key Files

```
~/.claude/
├── CLAUDE.md              # Global instructions (injected into every prompt, <2K tokens)
├── HANDOFF.md             # Session handoff state
├── LIVE_STATE.json        # Machine-readable project state
├── ARCHITECTURE.md        # Full framework architecture reference
├── settings.json          # Hook registration, permissions, config
├── mcp.json               # MCP server config (memory + analytics)
├── rules/                 # Domain-specific rules (scoped, not always-injected)
│   ├── framework.md       # Shared module and state rules
│   ├── hooks.md           # Gate contract and exit codes
│   └── memory.md          # ChromaDB and MCP rules
├── hooks/                 # All hook scripts and gates
│   ├── enforcer_shim.py   # Gate dispatcher (UDS to daemon)
│   ├── enforcer_daemon.py # Persistent gate executor
│   ├── enforcer.py        # Inline fallback (632 lines)
│   ├── boot.py            # Session start orchestrator
│   ├── boot_pkg/          # Boot pipeline modules (4 files)
│   ├── tracker.py         # PostToolUse orchestrator
│   ├── tracker_pkg/       # Tracker pipeline modules (8 files)
│   ├── session_end.py     # Session end handler
│   ├── memory_server.py   # Memory MCP server (4,188 lines)
│   ├── analytics_server.py# Analytics MCP server (379 lines)
│   ├── gates/             # 17 gate modules
│   └── shared/            # ~50 shared utility modules
├── skills/                # 34 slash command definitions
├── agents/                # 6 agent type definitions
├── teams/                 # Team configs (historical)
├── plugins/               # 9 plugins (3 LSP, 5 dev, 1 quality)
└── integrations/          # Telegram bot, terminal history indexer
```

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
4. Claude will search memory, plan, implement, test, and save

### Fixing a bug
1. Describe the error or paste the traceback
2. The causal chain kicks in: memory is searched for past fixes
3. If a strategy failed before, Gate 9 blocks it from being tried again
4. Fix is verified with tests before being marked done

### Ending a session cleanly
1. Type `/wrap-up` before ending
2. Review the generated handoff
3. Exit — `session_end.py` saves metrics and backs up the database
4. Next session picks up right where you left off

---

## Troubleshooting

**Gate blocked my tool call**
→ Read the gate message — it tells you what's required (e.g., "read the file first", "query memory first"). Satisfy the requirement and retry.

**Memory search returns nothing relevant**
→ Try different search terms or use `mode: "keyword"` for exact matches.

**Session handoff is stale**
→ Run `/wrap-up` before ending sessions. If you forgot, `session_end.py` writes basic metrics automatically.

**ChromaDB segfault in tests**
→ Known issue — ChromaDB can't handle concurrent access. Tests skip when the MCP server is running.

**Plan mode exit loop**
→ Known issue — if `ExitPlanMode` is rejected twice, you can get stuck. Ask Claude to stop and adjust the plan.
