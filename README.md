<p align="center">
  <h1 align="center">🔄 Torus Framework</h1>
  <p align="center">
    <em>A self-evolving quality framework for <a href="https://docs.anthropic.com/en/docs/claude-code">Claude Code</a></em>
  </p>
  <p align="center">
    <a href="https://github.com/OZmasterAI/Torus-Framework/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-blue.svg" alt="License"></a>
    <img src="https://img.shields.io/badge/Python-3.10+-green.svg" alt="Python">
    <img src="https://img.shields.io/badge/Platform-Linux-lightgrey.svg" alt="Platform">
    <img src="https://img.shields.io/badge/Framework-v2.5.8-orange.svg" alt="Version">
  </p>
</p>

---

Torus wraps Claude Code with persistent memory, 19 quality gates, automated hooks, and structured workflows — turning it from a stateless CLI into a disciplined, self-improving development partner.

> **151 Python files** · **~76K lines** · **17 active gates** · **36 skills** · **6 specialized agents** · **2 MCP servers**

---

## ⚡ Quick Start

```bash
# 1. Clone with submodules (toolshed + toroidal-skills)
git clone --recurse-submodules https://github.com/OZmasterAI/Torus-Framework.git ~/.claude

# Or: plain clone then run setup script
# git clone https://github.com/OZmasterAI/Torus-Framework.git ~/.claude && bash ~/.claude/setup.sh

# 2. Install Python dependencies
pip install -r ~/.claude/hooks/requirements.txt

# 3. Copy config templates
cp ~/.claude/config.example.json ~/.claude/config.json
cp ~/.claude/mcp.example.json ~/.claude/mcp.json

# 4. Edit mcp.json — replace $HOME with your actual home directory path

# 5. Set up the ramdisk (persistent tmpfs for fast state I/O)
bash ~/.claude/hooks/setup_ramdisk.sh

# 6. Launch Claude Code
cd ~/.claude && claude
```

On first launch, SessionStart hooks bootstrap the enforcer daemon, load memory, and initialize state.

---

## 🎯 What It Does

| Feature | Description |
|---------|-------------|
| **19 Quality Gates** | Mechanical enforcement — read before edit, test before deploy, memory-first, no-destroy, injection defense, and more |
| **Persistent Memory** | LanceDB with semantic search, causal fix tracking, tag indexing, and auto-captured observations |
| **Hook Pipeline** | 12 lifecycle events — SessionStart, PreToolUse, PostToolUse, Stop, SubagentStart, PreCompact, and more |
| **36 Skills** | Slash commands — `/commit`, `/benchmark`, `/security-scan`, `/brainstorm`, `/writing-plans`, `/domain`, and more |
| **6 Agents** | builder, debugger, researcher, security, perf-analyzer, stress-tester — with delegation rules |
| **2 MCP Servers** | Memory (8 tools) + Analytics (50 tools), accessible as native Claude tools |
| **Enforcer Daemon** | Persistent UDS server — gate checks in ~5ms instead of ~134ms inline |
| **Mentor System** | Real-time quality scoring (0.0–1.0) with deterministic verdicts, no LLM calls |
| **Session Continuity** | LIVE_STATE.json carries context across sessions automatically |
| **Telegram Bot** | Remote Claude sessions via Telegram with message mirroring |

---

## 🏗️ Architecture

```
                          ┌─────────────────────────────────┐
                          │      Claude Code Session         │
                          │         (13 hook events)         │
                          └──────┬───────────┬──────────┬────┘
                                 │           │          │
                    ┌────────────▼─┐  ┌──────▼────┐  ┌──▼──────────────┐
                    │ SessionStart  │  │PreToolUse │  │  PostToolUse    │
                    │ boot.py       │  │ enforcer  │  │  tracker.py     │
                    │ (22 steps)    │  │(17 gates) │  │  (17 steps)     │
                    └──────┬───────┘  └─────┬─────┘  └──┬──────────────┘
                           │                │            │
                 ┌─────────▼──────┐  ┌──────▼──────┐  ┌─▼────────────┐
                 │  Memory MCP    │  │ Gate Tiers   │  │ Mentor       │
                 │  8 tools       │  │ T1: Safety   │  │ System       │
                 │  LanceDB +     │  │ T2: Quality  │  │ 0.0–1.0     │
                 │  4-tier search │  │ T3: Advanced │  │ No LLM      │
                 └───────┬────────┘  └─────────────┘  └─┬────────────┘
                         │                               │
           ┌─────────────▼───────────────────────────────▼─────────┐
           │         Shared Infrastructure (67 modules)             │
           │   state · resilience · analysis · monitoring · auth    │
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

**285 files** · **67 shared modules** · **36 skills** · **6 agents**

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
| 14 | Confidence Check | Progressive warning → block on unverified edits |
| 15 | Causal Chain | Blocks edits after test failure until fix history queried |
| 16 | Code Quality | Catches debug prints, hardcoded secrets, broad excepts |

</details>

<details>
<summary><strong>Tier 3 — Advanced</strong></summary>

| Gate | Name | Purpose |
|------|------|---------|
| 17 | Injection Defense | Detects prompt injection (base64, ROT13, homoglyphs, zero-width) |
| 18 | Canary Monitor | Passive monitoring — never blocks. Detects bursts and anomalies |
| 19 | Hindsight | Reads mentor signals; blocks on sustained poor quality |

</details>

---

## 🧠 Memory System

Four-tier memory architecture with automatic cascade:

```
L1: LanceDB (curated, semantic search, ~6K memories)
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
| `record_attempt(error, strategy)` | Log a fix attempt → returns chain_id |
| `record_outcome(chain_id, result)` | Log whether the fix succeeded or failed |
| `fuzzy_search(query)` | Typo-tolerant search with boosted relevance |
| `health_check()` | Server health metrics, table counts, disk usage |

**Causal chain workflow:** `query_fix_history` → `record_attempt` → fix + test → `record_outcome` → `remember_this`

---

## 📂 Project Structure

```
~/.claude/
├── CLAUDE.md                # Rules injected into every Claude session
├── config.json              # Feature toggles (from config.example.json)
├── mcp.json                 # MCP server registration (from mcp.example.json)
├── settings.json            # Hook registrations and permissions
├── hooks/
│   ├── enforcer.py          # Gate engine (17 active gates)
│   ├── enforcer_daemon.py   # UDS daemon for low-latency gate checks (~5ms)
│   ├── memory_server.py     # MCP server: LanceDB memory + semantic search
│   ├── analytics_server.py  # MCP server: 50-tool analytics + gate dashboard
│   ├── gates/               # Individual gate implementations
│   ├── shared/              # 67 shared modules (state, audit, circuit breaker, etc.)
│   ├── tracker.py           # PostToolUse pipeline (mentor, observations, auto-remember)
│   └── boot.py              # SessionStart orchestrator
├── skills/                  # 36 slash commands (/commit, /benchmark, etc.)
├── agents/                  # 6 specialized agent definitions
├── integrations/
│   ├── telegram-bot/        # Remote Claude via Telegram
│   └── terminal-history/    # Session transcript indexer
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
| `mcp.example.json` | `mcp.json` | MCP server paths (memory + analytics) |

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
- Linux with systemd (for ramdisk state storage)

---

## 📄 License

[Apache-2.0](LICENSE)
