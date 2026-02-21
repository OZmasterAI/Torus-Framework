"""Gate 13: WORKSPACE ISOLATION (Tier 2 — Quality)

Prevents two agents in a team from editing the same file simultaneously.
Uses a shared claims file (.file_claims.json) with fcntl.flock for safe
concurrent access.

Only fires on Edit/Write/NotebookEdit tools and only when session_id != "main"
(solo work is exempt). Stale claims (>2h) are ignored and cleaned up.

Tier 2 (non-safety): gate crash = warn + continue, not block.
"""
import fcntl
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.gate_result import GateResult

GATE_NAME = "GATE 13: WORKSPACE ISOLATION"
CLAIMS_FILE = os.path.join(os.path.dirname(__file__), "..", ".file_claims.json")
STALE_THRESHOLD = 1800  # 30 minutes (reduced from 2h to prevent long stale claim blocks)

WATCHED_TOOLS = {"Edit", "Write", "NotebookEdit"}


def _read_claims():
    """Read claims file with flock. Returns dict of claims."""
    if not os.path.exists(CLAIMS_FILE):
        return {}
    try:
        with open(CLAIMS_FILE, "r") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            try:
                data = json.load(f)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError, ValueError):
        return {}


def _clean_stale_claims(claims):
    """Remove claims older than STALE_THRESHOLD. Returns cleaned dict."""
    now = time.time()
    cleaned = {}
    for filepath, info in claims.items():
        if isinstance(info, dict) and (now - info.get("claimed_at", 0)) < STALE_THRESHOLD:
            cleaned[filepath] = info
    return cleaned


def check(tool_name, tool_input, state, event_type="PreToolUse"):
    """Check if another agent already has a claim on the target file."""
    if event_type != "PreToolUse":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if tool_name not in WATCHED_TOOLS:
        return GateResult(blocked=False, gate_name=GATE_NAME)

    session_id = state.get("_session_id", "main")

    # Solo work is exempt — no need for workspace isolation
    if session_id == "main":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Get the target file path
    file_path = tool_input.get("file_path", "") or tool_input.get("notebook_path", "")
    if not file_path:
        return GateResult(blocked=False, gate_name=GATE_NAME)

    file_path = os.path.normpath(file_path)

    try:
        claims = _read_claims()
        claims = _clean_stale_claims(claims)

        claim = claims.get(file_path)
        if claim and isinstance(claim, dict):
            claimed_by = claim.get("session_id", "")
            claimed_at = claim.get("claimed_at", 0)
            age_seconds = time.time() - claimed_at

            # Claimed by a DIFFERENT session and not stale
            if claimed_by and claimed_by != session_id and age_seconds < STALE_THRESHOLD:
                age_minutes = int(age_seconds / 60)
                msg = (
                    f"[{GATE_NAME}] BLOCKED: File '{file_path}' is currently being "
                    f"edited by session '{claimed_by}' (claimed {age_minutes}m ago). "
                    f"Wait for the other agent to finish or work on a different file."
                )
                return GateResult(
                    blocked=True,
                    gate_name=GATE_NAME,
                    message=msg,
                    severity="warn",
                )

        # Unclaimed, claimed by self, or stale — allow
        return GateResult(blocked=False, gate_name=GATE_NAME)

    except Exception as e:
        # Tier 2: crash = warn + continue, never block
        msg = f"[{GATE_NAME}] WARNING: Gate crashed (non-blocking): {e}"
        print(msg, file=sys.stderr)
        return GateResult(
            blocked=False,
            gate_name=GATE_NAME,
            message=msg,
            severity="warn",
        )
