#!/usr/bin/env python3
"""Summarizer daemon — persistent Haiku worker for LLM summarization tasks.

Listens on a Unix socket, receives summarization requests, calls OpenRouter API
with a fast model (Haiku-class), returns results. Eliminates claude -p spawn
overhead (~3-8s) for session_end summaries and working-memory tasks.

Socket: ~/.claude/hooks/.summarizer.sock
PID:    ~/.claude/hooks/.summarizer.pid

Usage:
    python3 summarizer_daemon.py              # foreground
    python3 summarizer_daemon.py --daemon     # background (detach)

Protocol (JSON-over-newline, same as enforcer_daemon):
    Request:  {"type": "summarize", "prompt": "...", "max_tokens": 200, "model": "..."}
    Response: {"ok": true, "result": "..."} or {"ok": false, "error": "..."}
"""

import atexit
import json
import os
import signal
import socket
import sys
import threading

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
CLAUDE_DIR = os.path.dirname(HOOKS_DIR)
SOCKET_PATH = os.path.join(HOOKS_DIR, ".summarizer.sock")
PID_FILE = os.path.join(HOOKS_DIR, ".summarizer.pid")
CONFIG_FILE = os.path.join(CLAUDE_DIR, "config.json")

DEFAULT_MODEL = "anthropic/claude-haiku-4-5-20251001"
DEFAULT_MAX_TOKENS = 300
SOCKET_TIMEOUT = 30


def _load_config():
    """Load config.json and return dict."""
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _get_client(config=None):
    """Create OpenRouter-compatible client using config.json key."""
    import anthropic

    if config is None:
        config = _load_config()
    api_key = config.get("openrouter_api_key", "")
    if not api_key or api_key == "your-key-here":
        raise ValueError("openrouter_api_key not set in config.json")
    return anthropic.Anthropic(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
    )


def _summarize(client, prompt, max_tokens=DEFAULT_MAX_TOKENS, model=DEFAULT_MODEL):
    """Call the API and return the text response."""
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def _handle_request(client, raw, config):
    """Parse request JSON, dispatch, return response JSON."""
    try:
        req = json.loads(raw)
    except json.JSONDecodeError:
        return json.dumps({"ok": False, "error": "invalid JSON"})

    req_type = req.get("type", "")
    if req_type != "summarize":
        return json.dumps({"ok": False, "error": f"unknown type: {req_type}"})

    prompt = req.get("prompt", "")
    if not prompt:
        return json.dumps({"ok": False, "error": "empty prompt"})

    max_tokens = req.get("max_tokens", DEFAULT_MAX_TOKENS)
    model = req.get("model", config.get("summarizer_model", DEFAULT_MODEL))

    try:
        result = _summarize(client, prompt, max_tokens, model)
        return json.dumps({"ok": True, "result": result})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)[:200]})


def _handle_client(client, conn, config):
    """Handle a single client connection."""
    try:
        conn.settimeout(SOCKET_TIMEOUT)
        buf = b""
        while b"\n" not in buf:
            chunk = conn.recv(65536)
            if not chunk:
                break
            buf += chunk
        if buf:
            raw = buf.split(b"\n", 1)[0].decode("utf-8", errors="replace")
            response = _handle_request(client, raw, config)
            conn.sendall(response.encode("utf-8") + b"\n")
    except (socket.timeout, OSError):
        pass
    finally:
        conn.close()


def _cleanup():
    """Remove socket and PID files."""
    for path in (SOCKET_PATH, PID_FILE):
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass


def _bind_socket():
    """Create and bind the Unix socket. Removes stale socket if needed."""
    if os.path.exists(SOCKET_PATH):
        try:
            os.remove(SOCKET_PATH)
        except OSError:
            pass
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(SOCKET_PATH)
    sock.listen(5)
    return sock


def main():
    config = _load_config()

    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    atexit.register(_cleanup)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    client = _get_client(config)
    sock = _bind_socket()

    sys.stderr.write(
        f"[SUMMARIZER-DAEMON] Started (PID {os.getpid()}, socket {SOCKET_PATH})\n"
    )

    try:
        while True:
            conn, _ = sock.accept()
            t = threading.Thread(
                target=_handle_client, args=(client, conn, config), daemon=True
            )
            t.start()
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
        _cleanup()


if __name__ == "__main__":
    if "--daemon" in sys.argv:
        if os.fork() > 0:
            sys.exit(0)
        os.setsid()
        if os.fork() > 0:
            sys.exit(0)
        sys.stdout = open(os.devnull, "w")
        sys.stderr = open(os.devnull, "w")
    main()
