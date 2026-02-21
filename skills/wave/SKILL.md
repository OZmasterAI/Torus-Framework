# /wave — Torus Wave Orchestrator

## When to use
When user says "wave", "start wave", "run wave", "parallel tasks", or wants to execute
a PRP's tasks via parallel execution for maximum throughput.

Two modes:
- **In-Claude (default)** — Claude orchestrates via Task tool subagents. All 16 gates active on executors. Best for gated safety.
- **External (`--external`)** — Spawns `torus-wave.py` which launches `claude -p` processes. Zero gates on executors. Best for batch throughput.

## Commands
- `/wave start <prp> [--model sonnet|opus] [--max-waves N]` — In-Claude gated mode (default)
- `/wave start <prp> --external [--max-iterations N] [--model sonnet|opus] [--timeout SECONDS]` — External ungated batch mode
- `/wave status <prp>` — Show current task progress and activity log
- `/wave stop <prp>` — Signal the wave to stop after current wave completes

## In-Claude Start Flow (default)

### 1. VALIDATE
Check `~/.claude/PRPs/{prp}.tasks.json` exists. If not, abort with error.

### 2. CONFIRM
Run `python3 ~/.claude/PRPs/task_manager.py status {prp}` to get task count.
Show the user:
- Total tasks, pending count, failed count
- Mode: **In-Claude (gated)** — all 16 quality gates active
- Model: sonnet (default) or opus if `--model opus`
- Max waves: N (default 50) if `--max-waves N`

Ask user to confirm before proceeding.

### 3. CLEANUP
Run: `python3 -c "import sys; sys.path.insert(0, '$HOME/.claude/hooks'); from shared.agent_channel import cleanup; cleanup(max_age_hours=24)"`

### 3.5 PLAN VERIFICATION
Before spending executor tokens, validate the task plan structure. Run:
```bash
python3 ~/.claude/PRPs/task_manager.py plan-check {prp} ~/.claude/PRPs/{prp}.md
```
Parse the JSON output. Check:
- `uncovered` — requirement IDs with no task covering them
- `orphan_tasks` — tasks referencing nonexistent requirement IDs
- `pass` — true if both lists are empty

If `pass` is false, show the user the gaps and ask whether to proceed anyway or abort.

Additionally, verify task file targets exist or are creatable:
```bash
python3 ~/.claude/PRPs/task_manager.py wave {prp}
```
For each task in the output, check that parent directories of all `files` entries exist. If any are missing, warn the user before proceeding.

If the PRP requirements file (`~/.claude/PRPs/{prp}.md`) does not exist, skip the plan-check step (tasks-only PRPs are valid) and proceed directly to the wave loop.

### 4. WAVE LOOP
Repeat until all tasks done, `--max-waves` reached, or stop sentinel found:

#### a. GET ELIGIBLE TASKS
```bash
python3 ~/.claude/PRPs/task_manager.py wave {prp}
```
Parse the JSON array. If `{"done": true}` is returned, all tasks complete — exit loop.

#### b. CHECK STOP SENTINEL
```bash
test -f ~/.claude/PRPs/{prp}.stop
```
If exists, remove it and exit loop. Tell user wave stopped by sentinel.

#### c. FILE-OVERLAP GUARD
Apply the same algorithm as `torus-wave.py`'s `build_wave()`:
- Maintain a `claimed_files` set (initially empty)
- For each eligible task in order:
  - If any of the task's `files` overlap with `claimed_files` → defer to next wave
  - Otherwise → add to this wave, add its files to `claimed_files`
- Log deferred task IDs if any

#### d. CAP WAVE SIZE
If more than 5 tasks in wave, split: take first 5, defer the rest to next wave.

#### e. MARK IN-PROGRESS
For each task in the wave, run:
```bash
python3 ~/.claude/PRPs/task_manager.py update {prp} {task_id} in_progress
```

#### f. SPAWN SUBAGENTS
Launch one `Task(subagent_type="builder")` per wave task, **all in parallel** (single message with multiple Task tool calls).

**Subagent prompt construction** — build from these parts:

1. **Task metadata** from the wave output:
   ```
   You are executing task {task_id} of PRP "{prp}".
   ## Task
   {task_name}
   ## Files to modify
   {file_list}
   ## Validation
   Run this command to verify: `{validate_command}`
   ```

2. **CONTEXT.md** — if `~/.claude/PRPs/{prp}.context.md` exists, read and include it

