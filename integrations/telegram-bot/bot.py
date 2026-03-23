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

from telegram import BotCommand, Update
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
    """Check if tg_bot_tmux toggle is enabled in config.json or LIVE_STATE.json."""
    import json as _json

    # config.json is canonical for toggles
    try:
        _cfg_path = os.path.join(os.path.expanduser("~"), ".claude", "config.json")
        with open(_cfg_path) as f:
            cfg = _json.load(f)
            if cfg.get("tg_bot_tmux", False):
                return True
    except (FileNotFoundError, ValueError):
        pass
    # Fallback: LIVE_STATE.json
    try:
        with open(LIVE_STATE_PATH) as f:
            state = _json.load(f)
            return state.get("tg_bot_tmux", False)
    except (FileNotFoundError, ValueError):
        return False


def _is_authorized(user_id, chat_id):
    """Check if user or chat is in allowed lists."""
    return user_id in CFG.get("allowed_users", []) or chat_id in CFG.get(
        "allowed_groups", []
    )


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


async def _mirror_user_message(user_name: str, text: str):
    """Mirror user message to notify bot if tg_mirror_user is enabled."""
    import json as _json
    import urllib.request
    import urllib.error

    cfg_path = os.path.join(os.path.expanduser("~"), ".claude", "config.json")
    try:
        with open(cfg_path) as f:
            cfg = _json.load(f)
    except (FileNotFoundError, ValueError):
        return
    if not cfg.get("tg_mirror_user", False):
        return
    notify_token = CFG.get("notify_bot_token", "")
    if not notify_token:
        return
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html = f"<b>[{user_name}]</b>\n{escaped}"
    for uid in CFG.get("allowed_users", []):
        payload = _json.dumps(
            {"chat_id": uid, "text": html, "parse_mode": "HTML"}
        ).encode()
        url = f"https://api.telegram.org/bot{notify_token}/sendMessage"
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}
        )
        try:
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass


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
        is_reply = (
            msg.reply_to_message and msg.reply_to_message.from_user.id == context.bot.id
        )
        if not is_mention and not is_reply:
            return
        # Strip the @mention from the text
        if is_mention and bot_username:
            text = text.replace(f"@{bot_username}", "").strip()
        if not text:
            return

    # Log incoming message and mirror if enabled
    log_message(DB_PATH, chat.id, user.first_name or "user", text, _now_iso())
    await _mirror_user_message(user.first_name or "user", text)

    # Send typing indicator
    await chat.send_action(ChatAction.TYPING)

    # Route: tmux mode (exclusive) or subprocess mode
    use_tmux = _is_tmux_mode()
    result = None
    new_session_id = None

    if use_tmux:
        tmux_target = CFG.get("tmux_target", "claude-bot")
        if await is_tmux_session_alive(tmux_target):
            try:
                result, _ = await run_claude_tmux(
                    text,
                    tmux_target=tmux_target,
                    timeout=CFG.get("claude_timeout", 120),
                )
                logger.info("tmux response: %d chars", len(result) if result else 0)
            except TmuxError as e:
                logger.error("tmux error (no fallback): %s", e)
                await msg.reply_text(f"tmux error: {e}")
                return
        else:
            logger.warning("tmux target '%s' not alive", tmux_target)
            await msg.reply_text(
                f"tmux session '{tmux_target}' not running. Start it or disable tg_bot_tmux."
            )
            return
    else:
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

    # TTS voice reply for text messages (when enabled)
    if _tts_text_replies and result:
        audio_data = await _tts_synthesize(result)
        if audio_data:
            await msg.reply_voice(voice=audio_data)

    # Send reply (split if > 4096 chars)
    if len(result) <= 4096:
        await msg.reply_text(result)
    else:
        for i in range(0, len(result), 4096):
            await msg.reply_text(result[i : i + 4096])


# ── Voice-to-text (faster-whisper) ─────────────────────────────────────────
_whisper_model = None
_WHISPER_MODEL_SIZE = os.environ.get("WHISPER_MODEL", "small")
_GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
_whisper_backend = "groq" if _GROQ_API_KEY else "local"


def _get_whisper_model():
    """Lazy-load the faster-whisper model (stays in memory after first call)."""
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel

        logger.info(
            "Loading whisper model '%s' (first voice message)...", _WHISPER_MODEL_SIZE
        )
        _whisper_model = WhisperModel(
            _WHISPER_MODEL_SIZE, device="cpu", compute_type="int8"
        )
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
    logger.info(
        "Transcribed %.1fs audio (%s) → %d chars [local]",
        info.duration,
        info.language,
        len(text),
    )
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
    text = (
        transcription.strip()
        if isinstance(transcription, str)
        else str(transcription).strip()
    )
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


