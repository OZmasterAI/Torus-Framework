#!/usr/bin/env python3
"""UserPromptSubmit hook: detect corrections/feature requests and capture observations.

Replaces user_prompt_check.sh with Python equivalent plus auto-capture integration.
Reads hook JSON from stdin, outputs XML tags to stdout for Claude context.
Must always exit 0 — capture failures must never crash the hook.
"""

import json
import os
import re
import sys

# --- Detection patterns (ported from user_prompt_check.sh) ---

_CORRECTION_RE = re.compile(
    r'(^no,|wrong|actually,|that\'s not right|that\'s incorrect|try again)',
    re.IGNORECASE,
)

_FEATURE_REQ_RE = re.compile(
    r'(can you|i wish|is there a way|would it be possible)',
    re.IGNORECASE,
)

# --- Capture constants ---

CAPTURE_QUEUE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".capture_queue.jsonl")


def main():
    # Read JSON from stdin
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    prompt = data.get("prompt", "")
    if not prompt:
        sys.exit(0)

    # --- Detection phase (stdout tags for Claude context) ---

    if _CORRECTION_RE.search(prompt):
        print(
            "<correction_detected>User appears to be correcting a previous response. "
            "Pay close attention to what they say is wrong and save the correction to "
            "memory with type:correction tag.</correction_detected>"
        )

    if _FEATURE_REQ_RE.search(prompt):
        print(
            "<feature_request_detected>User may be requesting a new feature or capability. "
            "Consider saving to memory with type:feature-request tag if it represents a "
            "recurring need.</feature_request_detected>"
        )

    # --- Capture phase (append observation to queue) ---

    try:
        from shared.secrets_filter import scrub
        from shared.observation import compress_observation

        truncated = prompt[:200]
        scrubbed = scrub(truncated)
        tool_input = {"prompt": scrubbed}
        obs = compress_observation("UserPrompt", tool_input, {}, "prompt_hook")
        with open(CAPTURE_QUEUE, "a") as f:
            f.write(json.dumps(obs) + "\n")
    except Exception:
        pass  # Capture failures must never crash the hook

    sys.exit(0)


if __name__ == "__main__":
    main()
