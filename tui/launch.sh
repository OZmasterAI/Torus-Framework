#!/usr/bin/env bash
# Torus TUI Dashboard — tmux left-pane launcher
# Usage: bash ~/.claude/tui/launch.sh

SCRIPT="$(cd "$(dirname "$0")" && pwd)/app.py"

if [ -n "$TMUX" ]; then
    # Split LEFT — TUI on left, Claude stays on right
    tmux split-window -hb -l 18% "python3 $SCRIPT"
else
    python3 "$SCRIPT"
fi
