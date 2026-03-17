"""Claude Code adapter for TAP.

Two modes:
  - Ephemeral: `claude -p --output-format json` per task (fresh process each time)
  - Persistent (stream-json): `claude -p --input-format stream-json --output-format stream-json`
    (long-lived process, NDJSON on stdin/stdout, multi-turn conversations)

Output format (json mode):
  {"type":"result","subtype":"success","result":"...","session_id":"...","total_cost_usd":0.05,...}

Stream-json output (NDJSON, one per line):
  {"type":"system","session_id":"...","model":"..."}
  {"type":"assistant","message":{"content":[{"type":"text","text":"..."}]}}
  {"type":"result","subtype":"success","result":"...","session_id":"..."}
"""

from __future__ import annotations

import json

from .base import BaseAdapter


class ClaudeStreamParser:
    """Parse and format NDJSON stream-json messages for Claude Code."""

    @staticmethod
    def parse(line: str) -> dict | None:
        """Parse one NDJSON line into a message dict. Returns None on invalid JSON."""
        line = line.strip()
        if not line:
            return None
        try:
            return json.loads(line)
        except (json.JSONDecodeError, TypeError):
            return None

    @staticmethod
    def is_turn_complete(msg: dict) -> bool:
        """True if this message signals the end of a turn."""
        return msg.get("type") == "result"

    @staticmethod
    def extract_result(msg: dict) -> str:
        """Extract text from a result or assistant message."""
        msg_type = msg.get("type", "")
        if msg_type == "result":
            return msg.get("result", "")
        if msg_type == "assistant":
            message = msg.get("message", {})
            content = message.get("content", [])
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif isinstance(block, str):
                    parts.append(block)
            return "".join(parts)
        return ""

    @staticmethod
    def extract_session_id(msg: dict) -> str | None:
        """Extract session_id from system or result messages."""
        return msg.get("session_id")

    def format_prompt(self, prompt: str, session_id: str = "default") -> str:
        """Format a user prompt as an NDJSON line for stream-json input."""
        msg = {
            "type": "user",
            "message": {
                "role": "user",
                "content": prompt,
            },
            "session_id": session_id,
            "parent_tool_use_id": None,
        }
        return json.dumps(msg) + "\n"


class ClaudeAdapter(BaseAdapter):
    """Wraps Claude Code CLI as a TAP agent."""

    def __init__(
        self,
        model: str = "sonnet",
        persistent: bool = True,
        resume_session_id: str | None = None,
    ):
        super().__init__(model=model, persistent=persistent)
        self.resume_session_id = resume_session_id

    def spawn_cmd(self) -> list[str]:
        if self.persistent:
            cmd = [
                "claude",
                "-p",
                "--input-format",
                "stream-json",
                "--output-format",
                "stream-json",
                "--model",
                self.model,
                "--dangerously-skip-permissions",
            ]
        else:
            cmd = [
                "claude",
                "-p",
                "--output-format",
                "json",
                "--model",
                self.model,
                "--dangerously-skip-permissions",
            ]
        if self.resume_session_id:
            cmd.extend(["--resume", self.resume_session_id])
        return cmd

    def parse_output(self, raw: str) -> str:
        """Parse Claude's JSON output to extract the result text."""
        raw = raw.strip()
        if not raw:
            return ""

        try:
            data = json.loads(raw)
            msg_type = data.get("type", "")

            if msg_type == "result":
                return data.get("result", "")

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

            if msg_type in ("system", "rate_limit_event"):
                return ""

            return raw
        except (json.JSONDecodeError, TypeError):
            return raw

    def format_input(self, prompt: str) -> str:
        """Format prompt for Claude's stdin.

        For persistent (stream-json) mode, returns NDJSON.
        For ephemeral mode, returns plain text.
        """
        if self.persistent:
            parser = ClaudeStreamParser()
            return parser.format_prompt(prompt)
        return prompt.rstrip("\n") + "\n"
