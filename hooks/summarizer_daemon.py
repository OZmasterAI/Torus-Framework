#!/usr/bin/env python3
"""Summarizer daemon — persistent worker for LLM summarization tasks.

Listens on a Unix socket, receives summarization requests, races multiple
models via OpenRouter API, returns the fastest non-null result.

Socket: ~/.claude/hooks/.summarizer.sock
PID:    ~/.claude/hooks/.summarizer.pid

Usage:
    python3 summarizer_daemon.py              # foreground
    python3 summarizer_daemon.py --daemon     # background (detach)

Protocol (JSON-over-newline, same as enforcer_daemon):
    Request:  {"type": "summarize", "prompt": "...", "max_tokens": 200}
    Response: {"ok": true, "result": "...", "model": "..."} or {"ok": false, "error": "..."}

Config (config.json):
    "openrouter_api_key": "sk-key"                           # one key for all
    "openrouter_api_key": "sk-key-A,sk-key-B"                # comma-separated by model index
    "summarizer_models": ["model-a", "model-b"]              # race these models
    "summarizer_models": [{"model": "m", "api_key": "k"}]    # per-model key override
    "summarizer_model": "model-a"                             # single model fallback
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

DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"
DEFAULT_MAX_TOKENS = 2000  # High for reasoning models with hidden thinking tokens
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
    """Create client using the first openrouter_api_key. Validates key exists."""
    raw = config.get("openrouter_api_key", "")
    keys = [k.strip() for k in raw.split(",") if k.strip()] if raw else []
    if not keys or keys[0] == "your-key-here":
        raise ValueError("openrouter_api_key not set in config.json")
    return _make_client(keys[0])


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

    Supports:
      - Comma-separated keys paired to models by index (wraps around)
      - Per-model api_key override in object format
      - Single model fallback
    """
    raw_keys = config.get("openrouter_api_key", "")
    keys = [k.strip() for k in raw_keys.split(",") if k.strip()] if raw_keys else []
    default_key = keys[0] if keys else ""
    models_cfg = config.get("summarizer_models", [])

    if not models_cfg:
        single = req.get("model", config.get("summarizer_model", DEFAULT_MODEL))
        client = _make_client(default_key) if default_key else None
        return [(single, client)]

    clients = {}
    result = []
    for i, entry in enumerate(models_cfg):
        if isinstance(entry, str):
            key = keys[i % len(keys)] if keys else default_key
            if key not in clients:
                clients[key] = _make_client(key) if key else None
            result.append((entry, clients[key]))
        elif isinstance(entry, dict):
            model = entry.get("model", DEFAULT_MODEL)
            key = entry.get("api_key", keys[i % len(keys)] if keys else default_key)
            if key not in clients:
                clients[key] = _make_client(key) if key else None
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
        except (OSError, ValueError, KeyError, AttributeError):
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
    if req_type not in ("summarize", "classify"):
        return json.dumps({"ok": False, "error": f"unknown type: {req_type}"})

    if req_type == "classify":
        content = req.get("content", "")
        tags = req.get("tags", "")
        if not content:
            return json.dumps({"ok": False, "error": "empty content"})
        prompt = (
            "Classify the following memory as either 'reference' (long-term, reusable knowledge, "
            "decisions, lessons) or 'working' (ephemeral, session-specific, auto-captured). "
            "Respond with ONLY one word: reference or working.\n\n"
            f"Tags: {tags}\nContent: {content}"
        )
        try:
            model_clients = _parse_models(config, req)
            result, _ = _race_summarize(prompt, 10, model_clients)
            if result:
                mt = result.strip().lower().split()[0] if result.strip() else ""
                if mt in ("reference", "working"):
                    return json.dumps({"ok": True, "memory_type": mt})
        except Exception:
            pass
        return json.dumps({"ok": False, "error": "classification failed"})

    prompt = req.get("prompt", "")
    if not prompt:
        return json.dumps({"ok": False, "error": "empty prompt"})

    max_tokens = req.get("max_tokens", DEFAULT_MAX_TOKENS)
    model_clients = _parse_models(config, req)

    result, winner_model = _race_summarize(prompt, max_tokens, model_clients)
    if result:
        return json.dumps({"ok": True, "result": result, "model": winner_model})
    return json.dumps({"ok": False, "error": "all models returned null or failed"})


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
