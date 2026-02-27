"""ChromaDB Unix Domain Socket Client.

Connects to the UDS gateway exposed by memory_server.py to perform
ChromaDB operations without creating a separate PersistentClient.
This eliminates segfaults from concurrent Rust backend access.

Protocol: JSON-over-newline on Unix Domain Socket.
One request/response per connection (short-lived).
"""

import json
import os
import socket
import time

SOCKET_PATH = os.path.join(
    os.path.expanduser("~"), ".claude", "hooks", ".chromadb.sock"
)
SOCKET_TIMEOUT = 2  # seconds (kept low to avoid boot timeout — 15s hook limit)


class WorkerUnavailable(Exception):
    """Raised when the UDS worker (memory_server.py) is not reachable."""
    pass


def is_worker_available(retries=3, delay=0.5):
    """Check if the UDS worker is accepting connections.

    Retries with exponential backoff to handle startup race conditions
    (socket may not exist until first MCP tool call triggers _ensure_initialized).
    """
    for attempt in range(retries):
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(SOCKET_TIMEOUT)
            sock.connect(SOCKET_PATH)
            sock.close()
            return True
        except (FileNotFoundError, ConnectionRefusedError, OSError):
            if attempt < retries - 1:
                time.sleep(delay * (2 ** attempt))
    return False


def request(method, collection=None, params=None):
    """Send a request to the UDS worker and return the result.

    Raises WorkerUnavailable if the socket is unreachable.
    Raises RuntimeError if the worker returns an error response.
    """
    req = {"method": method}
    if collection is not None:
        req["collection"] = collection
    if params is not None:
        req["params"] = params

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(SOCKET_TIMEOUT)
        sock.connect(SOCKET_PATH)
    except (FileNotFoundError, ConnectionRefusedError, OSError) as e:
        raise WorkerUnavailable(f"Cannot connect to UDS worker: {e}")

    try:
        # Send request as JSON + newline
        sock.sendall((json.dumps(req) + "\n").encode("utf-8"))

        # Read response (accumulate until newline, cap at 10MB)
        MAX_RESPONSE_SIZE = 10 * 1024 * 1024
        buf = b""
        while b"\n" not in buf:
            chunk = sock.recv(65536)
            if not chunk:
                break
            buf += chunk
            if len(buf) > MAX_RESPONSE_SIZE:
                raise RuntimeError(f"Response exceeded {MAX_RESPONSE_SIZE} bytes")

        if not buf:
            raise WorkerUnavailable("Empty response from UDS worker")

        resp = json.loads(buf.decode("utf-8").strip())
        if not resp.get("ok"):
            raise RuntimeError(resp.get("error", "Unknown worker error"))
        return resp.get("result")
    finally:
        sock.close()


# ── Convenience wrappers ──────────────────────────────────────

def ping():
    """Health check — returns 'pong' if worker is alive."""
    return request("ping")


def count(collection="knowledge"):
    """Return the number of entries in a collection."""
    return request("count", collection=collection)


def query(collection, query_texts, n_results=5, include=None):
    """Semantic search on a collection."""
    params = {"query_texts": query_texts, "n_results": n_results}
    if include is not None:
        params["include"] = include
    return request("query", collection=collection, params=params)


def get(collection, ids=None, limit=None, include=None):
    """Get entries by IDs or limit from a collection."""
    params = {}
    if ids is not None:
        params["ids"] = ids
    if limit is not None:
        params["limit"] = limit
    if include is not None:
        params["include"] = include
    return request("get", collection=collection, params=params)


def upsert(collection, documents, metadatas, ids):
    """Upsert documents into a collection."""
    return request("upsert", collection=collection, params={
        "documents": documents,
        "metadatas": metadatas,
        "ids": ids,
    })


def delete(collection, ids):
    """Delete entries by IDs from a collection."""
    return request("delete", collection=collection, params={"ids": ids})


def remember(content, context="", tags=""):
    """Save a memory to knowledge via UDS. Returns result dict."""
    return request("auto_remember", params={
        "content": content, "context": context, "tags": tags,
    })


def flush_queue():
    """Flush the capture queue to ChromaDB observations."""
    return request("flush_queue")


def backup():
    """Trigger a consistent backup of chroma.sqlite3 on the server."""
    return request("backup")


