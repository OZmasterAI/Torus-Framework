<p align="center">
  <h1 align="center">🔄 Torus Framework</h1>
  <p align="center">
    <em>A self-evolving quality framework for <a href="https://docs.anthropic.com/en/docs/claude-code">Claude Code</a></em>
  </p>
  <p align="center">
    <a href="https://github.com/OZmasterAI/Torus-Framework/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-blue.svg" alt="License"></a>
    <img src="https://img.shields.io/badge/Python-3.10+-green.svg" alt="Python">
    <img src="https://img.shields.io/badge/Platform-Linux-lightgrey.svg" alt="Platform">
    <img src="https://img.shields.io/badge/Framework-v3.2.0-orange.svg" alt="Version">
  </p>
</p>

---

Torus wraps Claude Code with persistent memory, 21 quality gates, automated hooks, self-evolving skills, and a unified MCP gateway — turning it from a stateless CLI into a disciplined, self-improving development partner.

> **830 Python files** · **~217K lines** · **21 active gates** · **54 skills** · **7 MCP servers** · **14 hook events**

---

## ⚡ Quick Start

```bash
# 1. Clone with submodules (toolshed + torus-skills)
git clone --recurse-submodules https://github.com/OZmasterAI/Torus-Framework.git ~/.claude

# 2. Run setup (installs deps, copies templates, sets up ramdisk)
bash ~/.claude/setup.sh

# 3. Edit mcp.json — replace $HOME with your actual home directory path
$EDITOR ~/.claude/mcp.json

# 4. Launch Claude Code
cd ~/.claude && claude
```

On first launch, SessionStart hooks bootstrap the enforcer daemon, start MCP servers, load memory, and initialize state.

<details>
<summary><strong>Manual setup (if not using setup.sh)</strong></summary>

```bash
# Initialize submodules
cd ~/.claude && git submodule update --init --recursive

# Install Python dependencies
pip install -r ~/.claude/hooks/requirements.txt

# Copy config templates
cp ~/.claude/config.example.json ~/.claude/config.json
cp ~/.claude/mcp.example.json ~/.claude/mcp.json

# Set up the ramdisk (persistent tmpfs for fast state I/O)
bash ~/.claude/hooks/setup_ramdisk.sh
```

</details>

---

## 🔌 Toolshed (MCP Gateway)

All MCP tools route through a single gateway — **Toolshed** — which multiplexes requests to backend servers over HTTP or stdio:

| Server | Port | Purpose |
|--------|------|---------|
| **memory** | 8742 | LanceDB semantic search, causal fix tracking, observations |
| **torus-skills** | 8743 | 54 skills with usage tracking, self-evolution, lineage |
| **search** | 8744 | Terminal history FTS5, transcript context |
| **web-search** | 8745 | Web search integration |
| **analytics** | 8746 | Read-only gate dashboard, framework health metrics |
| **model-router** | 8747 | Model fan-out, comparison, scheduling |
| **torus** | stdio | Torus web proxy (connects to localhost:3000) |

Claude Code registers only toolshed in `mcp.json`. Toolshed handles routing, timeouts, and error isolation.

```
Claude Code → mcp.json → Toolshed → { memory, torus-skills, search, web-search, analytics, model-router, torus }
```

Usage: `run_tool("memory", "search_knowledge", {"query": "..."})`

---

## 🎯 What It Does

| Feature | Description |
|---------|-------------|
| **21 Quality Gates** | Mechanical enforcement — read before edit, test before deploy, memory-first, no-destroy, injection defense, self-check, and more |
| **Persistent Memory** | LanceDB with semantic search, causal fix tracking, tag indexing, and auto-captured observations |
| **Hook Pipeline** | 14 lifecycle events — SessionStart, PreToolUse, PostToolUse, Stop, SubagentStart, PreCompact, ConfigChange, and more |
| **54 Skills** | Slash commands via torus-skills — `/commit`, `/brainstorm`, `/writing-plans`, `/prp`, `/sprint`, `/wrap-up`, and more |
| **Skill Self-Evolution** | Skills track usage metrics; degraded skills auto-fix via LLM, derive variants, or capture new patterns |
| **Toolshed Gateway** | Single MCP entry point multiplexing 7 backend servers over HTTP/stdio |
| **4 Agent Types** | builder, explorer, planner, researcher — with delegation rules |
| **Enforcer Daemon** | Persistent UDS server — gate checks in ~5ms instead of ~134ms inline |
| **Mentor System** | Real-time quality scoring (0.0-1.0) with deterministic verdicts, no LLM calls |
| **Session Continuity** | LIVE_STATE.json carries context across sessions automatically |
| **Anomaly Detector** | Observation persistence, burst detection, gate correlation analysis |
| **Telegram Bot** | Remote Claude sessions via Telegram with message mirroring |

---

## 🏗️ Architecture