# ── Text-to-speech (multi-engine: Edge-TTS, Piper, Groq) ──────────────────
PIPER_VOICES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(_PLUGIN_DIR)),
    "integrations",
    "tts-voices",
    "piper-voices",
)
_piper_cache = {}  # voice_name -> loaded PiperVoice

_TTS_ENGINE_DEFAULTS = {
    "edge": "en-US-GuyNeural",
    "piper": "en_US-lessac-high",
    "groq": "austin",
}

# TTS state (loaded from config.json on startup)
_tts_engine = "edge"
_tts_voice = "en-US-GuyNeural"
_tts_text_replies = False

_CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".claude", "config.json")


def _load_tts_config():
    """Load TTS settings from config.json."""
    global _tts_engine, _tts_voice, _tts_text_replies
    import json as _json

    try:
        with open(_CONFIG_PATH) as f:
            cfg = _json.load(f)
        _tts_engine = cfg.get("tts_engine", "edge")
        _tts_voice = cfg.get(
            "tts_voice", _TTS_ENGINE_DEFAULTS.get(_tts_engine, "en-US-GuyNeural")
        )
        _tts_text_replies = cfg.get("tts_text_replies", False)
    except (FileNotFoundError, ValueError):
        pass


def _save_tts_config():
    """Persist TTS settings to config.json."""
    import json as _json

    try:
        with open(_CONFIG_PATH) as f:
            cfg = _json.load(f)
    except (FileNotFoundError, ValueError):
        cfg = {}
    cfg["tts_engine"] = _tts_engine
    cfg["tts_voice"] = _tts_voice
    cfg["tts_text_replies"] = _tts_text_replies
    with open(_CONFIG_PATH, "w") as f:
        _json.dump(cfg, f, indent=2)


_load_tts_config()


async def _audio_to_ogg(input_path: str, ogg_path: str) -> bool:
    """Convert audio file to OGG/Opus via ffmpeg. Returns True on success."""
    import asyncio

    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        "-c:a",
        "libopus",
        "-b:a",
        "48k",
        ogg_path,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await asyncio.wait_for(proc.wait(), timeout=10)
    if proc.returncode != 0:
        logger.error("ffmpeg conversion failed (rc=%d)", proc.returncode)
        return False
    return True


async def _tts_edge(text: str, voice: str = "en-US-GuyNeural") -> bytes | None:
    """Synthesize text to OGG/Opus audio using Edge-TTS (Microsoft)."""
    import hashlib
    import edge_tts

    tts_text = text[:10000] if len(text) > 10000 else text
    h = hashlib.md5(tts_text.encode()).hexdigest()[:8]
    mp3_path = os.path.join(tempfile.gettempdir(), f"tts-edge-{h}.mp3")
    ogg_path = mp3_path.replace(".mp3", ".ogg")

    try:
        communicate = edge_tts.Communicate(tts_text, voice)
        await communicate.save(mp3_path)

        if not await _audio_to_ogg(mp3_path, ogg_path):
            return None

        with open(ogg_path, "rb") as f:
            audio_data = f.read()

        logger.info(
            "TTS generated: %d chars → %d bytes OGG [edge-tts %s]",
            len(tts_text),
            len(audio_data),
            voice,
        )
        return audio_data

    except Exception as e:
        logger.error("Edge TTS failed: %s", e)
        return None
    finally:
        for p in [mp3_path, ogg_path]:
            try:
                os.unlink(p)
            except OSError:
                pass


