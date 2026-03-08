#!/usr/bin/env python3
"""TG Bot Response — Stop Hook

Fires after every Claude response. If a TG bot pending marker exists,
writes the clean last_assistant_message to a response signal file for
the bot to pick up.

Same pattern as tts_signal.py — pending marker + signal file.

Input (stdin JSON):
  {"session_id": "...", "last_assistant_message": "...", "hook_event_name": "Stop"}

Output: /tmp/tgbot-response-{target}.json
  {"text": "response text", "timestamp": 1709683200.0}

Pending marker: /tmp/tgbot-pending-{target}

Fail-open: always exits 0.
"""

import json
import os
import sys
import time

PENDING_PREFIX = "tgbot-pending-"


def _get_ancestor_pids():
    """Walk the process tree upward, return set of ancestor PIDs."""
    ancestors = set()
    pid = os.getpid()
    while pid > 1:
        ancestors.add(pid)
        try:
            with open(f"/proc/{pid}/stat") as f:
                pid = int(f.read().split()[3])
        except (OSError, ValueError, IndexError):
            break
    return ancestors


def main():
    try:
        data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        data = {}

    # Find any pending marker
    pending_files = [f for f in os.listdir("/tmp") if f.startswith(PENDING_PREFIX)]
    if not pending_files:
        sys.exit(0)

    message = (data.get("last_assistant_message") or "").strip()
    if not message:
        sys.exit(0)

    ancestors = _get_ancestor_pids()

    # Write signal for each pending target and consume marker
    for pf in pending_files:
        pending_path = os.path.join("/tmp", pf)
        target = pf.replace(PENDING_PREFIX, "")
        signal_file = f"/tmp/tgbot-response-{target}.json"

        # Read the pending marker to check session ownership
        try:
            with open(pending_path) as f:
                marker = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue

        # If marker has a pane_pid, only the Claude instance running
        # inside that tmux pane (i.e., descended from that PID) may claim it
        pane_pid = marker.get("pane_pid")
        if pane_pid and pane_pid not in ancestors:
            continue

        # Consume the pending marker
        try:
            os.unlink(pending_path)
        except OSError:
            continue

        # Write signal atomically
        signal = json.dumps({"text": message, "timestamp": time.time()})
        tmp = signal_file + ".tmp"
        try:
            with open(tmp, "w") as f:
                f.write(signal)
            os.replace(tmp, signal_file)
        except OSError:
            pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
