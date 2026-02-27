#!/usr/bin/env python3
"""One-shot script to apply all remaining chromadb→lancedb renames.

Edits are mechanical string replacements — zero logic changes.
Run once and delete.
"""
import sys

edits = [
    # web scripts - from shared import pattern
    ("skills/web/scripts/search.py", "from shared import chromadb_socket", "from shared import memory_socket"),
    ("skills/web/scripts/index.py", "from shared import chromadb_socket", "from shared import memory_socket"),
    ("skills/web/scripts/list.py", "from shared import chromadb_socket", "from shared import memory_socket"),

    # Also need to update usage of chromadb_socket.X in web_search_server.py
    ("hooks/web_search_server.py", "chromadb_socket.query(", "memory_socket.query("),

    # web/scripts usage updates
    ("skills/web/scripts/search.py", "chromadb_socket.query(", "memory_socket.query("),
    ("skills/web/scripts/delete.py", "chromadb_socket.get(", "memory_socket.get("),
    ("skills/web/scripts/delete.py", "chromadb_socket.delete(", "memory_socket.delete("),
    ("skills/web/scripts/index.py", "chromadb_socket.get(", "memory_socket.get("),
    ("skills/web/scripts/index.py", "chromadb_socket.upsert(", "memory_socket.upsert("),
    ("skills/web/scripts/list.py", "chromadb_socket.get(", "memory_socket.get("),
    ("skills/web/scripts/list.py", "chromadb_socket.count(", "memory_socket.count("),

    # Hardcoded socket paths
    ("hooks/tracker_pkg/mentor_memory.py", '".chromadb.sock"', '".memory.sock"'),
    ("hooks/pre_compact.py", '".chromadb_socket"', '".memory.sock"'),

    # health_monitor cosmetic
    ("hooks/shared/health_monitor.py", '"/home/crab/.claude/hooks/.chromadb.sock"', '"/home/crab/.claude/hooks/.memory.sock"'),
    ("hooks/shared/health_monitor.py", 'chromadb_socket import failed:', 'memory_socket import failed:'),
    ("hooks/shared/health_monitor.py", "Check whether the ChromaDB UDS worker", "Check whether the UDS worker"),

    # skill_mapper
    ("hooks/shared/skill_mapper.py", '"chromadb_socket": "ChromaDB socket communication"', '"memory_socket": "Memory socket communication"'),

    # Cosmetic comments
    ("hooks/boot_pkg/orchestrator.py", "# Check if UDS worker (memory_server.py) is available for ChromaDB access", "# Check if UDS worker (memory_server.py) is available"),
    ("hooks/boot_pkg/orchestrator.py", "# Watchdog: detect ChromaDB truncation/shrinkage early", "# Watchdog: detect database truncation/shrinkage early"),

    ("hooks/session_end.py", "2. Flush the capture queue to ChromaDB (observations collection)", "2. Flush the capture queue to LanceDB (observations collection)"),
    ("hooks/session_end.py", "# Try UDS socket flush (memory_server.py handles the actual ChromaDB upsert)", "# Try UDS socket flush (memory_server.py handles the actual LanceDB upsert)"),
    ("hooks/session_end.py", 'Backup ChromaDB if DB changed since last backup', 'Backup database if DB changed since last backup'),

    ("hooks/statusline.py", "# Cache memory count for 60 seconds to avoid cold-starting ChromaDB on every render", "# Cache memory count for 60 seconds to avoid cold-starting LanceDB on every render"),
    ("hooks/statusline.py", "Memory accessible (15%) \u2014 ChromaDB has memories", "Memory accessible (15%) \u2014 LanceDB has memories"),

    # memory_maintenance docstrings
    ("hooks/shared/memory_maintenance.py", "Provides ongoing health monitoring for the ChromaDB knowledge collection", "Provides ongoing health monitoring for the LanceDB knowledge collection"),
    ("hooks/shared/memory_maintenance.py", "- Uses the UDS socket client (chromadb_socket.py) so it never creates a", "- Uses the UDS socket client (memory_socket.py) so it never creates a"),
    ("hooks/shared/memory_maintenance.py", "Fetch all entries from a ChromaDB collection via the UDS socket.", "Fetch all entries from a LanceDB collection via the UDS socket."),
]


def main():
    success = 0
    skipped = 0
    for filepath, old, new in edits:
        try:
            with open(filepath, "r") as f:
                content = f.read()
            if old not in content:
                print(f"  SKIP {filepath}: not found: {old[:60]}...")
                skipped += 1
                continue
            content = content.replace(old, new, 1)
            with open(filepath, "w") as f:
                f.write(content)
            success += 1
        except Exception as e:
            print(f"  FAIL {filepath}: {e}")
            skipped += 1

    print(f"\n{success} edits applied, {skipped} skipped")
    return 0 if skipped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
