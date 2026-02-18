#!/usr/bin/env python3
"""Telegram Memory Plugin — Session End Hook

Posts HANDOFF.md content to Telegram Saved Messages as HTML.
Called by session_end.py via subprocess. Always exits 0.
"""

import os
import re
import sys

_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PLUGIN_DIR)

CLAUDE_DIR = os.path.join(os.path.expanduser("~"), ".claude")
HANDOFF_FILE = os.path.join(CLAUDE_DIR, "HANDOFF.md")
LIVE_STATE_FILE = os.path.join(CLAUDE_DIR, "LIVE_STATE.json")


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

        # Escape remaining HTML in non-tagged text
        # (We need to be careful not to double-escape the tags we just added)
        # Simple approach: escape first, then convert markdown
        # Actually, let's just pass through since we're building HTML

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


def main():
    try:
        # Read HANDOFF.md
        if not os.path.isfile(HANDOFF_FILE):
            print("[TG_SESSION_END] No HANDOFF.md found, skipping", file=sys.stderr)
            sys.exit(0)

        with open(HANDOFF_FILE) as f:
            handoff_content = f.read()

        if not handoff_content.strip():
            print("[TG_SESSION_END] Empty HANDOFF.md, skipping", file=sys.stderr)
            sys.exit(0)

        # Get session number
        session_num = "?"
        try:
            import json
            with open(LIVE_STATE_FILE) as f:
                live = json.load(f)
            session_num = str(live.get("session_count", "?"))
        except Exception:
            pass

        # Convert to HTML
        html = _format_html(handoff_content, session_num)

        # Post to Saved Messages (L2 memory archive)
        from telegram_memory import post_session, send_to_oz, TelegramError
        try:
            msg_id = post_session(html)
            print(f"[TG_SESSION_END] Posted session {session_num} to Saved Messages (msg {msg_id})", file=sys.stderr)
        except TelegramError as e:
            print(f"[TG_SESSION_END] Saved Messages post failed (non-fatal): {e}", file=sys.stderr)

        # Send notification to OZ
        try:
            notify = f"Session {session_num} ended.\n{handoff_content[:500]}"
            if len(handoff_content) > 500:
                notify += "\n..."
            send_to_oz(notify)
            print(f"[TG_SESSION_END] Notified OZ on Telegram", file=sys.stderr)
        except TelegramError as e:
            print(f"[TG_SESSION_END] OZ notification failed (non-fatal): {e}", file=sys.stderr)

    except Exception as e:
        print(f"[TG_SESSION_END] Error (non-fatal): {e}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
