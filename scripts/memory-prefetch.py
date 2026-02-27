#!/usr/bin/env python3
"""Pre-fetch relevant memories for a task executor prompt.

Queries the FTS5 index (read-only, safe for concurrent access) to find
memories relevant to a task's name and files. Returns formatted context
suitable for injection into an executor's prompt.

Usage: python3 memory-prefetch.py "task name" ["file1.py" "file2.py" ...]

Output: Formatted text block with top 5 relevant memories, or empty string
if no relevant memories found. Exit code always 0 (fail-open).
"""

import os
import re
import sqlite3
import sys

FTS5_DB = os.path.join(os.path.expanduser("~"), "data", "memory", "fts5_index.db")
MAX_RESULTS = 5


def sanitize_fts_query(query):
    """Strip FTS5 special characters to prevent query crashes."""
    # Remove FTS5 operators
    cleaned = re.sub(r'[*"()]', ' ', query)
    # Remove standalone AND/OR/NOT/NEAR
    cleaned = re.sub(r'\b(AND|OR|NOT|NEAR)\b', ' ', cleaned, flags=re.IGNORECASE)
    # Collapse whitespace
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned


def search_fts5(query, top_k=MAX_RESULTS):
    """Read-only FTS5 keyword search."""
    if not os.path.exists(FTS5_DB):
        return []

    sanitized = sanitize_fts_query(query)
    if not sanitized:
        return []

    try:
        # Open in read-only mode — safe for concurrent access
        conn = sqlite3.connect(f"file:{FTS5_DB}?mode=ro", uri=True)
        rows = conn.execute("""
            SELECT l.memory_id, f.preview, l.tags, l.timestamp
            FROM mem_fts f
            JOIN mem_lookup l ON l.fts_rowid = f.rowid
            WHERE mem_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (sanitized, top_k)).fetchall()
        conn.close()
        return rows
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return []


def format_results(rows):
    """Format FTS5 results as context block for executor prompt."""
    if not rows:
        return ""

    lines = ["## Relevant Memories (pre-fetched)", ""]
    for i, row in enumerate(rows, 1):
        memory_id, preview, tags, timestamp = row
        # Truncate preview to 200 chars
        preview_short = preview[:200] if preview else "(no preview)"
        lines.append(f"{i}. [{tags or 'untagged'}] {preview_short}")
    lines.append("")
    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        sys.exit(0)  # No query — fail-open, return empty

    task_name = sys.argv[1]
    file_names = sys.argv[2:] if len(sys.argv) > 2 else []

    # Build search query from task name + file basenames
    query_parts = [task_name]
    for f in file_names[:3]:  # Limit to 3 files to avoid overly broad search
        basename = os.path.splitext(os.path.basename(f))[0]
        if basename and basename not in task_name.lower():
            query_parts.append(basename)

    query = " ".join(query_parts)
    rows = search_fts5(query, MAX_RESULTS)
    output = format_results(rows)

    if output:
        print(output)


if __name__ == "__main__":
    main()
