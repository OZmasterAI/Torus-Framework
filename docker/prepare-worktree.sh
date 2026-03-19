#!/bin/bash
# Prepare the evolution-sprint worktree with all dormant components activated
set -euo pipefail

WORKTREE="/home/crab/agents/evolution-sprint"

if [ ! -d "$WORKTREE" ]; then
    echo "ERROR: Worktree not found at $WORKTREE"
    exit 1
fi

echo "=== Preparing Evolution Sprint Worktree ==="
echo "Path: $WORKTREE"
echo ""

# ── 1. Activate dormant skills ──
echo "--- Activating dormant skills ---"
DORMANT_SKILLS=(
    "self-improve/diagnose"
    "self-improve/introspect"
    "self-improve/sprint"
    "self-improve/super-health"
    "specialty/security-scan"
    "specialty/refactor"
    "specialty/report"
)

for skill_path in "${DORMANT_SKILLS[@]}"; do
    skill_name=$(basename "$skill_path")
    src="$WORKTREE/dormant/skills/$skill_path"
    dst="$WORKTREE/skills/$skill_name"
    if [ -d "$src" ] && [ ! -d "$dst" ]; then
        cp -r "$src" "$dst"
        echo "  Activated: $skill_name"
    elif [ -d "$dst" ]; then
        echo "  Already active: $skill_name"
    else
        echo "  Not found: $skill_path"
    fi
done

# ── 2. Activate dormant agents ──
echo ""
echo "--- Activating dormant agents ---"
DORMANT_AGENTS=("team-lead.md" "code-reviewer.md" "test-writer.md")

for agent in "${DORMANT_AGENTS[@]}"; do
    src="$WORKTREE/dormant/agents/$agent"
    dst="$WORKTREE/agents/$agent"
    if [ -f "$src" ] && [ ! -f "$dst" ]; then
        cp "$src" "$dst"
        echo "  Activated: $agent"
    elif [ -f "$dst" ]; then
        echo "  Already active: $agent"
    else
        echo "  Not found: $agent"
    fi
done

# ── 3. Copy gitignored files that the worktree doesn't get ──
echo ""
echo "--- Copying gitignored config files ---"
LIVE="$HOME/.claude"
for f in config.json mcp.json; do
    if [ -f "$LIVE/$f" ] && [ ! -f "$WORKTREE/$f" ]; then
        cp "$LIVE/$f" "$WORKTREE/$f"
        echo "  Copied: $f"
    elif [ -f "$WORKTREE/$f" ]; then
        echo "  Already exists: $f"
    fi
done

# ── 4. Flip AGENT_TEAMS to 1 ──
echo ""
echo "--- Enabling experimental agent teams ---"
if [ -f "$WORKTREE/settings.json" ]; then
    python3 -c "
import json
with open('$WORKTREE/settings.json', 'r') as f:
    data = json.load(f)
if 'env' not in data:
    data['env'] = {}
data['env']['CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS'] = '1'
with open('$WORKTREE/settings.json', 'w') as f:
    json.dump(data, f, indent=2)
print('  CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS = 1')
"
fi

# ── 5. Set security_profile to refactor ──
echo ""
echo "--- Setting security_profile to refactor ---"
if [ -f "$WORKTREE/config.json" ]; then
    python3 -c "
import json
with open('$WORKTREE/config.json', 'r') as f:
    data = json.load(f)
data['security_profile'] = 'refactor'
with open('$WORKTREE/config.json', 'w') as f:
    json.dump(data, f, indent=2)
print('  security_profile = refactor')
"
fi

# ── 6. Re-enable analytics MCP server ──
echo ""
echo "--- Re-enabling analytics MCP server ---"
# Add analytics to mcp.json in the worktree
if [ -f "$WORKTREE/mcp.json" ]; then
    python3 -c "
import json
with open('$WORKTREE/mcp.json', 'r') as f:
    data = json.load(f)
if 'mcpServers' not in data:
    data['mcpServers'] = {}
data['mcpServers']['analytics'] = {
    'command': '/usr/bin/python3',
    'args': ['/home/crab/.claude/hooks/analytics_server.py'],
    'type': 'stdio'
}
with open('$WORKTREE/mcp.json', 'w') as f:
    json.dump(data, f, indent=2)
print('  analytics MCP server added to mcp.json')
"
fi

# ── 7. Summary ──
echo ""
echo "=== Worktree Ready ==="
echo "Skills: $(ls -d $WORKTREE/skills/*/SKILL.md 2>/dev/null | wc -l)"
echo "Agents: $(ls $WORKTREE/agents/*.md 2>/dev/null | wc -l)"
echo "Security: refactor"
echo "Agent Teams: enabled"
echo "Analytics MCP: enabled"
echo ""
echo "Branch: $(cd $WORKTREE && git branch --show-current)"
echo "Changes: $(cd $WORKTREE && git status --short | wc -l) files modified"
