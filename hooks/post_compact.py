#!/usr/bin/env python3
"""PostCompact hook — inject working-memory and working-summary after compaction.

Fires after context window compression completes. Prints the content of
working-memory.md and working-summary.md to stdout so Claude Code includes
them in the next conversation turn (as system-reminder context).

FAIL-OPEN: Always exits 0.
"""

import json
import os
import sys

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))


def main():
    # Read stdin for session_id
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}

    for fname in ["working-memory.md", "working-summary.md"]:
        path = os.path.join(os.path.expanduser("~"), ".claude", "rules", fname)
        try:
            with open(path) as f:
                content = f.read().strip()
                if content:
                    print(content)
        except OSError:
            pass  # File missing or unreadable — skip silently

    # DAG: inject conversation summary after compaction (Task 8)
    try:
        sys.path.insert(0, HOOKS_DIR)
        from shared.dag import get_session_dag

        dag = get_session_dag(data.get("session_id", "main"))
        summary = dag.build_summary()
        if summary:
            print(f"<dag-context>\n{summary}\n</dag-context>")
    except Exception:
        pass  # Fail-open


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[PostCompact] Warning: {e}", file=sys.stderr)
    finally:
        sys.exit(0)
