#!/usr/bin/env python3
"""TTS Signal — Stop Hook

Fires after every Claude response. Writes the complete assistant message
to /tmp/voice-tts-signal.json for the voice-web server to read.

This solves the timing problem where polling tmux captured partial text
before Claude finished generating. The Stop hook only fires after the
full response is complete.

Input (stdin JSON):
  {"session_id": "...", "last_assistant_message": "...", "hook_event_name": "Stop"}

Output: /tmp/voice-tts-signal-{target}.json
  {"text": "cleaned response", "timestamp": 1709683200.0}

Pending markers are per-target: /tmp/voice-tts-pending-{target}
Supports multiple voice-web instances targeting different tmux sessions.

Fail-open: always exits 0.
"""

import json
import os
import re
import sys
import time

PENDING_PREFIX = "/tmp/voice-tts-pending-"


def _strip_markdown(text):
    """Strip markdown formatting that doesn't speak well in TTS."""
    # Remove code blocks first (before inline code)
    text = re.sub(r"```[\s\S]*?```", "", text)
    # Bold / italic
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    # Inline code
    text = re.sub(r"`(.+?)`", r"\1", text)
    # Headings
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Bullet lists
    text = re.sub(r"^[-*]\s+", "", text, flags=re.MULTILINE)
    # Numbered lists
    text = re.sub(r"^\d+\.\s+", "", text, flags=re.MULTILINE)
    # Horizontal rules
    text = re.sub(r"---+", "", text)
    # Collapse excessive newlines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _get_my_tmux_session():
    """Return the tmux session name this Claude instance is running in."""
    tmux_env = os.environ.get("TMUX", "")
    if not tmux_env:
        return None
    try:
        import subprocess

        result = subprocess.run(
            ["tmux", "display-message", "-p", "#S"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None


def main():
    try:
        data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        data = {}

    # Find any pending marker (e.g. /tmp/voice-tts-pending-claude)
    pending_files = [
        f for f in os.listdir("/tmp") if f.startswith("voice-tts-pending-")
    ]
    if not pending_files:
        sys.exit(0)

    message = (data.get("last_assistant_message") or "").strip()
    if not message:
        sys.exit(0)

    cleaned = _strip_markdown(message)
    if not cleaned:
        sys.exit(0)

    # Only write to targets that match our tmux session
    my_session = _get_my_tmux_session()

    # Write signal for each pending target and consume marker
    for pf in pending_files:
        pending_path = os.path.join("/tmp", pf)
        target = pf.replace("voice-tts-pending-", "")

        # Skip targets that belong to a different tmux session
        if my_session and target != my_session:
            continue

        signal_file = f"/tmp/voice-tts-signal-{target}.json"

        # Consume the pending marker
        try:
            os.unlink(pending_path)
        except OSError:
            continue

        # Write signal atomically
        signal = json.dumps({"text": cleaned, "timestamp": time.time()})
        tmp = signal_file + ".tmp"
        try:
            with open(tmp, "w") as f:
                f.write(signal)
            os.replace(tmp, signal_file)
        except OSError:
            pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
