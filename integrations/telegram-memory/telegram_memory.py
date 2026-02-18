#!/usr/bin/env python3
"""Telegram Memory Plugin — Core Telethon Wrapper

All other scripts import from this module. Provides three public functions:
- post_session(text) -> int  — sends HTML to Saved Messages, returns msg ID
- search(query, limit) -> list[dict]  — searches Saved Messages
- get_history(limit) -> list[dict]  — fetches recent messages

Uses sync Telethon client with per-call open/close pattern (safe for subprocess).
"""

import json
import os

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_PLUGIN_DIR, "config.json")


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

    # Expand ~ in session_path
    cfg["session_path"] = os.path.expanduser(cfg.get(
        "session_path",
        os.path.join(_PLUGIN_DIR, "session", "telegram")
    ))
    return cfg


def _get_client(cfg):
    """Create a TelegramClient instance from config.

    Usage: `with _get_client(cfg) as client: ...`
    """
    try:
        from telethon.sync import TelegramClient
    except ImportError:
        raise TelegramError("Telethon not installed. Run: pip install telethon")

    # Ensure session directory exists
    session_dir = os.path.dirname(cfg["session_path"])
    os.makedirs(session_dir, exist_ok=True)

    return TelegramClient(
        cfg["session_path"],
        cfg["api_id"],
        cfg["api_hash"],
    )


def post_session(text: str) -> int:
    """Send HTML text to Telegram Saved Messages.

    Args:
        text: HTML-formatted message (max 4096 chars, will be truncated)

    Returns:
        Message ID of the sent message.

    Raises:
        TelegramError on any failure.
    """
    if not text or not text.strip():
        raise TelegramError("Empty message text")

    # Telegram message limit
    if len(text) > 4096:
        text = text[:4090] + "\n..."

    cfg = _load_config()
    try:
        with _get_client(cfg) as client:
            client.start(phone=lambda: cfg.get("phone"))
            msg = client.send_message("me", text, parse_mode="html")
            return msg.id
    except TelegramError:
        raise
    except Exception as e:
        raise TelegramError(f"post_session failed: {e}")


def search(query: str, limit: int = 10) -> list:
    """Search Telegram Saved Messages.

    Args:
        query: Search text
        limit: Max results to return (default 10)

    Returns:
        List of dicts: [{id, text, date}, ...]

    Raises:
        TelegramError on any failure.
    """
    if not query or not query.strip():
        return []

    cfg = _load_config()
    try:
        with _get_client(cfg) as client:
            client.start(phone=lambda: cfg.get("phone"))
            messages = client.get_messages("me", search=query, limit=limit)
            results = []
            for msg in messages:
                if msg.text:
                    results.append({
                        "id": msg.id,
                        "text": msg.text,
                        "date": msg.date.isoformat() if msg.date else None,
                    })
            return results
    except TelegramError:
        raise
    except Exception as e:
        raise TelegramError(f"search failed: {e}")


def get_history(limit: int = 50) -> list:
    """Fetch recent messages from Telegram Saved Messages.

    Args:
        limit: Number of messages to fetch (default 50)

    Returns:
        List of dicts: [{id, text, date}, ...]

    Raises:
        TelegramError on any failure.
    """
    cfg = _load_config()
    try:
        with _get_client(cfg) as client:
            client.start(phone=lambda: cfg.get("phone"))
            messages = client.get_messages("me", limit=limit)
            results = []
            for msg in messages:
                if msg.text:
                    results.append({
                        "id": msg.id,
                        "text": msg.text,
                        "date": msg.date.isoformat() if msg.date else None,
                    })
            return results
    except TelegramError:
        raise
    except Exception as e:
        raise TelegramError(f"get_history failed: {e}")
