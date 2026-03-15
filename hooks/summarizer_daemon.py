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
DEFAULT_MAX_TOKENS = (
    2000  # High to accommodate reasoning models that use hidden thinking tokens
)
SOCKET_TIMEOUT = 30


def _load_config():
    """Load config.json and return dict."""
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _make_client(api_key):
    """Create OpenRouter-compatible client (OpenAI SDK)."""
    import openai

    return openai.OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")


def _get_default_client(config):
    """Create client using the default openrouter_api_key."""
    api_key = config.get("openrouter_api_key", "")
    if not api_key or api_key == "your-key-here":
        raise ValueError("openrouter_api_key not set in config.json")
    return _make_client(api_key)


def _summarize(client, prompt, max_tokens=DEFAULT_MAX_TOKENS, model=DEFAULT_MODEL):
    """Call the API and return the text response."""
    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content


def _parse_models(config, req):
    """Parse model config into (model_name, client) tuples.

    Config formats:
      "summarizer_models": ["model-a", "model-b"]           # all use default key
      "summarizer_models": [{"model": "m", "api_key": "k"}] # per-model keys
      "summarizer_model": "model-a"                          # single fallback
    """
    default_key = config.get("openrouter_api_key", "")
    default_client = _make_client(default_key) if default_key else None
    models_cfg = config.get("summarizer_models", [])

    if not models_cfg:
        single = req.get("model", config.get("summarizer_model", DEFAULT_MODEL))
        return [(single, default_client)]

    clients = {}  # cache per unique key
    result = []
    for entry in models_cfg:
        if isinstance(entry, str):
            result.append((entry, default_client))
        elif isinstance(entry, dict):
            model = entry.get("model", DEFAULT_MODEL)
            key = entry.get("api_key", default_key)
            if key not in clients:
                clients[key] = _make_client(key) if key else default_client
            result.append((model, clients[key]))
    return result


def _race_summarize(prompt, max_tokens, model_clients):
    """Race multiple models, return first non-null result."""
    result = [None]
    winner = [None]
    event = threading.Event()

    def _call(model, client):
        try:
            text = _summarize(client, prompt, max_tokens, model)
            if text and not event.is_set():
                result[0] = text
                winner[0] = model
                event.set()
        except Exception:
            pass

    threads = [
        threading.Thread(target=_call, args=(m, c), daemon=True)
        for m, c in model_clients
    ]
    for t in threads:
        t.start()
    event.wait(timeout=25)
    return result[0], winner[0]


def _handle_request(raw, config):
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
    model_clients = _parse_models(config, req)

    try:
        result, winner_model = _race_summarize(prompt, max_tokens, model_clients)
        if result:
            return json.dumps({"ok": True, "result": result, "model": winner_model})
        return json.dumps({"ok": False, "error": "all models returned null"})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)[:200]})


def _handle_client(conn, config):
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
            response = _handle_request(raw, config)
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

    _get_default_client(config)  # validate key early
    sock = _bind_socket()

    sys.stderr.write(
        f"[SUMMARIZER-DAEMON] Started (PID {os.getpid()}, socket {SOCKET_PATH})\n"
    )

    try:
        while True:
            conn, _ = sock.accept()
            t = threading.Thread(
                target=_handle_client, args=(conn, config), daemon=True
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
