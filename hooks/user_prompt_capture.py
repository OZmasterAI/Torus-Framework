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
import hashlib
import time

# --- Detection patterns (ported from user_prompt_check.sh) ---

_CORRECTION_RE = re.compile(
    r'(^no,|wrong|actually,|that\'s not right|that\'s incorrect|try again)',
    re.IGNORECASE,
)

_FEATURE_REQ_RE = re.compile(
    r'(can you|i wish|is there a way|would it be possible)',
    re.IGNORECASE,
)

# Session-ending keywords — must be the primary intent, not incidental
# Matches: "bye", "done", "gn", "goodnight", "end session", "wrap up", "save progress"
# Avoids: "done with this file", "I'm done editing" (requires word boundary + short prompt or end-of-string)
_SESSION_END_RE = re.compile(
    r'(?:^|\s)(?:bye|goodbye|goodnight|gn|see ya|end session|wrap[ -]?up|save progress)(?:\s*[.!]*\s*$)',
    re.IGNORECASE,
)
# "done" alone or "i'm done" / "im done" / "we're done" — but NOT "done with X"
_DONE_RE = re.compile(
    r"(?:^(?:i'?m\s+|we'?re\s+)?done\s*[.!]*\s*$)",
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

# URL detection for auto-indexing into LanceDB web_pages
_URL_RE = re.compile(r'https?://[^\s<>"\')\]]+', re.IGNORECASE)


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

DEDUP_WINDOW = 30  # seconds — skip identical prompts within this window
_LAST_PROMPT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".prompt_last_hash")


def _is_duplicate_prompt(prompt_text):
    """Check if this prompt was captured within the dedup window."""
    try:
        prompt_hash = hashlib.sha256(prompt_text.encode()).hexdigest()[:16]
        now = time.time()
        if os.path.exists(_LAST_PROMPT_FILE):
            with open(_LAST_PROMPT_FILE) as f:
                data = json.load(f)
            if data.get("hash") == prompt_hash and now - data.get("ts", 0) < DEDUP_WINDOW:
                return True
        # Update last hash
        with open(_LAST_PROMPT_FILE, "w") as f:
            json.dump({"hash": prompt_hash, "ts": now}, f)
        return False
    except Exception:
        return False  # Fail-open


_INDEX_SCRIPT = os.path.join(
    os.path.expanduser("~"), ".claude", "skills", "web", "scripts", "index.py"
)


def _auto_index_urls(urls):
    """Index URLs into LanceDB web_pages in the background. Fail-silent."""
    import subprocess

    for url in urls:
        # Skip common non-page URLs (images, videos, API endpoints, etc.)
        lower = url.lower().rstrip("/")
        if any(lower.endswith(ext) for ext in (
            ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",
            ".mp4", ".mp3", ".wav", ".pdf", ".zip", ".tar.gz",
        )):
            continue

        try:
            subprocess.Popen(
                [sys.executable, _INDEX_SCRIPT, url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception:
            pass  # Fail-silent


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

    if _SESSION_END_RE.search(prompt) or _DONE_RE.search(prompt):
        print(
            "<session_ending>User appears to be ending the session. "
            "Run /wrap-up to save progress, update LIVE_STATE.json, and commit changes "
            "before the session ends.</session_ending>"
        )

    # --- Auto-index URLs into LanceDB web_pages ---

    try:
        urls = _URL_RE.findall(prompt)
        if urls:
            _auto_index_urls(urls)
    except Exception:
        pass  # Index failures must never crash the hook

    # --- Capture phase (append observation to queue) ---

    try:
        from shared.secrets_filter import scrub
        from shared.observation import compress_observation

        truncated = prompt[:200]
        scrubbed = scrub(truncated)

        # Skip duplicate prompts within dedup window
        if _is_duplicate_prompt(scrubbed):
            sys.exit(0)

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