async def _tts_piper(text: str, voice: str = "en_US-lessac-high") -> bytes | None:
    """Synthesize text to OGG/Opus audio using Piper (local ONNX)."""
    import asyncio
    import hashlib
    import wave

    onnx_path = os.path.join(PIPER_VOICES_DIR, f"{voice}.onnx")
    config_path = onnx_path + ".json"
    if not os.path.exists(onnx_path) or not os.path.exists(config_path):
        logger.error("Piper voice '%s' not found at %s", voice, onnx_path)
        return None

    # Lazy-load voice model
    if voice not in _piper_cache:
        from piper import PiperVoice

        _piper_cache[voice] = PiperVoice.load(onnx_path, config_path=config_path)
        logger.info("Loaded Piper voice: %s", voice)
    pv = _piper_cache[voice]

    h = hashlib.md5(text.encode()).hexdigest()[:8]
    wav_path = os.path.join(tempfile.gettempdir(), f"tts-piper-{h}.wav")
    ogg_path = wav_path.replace(".wav", ".ogg")

    try:
        loop = asyncio.get_event_loop()

        def _synthesize():
            with wave.open(wav_path, "wb") as wav_file:
                pv.synthesize_wav(text, wav_file)

        await loop.run_in_executor(None, _synthesize)

        if not await _audio_to_ogg(wav_path, ogg_path):
            return None

        with open(ogg_path, "rb") as f:
            audio_data = f.read()

        logger.info(
            "TTS generated: %d chars → %d bytes OGG [piper %s]",
            len(text),
            len(audio_data),
            voice,
        )
        return audio_data

    except Exception as e:
        logger.error("Piper TTS failed: %s", e)
        return None
    finally:
        for p in [wav_path, ogg_path]:
            try:
                os.unlink(p)
            except OSError:
                pass


async def _tts_groq(text: str, voice: str = "austin") -> bytes | None:
    """Synthesize text to OGG/Opus audio using Groq Orpheus TTS."""
    import hashlib

    if not _GROQ_API_KEY:
        return None

    tts_text = text[:800] if len(text) > 800 else text

    h = hashlib.md5(tts_text.encode()).hexdigest()[:8]
    wav_path = os.path.join(tempfile.gettempdir(), f"tts-groq-{h}.wav")
    ogg_path = wav_path.replace(".wav", ".ogg")

    try:
        from groq import Groq

        client = Groq(api_key=_GROQ_API_KEY)

        response = client.audio.speech.create(
            model="canopylabs/orpheus-v1-english",
            input=tts_text,
            voice=voice,
            response_format="wav",
        )
        response.write_to_file(wav_path)

        if not await _audio_to_ogg(wav_path, ogg_path):
            return None

        with open(ogg_path, "rb") as f:
            audio_data = f.read()

        logger.info(
            "TTS generated: %d chars → %d bytes OGG [groq orpheus]",
            len(tts_text),
            len(audio_data),
        )
        return audio_data

    except Exception as e:
        logger.error("Groq TTS failed: %s", e)
        return None
    finally:
        for p in [wav_path, ogg_path]:
            try:
                os.unlink(p)
            except OSError:
                pass


async def _tts_synthesize(text: str) -> bytes | None:
    """Route TTS to the active engine."""
    if _tts_engine == "edge":
        return await _tts_edge(text, _tts_voice)
    elif _tts_engine == "piper":
        return await _tts_piper(text, _tts_voice)
    elif _tts_engine == "groq":
        return await _tts_groq(text, _tts_voice)
    else:
        logger.error("Unknown TTS engine: %s", _tts_engine)
        return None


async def handle_voice(update: Update, context):
    """Handle incoming voice messages — transcribe and process as text."""
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat

    if not msg or not user or not chat:
        return

    # Ignore bot's own voice replies (prevents feedback loop)
    if user.is_bot:
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
    log_message(
        DB_PATH, chat.id, user.first_name or "user", f"[voice] {text}", _now_iso()
    )

    # Send transcription preview, then route through normal Claude pipeline
    # (tmux mode sends to claude-bot pane and returns reply on Telegram)
    await msg.reply_text(f"🎤 _{text}_", parse_mode=ParseMode.MARKDOWN)
    await _mirror_user_message(user.first_name or "user", f"🎤 {text}")
    await chat.send_action(ChatAction.TYPING)

    use_tmux = _is_tmux_mode()
    result = None
    new_session_id = None

    if use_tmux:
        tmux_target = CFG.get("tmux_target", "claude-bot")
        if await is_tmux_session_alive(tmux_target):
            try:
                result, _ = await run_claude_tmux(
                    text,
                    tmux_target=tmux_target,
                    timeout=CFG.get("claude_timeout", 120),
                )
            except TmuxError as e:
                logger.error("tmux voice error (no fallback): %s", e)
                await msg.reply_text(f"tmux error: {e}")
                return
        else:
            await msg.reply_text(f"tmux session '{tmux_target}' not running.")
            return
    else:
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

    # Reply with voice + text for voice messages
    if result:
        audio_data = await _tts_synthesize(result)
        if audio_data:
            await msg.reply_voice(voice=audio_data)

    if len(result) <= 4096:
        await msg.reply_text(result)
    else:
        for i in range(0, len(result), 4096):
            await msg.reply_text(result[i : i + 4096])


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
        await msg.reply_text(
            f"Whisper backend: <b>{_whisper_backend}</b>\nGroq: {groq_status}",
            parse_mode=ParseMode.HTML,
        )
        return

    if arg == "groq":
        if not _GROQ_API_KEY:
            await msg.reply_text(
                "GROQ_API_KEY not set. Start bot with the env var to use Groq."
            )
            return
        _whisper_backend = "groq"
        await msg.reply_text(
            "Switched to <b>groq</b> backend.", parse_mode=ParseMode.HTML
        )
    elif arg == "local":
        _whisper_backend = "local"
        await msg.reply_text(
            "Switched to <b>local</b> (faster-whisper) backend.",
            parse_mode=ParseMode.HTML,
        )
    else:
        await msg.reply_text("Usage: /whisper [groq|local]")


