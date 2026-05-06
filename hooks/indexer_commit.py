#!/usr/bin/env python3
"""PostToolUse hook: incremental re-index after git commit.

Watches for Bash tool calls containing 'git commit', then runs
an incremental build to update the code graph in SurrealDB.

Fail-open: always exits 0.  Indexing failures must never block work.
"""

import json
import os
import sys

from indexer.schema import connect_code_graph, init_code_tables
from indexer.build import incremental_build, get_changed_files


def _handle_event(event):
    """Process a PostToolUse hook event. Returns True if indexing triggered, False otherwise.

    This function is the testable core of the hook. The __main__ block
    handles stdin parsing and sys.exit.
    """
    try:
        if not isinstance(event, dict):
            return False

        tool_name = event.get("tool_name", "")
        if tool_name != "Bash":
            return False

        command = event.get("tool_input", {}).get("command", "")
        if "git commit" not in command:
            return False

        # Determine project root from env or cwd
        project_root = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
        project_name = os.path.basename(project_root)

        db = connect_code_graph()
        init_code_tables(db)

        changed = get_changed_files(project_root)
        if changed:
            incremental_build(db, project_root, project_name, changed)

        return True

    except Exception:
        return False


if __name__ == "__main__":
    try:
        event = json.loads(sys.stdin.read())
        _handle_event(event)
    except Exception:
        pass
    sys.exit(0)
