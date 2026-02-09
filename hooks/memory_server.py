#!/usr/bin/env python3
"""Self-Healing Claude Framework — Memory MCP Server

A ChromaDB-backed persistent memory system exposed as MCP tools.
Claude Code connects to this server and gets search_knowledge, remember_this,
deep_query, and get_recent_activity as native tools.

The memory persists across sessions in ~/data/memory/, enabling cross-session
knowledge retention.

Run standalone: python3 memory_server.py
Used via MCP: configured in .claude/mcp.json
"""

import hashlib
import json
import os
import time
from datetime import datetime, timedelta

import chromadb
from mcp.server.fastmcp import FastMCP

# Sideband file: write memory query timestamps here so the enforcer
# can detect MCP tool calls that don't go through PreToolUse/PostToolUse hooks.
MEMORY_TIMESTAMP_FILE = os.path.join(
    os.path.expanduser("~"), ".claude", "hooks", ".memory_last_queried"
)


def _touch_memory_timestamp():
    """Write the current timestamp to the sideband file (atomic)."""
    tmp = MEMORY_TIMESTAMP_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"timestamp": time.time()}, f)
    os.replace(tmp, MEMORY_TIMESTAMP_FILE)

# Initialize MCP server
mcp = FastMCP("memory")

# Persistent ChromaDB storage
MEMORY_DIR = os.path.join(os.path.expanduser("~"), "data", "memory")
os.makedirs(MEMORY_DIR, exist_ok=True)

client = chromadb.PersistentClient(path=MEMORY_DIR)
collection = client.get_or_create_collection(
    name="knowledge",
    metadata={"hnsw:space": "cosine"},
)


def generate_id(content: str) -> str:
    """Generate a deterministic ID from content alone.

    Using only content (no timestamp) means saving the same knowledge twice
    produces the same ID, which ChromaDB treats as an upsert — preventing
    duplicate entries and unbounded database growth.
    """
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def format_results(results) -> list[dict]:
    """Format ChromaDB results into readable dicts."""
    if not results or not results.get("documents"):
        return []

    formatted = []
    docs = results["documents"][0] if results["documents"] else []
    metas = results["metadatas"][0] if results.get("metadatas") else []
    distances = results["distances"][0] if results.get("distances") else []

    for i, doc in enumerate(docs):
        entry = {
            "content": doc,
            "relevance": round(1 - (distances[i] if i < len(distances) else 0), 3),
        }
        if i < len(metas) and metas[i]:
            entry["context"] = metas[i].get("context", "")
            entry["tags"] = metas[i].get("tags", "")
            entry["timestamp"] = metas[i].get("timestamp", "")
        formatted.append(entry)

    return formatted


@mcp.tool()
def search_knowledge(query: str, top_k: int = 15) -> dict:
    """Search memory for relevant information. Use before starting any task.

    Args:
        query: What to search for (semantic search)
        top_k: Number of results to return (default 15)
    """
    top_k = max(1, min(top_k, 500))
    count = collection.count()
    if count == 0:
        return {"results": [], "total_memories": 0, "message": "Memory is empty. Start building knowledge with remember_this()."}

    actual_k = min(top_k, count)
    results = collection.query(query_texts=[query], n_results=actual_k)
    formatted = format_results(results)

    _touch_memory_timestamp()

    return {
        "results": formatted,
        "total_memories": count,
        "query": query,
    }


@mcp.tool()
def remember_this(content: str, context: str = "", tags: str = "") -> dict:
    """Save something to persistent memory. Use after every fix, discovery, or decision.

    Args:
        content: The knowledge to remember (be specific and detailed)
        context: What you were doing when you learned this
        tags: Comma-separated tags for categorization (e.g., "bug,fix,auth")
    """
    doc_id = generate_id(content)
    timestamp = datetime.now().isoformat()

    collection.upsert(
        documents=[content],
        metadatas=[{
            "context": context,
            "tags": tags,
            "timestamp": timestamp,
            "session_time": str(time.time()),
        }],
        ids=[doc_id],
    )

    _touch_memory_timestamp()

    return {
        "result": "Memory stored successfully!",
        "id": doc_id,
        "total_memories": collection.count(),
        "timestamp": timestamp,
    }


@mcp.tool()
def deep_query(query: str, top_k: int = 50) -> dict:
    """Comprehensive memory search — use for important decisions or debugging recurring issues.

    Returns more results than search_knowledge for thorough analysis.

    Args:
        query: What to search for
        top_k: Number of results (default 50)
    """
    top_k = max(1, min(top_k, 500))
    count = collection.count()
    if count == 0:
        return {"results": [], "total_memories": 0, "message": "Memory is empty."}

    actual_k = min(top_k, count)
    results = collection.query(query_texts=[query], n_results=actual_k)
    formatted = format_results(results)

    _touch_memory_timestamp()

    return {
        "results": formatted,
        "total_memories": count,
        "query": query,
        "depth": "comprehensive",
    }


@mcp.tool()
def get_recent_activity(hours: int = 48) -> dict:
    """Get recent memory saves chronologically. Good for session startup.

    Args:
        hours: How far back to look (default 48 hours)
    """
    hours = max(1, min(hours, 8760))
    count = collection.count()
    if count == 0:
        return {"results": [], "total_memories": 0, "message": "Memory is empty."}

    cutoff = time.time() - (hours * 3600)
    cutoff_iso = (datetime.now() - timedelta(hours=hours)).isoformat()

    # Get all recent entries (ChromaDB where filter on metadata)
    try:
        results = collection.get(
            where={"session_time": {"$gte": str(cutoff)}},
            limit=100,
        )
    except Exception:
        # Fallback: get most recent by querying with broad term
        results = collection.query(
            query_texts=["recent activity work session"],
            n_results=min(50, count),
        )
        return {
            "results": format_results(results),
            "total_memories": count,
            "hours": hours,
            "note": "Used fallback query (metadata filter unavailable)",
        }

    # Format get() results (different structure than query())
    formatted = []
    if results and results.get("documents"):
        docs = results["documents"]
        metas = results.get("metadatas", [])
        for i, doc in enumerate(docs):
            entry = {"content": doc}
            if i < len(metas) and metas[i]:
                entry["context"] = metas[i].get("context", "")
                entry["tags"] = metas[i].get("tags", "")
                entry["timestamp"] = metas[i].get("timestamp", "")
            formatted.append(entry)

    # Sort by timestamp (newest first)
    formatted.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

    return {
        "results": formatted,
        "total_memories": count,
        "hours": hours,
        "since": cutoff_iso,
    }


@mcp.tool()
def memory_stats() -> dict:
    """Get memory system statistics."""
    count = collection.count()
    return {
        "total_memories": count,
        "storage_path": MEMORY_DIR,
        "collection_name": "knowledge",
        "status": "healthy" if count >= 0 else "error",
    }


if __name__ == "__main__":
    mcp.run()
