#!/usr/bin/env python3
"""Telegram Bot — tmux routing transport for Claude.

Sends messages into an existing interactive Claude tmux session via
tmux send-keys and reads responses via a Stop hook signal file.

The tgbot_response.py Stop hook writes last_assistant_message to
/tmp/tgbot-response-{target}.json when a pending marker exists.
This gives us the clean final response without pane scraping.

Same interface as claude_runner.run_claude() so bot.py can swap transports.
"""

import asyncio
import json
import logging
import os
import time

logger = logging.getLogger(__name__)

PENDING_PREFIX = "/tmp/tgbot-pending-"
RESPONSE_PREFIX = "/tmp/tgbot-response-"


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


def _clean_target_name(target):
    """Normalize tmux target to a safe filename component."""
    return target.replace(":", "-").replace(".", "-")


async def run_claude_tmux(message, tmux_target="claude-bot", timeout=120):
    """Send message via tmux, wait for Stop hook signal, return response text.

    Flow:
      1. Write pending marker to /tmp/tgbot-pending-{target}
      2. Send message via tmux send-keys
      3. Poll for /tmp/tgbot-response-{target}.json (written by Stop hook)
      4. Read and return the clean response

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

    safe_target = _clean_target_name(tmux_target)
    pending_file = f"{PENDING_PREFIX}{safe_target}"
    response_file = f"{RESPONSE_PREFIX}{safe_target}.json"

    # Clean up any stale response file
    try:
        os.unlink(response_file)
    except OSError:
        pass

    # Get the pane PID so the Stop hook can verify session ownership
    try:
        proc = await asyncio.create_subprocess_exec(
            "tmux", "list-panes", "-t", tmux_target, "-F", "#{pane_pid}",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        pane_pid = int(stdout.decode().strip().split("\n")[0])
    except Exception:
        pane_pid = None

    # Write pending marker so the Stop hook knows to capture
    with open(pending_file, "w") as f:
        f.write(json.dumps({
            "timestamp": time.time(),
            "message_preview": message[:60],
            "pane_pid": pane_pid,
        }))

    # Send the message
    try:
        await _send_keys(tmux_target, message)
    except TmuxError:
        # Clean up pending marker on send failure
        try:
            os.unlink(pending_file)
        except OSError:
            pass
        raise

    logger.info("Sent message to tmux target %s (%d chars)", tmux_target, len(message))

    # Poll for response signal file
    poll_interval = 0.5
    elapsed = 0.0

    while elapsed < timeout:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

        if os.path.exists(response_file):
            try:
                with open(response_file) as f:
                    signal = json.load(f)
                response = signal.get("text", "").strip()
                if response:
                    # Clean up response file
                    try:
                        os.unlink(response_file)
                    except OSError:
                        pass
                    logger.info("Got response via signal (%d chars, %.1fs)", len(response), elapsed)
                    return response, None
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Signal file read error: %s", e)
                continue

    # Clean up pending marker on timeout
    try:
        os.unlink(pending_file)
    except OSError:
        pass

    raise TmuxError(f"Response timeout after {timeout}s — no signal received")
