#!/usr/bin/env python3
"""Stop hook — clean up stale state and capture last assistant message.

Fires after every Claude response. Performs two duties:
1. Clears pending_verification and workspace locks so the next session
   starts clean.
2. Saves last_assistant_message to a temp file for session_end.py to
   include in LIVE_STATE.json (enables better session handoffs).

Fail-open: always exits 0.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from shared.state import load_state, save_state

# Last-message capture file (ramdisk for speed, overwritten each Stop)
_LAST_MSG_PATH = None


def _get_last_msg_path():
    """Get path for last-message capture file (ramdisk or disk fallback)."""
    global _LAST_MSG_PATH
    if _LAST_MSG_PATH is not None:
        return _LAST_MSG_PATH
    try:
        from shared.ramdisk import TMPFS_STATE_DIR
        if os.path.isdir(TMPFS_STATE_DIR):
            _LAST_MSG_PATH = os.path.join(TMPFS_STATE_DIR, ".last_assistant_message")
            return _LAST_MSG_PATH
    except ImportError:
        pass
    _LAST_MSG_PATH = os.path.join(os.path.dirname(__file__), ".last_assistant_message")
    return _LAST_MSG_PATH


def _capture_last_message(payload):
    """Save last_assistant_message to disk for session_end.py consumption."""
    msg = payload.get("last_assistant_message", "")
    if not msg or not isinstance(msg, str):
        return
    # Truncate to 1000 chars — Stop fires frequently, keep file small
    msg = msg[:1000]
    try:
        path = _get_last_msg_path()
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            f.write(msg)
        os.replace(tmp, path)
    except OSError:
        pass


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}

    # Capture last_assistant_message for session handoff
    _capture_last_message(payload)

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
