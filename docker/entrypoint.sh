#!/bin/bash
set -euo pipefail

echo "=== Torus Evolution Sprint Container ==="
echo "Date: $(date)"
echo "Claude Code: $(claude --version 2>/dev/null || echo 'not found')"
echo "Node: $(node --version)"
echo "Python: $(python3 --version)"
echo ""

# Verify mounts
if [ ! -f "$HOME/.claude/settings.json" ]; then
    echo "ERROR: ~/.claude not mounted (no settings.json found)"
    exit 1
fi

if [ ! -f "$HOME/.claude.json" ]; then
    echo "ERROR: ~/.claude.json not mounted (OAuth credentials missing)"
    exit 1
fi

echo "Framework mounted: $(ls $HOME/.claude/hooks/gates/gate_*.py 2>/dev/null | wc -l) gates"
echo "Skills: $(ls -d $HOME/.claude/skills/*/SKILL.md 2>/dev/null | wc -l)"
echo "Agents: $(ls $HOME/.claude/agents/*.md 2>/dev/null | wc -l)"
echo ""

# Verify memory server reachable on host
if curl -s --max-time 3 http://127.0.0.1:8741/sse > /dev/null 2>&1; then
    echo "Memory server: REACHABLE (host :8741)"
else
    echo "WARNING: Memory server not reachable on :8741"
fi
echo ""

# Build sprint prompt command
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
fi

echo "Sprint session started. Container will stay alive."
echo "Ctrl+C or 'docker stop' to end."

# Keep container alive
tail -f /dev/null
