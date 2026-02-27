#!/usr/bin/env python3
"""Terminal History — JSONL Session Indexer

Parses Claude Code JSONL session files and indexes user/assistant text
into the FTS5 database. Supports inherit+derive tagging.

Usage:
    python3 indexer.py                        # Bulk index all sessions
    python3 indexer.py --session <uuid>       # Index single session
    python3 indexer.py --retag                 # Re-tag all indexed sessions
"""

import argparse
import glob
import json
import os
import re
import sqlite3
import sys

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _PLUGIN_DIR)

from db import init_db, log_entry, is_session_indexed, mark_session_indexed, update_session_tags

SESSIONS_DIR = os.path.join(
    os.path.expanduser("~"), ".claude", "projects", "-home-$USER--claude"
)
DB_PATH = os.path.join(_PLUGIN_DIR, "terminal_history.db")
FTS5_MIRROR_PATH = os.path.join(os.path.expanduser("~"), "data", "memory", "fts5_index.db")

# Derive rules: pattern → tag
_DERIVE_RULES = [
    (re.compile(r"\b(error|traceback|failed|exception|crash|broke)\b", re.I), "type:error"),
    (re.compile(r"\b(fix|fixed|resolved|patched|workaround)\b", re.I), "type:fix"),
    (re.compile(r"\b(test|passed|assert|pytest|unittest|1\d+ passed)\b", re.I), "area:testing"),
    (re.compile(r"\b(gate|enforcer|hook|PreToolUse|PostToolUse)\b", re.I), "area:framework"),
    (re.compile(r"\b(chromadb|chroma|collection|hnsw|embedding)\b", re.I), "chromadb"),
    (re.compile(r"\b(memory|remember_this|search_knowledge|observation)\b", re.I), "area:memory-system"),
    (re.compile(r"\b(telegram|bot|tg_|msg_log)\b", re.I), "telegram"),
    (re.compile(r"\b(git|commit|push|branch|merge|rebase)\b", re.I), "area:git"),
    (re.compile(r"\b(fts5|sqlite|database|sql)\b", re.I), "fts5"),
    (re.compile(r"\b(deploy|systemd|service|docker|nginx)\b", re.I), "area:infra"),
]


def _derive_tags(text):
    """Derive tags from text content using keyword patterns."""
    tags = set()
    for pattern, tag in _DERIVE_RULES:
        if pattern.search(text):
            tags.add(tag)
    return tags


def _inherit_tags_from_fts5_mirror(session_timestamps):
    """Look up FTS5 mirror for ChromaDB memories matching session time range.

    Returns (set of inherited tags, list of memory IDs).
    """
    if not os.path.isfile(FTS5_MIRROR_PATH):
        return set(), []
    if not session_timestamps:
        return set(), []

    # Get time range from session timestamps
    ts_sorted = sorted(session_timestamps)
    ts_start = ts_sorted[0].replace("Z", "").split(".")[0]
    ts_end = ts_sorted[-1].replace("Z", "").split(".")[0]

    try:
        conn = sqlite3.connect(FTS5_MIRROR_PATH)
        cursor = conn.execute(
            "SELECT memory_id, tags FROM mem_lookup "
            "WHERE substr(timestamp, 1, 19) BETWEEN ? AND ?",
            (ts_start, ts_end),
        )
        inherited_tags = set()
        memory_ids = []
        for row in cursor:
            memory_ids.append(row[0])
            if row[1]:
                for tag in row[1].split(","):
                    tag = tag.strip()
                    if tag:
                        inherited_tags.add(tag)
        conn.close()
        return inherited_tags, memory_ids
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return set(), []


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
    all_text = []
    all_timestamps = []
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
                all_text.append(text)
                if timestamp:
                    all_timestamps.append(timestamp)
                count += 1
    except (OSError, IOError) as e:
        print(f"  Error reading {jsonl_path}: {e}", file=sys.stderr)
        return 0

    if count > 0:
        mark_session_indexed(db_path, session_id, count)
        # Inherit + derive tags
        _apply_tags(db_path, session_id, all_text, all_timestamps)

    return count


def _apply_tags(db_path, session_id, all_text, all_timestamps):
    """Apply inherited + derived tags to a session's records."""
    # Step 1: Inherit from ChromaDB memories in this session's time range
    inherited_tags, memory_ids = _inherit_tags_from_fts5_mirror(all_timestamps)

    # Step 2: Derive from text content
    derived_tags = set()
    for text in all_text:
        derived_tags.update(_derive_tags(text))

    # Combine: inherit first, derive fills gaps
    all_tags = inherited_tags | derived_tags
    tags_str = ",".join(sorted(all_tags)) if all_tags else ""
    linked_ids_str = ",".join(memory_ids) if memory_ids else ""

    # Update all records in this session
    if tags_str or linked_ids_str:
        update_session_tags(db_path, session_id, tags_str, linked_ids_str)


def retag_all(db_path):
    """Re-tag all already-indexed sessions (inherit + derive)."""
    pattern = os.path.join(SESSIONS_DIR, "*.jsonl")
    files = sorted(glob.glob(pattern))

    retagged = 0
    for filepath in files:
        session_id = os.path.splitext(os.path.basename(filepath))[0]
        if not is_session_indexed(db_path, session_id):
            continue

        all_text = []
        all_timestamps = []
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
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
                    _, text, timestamp, _ = extracted
                    all_text.append(text)
                    if timestamp:
                        all_timestamps.append(timestamp)
        except (OSError, IOError):
            continue

        if all_text:
            _apply_tags(db_path, session_id, all_text, all_timestamps)
            retagged += 1

    print(f"Re-tagged {retagged} sessions")


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
    parser.add_argument("--retag", action="store_true", help="Re-tag all indexed sessions")
    parser.add_argument("--db", default=DB_PATH, help="Database path")
    args = parser.parse_args()

    init_db(args.db)

    if args.retag:
        retag_all(args.db)
    elif args.session:
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
