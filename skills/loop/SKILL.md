# /loop — Torus Loop Orchestrator

## When to use
When user says "loop", "start loop", "run loop", "torus loop", or wants to execute
a PRP's tasks via fresh Claude instances for maximum reasoning quality.

## Commands
- `/loop start <prp-name> [--max-iterations N] [--model sonnet|opus] [--parallel]` — Start the orchestrator
- `/loop status <prp-name>` — Show current task progress and activity log
- `/loop stop <prp-name>` — Signal the loop to stop after current task

## Start Flow
1. **VALIDATE**: Check ~/.claude/PRPs/{prp-name}.tasks.json exists
2. **CONFIRM**: Show task count and ask user to confirm
2.5. **PARALLEL CHECK**: If --parallel flag, use `nohup python3 ~/.claude/scripts/torus-wave.py {prp-name} [flags] > ~/.claude/PRPs/{prp-name}.loop.log 2>&1 &` instead of torus-loop.sh
3. **LAUNCH**: Run `nohup ~/.claude/scripts/torus-loop.sh {prp-name} [flags] > ~/.claude/PRPs/{prp-name}.loop.log 2>&1 &`
4. **REPORT**: Show PID and how to monitor: `tail -f ~/.claude/PRPs/{prp-name}.loop.log`

## Status Flow
1. **TASKS**: Run `python3 ~/.claude/PRPs/task_manager.py status {prp-name}` and display results
2. **ACTIVITY**: Read ~/.claude/PRPs/{prp-name}.activity.md and show recent iterations
3. **PROCESS**: Check if loop is still running via `pgrep -f "torus-loop.sh {prp-name}"`

## Stop Flow
1. **SENTINEL**: Create ~/.claude/PRPs/{prp-name}.stop (loop checks each iteration)
2. **CONFIRM**: Tell user the loop will stop after the current task completes
3. **NOTE**: For immediate stop, user can `kill $(pgrep -f "torus-loop.sh {prp-name}")`

## Post-Completion Verification
When all tasks are done (or loop ends), run phase verification:
1. `python3 ~/.claude/scripts/prp-phase-verify.py <prp-name> --auto-fix`
2. If failures found → fix tasks are auto-added to tasks.json → restart loop to process them
3. If all pass → phase is verified, proceed to next phase or report completion

## Rules
- ALWAYS validate tasks.json exists before starting
- NEVER start a loop if one is already running for the same PRP
- Default model is sonnet (cost-effective); use opus only when user requests it
- Default max iterations is 50
- The loop runs OUTSIDE Claude Code — it spawns fresh instances via `claude -p`
- Each instance gets full Memory MCP access via boot.py session start
- Each successful task is git-committed automatically
- Wave mode (--parallel) checks file overlap between tasks — tasks sharing files are never co-waved
- ALWAYS run phase verification after loop completes before declaring success
