#!/usr/bin/env python3
"""Telegram Bot — Session End Hook

Posts HANDOFF.md content to FTS5 log and optionally notifies user via Bot API.
Called by session_end.py via subprocess. Always exits 0.
"""

import json
import os
import re
import sys
import urllib.request
import urllib.error

_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PLUGIN_DIR)

CLAUDE_DIR = os.path.join(os.path.expanduser("~"), ".claude")
HANDOFF_FILE = os.path.join(CLAUDE_DIR, "HANDOFF.md")
LIVE_STATE_FILE = os.path.join(CLAUDE_DIR, "LIVE_STATE.json")
DB_PATH = os.path.join(_PLUGIN_DIR, "msg_log.db")
CONFIG_PATH = os.path.join(_PLUGIN_DIR, "config.json")


def _format_html(markdown_text: str, session_num: str = "?") -> str:
    """Convert HANDOFF.md markdown to Telegram-compatible HTML.

    Telegram supports: <b>, <i>, <code>, <pre>, <a>, <s>, <u>
    """
    lines = markdown_text.split("\n")
    html_lines = []

    for line in lines:
        # # H1 headers -> bold with separator
        if line.startswith("# ") and not line.startswith("##"):
            html_lines.append(f"<b>{_escape_html(line[2:].strip())}</b>")
            continue

        # ## H2 headers -> bold
        if line.startswith("## "):
            html_lines.append(f"\n<b>{_escape_html(line[3:].strip())}</b>")
            continue

        # **bold** patterns within lines
        converted = re.sub(
            r"\*\*(.+?)\*\*",
            r"<b>\1</b>",
            line,
        )

        # `code` patterns
        converted = re.sub(
            r"`(.+?)`",
            r"<code>\1</code>",
            converted,
        )

        html_lines.append(converted)

    html = "\n".join(html_lines).strip()

    # Add hashtags
    hashtags = f"\n\n#torus #session #session{session_num}"

    # Telegram limit: 4096 chars
    max_body = 4096 - len(hashtags)
    if len(html) > max_body:
        html = html[:max_body - 3] + "..."

    html += hashtags
    return html


def _escape_html(text: str) -> str:
    """Escape HTML special chars."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _send_bot_message(bot_token, chat_id, text):
    """Send a message via Bot API HTTP call. Returns True on success."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text[:4096],
        "parse_mode": "HTML",
    }).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
        return True
    except (urllib.error.URLError, urllib.error.HTTPError):
        return False


def main():
    try:
        # Read HANDOFF.md
        if not os.path.isfile(HANDOFF_FILE):
            print("[TG_BOT_SESSION_END] No HANDOFF.md found, skipping", file=sys.stderr)
            sys.exit(0)

        with open(HANDOFF_FILE) as f:
            handoff_content = f.read()

        if not handoff_content.strip():
            print("[TG_BOT_SESSION_END] Empty HANDOFF.md, skipping", file=sys.stderr)
            sys.exit(0)

        # Get session number
        session_num = "?"
        try:
            with open(LIVE_STATE_FILE) as f:
                live = json.load(f)
            session_num = str(live.get("session_count", "?"))
        except Exception:
            pass

        # Log to FTS5 database
        from db import init_db, log_message
        init_db(DB_PATH)
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        log_message(DB_PATH, 0, "system", handoff_content[:4000], now)
        print(f"[TG_BOT_SESSION_END] Logged session {session_num} to FTS5", file=sys.stderr)

        # Notify user via Bot API
        try:
            with open(CONFIG_PATH) as f:
                cfg = json.load(f)
            bot_token = cfg.get("bot_token", "")
            allowed_users = cfg.get("allowed_users", [])
            if bot_token and allowed_users:
                notify = f"Session {session_num} ended.\n{handoff_content[:500]}"
                if len(handoff_content) > 500:
                    notify += "\n..."
                for uid in allowed_users:
                    _send_bot_message(bot_token, uid, notify)
                print(f"[TG_BOT_SESSION_END] Notified user via Bot API", file=sys.stderr)
        except Exception as e:
            print(f"[TG_BOT_SESSION_END] User notification failed (non-fatal): {e}", file=sys.stderr)

    except Exception as e:
        print(f"[TG_BOT_SESSION_END] Error (non-fatal): {e}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
