#!/usr/bin/env python3
"""Telegram Mirror User — UserPromptSubmit Hook

Mirrors user messages from all sessions to the Telegram notify bot.
Gated by tg_mirror_user toggle in config.json.
Always exits 0 (fail-open).

Input (stdin JSON):
  {"prompt": "user message text", "session_id": "..."}
"""

import json
import os
import sys
import urllib.request
import urllib.error

CLAUDE_DIR = os.path.join(os.path.expanduser("~"), ".claude")
CONFIG_FILE = os.path.join(CLAUDE_DIR, "config.json")
TG_CONFIG_FILE = os.path.join(CLAUDE_DIR, "integrations", "telegram-bot", "config.json")


def main():
    try:
        data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    # Check toggle
    try:
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
        if not cfg.get("tg_mirror_user", False):
            sys.exit(0)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        sys.exit(0)

    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        sys.exit(0)

    # Load Telegram config
    try:
        with open(TG_CONFIG_FILE) as f:
            tg_cfg = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        sys.exit(0)

    bot_token = tg_cfg.get("notify_bot_token", "") or tg_cfg.get("bot_token", "")
    allowed_users = tg_cfg.get("allowed_users", [])
    if not bot_token or not allowed_users:
        sys.exit(0)

    # Format and send
    escaped = (
        prompt.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    msg = f"<b>[User]</b>\n{escaped}"

    for uid in allowed_users:
        payload = json.dumps({
            "chat_id": uid,
            "text": msg,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }).encode()
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass

    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
