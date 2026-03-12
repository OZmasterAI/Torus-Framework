#!/usr/bin/env python3
"""SessionStart hook — captures real Claude Code session ID for Toroidal Teams agents.

Reads session_id from stdin JSON. If AGENT_ROLE is set (i.e., this is a managed agent),
writes the real session ID to sessions.json so `claude --resume` works later.
"""

import sys
import json
import os
import time


def main():
    role = os.environ.get("AGENT_ROLE", "")
    if not role:
        return  # Not a Toroidal Teams session

    data = json.loads(sys.stdin.read())
    session_id = data.get("session_id", "")
    if not session_id:
        return

    sessions_file = os.path.expanduser("~/.claude/toroidal/sessions.json")
    if not os.path.exists(sessions_file):
        sessions = {}
    else:
        with open(sessions_file) as f:
            sessions = json.load(f)

    # Update only the session_id field, preserve other fields
    if role in sessions:
        sessions[role]["session_id"] = session_id
        sessions[role]["updated_at"] = int(time.time())
    else:
        sessions[role] = {
            "session_id": session_id,
            "model": os.environ.get("CLAUDE_MODEL", "unknown"),
            "status": "active",
            "updated_at": int(time.time()),
        }

    tmp = sessions_file + ".tmp"
    with open(tmp, "w") as f:
        json.dump(sessions, f, indent=2)
    os.replace(tmp, sessions_file)


if __name__ == "__main__":
    main()
