#!/usr/bin/env python3
"""Telegram Bot — Per-chat Claude session persistence.

Maps chat_id -> session_id so conversations resume across messages.
"""

import json
import os


def load_sessions(path):
    """Load sessions dict from JSON file. Returns {} if missing/corrupt."""
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_session(path, chat_id, session_id):
    """Save a chat_id -> session_id mapping. Atomic write."""
    sessions = load_sessions(path)
    sessions[str(chat_id)] = session_id

    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(sessions, f, indent=2)
    os.replace(tmp, path)


def get_session_id(path, chat_id):
    """Get session_id for a chat, or None if first message."""
    sessions = load_sessions(path)
    return sessions.get(str(chat_id))
