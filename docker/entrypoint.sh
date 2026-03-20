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

# ── Workspace: copy project code if repo is mounted ──
REPO_MOUNT="/mnt/repo"
WORKSPACE="$HOME/workspace"
if [ -d "$REPO_MOUNT/.git" ]; then
    echo ""
    echo "--- Creating workspace from mounted repo ---"
    rm -rf "$WORKSPACE"
    cp -a "$REPO_MOUNT" "$WORKSPACE"
    echo "  Copied from $(cd "$REPO_MOUNT" && git log --oneline -1)"
    echo "  Path: $WORKSPACE"
fi
echo ""

# ~/.claude is baked into the image as bare minimum (no hooks, no plugins, no MCP)
# This avoids the host's heavy hook framework hanging in Docker
echo "Config: bare minimum (no hooks, no plugins, no MCP)"
echo ""

echo "=== Ready ==="
echo "  Run: claude --dangerously-skip-permissions"
if [ -d "$WORKSPACE" ]; then
    echo "  Workspace: cd ~/workspace"
fi
echo "  Attach: docker exec -it evolution-sprint tmux attach -t sprint"
echo ""

# ── Launch tmux session ──
tmux new-session -d -s sprint -x 200 -y 50

# Drop into workspace if available
if [ -d "$WORKSPACE" ]; then
    tmux send-keys -t sprint "cd $WORKSPACE" Enter
fi

# Just open a shell — user does OAuth login manually if needed
tmux send-keys -t sprint "claude --dangerously-skip-permissions" Enter

echo "Sprint session started. Container will stay alive."

# Keep container alive
tail -f /dev/null
