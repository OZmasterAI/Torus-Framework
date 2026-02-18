#!/usr/bin/env python3
"""Terminal History — Session End Hook

Called by hooks/session_end.py to index the just-finished session.
Fail-open: always exits 0.
"""

import json
import os
import sys

_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PLUGIN_DIR)

from db import init_db
from indexer import index_session, SESSIONS_DIR

DB_PATH = os.path.join(_PLUGIN_DIR, "terminal_history.db")


def main():
    try:
        # Try to get session_id from stdin JSON (hook protocol)
        session_id = None
        try:
            data = json.load(sys.stdin)
            session_id = data.get("session_id")
        except Exception:
            pass

        # Fallback: scan for most recently modified JSONL
        if not session_id:
            import glob
            pattern = os.path.join(SESSIONS_DIR, "*.jsonl")
            files = glob.glob(pattern)
            if files:
                latest = max(files, key=os.path.getmtime)
                session_id = os.path.splitext(os.path.basename(latest))[0]

        if not session_id:
            sys.exit(0)

        jsonl_path = os.path.join(SESSIONS_DIR, f"{session_id}.jsonl")
        if not os.path.isfile(jsonl_path):
            sys.exit(0)

        init_db(DB_PATH)
        count = index_session(DB_PATH, jsonl_path)
        if count > 0:
            print(f"[TERMINAL_HISTORY] Indexed {count} records from session {session_id[:12]}...",
                  file=sys.stderr)
    except Exception as e:
        print(f"[TERMINAL_HISTORY] Error (non-fatal): {e}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
