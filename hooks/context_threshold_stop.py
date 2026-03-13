#!/usr/bin/env python3
"""Stop hook — context threshold verification + user-facing warning.

Fires after every Claude response. Checks if context threshold was
crossed this turn and whether a working summary was written.

Three states:
1. First fire (summary written): "[## WARNING ## {pct}% CONTEXT] Summary ({N} chars). Context preserved for /clear!"
2. First fire (summary NOT written): "[!! WARNING !!] Context at {pct}% but no summary written!"
3. Subsequent turns (/clear not run): "[# WARNING #] /clear not run! {pct}% CONTEXT!"

Prints to stderr (visible in user's terminal).
Fail-open: always exits 0.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

SUMMARY_PATH = os.path.join(
    os.path.expanduser("~"), ".claude", "rules", "working-summary.md"
)
MIN_SUMMARY_CHARS = 2000
SNAPSHOT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), ".statusline_snapshot.json"
)


def _get_summary_size():
    try:
        if os.path.exists(SUMMARY_PATH):
            return os.path.getsize(SUMMARY_PATH)
        return 0
    except Exception:
        return 0


def _get_context_pct():
    try:
        if os.path.exists(SNAPSHOT_PATH):
            with open(SNAPSHOT_PATH) as f:
                return json.load(f).get("context_pct", 0)
        return 0
    except Exception:
        return 0


def check_and_warn(op_state, summary_size=None, context_pct=None):
    """Check threshold + summary state, print warning to stderr.

    Args:
        op_state: Operation tracker state dict (read + mutated).
        summary_size: Override for testing (bytes). None = read from file.
        context_pct: Override for testing. None = read from snapshot.
    """
    if not op_state.get("summary_threshold_fired"):
        return

    pct = context_pct if context_pct is not None else _get_context_pct()
    size = summary_size if summary_size is not None else _get_summary_size()

    # If context dropped below threshold, /clear was run — reset and stop
    if pct < _CONTEXT_THRESHOLD_PCT:
        op_state["summary_threshold_fired"] = False
        op_state["context_warning_shown"] = False
        op_state["summary_warning_shown"] = False
        return

    # Subsequent turns: /clear not run reminder
    if op_state.get("summary_warning_shown"):
        print(
            f"[# WARNING #] /clear not run! {pct}% CONTEXT!",
            file=sys.stderr,
        )
        return

    # First fire: summary verification
    if size >= MIN_SUMMARY_CHARS:
        print(
            f"[## WARNING ## {pct}% CONTEXT] Summary ({size:,} chars). "
            f"Context preserved for /clear!",
            file=sys.stderr,
        )
        op_state["summary_warning_shown"] = True
    else:
        print(
            f"[!! WARNING !!] Context at {pct}% but no summary written!",
            file=sys.stderr,
        )


_CONTEXT_THRESHOLD_PCT = 65


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}

    session_id = payload.get("session_id", "main")

    try:
        from shared.operation_tracker import OperationTracker

        op_tracker = OperationTracker(session_id)
        op_state = op_tracker.get_state()
        check_and_warn(op_state)
        op_tracker._save_state(op_state)
    except Exception:
        pass  # Fail-open


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
