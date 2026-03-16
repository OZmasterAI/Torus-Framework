"""Claude Code adapter for TAP."""

from __future__ import annotations

from .base import BaseAdapter


class ClaudeAdapter(BaseAdapter):
    """Wraps Claude Code CLI as a TAP agent."""

    def spawn_cmd(self) -> list[str]:
        cmd = ["claude"]
        if self.persistent:
            # Long-lived: pipe mode, keep stdin open
            cmd.extend(["-p", "--model", self.model])
        else:
            # Ephemeral: print mode (task passed as arg later)
            cmd.extend(["-p", "--model", self.model])
        return cmd
