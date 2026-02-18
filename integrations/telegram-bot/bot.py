#!/usr/bin/env python3
"""Telegram Bot — Main bot service using python-telegram-bot v21.

Message flow:
  OZ sends message → bot receives (long polling)
    → log to FTS5 → look up session_id
      → claude -p --resume <session_id> → extract result
        → log response → send reply

Usage:
    python3 bot.py
"""

import logging
import os
import sys

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _PLUGIN_DIR)

from datetime import datetime, timezone

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from claude_runner import ClaudeError, run_claude
from tmux_runner import TmuxError, run_claude_tmux, is_tmux_session_alive
from config import load_config
from db import init_db, log_message, search_fts
from sessions import get_session_id, save_session

logger = logging.getLogger(__name__)

# Paths
DB_PATH = os.path.join(_PLUGIN_DIR, "msg_log.db")
SESSIONS_PATH = os.path.join(_PLUGIN_DIR, "sessions.json")
LIVE_STATE_PATH = os.path.join(os.path.expanduser("~"), ".claude", "LIVE_STATE.json")

# Loaded at startup
CFG = {}


def _is_tmux_mode():
    """Check if tg_bot_tmux toggle is enabled in LIVE_STATE.json."""
    try:
        with open(LIVE_STATE_PATH) as f:
            import json as _json
            state = _json.load(f)
            return state.get("tg_bot_tmux", False)
    except (FileNotFoundError, ValueError):
        return False


def _is_authorized(user_id, chat_id):
    """Check if user or chat is in allowed lists."""
    return user_id in CFG.get("allowed_users", []) or chat_id in CFG.get("allowed_groups", [])


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


async def handle_message(update: Update, context):
    """Handle incoming text messages."""
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat

    if not msg or not msg.text or not user or not chat:
        return

    if not _is_authorized(user.id, chat.id):
        await msg.reply_text("Unauthorized.")
        return

    text = msg.text.strip()
    if not text:
        return

    # In groups, only respond to @mentions or replies to the bot
    if chat.type in ("group", "supergroup"):
        bot_username = context.bot.username
        is_mention = f"@{bot_username}" in text
        is_reply = msg.reply_to_message and msg.reply_to_message.from_user.id == context.bot.id
        if not is_mention and not is_reply:
            return
        # Strip the @mention from the text
        if is_mention and bot_username:
            text = text.replace(f"@{bot_username}", "").strip()
        if not text:
            return

    # Log incoming message
    log_message(DB_PATH, chat.id, user.first_name or "user", text, _now_iso())

    # Send typing indicator
    await chat.send_action(ChatAction.TYPING)

    # Route: tmux mode or subprocess mode
    use_tmux = _is_tmux_mode()
    result = None
    new_session_id = None

    if use_tmux:
        tmux_target = CFG.get("tmux_target", "claude-bot")
        try:
            if await is_tmux_session_alive(tmux_target):
                result, _ = await run_claude_tmux(
                    text,
                    tmux_target=tmux_target,
                    timeout=CFG.get("claude_timeout", 120),
                )
                logger.info("tmux response: %d chars", len(result) if result else 0)
            else:
                logger.warning("tmux target '%s' not alive, falling back to claude -p", tmux_target)
                use_tmux = False
        except TmuxError as e:
            logger.warning("tmux error, falling back to claude -p: %s", e)
            use_tmux = False

    if not use_tmux or result is None:
        # Subprocess fallback
        session_id = get_session_id(SESSIONS_PATH, chat.id)
        try:
            result, new_session_id = await run_claude(
                text,
                session_id=session_id,
                cwd=CFG.get("claude_cwd"),
                timeout=CFG.get("claude_timeout", 120),
            )
        except ClaudeError as e:
            logger.error("Claude error: %s", e)
            await msg.reply_text(f"Error: {e}")
            return

    # Save session (only relevant for subprocess mode)
    if new_session_id:
        save_session(SESSIONS_PATH, chat.id, new_session_id)

    # Log response
    log_message(DB_PATH, chat.id, "Claude", result, _now_iso())

    # Send reply (split if > 4096 chars)
    if len(result) <= 4096:
        await msg.reply_text(result)
    else:
        for i in range(0, len(result), 4096):
            await msg.reply_text(result[i:i + 4096])


async def cmd_status(update: Update, context):
    """Handle /status command."""
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not msg or not user or not chat or not _is_authorized(user.id, chat.id):
        return

    from sessions import load_sessions
    sessions = load_sessions(SESSIONS_PATH)
    session_count = len(sessions)

    status_text = (
        "<b>Torus Bot Status</b>\n\n"
        f"Sessions: {session_count}\n"
        f"DB: {os.path.basename(DB_PATH)}\n"
        f"CWD: {CFG.get('claude_cwd', '?')}\n"
    )
    await msg.reply_text(status_text, parse_mode=ParseMode.HTML)


async def cmd_search(update: Update, context):
    """Handle /search <query> command."""
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not msg or not user or not chat or not _is_authorized(user.id, chat.id):
        return

    query = " ".join(context.args) if context.args else ""
    if not query:
        await msg.reply_text("Usage: /search <query>")
        return

    results = search_fts(DB_PATH, query, limit=5)
    if not results:
        await msg.reply_text(f"No results for: {query}")
        return

    lines = [f"<b>Search: {query}</b>\n"]
    for i, r in enumerate(results, 1):
        text_preview = r["text"][:150]
        if len(r["text"]) > 150:
            text_preview += "..."
        lines.append(f"{i}. [{r['date'][:10]}] {text_preview}")
    await msg.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_memory(update: Update, context):
    """Handle /memory <query> — search ChromaDB via memory_server."""
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not msg or not user or not chat or not _is_authorized(user.id, chat.id):
        return

    query = " ".join(context.args) if context.args else ""
    if not query:
        await msg.reply_text("Usage: /memory <query>")
        return

    # Forward to Claude with explicit memory search instruction
    await chat.send_action(ChatAction.TYPING)
    session_id = get_session_id(SESSIONS_PATH, chat.id)
    try:
        result, new_session_id = await run_claude(
            f"Search memory for: {query}",
            session_id=session_id,
            cwd=CFG.get("claude_cwd"),
            timeout=CFG.get("claude_timeout", 120),
        )
        if new_session_id:
            save_session(SESSIONS_PATH, chat.id, new_session_id)
        await msg.reply_text(result[:4096])
    except ClaudeError as e:
        await msg.reply_text(f"Error: {e}")


async def cmd_reset(update: Update, context):
    """Handle /reset — clear session for this chat."""
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not msg or not user or not chat or not _is_authorized(user.id, chat.id):
        return

    save_session(SESSIONS_PATH, chat.id, "")
    await msg.reply_text("Session reset. Next message starts a fresh conversation.")


def main():
    global CFG

    logging.basicConfig(
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        level=logging.INFO,
    )

    CFG = load_config()
    init_db(DB_PATH)

    logger.info("Starting Torus Bot...")

    app = Application.builder().token(CFG["bot_token"]).build()

    # Commands
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("memory", cmd_memory))
    app.add_handler(CommandHandler("reset", cmd_reset))

    # Messages — private chat: all text; groups: only @mentions or replies
    private_filter = filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND
    group_filter = filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND
    app.add_handler(MessageHandler(private_filter | group_filter, handle_message))

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
