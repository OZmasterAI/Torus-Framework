#!/usr/bin/env python3
"""Torus Voice — WebSocket server bridging iPad speech to Claude via tmux.

Fire-and-forget: sends transcribed text to tmux, confirms delivery.
Optional TTS mode: polls tmux for Claude's response and sends it back.
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import sys
import tempfile
import time

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
    await _send_keys(target, message)


async def capture_tmux_pane(target, lines=200):
    """Capture tmux pane content."""
    rc, stdout, stderr = await _run([
        "tmux", "capture-pane", "-t", target, "-p", "-S", f"-{lines}",
    ])
    if rc != 0:
        raise TmuxError(f"capture-pane failed: {stderr[:200]}")
    return stdout


def _is_tool_call(text):
    """Check if a ● line is a tool call rather than a text response."""
    tool_prefixes = (
        "Bash(", "Read ", "Edit(", "Write(", "Glob(", "Grep(", "Update(",
        "Agent(", "NotebookEdit(", "Skill(", "Search(", "WebFetch(",
        "Reading ", "Searching ", "Running ", "Editing ",
        "memory ", "mcp__",  # MCP tool calls
    )
    if any(text.startswith(p) for p in tool_prefixes):
        return True
    if "(MCP)" in text:
        return True
    return False


def extract_last_response(pane_text):
    """Extract Claude's last text response from tmux pane output.

    Claude responses start with ● (bullet). Tool calls also start with ●
    but are filtered out. The idle prompt ❯ at the bottom means Claude is done.
    Only the last consecutive text block (before the ❯) is returned.
    """
    lines = pane_text.split("\n")

    # Find the last idle prompt (❯) — means Claude is done
    last_prompt_idx = -1
    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].strip()
        if stripped.startswith("❯") or stripped == "❯":
            last_prompt_idx = i
            break

    if last_prompt_idx < 0:
        return None  # Claude still generating

    # Walk backwards from ❯ to collect the last text response block.
    # Skip tool output (⎿, ·), tool calls (● Bash(...)), and empty lines.
    # Stop at the previous ❯ or a tool call after we've found text.
    response_lines = []
    found_text = False

    for i in range(last_prompt_idx - 1, -1, -1):
        stripped = lines[i].strip()

        # Previous user prompt — stop
        if stripped.startswith("❯") or stripped == "❯":
            break

        # Empty line
        if not stripped:
            if found_text:
                response_lines.append("")
            continue

        # Tool output indicators — skip or stop
        if stripped.startswith(("⎿", "·", "╭", "╰", "│")):
            if found_text:
                break
            continue

        # ● line — could be text or tool call
        if stripped.startswith("●"):
            content = stripped[1:].strip()
            if _is_tool_call(content):
                if found_text:
                    break
                continue
            found_text = True
            response_lines.append(content)
            continue

        # Continuation line (indented text after a ● line)
        if found_text:
            if stripped.endswith("(ctrl+o to expand)"):
                break
            response_lines.append(stripped)

    if not response_lines:
        return None

    # We collected backwards — reverse
    response_lines.reverse()

    # Clean up empty edges
    while response_lines and not response_lines[-1]:
        response_lines.pop()
    while response_lines and not response_lines[0]:
        response_lines.pop(0)

    text = "\n".join(response_lines).strip()
    # Remove markdown formatting that doesn't speak well
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'`(.+?)`', r'\1', text)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^[-*]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\d+\.\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'---+', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip() if text.strip() else None


async def poll_for_response(websocket, target, timeout=120):
    """Poll tmux until Claude finishes responding, then send the response back."""
    poll_interval = 2.0  # seconds between polls
    elapsed = 0.0
    last_content = ""

    while elapsed < timeout:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

        try:
            pane = await capture_tmux_pane(target)
        except TmuxError:
            break

        # Check if content is still changing (Claude still generating)
        if pane == last_content and last_content:
            # Content stabilized — try to extract response
            response = extract_last_response(pane)
            if response:
                await websocket.send_json({"type": "response", "text": response})
                logger.info("TTS response sent (%d chars)", len(response))
                return
        last_content = pane

    logger.warning("TTS poll timed out after %.0fs", elapsed)


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


# Server-side stability tracking for /last-response
_last_pane_content = ""
_last_pane_time = 0.0
_stable_text = None  # only set when pane content unchanged for 4+ seconds


async def last_response(request):
    """Extract Claude's last response from tmux pane for TTS.

    Returns text only when tmux pane has been stable (unchanged) for 4+ seconds,
    meaning Claude is done generating.

    Query params:
      token — auth token (required)
    Returns: {"text": "...", "ok": true} or {"text": null, "ok": true} if still generating.
    """
    global _last_pane_content, _last_pane_time, _stable_text

    token = request.query_params.get("token", "")
    if token != CONFIG["auth_token"]:
        return JSONResponse({"ok": False, "error": "Invalid token"}, status_code=401)

    tmux_target = CONFIG.get("tmux_target", "claude-bot")
    try:
        pane = await capture_tmux_pane(tmux_target)
        now = time.time()

        if pane != _last_pane_content:
            # Content changed — reset stability timer
            _last_pane_content = pane
            _last_pane_time = now
            _stable_text = None
            return JSONResponse({"ok": True, "text": None})

        # Content unchanged — check if stable for 4+ seconds
        if (now - _last_pane_time) >= 4.0:
            if _stable_text is None:
                _stable_text = extract_last_response(pane)
            return JSONResponse({"ok": True, "text": _stable_text})

        return JSONResponse({"ok": True, "text": None})
    except TmuxError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


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
    response_timeout = CONFIG.get("response_timeout", 120)
    tts_enabled = False
    poll_task = None

    try:
        while True:
            raw = await websocket.receive_json()
            msg_type = raw.get("type")

            if msg_type == "tts_toggle":
                tts_enabled = bool(raw.get("enabled", False))
                logger.info("TTS %s", "enabled" if tts_enabled else "disabled")
                continue

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

            # Cancel any in-flight TTS poll
            if poll_task and not poll_task.done():
                poll_task.cancel()

            try:
                await send_to_tmux(text, target=tmux_target)
                await websocket.send_json({"type": "sent", "text": "Sent!"})
                logger.info("Sent to tmux: %s", text[:80])

                # Start polling for response if TTS is enabled
                if tts_enabled:
                    poll_task = asyncio.create_task(
                        poll_for_response(websocket, tmux_target, timeout=response_timeout)
                    )
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
    finally:
        if poll_task and not poll_task.done():
            poll_task.cancel()


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
