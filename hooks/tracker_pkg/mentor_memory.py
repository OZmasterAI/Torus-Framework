"""Memory Mentor (Module E) — historical pattern matching via UDS.

Standalone module. Queries the memory system via Unix Domain Socket
for historical context relevant to the current tool call.
Called from orchestrator.py with the mentor_memory toggle.
Completely fail-open: if UDS is down, returns None gracefully.
"""
import json
import os
import socket
from typing import Optional

from tracker_pkg import _log_debug

_UDS_SOCKET = os.path.join(os.path.expanduser("~"), ".claude", "hooks", ".memory.sock")
_QUERY_TIMEOUT = 2.0  # seconds
_RELEVANCE_THRESHOLD = 0.5  # cosine distance threshold (lower = more similar)


def _query_uds(query_text: str, n_results: int = 3) -> Optional[dict]:
    """Query the memory UDS gateway. Returns response dict or None on failure."""
    if not os.path.exists(_UDS_SOCKET):
        return None

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(_QUERY_TIMEOUT)
        sock.connect(_UDS_SOCKET)

        request = json.dumps({
            "action": "query",
            "query": query_text,
            "n_results": n_results,
            "collection": "knowledge",
        })
        sock.sendall(request.encode("utf-8"))
        sock.shutdown(socket.SHUT_WR)  # Signal end of request

        response_bytes = b""
        while True:
            chunk = sock.recv(8192)
            if not chunk:
                break
            response_bytes += chunk

        sock.close()

        if response_bytes:
            parsed = json.loads(response_bytes.decode("utf-8"))
            # Fail-open: treat error responses the same as no response
            if isinstance(parsed, dict) and not parsed.get("ok", True) and "ids" not in parsed:
                return None
            return parsed
        return None

    except Exception as e:
        _log_debug(f"mentor_memory UDS query failed: {e}")
        return None


def _extract_query_context(tool_name, tool_input, tool_response, state) -> str:
    """Extract a meaningful search query from the current tool call context."""
    parts = []

    # Use error pattern if available
    recent_failure = state.get("recent_test_failure")
    if isinstance(recent_failure, dict):
        pattern = recent_failure.get("pattern", "")
        if pattern:
            parts.append(f"error: {pattern}")

    # Use file being edited
    if isinstance(tool_input, dict):
        file_path = tool_input.get("file_path", "") or tool_input.get("notebook_path", "")
        if file_path:
            parts.append(os.path.basename(file_path))

    # Use command if Bash
    if tool_name == "Bash" and isinstance(tool_input, dict):
        command = tool_input.get("command", "")
        if command:
            parts.append(command[:100])

    # Use current strategy
    strategy = state.get("current_strategy_id", "")
    if strategy:
        parts.append(f"strategy: {strategy}")

    return " ".join(parts[:3]) if parts else ""


def evaluate(tool_name, tool_input, tool_response, state):
    """Query memory for historical context relevant to current action.

    Updates state["mentor_memory_match"] and state["mentor_historical_context"].
    Returns dict {"match": dict, "context": str} or None.
    """
    try:
        query = _extract_query_context(tool_name, tool_input, tool_response, state)
        if not query:
            return None

        response = _query_uds(query)
        if not response:
            return None

        # Parse response — UDS returns {"ids": [...], "documents": [...], "distances": [...]}
        ids = response.get("ids", [[]])[0] if response.get("ids") else []
        documents = response.get("documents", [[]])[0] if response.get("documents") else []
        distances = response.get("distances", [[]])[0] if response.get("distances") else []

        if not documents or not distances:
            return None

        # Find best match under relevance threshold
        best_idx = None
        best_distance = float("inf")
        for i, dist in enumerate(distances):
            if dist < best_distance:
                best_distance = dist
                best_idx = i

        if best_idx is None or best_distance > _RELEVANCE_THRESHOLD:
            return None

        match_doc = documents[best_idx] if best_idx < len(documents) else ""
        match_id = ids[best_idx] if best_idx < len(ids) else ""

        match_info = {
            "id": match_id,
            "document": match_doc[:500],  # Cap for state storage
            "distance": best_distance,
            "query": query[:200],
        }

        context = f"Historical match (distance={best_distance:.3f}): {match_doc[:200]}"

        # Update state
        state["mentor_memory_match"] = match_info
        state["mentor_historical_context"] = context[:500]

        _log_debug(f"mentor_memory: found match distance={best_distance:.3f}")

        return {"match": match_info, "context": context}

    except Exception as e:
        _log_debug(f"mentor_memory.evaluate failed (non-blocking): {e}")
        return None
