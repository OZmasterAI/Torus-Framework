#!/usr/bin/env python3
"""Self-Healing Claude Framework — Boot Sequence

Runs on SessionStart to:
1. Load handoff context from previous session
2. Load live state
3. Inject relevant memories (auto-satisfies Gate 4)
4. Display a dashboard with project status + memory context
5. Reset enforcement state for new session
6. Flush stale capture queue

This ensures every session starts with full context rather than amnesia.
"""

import json
import os
import sys
import time
from datetime import datetime

# Add hooks dir to path for shared imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from shared.state import cleanup_all_states

CLAUDE_DIR = os.path.join(os.path.expanduser("~"), ".claude")
HANDOFF_FILE = os.path.join(CLAUDE_DIR, "HANDOFF.md")
LIVE_STATE_FILE = os.path.join(CLAUDE_DIR, "LIVE_STATE.json")
MEMORY_DIR = os.path.join(os.path.expanduser("~"), "data", "memory")
SIDEBAND_FILE = os.path.join(os.path.dirname(__file__), ".memory_last_queried")


def read_file(path):
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        return None


def extract_summary(handoff_content):
    """Extract the first meaningful line from HANDOFF.md as a summary."""
    if not handoff_content:
        return "No handoff file found"
    for line in handoff_content.split("\n"):
        line = line.strip()
        if line and not line.startswith("#") and not line.startswith("---"):
            return line[:70]
    return "Handoff exists but no summary found"


def extract_session_number(handoff_content):
    """Try to find session number from handoff."""
    if not handoff_content:
        return "?"
    for line in handoff_content.split("\n"):
        if "session" in line.lower() and any(c.isdigit() for c in line):
            digits = "".join(c for c in line if c.isdigit())
            if digits:
                return digits[:4]
    return "?"


def load_live_state():
    content = read_file(LIVE_STATE_FILE)
    if content:
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {}
    return {}


def reset_enforcement_state():
    """Reset all gate enforcement state files for a new session.

    Cleans up per-agent state files from the previous session (each team member
    had its own state_*.json file) and the legacy shared state.json.
    The new session's main agent will create its own state file on first tool use.
    """
    cleanup_all_states()


def inject_memories(handoff_content, live_state, knowledge_col):
    """Query ChromaDB for memories relevant to the current handoff context.

    Extracts project name, active tasks, and "What's Next" from handoff,
    then runs a semantic search to find the most relevant memories.

    Returns a list of compact preview lines for the dashboard.
    """
    if knowledge_col is None:
        return []

    count = knowledge_col.count()
    if count == 0:
        return []

    # Build search query from handoff context
    query_parts = []

    # Project name
    project = live_state.get("project", "")
    if project:
        query_parts.append(project)

    # Active feature
    feature = live_state.get("feature", "")
    if feature:
        query_parts.append(feature)

    # What's Next section from handoff
    if handoff_content:
        in_next = False
        for line in handoff_content.split("\n"):
            stripped = line.strip()
            if "what's next" in stripped.lower() or "whats next" in stripped.lower():
                in_next = True
                continue
            if in_next:
                if stripped.startswith("#") or stripped.startswith("---"):
                    break
                if stripped:
                    query_parts.append(stripped[:100])

    if not query_parts:
        query_parts.append("recent session activity framework")

    search_query = " ".join(query_parts)[:500]

    try:
        results = knowledge_col.query(
            query_texts=[search_query],
            n_results=min(5, count),
            include=["metadatas", "distances"],
        )
    except Exception:
        return []

    if not results or not results.get("ids") or not results["ids"][0]:
        return []

    # Filter by relevance threshold (cosine distance < 0.7 means relevance > 0.3)
    injected = []
    ids = results["ids"][0]
    metas = results["metadatas"][0] if results.get("metadatas") else []
    distances = results["distances"][0] if results.get("distances") else []

    for i, mid in enumerate(ids):
        distance = distances[i] if i < len(distances) else 1.0
        relevance = 1 - distance
        if relevance < 0.3:
            continue

        meta = metas[i] if i < len(metas) else {}
        preview = meta.get("preview", "(no preview)")
        # Truncate preview to fit dashboard width
        display = preview[:58]
        if len(preview) > 58:
            display += ".."
        injected.append(f"[{mid[:8]}] {display}")

    return injected


