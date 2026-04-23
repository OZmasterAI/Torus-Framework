"""Goose adapter for TAP."""

from __future__ import annotations

from .base import BaseAdapter


class GooseAdapter(BaseAdapter):
    """Wraps Goose CLI as a TAP agent."""

    def spawn_cmd(self) -> list[str]:
        if self.persistent:
            return ["goose", "session", "--with-builtin", "developer"]
        return ["goose", "run", "--no-session", "-t"]
