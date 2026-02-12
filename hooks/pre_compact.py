#!/usr/bin/env python3
"""Self-Healing Claude Framework — PreCompact Hook

Fires before context window compression. Saves a snapshot of the current
enforcer state to the capture queue so important context is not lost.

FAIL-OPEN: Entire script wrapped in try/except, always exits 0.
"""

import hashlib
import json
import os
import sys
import time
from datetime import datetime

CAPTURE_QUEUE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".capture_queue.jsonl")


def main():
    # Read session data from stdin
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError, ValueError):
        data = {}

    session_id = data.get("session_id", "main")

    # Load enforcer state for this session
    sys.path.insert(0, os.path.dirname(__file__))
    from shared.state import load_state
    state = load_state(session_id=session_id)

    # Extract snapshot metrics
    tool_call_count = state.get("tool_call_count", 0)
    files_read_count = len(state.get("files_read", []))
    pending_count = len(state.get("pending_verification", []))
    verified_count = len(state.get("verified_fixes", []))
    elapsed = time.time() - state.get("session_start", time.time())

    # Log snapshot to stderr (visible in Claude Code hook output)
    print(
        f"[PreCompact] Snapshot before compaction: "
        f"{tool_call_count} tool calls, "
        f"{files_read_count} files read, "
        f"{pending_count} pending verification, "
        f"{verified_count} verified fixes, "
        f"{elapsed:.0f}s elapsed",
        file=sys.stderr,
    )

    # Build observation document for capture queue
    document = (
        f"PreCompact snapshot: {tool_call_count} tool calls, "
        f"{files_read_count} files read, "
        f"{pending_count} pending, "
        f"{verified_count} verified, "
        f"{elapsed:.0f}s elapsed"
    )

    timestamp = datetime.now().isoformat()
    obs_id = hashlib.sha256(document.encode()).hexdigest()[:16]

    metadata = {
        "tool_name": "PreCompact",
        "session_id": session_id,
        "session_time": time.time(),
        "timestamp": timestamp,
        "has_error": "false",
        "error_pattern": "",
    }

    observation = {
        "document": document,
        "metadata": metadata,
        "id": obs_id,
    }

    # Append to capture queue
    with open(CAPTURE_QUEUE, "a") as f:
        f.write(json.dumps(observation) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[PreCompact] Warning: {e}", file=sys.stderr)
    finally:
        sys.exit(0)
