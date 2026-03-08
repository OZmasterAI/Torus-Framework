#!/usr/bin/env python3
"""Telegram Bot — tmux routing transport for Claude.

Sends messages into an existing interactive Claude tmux session via
tmux send-keys and reads responses via tmux capture-pane.

Uses prompt detection (❯ for idle, ● for response) instead of sentinels.
No special instructions to Claude needed — purely observational.

Same interface as claude_runner.run_claude() so bot.py can swap transports.
"""

import asyncio
import logging
import re

logger = logging.getLogger(__name__)

# Prompt detection patterns (Claude Code terminal output)
_IDLE_RE = re.compile(r"^❯\s*$", re.MULTILINE)
_RESPONSE_RE = re.compile(r"^● ", re.MULTILINE)


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
    """Capture last N lines of tmux pane content."""
    start = f"-{last_n}" if last_n else "-"
    rc, stdout, _ = await _run(["tmux", "capture-pane", "-p", "-S", start, "-t", target])
    if rc != 0:
        raise TmuxError(f"capture-pane failed (rc={rc})")
    return stdout


async def is_tmux_session_alive(target):
    """Check if the tmux target session/pane exists."""
    rc, _, _ = await _run(["tmux", "has-session", "-t", target.split(":")[0]])
    return rc == 0


async def _send_keys(target, text):
    """Send text to tmux pane using literal mode to avoid interpretation."""
    rc, _, stderr = await _run(["tmux", "send-keys", "-t", target, "-l", text])
    if rc != 0:
        raise TmuxError(f"send-keys failed: {stderr[:200]}")
    # Send Enter separately (not literal)
    rc2, _, stderr2 = await _run(["tmux", "send-keys", "-t", target, "Enter"])
    if rc2 != 0:
        raise TmuxError(f"send-keys Enter failed: {stderr2[:200]}")


def _extract_response(pane_text, message):
    """Extract Claude's response between the user message and the idle prompt.

    Looks for the user's message in the pane, then captures everything from
    Claude's response (● marker) up to the next idle prompt (❯).
    """
    lines = pane_text.splitlines()

    # Find the last occurrence of the user's message
    msg_start = -1
    msg_prefix = message[:60]  # Match on first 60 chars to handle wrapping
    for i in range(len(lines) - 1, -1, -1):
        if msg_prefix in lines[i]:
            msg_start = i
            break

    if msg_start == -1:
        return ""

    # Find the response block: starts with ● after the message
    resp_start = -1
    for i in range(msg_start + 1, len(lines)):
        if _RESPONSE_RE.match(lines[i]):
            resp_start = i
            break

    if resp_start == -1:
        return ""

    # Find the idle prompt ❯ after the response
    resp_end = len(lines)
    for i in range(resp_start + 1, len(lines)):
        if _IDLE_RE.match(lines[i]):
            resp_end = i
            break

    # Extract and clean response lines
    response_lines = lines[resp_start:resp_end]

    # Strip the ● prefix from the first line
    if response_lines and response_lines[0].startswith("● "):
        response_lines[0] = response_lines[0][2:]

    # Strip tool call indicators and keep just the text content
    cleaned = []
    for line in response_lines:
        # Skip lines that are just horizontal rules or status bars
        if line.strip().startswith("─") and len(line.strip()) > 10:
            continue
        cleaned.append(line)

    result = "\n".join(cleaned).strip()
    return result


async def run_claude_tmux(message, tmux_target="claude-bot", timeout=120):
    """Send message via tmux, poll for idle prompt, return response text.

    Uses prompt detection — watches for ❯ (idle) and ● (response) markers
    in the terminal output. No sentinel instruction needed.

    Args:
        message: User message text
        tmux_target: tmux session:pane target (default "claude-bot")
        timeout: Max seconds to wait for response

    Returns:
        tuple: (result_text, None)

    Raises:
        TmuxError: On tmux failure or timeout
    """
    if not await is_tmux_session_alive(tmux_target):
        raise TmuxError(f"tmux target '{tmux_target}' not found")

    # Capture pane before sending to establish baseline
    before = await _capture_pane(tmux_target)
    before_idle_count = len(_IDLE_RE.findall(before))

    # Send the message (plain, no marker tag needed)
    await _send_keys(tmux_target, message)
    logger.info("Sent message to tmux target %s (%d chars)", tmux_target, len(message))

    # Poll for response completion
    # Phase 1: Wait for ● (Claude starts responding)
    # Phase 2: Wait for ❯ (Claude is idle again)
    saw_response = False
    poll_interval = 0.5
    elapsed = 0.0

    while elapsed < timeout:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

        current = await _capture_pane(tmux_target)

        # Check if Claude started responding (● appeared after our message)
        if not saw_response:
            # Look for ● after our message text
            msg_pos = current.rfind(message[:60])
            if msg_pos != -1:
                after_msg = current[msg_pos:]
                if _RESPONSE_RE.search(after_msg):
                    saw_response = True
                    logger.info("Claude started responding (%.1fs)", elapsed)
            continue

        # Phase 2: Claude is responding, wait for idle prompt
        current_idle_count = len(_IDLE_RE.findall(current))
        if current_idle_count > before_idle_count:
            # New idle prompt appeared = Claude is done
            response = _extract_response(current, message)
            if response:
                logger.info("Got response from tmux (%d chars, %.1fs)", len(response), elapsed)
                return response, None

    if saw_response:
        # Claude started but didn't finish in time — try to extract partial
        current = await _capture_pane(tmux_target)
        response = _extract_response(current, message)
        if response:
            logger.warning("Partial response extracted after timeout (%d chars)", len(response))
            return response, None

    raise TmuxError(f"Response timeout after {timeout}s — no idle prompt detected")
