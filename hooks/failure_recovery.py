#!/usr/bin/env python3
"""PostToolUseFailure hook — auto-triage tool failures.

Provides contextual recovery hints and tracks consecutive failures.
Fail-open: always exits 0.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from shared.state import load_state, save_state


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return

    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {})
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except Exception:
            tool_input = {}

    tool_response = payload.get("tool_response", "")
    if isinstance(tool_response, dict):
        tool_response = json.dumps(tool_response)

    session_id = payload.get("session_id", "main")
    state = load_state(session_id=session_id)

    # Edit failures: hint about old_string uniqueness
    if tool_name == "Edit" and ("not unique" in tool_response or "old_string" in tool_response):
        print("[RECOVERY] Edit failed — old_string not unique in file. "
              "Use more surrounding context to make it unique, or use replace_all.",
              file=sys.stderr)

    # Bash failures: track consecutive failures
    if tool_name == "Bash":
        count = state.get("consecutive_bash_failures", 0) + 1
        state["consecutive_bash_failures"] = count
        if count >= 3:
            print(f"[RECOVERY] {count} consecutive Bash failures — "
                  "consider a different approach or check the command.",
                  file=sys.stderr)
        save_state(state, session_id=session_id)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
