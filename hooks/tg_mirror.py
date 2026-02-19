#!/usr/bin/env python3
"""Telegram Mirror — Stop Hook

Fires after every Claude response. Reads the last assistant turn from
the transcript and sends it to Telegram via Bot API.

Gated by tg_mirror_messages toggle in LIVE_STATE.json.
Always exits 0 (fail-open, never blocks Claude).

Input (stdin JSON):
  {"session_id": "...", "transcript_path": "...", "cwd": "...", "hook_event_name": "Stop"}
"""

import json
import os
import sys
import urllib.request
import urllib.error

CLAUDE_DIR = os.path.join(os.path.expanduser("~"), ".claude")
LIVE_STATE_FILE = os.path.join(CLAUDE_DIR, "LIVE_STATE.json")
TG_CONFIG_FILE = os.path.join(CLAUDE_DIR, "integrations", "telegram-bot", "config.json")

# Track last sent position to avoid re-sending on each Stop
_CURSOR_FILE = os.path.join(CLAUDE_DIR, "hooks", ".tg_mirror_cursor.json")


def _load_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default or {}


def _save_cursor(session_id, line_num):
    """Save the last-sent line number for this session."""
    try:
        cursor = _load_json(_CURSOR_FILE, {})
        cursor[session_id] = line_num
        # Keep only last 5 sessions
        if len(cursor) > 5:
            keys = sorted(cursor.keys())
            for k in keys[:-5]:
                del cursor[k]
        tmp = _CURSOR_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(cursor, f)
        os.replace(tmp, _CURSOR_FILE)
    except OSError:
        pass


def _extract_new_assistant_turns(transcript_path, session_id):
    """Read new assistant turns since last cursor position."""
    cursor = _load_json(_CURSOR_FILE, {})
    last_line = cursor.get(session_id, 0)

    turns = []
    current_line = 0
    try:
        with open(transcript_path) as f:
            for raw_line in f:
                current_line += 1
                if current_line <= last_line:
                    continue
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    entry = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                entry_type = entry.get("type", "")
                if entry_type != "assistant":
                    continue
                msg = entry.get("message", {})
                content = msg.get("content", "")
                if isinstance(content, list):
                    text_parts = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                    content = "\n".join(text_parts)
                content = content.strip()
                if content:
                    turns.append(content)
    except (FileNotFoundError, OSError):
        return [], last_line

    return turns, current_line


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

        # Check toggle
        live = _load_json(LIVE_STATE_FILE, {})
        if not live.get("tg_mirror_messages", False):
            sys.exit(0)

        # Get transcript path
        transcript_path = data.get("transcript_path", "")
        session_id = data.get("session_id", "unknown")
        if not transcript_path or not os.path.isfile(transcript_path):
            sys.exit(0)

        # Load Telegram config
        tg_cfg = _load_json(TG_CONFIG_FILE, {})
        bot_token = tg_cfg.get("bot_token", "")
        allowed_users = tg_cfg.get("allowed_users", [])
        if not bot_token or not allowed_users:
            print("[TG_MIRROR] No bot_token or allowed_users configured", file=sys.stderr)
            sys.exit(0)

        # Extract new assistant turns
        turns, new_cursor = _extract_new_assistant_turns(transcript_path, session_id)
        if not turns:
            _save_cursor(session_id, new_cursor)
            sys.exit(0)

        # Format and send
        for turn in turns:
            # Escape HTML and send
            escaped = _escape_html(turn)
            # Prefix with session indicator
            msg = f"<b>[Claude]</b>\n{escaped}"
            for uid in allowed_users:
                _send_telegram(bot_token, uid, msg)

        _save_cursor(session_id, new_cursor)
        print(f"[TG_MIRROR] Sent {len(turns)} turn(s)", file=sys.stderr)

    except Exception as e:
        print(f"[TG_MIRROR] Error (non-fatal): {e}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
