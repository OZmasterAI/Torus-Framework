#!/bin/bash
# Toroidal Teams — Management Commands
# Usage:
#   manage.sh status                    — show all agents' status
#   manage.sh list                      — list active agents
#   manage.sh compact <role>            — send /compact to worker
#   manage.sh clear <role>              — send /clear to worker
#   manage.sh send <role> <command> [priority]  — send task to worker (priority 1-10, default 5)
#   manage.sh suspend <role>            — gracefully suspend (keeps session ID)
#   manage.sh resume <role>             — resume suspended agent

set -uo pipefail

CHANNELS_DIR="$HOME/.claude/channels"
SESSIONS_FILE="$HOME/.claude/toroidal/sessions.json"

cmd_status() {
    echo "=== Toroidal Teams Status ==="
    if [ ! -f "$SESSIONS_FILE" ]; then
        echo "No sessions registered."
        return
    fi
    python3 -c "
import json, os, time
sessions = json.load(open('$SESSIONS_FILE'))
channels = os.path.expanduser('~/.claude/channels')
for role, info in sorted(sessions.items()):
    status_file = os.path.join(channels, f'status_{role}.json')
    if os.path.exists(status_file):
        st = json.load(open(status_file))
        state = st.get('state', 'unknown')
        ts = st.get('timestamp', 0)
        age = int(time.time() - ts) if ts else 0
    else:
        state = 'no-status-file'
        age = 0
    model = info.get('model', '?')
    reg_status = info.get('status', '?')
    print(f'  {role:25s} model={model:8s} registry={reg_status:8s} state={state:12s} ({age}s ago)')
"
}

cmd_list() {
    if [ ! -f "$SESSIONS_FILE" ]; then
        echo "No sessions."
        return
    fi
    python3 -c "
import json
for role, info in json.load(open('$SESSIONS_FILE')).items():
    if info.get('status') == 'active':
        print(f\"{role} ({info.get('model', '?')})\")
"
}

cmd_send() {
    local ROLE="$1"
    local CMD="$2"
    local PRIORITY="${3:-5}"
    python3 - "$CMD" "$ROLE" "$PRIORITY" <<'PYEOF'
import sys, os
sys.path.insert(0, os.path.expanduser("~/.claude/hooks"))
from shared.agent_channel import create_task
title, role, pri = sys.argv[1], sys.argv[2], int(sys.argv[3])
tid = create_task(title=title, created_by="manage.sh", assigned_to=role, priority=pri)
if tid:
    print(f"Task created: {tid} (priority={pri}, role={role})")
else:
    print("ERROR: Failed to create task", file=sys.stderr)
    sys.exit(1)
PYEOF
}

cmd_suspend() {
    local ROLE="$1"
    # Get Claude session ID before killing
    local SESSION_ID
    SESSION_ID=$(jq -r ".\"$ROLE\".session_id // \"unknown\"" "$SESSIONS_FILE")
    local MODEL
    MODEL=$(jq -r ".\"$ROLE\".model // \"unknown\"" "$SESSIONS_FILE")

    # Graceful exit
    if tmux has-session -t "$ROLE" 2>/dev/null; then
        tmux send-keys -t "$ROLE" "/exit" Enter
        sleep 2
        tmux kill-session -t "$ROLE" 2>/dev/null || true
    fi

    # Update registry to suspended (preserve session_id for resume)
    "$HOME/.claude/toroidal/session_register.sh" "$ROLE" "$SESSION_ID" "$MODEL" "suspended"
    echo "$ROLE suspended (session: $SESSION_ID)"
}

cmd_resume() {
    local ROLE="$1"
    local SESSION_ID
    SESSION_ID=$(jq -r ".\"$ROLE\".session_id // empty" "$SESSIONS_FILE")
    local MODEL
    MODEL=$(jq -r ".\"$ROLE\".model // \"sonnet\"" "$SESSIONS_FILE")
    local AGENT_DIR="$HOME/agents/$ROLE"

    if [ -z "$SESSION_ID" ]; then
        echo "ERROR: No session ID found for $ROLE — use launch.sh instead"
        exit 1
    fi

    if tmux has-session -t "$ROLE" 2>/dev/null; then
        echo "$ROLE already has an active tmux session"
        exit 0
    fi

    echo "Resuming $ROLE (session: $SESSION_ID, model: $MODEL)"
    tmux new-session -d -s "$ROLE" -c "$AGENT_DIR" \
        "AGENT_ROLE=$ROLE CLAUDE_CODE_DISABLE_TERMINAL_TITLE=1 claude --dangerously-skip-permissions --resume $SESSION_ID --model $MODEL"

    "$HOME/.claude/toroidal/session_register.sh" "$ROLE" "$SESSION_ID" "$MODEL" "active"
    echo "$ROLE resumed. Attach with: tmux attach -t $ROLE"
}

ACTION="${1:?Usage: manage.sh <status|list|compact|clear|send|suspend|resume> [role] [args]}"

case "$ACTION" in
    status)  cmd_status ;;
    list)    cmd_list ;;
    compact) cmd_send "${2:?role required}" "/compact" ;;
    clear)   cmd_send "${2:?role required}" "/clear" ;;
    send)    cmd_send "${2:?role required}" "${3:?command required}" "${4:-5}" ;;
    suspend) cmd_suspend "${2:?role required}" ;;
    resume)  cmd_resume "${2:?role required}" ;;
    *)       echo "Unknown action: $ACTION"; exit 1 ;;
esac
