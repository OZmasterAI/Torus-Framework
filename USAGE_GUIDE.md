# Torus-Framework Usage Guide

## What Is This?

**Claude Code** is Anthropic's CLI tool for working with Claude. **Torus-framework** is a customization layer built on top of it that adds persistent memory, quality gates, session continuity, and enforced workflows.

```
┌─────────────────────────────────────────┐
│          torus-framework              │
│  (hooks, gates, memory, sessions)       │
│                                         │
│  ┌───────────────────────────────────┐  │
│  │         Claude Code v2.1.42       │  │
│  │    (Anthropic CLI — the engine)   │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

**Install location:** `~/.local/share/claude/versions/2.1.42`
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

Launching from `~` (home directory) still loads the framework (global config), but session tracking won't associate with the project.

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
`boot.py` runs on every launch and:
- Reads `HANDOFF.md` and `LIVE_STATE.json` from the previous session
- Injects recent memories from the knowledge base
- Resets per-session enforcement state
- Presents a summary: what was done, what's next, session number

You'll be asked: **"Continue or New task?"**
- **Continue** — pick up from where the last session left off
- **New task** — start fresh (handoff is archived, state is reset)

### During a Session
Work normally — ask Claude to fix bugs, add features, explore code, etc. The framework enforces quality automatically via gates (see below).

### Session End
Before ending a session, run:
```
/wrap-up
```
This generates a comprehensive handoff with:
- What was done (summary of changes)
- What's next (remaining work)
- Service status (memory, tests, gates)
- Session metrics (duration, tool calls, files modified, errors)

The `session_end.py` hook also runs automatically on exit to capture metrics even if you forget `/wrap-up`.

### Handoff Files
| File | Purpose | Format |
|---|---|---|
| `HANDOFF.md` | Human-readable session state | Markdown |
| `LIVE_STATE.json` | Machine-readable project state | JSON |

---

## Quality Gates

The framework enforces 15 quality gates that run **before every tool call** via `enforcer.py`. Gates either **block** (exit code 2) or **warn** (advisory).

### Blocking Gates (will stop you)

| Gate | Name | What It Does |
|---|---|---|
| 1 | Read Before Edit | Must read a `.py` file before editing it |
| 2 | No Destroy | Blocks `rm -rf`, `DROP TABLE`, force push, `reset --hard` |
| 3 | Test Before Deploy | Must run tests before deploying |
| 4 | Memory First | Must query memory before editing files |
| 5 | Proof Before Fixed | Must verify changes before making more |
| 7 | Critical File Guard | Extra checks when editing high-risk files (enforcer, memory_server, state) |
| 8 | Temporal Awareness | Extra caution during late-night hours |
| 9 | Strategy Ban | Blocks fix strategies that have failed multiple times |
| 10 | Model Cost Guard | Blocks expensive model usage without justification |
| 11 | Rate Limit | Blocks runaway tool-call loops |
| 13 | Workspace Isolation | Prevents concurrent file edits across agents |
| 14 | Confidence Check | Progressive readiness enforcement (3-strike escalation) |
| 15 | Causal Chain | Blocks edits after test failure until fix history is queried |

### Advisory Gates (warn only)

| Gate | Name | What It Does |
|---|---|---|
| 6 | Save Verified Fix | Warns when verified fixes aren't saved to memory |
| 12 | Plan Mode Save | Warns if exiting plan mode without saving to memory |

### Gate Tiers
- **Tier 1 (gates 1-3):** Safety gates. Fail-**closed** — if the gate crashes, the tool call is blocked.
- **Tier 2+ (gates 4-15):** Quality gates. Fail-**open** — if the gate crashes, a warning is logged but the tool call proceeds.

---

## Memory System

The framework includes a persistent memory system powered by ChromaDB, exposed via MCP (Model Context Protocol).

### What Gets Stored
| Collection | Contents | How It's Used |
|---|---|---|
| `knowledge` | Curated memories — fixes, decisions, discoveries | Searched before every edit (Gate 4) |
| `observations` | Auto-captured patterns from sessions | Background learning |
| `fix_outcomes` | Causal fix chains (what worked, what didn't) | Queried when errors repeat (Gate 15) |
| `web_pages` | Indexed web content | Searched via `/web` skill |

### Memory Tools
These are available as MCP tools during any session:

- **`search_knowledge(query)`** — Semantic search across memories
- **`remember_this(content, context, tags)`** — Save a new memory
- **`get_memory(id)`** — Retrieve full memory by ID
- **`query_fix_history(error_text)`** — Find what strategies worked/failed for an error
- **`record_attempt(error_text, strategy_id)`** — Log a fix attempt
- **`record_outcome(chain_id, outcome)`** — Log whether the fix worked
- **`maintenance(action)`** — Run maintenance (promotions, stale cleanup, clustering, health check)

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

## Slash Commands

Type these during a session to trigger specialized workflows:

| Command | Purpose |
|---|---|
| `/audit` | Run a 3-agent security/dependency/test audit |
| `/chain` | Track causal fix chains |
| `/commit` | Auto-generate a git commit with message |
| `/deep-dive` | Deep investigation of an issue |
| `/explore` | Explore the codebase |
| `/fix` | Fix a bug using memory + causal chain |
| `/loop` | Loop until success (test → fix → repeat) |
| `/profile` | Profile code performance |
| `/refactor` | Refactor code |
| `/research` | Research a topic |
| `/review` | Code review |
| `/status` | Show project status and metrics |
| `/test` | Run the test suite |
| `/web` | Index and search web pages |
| `/wrap-up` | Generate session handoff (run before ending) |

---

## Hooks

Hooks are shell commands that run in response to Claude Code events. They're registered in `~/.claude/settings.json`.

| Event | Hook | What It Does |
|---|---|---|
| **SessionStart** | `boot.py` | Load handoff, inject memories, reset state |
| **PreToolUse** | `enforcer.py` | Run all 15 quality gates |
| **PostToolUse** | `tracker.py` | Track files read/edited, errors, test results |
| **PostToolUse** (Edit/Write) | `auto_commit.py stage` | Auto-stage changed files |
| **UserPromptSubmit** | `user_prompt_capture.py` | Capture user prompts |
| **UserPromptSubmit** | `auto_commit.py commit` | Batch-commit staged changes |
| **PermissionRequest** | `auto_approve.py` | Auto-approve safe operations |
| **SubagentStart** | `subagent_context.py` | Inject context into sub-agents |
| **PreCompact** | `pre_compact.py` | Pre-compaction handling |
| **SessionEnd** | `session_end.py` | Generate handoff, flush observations, backup DB |
| **Notification** | `event_logger.py` | Log events |

---

## Key Files

```
~/.claude/
├── CLAUDE.md              # Global instructions (injected into every prompt)
├── HANDOFF.md             # Session handoff state
├── LIVE_STATE.json        # Machine-readable project state
├── settings.json          # Hook registration and config
├── mcp.json               # Memory MCP server config
├── rules/                 # Domain-specific rules (scoped, not always-injected)
│   ├── framework.md       # Shared module and state rules
│   ├── hooks.md           # Gate contract and exit codes
│   └── memory.md          # ChromaDB and MCP rules
├── hooks/                 # All hook scripts and gates
│   ├── enforcer.py        # Gate dispatcher
│   ├── boot.py            # Session start
│   ├── session_end.py     # Session end
│   ├── tracker.py         # PostToolUse state tracking
│   ├── memory_server.py   # MCP memory server
│   ├── gates/             # 15 gate modules
│   └── shared/            # Shared utilities (state, gate_result, etc.)
├── skills/                # 22 slash command definitions
└── memory/                # ChromaDB persistent storage
```

---

## Rules Files vs CLAUDE.md

- **`CLAUDE.md`** — Injected into **every** prompt. Keep it lean (<2,000 tokens). Only put universal rules here.
- **`rules/*.md`** — Scoped by file path patterns. Only injected when working on matching files. Put domain-specific guidance here.

| File | When It's Loaded |
|---|---|
| `CLAUDE.md` | Always |
| `rules/framework.md` | When touching `CLAUDE.md`, `settings.json`, or `hooks/shared/` |
| `rules/hooks.md` | When touching `hooks/` or `hooks/gates/` |
| `rules/memory.md` | When touching `memory_server.py` or MCP code |

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

### Checking system health
- `/status` — project status and metrics
- `maintenance("health")` — memory system health score
- `maintenance("stale")` — find old unused memories
- `maintenance("promotions")` — find patterns worth promoting to rules

---

## Current Status (as of Session 101)

| Metric | Value |
|---|---|
| Framework Version | v2.4.5 |
| Sessions Completed | 101 |
| Memories Stored | 452 |
| Tests Passing | 1,043 / 1,043 |
| Gate Enforcement | Mechanical (exit code 2) |
| Memory MCP | Active |
| ChromaDB Backup | Shipped |
| Ramdisk | Active |

---

## Troubleshooting

**"No recent activity" on welcome screen**
→ You launched from the wrong directory. Use `cd ~/.claude && claude`.

**Gate blocked my tool call**
→ Read the gate message — it tells you what's required (e.g., "read the file first", "query memory first"). Satisfy the requirement and retry.

**Memory search returns nothing relevant**
→ Try different search terms or use `mode: "keyword"` for exact matches. Check `maintenance("health")` for system status.

**Session handoff is stale**
→ Run `/wrap-up` before ending sessions. If you forgot, `session_end.py` writes basic metrics automatically.

**ChromaDB segfault in tests**
→ Known issue — ChromaDB can't handle concurrent access. Tests that need ChromaDB skip when the MCP server is running. Stop the MCP server or run tests in isolation.

**Plan mode exit loop**
→ Known issue — if `ExitPlanMode` is rejected twice, you can get stuck. Ask Claude to stop and adjust the plan, or start a new message.
