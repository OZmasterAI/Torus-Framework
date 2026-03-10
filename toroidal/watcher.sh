#!/bin/bash
# Toroidal Teams — Unified Watcher
# Monitors ~/.claude/channels/ for task_*.json files
# Delivers tasks to the correct tmux session when worker is idle
#
# Usage: watcher.sh
# Runs in foreground (use tmux or & to background)

set -uo pipefail

CHANNELS_DIR="$HOME/.claude/channels"

echo "[watcher] Monitoring $CHANNELS_DIR for task files..."

# Ensure channels dir exists
mkdir -p "$CHANNELS_DIR"

inotifywait -m -e create,moved_to "$CHANNELS_DIR" --format '%f' |
while read -r file; do
    # Only process task files
    [[ "$file" == task_*.json ]] || continue

    TASK_FILE="$CHANNELS_DIR/$file"

    # Extract role from filename: task_researcher-alpha.json → researcher-alpha
    ROLE="${file#task_}"
    ROLE="${ROLE%.json}"

    echo "[watcher] Task detected for $ROLE: $file"

    # Check tmux session exists
    if ! tmux has-session -t "$ROLE" 2>/dev/null; then
        echo "[watcher] WARNING: No tmux session '$ROLE' — task will be skipped"
        # Move to dead-letter instead of deleting
        mkdir -p "$CHANNELS_DIR/dead-letter"
        mv "$TASK_FILE" "$CHANNELS_DIR/dead-letter/${ROLE}_$(date +%s).json"
        continue
    fi

    # Wait until worker is idle
    STATUS_FILE="$CHANNELS_DIR/status_${ROLE}.json"
    WAIT_COUNT=0
    MAX_WAIT=300  # 150 seconds max wait (300 * 0.5s)
    while true; do
        STATE=$(jq -r '.state // "unknown"' "$STATUS_FILE" 2>/dev/null || echo "unknown")
        if [ "$STATE" = "idle" ]; then
            break
        fi
        WAIT_COUNT=$((WAIT_COUNT + 1))
        if [ $WAIT_COUNT -ge $MAX_WAIT ]; then
            echo "[watcher] WARNING: $ROLE not idle after 150s — delivering anyway"
            break
        fi
        sleep 0.5
    done

    # Read task content
    if [ ! -f "$TASK_FILE" ]; then
        echo "[watcher] Task file disappeared before delivery: $file"
        continue
    fi

    TASK_CONTENT=$(jq -r '.task // empty' "$TASK_FILE" 2>/dev/null)
    PROJECT=$(jq -r '.project // empty' "$TASK_FILE" 2>/dev/null)

    if [ -z "$TASK_CONTENT" ]; then
        echo "[watcher] WARNING: Empty task in $file — skipping"
        rm -f "$TASK_FILE"
        continue
    fi

    # Save raw task JSON for Phase 3 co-claim registration
    TASK_JSON=$(cat "$TASK_FILE")

    # Build merged prompt with project config injection
    # NOTE: PROJECT must be an absolute path (no ~ or $HOME). Watcher rejects relative paths.
    PROMPT=""

    # Inject .agent-config.json rules if project has one
    if [ -n "$PROJECT" ]; then
        # Reject non-absolute paths (security: no eval/expansion of user input)
        if [[ "$PROJECT" != /* ]]; then
            echo "[watcher] WARNING: PROJECT must be an absolute path, got '$PROJECT' — skipping config injection"
            PROJECT=""
        else
            CONFIG_FILE="$PROJECT/.agent-config.json"
            if [ -f "$CONFIG_FILE" ]; then
                # Extract role type from agent config.json (e.g., researcher-alpha → researcher)
                AGENT_DIR="$HOME/agents/$ROLE"
                ROLE_TYPE=$(python3 -c "import json; print(json.load(open('$AGENT_DIR/config.json')).get('role_type',''))" 2>/dev/null || echo "")
                if [ -z "$ROLE_TYPE" ]; then
                    # Fallback: strip suffix (researcher-alpha → researcher)
                    ROLE_TYPE=$(echo "$ROLE" | sed 's/-[a-zA-Z]*$//')
                fi
                ROLE_CONFIG=$(jq -r ".$ROLE_TYPE // empty" "$CONFIG_FILE" 2>/dev/null)
                if [ -n "$ROLE_CONFIG" ]; then
                    PROMPT="## Project Rules for $ROLE_TYPE in $(basename "$PROJECT")
$ROLE_CONFIG

---

"
                fi
            fi
            PROMPT="${PROMPT}Project: $PROJECT

"
        fi
    fi

    PROMPT="${PROMPT}${TASK_CONTENT}

---
When done, write your result summary to ~/.claude/channels/result_${ROLE}.json"

    # Update status to working
    echo "{\"state\":\"working\",\"role\":\"$ROLE\",\"timestamp\":$(date +%s)}" > "$STATUS_FILE"

    # Deliver to tmux session
    # Use a temp file to avoid shell escaping issues with send-keys
    PROMPT_FILE=$(mktemp)
    printf '%s\n' "$PROMPT" > "$PROMPT_FILE"
    tmux load-buffer "$PROMPT_FILE"
    tmux paste-buffer -t "$ROLE"
    tmux send-keys -t "$ROLE" Enter
    rm -f "$PROMPT_FILE"

    echo "[watcher] Task delivered to $ROLE"

    # Clean up task file
    rm -f "$TASK_FILE"
done
