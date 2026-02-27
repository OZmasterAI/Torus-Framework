#!/usr/bin/env python3
"""Telegram Bot — Main bot service using python-telegram-bot v21.

Message flow:
  user sends message → bot receives (long polling)
    → log to FTS5 → look up session_id
      → claude -p --resume <session_id> → extract result
        → log response → send reply

  Voice messages:
    user sends voice → bot downloads .ogg → faster-whisper transcribes
      → same pipeline as text messages

Usage:
    python3 bot.py
"""

import logging
import os
import sys
import tempfile

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


# ── Voice-to-text (faster-whisper) ─────────────────────────────────────────
_whisper_model = None
_WHISPER_MODEL_SIZE = os.environ.get("WHISPER_MODEL", "small")
_GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
_whisper_backend = "local"  # "local" or "groq"


def _get_whisper_model():
    """Lazy-load the faster-whisper model (stays in memory after first call)."""
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        logger.info("Loading whisper model '%s' (first voice message)...", _WHISPER_MODEL_SIZE)
        _whisper_model = WhisperModel(_WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
        logger.info("Whisper model loaded.")
    return _whisper_model


def _transcribe_local(ogg_path: str) -> str:
    """Transcribe an .ogg voice file using faster-whisper with optimized params."""
    model = _get_whisper_model()
    segments, info = model.transcribe(
        ogg_path,
        beam_size=1,
        temperature=0,
        vad_filter=True,
        without_timestamps=True,
    )
    text = " ".join(seg.text for seg in segments).strip()
    logger.info("Transcribed %.1fs audio (%s) → %d chars [local]", info.duration, info.language, len(text))
    return text


def _transcribe_groq(ogg_path: str) -> str:
    """Transcribe an .ogg voice file using Groq's Whisper API."""
    from groq import Groq
    client = Groq(api_key=_GROQ_API_KEY)
    with open(ogg_path, "rb") as f:
        transcription = client.audio.transcriptions.create(
            file=(os.path.basename(ogg_path), f),
            model="whisper-large-v3-turbo",
            response_format="text",
        )
    text = transcription.strip() if isinstance(transcription, str) else str(transcription).strip()
    logger.info("Transcribed audio → %d chars [groq]", len(text))
    return text


def _transcribe_ogg(ogg_path: str) -> str:
    """Route transcription to the active backend with auto-fallback."""
    if _whisper_backend == "groq" and _GROQ_API_KEY:
        try:
            return _transcribe_groq(ogg_path)
        except Exception as e:
            logger.warning("Groq transcription failed (%s), falling back to local", e)
    return _transcribe_local(ogg_path)


async def handle_voice(update: Update, context):
    """Handle incoming voice messages — transcribe and process as text."""
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat

    if not msg or not user or not chat:
        return

    if not _is_authorized(user.id, chat.id):
        await msg.reply_text("Unauthorized.")
        return

    # Download voice file
    voice = msg.voice or msg.audio
    if not voice:
        return

    await chat.send_action(ChatAction.TYPING)

    try:
        tg_file = await voice.get_file()
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp_path = tmp.name
        await tg_file.download_to_drive(tmp_path)
    except Exception as e:
        logger.error("Voice download failed: %s", e)
        await msg.reply_text(f"Failed to download voice: {e}")
        return

    # Transcribe
    try:
        text = _transcribe_ogg(tmp_path)
    except Exception as e:
        logger.error("Transcription failed: %s", e)
        await msg.reply_text(f"Transcription error: {e}")
        return
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    if not text:
        await msg.reply_text("(empty transcription)")
        return

    # Log transcription
    log_message(DB_PATH, chat.id, user.first_name or "user", f"[voice] {text}", _now_iso())

    # Inject into the active Claude Code tmux pane (voice_tmux_target in config)
    # Falls back to normal Claude pipeline if no target configured
    voice_target = CFG.get("voice_tmux_target", "")
    if voice_target:
        import subprocess as _sp
        try:
            # Check pane is alive
            _check = _sp.run(
                ["tmux", "has-session", "-t", voice_target.split(":")[0]],
                capture_output=True, timeout=5,
            )
            if _check.returncode == 0:
                # Send transcribed text into the pane (literal mode for special chars)
                _sp.run(
                    ["tmux", "send-keys", "-t", voice_target, "-l", text],
                    capture_output=True, timeout=5,
                )
                await msg.reply_text(f"🎤 Injected: _{text}_", parse_mode=ParseMode.MARKDOWN)
                logger.info("Voice injected into tmux %s: %d chars", voice_target, len(text))
                return
            else:
                logger.warning("voice_tmux_target '%s' not alive, falling back", voice_target)
        except Exception as e:
            logger.warning("tmux send-keys failed: %s, falling back", e)

    # Fallback: process through normal Claude pipeline
    await msg.reply_text(f"🎤 _{text}_", parse_mode=ParseMode.MARKDOWN)
    await chat.send_action(ChatAction.TYPING)

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
            else:
                use_tmux = False
        except TmuxError:
            use_tmux = False

    if not use_tmux or result is None:
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

    if new_session_id:
        save_session(SESSIONS_PATH, chat.id, new_session_id)

    log_message(DB_PATH, chat.id, "Claude", result, _now_iso())

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


async def cmd_whisper(update: Update, context):
    """Handle /whisper — show or switch transcription backend."""
    global _whisper_backend
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not msg or not user or not chat or not _is_authorized(user.id, chat.id):
        return

    arg = context.args[0].lower() if context.args else ""
    if not arg:
        groq_status = "available" if _GROQ_API_KEY else "no API key"
        await msg.reply_text(f"Whisper backend: <b>{_whisper_backend}</b>\nGroq: {groq_status}", parse_mode=ParseMode.HTML)
        return

    if arg == "groq":
        if not _GROQ_API_KEY:
            await msg.reply_text("GROQ_API_KEY not set. Start bot with the env var to use Groq.")
            return
        _whisper_backend = "groq"
        await msg.reply_text("Switched to <b>groq</b> backend.", parse_mode=ParseMode.HTML)
    elif arg == "local":
        _whisper_backend = "local"
        await msg.reply_text("Switched to <b>local</b> (faster-whisper) backend.", parse_mode=ParseMode.HTML)
    else:
        await msg.reply_text("Usage: /whisper [groq|local]")


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
    app.add_handler(CommandHandler("whisper", cmd_whisper))

    # Messages — private chat: all text; groups: only @mentions or replies
    private_filter = filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND
    group_filter = filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND
    app.add_handler(MessageHandler(private_filter | group_filter, handle_message))

    # Voice messages — transcribe via faster-whisper, then process as text
    voice_filter = filters.ChatType.PRIVATE & (filters.VOICE | filters.AUDIO)
    group_voice_filter = filters.ChatType.GROUPS & (filters.VOICE | filters.AUDIO)
    app.add_handler(MessageHandler(voice_filter | group_voice_filter, handle_voice))

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
