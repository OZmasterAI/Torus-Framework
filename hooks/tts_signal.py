#!/usr/bin/env python3
"""TTS Signal — Stop Hook

Fires after every Claude response. Writes the complete assistant message
to /tmp/voice-tts-signal.json for the voice-web server to read.

This solves the timing problem where polling tmux captured partial text
before Claude finished generating. The Stop hook only fires after the
full response is complete.

Input (stdin JSON):
  {"session_id": "...", "last_assistant_message": "...", "hook_event_name": "Stop"}

Output: /tmp/voice-tts-signal.json
  {"text": "cleaned response", "timestamp": 1709683200.0}

Fail-open: always exits 0.
"""

import json
import os
import re
import sys
import time

SIGNAL_FILE = "/tmp/voice-tts-signal.json"


def _strip_markdown(text):
    """Strip markdown formatting that doesn't speak well in TTS."""
    # Remove code blocks first (before inline code)
    text = re.sub(r'```[\s\S]*?```', '', text)
    # Bold / italic
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    # Inline code
    text = re.sub(r'`(.+?)`', r'\1', text)
    # Headings
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # Bullet lists
    text = re.sub(r'^[-*]\s+', '', text, flags=re.MULTILINE)
    # Numbered lists
    text = re.sub(r'^\d+\.\s+', '', text, flags=re.MULTILINE)
    # Horizontal rules
    text = re.sub(r'---+', '', text)
    # Collapse excessive newlines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def main():
    try:
        data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        data = {}

    message = (data.get("last_assistant_message") or "").strip()
    if not message:
        sys.exit(0)

    cleaned = _strip_markdown(message)
    if not cleaned:
        sys.exit(0)

    # Write atomically
    signal = json.dumps({"text": cleaned, "timestamp": time.time()})
    tmp = SIGNAL_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            f.write(signal)
        os.replace(tmp, SIGNAL_FILE)
    except OSError:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
