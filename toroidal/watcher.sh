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

    # Build merged prompt (project rules injection is Phase 2)
    PROMPT="$TASK_CONTENT"
    if [ -n "$PROJECT" ]; then
        PROMPT="Project: $PROJECT

$TASK_CONTENT"
    fi

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
