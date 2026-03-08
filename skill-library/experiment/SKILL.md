# /experiment — Autoresearch-Style Experiment Loop

## When to use
When the user says "experiment", "autoresearch", "optimize metric", "run experiments",
or wants unattended metric-driven optimization on a specific target.

## Commands
- `/experiment start <program.md>` — Run the experiment loop
- `/experiment start <program.md> --max N` — Limit to N iterations (default 10)
- `/experiment status` — Show results.tsv for current branch
- `/experiment resume` — Resume from last experiment on current branch

## Phase 0: SETUP

1. **Read program.md**: Parse Goal, Metric, editable files, constraints
2. **Create branch**: `git checkout -b experiment/{tag}` where tag = user-provided or date-based
3. **Init results.tsv**: Create with header row:
   ```
   commit	metric	status	description
   ```
4. **Run baseline**: Execute the metric command, extract the number, log as first row:
   ```
   {commit}	{metric_value}	baseline	unmodified baseline
   ```
5. **Set best**: `best_metric = baseline_value`
6. **Confirm**: Show baseline and ask "Starting experiment loop. Ready?"

## Phase 1: EXPERIMENT LOOP

Repeat until stop condition (Phase 2):

### a. PLAN CHANGE
- Look at results.tsv history — what's been tried, what worked
- Read the editable files from program.md
- Propose a single, focused change (one idea per iteration)
- Prefer small changes over large rewrites

### b. IMPLEMENT
- Edit only files listed in "What You CAN Edit"
- Keep changes minimal and reversible

### c. TEST GUARD
- Run the test command from Constraints (if specified)
- If tests fail: revert with `git checkout -- .`, log as crash, increment failure counter, skip to next iteration

### d. MEASURE
- Run the metric command from program.md
- Extract the metric value using the extract pattern

### e. DECIDE
Compare to `best_metric` using the direction from program.md:
- **Keep**: New metric is better → `best_metric = new_metric`
- **Discard**: New metric is worse or equal → `git checkout -- .` to revert

### f. LOG
Append to results.tsv:
```
{commit}	{metric_value}	{keep|discard|crash}	{short description of what was tried}
```

### g. COMMIT
- If keep: `git add -A && git commit -m "experiment: {description}"`
- If discard: no commit (files already reverted)
- If crash: `git commit --allow-empty -m "experiment(crash): {description}"`

### h. SAVE TO MEMORY
Every 3 iterations:
```
remember_this("Experiment {tag} iteration {N}: best={best_metric}, tried={description}, result={keep|discard}", "experiment loop", "type:learning,area:framework,experiment")
```

## Phase 2: STOP CONDITIONS

Any of these triggers a full stop:
- **Max iterations reached** (default 10)
- **3 consecutive crashes** (something is fundamentally broken)
- **Metric plateau**: 3 consecutive discards with <0.1% change from best
- **User interrupt**: User sends any message

## Phase 3: REPORT

Display summary:
```
Experiment: {tag}
Iterations: {N}/{max}
Baseline:   {baseline_metric}
Best:       {best_metric} ({improvement}% improvement)
Kept:       {keep_count}
Discarded:  {discard_count}
Crashed:    {crash_count}

Results:
commit   metric     status   description
-------  ---------  -------  -----------
a1b2c3d  {value}    baseline unmodified baseline
b2c3d4e  {value}    keep     {description}
...
```

Save final summary to memory:
```
remember_this("Experiment {tag} complete: {N} iterations, baseline={baseline} → best={best} ({improvement}%). Kept {k}, discarded {d}, crashed {c}.", "experiment result", "type:learning,area:framework,experiment,outcome:success")
```

## Rules
- NEVER edit files not listed in program.md's "What You CAN Edit"
- NEVER skip the test guard — if tests break, it's a crash
- NEVER continue past stop conditions
- One change per iteration — keep experiments isolated and comparable
- Simpler is better — a small improvement with less code beats a big improvement with complex code
- Revert cleanly on discard — working tree must match last kept commit
- results.tsv is tab-separated, never comma-separated
