#!/usr/bin/env python3
"""Telegram Bot — Config loader and validator."""

import json
import os

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_PLUGIN_DIR, "config.json")


class BotConfigError(Exception):
    """Raised when config.json is missing or invalid."""
    pass


def load_config(path=None):
    """Load and validate config.json. Returns dict with all required fields."""
    path = path or _CONFIG_PATH
    try:
        with open(path) as f:
            cfg = json.load(f)
    except FileNotFoundError:
        raise BotConfigError(f"Config not found: {path}")
    except json.JSONDecodeError as e:
        raise BotConfigError(f"Invalid JSON in config: {e}")

    if not cfg.get("bot_token"):
        raise BotConfigError("bot_token must be set in config.json")
    if not isinstance(cfg.get("allowed_users", []), list):
        raise BotConfigError("allowed_users must be a list")
    if not isinstance(cfg.get("allowed_groups", []), list):
        raise BotConfigError("allowed_groups must be a list")

    # Defaults
    cfg.setdefault("allowed_users", [])
    cfg.setdefault("allowed_groups", [])
    cfg.setdefault("claude_cwd", os.path.expanduser("~/.claude"))
    cfg.setdefault("claude_timeout", 120)

    return cfg
