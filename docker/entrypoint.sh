#!/bin/bash
set -euo pipefail

echo "=== Torus Evolution Sprint Container ==="
echo "Date: $(date)"
echo "Claude Code: $(claude --version 2>/dev/null || echo 'not found')"
echo "Node: $(node --version)"
echo "Python: $(python3 --version)"
echo ""

# ── Verify OAuth credentials ──
if [ ! -f "$HOME/.claude.json" ]; then
    echo "WARNING: ~/.claude.json not mounted — you'll need to log in manually"
else
    echo "Auth: OAuth credentials present"
fi

# ── Workspace: shallow clone from mounted repo ──
REPO_MOUNT="/mnt/repo"
WORKSPACE="$HOME/workspace"
if [ -d "$REPO_MOUNT/.git" ]; then
    echo ""
    echo "--- Creating workspace ---"
    rm -rf "$WORKSPACE"
    git clone --depth 1 --single-branch "file://$REPO_MOUNT" "$WORKSPACE" 2>&1 | tail -1
    echo "  Path: $WORKSPACE"
fi
echo ""

# ~/.claude is baked into the image as bare minimum (no hooks, no plugins, no MCP)
echo "Config: bare minimum (no hooks, no plugins, no MCP)"
echo ""

echo "=== Ready ==="
echo ""

# ── Launch tmux session ──
tmux new-session -d -s sprint -x 200 -y 50

if [ -d "$WORKSPACE" ]; then
    tmux send-keys -t sprint "cd $WORKSPACE" Enter
fi

tmux send-keys -t sprint "claude --dangerously-skip-permissions" Enter

echo "Sprint session started. Container will stay alive."
echo "Attach: docker exec -it evolution-sprint tmux attach -t sprint"

# Keep container alive
tail -f /dev/null
