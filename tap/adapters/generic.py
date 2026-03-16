"""Generic adapter for any stdin/stdout CLI agent."""

from __future__ import annotations

from .base import BaseAdapter


class GenericAdapter(BaseAdapter):
    """Wraps any CLI that accepts stdin and outputs to stdout."""

    def __init__(
        self,
        cmd: list[str],
        model: str = "",
        persistent: bool = True,
    ):
        super().__init__(model=model, persistent=persistent)
        self.cmd = cmd

    def spawn_cmd(self) -> list[str]:
        return list(self.cmd)
