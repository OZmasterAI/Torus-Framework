#!/usr/bin/env python3
"""Torus Voice — WebSocket server bridging iPad speech to Claude via tmux.

Serves a static web app with Web Speech API integration.
WebSocket endpoint receives transcribed text, routes through tmux_runner,
and streams back Claude's response.
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

# Import tmux_runner from telegram-bot (zero duplication)
_HERE = os.path.dirname(os.path.abspath(__file__))
_TG_BOT_DIR = os.path.join(os.path.dirname(_HERE), "telegram-bot")
sys.path.insert(0, _TG_BOT_DIR)

from tmux_runner import run_claude_tmux, is_tmux_session_alive, TmuxError  # noqa: E402

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
    """WebSocket endpoint for voice chat.

    Protocol:
      Client sends: {"type": "auth", "token": "..."}
      Client sends: {"type": "message", "text": "..."}
      Server sends: {"type": "response", "text": "..."}
      Server sends: {"type": "error", "text": "..."}
      Server sends: {"type": "status", "text": "..."}
    """
    await websocket.accept()

    # --- Auth handshake ---
    authenticated = False
    try:
        # Check query param first (for reconnect with stored token)
        token = websocket.query_params.get("token")
        if token and token == CONFIG["auth_token"]:
            authenticated = True
            await websocket.send_json({"type": "status", "text": "authenticated"})
        else:
            # Wait for auth message
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
    timeout = CONFIG.get("response_timeout", 120)
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
            await websocket.send_json({"type": "status", "text": "thinking"})

            try:
                response, _ = await run_claude_tmux(
                    text,
                    tmux_target=tmux_target,
                    timeout=timeout,
                )
                await websocket.send_json({"type": "response", "text": response})
                logger.info("Sent response (%d chars)", len(response))
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


# --- App ---

routes = [
    Route("/health", health),
    WebSocketRoute("/ws", ws_endpoint),
    Mount("/", StaticFiles(directory=os.path.join(_HERE, "static"), html=True)),
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
