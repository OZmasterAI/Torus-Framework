#!/usr/bin/env python3
"""Self-Healing Claude Framework — Memory MCP Server

A ChromaDB-backed persistent memory system exposed as MCP tools.
Claude Code connects to this server and gets search_knowledge, remember_this,
deep_query, get_recent_activity, and get_memory as native tools.

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

# Add shared module path for error_normalizer
import sys as _sys
_sys.path.insert(0, os.path.dirname(__file__))
from shared.error_normalizer import normalize_error, fnv1a_hash, error_signature


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

fix_outcomes = client.get_or_create_collection(
    name="fix_outcomes",
    metadata={"hnsw:space": "cosine"},
)

# Auto-capture: observations collection (separate from curated knowledge)
observations = client.get_or_create_collection(
    name="observations",
    metadata={"hnsw:space": "cosine"},
)

# Auto-capture settings
OBSERVATION_TTL_DAYS = 30
MAX_OBSERVATIONS = 5000
CAPTURE_QUEUE_FILE = os.path.join(os.path.dirname(__file__), ".capture_queue.jsonl")
DIGEST_TAGS = "type:digest,auto-generated,area:framework"


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


SUMMARY_LENGTH = 120


def format_summaries(results) -> list[dict]:
    """Format ChromaDB query results into compact summaries (id + preview).

    Returns lightweight entries for progressive disclosure. Use get_memory(id)
    to retrieve full content for specific entries.

    Handles both query() results (nested ids[0]) and get() results (flat ids).
    """
    if not results:
        return []

    # Detect query() vs get() result structure
    ids_raw = results.get("ids", [])
    docs_raw = results.get("documents", [])
    metas_raw = results.get("metadatas", [])
    distances_raw = results.get("distances", [])

    # query() nests inside [0]; get() returns flat lists
    if ids_raw and isinstance(ids_raw[0], list):
        ids = ids_raw[0] if ids_raw else []
        docs = docs_raw[0] if docs_raw else []
        metas = metas_raw[0] if metas_raw else []
        distances = distances_raw[0] if distances_raw else []
    else:
        ids = ids_raw
        docs = docs_raw
        metas = metas_raw
        distances = []

    if not docs:
        return []

    formatted = []
    for i, doc in enumerate(docs):
        preview = doc[:SUMMARY_LENGTH].replace("\n", " ")
        if len(doc) > SUMMARY_LENGTH:
            preview += "..."
        entry = {
            "id": ids[i] if i < len(ids) else "",
            "preview": preview,
        }
        if i < len(distances) and distances:
            entry["relevance"] = round(1 - distances[i], 3)
        if i < len(metas) and metas[i]:
            entry["tags"] = metas[i].get("tags", "")
            entry["timestamp"] = metas[i].get("timestamp", "")
        formatted.append(entry)

    return formatted


def _compute_confidence(successes, attempts):
    """Laplace-smoothed confidence: (s+1)/(n+2)."""
    return (successes + 1) / (attempts + 2)


def _temporal_decay(confidence, timestamp_str):
    """Apply temporal decay with 30-day half-life."""
    try:
        age_seconds = time.time() - float(timestamp_str)
        age_days = max(0, age_seconds / 86400)
        return confidence * (0.5 ** (age_days / 30))
    except (ValueError, TypeError):
        return confidence


def _flush_capture_queue():
    """Read the capture queue and upsert all observations to ChromaDB.

    Atomically replaces the queue file with an empty one to prevent
    duplicate ingestion. Skips corrupted lines gracefully.
    """
    if not os.path.exists(CAPTURE_QUEUE_FILE):
        return 0

    try:
        # Atomic read-and-clear: read all, then truncate
        with open(CAPTURE_QUEUE_FILE, "r") as f:
            lines = f.readlines()

        if not lines:
            return 0

        # Truncate the file atomically
        tmp = CAPTURE_QUEUE_FILE + ".tmp"
        with open(tmp, "w") as f:
            pass  # empty file
        os.replace(tmp, CAPTURE_QUEUE_FILE)

        # Parse and batch upsert
        docs, metas, ids = [], [], []
        for line in lines:
            try:
                obs = json.loads(line.strip())
                if "document" in obs and "id" in obs:
                    docs.append(obs["document"])
                    metas.append(obs.get("metadata", {}))
                    ids.append(obs["id"])
            except (json.JSONDecodeError, KeyError):
                continue  # skip corrupted lines

        if docs:
            # Batch upsert (ChromaDB handles dedup via ids)
            batch_size = 100
            for i in range(0, len(docs), batch_size):
                observations.upsert(
                    documents=docs[i:i + batch_size],
                    metadatas=metas[i:i + batch_size],
                    ids=ids[i:i + batch_size],
                )

        # Run compaction after flush
        _compact_observations()

        return len(docs)

    except Exception:
        return 0


def _compact_observations():
    """Expire old observations and enforce hard cap.

    Observations older than OBSERVATION_TTL_DAYS get digested into a
    compact summary saved to the curated knowledge collection, then deleted.
    """
    try:
        total = observations.count()
        if total == 0:
            return

        cutoff = str(time.time() - (OBSERVATION_TTL_DAYS * 86400))

        # Find expired observations
        try:
            expired = observations.get(
                where={"session_time": {"$lt": cutoff}},
                limit=500,
            )
        except Exception:
            expired = None

        if expired and expired.get("documents") and len(expired["documents"]) > 0:
            exp_docs = expired["documents"]
            exp_metas = expired.get("metadatas", [])
            exp_ids = expired.get("ids", [])

            # Generate digest from expired observations
            error_counts = {}
            tool_counts = {}
            file_paths = {}
            bash_total = 0
            bash_errors = 0
            session_ids = set()

            for i, doc in enumerate(exp_docs):
                meta = exp_metas[i] if i < len(exp_metas) else {}
                tool = meta.get("tool_name", "?")
                tool_counts[tool] = tool_counts.get(tool, 0) + 1

                ep = meta.get("error_pattern", "")
                if ep:
                    error_counts[ep] = error_counts.get(ep, 0) + 1

                if tool == "Bash":
                    bash_total += 1
                    if meta.get("has_error") == "true":
                        bash_errors += 1

                if tool in ("Edit", "Write"):
                    # Extract file path from document text
                    parts = doc.split(":", 1)
                    if len(parts) > 1:
                        fp = parts[1].strip().split(" ")[0]
                        file_paths[fp] = file_paths.get(fp, 0) + 1

                sid = meta.get("session_id", "")
                if sid:
                    session_ids.add(sid)

            # Format digest
            top_errors = sorted(error_counts.items(), key=lambda x: -x[1])[:5]
            top_files = sorted(file_paths.items(), key=lambda x: -x[1])[:10]
            top_tools = sorted(tool_counts.items(), key=lambda x: -x[1])

            digest_parts = [
                f"Auto-Capture Digest ({len(exp_docs)} observations, {len(session_ids)} sessions, expired {OBSERVATION_TTL_DAYS}d+):",
                f"Tools: {', '.join(f'{t}:{c}' for t, c in top_tools)}",
            ]
            if bash_total > 0:
                rate = round(bash_errors / bash_total * 100, 1)
                digest_parts.append(f"Bash error rate: {rate}% ({bash_errors}/{bash_total})")
            if top_errors:
                digest_parts.append(f"Top errors: {', '.join(f'{e}:{c}' for e, c in top_errors)}")
            if top_files:
                digest_parts.append(f"Top files: {', '.join(f'{f}:{c}' for f, c in top_files[:5])}")

            digest_text = "\n".join(digest_parts)

            # Save digest to curated knowledge collection
            digest_id = hashlib.sha256(digest_text.encode()).hexdigest()[:16]
            collection.upsert(
                documents=[digest_text],
                metadatas=[{
                    "context": "auto-capture compaction digest",
                    "tags": DIGEST_TAGS,
                    "timestamp": datetime.now().isoformat(),
                    "session_time": str(time.time()),
                }],
                ids=[digest_id],
            )

            # Delete expired observations
            if exp_ids:
                batch_size = 100
                for i in range(0, len(exp_ids), batch_size):
                    observations.delete(ids=exp_ids[i:i + batch_size])

        # Hard cap enforcement
        total = observations.count()
        if total > MAX_OBSERVATIONS:
            # Delete oldest to get below cap (with buffer)
            target_delete = total - (MAX_OBSERVATIONS - 500)
            try:
                oldest = observations.get(
                    limit=target_delete,
                    # ChromaDB returns in insertion order by default
                )
                if oldest and oldest.get("ids"):
                    batch_size = 100
                    old_ids = oldest["ids"]
                    for i in range(0, len(old_ids), batch_size):
                        observations.delete(ids=old_ids[i:i + batch_size])
            except Exception:
                pass

    except Exception:
        pass  # Compaction failure must not crash the server


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
    formatted = format_summaries(results)

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
    formatted = format_summaries(results)

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
            "results": format_summaries(results),
            "total_memories": count,
            "hours": hours,
            "note": "Used fallback query (metadata filter unavailable)",
        }

    # Format get() results using summary format (get() returns flat lists)
    formatted = format_summaries(results)

    # Sort by timestamp (newest first)
    formatted.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

    return {
        "results": formatted,
        "total_memories": count,
        "hours": hours,
        "since": cutoff_iso,
    }


@mcp.tool()
def get_memory(id: str) -> dict:
    """Retrieve full content for a specific memory by ID.

    Use after search_knowledge/deep_query to get complete details for relevant entries.

    Args:
        id: The memory ID (from search results)
    """
    try:
        result = collection.get(ids=[id])
        if not result or not result.get("documents") or len(result["documents"]) == 0:
            return {"error": f"No memory found with id: {id}"}

        entry = {
            "id": id,
            "content": result["documents"][0],
        }
        if result.get("metadatas") and result["metadatas"][0]:
            meta = result["metadatas"][0]
            entry["context"] = meta.get("context", "")
            entry["tags"] = meta.get("tags", "")
            entry["timestamp"] = meta.get("timestamp", "")

        _touch_memory_timestamp()
        return entry

    except Exception as e:
        return {"error": f"Failed to retrieve memory: {str(e)}"}


@mcp.tool()
def memory_stats() -> dict:
    """Get memory system statistics."""
    count = collection.count()
    obs_count = observations.count()
    fix_count = fix_outcomes.count()

    # Queue file size
    queue_size = 0
    queue_lines = 0
    try:
        if os.path.exists(CAPTURE_QUEUE_FILE):
            queue_size = os.path.getsize(CAPTURE_QUEUE_FILE)
            with open(CAPTURE_QUEUE_FILE, "r") as f:
                queue_lines = sum(1 for _ in f)
    except Exception:
        pass

    return {
        "total_memories": count,
        "total_observations": obs_count,
        "total_fix_outcomes": fix_count,
        "capture_queue_lines": queue_lines,
        "capture_queue_bytes": queue_size,
        "storage_path": MEMORY_DIR,
        "collections": ["knowledge", "observations", "fix_outcomes"],
        "status": "healthy" if count >= 0 else "error",
    }


@mcp.tool()
def search_observations(query: str, top_k: int = 20, hours: int = 0) -> dict:
    """Search auto-captured observations (tool calls, errors, prompts).

    Unlike curated memories, observations are passively captured from every
    Bash, Edit, Write, and NotebookEdit tool call. Use this to find past
    commands, errors, or patterns.

    Args:
        query: What to search for (semantic search)
        top_k: Number of results to return (default 20)
        hours: If > 0, only return observations from the last N hours
    """
    top_k = max(1, min(top_k, 100))

    # Flush queue to ensure latest data
    _flush_capture_queue()

    count = observations.count()
    if count == 0:
        return {"results": [], "total_observations": 0, "message": "No observations yet."}

    actual_k = min(top_k, count)

    if hours > 0:
        cutoff = str(time.time() - (hours * 3600))
        try:
            results = observations.query(
                query_texts=[query],
                n_results=actual_k,
                where={"session_time": {"$gte": cutoff}},
            )
        except Exception:
            results = observations.query(query_texts=[query], n_results=actual_k)
    else:
        results = observations.query(query_texts=[query], n_results=actual_k)

    formatted = format_summaries(results)

    _touch_memory_timestamp()

    return {
        "results": formatted,
        "total_observations": count,
        "query": query,
    }


@mcp.tool()
def get_observation(id: str) -> dict:
    """Retrieve full content for a specific observation by ID.

    Use after search_observations to get complete details.

    Args:
        id: The observation ID (from search results)
    """
    try:
        result = observations.get(ids=[id])
        if not result or not result.get("documents") or len(result["documents"]) == 0:
            return {"error": f"No observation found with id: {id}"}

        entry = {
            "id": id,
            "document": result["documents"][0],
        }
        if result.get("metadatas") and result["metadatas"][0]:
            entry["metadata"] = result["metadatas"][0]

        _touch_memory_timestamp()
        return entry

    except Exception as e:
        return {"error": f"Failed to retrieve observation: {str(e)}"}


@mcp.tool()
def timeline(anchor_id: str = "", anchor_time: str = "", window_minutes: int = 10, limit: int = 20) -> dict:
    """Get chronological observations around a point in time.

    Useful for understanding what happened before/after an error.

    Args:
        anchor_id: Observation ID to center the timeline on
        anchor_time: Epoch timestamp string to center on (alternative to anchor_id)
        window_minutes: How many minutes before/after the anchor to include (default 10)
        limit: Max observations to return (default 20)
    """
    # Flush queue first
    _flush_capture_queue()

    count = observations.count()
    if count == 0:
        return {"results": [], "total_observations": 0, "message": "No observations yet."}

    # Determine anchor time
    anchor_epoch = None
    anchor_obs_id = None

    if anchor_id:
        try:
            result = observations.get(ids=[anchor_id])
            if result and result.get("metadatas") and result["metadatas"][0]:
                anchor_epoch = float(result["metadatas"][0].get("session_time", 0))
                anchor_obs_id = anchor_id
        except Exception:
            pass

    if anchor_epoch is None and anchor_time:
        try:
            anchor_epoch = float(anchor_time)
        except (ValueError, TypeError):
            pass

    if anchor_epoch is None:
        # Default: most recent
        anchor_epoch = time.time()

    # Query window
    window_secs = window_minutes * 60
    start = str(anchor_epoch - window_secs)
    end = str(anchor_epoch + window_secs)

    limit = max(1, min(limit, 100))

    try:
        results = observations.get(
            where={
                "$and": [
                    {"session_time": {"$gte": start}},
                    {"session_time": {"$lte": end}},
                ]
            },
            limit=limit,
        )
    except Exception:
        return {"results": [], "error": "Timeline query failed"}

    if not results or not results.get("documents"):
        return {"results": [], "window": f"±{window_minutes}min", "anchor": anchor_epoch}

    # Build entries and sort chronologically
    entries = []
    docs = results["documents"]
    metas = results.get("metadatas", [])
    ids = results.get("ids", [])

    for i, doc in enumerate(docs):
        meta = metas[i] if i < len(metas) else {}
        obs_id = ids[i] if i < len(ids) else ""
        entry = {
            "id": obs_id,
            "preview": doc[:SUMMARY_LENGTH].replace("\n", " "),
            "session_time": meta.get("session_time", ""),
            "timestamp": meta.get("timestamp", ""),
            "tool_name": meta.get("tool_name", ""),
            "has_error": meta.get("has_error", "false"),
        }
        if obs_id == anchor_obs_id:
            entry["is_anchor"] = True
        entries.append(entry)

    entries.sort(key=lambda x: float(x.get("session_time", 0)))

    _touch_memory_timestamp()

    return {
        "results": entries,
        "window": f"±{window_minutes}min",
        "anchor": anchor_epoch,
        "total_in_window": len(entries),
    }


@mcp.tool()
def record_attempt(error_text: str, strategy_id: str) -> dict:
    """Record a fix attempt for causal tracking.

    Args:
        error_text: The error message being fixed
        strategy_id: A short name for the fix strategy (e.g., "fix-type-cast")
    """
    normalized, error_hash = error_signature(error_text)
    strategy_hash = fnv1a_hash(strategy_id)
    chain_id = f"{error_hash}_{strategy_hash}"

    # Check for existing record
    attempts = 1
    successes = 0
    try:
        existing = fix_outcomes.get(ids=[chain_id])
        if existing and existing.get("documents") and len(existing["documents"]) > 0:
            meta = existing["metadatas"][0] if existing.get("metadatas") else {}
            attempts = int(meta.get("attempts", 0)) + 1
            successes = int(meta.get("successes", 0))
    except Exception:
        pass

    confidence = _compute_confidence(successes, attempts)

    fix_outcomes.upsert(
        documents=[normalized],
        metadatas=[{
            "error_hash": error_hash,
            "strategy_id": strategy_id,
            "chain_id": chain_id,
            "outcome": "pending",
            "confidence": str(round(confidence, 4)),
            "attempts": str(attempts),
            "successes": str(successes),
            "timestamp": str(time.time()),
            "last_outcome_time": "",
        }],
        ids=[chain_id],
    )

    _touch_memory_timestamp()

    return {
        "chain_id": chain_id,
        "error_hash": error_hash,
        "normalized_error": normalized,
        "attempts": attempts,
    }


@mcp.tool()
def record_outcome(chain_id: str, outcome: str) -> dict:
    """Record the outcome of a fix attempt.

    Args:
        chain_id: The chain_id returned by record_attempt
        outcome: "success" or "failure"
    """
    if outcome not in ("success", "failure"):
        return {"error": "outcome must be 'success' or 'failure'"}

    try:
        existing = fix_outcomes.get(ids=[chain_id])
        if not existing or not existing.get("documents") or len(existing["documents"]) == 0:
            return {"error": f"No record found for chain_id: {chain_id}"}

        meta = existing["metadatas"][0] if existing.get("metadatas") else {}
        attempts = int(meta.get("attempts", 1))
        successes = int(meta.get("successes", 0))
        strategy_id = meta.get("strategy_id", "")

        if outcome == "success":
            successes += 1

        confidence = _compute_confidence(successes, attempts)
        banned = attempts >= 2 and confidence < 0.18

        fix_outcomes.update(
            ids=[chain_id],
            metadatas=[{
                **meta,
                "outcome": outcome,
                "confidence": str(round(confidence, 4)),
                "successes": str(successes),
                "banned": str(banned),
                "last_outcome_time": str(time.time()),
            }],
        )

        _touch_memory_timestamp()

        return {
            "confidence": round(confidence, 4),
            "banned": banned,
            "strategy_id": strategy_id,
            "chain_id": chain_id,
            "attempts": attempts,
            "successes": successes,
        }

    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def query_fix_history(error_text: str, top_k: int = 10) -> dict:
    """Query fix history for a given error to find what strategies worked or failed.

    Args:
        error_text: The error message to look up
        top_k: Maximum number of results (default 10)
    """
    top_k = max(1, min(top_k, 100))
    normalized, error_hash = error_signature(error_text)

    results_by_chain = {}

    # Semantic search
    try:
        count = fix_outcomes.count()
        if count > 0:
            semantic = fix_outcomes.query(
                query_texts=[normalized],
                n_results=min(top_k, count),
            )
            if semantic and semantic.get("documents"):
                docs = semantic["documents"][0]
                metas = semantic["metadatas"][0] if semantic.get("metadatas") else []
                for i, doc in enumerate(docs):
                    meta = metas[i] if i < len(metas) else {}
                    cid = meta.get("chain_id", "")
                    if cid:
                        results_by_chain[cid] = meta
    except Exception:
        pass

    # Exact hash match
    try:
        exact = fix_outcomes.get(where={"error_hash": error_hash})
        if exact and exact.get("documents"):
            metas = exact.get("metadatas", [])
            for meta in metas:
                cid = meta.get("chain_id", "")
                if cid:
                    results_by_chain[cid] = meta
    except Exception:
        pass

    # Categorize with temporal decay
    recommended = []
    banned = []
    pending = []

    for chain_id, meta in results_by_chain.items():
        confidence = float(meta.get("confidence", 0))
        timestamp = meta.get("timestamp", "")
        attempts = int(meta.get("attempts", 0))
        outcome = meta.get("outcome", "pending")

        decayed = _temporal_decay(confidence, timestamp)

        entry = {
            "chain_id": chain_id,
            "strategy_id": meta.get("strategy_id", ""),
            "confidence": round(decayed, 4),
            "raw_confidence": round(confidence, 4),
            "attempts": attempts,
            "successes": int(meta.get("successes", 0)),
            "outcome": outcome,
        }

        if outcome == "pending":
            pending.append(entry)
        elif decayed > 0.5:
            recommended.append(entry)
        elif decayed < 0.18 and attempts >= 2:
            banned.append(entry)
        else:
            # Neither recommended nor banned — include in recommended with low confidence
            recommended.append(entry)

    # Sort recommended by confidence descending
    recommended.sort(key=lambda x: x["confidence"], reverse=True)

    _touch_memory_timestamp()

    result = {
        "recommended": recommended,
        "banned": banned,
        "pending": pending,
        "error_hash": error_hash,
        "normalized_error": normalized,
    }

    # Auto-surface fallback: if no fix history exists, search observations
    if not recommended and not banned:
        try:
            obs_count = observations.count()
            if obs_count > 0:
                _flush_capture_queue()
                obs_results = observations.query(
                    query_texts=[normalized],
                    n_results=min(5, obs_count),
                )
                obs_formatted = format_summaries(obs_results)
                if obs_formatted:
                    result["observations"] = obs_formatted
                    result["observation_note"] = "No fix history found. Showing related observations."
        except Exception:
            pass

    return result


if __name__ == "__main__":
    mcp.run()
