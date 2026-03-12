#!/bin/bash
# Toroidal Teams — idle_prompt Notification Hook
# Implements 3-state machine: working → summarizing → idle
#
# Called by Claude Code Notification hook when idle_prompt fires.
# Reads AGENT_ROLE from env (set at launch) and manages status transitions.
#
# State machine:
#   working     → send "write result" prompt, transition to summarizing
#   summarizing → transition to idle (result written, ready for next task)
#   idle        → no-op (already idle, no task was in progress)

set -uo pipefail

CHANNELS_DIR="$HOME/.claude/channels"
ROLE="${AGENT_ROLE:-}"

# If no agent role set, this isn't a Toroidal Teams session — exit silently
if [ -z "$ROLE" ]; then
    exit 0
fi

STATUS_FILE="$CHANNELS_DIR/status_${ROLE}.json"

# If no status file, not a managed agent
if [ ! -f "$STATUS_FILE" ]; then
    exit 0
fi

CURRENT=$(jq -r '.state // "idle"' "$STATUS_FILE" 2>/dev/null || echo "idle")

case "$CURRENT" in
    working)
        # Task just finished — trigger summary write
        echo "{\"state\":\"summarizing\",\"role\":\"$ROLE\",\"timestamp\":$(date +%s)}" > "$STATUS_FILE"

        # Send result-write prompt to the agent's tmux session
        if tmux has-session -t "$ROLE" 2>/dev/null; then
            RESULT_PROMPT="Write a structured JSON result summary of what you just did to ~/.claude/channels/result_${ROLE}.json. Include: {\"status\": \"done\", \"role\": \"${ROLE}\", \"summary\": \"<what you did>\", \"findings\": [\"<key finding 1>\", ...], \"files_touched\": [\"<path>\", ...], \"memories_saved\": <count>, \"timestamp\": $(date +%s)}"
            PROMPT_FILE=$(mktemp)
            echo "$RESULT_PROMPT" > "$PROMPT_FILE"
            tmux load-buffer "$PROMPT_FILE"
            tmux paste-buffer -t "$ROLE"
            tmux send-keys -t "$ROLE" Enter
            rm -f "$PROMPT_FILE"
        fi
        ;;

    summarizing)
        # Summary written — now truly idle
        echo "{\"state\":\"idle\",\"role\":\"$ROLE\",\"timestamp\":$(date +%s)}" > "$STATUS_FILE"
        ;;

    idle|stopped|*)
        # Already idle or stopped — no-op
        ;;
esac

exit 0
