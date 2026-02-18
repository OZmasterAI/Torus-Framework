#!/usr/bin/env python3
"""Terminal History — JSONL Session Indexer

Parses Claude Code JSONL session files and indexes user/assistant text
into the FTS5 database.

Usage:
    python3 indexer.py                        # Bulk index all sessions
    python3 indexer.py --session <uuid>       # Index single session
"""

import argparse
import glob
import json
import os
import sys

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _PLUGIN_DIR)

from db import init_db, log_entry, is_session_indexed, mark_session_indexed

SESSIONS_DIR = os.path.join(
    os.path.expanduser("~"), ".claude", "projects", "-home-crab--claude"
)
DB_PATH = os.path.join(_PLUGIN_DIR, "terminal_history.db")


def _extract_text(record):
    """Parse a JSONL record, return (role, text, timestamp, slug) or None.

    Indexes:
    - type="user": string content only (skip tool_result arrays)
    - type="assistant": text blocks only (skip tool_use blocks)
    Skips: progress, queue-operation, system records
    """
    rec_type = record.get("type", "")
    if rec_type in ("progress", "queue-operation", "system"):
        return None

    message = record.get("message", {})
    role = message.get("role", "")
    if role not in ("user", "assistant"):
        return None

    timestamp = record.get("timestamp", "")
    content = message.get("content", "")

    if isinstance(content, str):
        text = content.strip()
        if not text:
            return None
        return (role, text, timestamp, "")

    if isinstance(content, list):
        parts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type", "")
            # For user messages: only text blocks (skip tool_result)
            # For assistant messages: only text blocks (skip tool_use)
            if block_type == "text":
                t = block.get("text", "").strip()
                if t:
                    parts.append(t)
        if not parts:
            return None
        return (role, "\n".join(parts), timestamp, "")

    return None


def index_session(db_path, jsonl_path):
    """Index one session file. Returns number of records indexed."""
    session_id = os.path.splitext(os.path.basename(jsonl_path))[0]

    if is_session_indexed(db_path, session_id):
        return 0

    count = 0
    try:
        with open(jsonl_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                extracted = _extract_text(record)
                if extracted is None:
                    continue

                role, text, timestamp, slug = extracted
                log_entry(db_path, session_id, role, text, timestamp, slug)
                count += 1
    except (OSError, IOError) as e:
        print(f"  Error reading {jsonl_path}: {e}", file=sys.stderr)
        return 0

    if count > 0:
        mark_session_indexed(db_path, session_id, count)

    return count


def bulk_index(db_path):
    """Index all session JSONL files. Skips already-indexed sessions."""
    pattern = os.path.join(SESSIONS_DIR, "*.jsonl")
    files = sorted(glob.glob(pattern))

    if not files:
        print(f"No JSONL files found in {SESSIONS_DIR}")
        return

    total_sessions = 0
    total_records = 0
    skipped = 0

    for filepath in files:
        session_id = os.path.splitext(os.path.basename(filepath))[0]
        if is_session_indexed(db_path, session_id):
            skipped += 1
            continue

        count = index_session(db_path, filepath)
        if count > 0:
            total_sessions += 1
            total_records += count
            print(f"  Indexed {session_id[:12]}... ({count} records)")

    print(f"\nDone: {total_sessions} new sessions, {total_records} records indexed "
          f"({skipped} already indexed)")


def main():
    parser = argparse.ArgumentParser(description="Index terminal session history")
    parser.add_argument("--session", help="Index a single session UUID")
    parser.add_argument("--db", default=DB_PATH, help="Database path")
    args = parser.parse_args()

    init_db(args.db)

    if args.session:
        jsonl_path = os.path.join(SESSIONS_DIR, f"{args.session}.jsonl")
        if not os.path.isfile(jsonl_path):
            print(f"Session file not found: {jsonl_path}", file=sys.stderr)
            sys.exit(1)
        count = index_session(args.db, jsonl_path)
        print(f"Indexed {count} records from session {args.session[:12]}...")
    else:
        bulk_index(args.db)


if __name__ == "__main__":
    main()