```
                          ┌─────────────────────────────────┐
                          │      Claude Code Session         │
                          │        (14 hook events)          │
                          └──────┬───────────┬──────────┬────┘
                                 │           │          │
                    ┌────────────▼─┐  ┌──────▼────┐  ┌──▼──────────────┐
                    │ SessionStart  │  │PreToolUse │  │  PostToolUse    │
                    │ boot.py       │  │ enforcer  │  │  tracker.py     │
                    │ (22 steps)    │  │(21 gates) │  │  (17 steps)     │
                    └──────┬───────┘  └─────┬─────┘  └──┬──────────────┘
                           │                │            │
                 ┌─────────▼──────┐  ┌──────▼──────┐  ┌─▼────────────┐
                 │   Toolshed     │  │ Gate Tiers   │  │ Mentor       │
                 │   (gateway)    │  │ T1: Safety   │  │ System       │
                 │  7 MCP servers │  │ T2: Quality  │  │ 0.0-1.0     │
                 │  HTTP + stdio  │  │ T3: Advanced │  │ No LLM      │
                 └───────┬────────┘  └─────────────┘  └─┬────────────┘
                         │                               │
           ┌─────────────▼───────────────────────────────▼─────────┐
           │       Shared Infrastructure (~100 modules)             │
           │   state · resilience · analysis · monitoring · auth    │
           │   skill_evolver · skill_triggers · anomaly_detector    │
           └─────────────────────────┬─────────────────────────────┘
                                     │
      ┌───────────┬──────────────────┼───────────────┬───────────┐
      │           │                  │               │           │
  ┌───▼────┐ ┌───▼─────┐  ┌────────▼────────┐ ┌────▼────┐ ┌────▼─────┐
  │   L1   │ │   L2    │  │   L0 Raw        │ │   L3    │ │ Ramdisk  │
  │LanceDB │ │Terminal │  │   Transcripts   │ │Telegram │ │  tmpfs   │
  │ ~7K mem│ │  FTS5   │  │  JSONL windows  │ │  FTS5   │ │ 544 MB/s │
  └────────┘ └─────────┘  └─────────────────┘ └─────────┘ └──────────┘
```

**451 tracked files** · **~100 shared modules** · **54 skills** · **4 agents**

For the full architecture reference, see **[ARCHITECTURE.md](ARCHITECTURE.md)**.

---

## 🛡️ Gate System

Three tiers of enforcement — safety gates fail-closed, quality gates fail-open:

<details>
<summary><strong>Tier 1 — Safety (fail-closed: crash = block)</strong></summary>

| Gate | Name | Purpose |
|------|------|---------|
| 1 | Read Before Edit | Must read a file before editing it |
| 2 | No Destroy | Blocks `rm -rf`, `DROP TABLE`, force push, `reset --hard` (47 patterns) |
| 3 | Test Before Deploy | Must run tests before deploying |

</details>

<details>
<summary><strong>Tier 2 — Quality (fail-open: crash = warn)</strong></summary>

| Gate | Name | Purpose |
|------|------|---------|
| 4 | Memory First | Blocks edits if memory not queried in last 5 min |
| 5 | Proof Before Fixed | Blocks edits to new files when 3+ unverified |
| 6 | Save To Memory | Warns then blocks when fixes aren't saved |
| 7 | Critical File Guard | Extra checks for high-risk files |
| 9 | Strategy Ban | Blocks strategies that failed 3+ times |
| 10 | Model Cost Guard | Enforces model selection within budget tier |
| 11 | Rate Limit | Blocks >60 tool calls/min |
| 13 | Workspace Isolation | Prevents concurrent file edits across agents |
| 14 | Confidence Check | Progressive warning -> block on unverified edits |
| 15 | Causal Chain | Blocks edits after test failure until fix history queried |
| 16 | Code Quality | AST linting — debug prints, hardcoded secrets, broad excepts |
| 20 | Self Check | Risk-score threshold triggers targeted verification questions |
| 21 | Working Summary | Blocks edits after context threshold until working summary written |
| 23 | Require Tests | Blocks code edits if session has no corresponding test files |

</details>

<details>
<summary><strong>Tier 3 — Advanced</strong></summary>

| Gate | Name | Purpose |
|------|------|---------|
| 17 | Injection Defense | Detects prompt injection (base64, ROT13, homoglyphs, zero-width) |
| 18 | Canary Monitor | Passive monitoring — never blocks. Detects bursts and anomalies |
| 19 | Hindsight | Reads mentor signals; blocks on sustained poor quality |
| 22 | Tool Profiles | Warns when tool calls match known failure patterns |

</details>

---

## 🧬 Skill Self-Evolution

Skills track usage metrics (selections, completions, fallbacks) in SQLite. When a skill degrades below thresholds, it becomes eligible for automatic evolution:

| Evolution Type | Trigger | What Happens |
|----------------|---------|--------------|
| **FIX** | completion < 35% or fallback > 40% | LLM rewrites SKILL.md in-place using failure context and metrics |
| **DERIVED** | Low applied rate + low completion | Creates a new specialized variant; parent stays active |
| **CAPTURED** | Manual or pattern detection | Extracts a novel pattern from task executions into a brand-new skill |

