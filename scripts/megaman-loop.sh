#!/bin/bash
# megaman-loop.sh — External orchestrator for fresh-context task execution
#
# Spawns a fresh Claude instance per task from a PRP's tasks.json.
# Each instance gets peak reasoning quality (no context degradation).
# Memory MCP bridges knowledge between instances.
#
# Usage: megaman-loop.sh <prp-name> [--max-iterations N] [--model opus|sonnet] [--timeout SECONDS]

set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────
CLAUDE_DIR="$HOME/.claude"
PRP_DIR="$CLAUDE_DIR/PRPs"
SCRIPTS_DIR="$CLAUDE_DIR/scripts"
TASK_MANAGER="$PRP_DIR/task_manager.py"
PROMPT_TEMPLATE="$SCRIPTS_DIR/megaman-prompt.md"

# ── Defaults ───────────────────────────────────────────────────────
MAX_ITERATIONS=50
MODEL="sonnet"
TASK_TIMEOUT=600  # 10 minutes per task

# ── Parse arguments ────────────────────────────────────────────────
PRP_NAME="${1:-}"
if [[ -z "$PRP_NAME" ]]; then
    echo "Usage: megaman-loop.sh <prp-name> [--max-iterations N] [--model opus|sonnet] [--timeout SECONDS]"
    exit 1
fi
shift

while [[ $# -gt 0 ]]; do
    case "$1" in
        --max-iterations) MAX_ITERATIONS="$2"; shift 2 ;;
        --model)          MODEL="$2"; shift 2 ;;
        --timeout)        TASK_TIMEOUT="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# ── Validate prerequisites ─────────────────────────────────────────
TASKS_FILE="$PRP_DIR/${PRP_NAME}.tasks.json"
ACTIVITY_LOG="$PRP_DIR/${PRP_NAME}.activity.md"
STOP_SENTINEL="$PRP_DIR/${PRP_NAME}.stop"

if [[ ! -f "$TASKS_FILE" ]]; then
    echo "Error: Tasks file not found: $TASKS_FILE"
    exit 1
fi

if ! command -v claude &>/dev/null; then
    echo "Error: 'claude' CLI not found in PATH"
    exit 1
fi

# ── Clean up any stale stop sentinel ───────────────────────────────
rm -f "$STOP_SENTINEL"

# ── Initialize activity log ────────────────────────────────────────
{
    echo "# Megaman Loop: $PRP_NAME"
    echo ""
    echo "**Started**: $(date -Iseconds)"
    echo "**Model**: $MODEL"
    echo "**Max iterations**: $MAX_ITERATIONS"
    echo ""
    echo "---"
    echo ""
} > "$ACTIVITY_LOG"

# ── Build prompt from template ─────────────────────────────────────
build_prompt() {
    local task_json="$1"
    local task_id task_name file_list validate_cmd

    task_id=$(echo "$task_json" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
    task_name=$(echo "$task_json" | python3 -c "import sys,json; print(json.load(sys.stdin)['name'])")
    file_list=$(echo "$task_json" | python3 -c "import sys,json; print('\n'.join(json.load(sys.stdin).get('files', [])))")
    validate_cmd=$(echo "$task_json" | python3 -c "import sys,json; print(json.load(sys.stdin).get('validate', 'echo no validation'))")

    if [[ -f "$PROMPT_TEMPLATE" ]]; then
        sed -e "s|{task_id}|$task_id|g" \
            -e "s|{prp_name}|$PRP_NAME|g" \
            -e "s|{task_name}|$task_name|g" \
            -e "s|{file_list}|$file_list|g" \
            -e "s|{validate_command}|$validate_cmd|g" \
            "$PROMPT_TEMPLATE"
    else
        cat <<PROMPT
You are executing task $task_id of PRP "$PRP_NAME".

## Task
$task_name

## Files to modify
$file_list

## Validation
Run this command to verify: \`$validate_cmd\`

## Rules
1. Query memory first: search_knowledge("$task_name")
2. Read all files before editing
3. Implement ONLY this task — do not touch other tasks
4. Run the validation command and show output
5. If validation passes, save to memory: remember_this("Completed task $task_id: $task_name", "megaman-loop iteration", "type:fix,area:framework")
6. If validation fails, describe what went wrong clearly
PROMPT
    fi
}

# ── Main loop ──────────────────────────────────────────────────────
ITERATION=0
echo "Starting megaman-loop for PRP: $PRP_NAME"
echo ""

while [[ $ITERATION -lt $MAX_ITERATIONS ]]; do
    ITERATION=$((ITERATION + 1))

    # Check stop sentinel
    if [[ -f "$STOP_SENTINEL" ]]; then
        echo "Stop sentinel detected. Exiting gracefully."
        echo "## Iteration $ITERATION: STOPPED BY SENTINEL" >> "$ACTIVITY_LOG"
        rm -f "$STOP_SENTINEL"
        exit 0
    fi

    # Get next task
    TASK_JSON=$(python3 "$TASK_MANAGER" next "$PRP_NAME" 2>/dev/null) || {
        echo ""
        echo "All tasks complete!"
        echo "## COMPLETE" >> "$ACTIVITY_LOG"
        echo "" >> "$ACTIVITY_LOG"
        echo "**Finished**: $(date -Iseconds)" >> "$ACTIVITY_LOG"
        exit 0
    }

    TASK_ID=$(echo "$TASK_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
    TASK_NAME=$(echo "$TASK_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['name'])")

    echo "[$ITERATION/$MAX_ITERATIONS] Task $TASK_ID: $TASK_NAME"

    # Mark task as in_progress
    python3 "$TASK_MANAGER" update "$PRP_NAME" "$TASK_ID" in_progress >/dev/null

    # Build prompt
    PROMPT=$(build_prompt "$TASK_JSON")

    # Spawn fresh Claude instance (unset CLAUDECODE to allow launching from within a session)
    START_TIME=$(date +%s)
    CLAUDE_EXIT=0
    env -u CLAUDECODE timeout "$TASK_TIMEOUT" claude -p "$PROMPT" --dangerously-skip-permissions --model "$MODEL" 2>&1 || CLAUDE_EXIT=$?
    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))

    # Validate the task
    VALIDATE_EXIT=0
    python3 "$TASK_MANAGER" validate "$PRP_NAME" "$TASK_ID" >/dev/null 2>&1 || VALIDATE_EXIT=$?

    # Determine final status
    if [[ $VALIDATE_EXIT -eq 0 ]]; then
        STATUS="PASSED"
        # Git commit on success
        if command -v git &>/dev/null && git rev-parse --is-inside-work-tree &>/dev/null 2>&1; then
            git add -A && git commit -m "megaman-loop: task $TASK_ID - $TASK_NAME" --no-verify 2>/dev/null || true
        fi
    else
        STATUS="FAILED"
    fi

    # Log to activity
    {
        echo "### Iteration $ITERATION — Task $TASK_ID: $TASK_NAME"
        echo "- **Status**: $STATUS"
        echo "- **Duration**: ${DURATION}s"
        echo "- **Claude exit**: $CLAUDE_EXIT"
        echo ""
    } >> "$ACTIVITY_LOG"

    echo "  → $STATUS (${DURATION}s)"
    echo ""
done

echo "Max iterations ($MAX_ITERATIONS) reached."
echo "## MAX ITERATIONS REACHED" >> "$ACTIVITY_LOG"
echo "**Finished**: $(date -Iseconds)" >> "$ACTIVITY_LOG"
exit 1
