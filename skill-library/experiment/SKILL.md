# /experiment — Autoresearch-Style Experiment Loop

## When to use
When the user says "experiment", "autoresearch", "optimize metric", "optimize skill",
"improve skill", "run experiments", or wants unattended metric-driven optimization.

## Commands
- `/experiment start <program.md>` — Run the experiment loop
- `/experiment start <program.md> --max N` — Limit to N iterations (default 10)
- `/experiment start <program.md> --runs N` — Run skill N times per iteration for statistical eval (default 10)
- `/experiment start <program.md> --interval Nm` — Auto-restart every N minutes for overnight runs (default: off)
- `/experiment start <program.md> --forever` — Never stop (run until manual kill or user interrupt)
- `/experiment start <program.md> --no-confirm` — Skip the "Ready?" prompt
- `/experiment start <program.md> --timeout Ns` — Kill individual runs exceeding N seconds
- `/experiment status` — Show results and dashboard for current experiment
- `/experiment resume` — Resume from last experiment on current branch

## Mode Detection

The skill operates in two modes based on program.md content:

**Metric Mode** (original): program.md has a `Metric` section with a numeric metric command.
Use for: code optimization, performance tuning, training loops.

**Eval Mode** (v2): program.md has an `Eval` section with binary yes/no criteria.
Use for: skill prompt optimization, output quality improvement, content generation.

---

## program.md Format

### Metric Mode (unchanged)
```markdown
# Goal
Optimize X

# Metric
- Run: `command to run`
- Extract: `grep pattern`
- Direction: lower|higher

# What You CAN Edit
- file1.py
- file2.py

# Constraints
- Test: `pytest tests/`
```

### Eval Mode (new)
```markdown
# Goal
Improve the /my-skill skill to produce better outputs

# Skill
- Name: my-skill
- Path: ~/.claude/skill-library/my-skill/SKILL.md
- Test prompt: "Generate a diagram of a REST API flow"

# Eval
Binary criteria — each scored yes(1) or no(0) per run:
- Is all text legible and grammatically correct?
- Does the output use the correct color palette (pastels, no neon)?
- Is the layout linear (left-to-right or top-to-bottom)?
- Is the output free of unnecessary numbering or ordinals?

# What You CAN Edit
- ~/.claude/skill-library/my-skill/SKILL.md

# Constraints
- Do not change the skill's core purpose
- Do not remove existing functionality
- Keep the SKILL.md under 3000 tokens
```

---

## Phase 0: SETUP

1. **Read program.md**: Detect mode (Metric vs Eval) based on sections present
2. **Create worktree**: Use `EnterWorktree` to create an isolated worktree on branch `experiment/{tag}`. All edits run inside the worktree — main working tree stays untouched.
3. **Parse eval criteria** (Eval Mode only):
   - Extract each criterion as a binary question
   - Validate: every criterion MUST be answerable with yes/no. Reject criteria with scales, ranges, or subjective qualifiers ("somewhat", "mostly", "about")
   - Count: `criteria_count = len(criteria)`
   - Max score per iteration: `max_score = runs * criteria_count`
4. **Init tracking**:
   - Metric Mode: Create `results.tsv` with header `commit	metric	duration_s	status	description`
   - Eval Mode: Create `experiment_log.jsonl` for detailed per-run results
5. **Pre-flight checks**:
   - Run test command from Constraints (if specified). Note pass/fail as `baseline_test_status`
   - If tests fail: warn but continue (experiments track relative improvement)
6. **Run baseline**:
   - Metric Mode: Execute metric command, extract the number
   - Eval Mode: Run the skill `--runs` times (default 10) using subagent, evaluate each output against all binary criteria, compute aggregate score
7. **Validate baseline**:
   - Metric Mode: If extract returns empty/NaN, STOP with error
   - Eval Mode: If all runs score 0 on all criteria, STOP with error — criteria may be broken
8. **Log baseline**:
   - Metric Mode: Append to results.tsv
   - Eval Mode: Log to experiment_log.jsonl:
     ```json
     {"iteration": 0, "type": "baseline", "score": 32, "max": 40, "pct": 80.0, "runs": [...], "timestamp": "..."}
     ```
