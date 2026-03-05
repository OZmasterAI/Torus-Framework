#!/usr/bin/env python3
"""Torus Voice — WebSocket server bridging iPad speech to Claude via tmux.

Fire-and-forget: sends transcribed text to tmux, confirms delivery.
User reads Claude's response in the terminal directly.
"""

import asyncio
import json
import logging
import os
import sys

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

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
    await _send_keys(target, message)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("voice-web")


def load_config():
    """Load config.json from the same directory."""
    config_path = os.path.join(_HERE, "config.json")
    with open(config_path) as f:
        return json.load(f)


CONFIG = load_config()


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

    # --- Message loop (fire-and-forget) ---
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

    except WebSocketDisconnect:
        logger.info("Client disconnected")
    except Exception as e:
        logger.exception("WebSocket error: %s", e)
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
