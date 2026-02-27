#!/usr/bin/env python3
"""Telegram Bot — subprocess wrapper for claude -p.

Runs Claude CLI as a subprocess and extracts result + session_id from JSON output.
"""

import asyncio
import json
import logging
import os

logger = logging.getLogger(__name__)


class ClaudeError(Exception):
    """Raised when Claude CLI fails."""
    pass


async def run_claude(message, session_id=None, cwd=None, timeout=120):
    """Run claude -p with message, return (result_text, session_id).

    Args:
        message: The user message to send to Claude
        session_id: Optional session ID to resume
        cwd: Working directory for Claude
        timeout: Max seconds to wait

    Returns:
        tuple: (result_text, session_id)

    Raises:
        ClaudeError: On subprocess failure or timeout
    """
    # Prepend learning prompt so bot saves preferences/decisions/corrections to memory
    _learning_prefix = (
        "[System: If user shares a preference, decision, correction, or important context, "
        "call remember_this() to save it. Keep tags concise.]\n\n"
    )
    full_message = _learning_prefix + message
    cmd = ["claude", "-p", full_message, "--output-format", "json", "--dangerously-skip-permissions"]
    if session_id:
        cmd += ["--resume", session_id]

    # Strip CLAUDECODE env var to avoid nested-session block
    # Set TORUS_BOT_SESSION so hooks skip heavy session lifecycle ops
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    env["TORUS_BOT_SESSION"] = "1"

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
    except FileNotFoundError:
        raise ClaudeError("claude CLI not found in PATH")

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise ClaudeError(f"Claude timed out after {timeout}s")

    if proc.returncode != 0:
        err = stderr.decode(errors="replace").strip()
        raise ClaudeError(f"Claude exited {proc.returncode}: {err[:500]}")

    try:
        data = json.loads(stdout.decode())
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ClaudeError(f"Failed to parse Claude output: {e}")

    result = data.get("result", "")
    new_session_id = data.get("session_id", session_id)

    if not result:
        logger.warning("Claude returned empty result")

    return result, new_session_id