9. **Set best**: `best_score = baseline_score`
10. **Display dashboard** (see Phase 5)
11. **Confirm**: Show baseline score and ask "Starting experiment loop. Ready?" (skip if `--no-confirm`)

---

## Phase 1: EXPERIMENT LOOP

Repeat until stop condition (Phase 2):

### a. PLAN MUTATION
- Review experiment history — what mutations were tried, which improved scores
- Read the current editable file (SKILL.md or code files)
- Propose a single, focused mutation to the prompt/code
- Prefer small targeted changes over large rewrites
- Focus on criteria with lowest pass rates from previous iteration

### b. IMPLEMENT
- Edit only files listed in "What You CAN Edit"
- Keep changes minimal and reversible
- Save a copy of the pre-mutation file: `cp SKILL.md SKILL.md.bak`

### c. TEST GUARD
- Run test command from Constraints (if specified)
- On failure: attempt ONE fix, re-run. Still fails → revert from .bak, log as crash, skip to next iteration

### d. MEASURE

**Metric Mode** (unchanged):
- Run metric command, extract value, record duration

**Eval Mode** (v2 — subagent-based N-run evaluation):

For each run `i` in `1..N`:
1. **Spawn subagent** (type: general-purpose) with prompt:
   ```
   Run the skill /{skill_name} with this test prompt: "{test_prompt}"
   Return ONLY the skill's output, nothing else.
   ```
2. **Collect output** from subagent
3. **Evaluate output** against each binary criterion. For each criterion, ask yourself:
   - Does this output satisfy: "{criterion}"?
   - Answer: 1 (yes) or 0 (no)
   - NO PARTIAL CREDIT. No "mostly yes". Binary only.
4. **Record per-run result**:
   ```json
   {"run": i, "scores": [1, 1, 0, 1], "total": 3, "max": 4}
   ```

After all N runs:
- `iteration_score = sum(all run totals)`
- `iteration_max = N * criteria_count`
- `iteration_pct = (iteration_score / iteration_max) * 100`

### e. DECIDE

**Metric Mode**: Compare to `best_metric` using direction from program.md

**Eval Mode**:
- **Keep**: `iteration_score > best_score`
- **Simplification win**: `iteration_score == best_score` AND SKILL.md is shorter/cleaner → keep
- **Discard**: `iteration_score <= best_score` with no simplification → revert from .bak

### f. LOG

**Metric Mode**: Append to results.tsv (unchanged)

**Eval Mode**: Append to experiment_log.jsonl:
```json
{
  "iteration": N,
  "score": 37,
  "max": 40,
  "pct": 92.5,
  "best_score": 37,
  "status": "keep",
  "mutation": "Added explicit color constraint: pastels only, no saturation > 60%",
  "per_criterion": [
    {"criterion": "Is all text legible?", "pass_rate": "10/10"},
    {"criterion": "Correct color palette?", "pass_rate": "9/10"},
    {"criterion": "Linear layout?", "pass_rate": "8/10"},
    {"criterion": "No numbering?", "pass_rate": "10/10"}
  ],
  "runs": [...],
  "duration_s": 45,
  "timestamp": "2026-03-18T12:00:00Z"
}
```

### g. COMMIT
- If keep: `git add {editable files} experiment_log.jsonl && git commit -m "experiment: {mutation} (score: {score}/{max})"`
- If discard: restore from .bak, no commit
- If crash: `git commit --allow-empty -m "experiment(crash): {description}"`

### h. SAVE TO MEMORY
Every 3 iterations:
```
remember_this("Experiment {tag} iter {N}: best={best_score}/{max} ({pct}%). Tried: {mutation}. Result: {status}. Weakest criterion: {weakest}.", "experiment loop", "type:learning,experiment,autoresearch")
```

---

## Phase 2: STOP CONDITIONS

