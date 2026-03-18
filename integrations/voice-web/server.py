#!/usr/bin/env python3
"""Torus Voice — WebSocket server bridging iPad speech to Claude via tmux.

Fire-and-forget: sends transcribed text to tmux, confirms delivery.
TTS: reads complete response from signal file written by Stop hook (tts_signal.py).
"""

import asyncio
import glob as globmod
import hashlib
import io
import json
import logging
import os
import tempfile
import wave

from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

import edge_tts
from piper import PiperVoice

import uvicorn

_HERE = os.path.dirname(os.path.abspath(__file__))

# --- Piper TTS voice loading ---
PIPER_VOICES_DIR = os.path.join(os.path.dirname(_HERE), "tts-voices", "piper-voices")
PIPER_PREFIX = "piper:"
_piper_models = {}  # name -> onnx_path
_piper_cache = {}  # name -> loaded PiperVoice (lazy)


def _scan_piper_voices():
    """Scan piper-voices/ dir for .onnx files and build name->path map."""
    _piper_models.clear()
    if not os.path.isdir(PIPER_VOICES_DIR):
        return
    for onnx_path in sorted(globmod.glob(os.path.join(PIPER_VOICES_DIR, "*.onnx"))):
        name = os.path.basename(onnx_path).replace(".onnx", "")
        _piper_models[name] = onnx_path


def _get_piper_voice(name):
    """Get or lazy-load a PiperVoice object by name."""
    if name in _piper_cache:
        return _piper_cache[name]
    onnx_path = _piper_models.get(name)
    if not onnx_path:
        return None
    config_path = onnx_path + ".json"
    if not os.path.exists(config_path):
        return None
    voice = PiperVoice.load(onnx_path, config_path=config_path)
    _piper_cache[name] = voice
    return voice


_scan_piper_voices()


class TmuxError(Exception):
    pass


async def _run(cmd):
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
    return (
        proc.returncode,
        stdout.decode(errors="replace"),
        stderr.decode(errors="replace"),
    )


async def is_tmux_session_alive(target):
    rc, _, _ = await _run(["tmux", "has-session", "-t", target.split(":")[0]])
    return rc == 0


async def _send_keys(target, text):
    sess = target if ":" in target else target + ":"
    rc, _, stderr = await _run(["tmux", "send-keys", "-t", sess, "-l", text])
    if rc != 0:
        raise TmuxError(f"send-keys failed: {stderr[:200]}")
    rc2, _, stderr2 = await _run(["tmux", "send-keys", "-t", sess, "Enter"])
    if rc2 != 0:
        raise TmuxError(f"send-keys Enter failed: {stderr2[:200]}")


async def send_to_tmux(message, target="claude-bot"):
    """Send message to tmux pane — fire and forget, no response polling."""
    if not await is_tmux_session_alive(target):
        raise TmuxError(f"tmux target '{target}' not found")
    # Signal that a voice message was sent — tts_signal.py checks for this
    pending_file = f"/tmp/voice-tts-pending-{target}"
    try:
        with open(pending_file, "w") as f:
            json.dump({"target": target}, f)
    except OSError:
        pass
    await _send_keys(target, message)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("voice-web")


def load_config():
    """Load config.json from same directory as server.py."""
    with open(os.path.join(_HERE, "config.json")) as f:
        return json.load(f)


CONFIG = load_config()

# --- Routes ---


async def list_tmux_sessions():
    """Get list of active tmux session names."""
    rc, stdout, _ = await _run(["tmux", "list-sessions", "-F", "#S"])
    if rc != 0:
        return []
    return [s.strip() for s in stdout.strip().splitlines() if s.strip()]


async def health(request):
    """Health check — also reports tmux session status."""
    sessions = await list_tmux_sessions()
    return JSONResponse(
        {
            "status": "ok",
            "tmux_sessions": sessions,
            "tmux_alive": len(sessions) > 0,
        }
    )


async def tmux_sessions(request):
    """List active tmux sessions for tab bar."""
    token = request.query_params.get("token", "")
    if token != CONFIG["auth_token"]:
        return JSONResponse({"ok": False, "error": "Invalid token"}, status_code=401)

    sessions = await list_tmux_sessions()
    return JSONResponse(
        {
            "ok": True,
            "sessions": sessions,
            "default_target": CONFIG.get("tmux_target", "claude"),
        }
    )


