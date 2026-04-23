"""Base adapter interface for TAP agent wrapping."""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseAdapter(ABC):
    """Abstract adapter for wrapping a coding agent CLI."""

    def __init__(self, model: str = "sonnet", persistent: bool = True):
        self.model = model
        self.persistent = persistent

    @abstractmethod
    def spawn_cmd(self) -> list[str]:
        """Return the command + args to start the agent subprocess."""

    def parse_output(self, raw: str) -> str:
        """Parse raw subprocess output into a clean result string."""
        return raw.strip()

    def format_input(self, prompt: str) -> str:
        """Format a prompt for sending to the agent's stdin."""
        return prompt + "\n"

    @property
    def name(self) -> str:
        """Adapter name for display."""
        return self.__class__.__name__.replace("Adapter", "").lower()
