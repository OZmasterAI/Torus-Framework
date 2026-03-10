#!/bin/bash
# Toroidal Teams — Agent Launch Script
# Usage: launch.sh <role> [model]
# Example: launch.sh researcher-alpha sonnet

set -euo pipefail

ROLE="${1:?Usage: launch.sh <role> [model]}"
AGENTS_DIR="$HOME/agents"
CHANNELS_DIR="$HOME/.claude/channels"
AGENT_DIR="$AGENTS_DIR/$ROLE"

# Validate agent exists
if [ ! -d "$AGENT_DIR" ]; then
    echo "ERROR: Agent dir $AGENT_DIR does not exist"
    exit 1
fi

# Read model from config.json or use argument
if [ -n "${2:-}" ]; then
    MODEL="$2"
else
    MODEL=$(python3 -c "import json; print(json.load(open('$AGENT_DIR/config.json')).get('model','sonnet'))" 2>/dev/null || echo "sonnet")
fi

# Ensure channels dir exists
mkdir -p "$CHANNELS_DIR"

# Initialize status file if missing
STATUS_FILE="$CHANNELS_DIR/status_${ROLE}.json"
if [ ! -f "$STATUS_FILE" ]; then
    echo "{\"state\":\"idle\",\"role\":\"$ROLE\",\"timestamp\":$(date +%s)}" > "$STATUS_FILE"
fi

# Check if tmux session already exists
if tmux has-session -t "$ROLE" 2>/dev/null; then
    echo "Session '$ROLE' already exists. Attach with: tmux attach -t $ROLE"
    exit 0
fi

# Export agent role for hooks to use
export AGENT_ROLE="$ROLE"
export CLAUDE_CODE_DISABLE_TERMINAL_TITLE=1

# Launch tmux session from agent directory
echo "Launching $ROLE (model: $MODEL) from $AGENT_DIR"
tmux new-session -d -s "$ROLE" -c "$AGENT_DIR" \
    "AGENT_ROLE=$ROLE CLAUDE_CODE_DISABLE_TERMINAL_TITLE=1 claude --model $MODEL"

echo "Agent '$ROLE' started. Attach with: tmux attach -t $ROLE"