async def cmd_mirror(update: Update, context):
    """Handle /mirror — toggle mirror settings."""
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not msg or not user or not chat or not _is_authorized(user.id, chat.id):
        return

    import json as _json

    cfg_path = os.path.join(os.path.expanduser("~"), ".claude", "config.json")
    try:
        with open(cfg_path) as f:
            cfg = _json.load(f)
    except (FileNotFoundError, ValueError):
        cfg = {}

    arg = context.args[0].lower() if context.args else ""
    if not arg:
        mirror_on = cfg.get("tg_mirror_messages", False)
        user_on = cfg.get("tg_mirror_user", False)
        await msg.reply_text(
            f"<b>Mirror settings</b>\n\n"
            f"Mirror: <b>{'on' if mirror_on else 'off'}</b>\n"
            f"User messages: <b>{'on' if user_on else 'off'}</b>\n\n"
            f"Usage: /mirror [on|off|user]",
            parse_mode=ParseMode.HTML,
        )
        return

    if arg == "on":
        cfg["tg_mirror_messages"] = True
        with open(cfg_path, "w") as f:
            _json.dump(cfg, f, indent=2)
        await msg.reply_text("Mirror <b>enabled</b>.", parse_mode=ParseMode.HTML)
    elif arg == "off":
        cfg["tg_mirror_messages"] = False
        with open(cfg_path, "w") as f:
            _json.dump(cfg, f, indent=2)
        await msg.reply_text("Mirror <b>disabled</b>.", parse_mode=ParseMode.HTML)
    elif arg == "user":
        current = cfg.get("tg_mirror_user", False)
        cfg["tg_mirror_user"] = not current
        with open(cfg_path, "w") as f:
            _json.dump(cfg, f, indent=2)
        state = "on" if not current else "off"
        await msg.reply_text(
            f"User message mirroring <b>{state}</b>.", parse_mode=ParseMode.HTML
        )
    else:
        await msg.reply_text("Usage: /mirror [on|off|user]")


async def cmd_tts(update: Update, context):
    """Handle /tts — toggle voice replies on text messages."""
    global _tts_text_replies
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not msg or not user or not chat or not _is_authorized(user.id, chat.id):
        return

    arg = context.args[0].lower() if context.args else ""
    if not arg:
        await msg.reply_text(
            f"<b>TTS Settings</b>\n\n"
            f"Engine: <b>{_tts_engine}</b>\n"
            f"Voice: <b>{_tts_voice}</b>\n"
            f"Text replies: <b>{'on' if _tts_text_replies else 'off'}</b>\n\n"
            f"Usage: /tts [on|off]\n"
            f"See also: /voice",
            parse_mode=ParseMode.HTML,
        )
        return

    if arg == "on":
        _tts_text_replies = True
        _save_tts_config()
        await msg.reply_text(
            f"Voice replies on text messages <b>enabled</b> ({_tts_engine}: {_tts_voice}).",
            parse_mode=ParseMode.HTML,
        )
    elif arg == "off":
        _tts_text_replies = False
        _save_tts_config()
        await msg.reply_text(
            "Voice replies on text messages <b>disabled</b>.", parse_mode=ParseMode.HTML
        )
    else:
        await msg.reply_text("Usage: /tts [on|off]")


