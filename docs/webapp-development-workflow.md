# Torus Framework — Webapp Development Workflow

## Core Systems

**Toroidal Agents** — Full autonomous Claude Code instances running in tmux sessions. Each agent gets the complete framework (19 gates, hooks, Memory MCP). Spawn as many as you need: researchers, builders, reviewers, testers — create a config in `~/agents/<role>/` and `launch.sh <role>`. They persist, self-coordinate via agent channel (SQLite broadcast), share discoveries through Memory MCP, and Gate 13 handles file co-claims so they don't collide. Manage with `manage.sh` (status/suspend/resume/send). The watcher delivers tasks and cycles idle agents back to work.

**PRP (Product Requirements Prompts)** — Structured blueprints that decompose a project into phased, traceable, executable task plans. `/prp new-project` creates requirements, roadmap, context (locked decisions injected into every executor), and a tasks.json with validation commands per task. Every task traces back to a requirement. Plan verification catches gaps before you spend tokens executing.

**PRP-Wave** — Parallel task executor for PRPs. In-Claude mode spawns up to 5 builder subagents simultaneously with all 16 gates active and file-overlap guards. External mode spawns `claude -p` processes for max throughput without gates. Same tasks.json, same validation, same memory bridging — just parallel.

**Torus-Loop** — Sequential external executor. One fresh `claude -p` per task, peak reasoning (no context degradation), memory bridges knowledge between instances, auto-commits on pass.

---

## Phase 0: Spawn Agents + Research

```bash
# Spawn toroidal agents for the project
launch.sh researcher-alpha sonnet    # tech stack research
launch.sh researcher-beta sonnet     # API docs, library patterns
launch.sh reviewer opus              # will review later, idle for now

# Dispatch research tasks via watcher
echo '{"task":"Research best auth library for Next.js 15 + comparison matrix","project":"~/projects/myapp"}' \
  > ~/.claude/channels/task_researcher-alpha.json

echo '{"task":"Research database options: Postgres vs PlanetScale vs Turso for edge deployment","project":"~/projects/myapp"}' \
  > ~/.claude/channels/task_researcher-beta.json
```

Agents investigate autonomously, post discoveries to memory. Meanwhile in your main session:

```
model_research("optimal tech stack for production Next.js webapp 2026")  # 17 models weigh in
/brainstorm                          # synthesize agent findings + model research into 3+ options
```

By the time you're ready to blueprint, memory is loaded with researched decisions.

---

## Phase 1: Blueprint

```
/prp new-project "SaaS dashboard with auth, billing, real-time analytics"
```

This creates:
- **requirements.md** — R1..RN with acceptance criteria
- **roadmap.md** — phased delivery (Phase 1: core API + auth, Phase 2: UI + dashboard, Phase 3: billing + polish)
- **context.md** — locked decisions (Next.js 15, Postgres, Tailwind, etc.) injected into every executor prompt
- **Phase 1 tasks.json** — ready to run, each task traced to a requirement

---

## Phase 2: Execute

### Option A — Toroidal agents (full power, persistent):

```bash
# Spawn builder agents
launch.sh builder-alpha sonnet
launch.sh builder-beta sonnet
launch.sh builder-gamma sonnet

# Watcher dispatches tasks from the PRP to idle agents
# Agents coordinate via agent channel, share file claims via Gate 13
# Researcher agents keep running alongside — investigating bugs builders hit
```

Best for: complex projects where agents need full context, long-running tasks, inter-task coordination.

### Option B — PRP-Wave (parallel, gated, ephemeral):

```
/wave start <prp-name> --model sonnet
```

Up to 5 builder subagents in parallel, all 16 gates active, file-overlap guards prevent conflicts. Each wave auto-validates and advances to the next batch.

Best for: well-defined independent tasks, medium complexity.

### Option C — Torus-Loop (sequential, fresh context):

```bash
torus-loop.sh <prp-name> --model sonnet --timeout 600
```

One fresh Claude per task, peak reasoning, memory bridges knowledge, auto-commits on pass.

Best for: tasks that need maximum reasoning quality, no context bleed between tasks.

---

## Phase 3: Verify + Review

```
/prp verify-phase <prp-name>        # 3-level: files exist, no stubs, code is wired
/test                                # run test suite
```

Dispatch to the reviewer agent that's been idle:

```bash
echo '{"task":"Review all Phase 1 code for security, patterns, edge cases","project":"~/projects/myapp"}' \
  > ~/.claude/channels/task_reviewer.json
```

Verification catches stubs, missing files, unwired code. Auto-generates fix tasks for failures.

---

## Phase 4: Iterate

```bash
/prp plan-phase <name> phase-2      # plan next phase against requirements
# Agents are still running — reassign roles as needed
manage.sh send researcher-alpha "Research charting libraries for real-time analytics dashboard"
/wave start <name> --model sonnet   # execute Phase 2
```

---

## Choosing Your Executor

|              | Toroidal Agents                        | PRP-Wave                          | Torus-Loop                       |
|--------------|----------------------------------------|-----------------------------------|----------------------------------|
| Parallelism  | N agents                               | Up to 5                           | Sequential                       |
| Context      | Persistent (full session)              | Ephemeral (subagent)              | Ephemeral (fresh per task)       |
| Gates        | All 16                                 | All 16 (in-Claude)                | None                             |
| Memory       | Full MCP                               | Full MCP                          | Full MCP                         |
| Coordination | Agent channel + Gate 13                | File-overlap guards               | Agent channel                    |
| Best for     | Complex, long-running, inter-dependent | Independent batches, gated safety | Max reasoning quality per task   |
| Cost         | Highest (persistent sessions)          | Medium                            | Lowest (fresh context, no waste) |

