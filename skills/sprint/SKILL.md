# /sprint — Multi-Agent Self-Improvement Sprint

## When to use
When user says "sprint", "self-improve sprint", "autonomous improvement",
"launch improvement swarm", or wants to run a coordinated multi-agent
improvement session.

## Commands
- `/sprint` — Full sprint with research + build + test phases
- `/sprint research` — Research-only phase (no code changes)
- `/sprint build` — Build-only phase (assumes research done)
- `/sprint $ARGUMENTS` — Focus on specific area (e.g., "gates", "skills", "memory")

## Flow

### Phase 1: ASSESS (2 min)
- Run `/benchmark --quick` to capture baseline metrics
- Read LIVE_STATE.json for current state
- Search memory for previous sprint results
- Identify top 5 improvement opportunities

### Phase 2: RESEARCH (5 min)
Launch research swarm (3-5 haiku agents in parallel):
- Agent 1: Search GitHub for Claude Code frameworks
- Agent 2: Search for self-improving agent patterns
- Agent 3: Search for specific area improvements (from $ARGUMENTS)
- Collect results, save to memory

### Phase 3: PLAN (2 min)
- Synthesize research findings
- Create prioritized task list using TaskCreate
- Score each task: Impact (40%) + Effort (30%) + Risk (20%) + Novelty (10%)
- Select top 5-7 tasks for implementation

### Phase 4: BUILD (10 min)
Launch builder team (3-5 sonnet agents):
- Create agent team with TeamCreate
- Assign tasks to team members
- Monitor progress via TaskList
- Handle blocking issues

### Phase 5: VERIFY (3 min)
- Run full test suite
- Compare metrics against Phase 1 baseline
- Fix any regressions

### Phase 6: REPORT (1 min)
- Generate sprint report with `/report sprint`
- Save comprehensive results to memory
- Update LIVE_STATE.json and ARCHITECTURE.md
- Git commit all changes

## Rules
- NEVER exceed 7 concurrent agents (resource limit)
- Research agents use haiku model, builders use sonnet
- Always capture baseline BEFORE making changes
- Stop after 2 consecutive test regressions (circuit breaker)
- Save all research and decisions to memory
- Maximum sprint duration: 25 minutes
- Update LIVE_STATE.json at each phase transition
