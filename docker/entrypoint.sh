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

# ── Copy framework into ~/.claude (skip heavy dirs) ──
REPO_MOUNT="/mnt/repo"
CONF="$HOME/.claude"
if [ -d "$REPO_MOUNT" ]; then
    echo ""
    echo "--- Loading framework ---"
    # rsync everything except the multi-GB junk dirs
    rsync -a --exclude='projects' --exclude='integrations' --exclude='debug' \
        --exclude='file-history' --exclude='paste-cache' --exclude='plugins' \
        --exclude='.git' --exclude='__pycache__' \
        "$REPO_MOUNT/" "$CONF/"
    echo "  Gates: $(ls $CONF/hooks/gates/gate_*.py 2>/dev/null | wc -l)"
    echo "  Skills: $(ls -d $CONF/skills/*/SKILL.md 2>/dev/null | wc -l)"
    echo "  Agents: $(ls $CONF/agents/*.md 2>/dev/null | wc -l)"
fi

# ── Fix settings.json for Docker: disable plugins, strip statusLine ──
echo ""
echo "--- Patching config for Docker ---"
python3 -c "
import json
with open('$CONF/settings.json', 'r') as f:
    data = json.load(f)
# Disable all LSP plugins (not installed in container)
data['enabledPlugins'] = {k: False for k in data.get('enabledPlugins', {})}
# Remove statusLine (needs deps that may not be available)
data.pop('statusLine', None)
with open('$CONF/settings.json', 'w') as f:
    json.dump(data, f, indent=2)
print('  Plugins: all disabled')
print('  StatusLine: removed')
"

# ── Strip MCP to memory-only (stdio servers may hang) ──
cat > "$CONF/mcp.json" << 'MCPEOF'
{
  "mcpServers": {
    "memory": {
      "type": "sse",
      "url": "http://localhost:8741/sse"
    }
  }
}
MCPEOF
echo "  MCP: memory (SSE) only"

# ── Check memory server ──
echo ""
if curl -s --max-time 3 http://127.0.0.1:8741/sse > /dev/null 2>&1; then
    echo "Memory server: REACHABLE"
else
    echo "Memory server: NOT reachable (host :8741)"
fi

echo ""
echo "=== Ready ==="
echo ""

# ── Launch tmux session ──
tmux new-session -d -s sprint -x 200 -y 50
tmux send-keys -t sprint "cd $CONF && claude --dangerously-skip-permissions" Enter

echo "Sprint session started. Container will stay alive."
echo "Attach: docker exec -it evolution-sprint tmux attach -t sprint"

# Keep container alive
tail -f /dev/null