---

## Diagrams

### Option A — Toroidal Agents (Full Power)

```
┌─────────────────────────────────────────────────────────────┐
│                     YOU (main session)                       │
│              /prp new-project → blueprint                   │
│              dispatch tasks → verify → iterate              │
└──────────┬──────────┬──────────┬──────────┬────────────────┘
           │          │          │          │
     task_*.json  task_*.json  task_*.json  task_*.json
           │          │          │          │
           ▼          ▼          ▼          ▼
      ┌─────────┐┌─────────┐┌─────────┐┌─────────┐
      │researcher││researcher││ builder ││reviewer │
      │  alpha   ││  beta   ││  alpha  ││         │
      │ (tmux)  ││ (tmux)  ││ (tmux)  ││ (tmux)  │
      │16 gates ││16 gates ││16 gates ││16 gates │
      └────┬─────┘└────┬─────┘└────┬─────┘└────┬─────┘
           │          │          │          │
           ▼          ▼          ▼          ▼
      ┌───────────────────────────────────────────┐
      │          Memory MCP + Agent Channel        │
      │   (shared knowledge, discoveries, claims)  │
      └───────────────────────────────────────────┘
```

1. **Spawn agents** — `launch.sh <role>` for each role you need
2. **Blueprint** — main session runs `/prp new-project` while researchers populate memory
3. **Dispatch** — drop `task_<role>.json` into channels/, watcher delivers to idle agents
4. **Coordinate** — agents see each other's discoveries via agent channel, Gate 13 prevents file collisions
5. **Verify** — main session runs `/prp verify-phase`, dispatches fixes or next phase
6. **Scale** — need more builders? `launch.sh builder-beta`. Agents spawn on demand.

### Option B — PRP-Wave (Parallel Gated)

```
┌─────────────────────────────────────────────────┐
│                YOU (main session)                 │
│         /wave start <prp> --model sonnet         │
└──────────────────────┬──────────────────────────┘
                       │
                 ┌─────▼──────┐
                 │ wave loop   │
                 │ file-overlap│
                 │   guard     │
                 └──┬──┬──┬───┘
                    │  │  │
            ┌───────┘  │  └───────┐
            ▼          ▼          ▼
      ┌──────────┐┌──────────┐┌──────────┐
      │subagent 1││subagent 2││subagent 3│  (up to 5)
      │ builder  ││ builder  ││ builder  │
      │16 gates  ││16 gates  ││16 gates  │
      └─────┬────┘└─────┬────┘└─────┬────┘
            │          │          │
            ▼          ▼          ▼
      ┌───────────────────────────────────┐
      │          Memory MCP               │
      └───────────────────────────────────┘
                       │
                 ┌─────▼──────┐
                 │  validate   │
                 │ (sequential)│
                 └─────┬──────┘
                       │
                 next wave or done
```

1. **Start** — `/wave start <prp>` reads tasks.json, runs plan verification
2. **Build wave** — picks up to 5 tasks with no file overlap
3. **Spawn** — launches builder subagents in parallel, all 16 gates active
4. **Validate** — collects results, runs validation commands sequentially
5. **Loop** — next wave picks up remaining tasks until done or stop sentinel
6. **Verify** — auto-runs phase verification, reports gaps

### Option C — Torus-Loop (Sequential Fresh Context)

```
┌──────────────────────────────────────┐
│          torus-loop.sh <prp>          │
└──────────────────┬───────────────────┘
                   │
                   ▼
            ┌──────────────┐
            │ task_manager  │
            │  next task    │◄──────────────┐
            └──────┬───────┘               │
                   │                       │
                   ▼                       │
            ┌──────────────┐               │
            │ memory       │               │
            │ prefetch     │               │
            └──────┬───────┘               │
                   │                       │
                   ▼                       │
            ┌──────────────┐               │
            │ claude -p    │               │
            │ fresh context│               │
            │ no gates     │               │
            │ full memory  │               │
            └──────┬───────┘               │
                   │                       │
                   ▼                       │
            ┌──────────────┐    pass       │
            │  validate    ├───► commit ───┘
            └──────┬───────┘
                   │ fail
                   ▼
             log + on_fail
             route → loop
```

1. **Get task** — task_manager pulls next pending task from tasks.json
2. **Prefetch** — pre-loads relevant memories + agent channel messages into the prompt
3. **Execute** — spawns a fresh `claude -p` instance, full reasoning capacity, zero context bleed
4. **Validate** — runs the task's validation command
5. **Pass** → git commit + save to memory + loop to next task
6. **Fail** → log it, route `on_fail` task if defined, loop continues
7. **Bridge** — memory MCP carries knowledge between instances

---

## The TL;DR

Toroidal agents are your **standing army** — spawn them, they persist, they coordinate. PRP is your **battle plan** — structured, traceable, verifiable. Wave and torus-loop are **lightweight alternatives** when you don't need full persistent agents. Use all three together: agents research and review continuously, PRP structures the work, wave/loop handles the batch execution.
