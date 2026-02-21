#!/usr/bin/env python3
"""Stop hook — clean up stale state from interrupted sessions.

Clears pending_verification and workspace locks so the next session
starts clean. Fail-open: always exits 0.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from shared.state import load_state, save_state


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}

    session_id = payload.get("session_id", "main")
    state = load_state(session_id=session_id)

    changed = False

    # Clear stale pending verifications
    if state.get("pending_verification"):
        state["pending_verification"] = []
        changed = True

    # Release workspace locks
    if state.get("workspace_lock"):
        state["workspace_lock"] = None
        changed = True

    if changed:
        save_state(state, session_id=session_id)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
