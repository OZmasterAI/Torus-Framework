#!/usr/bin/env python3
"""Rewrite entrypoint.sh with file-based prompt delivery."""

import os

path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "entrypoint.sh")
with open(path, "r") as f:
    content = f.read()

# Replace the prompt loading and tmux launch section
old_block = """# Load sprint prompt if provided
SPRINT_PROMPT="${SPRINT_PROMPT:-}"
if [ -f "$HOME/.claude/docker/sprint-prompt.md" ]; then
    SPRINT_PROMPT=$(cat "$HOME/.claude/docker/sprint-prompt.md")
fi

echo "=== Starting tmux session 'sprint' ==="
echo "Attach from host: docker exec -it evolution-sprint tmux attach -t sprint"
echo ""

# Start Claude Code inside tmux so the user can attach and watch
tmux new-session -d -s sprint -x 200 -y 50

if [ -n "$SPRINT_PROMPT" ]; then
    # Send the sprint prompt to Claude Code
    tmux send-keys -t sprint "claude --dangerously-skip-permissions -p \\"$SPRINT_PROMPT\\"" Enter
else
    # Interactive mode
    tmux send-keys -t sprint "claude --dangerously-skip-permissions" Enter
fi"""

new_block = """# Build sprint prompt command
PROMPT_FILE="$HOME/.claude/docker/sprint-prompt.md"

echo "=== Starting tmux session 'sprint' ==="
echo "Attach from host: docker attach evolution-sprint tmux attach -t sprint"
echo ""

# Start Claude Code inside tmux so the user can attach and watch
tmux new-session -d -s sprint -x 200 -y 50

if [ -f "$PROMPT_FILE" ]; then
    # Pipe prompt from file to avoid shell escaping issues
    tmux send-keys -t sprint "cat $PROMPT_FILE | claude --dangerously-skip-permissions -p -" Enter
else
    # Interactive mode
    tmux send-keys -t sprint "claude --dangerously-skip-permissions" Enter
fi"""

if old_block in content:
    content = content.replace(old_block, new_block)
    with open(path, "w") as f:
        f.write(content)
    os.chmod(path, 0o755)
    print("entrypoint.sh updated successfully")
else:
    # Already updated or different format — write fresh
    print("Old block not found — entrypoint may already be updated")
    print("Current content starts with:", content[:100])