async def last_response(request):
    """Read Claude's last complete response from a target's TTS signal file.

    Query params:
      token — auth token (required)
      target — tmux session name (optional, falls back to config tmux_target)
    Returns: {"text": "...", "ok": true} or {"text": null, "ok": true} if no signal.
    """
    token = request.query_params.get("token", "")
    if token != CONFIG["auth_token"]:
        return JSONResponse({"ok": False, "error": "Invalid token"}, status_code=401)

    target = request.query_params.get("target") or CONFIG.get("tmux_target", "claude")
    signal_file = f"/tmp/voice-tts-signal-{target}.json"

    try:
        with open(signal_file) as f:
            signal = json.load(f)
        return JSONResponse({"ok": True, "text": signal.get("text")})
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return JSONResponse({"ok": True, "text": None})


TTS_CACHE_DIR = os.path.join(tempfile.gettempdir(), "voice-web-tts")
os.makedirs(TTS_CACHE_DIR, exist_ok=True)
DEFAULT_VOICE = "en-US-GuyNeural"


def _piper_synthesize(pv, text, out_path):
    """Synthesize text to WAV file using Piper (runs in executor thread)."""
    with wave.open(out_path, "wb") as wav_file:
        pv.synthesize_wav(text, wav_file)


async def tts_endpoint(request):
    """Generate TTS audio from text using edge-tts or Piper.

    Query params:
      token — auth token (required)
      voice — edge-tts voice name (optional, default en-US-GuyNeural)
    Body: raw text to speak
    Returns: audio/mpeg
    """
    token = request.query_params.get("token", "")
    if token != CONFIG["auth_token"]:
        return JSONResponse({"ok": False, "error": "Invalid token"}, status_code=401)

    body = await request.body()
    text = body.decode("utf-8", errors="replace").strip()
    if not text:
        return JSONResponse({"ok": False, "error": "No text"}, status_code=400)
    if len(text) > 10000:
        return JSONResponse({"ok": False, "error": "Text too long"}, status_code=400)

    voice = request.query_params.get("voice", DEFAULT_VOICE)

    # Cache by text+voice hash
    cache_key = hashlib.md5(f"{voice}:{text}".encode()).hexdigest()

    # Route: Piper (local) vs edge-tts (cloud)
    if voice.startswith(PIPER_PREFIX):
        piper_name = voice[len(PIPER_PREFIX) :]
        cache_path = os.path.join(TTS_CACHE_DIR, f"{cache_key}.wav")

        if not os.path.exists(cache_path):
            pv = _get_piper_voice(piper_name)
            if not pv:
                return JSONResponse(
                    {"ok": False, "error": f"Piper voice '{piper_name}' not found"},
                    status_code=404,
                )
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None, _piper_synthesize, pv, text, cache_path
                )
                logger.info(
                    "Piper TTS generated: %d chars, voice=%s", len(text), piper_name
                )
            except Exception as e:
                logger.error("Piper TTS error: %s", e)
                return JSONResponse(
                    {"ok": False, "error": "TTS failed"}, status_code=500
                )

        with open(cache_path, "rb") as f:
            audio = f.read()
        return Response(
            audio,
            media_type="audio/wav",
            headers={
                "Cache-Control": "public, max-age=300",
            },
        )

    # Edge-TTS (cloud)
    cache_path = os.path.join(TTS_CACHE_DIR, f"{cache_key}.mp3")

    if not os.path.exists(cache_path):
        try:
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(cache_path)
            logger.info("TTS generated: %d chars, voice=%s", len(text), voice)
        except Exception as e:
            logger.error("edge-tts error: %s", e)
            return JSONResponse({"ok": False, "error": "TTS failed"}, status_code=500)

    with open(cache_path, "rb") as f:
        audio = f.read()

    return Response(
        audio,
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "public, max-age=300",
        },
    )


async def tts_voices(request):
    """List available edge-tts voices."""
    token = request.query_params.get("token", "")
    if token != CONFIG["auth_token"]:
        return JSONResponse({"ok": False, "error": "Invalid token"}, status_code=401)

    voices = await edge_tts.list_voices()
    # Filter to English voices
    en_voices = [
        {"name": v["ShortName"], "gender": v["Gender"]}
        for v in voices
        if v["Locale"].startswith("en-")
    ]

    # Include Piper voices
    piper_voices = [
        {"name": f"{PIPER_PREFIX}{name}"} for name in sorted(_piper_models.keys())
    ]

    return JSONResponse({"ok": True, "voices": en_voices, "piper_voices": piper_voices})


