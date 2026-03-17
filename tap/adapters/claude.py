"""Claude Code adapter for TAP.

Two modes:
  - Ephemeral: `claude -p --output-format json` per task (fresh process each time)
  - Persistent: `claude -p --output-format json --verbose` with stdin pipe
    (keep process alive, send prompts via stdin, read JSON results from stdout)

Output format (json mode):
  {"type":"result","subtype":"success","result":"...","session_id":"...","total_cost_usd":0.05,...}
"""

from __future__ import annotations

import json

from .base import BaseAdapter


class ClaudeAdapter(BaseAdapter):
    """Wraps Claude Code CLI as a TAP agent."""

    def spawn_cmd(self) -> list[str]:
        cmd = [
            "claude",
            "-p",
            "--output-format",
            "json",
            "--model",
            self.model,
            "--dangerously-skip-permissions",
        ]
        if self.persistent:
            cmd.append("--verbose")
        return cmd

    def parse_output(self, raw: str) -> str:
        """Parse Claude's JSON output to extract the result text."""
        raw = raw.strip()
        if not raw:
            return ""

        # Try to parse as JSON (claude -p --output-format json)
        try:
            data = json.loads(raw)
            msg_type = data.get("type", "")

            # Final result message
            if msg_type == "result":
                return data.get("result", "")

            # Streaming assistant message
            if msg_type == "assistant":
                message = data.get("message", {})
                content = message.get("content", [])
                parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))
                    elif isinstance(block, str):
                        parts.append(block)
                return "".join(parts)

            # System/init/rate_limit messages — skip
            if msg_type in ("system", "rate_limit_event"):
                return ""

            # Unknown JSON — return as-is
            return raw
        except (json.JSONDecodeError, TypeError):
            # Not JSON — return raw text
            return raw

    def format_input(self, prompt: str) -> str:
        """Format prompt for Claude's stdin."""
        # Claude -p reads from stdin as plain text, one prompt
        # For persistent mode, each line sent is a new prompt
        return prompt.rstrip("\n") + "\n"
