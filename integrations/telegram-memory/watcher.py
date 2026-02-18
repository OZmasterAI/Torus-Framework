#!/usr/bin/env python3
"""Telegram Memory Plugin — Message Watcher

Polls for new messages from OZ. Prints to stdout when a new message arrives,
then exits. Designed to be called in a loop by the session.

Usage: python3 watcher.py [--interval 5] [--since-id 123]
"""

import argparse
import json
import os
import sys
import time

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _PLUGIN_DIR)

LAST_ID_FILE = os.path.join(_PLUGIN_DIR, ".last_seen_id")


def _get_last_seen_id():
    try:
        with open(LAST_ID_FILE) as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return 0


def _save_last_seen_id(msg_id):
    with open(LAST_ID_FILE, "w") as f:
        f.write(str(msg_id))


def watch(interval=5, since_id=None):
    from telegram_memory import _load_config, _get_client, TelegramError

    if since_id is None:
        since_id = _get_last_seen_id()

    cfg = _load_config()
    client = _get_client(cfg)
    client.connect()
    if not client.is_user_authorized():
        print(json.dumps({"error": "Not authenticated"}))
        sys.exit(1)

    # If no since_id, set it to latest message so we only catch NEW ones
    if since_id == 0:
        msgs = client.get_messages("@***REDACTED***", limit=1)
        if msgs and msgs[0]:
            since_id = msgs[0].id
            _save_last_seen_id(since_id)

    try:
        while True:
            messages = client.get_messages("@***REDACTED***", limit=10, min_id=since_id)
            new_msgs = [m for m in messages if m.text and not m.out and m.id > since_id]

            if new_msgs:
                # Sort oldest first
                new_msgs.sort(key=lambda m: m.id)
                result = []
                for m in new_msgs:
                    result.append({
                        "id": m.id,
                        "text": m.text,
                        "date": m.date.isoformat() if m.date else None,
                    })
                # Update last seen
                _save_last_seen_id(new_msgs[-1].id)
                print(json.dumps({"new_messages": result, "count": len(result)}))
                sys.stdout.flush()
                client.disconnect()
                return

            time.sleep(interval)
    except KeyboardInterrupt:
        client.disconnect()
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        client.disconnect()
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=int, default=5)
    parser.add_argument("--since-id", type=int, default=None)
    args = parser.parse_args()
    watch(interval=args.interval, since_id=args.since_id)