async def ws_endpoint(websocket: WebSocket):
    """WebSocket endpoint for voice input.

    Protocol:
      Client sends: {"type": "auth", "token": "..."}
      Client sends: {"type": "message", "text": "..."}
      Server sends: {"type": "sent", "text": "Sent!"}
      Server sends: {"type": "error", "text": "..."}
      Server sends: {"type": "status", "text": "..."}
    """
    await websocket.accept()

    # --- Auth handshake ---
    authenticated = False
    try:
        token = websocket.query_params.get("token")
        if token and token == CONFIG["auth_token"]:
            authenticated = True
            await websocket.send_json({"type": "status", "text": "authenticated"})
        else:
            try:
                raw = await asyncio.wait_for(websocket.receive_json(), timeout=30)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "error", "text": "Auth timeout"})
                await websocket.close(1008)
                return

            if raw.get("type") == "auth" and raw.get("token") == CONFIG["auth_token"]:
                authenticated = True
                await websocket.send_json({"type": "status", "text": "authenticated"})
            else:
                await websocket.send_json({"type": "error", "text": "Invalid token"})
                await websocket.close(1008)
                return
    except WebSocketDisconnect:
        return

    if not authenticated:
        return

    logger.info("Client authenticated via WebSocket")

    # --- Message loop ---
    default_target = CONFIG.get("tmux_target", "claude")
    max_len = CONFIG.get("max_message_length", 4000)

    try:
        while True:
            raw = await websocket.receive_json()
            msg_type = raw.get("type")

            if msg_type != "message":
                continue

            text = (raw.get("text") or "").strip()
            if not text:
                await websocket.send_json({"type": "error", "text": "Empty message"})
                continue

            if len(text) > max_len:
                await websocket.send_json(
                    {
                        "type": "error",
                        "text": f"Message too long ({len(text)} > {max_len})",
                    }
                )
                continue

            target = raw.get("target") or default_target
            logger.info("Received message for %s: %s", target, text[:80])

            try:
                await send_to_tmux(text, target=target)
                await websocket.send_json({"type": "sent", "text": "Sent!"})
                logger.info("Sent to tmux %s: %s", target, text[:80])
            except TmuxError as e:
                logger.error("Tmux error: %s", e)
                await websocket.send_json({"type": "error", "text": str(e)})

    except WebSocketDisconnect as e:
        logger.info("Client disconnected (code=%s)", getattr(e, "code", "unknown"))
    except Exception as e:
        logger.exception("WebSocket exception: %s", e)
        try:
            await websocket.send_json({"type": "error", "text": "Internal error"})
            await websocket.close(1011)
        except Exception:
            pass


# --- No-cache static files ---


class NoCacheStaticFiles(StaticFiles):
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            original_send = send

            async def no_cache_send(message):
                if message.get("type") == "http.response.start":
                    headers = list(message.get("headers", []))
                    headers.append(
                        (b"cache-control", b"no-cache, no-store, must-revalidate")
                    )
                    message["headers"] = headers
                await original_send(message)

            await super().__call__(scope, receive, no_cache_send)
        else:
            await super().__call__(scope, receive, send)


# --- App ---

routes = [
    Route("/health", health),
    Route("/tmux-sessions", tmux_sessions),
    Route("/last-response", last_response),
    Route("/tts", tts_endpoint, methods=["POST"]),
    Route("/tts/voices", tts_voices),
    WebSocketRoute("/ws", ws_endpoint),
    Mount("/", NoCacheStaticFiles(directory=os.path.join(_HERE, "static"), html=True)),
]

app = Starlette(routes=routes)


if __name__ == "__main__":
    ssl_cert = os.path.join(_HERE, CONFIG.get("ssl_cert", "certs/cert.pem"))
    ssl_key = os.path.join(_HERE, CONFIG.get("ssl_key", "certs/key.pem"))
    port = CONFIG.get("port", 8443)
    host = CONFIG.get("host", "0.0.0.0")

    ssl_kwargs = {}
    if os.path.exists(ssl_cert) and os.path.exists(ssl_key):
        ssl_kwargs = {"ssl_certfile": ssl_cert, "ssl_keyfile": ssl_key}
        logger.info("HTTPS enabled (cert: %s)", ssl_cert)
    else:
        logger.warning(
            "SSL certs not found — running without HTTPS! Web Speech API won't work on Safari."
        )

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
        **ssl_kwargs,
    )
