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

# ── Copy lightweight framework parts into ~/.claude ──
CONF="$HOME/.claude"
if [ -d "$REPO_MOUNT" ]; then
    echo "--- Loading framework into ~/.claude ---"
    for d in skills agents rules dormant skill-library; do
        if [ -d "$REPO_MOUNT/$d" ]; then
            cp -r "$REPO_MOUNT/$d" "$CONF/$d"
            echo "  Copied: $d/"
        fi
    done
    # Copy individual config files
    for f in CLAUDE.md config.json; do
        if [ -f "$REPO_MOUNT/$f" ]; then
            cp "$REPO_MOUNT/$f" "$CONF/$f"
            echo "  Copied: $f"
        fi
    done
    echo "  Skills: $(ls -d $CONF/skills/*/SKILL.md 2>/dev/null | wc -l)"
    echo "  Agents: $(ls $CONF/agents/*.md 2>/dev/null | wc -l)"
fi
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
