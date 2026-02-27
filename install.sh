#!/usr/bin/env bash
set -euo pipefail

echo "Torus Framework Installer"
echo "========================="
echo ""

# Check prerequisites
command -v python3 >/dev/null 2>&1 || { echo "Error: python3 is required but not found."; exit 1; }
command -v claude >/dev/null 2>&1 || echo "Warning: Claude Code CLI not found. Install it from https://docs.anthropic.com/en/docs/claude-code"

# Verify we're in the right directory
if [ ! -f ~/.claude/hooks/requirements.txt ]; then
    echo "Error: Expected to find ~/.claude/hooks/requirements.txt"
    echo "Make sure you cloned the repo into ~/.claude/"
    exit 1
fi

# Install Python dependencies
echo ""
echo "Installing Python dependencies..."
pip install -r ~/.claude/hooks/requirements.txt

# Copy config templates (don't overwrite existing)
echo ""
echo "Setting up configuration..."

if [ -f ~/.claude/config.json ]; then
    echo "  config.json already exists, skipping."
else
    cp ~/.claude/config.example.json ~/.claude/config.json
    echo "  Created config.json from template."
fi

if [ -f ~/.claude/mcp.json ]; then
    echo "  mcp.json already exists, skipping."
else
    sed "s|\$HOME|$HOME|g" ~/.claude/mcp.example.json > ~/.claude/mcp.json
    echo "  Created mcp.json (replaced \$HOME with $HOME)"
fi

# Optional: ramdisk setup
echo ""
read -p "Set up ramdisk for fast state I/O? (recommended) [Y/n] " ramdisk
if [[ "${ramdisk:-Y}" =~ ^[Yy] ]]; then
    bash ~/.claude/hooks/setup_ramdisk.sh
fi

# Optional: ruff formatter
echo ""
read -p "Install ruff for auto-formatting? [Y/n] " ruff_choice
if [[ "${ruff_choice:-Y}" =~ ^[Yy] ]]; then
    pip install ruff
fi

echo ""
echo "========================="
echo "Setup complete!"
echo ""
echo "Launch with:  cd ~/.claude && claude"
echo ""
echo "Note: First run will download the embedding model (~270MB)."
echo "This is a one-time download for semantic memory search."