3. **Recent agent messages** — run:
   ```bash
   python3 -c "import sys,json; sys.path.insert(0, '$HOME/.claude/hooks'); from shared.agent_channel import read_messages; msgs=read_messages(0.0, limit=5); print(json.dumps(msgs))"
   ```
   Include as: `## Recent Agent Messages\n{formatted messages}`

4. **Rules** (always include):
   ```
   ## Rules
   1. Query memory first: search_knowledge("{task_name}")
   2. Read all files before editing
   3. Implement ONLY this task — do not touch other tasks
   4. Run the validation command and show output
   5. If validation passes, save to memory: remember_this("Completed task {task_id}: {task_name}", "wave execution", "type:fix,area:framework")
   6. If validation fails, describe what went wrong clearly
   7. Post discoveries to agent channel:
      python3 -c "import sys; sys.path.insert(0, '/home/crab/.claude/hooks'); from shared.agent_channel import post_message; post_message('task-{task_id}', 'discovery', 'what you found')"
   ```

Set subagent model to match `--model` flag (default sonnet).

#### g. COLLECT RESULTS
Wait for all subagents to complete. For each:
- If subagent reports validation passed → proceed to serialized validation
- If subagent reports failure → note it

#### h. SERIALIZE VALIDATION
Run validations **one at a time** (tasks.json write races):
```bash
python3 ~/.claude/PRPs/task_manager.py validate {prp} {task_id}
```
Parse output JSON for status. Log pass/fail for each task.

#### i. POST RESULTS
For each completed task, post to agent channel:
```bash
python3 -c "import sys; sys.path.insert(0, '$HOME/.claude/hooks'); from shared.agent_channel import post_message; post_message('wave-orchestrator', 'wave-result', 'Wave {N}: task {id} {status}')"
```

#### j. LOG WAVE SUMMARY
Append to `~/.claude/PRPs/{prp}.activity.md`:
```
## Wave {N} — {timestamp}
- Tasks launched: {count} ({task_ids})
- Deferred: {deferred_ids or "none"}
- Results: {passed} passed, {failed} failed
```

### 5. POST-COMPLETION
When all tasks are done (or max waves reached):
1. Run `python3 ~/.claude/scripts/prp-phase-verify.py {prp} --auto-fix`
2. If failures found → report to user, suggest re-running wave
3. If all pass → report completion
4. Run `python3 ~/.claude/PRPs/task_manager.py status {prp}` and show final summary

## External Start Flow (`--external` flag)

### 1. VALIDATE
Check `~/.claude/PRPs/{prp}.tasks.json` exists.

### 2. CONFIRM
Show task count and warn: **External mode — executors run WITHOUT quality gates.**
Ask user to confirm.

### 3. LAUNCH
```bash
nohup python3 ~/.claude/scripts/torus-wave.py {prp} [--max-iterations N] [--model sonnet|opus] [--timeout SECONDS] > ~/.claude/PRPs/{prp}.wave.log 2>&1 &
```

### 4. REPORT
Show PID and how to monitor: `tail -f ~/.claude/PRPs/{prp}.wave.log`

## Status Flow
1. **TASKS**: Run `python3 ~/.claude/PRPs/task_manager.py status {prp}` and display results
2. **ACTIVITY**: Read `~/.claude/PRPs/{prp}.activity.md` and show recent waves
3. **PROCESS**: Check if wave is still running:
   - External: `pgrep -f "torus-wave.py {prp}"`
   - In-Claude: check if Task tool subagents are active

## Stop Flow
1. **SENTINEL**: Create `~/.claude/PRPs/{prp}.stop` (wave checks each iteration)
2. **CONFIRM**: Tell user the wave will stop after the current wave of tasks completes
3. **NOTE**: For external mode immediate stop: `kill $(pgrep -f "torus-wave.py {prp}")`

## Rules
- ALWAYS validate tasks.json exists before starting
- NEVER start a wave if one is already running for the same PRP
- Default model is sonnet (cost-effective); use opus only when user requests it
- Default max waves is 50
- In-Claude mode: all 16 quality gates are active on executor subagents
- External mode: executors run via `claude -p` with no gates
- Each instance gets full Memory MCP access via boot.py session start
- Wave mode checks file overlap between tasks — tasks sharing files are never co-waved
- Tasks with on_fail routing: if a task fails and has on_fail set, the target task is activated automatically
- Max 5 parallel subagents per wave (Task tool soft limit) — larger waves split automatically
- Validations always run sequentially to avoid tasks.json write races
- ALWAYS run phase verification after wave completes before declaring success
