#!/usr/bin/env python3
"""Telegram Bot — One-Time Setup

Validates config.json, tests Bot API connection, initializes DB.

Usage:
    python3 setup.py
"""

import json
import os
import sys
import urllib.request
import urllib.error

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _PLUGIN_DIR)


def main():
    print("=== Telegram Bot Setup ===\n")

    # Load config
    from config import load_config, BotConfigError
    try:
        cfg = load_config()
    except BotConfigError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    token = cfg["bot_token"]
    print(f"  Token: {token[:10]}...{token[-4:]}")
    print(f"  Allowed users: {cfg['allowed_users']}")
    print(f"  Allowed groups: {cfg['allowed_groups']}")
    print()

    # Test Bot API
    print("Testing Bot API connection...")
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        resp = urllib.request.urlopen(url, timeout=10)
        data = json.loads(resp.read().decode())
        if data.get("ok"):
            bot = data["result"]
            print(f"  Bot: @{bot.get('username', '?')} ({bot.get('first_name', '?')})")
            print(f"  Bot ID: {bot.get('id', '?')}")
        else:
            print(f"ERROR: API returned ok=false: {data}")
            sys.exit(1)
    except urllib.error.HTTPError as e:
        print(f"ERROR: Bot API returned HTTP {e.code}")
        if e.code == 401:
            print("  Token is invalid. Get a new one from @BotFather.")
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"ERROR: Cannot reach Telegram API: {e}")
        sys.exit(1)

    print()

    # Initialize database
    from db import init_db
    db_path = os.path.join(_PLUGIN_DIR, "msg_log.db")
    init_db(db_path)
    print(f"  Database: {db_path} (initialized)")

    # Create empty sessions file
    sessions_path = os.path.join(_PLUGIN_DIR, "sessions.json")
    if not os.path.isfile(sessions_path):
        with open(sessions_path, "w") as f:
            json.dump({}, f)
        print(f"  Sessions: {sessions_path} (created)")
    else:
        print(f"  Sessions: {sessions_path} (exists)")

    print("\nSetup complete! Run: python3 bot.py")


if __name__ == "__main__":
    main()
