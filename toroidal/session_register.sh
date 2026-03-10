#!/bin/bash
# Register/update a session in sessions.json
# Usage: session_register.sh <role> <session_id> <model> <status>

set -uo pipefail

SESSIONS_FILE="$HOME/.claude/toroidal/sessions.json"
ROLE="${1:?}"
SESSION_ID="${2:?}"
MODEL="${3:-sonnet}"
STATUS="${4:-active}"

# Read existing
if [ -f "$SESSIONS_FILE" ]; then
    DATA=$(cat "$SESSIONS_FILE")
else
    DATA="{}"
fi

# Update (pass values via env to avoid shell interpolation in Python)
echo "$DATA" | SREG_ROLE="$ROLE" SREG_SID="$SESSION_ID" SREG_MODEL="$MODEL" SREG_STATUS="$STATUS" python3 -c "
import sys, json, time, os
data = json.load(sys.stdin)
data[os.environ['SREG_ROLE']] = {
    'session_id': os.environ['SREG_SID'],
    'model': os.environ['SREG_MODEL'],
    'status': os.environ['SREG_STATUS'],
    'updated_at': int(time.time())
}
json.dump(data, sys.stdout, indent=2)
" > "${SESSIONS_FILE}.tmp"
mv "${SESSIONS_FILE}.tmp" "$SESSIONS_FILE"
