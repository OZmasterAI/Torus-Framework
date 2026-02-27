#!/usr/bin/env python3
"""Telegram Mirror — Stop Hook

Fires after every Claude response. Reads last_assistant_message from
the Stop hook stdin JSON and sends it to Telegram via Bot API.

Gated by tg_mirror_messages toggle in LIVE_STATE.json.
Always exits 0 (fail-open, never blocks Claude).

Input (stdin JSON):
  {"session_id": "...", "last_assistant_message": "...", "hook_event_name": "Stop"}
"""

import json
import os
import sys
import urllib.request
import urllib.error

CLAUDE_DIR = os.path.join(os.path.expanduser("~"), ".claude")
CONFIG_FILE = os.path.join(CLAUDE_DIR, "config.json")
LIVE_STATE_FILE = os.path.join(CLAUDE_DIR, "LIVE_STATE.json")
TG_CONFIG_FILE = os.path.join(CLAUDE_DIR, "integrations", "telegram-bot", "config.json")


def _load_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default or {}


def _send_telegram(bot_token, chat_id, text):
    """Send message via Telegram Bot API. Handles message splitting for >4096 chars."""
    # Telegram max message length
    MAX_LEN = 4096
    chunks = []
    while text:
        if len(text) <= MAX_LEN:
            chunks.append(text)
            break
        # Find a good split point
        split_at = text.rfind("\n", 0, MAX_LEN)
        if split_at < MAX_LEN // 2:
            split_at = MAX_LEN
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    for chunk in chunks:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = json.dumps({
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }).encode()
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=10)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError):
            # Fall back to plain text if HTML parsing fails
            payload = json.dumps({
                "chat_id": chat_id,
                "text": chunk,
                "disable_web_page_preview": True,
            }).encode()
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            try:
                urllib.request.urlopen(req, timeout=10)
            except Exception:
                pass


def _escape_html(text):
    """Escape HTML special chars for Telegram."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def main():
    try:
        # Read stdin
        try:
            data = json.loads(sys.stdin.read())
        except (json.JSONDecodeError, ValueError):
            data = {}

        # Check toggle (config.json first, LIVE_STATE.json fallback)
        cfg = _load_json(CONFIG_FILE, {})
        if "tg_mirror_messages" not in cfg:
            cfg = _load_json(LIVE_STATE_FILE, {})
        if not cfg.get("tg_mirror_messages", False):
            sys.exit(0)

        # Get last assistant message (added in Claude Code 2.1.47)
        message = (data.get("last_assistant_message") or "").strip()
        if not message:
            sys.exit(0)

        # Load Telegram config
        tg_cfg = _load_json(TG_CONFIG_FILE, {})
        bot_token = tg_cfg.get("bot_token", "")
        allowed_users = tg_cfg.get("allowed_users", [])
        if not bot_token or not allowed_users:
            print("[TG_MIRROR] No bot_token or allowed_users configured", file=sys.stderr)
            sys.exit(0)

        # Format and send
        escaped = _escape_html(message)
        msg = f"<b>[Claude]</b>\n{escaped}"
        for uid in allowed_users:
            _send_telegram(bot_token, uid, msg)

        print("[TG_MIRROR] Sent 1 turn", file=sys.stderr)

    except Exception as e:
        print(f"[TG_MIRROR] Error (non-fatal): {e}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
