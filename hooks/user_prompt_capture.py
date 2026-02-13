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

# --- Sentiment detection patterns ---

_FRUSTRATION_RE = re.compile(
    r'\b(again|still|ugh|sigh|wrong|not working|broken|doesn\'t work|won\'t work)\b',
    re.IGNORECASE,
)
_CONFIDENCE_RE = re.compile(
    r'\b(great|perfect|nice|works|good|awesome|excellent|fixed)\b',
    re.IGNORECASE,
)
_UNCERTAINTY_RE = re.compile(
    r'\b(hmm|maybe|wonder|not sure|try|might|could)\b',
    re.IGNORECASE,
)
# 3+ consecutive uppercase words (e.g. "THIS IS WRONG")
_ALL_CAPS_RE = re.compile(r'(?:\b[A-Z]{2,}\b[\s]+){2,}\b[A-Z]{2,}\b')


def detect_sentiment(text: str) -> str:
    """Detect sentiment from user prompt text.

    Returns one of: frustration, confidence, uncertainty, neutral.
    Frustration takes priority (most actionable signal).
    """
    if _FRUSTRATION_RE.search(text) or _ALL_CAPS_RE.search(text):
        return "frustration"
    if _CONFIDENCE_RE.search(text):
        return "confidence"
    if _UNCERTAINTY_RE.search(text):
        return "uncertainty"
    return "neutral"


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
        sentiment = detect_sentiment(prompt)
        tool_input = {"prompt": scrubbed}
        obs = compress_observation("UserPrompt", tool_input, {}, "prompt_hook")
        obs["metadata"]["sentiment"] = sentiment
        with open(CAPTURE_QUEUE, "a") as f:
            f.write(json.dumps(obs) + "\n")
    except Exception:
        pass  # Capture failures must never crash the hook

    sys.exit(0)


if __name__ == "__main__":
    main()
