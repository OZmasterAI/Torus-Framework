#!/bin/bash
set -euo pipefail

echo "=== Torus Evolution Sprint Container ==="
echo "Date: $(date)"
echo "Claude Code: $(claude --version 2>/dev/null || echo 'not found')"
echo "Node: $(node --version)"
echo "Python: $(python3 --version)"
echo ""

# ── Verify source repo mount ──
REPO_MOUNT="/mnt/repo"
if [ ! -d "$REPO_MOUNT/.git" ]; then
    echo "ERROR: Repo not mounted at $REPO_MOUNT"
    exit 1
fi

# ── Verify OAuth credentials ──
if [ ! -f "$HOME/.claude.json" ]; then
    echo "ERROR: ~/.claude.json not mounted (OAuth credentials missing)"
    exit 1
fi
echo "Auth: OAuth credentials present"

# ── Create fresh working copy from mounted repo ──
echo ""
echo "--- Creating fresh working copy ---"
WORK="$HOME/.claude"
rm -rf "$WORK"
cp -a "$REPO_MOUNT" "$WORK"
echo "  Copied from $(cd "$REPO_MOUNT" && git log --oneline -1)"

# ── Strip mcp.json to memory-only (stdio servers hang without full deps) ──
echo ""
echo "--- Configuring MCP for Docker ---"
cat > "$WORK/mcp.json" << 'MCPEOF'
{
  "mcpServers": {
    "memory": {
      "type": "sse",
      "url": "http://localhost:8741/sse"
    }
  }
}
MCPEOF
echo "  MCP: memory (SSE) only — search/analytics stripped (missing deps in container)"

# ── Copy gitignored config files from mount ──
for f in config.json; do
    if [ -f "$REPO_MOUNT/$f" ] && [ ! -f "$WORK/$f" ]; then
        cp "$REPO_MOUNT/$f" "$WORK/$f"
        echo "  Copied: $f"
    fi
done

echo ""
echo "Framework: $(ls $WORK/hooks/gates/gate_*.py 2>/dev/null | wc -l) gates"
echo "Skills: $(ls -d $WORK/skills/*/SKILL.md 2>/dev/null | wc -l)"
echo "Agents: $(ls $WORK/agents/*.md 2>/dev/null | wc -l)"
echo ""

# ── Verify memory server reachable on host ──
if curl -s --max-time 3 http://127.0.0.1:8741/sse > /dev/null 2>&1; then
    echo "Memory server: REACHABLE (host :8741)"
else
    echo "WARNING: Memory server not reachable on :8741"
fi
echo ""

# ── Launch Claude Code in tmux ──
PROMPT_FILE="$WORK/docker/sprint-prompt.md"

echo "=== Starting tmux session 'sprint' ==="
echo "Attach: docker exec -it evolution-sprint tmux attach -t sprint"
echo ""

tmux new-session -d -s sprint -x 200 -y 50

if [ -f "$PROMPT_FILE" ]; then
    tmux send-keys -t sprint "cat $PROMPT_FILE | claude --dangerously-skip-permissions -p -" Enter
else
    tmux send-keys -t sprint "claude --dangerously-skip-permissions" Enter
fi

echo "Sprint session started. Container will stay alive."
echo "Ctrl+C or 'docker stop' to end."

# Keep container alive
tail -f /dev/null
