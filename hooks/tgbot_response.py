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

    # Write signal for each pending target and consume marker
    for pf in pending_files:
        pending_path = os.path.join("/tmp", pf)
        target = pf.replace(PENDING_PREFIX, "")
        signal_file = f"/tmp/tgbot-response-{target}.json"

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
