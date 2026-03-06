#!/usr/bin/env python3
"""Torus Voice — WebSocket server bridging iPad speech to Claude via tmux.

Fire-and-forget: sends transcribed text to tmux, confirms delivery.
TTS: reads complete response from signal file written by Stop hook (tts_signal.py).
"""

import asyncio
import hashlib
import json
import logging
import os
import sys
import tempfile

from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

import edge_tts

import uvicorn

_HERE = os.path.dirname(os.path.abspath(__file__))


class TmuxError(Exception):
    pass


async def _run(cmd):
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
    return proc.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")


async def is_tmux_session_alive(target):
    rc, _, _ = await _run(["tmux", "has-session", "-t", target.split(":")[0]])
    return rc == 0


async def _send_keys(target, text):
    rc, _, stderr = await _run(["tmux", "send-keys", "-t", target, "-l", text])
    if rc != 0:
        raise TmuxError(f"send-keys failed: {stderr[:200]}")
    rc2, _, stderr2 = await _run(["tmux", "send-keys", "-t", target, "Enter"])
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


def load_config(path=None):
    """Load config JSON. Accepts --config CLI arg or defaults to config.json."""
    if path is None:
        path = os.path.join(_HERE, "config.json")
    with open(path) as f:
        return json.load(f)


# Parse --config before anything else
_config_path = None
if "--config" in sys.argv:
    _idx = sys.argv.index("--config")
    if _idx + 1 < len(sys.argv):
        _config_path = sys.argv[_idx + 1]

CONFIG = load_config(_config_path)

# Signal file is scoped to tmux target so multiple instances don't collide
_tmux_target = CONFIG.get("tmux_target", "claude-bot")
SIGNAL_FILE = f"/tmp/voice-tts-signal-{_tmux_target}.json"

# --- Routes ---

async def health(request):
    """Health check — also reports tmux session status."""
    tmux_target = CONFIG.get("tmux_target", "claude-bot")
    tmux_alive = await is_tmux_session_alive(tmux_target)
    return JSONResponse({
        "status": "ok",
        "tmux_target": tmux_target,
        "tmux_alive": tmux_alive,
    })


async def last_response(request):
    """Read Claude's last complete response from the TTS signal file.

    The Stop hook (tts_signal.py) writes /tmp/voice-tts-signal.json after
    every Claude response completes, ensuring we always get the full text.

    Query params:
      token — auth token (required)
    Returns: {"text": "...", "ok": true} or {"text": null, "ok": true} if no signal.
    """
    token = request.query_params.get("token", "")
    if token != CONFIG["auth_token"]:
        return JSONResponse({"ok": False, "error": "Invalid token"}, status_code=401)

    try:
        with open(SIGNAL_FILE) as f:
            signal = json.load(f)
        return JSONResponse({"ok": True, "text": signal.get("text")})
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return JSONResponse({"ok": True, "text": None})


TTS_CACHE_DIR = os.path.join(tempfile.gettempdir(), "voice-web-tts")
os.makedirs(TTS_CACHE_DIR, exist_ok=True)
DEFAULT_VOICE = "en-US-GuyNeural"


async def tts_endpoint(request):
    """Generate TTS audio from text using edge-tts.

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

    return Response(audio, media_type="audio/mpeg", headers={
        "Cache-Control": "public, max-age=300",
    })


async def tts_voices(request):
    """List available edge-tts voices."""
    token = request.query_params.get("token", "")
    if token != CONFIG["auth_token"]:
        return JSONResponse({"ok": False, "error": "Invalid token"}, status_code=401)

    voices = await edge_tts.list_voices()
    # Filter to English voices
    en_voices = [{"name": v["ShortName"], "gender": v["Gender"]} for v in voices if v["Locale"].startswith("en-")]
    return JSONResponse({"ok": True, "voices": en_voices})


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
    tmux_target = CONFIG.get("tmux_target", "claude-bot")
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
                await websocket.send_json({
                    "type": "error",
                    "text": f"Message too long ({len(text)} > {max_len})",
                })
                continue

            logger.info("Received message: %s", text[:80])

            try:
                await send_to_tmux(text, target=tmux_target)
                await websocket.send_json({"type": "sent", "text": "Sent!"})
                logger.info("Sent to tmux: %s", text[:80])
            except TmuxError as e:
                logger.error("Tmux error: %s", e)
                await websocket.send_json({"type": "error", "text": str(e)})

    except WebSocketDisconnect as e:
        logger.info("Client disconnected (code=%s)", getattr(e, 'code', 'unknown'))
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
                    headers.append((b"cache-control", b"no-cache, no-store, must-revalidate"))
                    message["headers"] = headers
                await original_send(message)
            await super().__call__(scope, receive, no_cache_send)
        else:
            await super().__call__(scope, receive, send)

# --- App ---

routes = [
    Route("/health", health),
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
        logger.warning("SSL certs not found — running without HTTPS! Web Speech API won't work on Safari.")

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
        **ssl_kwargs,
    )
