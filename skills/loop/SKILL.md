# /loop — Megaman Loop Orchestrator

## When to use
When user says "loop", "start loop", "run loop", "megaman loop", or wants to execute
a PRP's tasks via fresh Claude instances for maximum reasoning quality.

## Commands
- `/loop start <prp-name> [--max-iterations N] [--model sonnet|opus]` — Start the orchestrator
- `/loop status <prp-name>` — Show current task progress and activity log
- `/loop stop <prp-name>` — Signal the loop to stop after current task

## Start Flow
1. **VALIDATE**: Check ~/.claude/PRPs/{prp-name}.tasks.json exists
2. **CONFIRM**: Show task count and ask user to confirm
3. **LAUNCH**: Run `nohup ~/.claude/scripts/megaman-loop.sh {prp-name} [flags] > ~/.claude/PRPs/{prp-name}.loop.log 2>&1 &`
4. **REPORT**: Show PID and how to monitor: `tail -f ~/.claude/PRPs/{prp-name}.loop.log`

## Status Flow
1. **TASKS**: Run `python3 ~/.claude/PRPs/task_manager.py status {prp-name}` and display results
2. **ACTIVITY**: Read ~/.claude/PRPs/{prp-name}.activity.md and show recent iterations
3. **PROCESS**: Check if loop is still running via `pgrep -f "megaman-loop.sh {prp-name}"`

## Stop Flow
1. **SENTINEL**: Create ~/.claude/PRPs/{prp-name}.stop (loop checks each iteration)
2. **CONFIRM**: Tell user the loop will stop after the current task completes
3. **NOTE**: For immediate stop, user can `kill $(pgrep -f "megaman-loop.sh {prp-name}")`

## Rules
- ALWAYS validate tasks.json exists before starting
- NEVER start a loop if one is already running for the same PRP
- Default model is sonnet (cost-effective); use opus only when user requests it
- Default max iterations is 50
- The loop runs OUTSIDE Claude Code — it spawns fresh instances via `claude -p`
- Each instance gets full Memory MCP access via boot.py session start
- Each successful task is git-committed automatically