def _write_sideband_timestamp():
    """Write fresh sideband timestamp (auto-injection counts as querying memory)."""
    try:
        tmp = SIDEBAND_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"timestamp": time.time()}, f)
        os.replace(tmp, SIDEBAND_FILE)
    except OSError:
        pass


def main():
    now = datetime.now()
    hour = now.hour
    day = now.strftime("%A")

    # Load context
    handoff = read_file(HANDOFF_FILE)
    live_state = load_live_state()
    session_num = extract_session_number(handoff)
    summary = extract_summary(handoff)

    # Time-based warnings
    time_warning = ""
    if 1 <= hour <= 5:
        time_warning = "  !! LATE NIGHT — Extra caution required !!"
    elif hour >= 22:
        time_warning = "  -- Late evening session --"

    # Project name from live state
    project_name = live_state.get("project", "Self-Healing Claude")
    active_tasks = live_state.get("active_tasks", [])

    # Gate count
    gates_dir = os.path.join(CLAUDE_DIR, "hooks", "gates")
    gate_count = 0
    if os.path.isdir(gates_dir):
        gate_count = len([f for f in os.listdir(gates_dir) if f.startswith("gate_") and f.endswith(".py")])

    # Initialize ChromaDB client (shared for queue flush + memory injection)
    db = None
    knowledge_col = None
    try:
        import chromadb
        db = chromadb.PersistentClient(path=MEMORY_DIR)
        knowledge_col = db.get_or_create_collection(
            name="knowledge", metadata={"hnsw:space": "cosine"}
        )
    except Exception:
        pass  # Boot must never crash

    # Inject relevant memories
    injected = inject_memories(handoff, live_state, knowledge_col)

    # Build dashboard
    dashboard = f"""
+====================================================================+
|  {project_name:<20} | Session {session_num:<6} | {day} {hour:02d}:{now.minute:02d}             |
|====================================================================|
|  LAST SESSION: {summary:<53}|
|--------------------------------------------------------------------|
|  GATES ACTIVE: {gate_count:<3} | MEMORY: ~/data/memory/                     |
|--------------------------------------------------------------------|"""

    if time_warning:
        dashboard += f"\n|  {time_warning:<67}|"
        dashboard += "\n|--------------------------------------------------------------------|"

    if active_tasks:
        dashboard += "\n|  ACTIVE TASKS:                                                     |"
        for task in active_tasks[:3]:
            dashboard += f"\n|    - {task:<63}|"
        dashboard += "\n|--------------------------------------------------------------------|"

    if injected:
        dashboard += f"\n|  MEMORY CONTEXT ({len(injected)} relevant):{'':>42}|"
        for line in injected:
            dashboard += f"\n|    {line:<64}|"
        dashboard += "\n|--------------------------------------------------------------------|"

    dashboard += """
|  TIP: Query memory about your task before starting work.           |
+====================================================================+
"""

    # Print to stderr (Claude Code displays this as hook output)
    print(dashboard, file=sys.stderr)

    # Reset state
    reset_enforcement_state()

    # Flush stale capture queue from previous session (crash recovery)
    capture_queue = os.path.join(os.path.dirname(__file__), ".capture_queue.jsonl")
    try:
        if os.path.exists(capture_queue) and os.path.getsize(capture_queue) > 0:
            with open(capture_queue, "r") as f:
                lines = f.readlines()
            if lines:
                obs_col = db.get_or_create_collection(
                    name="observations", metadata={"hnsw:space": "cosine"}
                ) if db else None
                if obs_col:
                    docs, metas, ids = [], [], []
                    for line in lines:
                        try:
                            obs = json.loads(line.strip())
                            if "document" in obs and "id" in obs:
                                docs.append(obs["document"])
                                metas.append(obs.get("metadata", {}))
                                ids.append(obs["id"])
                        except (json.JSONDecodeError, KeyError):
                            continue
                    if docs:
                        obs_col.upsert(documents=docs, metadatas=metas, ids=ids)
                        flushed = len(docs)
                        print(f"  [BOOT] Flushed {flushed} stale observations from capture queue", file=sys.stderr)
                # Clear the queue file
                with open(capture_queue, "w") as f:
                    pass
    except Exception:
        pass  # Boot must never crash

    # Write sideband timestamp (auto-injection satisfies Gate 4)
    _write_sideband_timestamp()


if __name__ == "__main__":
    main()
