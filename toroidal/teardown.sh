#!/bin/bash
# Toroidal Teams — Agent Teardown
# Usage: teardown.sh <role|all>

set -uo pipefail

CHANNELS_DIR="$HOME/.claude/channels"

teardown_agent() {
    local ROLE="$1"
    if tmux has-session -t "$ROLE" 2>/dev/null; then
        echo "Stopping $ROLE..."
        tmux send-keys -t "$ROLE" "/exit" Enter
        sleep 2
        if tmux has-session -t "$ROLE" 2>/dev/null; then
            tmux kill-session -t "$ROLE"
        fi
        echo "$ROLE stopped."
    else
        echo "$ROLE: no active session."
    fi
    # Update status
    echo "{\"state\":\"stopped\",\"role\":\"$ROLE\",\"timestamp\":$(date +%s)}" \
        > "$CHANNELS_DIR/status_${ROLE}.json" 2>/dev/null || true
}

TARGET="${1:?Usage: teardown.sh <role|all>}"

if [ "$TARGET" = "all" ]; then
    # Find all agent status files
    for f in "$CHANNELS_DIR"/status_*.json; do
        [ -f "$f" ] || continue
        ROLE=$(basename "$f" | sed 's/^status_//;s/\.json$//')
        teardown_agent "$ROLE"
    done
    # Stop watcher
    pkill -f "inotifywait.*channels" 2>/dev/null && echo "Watcher stopped." || true
else
    teardown_agent "$TARGET"
fi
