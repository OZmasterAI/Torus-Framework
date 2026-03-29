#!/usr/bin/env python3
"""LLM backend for Skill MCP v2 — claude -p subprocess wrapper.

Drop-in replacement for OpenSpace's LLMClient. Used by the analyzer
and evolver modules. Phase 5 will add OpenAICompatBackend alternative.
"""

import subprocess


class ClaudePClient:
    """LLM client using claude -p (pipe mode) subprocess."""

    def __init__(self, model: str = "claude-sonnet-4-6", timeout: int = 300):
        self.model = model
        self.timeout = timeout

    def complete(self, prompt: str, max_tokens: int | None = None) -> str:
        """Send prompt to claude -p and return the response text.

        Args:
            prompt: The full prompt text to send.
            max_tokens: Ignored (CLI no longer supports --max-tokens).

        Returns:
            The model's response text (stdout).

        Raises:
            RuntimeError: If claude -p exits with non-zero code.
            subprocess.TimeoutExpired: If the command exceeds timeout.
        """
        cmd = ["claude", "-p", "--model", self.model]

        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"claude -p failed (exit {result.returncode}): {result.stderr}"
            )
        return result.stdout
