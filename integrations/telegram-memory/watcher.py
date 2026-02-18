#!/usr/bin/env python3
"""Telegram Memory Plugin — Message Watcher

Runs continuously, polls for new messages from OZ every N seconds.
Appends new messages to .inbox.jsonl and prints to stdout.
Keeps the Telethon connection open — no restart needed.

Usage: python3 watcher.py [--interval 5]
"""

import argparse
import json
import os
import sys
import time

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _PLUGIN_DIR)

LAST_ID_FILE = os.path.join(_PLUGIN_DIR, ".last_seen_id")
INBOX_FILE = os.path.join(_PLUGIN_DIR, ".inbox.jsonl")


def _get_last_seen_id():
    try:
        with open(LAST_ID_FILE) as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return 0


def _save_last_seen_id(msg_id):
    with open(LAST_ID_FILE, "w") as f:
        f.write(str(msg_id))


def watch(interval=5):
    from telegram_memory import _load_config, _get_client

    since_id = _get_last_seen_id()
    cfg = _load_config()
    client = _get_client(cfg)
    client.connect()
    if not client.is_user_authorized():
        print("ERROR: Not authenticated", file=sys.stderr)
        sys.exit(1)

    # Set baseline to latest message so we only catch NEW ones
    if since_id == 0:
        msgs = client.get_messages("@***REDACTED***", limit=1)
        if msgs and msgs[0]:
            since_id = msgs[0].id
            _save_last_seen_id(since_id)

    print(f"Watching for messages (since ID {since_id}, polling every {interval}s)...", file=sys.stderr)

    try:
        while True:
            messages = client.get_messages("@***REDACTED***", limit=10, min_id=since_id)
            new_msgs = [m for m in messages if m.text and not m.out and m.id > since_id]

            if new_msgs:
                new_msgs.sort(key=lambda m: m.id)
                for m in new_msgs:
                    entry = {
                        "id": m.id,
                        "text": m.text,
                        "date": m.date.isoformat() if m.date else None,
                        "ts": time.time(),
                    }
                    # Print to stdout (session can tail the output file)
                    print(json.dumps(entry))
                    sys.stdout.flush()

                    # Also append to inbox file (persistent across checks)
                    with open(INBOX_FILE, "a") as f:
                        f.write(json.dumps(entry) + "\n")

                since_id = new_msgs[-1].id
                _save_last_seen_id(since_id)

            time.sleep(interval)

    except KeyboardInterrupt:
        pass
    finally:
        client.disconnect()
        print("Watcher stopped.", file=sys.stderr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=int, default=5)
    args = parser.parse_args()
    watch(interval=args.interval)
