#!/usr/bin/env python3
"""Telegram Memory Plugin — Core Telethon Wrapper

Public functions:
- post_session(text) -> int  — sends HTML to Saved Messages, returns msg ID
- search(query, limit) -> list[dict]  — searches Saved Messages
- get_history(limit) -> list[dict]  — fetches recent messages
- send_to_oz(text) -> int  — sends message to OZ (@***REDACTED***)
- read_from_oz(limit) -> list[dict]  — reads chat with OZ

Uses sync Telethon client with per-call open/close pattern (safe for subprocess).
"""

import json
import os
from contextlib import contextmanager

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_PLUGIN_DIR, "config.json")

OZ_USERNAME = "@***REDACTED***"
OZ_USER_ID = ***TG_USER_ID***
_OUTBOX_FILE = os.path.join(_PLUGIN_DIR, ".outbox.jsonl")
_PID_FILE = os.path.join(_PLUGIN_DIR, ".watcher.pid")


class TelegramError(Exception):
    """Raised when any Telegram operation fails."""
    pass


def _load_config():
    """Load and validate config.json."""
    try:
        with open(_CONFIG_PATH) as f:
            cfg = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        raise TelegramError(f"Config error: {e}")

    if not cfg.get("api_id") or not cfg.get("api_hash"):
        raise TelegramError("api_id and api_hash must be set in config.json")

    cfg["session_path"] = os.path.expanduser(cfg.get(
        "session_path",
        os.path.join(_PLUGIN_DIR, "session", "telegram")
    ))
    return cfg


def _get_client(cfg):
    """Create a TelegramClient instance from config."""
    try:
        from telethon.sync import TelegramClient
    except ImportError:
        raise TelegramError("Telethon not installed. Run: pip install telethon")

    session_dir = os.path.dirname(cfg["session_path"])
    os.makedirs(session_dir, exist_ok=True)

    return TelegramClient(
        cfg["session_path"],
        cfg["api_id"],
        cfg["api_hash"],
    )


@contextmanager
def _connected_client():
    """Context manager: yields an authenticated Telethon client."""
    cfg = _load_config()
    client = _get_client(cfg)
    client.connect()
    if not client.is_user_authorized():
        client.disconnect()
        raise TelegramError("Not authenticated. Run setup.py first.")
    try:
        yield client
    finally:
        client.disconnect()


def post_session(text: str) -> int:
    """Send HTML text to Telegram Saved Messages. Returns msg ID."""
    if not text or not text.strip():
        raise TelegramError("Empty message text")
    if len(text) > 4096:
        text = text[:4090] + "\n..."

    try:
        with _connected_client() as client:
            msg = client.send_message("me", text, parse_mode="html")
            return msg.id
    except TelegramError:
        raise
    except Exception as e:
        raise TelegramError(f"post_session failed: {e}")


def search(query: str, limit: int = 10) -> list:
    """Search Telegram Saved Messages. Returns [{id, text, date}, ...]."""
    if not query or not query.strip():
        return []

    try:
        with _connected_client() as client:
            messages = client.get_messages("me", search=query, limit=limit)
            return [
                {"id": m.id, "text": m.text, "date": m.date.isoformat() if m.date else None}
                for m in messages if m.text
            ]
    except TelegramError:
        raise
    except Exception as e:
        raise TelegramError(f"search failed: {e}")


def get_history(limit: int = 50) -> list:
    """Fetch recent messages from Saved Messages. Returns [{id, text, date}, ...]."""
    try:
        with _connected_client() as client:
            messages = client.get_messages("me", limit=limit)
            return [
                {"id": m.id, "text": m.text, "date": m.date.isoformat() if m.date else None}
                for m in messages if m.text
            ]
    except TelegramError:
        raise
    except Exception as e:
        raise TelegramError(f"get_history failed: {e}")


def _watcher_is_running():
    """Check if the watcher process is alive (by PID file)."""
    try:
        with open(_PID_FILE) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)  # signal 0 = check if process exists
        return True
    except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
        return False


def _queue_outbox(text: str):
    """Write a message to .outbox.jsonl for the watcher to send."""
    import json as _json
    entry = {"text": text}
    with open(_OUTBOX_FILE, "a") as f:
        f.write(_json.dumps(entry) + "\n")


def send_to_oz(text: str) -> int:
    """Send a message to OZ (@***REDACTED***). Returns msg ID or 0 if queued via outbox."""
    if not text or not text.strip():
        raise TelegramError("Empty message text")
    if len(text) > 4096:
        text = text[:4090] + "\n..."

    # If watcher is running, route through outbox to avoid session lock
    if _watcher_is_running():
        _queue_outbox(text)
        return 0  # queued, no msg ID available

    try:
        with _connected_client() as client:
            msg = client.send_message(OZ_USERNAME, text)
            return msg.id
    except TelegramError:
        raise
    except Exception as e:
        raise TelegramError(f"send_to_oz failed: {e}")


def read_from_oz(limit: int = 10) -> list:
    """Read recent messages from chat with OZ. Returns [{sender, text, date, id}, ...]."""
    try:
        with _connected_client() as client:
            messages = client.get_messages(OZ_USERNAME, limit=limit)
            return [
                {
                    "id": m.id,
                    "sender": "Claude" if m.out else "OZ",
                    "text": m.text,
                    "date": m.date.isoformat() if m.date else None,
                }
                for m in messages if m.text
            ]
    except TelegramError:
        raise
    except Exception as e:
        raise TelegramError(f"read_from_oz failed: {e}")