async def cmd_voice(update: Update, context):
    """Handle /voice — switch TTS engine, list voices, set voice."""
    global _tts_engine, _tts_voice
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not msg or not user or not chat or not _is_authorized(user.id, chat.id):
        return

    arg = context.args[0].lower() if context.args else ""
    if not arg:
        groq_status = "available" if _GROQ_API_KEY else "no API key"
        await msg.reply_text(
            f"<b>Voice Settings</b>\n\n"
            f"Engine: <b>{_tts_engine}</b>\n"
            f"Voice: <b>{_tts_voice}</b>\n\n"
            f"Engines: edge (cloud), piper (local), groq ({groq_status})\n\n"
            f"Usage:\n"
            f"/voice edge|piper|groq — switch engine\n"
            f"/voice list — list voices\n"
            f"/voice &lt;name&gt; — set voice",
            parse_mode=ParseMode.HTML,
        )
        return

    if arg in ("edge", "piper", "groq"):
        if arg == "groq" and not _GROQ_API_KEY:
            await msg.reply_text(
                "GROQ_API_KEY not set. Start bot with the env var to use Groq TTS."
            )
            return
        _tts_engine = arg
        _tts_voice = _TTS_ENGINE_DEFAULTS[arg]
        _save_tts_config()
        await msg.reply_text(
            f"Switched to <b>{arg}</b> engine (voice: {_tts_voice}).",
            parse_mode=ParseMode.HTML,
        )
        return

    if arg == "list":
        if _tts_engine == "edge":
            import edge_tts

            voices = await edge_tts.list_voices()
            en_voices = [
                v["ShortName"] for v in voices if v.get("Locale", "").startswith("en")
            ]
            en_voices.sort()
            lines = "\n".join(en_voices)
            await msg.reply_text(
                f"<b>Edge-TTS voices ({len(en_voices)} English):</b>\n<code>{lines}</code>",
                parse_mode=ParseMode.HTML,
            )
        elif _tts_engine == "piper":
            import glob as globmod

            onnx_files = sorted(globmod.glob(os.path.join(PIPER_VOICES_DIR, "*.onnx")))
            names = [os.path.basename(f).replace(".onnx", "") for f in onnx_files]
            if not names:
                await msg.reply_text("No Piper voices found.")
                return
            lines = "\n".join(names)
            await msg.reply_text(
                f"<b>Piper voices ({len(names)}):</b>\n<code>{lines}</code>",
                parse_mode=ParseMode.HTML,
            )
        elif _tts_engine == "groq":
            groq_voices = "austin\nautumn\ndaniel\ndiana\nhannah\ntroy"
            await msg.reply_text(
                f"<b>Groq Orpheus voices (6):</b>\n<code>{groq_voices}</code>",
                parse_mode=ParseMode.HTML,
            )
        return

    # Treat as voice name
    _tts_voice = context.args[0]  # Preserve original case
    _save_tts_config()
    await msg.reply_text(
        f"Voice set to <b>{_tts_voice}</b> (engine: {_tts_engine}).",
        parse_mode=ParseMode.HTML,
    )


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
    app.add_handler(CommandHandler("mirror", cmd_mirror))
    app.add_handler(CommandHandler("tts", cmd_tts))
    app.add_handler(CommandHandler("voice", cmd_voice))

    # Messages — private chat: all text; groups: only @mentions or replies
    private_filter = filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND
    group_filter = filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND
    app.add_handler(MessageHandler(private_filter | group_filter, handle_message))

    # Voice messages — transcribe via faster-whisper, then process as text
    voice_filter = filters.ChatType.PRIVATE & (filters.VOICE | filters.AUDIO)
    group_voice_filter = filters.ChatType.GROUPS & (filters.VOICE | filters.AUDIO)
    app.add_handler(MessageHandler(voice_filter | group_voice_filter, handle_voice))

    app.post_init = _register_commands
    app.run_polling(allowed_updates=Update.ALL_TYPES)


async def _register_commands(application):
    """Register slash commands with Telegram so they appear in the / menu."""
    await application.bot.set_my_commands(
        [
            BotCommand("status", "Bot and session status"),
            BotCommand("search", "Search message history"),
            BotCommand("memory", "Search framework memory"),
            BotCommand("reset", "Reset conversation session"),
            BotCommand("whisper", "Switch STT engine (groq/local)"),
            BotCommand("mirror", "Toggle message mirroring (on/off/user)"),
            BotCommand("tts", "Toggle text-to-speech (on/off)"),
            BotCommand("voice", "Change TTS voice/engine"),
        ]
    )


if __name__ == "__main__":
    main()
