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
sys.path.insert(0, HOOKS_DIR)
from shared.context_compressor import compress_postcompact


def main():
    # Read stdin for session_id
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}

    wm_content = ""
    ws_content = ""
    for fname, var_name in [("working-memory.md", "wm"), ("working-summary.md", "ws")]:
        path = os.path.join(os.path.expanduser("~"), ".claude", "hooks", fname)
        try:
            with open(path) as f:
                content = f.read().strip()
                if var_name == "wm":
                    wm_content = content
                else:
                    ws_content = content
        except OSError:
            pass

    # DAG: inject conversation summary after compaction (Task 8 + Phase 2 Tasks 13, 15)
    dag_summary = ""
    try:
        from shared.dag import get_session_dag

        _sid = data.get("session_id", "main")
        dag = get_session_dag(_sid)
        summary = dag.build_summary()
        if summary:
            # Task 15: enrich with related memory hits
            try:
                from shared.dag_memory import enrich_summary_with_memory

                summary = enrich_summary_with_memory(summary, _sid)
            except Exception:
                pass
            dag_summary = summary
            # Task 13: save summary to memory for cross-session persistence
            try:
                from shared.dag_memory import save_compaction_summary

                save_compaction_summary(_sid)
            except Exception:
                pass
    except Exception:
        pass  # Fail-open

    # Print compressed output (Task 4: context compression)
    compressed = compress_postcompact(wm_content, ws_content, dag_summary)
    if compressed:
        print(compressed)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[PostCompact] Warning: {e}", file=sys.stderr)
    finally:
        sys.exit(0)
