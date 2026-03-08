# /experiment — Autoresearch-Style Experiment Loop

## When to use
When the user says "experiment", "autoresearch", "optimize metric", "run experiments",
or wants unattended metric-driven optimization on a specific target.

## Commands
- `/experiment start <program.md>` — Run the experiment loop
- `/experiment start <program.md> --max N` — Limit to N iterations (default 10)
- `/experiment start <program.md> --no-confirm` — Skip the "Ready?" prompt (for automated runs)
- `/experiment status` — Show results.tsv for current branch
- `/experiment resume` — Resume from last experiment on current branch

## Phase 0: SETUP

1. **Read program.md**: Parse Goal, Metric, editable files, constraints
2. **Create worktree**: Use `EnterWorktree` to create an isolated worktree on branch `experiment/{tag}` (tag = user-provided or date-based). All subsequent file edits, commands, and git operations run **inside the worktree** — the main working tree stays untouched.
3. **Init results.tsv**: Create with header row:
   ```
   commit	metric	status	description
   ```
4. **Pre-flight checks**:
   - Run the test command from Constraints. Note pass/fail as `baseline_test_status`.
   - If tests fail: warn "Pre-existing test failures detected" but continue (experiments track *relative* improvement, not absolute pass)
5. **Run baseline**: Execute the metric command, extract the number
6. **Validate metric**: If extract returns empty/NaN, STOP and report: "Metric extraction failed — check your Run and Extract commands in program.md." Do not proceed with a broken baseline.
7. **Log baseline** to results.tsv:
   ```
   {commit}	{metric_value}	baseline	unmodified baseline
   ```
8. **Set best**: `best_metric = baseline_value`
9. **Confirm**: Show baseline, test status, and ask "Starting experiment loop. Ready?" (skip if `--no-confirm`)

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
- If `baseline_test_status` was failing: check that no *new* tests fail (compare failure set, not absolute pass)
- If `baseline_test_status` was passing: all tests must still pass
- On failure: revert with `git checkout -- .`, log as crash, increment failure counter, skip to next iteration

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
- If keep: `git add {files from program.md "What You CAN Edit"} results.tsv && git commit -m "experiment: {description}"`
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

## Phase 4: CLEANUP

After reporting results:
1. **If improvements were kept**: Ask the user if they want to merge the experiment branch back (e.g., `git merge experiment/{tag}`) or keep it for review.
2. **Remove worktree**: Run `git worktree remove <worktree_path>` (use `--force` if needed). Always clean up — do not leave stale worktrees behind.
3. **Prune branches** (optional): If the user doesn't want the branch, `git branch -d experiment/{tag}`.

## Rules
- NEVER edit files not listed in program.md's "What You CAN Edit"
- NEVER skip the test guard — if tests break, it's a crash
- NEVER continue past stop conditions
- One change per iteration — keep experiments isolated and comparable
- Simpler is better — a small improvement with less code beats a big improvement with complex code
- Revert cleanly on discard — working tree must match last kept commit
- results.tsv is tab-separated, never comma-separated
- ALL work happens inside the worktree — never modify the main working tree
- ALWAYS clean up the worktree in Phase 4 — do not leave stale worktrees behind
