#!/usr/bin/env python3
"""Telegram Bot — tmux routing transport for Claude.

Sends messages into an existing interactive Claude tmux session via
tmux send-keys and reads responses via tmux capture-pane.  Falls back
gracefully when the tmux session is unavailable.

Same interface as claude_runner.run_claude() so bot.py can swap transports.
"""

import asyncio
import logging
import os
import time

logger = logging.getLogger(__name__)

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
_SENTINEL = "END_TORUS_RESPONSE"
_MARKER_PREFIX = "TORUS_MSG_"
_SENTINEL_FILE = os.path.join(_PLUGIN_DIR, ".sentinel_sent")

# Learning prefix injected with sentinel rule
_LEARNING_PREFIX = (
    "[System: If user shares a preference, decision, correction, or important context, "
    "call remember_this() to save it. Keep tags concise.]"
)


class TmuxError(Exception):
    """Raised when tmux transport fails."""
    pass


async def _run(cmd):
    """Run a shell command, return stdout as string."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
    return proc.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")


async def _capture_pane(target, last_n=200):
    """Capture last N lines of tmux pane content (not full scrollback)."""
    start = f"-{last_n}" if last_n else "-"
    rc, stdout, _ = await _run(["tmux", "capture-pane", "-p", "-S", start, "-t", target])
    if rc != 0:
        raise TmuxError(f"capture-pane failed (rc={rc})")
    return stdout


async def is_tmux_session_alive(target):
    """Check if the tmux target session/pane exists."""
    rc, _, _ = await _run(["tmux", "has-session", "-t", target.split(":")[0]])
    return rc == 0


def _sentinel_was_sent(target):
    """Check if we already sent the sentinel rule to this target."""
    try:
        if not os.path.exists(_SENTINEL_FILE):
            return False
        with open(_SENTINEL_FILE) as f:
            return target in f.read()
    except OSError:
        return False


def _mark_sentinel_sent(target):
    """Record that we sent the sentinel rule to this target."""
    try:
        existing = ""
        if os.path.exists(_SENTINEL_FILE):
            with open(_SENTINEL_FILE) as f:
                existing = f.read()
        if target not in existing:
            with open(_SENTINEL_FILE, "a") as f:
                f.write(target + "\n")
    except OSError:
        pass


async def _send_keys(target, text):
    """Send text to tmux pane using literal mode to avoid interpretation."""
    rc, _, stderr = await _run(["tmux", "send-keys", "-t", target, "-l", text])
    if rc != 0:
        raise TmuxError(f"send-keys failed: {stderr[:200]}")
    # Send Enter separately (not literal)
    rc2, _, stderr2 = await _run(["tmux", "send-keys", "-t", target, "Enter"])
    if rc2 != 0:
        raise TmuxError(f"send-keys Enter failed: {stderr2[:200]}")


async def _send_sentinel_rule(target):
    """Send the sentinel instruction to Claude on first use of this target.

    Tells Claude to end every response with the sentinel string.
    Waits for the sentinel to appear (confirming Claude understood),
    then discards that response.
    """
    if _sentinel_was_sent(target):
        return

    logger.info("Sending sentinel rule to tmux target %s", target)

    rule = (
        f"{_LEARNING_PREFIX} "
        f"IMPORTANT RULE: End every response you give with the exact text "
        f'"{_SENTINEL}" on its own line. This is required for message parsing. '
        f"Acknowledge with just: Understood. {_SENTINEL}"
    )

    await _send_keys(target, rule)

    # Wait for sentinel acknowledgment
    for _ in range(60):  # 30 seconds max
        await asyncio.sleep(0.5)
        current = await _capture_pane(target)
        if _SENTINEL in current:
            _mark_sentinel_sent(target)
            logger.info("Sentinel rule acknowledged by target %s", target)
            return

    raise TmuxError("Sentinel rule not acknowledged within 30s")


def _extract_response(pane_text, marker):
    """Extract response text between marker and sentinel.

    The pane contains: ...marker...user_message...Claude_response...SENTINEL...
    We find the marker, skip the user message line, then grab everything
    up to the sentinel.
    """
    marker_pos = pane_text.rfind(marker)
    if marker_pos == -1:
        return ""

    sentinel_pos = pane_text.find(_SENTINEL, marker_pos)
    if sentinel_pos == -1:
        return ""

    # Text between marker and sentinel
    between = pane_text[marker_pos + len(marker):sentinel_pos]

    # The first line contains the rest of the user's message (same line as marker).
    # Find the first newline to skip it, then take Claude's response.
    first_nl = between.find("\n")
    if first_nl == -1:
        return ""
    response_block = between[first_nl + 1:]

    # Strip leading/trailing whitespace and empty lines
    return response_block.strip()


async def run_claude_tmux(message, tmux_target="claude-bot", timeout=120):
    """Send message via tmux, poll for sentinel, return response text.

    Args:
        message: User message text
        tmux_target: tmux session:pane target (default "claude-bot")
        timeout: Max seconds to wait for response

    Returns:
        tuple: (result_text, None)  — no session_id needed for persistent session

    Raises:
        TmuxError: On tmux failure or timeout
    """
    if not await is_tmux_session_alive(tmux_target):
        raise TmuxError(f"tmux target '{tmux_target}' not found")

    # Ensure sentinel rule is active
    await _send_sentinel_rule(tmux_target)

    # Generate unique marker for this message
    marker = f"{_MARKER_PREFIX}{int(time.time() * 1000)}"

    # Send marker + message as a single input so they appear together in the pane
    tagged_message = f"[{marker}] {message}"
    await _send_keys(tmux_target, tagged_message)
    logger.info("Sent message to tmux target %s (%d chars, marker=%s)", tmux_target, len(message), marker)

    # Poll for sentinel after our marker
    poll_interval = 0.5
    elapsed = 0.0
    while elapsed < timeout:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

        current = await _capture_pane(tmux_target)
        # Only look for sentinel AFTER our marker to avoid matching old responses
        marker_pos = current.rfind(marker)
        if marker_pos != -1 and _SENTINEL in current[marker_pos:]:
            response = _extract_response(current, marker)
            if response:
                logger.info("Got response from tmux (%d chars, %.1fs)", len(response), elapsed)
                return response, None

    raise TmuxError(f"Response timeout after {timeout}s — sentinel not detected")