Each evolution creates a lineage record in SQLite, tracking parent-child relationships and generation numbers. Anti-loop protection requires 5 fresh selections after each evolution before re-evaluation.

---

## 🧠 Memory System

Four-tier memory architecture with automatic cascade:

```
L1: LanceDB (curated, semantic search, ~7K memories)
 └── L2: Terminal History (FTS5 full-text, indexed session transcripts)
      └── L0: Raw Transcripts (JSONL session files, time-windowed retrieval)
           └── L3: Telegram (FTS5, message history fallback)
```

L0 activates when `transcript_l0: true` in config — pulls raw conversation windows from matching sessions when L1+L2 results are weak (< 0.3 relevance).

| Tool | Purpose |
|------|---------|
| `search_knowledge(query)` | Semantic search across 8 modes with L2/L0/L3 cascade |
| `remember_this(content)` | Save memory with automatic dedup (cosine > 0.85) |
| `get_memory(id)` | Retrieve full memory by ID |
| `query_fix_history(error)` | Find what strategies worked or failed |
| `record_attempt(error, strategy)` | Log a fix attempt -> returns chain_id |
| `record_outcome(chain_id, result)` | Log whether the fix succeeded or failed |
| `fuzzy_search(query)` | Typo-tolerant search with boosted relevance |
| `health_check()` | Server health metrics, table counts, disk usage |

**Causal chain workflow:** `query_fix_history` -> `record_attempt` -> fix + test -> `record_outcome` -> `remember_this`

---

## 📂 Project Structure

```
~/.claude/
├── CLAUDE.md                # Rules injected into every Claude session
├── config.json              # Feature toggles (from config.example.json)
├── mcp.json                 # MCP server registration (toolshed gateway)
├── settings.json            # Hook registrations and permissions
├── setup.sh                 # One-command install script
├── hooks/
│   ├── enforcer.py          # Gate engine (21 active gates)
│   ├── enforcer_daemon.py   # UDS daemon for low-latency gate checks (~5ms)
│   ├── memory_server.py     # MCP server: LanceDB memory + semantic search
│   ├── analytics_server.py  # MCP server: analytics + gate dashboard
│   ├── gates/               # 21 gate implementations
│   ├── shared/              # ~100 shared modules (state, evolution, analysis, etc.)
│   ├── tracker.py           # PostToolUse pipeline (mentor, observations, auto-remember)
│   └── boot.py              # SessionStart orchestrator
├── toolshed/                # MCP gateway (submodule) — routes all tool calls
│   ├── toolshed.py          # Gateway server
│   └── toolshed.json        # Server registry (ports, transport, timeouts)
├── torus-skills/            # Skill library (submodule) — self-evolving skills
│   ├── trs_skill_server.py  # Skills-v2 MCP server with evolution engine
│   └── skill-library/       # 54 skill directories (each with SKILL.md)
├── agents/                  # 4 agent definitions (builder, explorer, planner, researcher)
├── tap/                     # Toroidal Agent Protocol — multi-agent orchestration (v0.1.0)
├── integrations/
│   ├── telegram-bot/        # Remote Claude via Telegram
│   ├── terminal-history/    # Session transcript indexer (FTS5)
│   ├── model-router/        # Model fan-out, comparison, scheduling
│   └── voice-web/           # Voice/TTS integration
└── scripts/                 # Orchestration (torus-loop, torus-wave, cleanup)
```

---

## 📚 Documentation

| Document | Description |
|----------|-------------|
| **[USAGE_GUIDE.md](USAGE_GUIDE.md)** | Full usage guide — sessions, gates, memory, skills, workflows |
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | Deep technical reference — all components, data flow, config options |
| **[CLAUDE.md](CLAUDE.md)** | The rules file injected into every Claude session |

---

## ⚙️ Configuration

Copy the example files and customize:

| Template | Target | Purpose |
|----------|--------|---------|
| `config.example.json` | `config.json` | Feature toggles (gates, memory, mentor, telegram) |
| `mcp.example.json` | `mcp.json` | MCP server paths (toolshed gateway) |
| `toolshed/toolshed.json` | — | Server registry (ports, transport, groups) |

<details>
<summary><strong>Optional: Telegram Bot</strong></summary>

```bash
pip install -r ~/.claude/integrations/telegram-bot/requirements.txt
cp ~/.claude/integrations/telegram-bot/config.example.json \
   ~/.claude/integrations/telegram-bot/config.json
# Edit config.json with your bot token and allowed user IDs
python3 ~/.claude/integrations/telegram-bot/bot.py
```

</details>

<details>
<summary><strong>Optional: Web Skill Dependencies</strong></summary>

```bash
pip install -r ~/.claude/skill-library/web/requirements.txt
```

</details>

---

## 🔧 Prerequisites

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI installed
- Python 3.10+
- Node.js 20+ (for torus MCP server)
- Linux with systemd (for ramdisk state storage)

---

## 📄 License

[Apache-2.0](LICENSE)