Any of these triggers a full stop:
- **Max iterations reached** (default 10, disabled with `--forever`)
- **3 consecutive crashes** (something is fundamentally broken)
- **Score plateau**: 3 consecutive discards with <1% change (disabled with `--forever`)
- **Perfect score**: `iteration_score == iteration_max` for 2 consecutive iterations (skill is optimized)
- **User interrupt**: User sends any message

When `--interval` is set and a stop condition fires (except user interrupt or perfect score):
- Save state to `experiment_state.json` in worktree
- Wait for interval duration
- Resume from saved state with a fresh approach (different mutation strategy)
- This enables overnight unattended runs

---

## Phase 3: REPORT

### Metric Mode (unchanged)
Display results.tsv summary with baseline, best, improvement%.

### Eval Mode
Display dashboard:
```
═══════════════════════════════════════════════════════
  EXPERIMENT: {tag}     Skill: /{skill_name}
═══════════════════════════════════════════════════════
  Iterations:  {N}/{max}        Runs/iter: {runs}
  Baseline:    {baseline_score}/{max} ({baseline_pct}%)
  Best:        {best_score}/{max} ({best_pct}%)
  Improvement: +{delta} ({improvement}%)
═══════════════════════════════════════════════════════

  Per-Criterion Pass Rates (best iteration):
  ✓ Is all text legible?           10/10 (100%)
  ✓ Correct color palette?         9/10  (90%)
  ◐ Linear layout?                 8/10  (80%)  ← weakest
  ✓ No numbering?                 10/10 (100%)

  Iteration History:
  #   Score   Status    Mutation
  ─── ─────── ──────── ─────────────────────────────
  0   32/40   baseline (unmodified)
  1   34/40   keep     Added explicit color constraint
  2   33/40   discard  Tried removing layout hints
  3   37/40   keep     Added "left-to-right flow" rule
  4   37/40   discard  Attempted icon style change
  5   39/40   keep     Reinforced linear constraint
═══════════════════════════════════════════════════════
```

Save final summary to memory:
```
remember_this("Experiment {tag} complete: {N} iters, baseline={baseline}/{max} → best={best}/{max} (+{improvement}%). Weakest: {weakest_criterion}. Key mutation: {best_mutation}.", "experiment result", "type:learning,experiment,autoresearch,outcome:success")
```

---

## Phase 4: CLEANUP

1. **If improvements kept**: Ask user to merge experiment branch or keep for review
2. **Keep worktree alive**: Do NOT auto-remove. Tell user where it is.
3. **Cleanup on request only**: `git worktree remove <path>` + `git branch -d experiment/{tag}`

---

## Phase 5: DASHBOARD (real-time)

During the experiment loop, display after each iteration:

```
  ┌─────────────────────────────────────┐
  │ Experiment: {tag}  Iter: {N}/{max}  │
  │ Score: {score}/{max} ({pct}%)       │
  │ Best:  {best}/{max} ({best_pct}%)   │
  │ Status: {keep|discard|crash}        │
  │                                     │
  │ ████████████████░░░░ 80% baseline   │
  │ ██████████████████░░ 90% current    │
  │ ███████████████████░ 95% best       │
  │                                     │
  │ Weakest: {criterion} ({rate})       │
  │ Next: planning mutation...          │
  └─────────────────────────────────────┘
```

Progress bars use block characters: █ for filled, ░ for empty, scaled to terminal width.

---

## Rules
- NEVER edit files not listed in program.md's "What You CAN Edit"
- NEVER skip the test guard — if tests break, it's a crash
- NEVER continue past stop conditions
- One mutation per iteration — keep experiments isolated and comparable
- Simpler is better — equal score + less code = keep (simplification win)
- Revert cleanly on discard — working tree must match last kept commit
- ALL work happens inside the worktree — never modify the main working tree
- Keep worktree alive after experiment — only clean up when user explicitly requests it
- Binary evals ONLY — no scales, no partial credit, no "mostly"
- Eval criteria must be yes/no questions. Reject anything else at parse time.
- Each subagent run is independent — no state leaks between runs
- Log everything to experiment_log.jsonl — this is the research asset
- Focus mutations on weakest criteria — don't fix what's already passing
