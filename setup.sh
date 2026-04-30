#!/usr/bin/env bash
set -euo pipefail

CLAUDE_DIR="${1:-$HOME/.claude}"
cd "$CLAUDE_DIR"

echo "==> Initializing submodules (toolshed + torus-skills)..."
git submodule update --init --recursive

echo "==> Installing Python dependencies..."
pip install -r hooks/requirements.txt

if [ -f config.example.json ] && [ ! -f config.json ]; then
    cp config.example.json config.json
    echo "==> Created config.json from template"
fi

if [ -f mcp.example.json ] && [ ! -f mcp.json ]; then
    cp mcp.example.json mcp.json
    echo "==> Created mcp.json from template (edit to replace \$HOME with your home path)"
fi

if [ -f hooks/setup_ramdisk.sh ]; then
    echo "==> Setting up ramdisk..."
    bash hooks/setup_ramdisk.sh
fi

echo "==> Done. Run 'cd $CLAUDE_DIR && claude' to start."
