"""Memory injection and sideband timestamp for boot sequence."""
import json
import os
import time

from shared.chromadb_socket import (
    is_worker_available as socket_available,
    query as _default_query,
    count as _default_count,
    flush_queue as socket_flush,
    remember as socket_remember,
    WorkerUnavailable,
)

SIDEBAND_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".memory_last_queried")


def _write_sideband_timestamp():
    """Write fresh sideband timestamp (auto-injection counts as querying memory)."""
    try:
        tmp = SIDEBAND_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"timestamp": time.time()}, f)
        os.replace(tmp, SIDEBAND_FILE)
    except OSError:
        pass


def inject_memories_via_socket(handoff_content, live_state, _socket_count=None, _socket_query=None):
    """Query memories via UDS socket for boot dashboard injection.

    _socket_count and _socket_query are injectable for test patching via the shim.
    When called directly (from boot_pkg.orchestrator), defaults are used.
    """
    _count = _socket_count if _socket_count is not None else _default_count
    _query = _socket_query if _socket_query is not None else _default_query

    try:
        cnt = _count("knowledge")
        if cnt == 0:
            return []
    except (WorkerUnavailable, RuntimeError):
        return []

    # Build search query from handoff context
    query_parts = []
    project = live_state.get("project", "")
    if project:
        query_parts.append(project)
    feature = live_state.get("feature", "")
    if feature:
        query_parts.append(feature)
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
        results = _query(
            "knowledge", [search_query], n_results=min(5, cnt),
            include=["metadatas", "distances"],
        )
    except (WorkerUnavailable, RuntimeError):
        return []

    if not results or not results.get("ids") or not results["ids"][0]:
        return []

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
        display = preview[:58]
        if len(preview) > 58:
            display += ".."
        injected.append(f"[{mid[:8]}] {display}")
    return injected
