#!/usr/bin/env python3
"""Telegram Memory Plugin — One-Time Setup

Run interactively to:
1. Validate config.json credentials
2. Authenticate with Telegram (SMS code)
3. Send a test message to Saved Messages

Usage:
    python3 setup.py
"""

import json
import os
import sys

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_PLUGIN_DIR, "config.json")


def main():
    print("=== Telegram Memory Plugin Setup ===\n")

    # Load config
    try:
        with open(_CONFIG_PATH) as f:
            cfg = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: {_CONFIG_PATH} not found.")
        print("Create it with api_id, api_hash, and phone fields.")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in config.json: {e}")
        sys.exit(1)

    # Validate required fields
    api_id = cfg.get("api_id", 0)
    api_hash = cfg.get("api_hash", "")
    phone = cfg.get("phone", "")

    if not api_id or api_id == 0:
        print("ERROR: api_id is not set in config.json")
        print("Get your API credentials at https://my.telegram.org/apps")
        sys.exit(1)
    if not api_hash:
        print("ERROR: api_hash is not set in config.json")
        sys.exit(1)
    if not phone:
        print("ERROR: phone is not set in config.json (e.g. '+1234567890')")
        sys.exit(1)

    print(f"  API ID: {api_id}")
    print(f"  Phone:  {phone}")
    print()

    # Import Telethon
    try:
        from telethon.sync import TelegramClient
    except ImportError:
        print("ERROR: Telethon not installed.")
        print("Run: pip install 'telethon>=1.37,<2.0'")
        sys.exit(1)

    # Expand session path
    session_path = os.path.expanduser(cfg.get(
        "session_path",
        os.path.join(_PLUGIN_DIR, "session", "telegram")
    ))
    session_dir = os.path.dirname(session_path)
    os.makedirs(session_dir, exist_ok=True)

    print("Connecting to Telegram...")
    print("(You may receive an SMS code or Telegram notification)\n")

    try:
        with TelegramClient(session_path, api_id, api_hash) as client:
            client.start(phone=phone)

            # Verify connection
            me = client.get_me()
            print(f"Authenticated as: {me.first_name} (@{me.username or 'no username'})")
            print()

            # Send test message
            test_msg = (
                "<b>Telegram Memory Plugin connected.</b>\n\n"
                "This account is now linked to the Torus Framework.\n"
                "Session summaries will appear here as searchable messages.\n\n"
                "#torus #setup"
            )
            msg = client.send_message("me", test_msg, parse_mode="html")
            print(f"Test message sent (ID: {msg.id})")
            print(f"Check your Telegram Saved Messages to confirm.\n")
            print(f"Session file: {session_path}.session")
            print("WARNING: Keep the session file secure — it grants account access.")
            print("\nSetup complete!")

    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
