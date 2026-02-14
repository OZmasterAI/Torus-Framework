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

import atexit
import functools
import hashlib
import json
import os
import socket
import threading
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


def _validate_top_k(value, default=15, min_val=1, max_val=500):
    """Validate and clamp a top_k/limit parameter."""
    try:
        val = int(value)
        return max(min_val, min(val, max_val))
    except (ValueError, TypeError):
        return default


def _validate_hours(value, default=48, min_val=1, max_val=720):
    """Validate and clamp an hours parameter."""
    try:
        val = int(value)
        return max(min_val, min(val, max_val))
    except (ValueError, TypeError):
        return default


def _validate_distance_threshold(value, default=0.3, min_val=0.05, max_val=0.8):
    """Validate and clamp a distance_threshold parameter."""
    try:
        val = float(value)
        return max(min_val, min(val, max_val))
    except (ValueError, TypeError):
        return default


def _touch_memory_timestamp():
    """Write the current timestamp to the sideband file (atomic)."""
    tmp = MEMORY_TIMESTAMP_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"timestamp": time.time()}, f)
    os.replace(tmp, MEMORY_TIMESTAMP_FILE)

# Initialize MCP server
mcp = FastMCP("memory")


def crash_proof(fn):
    """Wrap MCP tool handler so exceptions return error dicts instead of crashing the server."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            print(f"[MCP] {fn.__name__} error: {e}\n{tb}", file=_sys.stderr)
            return {"error": f"{fn.__name__} failed: {type(e).__name__}: {e}"}
    return wrapper


# Persistent ChromaDB storage
MEMORY_DIR = os.path.join(os.path.expanduser("~"), "data", "memory")
os.makedirs(MEMORY_DIR, exist_ok=True)
FTS5_DB_PATH = os.path.join(MEMORY_DIR, "fts5_index.db")

# Unix Domain Socket gateway for external consumers (hooks, dashboard)
SOCKET_PATH = os.path.join(
    os.path.expanduser("~"), ".claude", "hooks", ".chromadb.sock"
)
_socket_server = None  # threading server reference for cleanup

# Lazy ChromaDB initialization — prevents segfault when module is imported
# by test code while MCP server already holds a PersistentClient on the same path.
# ChromaDB Rust backend cannot handle concurrent PersistentClient access.
client = None
collection = None
fix_outcomes = None
observations = None
web_pages = None
_chromadb_degraded = False


def _init_chromadb():
    """Lazy initialization of ChromaDB client and collections.

    Called from _ensure_initialized() on first MCP tool use.
    Safe to call multiple times — idempotent after first run.
    """
    global client, collection, fix_outcomes, observations, web_pages, _chromadb_degraded
    if client is not None:
        return
    try:
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
        # Web page indexing collection (used by /web skill)
        web_pages = client.get_or_create_collection(
            name="web_pages",
            metadata={"hnsw:space": "cosine"},
        )
    except Exception as e:
        import traceback
        print(f"[MCP] ChromaDB init failed: {e}\n{traceback.format_exc()}", file=_sys.stderr)
        _chromadb_degraded = True

# Progressive disclosure: preview length for search summaries
SUMMARY_LENGTH = 120

# Auto-capture settings
OBSERVATION_TTL_DAYS = 30
MAX_OBSERVATIONS = 5000
CAPTURE_QUEUE_FILE = os.path.join(os.path.dirname(__file__), ".capture_queue.jsonl")
DIGEST_TAGS = "type:digest,auto-generated,area:framework"

# Ingestion filter: reject noise patterns
MIN_CONTENT_LENGTH = 20
NOISE_PATTERNS = [
    "npm install", "pip install", "Successfully installed",
    "already satisfied", "up to date", "added .* packages",
    "removing .* packages", "npm WARN", "DEPRECATION",
    "Collecting ", "Downloading ", "Installing collected",
    "running setup.py", "Building wheel", "Using cached",
]
import re as _re
NOISE_REGEXES = [_re.compile(p, _re.IGNORECASE) for p in NOISE_PATTERNS]

# Near-dedup: cosine distance threshold
DEDUP_THRESHOLD = 0.05  # distance < 0.05 means >95% similar

# Observation promotion settings
MAX_PROMOTIONS_PER_CYCLE = 10
PROMOTION_TAGS = "type:auto-promoted,area:framework"


def generate_id(content: str) -> str:
    """Generate a deterministic ID from content alone.

    Using only content (no timestamp) means saving the same knowledge twice
    produces the same ID, which ChromaDB treats as an upsert — preventing
    duplicate entries and unbounded database growth.
    """
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _migrate_previews():
    """One-time backfill: add preview field to all existing entries missing it.

    Checks the first entry for a 'preview' key. If present, migration is
    already done. Otherwise, batch-updates all entries in chunks of 100.
    Called once at module load time.
    """
    count = collection.count()
    if count == 0:
        return 0

    # Check if migration is needed by sampling first entry
    sample = collection.get(limit=1, include=["metadatas"])
    if sample and sample.get("metadatas") and sample["metadatas"][0].get("preview"):
        return 0  # Already migrated

    # Fetch all entries to backfill previews
    all_data = collection.get(limit=count, include=["documents", "metadatas"])
    if not all_data or not all_data.get("ids"):
        return 0

    ids = all_data["ids"]
    docs = all_data.get("documents", [])
    metas = all_data.get("metadatas", [])

    migrated = 0
    batch_size = 100
    for start in range(0, len(ids), batch_size):
        end = min(start + batch_size, len(ids))
        batch_ids = []
        batch_metas = []

        for i in range(start, end):
            meta = metas[i] if i < len(metas) else {}
            if meta.get("preview"):
                continue  # Already has preview

            doc = docs[i] if i < len(docs) else ""
            preview = doc[:SUMMARY_LENGTH].replace("\n", " ")
            if len(doc) > SUMMARY_LENGTH:
                preview += "..."

            updated_meta = dict(meta) if meta else {}
            updated_meta["preview"] = preview
            batch_ids.append(ids[i])
            batch_metas.append(updated_meta)

        if batch_ids:
            collection.update(ids=batch_ids, metadatas=batch_metas)
            migrated += len(batch_ids)

    return migrated


# ──────────────────────────────────────────────────
# FTS5 Hybrid Search Index
# ──────────────────────────────────────────────────
import sqlite3
import re


class FTS5Index:
    """SQLite FTS5 index for keyword and tag search.

    Persisted to disk by default; falls back to :memory: for tests.
    ChromaDB remains the source of truth; FTS5 is a read-optimized
    secondary index. A sync_meta table tracks whether the on-disk
    index matches ChromaDB, skipping rebuild when already synced.
    """

    def __init__(self, db_path=":memory:"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        if db_path != ":memory:":
            self.conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self):
        c = self.conn
        c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS mem_fts USING fts5(content, preview)")
        c.execute("""CREATE TABLE IF NOT EXISTS mem_lookup (
            fts_rowid INTEGER PRIMARY KEY,
            memory_id TEXT UNIQUE,
            tags TEXT,
            timestamp TEXT,
            session_time REAL
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS tags (
            memory_id TEXT,
            tag TEXT
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_tags_mid ON tags(memory_id)")
        c.execute("CREATE TABLE IF NOT EXISTS sync_meta (key TEXT PRIMARY KEY, value TEXT)")
        c.commit()

    def is_synced(self, chromadb_count):
        """Check if FTS5 index is in sync with ChromaDB by entry count."""
        row = self.conn.execute(
            "SELECT value FROM sync_meta WHERE key='sync_count'"
        ).fetchone()
        if row is None:
            return False
        return int(row[0]) == chromadb_count

    def _update_sync_count(self, count):
        """Record the current sync count after a successful rebuild or add."""
        self.conn.execute(
            "INSERT OR REPLACE INTO sync_meta (key, value) VALUES ('sync_count', ?)",
            (str(count),),
        )
        self.conn.commit()

    def reset_and_rebuild(self, chroma_collection):
        """Drop all tables and rebuild from ChromaDB (corruption recovery)."""
        self.conn.execute("DROP TABLE IF EXISTS mem_fts")
        self.conn.execute("DROP TABLE IF EXISTS mem_lookup")
        self.conn.execute("DROP TABLE IF EXISTS tags")
        self.conn.execute("DROP TABLE IF EXISTS sync_meta")
        self.conn.commit()
        self._create_tables()
        return self.build_from_chromadb(chroma_collection)

    def build_from_chromadb(self, chroma_collection):
        """Populate FTS5 index from ChromaDB data. Returns entry count."""
        count = chroma_collection.count()
        if count == 0:
            return 0

        all_data = chroma_collection.get(
            limit=count,
            include=["documents", "metadatas"],
        )
        if not all_data or not all_data.get("ids"):
            return 0

        ids = all_data["ids"]
        docs = all_data.get("documents", [])
        metas = all_data.get("metadatas", [])

        for i, mid in enumerate(ids):
            doc = docs[i] if i < len(docs) else ""
            meta = metas[i] if i < len(metas) else {}
            preview = meta.get("preview", doc[:SUMMARY_LENGTH] if doc else "")
            tags_str = meta.get("tags", "")
            timestamp = meta.get("timestamp", "")
            session_time = meta.get("session_time", 0.0)
            if isinstance(session_time, str):
                try:
                    session_time = float(session_time)
                except (ValueError, TypeError):
                    session_time = 0.0

            self._insert_entry(mid, doc, preview, tags_str, timestamp, session_time)

        self.conn.commit()
        self._update_sync_count(len(ids))
        return len(ids)

    def _insert_entry(self, memory_id, content, preview, tags_str, timestamp, session_time):
        """Insert a single entry into FTS5 + lookup + tags tables."""
        c = self.conn
        # Upsert: delete old entry if exists
        existing = c.execute(
            "SELECT fts_rowid FROM mem_lookup WHERE memory_id = ?", (memory_id,)
        ).fetchone()
        if existing:
            c.execute("DELETE FROM mem_fts WHERE rowid = ?", (existing[0],))
            c.execute("DELETE FROM mem_lookup WHERE memory_id = ?", (memory_id,))
            c.execute("DELETE FROM tags WHERE memory_id = ?", (memory_id,))

        c.execute("INSERT INTO mem_fts(content, preview) VALUES (?, ?)", (content, preview))
        rowid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        c.execute(
            "INSERT INTO mem_lookup(fts_rowid, memory_id, tags, timestamp, session_time) VALUES (?,?,?,?,?)",
            (rowid, memory_id, tags_str, timestamp, session_time),
        )

        # Normalize tags into tag table
        if tags_str:
            for tag in tags_str.split(","):
                tag = tag.strip()
                if tag:
                    c.execute("INSERT INTO tags(memory_id, tag) VALUES (?, ?)", (memory_id, tag))

    def add_entry(self, memory_id, content, preview, tags_str, timestamp, session_time):
        """Add or update an entry (dual-write from remember_this)."""
        self._insert_entry(memory_id, content, preview, tags_str, timestamp, session_time)
        self.conn.commit()
        # Keep sync_count in step with additions
        row = self.conn.execute(
            "SELECT value FROM sync_meta WHERE key='sync_count'"
        ).fetchone()
        if row:
            self._update_sync_count(int(row[0]) + 1)

    def keyword_search(self, query, top_k=15):
        """FTS5 keyword search with BM25 ranking."""
        sanitized = self._sanitize_fts_query(query)
        if not sanitized:
            return []

        try:
            rows = self.conn.execute("""
                SELECT l.memory_id, f.preview, l.tags, l.timestamp,
                       rank * -1 as score
                FROM mem_fts f
                JOIN mem_lookup l ON l.fts_rowid = f.rowid
                WHERE mem_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """, (sanitized, top_k)).fetchall()
        except sqlite3.OperationalError:
            return []

        results = []
        for row in rows:
            results.append({
                "id": row[0],
                "preview": row[1],
                "tags": row[2],
                "timestamp": row[3],
                "fts_score": round(row[4], 4),
            })
        return results

    def tag_search(self, tags_list, match_all=False, top_k=15):
        """Exact tag matching via normalized tag table."""
        if not tags_list:
            return []

        if match_all:
            # All tags must be present
            placeholders = ",".join("?" * len(tags_list))
            query = f"""
                SELECT t.memory_id, l.tags, l.timestamp,
                       (SELECT preview FROM mem_fts WHERE rowid = l.fts_rowid) as preview
                FROM tags t
                JOIN mem_lookup l ON l.memory_id = t.memory_id
                WHERE t.tag IN ({placeholders})
                GROUP BY t.memory_id
                HAVING COUNT(DISTINCT t.tag) = ?
                LIMIT ?
            """
            rows = self.conn.execute(query, (*tags_list, len(tags_list), top_k)).fetchall()
        else:
            # Any tag matches
            placeholders = ",".join("?" * len(tags_list))
            query = f"""
                SELECT DISTINCT t.memory_id, l.tags, l.timestamp,
                       (SELECT preview FROM mem_fts WHERE rowid = l.fts_rowid) as preview
                FROM tags t
                JOIN mem_lookup l ON l.memory_id = t.memory_id
                WHERE t.tag IN ({placeholders})
                LIMIT ?
            """
            rows = self.conn.execute(query, (*tags_list, top_k)).fetchall()

        results = []
        for row in rows:
            results.append({
                "id": row[0],
                "tags": row[1],
                "timestamp": row[2],
                "preview": row[3] or "(no preview)",
            })
        return results

    def get_preview(self, memory_id):
        """Get preview + metadata for a single memory ID."""
        row = self.conn.execute("""
            SELECT l.tags, l.timestamp,
                   (SELECT preview FROM mem_fts WHERE rowid = l.fts_rowid) as preview
            FROM mem_lookup l
            WHERE l.memory_id = ?
        """, (memory_id,)).fetchone()
        if not row:
            return None
        return {"id": memory_id, "tags": row[0], "timestamp": row[1], "preview": row[2]}

    @staticmethod
    def _sanitize_fts_query(query):
        """Strip FTS5 special characters to prevent query crashes."""
        # Remove FTS5 operators that could cause syntax errors
        sanitized = re.sub(r'[*(){}[\]^~"\'\\:;!@#$%&+=|<>]', " ", query)
        # Collapse whitespace
        sanitized = re.sub(r"\s+", " ", sanitized).strip()
        return sanitized


def _detect_query_mode(query):
    """Route queries to the appropriate search engine.

    Returns one of: 'tags', 'keyword', 'semantic', 'hybrid'.
    """
    q = query.strip()
    ql = q.lower()

    # Tag queries: explicit tag: or tags: prefix
    if ql.startswith("tag:") or ql.startswith("tags:"):
        return "tags"

    # Keyword: quoted phrases or boolean operators
    if '"' in q or " AND " in q or " OR " in q:
        return "keyword"

    words = q.split()

    # Keyword: 1-2 word queries (likely identifiers or exact terms)
    if len(words) <= 2:
        return "keyword"

    # Semantic: questions or long natural language
    if ql.endswith("?") or ql.startswith(("how ", "why ", "what ", "when ", "where ", "which ")):
        return "semantic"
    if len(words) >= 5:
        return "semantic"

    # Hybrid: 3-4 word ambiguous queries
    return "hybrid"


def _apply_recency_boost(results, recency_weight=0.15):
    """Apply temporal recency boost to search results.

    Adjusts relevance scores so newer entries rank slightly higher.
    adjusted_relevance = raw_relevance + (recency_weight * max(0, 1 - age_days/365))

    Args:
        results: List of result dicts with optional 'relevance' and 'timestamp' fields
        recency_weight: How much to boost recent results (0.0-1.0, default 0.15)
    Returns:
        Results list re-sorted by adjusted relevance
    """
    if not results or recency_weight <= 0:
        return results

    now = datetime.now()
    for entry in results:
        raw_relevance = entry.get("relevance", 0) or entry.get("fts_score", 0) or 0
        timestamp_str = entry.get("timestamp", "")
        boost = 0.0
        if timestamp_str:
            try:
                entry_time = datetime.fromisoformat(timestamp_str)
                age_days = max(0, (now - entry_time).total_seconds() / 86400)
                boost = recency_weight * max(0, 1 - age_days / 365)
            except (ValueError, TypeError):
                pass  # No boost if timestamp parsing fails
        entry["_adjusted_relevance"] = raw_relevance + boost

    results.sort(key=lambda x: x.get("_adjusted_relevance", 0), reverse=True)

    # Clean up internal key
    for entry in results:
        entry.pop("_adjusted_relevance", None)

    return results


def _merge_results(fts_results, chroma_summaries, top_k=15):
    """Merge FTS5 and ChromaDB results, dedup by memory_id.

    Entries appearing in both sources get a +0.1 relevance bonus.
    """
    seen = {}  # memory_id -> entry

    # Add ChromaDB results first (they have relevance scores)
    for entry in chroma_summaries:
        mid = entry.get("id", "")
        if mid:
            seen[mid] = dict(entry)

    # Merge FTS5 results
    for entry in fts_results:
        mid = entry.get("id", "")
        if not mid:
            continue
        if mid in seen:
            # Boost: appeared in both semantic + keyword
            if "relevance" in seen[mid]:
                seen[mid]["relevance"] = min(1.0, seen[mid]["relevance"] + 0.1)
            seen[mid]["match"] = "both"
        else:
            seen[mid] = dict(entry)
            seen[mid]["match"] = "keyword"

    # Sort: items with relevance first (descending), then by fts_score
    results = list(seen.values())
    results.sort(key=lambda x: (x.get("relevance", 0), x.get("fts_score", 0)), reverse=True)

    return results[:top_k]


# Lazy initialization — only run when module is used as a server, not when imported
# for testing. ChromaDB Rust backend segfaults on concurrent PersistentClient access.
_preview_migrated = False
fts_index = FTS5Index(db_path=FTS5_DB_PATH)
_fts_count = 0
_initialized = False


def _ensure_initialized():
    """Run one-time initialization (ChromaDB client + preview migration + FTS5 build).

    Called lazily on first MCP tool use or explicitly at server startup.
    Safe to call multiple times — idempotent after first run.
    If the on-disk FTS5 index is already in sync with ChromaDB (by count),
    the expensive rebuild is skipped entirely.
    """
    global _preview_migrated, fts_index, _fts_count, _initialized
    if _initialized:
        return
    _init_chromadb()
    _preview_migrated = _migrate_previews()

    # Check if persisted FTS5 is already synced with ChromaDB
    chroma_count = collection.count()
    if fts_index.is_synced(chroma_count):
        _fts_count = chroma_count
        _initialized = True
        return  # Skip rebuild — disk FTS5 is current

    _fts_count = fts_index.build_from_chromadb(collection)
    _initialized = True

# ──────────────────────────────────────────────────
# Tag Co-occurrence Matrix (lazy-built, cached)
# ──────────────────────────────────────────────────
_tag_cooccurrence: dict[str, dict[str, int]] = {}  # tag_a -> {tag_b: count}
_tag_counts: dict[str, int] = {}  # tag -> total memories with this tag
_tag_cooccurrence_dirty: bool = True  # rebuild on first use


def _build_tag_cooccurrence():
    """Build tag co-occurrence matrix from FTS5 tag index.

    Scans all memory tags, counts how often tag pairs appear together.
    Called lazily on first search or explicitly via rebuild_tag_index().
    """
    global _tag_cooccurrence, _tag_counts, _tag_cooccurrence_dirty

    conn = fts_index.conn
    rows = conn.execute("SELECT memory_id, tag FROM tags").fetchall()

    # Group tags by memory_id
    mem_tags: dict[str, set[str]] = {}
    tag_totals: dict[str, int] = {}
    for mid, tag in rows:
        mem_tags.setdefault(mid, set()).add(tag)
        tag_totals[tag] = tag_totals.get(tag, 0) + 1

    # Build co-occurrence counts
    cooccur: dict[str, dict[str, int]] = {}
    for _mid, tagset in mem_tags.items():
        tags = list(tagset)
        for i in range(len(tags)):
            for j in range(len(tags)):
                if i != j:
                    cooccur.setdefault(tags[i], {})
                    cooccur[tags[i]][tags[j]] = cooccur[tags[i]].get(tags[j], 0) + 1

    _tag_cooccurrence = cooccur
    _tag_counts = tag_totals
    _tag_cooccurrence_dirty = False


def _get_expanded_tags(query: str) -> list[str]:
    """Find tags that co-occur with tags matching the query (>40% rate).

    Checks if query text matches any known tags, then returns co-occurring
    tags above the 40% co-occurrence threshold.
    """
    if _tag_cooccurrence_dirty:
        _build_tag_cooccurrence()

    if not _tag_counts:
        return []

    query_lower = query.lower().strip()
    query_tokens = set(query_lower.split())

    # Match query against known tags (substring or token match)
    matched_tags = []
    for tag in _tag_counts:
        tag_lower = tag.lower()
        # Exact match, substring, or token overlap
        if tag_lower == query_lower or tag_lower in query_lower or tag_lower in query_tokens:
            matched_tags.append(tag)

    if not matched_tags:
        return []

    # Find co-occurring tags above 40% threshold
    expanded = set()
    matched_set = set(matched_tags)
    for tag in matched_tags:
        if tag not in _tag_cooccurrence:
            continue
        tag_total = _tag_counts.get(tag, 1)
        for co_tag, count in _tag_cooccurrence[tag].items():
            rate = count / tag_total
            if rate > 0.4 and co_tag not in matched_set:
                expanded.add(co_tag)

    return list(expanded)


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


def format_summaries(results) -> list[dict]:
    """Format ChromaDB query results into compact summaries (id + preview).

    Returns lightweight entries for progressive disclosure. Use get_memory(id)
    to retrieve full content for specific entries.

    Handles both query() results (nested ids[0]) and get() results (flat ids).
    Supports metadata-only queries (documents=None) by using stored preview field.
    Also tracks retrieval counts for stale memory detection.
    """
    if not results:
        return []

    # Detect query() vs get() result structure
    ids_raw = results.get("ids", [])
    docs_raw = results.get("documents")  # May be None for metadata-only queries
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
        docs = docs_raw if docs_raw else []
        metas = metas_raw
        distances = []

    if not ids:
        return []

    formatted = []
    retrieval_update_ids = []
    retrieval_update_metas = []
    now_iso = datetime.now().isoformat()

    for i in range(len(ids)):
        meta = metas[i] if i < len(metas) and metas else {}

        # Prefer stored preview from metadata; fall back to doc truncation
        if meta and meta.get("preview"):
            preview = meta["preview"]
        elif i < len(docs) and docs[i]:
            doc = docs[i]
            preview = doc[:SUMMARY_LENGTH].replace("\n", " ")
            if len(doc) > SUMMARY_LENGTH:
                preview += "..."
        else:
            preview = "(no preview available)"

        entry = {
            "id": ids[i] if i < len(ids) else "",
            "preview": preview,
        }
        if i < len(distances) and distances:
            entry["relevance"] = round(1 - distances[i], 3)
        if meta:
            entry["tags"] = meta.get("tags", "")
            entry["timestamp"] = meta.get("timestamp", "")
        formatted.append(entry)

        # Queue retrieval tracking update
        if meta and ids[i]:
            updated_meta = dict(meta)
            updated_meta["retrieval_count"] = int(meta.get("retrieval_count", 0)) + 1
            updated_meta["last_retrieved"] = now_iso
            retrieval_update_ids.append(ids[i])
            retrieval_update_metas.append(updated_meta)

    # Batch update retrieval counts (fire-and-forget)
    if retrieval_update_ids:
        try:
            collection.update(ids=retrieval_update_ids, metadatas=retrieval_update_metas)
        except Exception:
            pass  # Tracking failure must not break search

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

        cutoff = time.time() - (OBSERVATION_TTL_DAYS * 86400)

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
                    "session_time": time.time(),
                }],
                ids=[digest_id],
            )

            # Promote high-value expired observations to curated knowledge
            promoted = 0
            for i, doc in enumerate(exp_docs):
                if promoted >= MAX_PROMOTIONS_PER_CYCLE:
                    break
                meta = exp_metas[i] if i < len(exp_metas) else {}
                ep = meta.get("error_pattern", "")
                has_error = meta.get("has_error", "false")
                if ep or has_error == "true":
                    promo_id = hashlib.sha256(
                        f"promoted:{doc}".encode()
                    ).hexdigest()[:16]
                    promo_preview = doc[:SUMMARY_LENGTH].replace("\n", " ")
                    if len(doc) > SUMMARY_LENGTH:
                        promo_preview += "..."
                    collection.upsert(
                        documents=[doc],
                        metadatas=[{
                            "context": "auto-promoted from observation",
                            "tags": PROMOTION_TAGS,
                            "timestamp": datetime.now().isoformat(),
                            "session_time": time.time(),
                            "preview": promo_preview,
                            "original_error_pattern": ep,
                        }],
                        ids=[promo_id],
                    )
                    promoted += 1

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
@crash_proof
def search_knowledge(query: str, top_k: int = 15, mode: str = "", recency_weight: float = 0.15) -> dict:
    """Search memory for relevant information. Use before starting any task.

    Args:
        query: What to search for (semantic search)
        top_k: Number of results to return (default 15)
        mode: Force search mode ("keyword", "semantic", "hybrid", "tags"). Empty = auto-detect.
        recency_weight: Boost for recent results (0.0-1.0, default 0.15). 0 disables.
    """
    recency_weight = max(0.0, min(1.0, recency_weight))
    top_k = _validate_top_k(top_k, default=15, min_val=1, max_val=500)
    count = collection.count()
    if count == 0:
        return {"results": [], "total_memories": 0, "message": "Memory is empty. Start building knowledge with remember_this()."}

    VALID_MODES = {"keyword", "semantic", "hybrid", "tags"}
    if mode and mode not in VALID_MODES:
        mode = ""  # Invalid mode falls back to auto-detect
    if not mode:
        mode = _detect_query_mode(query)
    actual_k = min(top_k, count)

    if mode == "tags":
        # Strip tag:/tags: prefix and parse
        tag_query = re.sub(r"^tags?:\s*", "", query, flags=re.IGNORECASE)
        tags_list = [t.strip() for t in tag_query.split(",") if t.strip()]
        formatted = fts_index.tag_search(tags_list, match_all=False, top_k=actual_k)
    elif mode == "keyword":
        formatted = fts_index.keyword_search(query, top_k=actual_k)
    elif mode == "hybrid":
        # Both engines, merged
        fts_results = fts_index.keyword_search(query, top_k=actual_k)
        chroma_results = collection.query(
            query_texts=[query], n_results=actual_k,
            include=["metadatas", "distances"],
        )
        chroma_summaries = format_summaries(chroma_results)
        formatted = _merge_results(fts_results, chroma_summaries, top_k=actual_k)
    else:
        # Semantic (default)
        results = collection.query(
            query_texts=[query], n_results=actual_k,
            include=["metadatas", "distances"],
        )
        formatted = format_summaries(results)

    # Tag expansion: find co-occurring tags and merge additional results
    tag_expanded = False
    expanded_tags = []
    try:
        expanded_tags = _get_expanded_tags(query)
        if expanded_tags:
            tag_results = fts_index.tag_search(expanded_tags, match_all=False, top_k=actual_k)
            if tag_results:
                # Merge: deduplicate by ID, keep highest relevance
                seen_ids = {r.get("id") for r in formatted if r.get("id")}
                for tr in tag_results:
                    tid = tr.get("id", "")
                    if tid and tid not in seen_ids:
                        tr["tag_expanded"] = True
                        formatted.append(tr)
                        seen_ids.add(tid)
                tag_expanded = True
    except Exception:
        pass  # Tag expansion failure must not break search

    # Apply recency boost and re-sort
    if recency_weight > 0:
        formatted = _apply_recency_boost(formatted, recency_weight)

    # Trim to requested top_k after expansion
    formatted = formatted[:top_k]

    _touch_memory_timestamp()

    result = {
        "results": formatted,
        "total_memories": count,
        "query": query,
        "mode": mode,
    }
    if tag_expanded:
        result["tag_expanded"] = True
        result["expanded_tags"] = expanded_tags
    return result


@mcp.tool()
@crash_proof
def remember_this(content: str, context: str = "", tags: str = "") -> dict:
    """Save something to persistent memory. Use after every fix, discovery, or decision.

    Args:
        content: The knowledge to remember (be specific and detailed)
        context: What you were doing when you learned this
        tags: Comma-separated tags for categorization (e.g., "bug,fix,auth")
    """
    # --- Ingestion filter: reject noise ---
    if len(content.strip()) < MIN_CONTENT_LENGTH:
        return {
            "result": "Rejected: content too short (minimum 20 characters)",
            "rejected": True,
            "total_memories": collection.count(),
        }

    for noise_re in NOISE_REGEXES:
        if noise_re.search(content):
            return {
                "result": f"Rejected: matches noise pattern ('{noise_re.pattern}')",
                "rejected": True,
                "total_memories": collection.count(),
            }

    # --- Near-dedup: skip if >95% similar entry already exists ---
    try:
        count = collection.count()
        if count > 0:
            similar = collection.query(
                query_texts=[content], n_results=1,
                include=["distances"],
            )
            if (similar and similar.get("distances") and similar["distances"][0]
                    and similar["distances"][0][0] < DEDUP_THRESHOLD):
                existing_id = similar["ids"][0][0]
                return {
                    "result": "Deduplicated: very similar memory already exists",
                    "existing_id": existing_id,
                    "distance": round(similar["distances"][0][0], 4),
                    "total_memories": count,
                }
    except Exception:
        pass  # Dedup failure falls through to normal save

    doc_id = generate_id(content)
    timestamp = datetime.now().isoformat()

    # Pre-compute preview for progressive disclosure (stored in metadata)
    preview = content[:SUMMARY_LENGTH].replace("\n", " ")
    if len(content) > SUMMARY_LENGTH:
        preview += "..."

    now = time.time()

    collection.upsert(
        documents=[content],
        metadatas=[{
            "context": context,
            "tags": tags,
            "timestamp": timestamp,
            "session_time": now,
            "preview": preview,
        }],
        ids=[doc_id],
    )

    # Dual-write: keep FTS5 index in sync
    fts_index.add_entry(doc_id, content, preview, tags, timestamp, now)

    # Mark tag co-occurrence matrix as dirty (new tags may change co-occurrence rates)
    global _tag_cooccurrence_dirty
    if tags:
        _tag_cooccurrence_dirty = True

    _touch_memory_timestamp()

    return {
        "result": "Memory stored successfully!",
        "id": doc_id,
        "total_memories": collection.count(),
        "timestamp": timestamp,
    }


@mcp.tool()
@crash_proof
def deep_query(query: str, top_k: int = 50, recency_weight: float = 0.15) -> dict:
    """Comprehensive memory search — use for important decisions or debugging recurring issues.

    Returns more results than search_knowledge for thorough analysis.

    Args:
        query: What to search for
        top_k: Number of results (default 50)
        recency_weight: Boost for recent results (0.0-1.0, default 0.15). 0 disables.
    """
    recency_weight = max(0.0, min(1.0, recency_weight))
    top_k = _validate_top_k(top_k, default=50, min_val=1, max_val=500)
    count = collection.count()
    if count == 0:
        return {"results": [], "total_memories": 0, "message": "Memory is empty."}

    actual_k = min(top_k, count)
    results = collection.query(
        query_texts=[query], n_results=actual_k,
        include=["metadatas", "distances"],
    )
    formatted = format_summaries(results)

    # Apply recency boost and re-sort
    if recency_weight > 0:
        formatted = _apply_recency_boost(formatted, recency_weight)

    _touch_memory_timestamp()

    return {
        "results": formatted,
        "total_memories": count,
        "query": query,
        "depth": "comprehensive",
    }


@mcp.tool()
@crash_proof
def get_recent_activity(hours: int = 48) -> dict:
    """Get recent memory saves chronologically. Good for session startup.

    Args:
        hours: How far back to look (default 48 hours)
    """
    hours = _validate_hours(hours, default=48, min_val=1, max_val=720)
    count = collection.count()
    if count == 0:
        return {"results": [], "total_memories": 0, "message": "Memory is empty."}

    cutoff = time.time() - (hours * 3600)
    cutoff_iso = (datetime.now() - timedelta(hours=hours)).isoformat()

    # Get all recent entries (ChromaDB where filter on metadata)
    try:
        results = collection.get(
            where={"session_time": {"$gte": cutoff}},
            limit=100,
        )
    except Exception:
        # Fallback: get most recent by querying with broad term
        results = collection.query(
            query_texts=["recent activity work session"],
            n_results=min(50, count),
            include=["metadatas", "distances"],
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
@crash_proof
def get_memory(id: str) -> dict:
    """Retrieve full content for a specific memory by ID.

    Use after search_knowledge/deep_query to get complete details for relevant entries.

    Args:
        id: The memory ID (from search results)
    """
    try:
        # Support batch fetch: comma-separated IDs return multiple memories
        ids = [i.strip() for i in id.split(",") if i.strip()]
        if not ids:
            return {"error": "No valid ID provided"}

        result = collection.get(ids=ids, include=["documents", "metadatas"])
        if not result or not result.get("documents") or len(result["documents"]) == 0:
            return {"error": f"No memory found with id: {id}"}

        entries = []
        for i, doc in enumerate(result["documents"]):
            entry = {
                "id": ids[i] if i < len(ids) else "unknown",
                "content": doc,
            }
            if result.get("metadatas") and i < len(result["metadatas"]) and result["metadatas"][i]:
                meta = result["metadatas"][i]
                entry["context"] = meta.get("context", "")
                entry["tags"] = meta.get("tags", "")
                entry["timestamp"] = meta.get("timestamp", "")

                # Retrieval tracking: increment count and update timestamp
                try:
                    retrieval_count = int(meta.get("retrieval_count", 0)) + 1
                    updated_meta = dict(meta)
                    updated_meta["retrieval_count"] = retrieval_count
                    updated_meta["last_retrieved"] = datetime.now().isoformat()
                    collection.update(ids=[ids[i]], metadatas=[updated_meta])
                except Exception:
                    pass  # Tracking failure must not break retrieval

            entries.append(entry)

        _touch_memory_timestamp()
        # Single ID: return single entry (backward compatible)
        return entries[0] if len(entries) == 1 else {"memories": entries, "count": len(entries)}

    except Exception as e:
        return {"error": f"Failed to retrieve memory: {str(e)}"}


@mcp.tool()
@crash_proof
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
        "collections": ["knowledge", "observations", "fix_outcomes", "web_pages"],
        "fts_index_count": _fts_count,
        "status": "healthy" if count >= 0 else "error",
    }


@mcp.tool()
@crash_proof
def search_by_tags(tags: str, match_all: bool = False, top_k: int = 15) -> dict:
    """Search memories by exact tag matching.

    Faster than semantic search for finding memories with specific tags.
    Uses the FTS5 normalized tag index.

    Args:
        tags: Comma-separated tags to search for (e.g., "type:fix,area:framework")
        match_all: If true, all tags must be present. If false, any tag matches (default false)
        top_k: Maximum number of results (default 15)
    """
    tags_list = [t.strip() for t in tags.split(",") if t.strip()]
    if not tags_list:
        return {"results": [], "message": "No tags provided"}

    top_k = _validate_top_k(top_k, default=15, min_val=1, max_val=500)
    results = fts_index.tag_search(tags_list, match_all=match_all, top_k=top_k)

    _touch_memory_timestamp()

    return {
        "results": results,
        "total_results": len(results),
        "tags_searched": tags_list,
        "match_mode": "all" if match_all else "any",
    }


@mcp.tool()
@crash_proof
def search_observations(query: str, top_k: int = 20, hours: int = 0, sentiment: str = "") -> dict:
    """Search auto-captured observations (tool calls, errors, prompts).

    Unlike curated memories, observations are passively captured from every
    Bash, Edit, Write, and NotebookEdit tool call. Use this to find past
    commands, errors, or patterns.

    Args:
        query: What to search for (semantic search)
        top_k: Number of results to return (default 20)
        hours: If > 0, only return observations from the last N hours
        sentiment: Filter by sentiment value (frustration, confidence, uncertainty, neutral). Empty = no filter.
    """
    top_k = _validate_top_k(top_k, default=20, min_val=1, max_val=100)

    # Flush queue to ensure latest data
    _flush_capture_queue()

    count = observations.count()
    if count == 0:
        return {"results": [], "total_observations": 0, "message": "No observations yet."}

    actual_k = min(top_k, count)

    # Build where clause from optional filters
    where_clauses = []
    if hours > 0:
        cutoff = time.time() - (hours * 3600)
        where_clauses.append({"session_time": {"$gte": cutoff}})
    if sentiment and sentiment in ("frustration", "confidence", "uncertainty", "neutral"):
        where_clauses.append({"sentiment": sentiment})

    where = None
    if len(where_clauses) == 1:
        where = where_clauses[0]
    elif len(where_clauses) > 1:
        where = {"$and": where_clauses}

    try:
        if where:
            results = observations.query(
                query_texts=[query],
                n_results=actual_k,
                where=where,
            )
        else:
            results = observations.query(query_texts=[query], n_results=actual_k)
    except Exception:
        # Fallback: query without filters if ChromaDB rejects the where clause
        results = observations.query(query_texts=[query], n_results=actual_k)

    formatted = format_summaries(results)

    _touch_memory_timestamp()

    return {
        "results": formatted,
        "total_observations": count,
        "query": query,
    }


@mcp.tool()
@crash_proof
def get_session_sentiment(hours: int = 24) -> dict:
    """Get sentiment distribution for recent user interactions.

    Analyzes captured UserPrompt observations to show how the user has been
    feeling during the session. Useful for detecting frustration patterns
    and adjusting approach.

    Args:
        hours: Time window in hours (default 24). Set to 1-2 for current session.
    """
    hours = max(1, min(hours, 168))  # Cap at 1 week

    # Flush queue to ensure latest data
    _flush_capture_queue()

    count = observations.count()
    if count == 0:
        return {
            "distribution": {"frustration": 0, "confidence": 0, "uncertainty": 0, "neutral": 0},
            "dominant": "neutral",
            "total": 0,
            "insight": "No observations captured yet.",
        }

    cutoff = time.time() - (hours * 3600)

    try:
        # Get UserPrompt observations within time window
        results = observations.get(
            where={"$and": [
                {"tool_name": "UserPrompt"},
                {"session_time": {"$gte": cutoff}},
            ]},
            limit=min(count, 500),
            include=["metadatas"],
        )
    except Exception:
        try:
            # Fallback: just get UserPrompt observations without time filter
            results = observations.get(
                where={"tool_name": "UserPrompt"},
                limit=min(count, 500),
                include=["metadatas"],
            )
        except Exception:
            return {
                "distribution": {"frustration": 0, "confidence": 0, "uncertainty": 0, "neutral": 0},
                "dominant": "neutral",
                "total": 0,
                "insight": "Could not query observations.",
            }

    dist = {"frustration": 0, "confidence": 0, "uncertainty": 0, "neutral": 0}
    metas = results.get("metadatas") or []

    for meta in metas:
        if not meta:
            continue
        sentiment = meta.get("sentiment", "neutral")
        if sentiment in dist:
            dist[sentiment] += 1
        else:
            dist["neutral"] += 1

    total = sum(dist.values())
    dominant = max(dist, key=dist.get) if total > 0 else "neutral"

    # Generate brief insight
    if total == 0:
        insight = "No user prompts captured in the last {} hours.".format(hours)
    elif dist["frustration"] > total * 0.4:
        insight = "High frustration detected ({}/{} prompts). Consider verifying approach and checking memory for repeated issues.".format(dist["frustration"], total)
    elif dist["confidence"] > total * 0.4:
        insight = "User appears satisfied ({}/{} positive prompts). Current approach is working well.".format(dist["confidence"], total)
    elif dist["uncertainty"] > total * 0.4:
        insight = "User seems uncertain ({}/{} prompts). Consider providing more explanation or asking clarifying questions.".format(dist["uncertainty"], total)
    else:
        insight = "Mixed sentiment across {} prompts. Dominant: {}.".format(total, dominant)

    _touch_memory_timestamp()

    return {
        "distribution": dist,
        "dominant": dominant,
        "total": total,
        "insight": insight,
    }


@mcp.tool()
@crash_proof
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
@crash_proof
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
    start = anchor_epoch - window_secs
    end = anchor_epoch + window_secs

    limit = _validate_top_k(limit, default=20, min_val=1, max_val=100)

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
@crash_proof
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
@crash_proof
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
@crash_proof
def query_fix_history(error_text: str, top_k: int = 10) -> dict:
    """Query fix history for a given error to find what strategies worked or failed.

    Args:
        error_text: The error message to look up
        top_k: Maximum number of results (default 10)
    """
    top_k = _validate_top_k(top_k, default=10, min_val=1, max_val=100)
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


def suggest_promotions(top_k: int = 5) -> dict:
    """Suggest memory entries that should be promoted to permanent rules.

    Finds clusters of similar error/learning/correction memories and ranks them
    by frequency and recency. High-scoring clusters indicate recurring patterns
    that may warrant a permanent rule in CLAUDE.md.

    Args:
        top_k: Number of top clusters to return (default 5)
    """
    top_k = _validate_top_k(top_k, default=5, min_val=1, max_val=50)
    count = collection.count()
    if count == 0:
        return {"clusters": [], "message": "Memory is empty."}

    # Query for promotable memory types
    promotion_tags = ["type:error", "type:learning", "type:correction"]
    candidates = []

    for tag in promotion_tags:
        try:
            tag_results = fts_index.tag_search([tag], match_all=False, top_k=200)
            for r in tag_results:
                if r.get("id") and r["id"] not in [c["id"] for c in candidates]:
                    candidates.append(r)
        except Exception:
            continue

    if not candidates:
        return {"clusters": [], "message": "No promotable memories found (need type:error, type:learning, or type:correction tags)."}

    # Get embeddings for clustering via ChromaDB
    candidate_ids = [c["id"] for c in candidates]

    # Build a lookup from id -> candidate info
    id_to_candidate = {c["id"]: c for c in candidates}

    # Batch fetch all candidate documents to avoid N+1 queries
    id_to_doc = {}
    try:
        batch_docs = collection.get(ids=candidate_ids, include=["documents"])
        if batch_docs and batch_docs.get("ids") and batch_docs.get("documents"):
            for doc_id, doc_text in zip(batch_docs["ids"], batch_docs["documents"]):
                if doc_text:
                    id_to_doc[doc_id] = doc_text
    except Exception:
        pass

    # Cluster similar memories using ChromaDB cosine distance
    # For each candidate, find others within distance 0.3
    clusters = []  # list of sets of ids
    clustered = set()

    for cand in candidates:
        cid = cand["id"]
        if cid in clustered:
            continue

        # Find similar entries to this one using its content
        try:
            # Get full content for this entry from batch lookup
            doc_text = id_to_doc.get(cid)
            if not doc_text:
                clustered.add(cid)
                clusters.append({cid})
                continue
            similar = collection.query(
                query_texts=[doc_text],
                n_results=min(50, count),
                include=["distances"],
            )

            cluster = {cid}
            if similar and similar.get("ids") and similar["ids"][0]:
                sim_ids = similar["ids"][0]
                sim_dists = similar["distances"][0] if similar.get("distances") else []
                candidate_id_set = set(candidate_ids)
                for i, sid in enumerate(sim_ids):
                    if sid in candidate_id_set and sid not in clustered:
                        dist = sim_dists[i] if i < len(sim_dists) else 1.0
                        if dist <= 0.3:
                            cluster.add(sid)

            for mid in cluster:
                clustered.add(mid)
            clusters.append(cluster)

        except Exception:
            clustered.add(cid)
            clusters.append({cid})

    # Score each cluster: score = (count * 2) + recency_bonus
    now = datetime.now()
    scored_clusters = []

    for cluster_ids in clusters:
        member_count = len(cluster_ids)
        # Calculate average age and recency bonus
        ages = []
        best_preview = ""
        best_score = -1
        member_id_list = list(cluster_ids)

        for mid in member_id_list:
            cand = id_to_candidate.get(mid, {})
            ts = cand.get("timestamp", "")
            if ts:
                try:
                    entry_time = datetime.fromisoformat(ts)
                    age_days = max(0, (now - entry_time).total_seconds() / 86400)
                    ages.append(age_days)
                except (ValueError, TypeError):
                    pass

            # Track highest-scored member for the suggested rule
            preview = cand.get("preview", "")
            # Simple score: shorter age = higher score
            member_score = member_count
            if ages:
                member_score += max(0, 1 - ages[-1] / 365)
            if member_score > best_score:
                best_score = member_score
                best_preview = preview

        avg_age = sum(ages) / len(ages) if ages else 365
        recency_bonus = max(0, 1 - avg_age / 365)
        score = (member_count * 2) + recency_bonus

        scored_clusters.append({
            "suggested_rule": best_preview[:200],
            "supporting_ids": member_id_list,
            "count": member_count,
            "score": round(score, 3),
            "avg_age_days": round(avg_age, 1),
        })

    # Sort by score descending and take top_k
    scored_clusters.sort(key=lambda x: x["score"], reverse=True)
    top_clusters = scored_clusters[:top_k]

    return {
        "clusters": top_clusters,
        "total_candidates": len(candidates),
        "total_clusters": len(clusters),
    }


def list_stale_memories(days: int = 60, top_k: int = 20) -> dict:
    """Find memories that haven't been retrieved recently.

    Returns memories older than `days` with zero or low retrieval counts,
    sorted by age (oldest first). Useful for identifying knowledge that may
    be outdated or irrelevant for cleanup.

    Args:
        days: Age threshold in days (default 60). Only memories older than this are returned.
        top_k: Maximum number of results (default 20).
    """
    days = max(1, min(days, 3650))
    top_k = _validate_top_k(top_k, default=20, min_val=1, max_val=200)

    try:
        count = collection.count()
        if count == 0:
            return {"results": [], "total_memories": 0, "message": "Memory is empty."}

        cutoff = time.time() - (days * 86400)

        # Query memories older than the threshold
        try:
            old_memories = collection.get(
                where={"session_time": {"$lt": cutoff}},
                limit=min(count, 500),
                include=["documents", "metadatas"],
            )
        except Exception:
            # Fallback: get all and filter manually
            old_memories = collection.get(
                limit=min(count, 500),
                include=["documents", "metadatas"],
            )

        if not old_memories or not old_memories.get("ids"):
            return {"results": [], "total_memories": count, "message": "No memories found matching criteria."}

        ids = old_memories["ids"]
        docs = old_memories.get("documents") or []
        metas = old_memories.get("metadatas") or []

        now = time.time()
        stale = []

        for i, mid in enumerate(ids):
            meta = metas[i] if i < len(metas) else {}
            doc = docs[i] if i < len(docs) else ""

            retrieval_count = int(meta.get("retrieval_count", 0))

            # Only include memories with zero or low retrievals
            if retrieval_count > 2:
                continue

            # Calculate age
            session_time = meta.get("session_time")
            if session_time is not None:
                try:
                    age_seconds = now - float(session_time)
                except (ValueError, TypeError):
                    age_seconds = days * 86400  # Assume old if unparseable
            else:
                age_seconds = days * 86400

            age_days = round(age_seconds / 86400, 1)

            # Filter by age threshold (needed for fallback path)
            if age_days < days:
                continue

            preview = meta.get("preview", "")
            if not preview and doc:
                preview = doc[:100].replace("\n", " ")
                if len(doc) > 100:
                    preview += "..."

            stale.append({
                "id": mid,
                "preview": preview[:100],
                "age_days": age_days,
                "retrieval_count": retrieval_count,
                "last_retrieved": meta.get("last_retrieved", "never"),
                "tags": meta.get("tags", ""),
            })

        # Sort by age descending (oldest first)
        stale.sort(key=lambda x: x["age_days"], reverse=True)

        return {
            "results": stale[:top_k],
            "total_stale": len(stale),
            "total_memories": count,
            "threshold_days": days,
        }

    except Exception as e:
        return {"error": f"Failed to list stale memories: {str(e)}"}


def cluster_knowledge(min_cluster_size: int = 3, distance_threshold: float = 0.3) -> dict:
    """Group related memories into semantic clusters using ChromaDB distance queries.

    Uses a union-find algorithm over ChromaDB neighbor queries to discover
    clusters of related knowledge. Useful for finding themes, redundancies,
    and knowledge gaps.

    Args:
        min_cluster_size: Minimum memories in a cluster to be returned (default 3)
        distance_threshold: Max cosine distance to consider memories related (default 0.3, range 0.05-0.8)
    """
    min_cluster_size = max(2, min(min_cluster_size, 20))
    distance_threshold = _validate_distance_threshold(distance_threshold, default=0.3, min_val=0.05, max_val=0.8)

    count = collection.count()
    if count == 0:
        return {"clusters": [], "total_memories": 0, "message": "Memory is empty."}

    # Fetch all memories
    try:
        all_data = collection.get(
            limit=count,
            include=["metadatas", "documents"],
        )
    except Exception as e:
        return {"clusters": [], "error": f"Failed to fetch memories: {str(e)}"}

    if not all_data or not all_data.get("ids"):
        return {"clusters": [], "total_memories": 0}

    ids = all_data["ids"]
    docs = all_data.get("documents") or []
    metas = all_data.get("metadatas") or []

    n = len(ids)
    if n < min_cluster_size:
        return {"clusters": [], "total_memories": n, "message": f"Not enough memories ({n}) for clustering."}

    # Build id -> index mapping
    id_to_idx = {mid: i for i, mid in enumerate(ids)}

    # Union-Find data structure
    parent = list(range(n))
    rank = [0] * n

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]  # path compression
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        if rank[ra] < rank[rb]:
            ra, rb = rb, ra
        parent[rb] = ra
        if rank[ra] == rank[rb]:
            rank[ra] += 1

    # For each memory, find neighbors within distance_threshold
    # Process in batches to avoid overwhelming ChromaDB
    neighbor_k = min(30, n)  # Check up to 30 nearest neighbors per memory

    for i in range(n):
        doc = docs[i] if i < len(docs) and docs[i] else None
        if not doc:
            continue

        try:
            neighbors = collection.query(
                query_texts=[doc],
                n_results=neighbor_k,
                include=["distances"],
            )

            if not neighbors or not neighbors.get("ids") or not neighbors["ids"][0]:
                continue

            neighbor_ids = neighbors["ids"][0]
            neighbor_dists = neighbors["distances"][0] if neighbors.get("distances") else []

            for j, nid in enumerate(neighbor_ids):
                if nid == ids[i]:
                    continue  # skip self
                dist = neighbor_dists[j] if j < len(neighbor_dists) else 1.0
                if dist <= distance_threshold and nid in id_to_idx:
                    union(i, id_to_idx[nid])

        except Exception:
            continue

    # Collect clusters
    clusters_map = {}  # root_idx -> [member_indices]
    for i in range(n):
        root = find(i)
        if root not in clusters_map:
            clusters_map[root] = []
        clusters_map[root].append(i)

    # Filter by min_cluster_size and build output
    from collections import Counter

    result_clusters = []
    for root, members in clusters_map.items():
        if len(members) < min_cluster_size:
            continue

        member_ids = [ids[i] for i in members]

        # Extract common tags
        all_tags = []
        all_words = []
        for i in members:
            meta = metas[i] if i < len(metas) else {}
            tags_str = meta.get("tags", "")
            if tags_str:
                all_tags.extend(t.strip() for t in tags_str.split(",") if t.strip())

            # Collect content words for topic label
            doc = docs[i] if i < len(docs) and docs[i] else ""
            words = re.findall(r'[a-zA-Z_]{4,}', doc.lower())
            all_words.extend(words)

        # Common tags: tags appearing in >30% of cluster members
        tag_counts = Counter(all_tags)
        common_tags = [tag for tag, cnt in tag_counts.most_common(10)
                       if cnt >= max(2, len(members) * 0.3)]

        # Topic label: top 3 most frequent meaningful words (exclude stop words)
        stop_words = {"this", "that", "with", "from", "have", "been", "were", "will",
                      "would", "could", "should", "their", "there", "they", "which",
                      "when", "what", "where", "than", "then", "also", "about", "into",
                      "more", "some", "such", "only", "other", "each", "just", "like",
                      "over", "very", "after", "before", "between", "under", "again",
                      "does", "done", "make", "made", "most", "much", "must", "need",
                      "none", "true", "false"}
        word_counts = Counter(w for w in all_words if w not in stop_words)
        top_words = [w for w, _ in word_counts.most_common(3)]
        topic = " / ".join(top_words) if top_words else "misc"

        # Sample preview: first member's content snippet
        sample_idx = members[0]
        sample_doc = docs[sample_idx] if sample_idx < len(docs) and docs[sample_idx] else ""
        sample_preview = sample_doc[:SUMMARY_LENGTH].replace("\n", " ")
        if len(sample_doc) > SUMMARY_LENGTH:
            sample_preview += "..."

        result_clusters.append({
            "cluster_id": f"cluster_{len(result_clusters)}",
            "topic": topic,
            "size": len(members),
            "common_tags": common_tags,
            "member_ids": member_ids,
            "sample_preview": sample_preview,
        })

    # Sort by size descending, cap at 20
    result_clusters.sort(key=lambda x: x["size"], reverse=True)
    result_clusters = result_clusters[:20]

    _touch_memory_timestamp()

    return {
        "clusters": result_clusters,
        "total_clusters": len(result_clusters),
        "total_memories": count,
        "params": {
            "min_cluster_size": min_cluster_size,
            "distance_threshold": distance_threshold,
        },
    }


def memory_health_report() -> dict:
    """Generate a comprehensive memory health report with metrics and trends.

    Returns total counts, growth trends, stale memory count, tag distribution,
    retrieval statistics, and an overall health score (0-100).
    """
    now = time.time()
    now_dt = datetime.now()

    # Total counts
    mem_count = collection.count()
    obs_count = observations.count()

    if mem_count == 0:
        return {
            "total_memories": 0,
            "total_observations": obs_count,
            "added_24h": 0,
            "added_7d": 0,
            "added_30d": 0,
            "stale_count": 0,
            "top_tags": [],
            "avg_retrieval_count": 0.0,
            "health_score": 0,
            "health_label": "empty",
            "message": "Memory is empty. Start building knowledge with remember_this().",
        }

    # Fetch all metadata for analysis
    all_data = collection.get(
        limit=mem_count,
        include=["metadatas"],
    )
    metas = all_data.get("metadatas", [])

    # Growth trends: memories added in last 24h, 7d, 30d
    cutoff_24h = now - 86400
    cutoff_7d = now - 7 * 86400
    cutoff_30d = now - 30 * 86400
    added_24h = 0
    added_7d = 0
    added_30d = 0

    # Stale count: unretrieved >60 days
    cutoff_stale = now - 60 * 86400
    stale_count = 0

    # Tag frequency
    tag_freq = {}

    # Retrieval stats
    total_retrieval = 0
    retrieval_entries = 0

    for meta in metas:
        if not meta:
            continue

        # Growth: check session_time
        session_time = meta.get("session_time")
        if session_time is not None:
            try:
                st = float(session_time)
                if st >= cutoff_24h:
                    added_24h += 1
                if st >= cutoff_7d:
                    added_7d += 1
                if st >= cutoff_30d:
                    added_30d += 1

                # Stale: old + low retrieval
                rc = int(meta.get("retrieval_count", 0))
                if st < cutoff_stale and rc <= 2:
                    stale_count += 1
            except (ValueError, TypeError):
                pass

        # Tags
        tags_str = meta.get("tags", "")
        if tags_str:
            for tag in tags_str.split(","):
                tag = tag.strip()
                if tag:
                    tag_freq[tag] = tag_freq.get(tag, 0) + 1

        # Retrieval counts
        rc = int(meta.get("retrieval_count", 0))
        total_retrieval += rc
        retrieval_entries += 1

    # Top 10 tags
    top_tags = sorted(tag_freq.items(), key=lambda x: -x[1])[:10]
    top_tags_list = [{"tag": t, "count": c} for t, c in top_tags]

    # Average retrieval count
    avg_retrieval = round(total_retrieval / max(retrieval_entries, 1), 2)

    # Unique tag count
    unique_tags = len(tag_freq)

    # Health score: 0-100
    # recent_activity (40%): based on memories added in 7d
    if added_7d >= 10:
        recent_score = 1.0
    elif added_7d >= 5:
        recent_score = 0.8
    elif added_7d >= 2:
        recent_score = 0.6
    elif added_7d >= 1:
        recent_score = 0.4
    else:
        recent_score = 0.1

    # retrieval_rate (30%): how often memories are actually used
    if avg_retrieval >= 3.0:
        retrieval_score = 1.0
    elif avg_retrieval >= 1.5:
        retrieval_score = 0.8
    elif avg_retrieval >= 0.5:
        retrieval_score = 0.5
    elif avg_retrieval >= 0.1:
        retrieval_score = 0.3
    else:
        retrieval_score = 0.1

    # tag_diversity (30%): variety of tags used
    if unique_tags >= 20:
        diversity_score = 1.0
    elif unique_tags >= 10:
        diversity_score = 0.7
    elif unique_tags >= 5:
        diversity_score = 0.5
    elif unique_tags >= 2:
        diversity_score = 0.3
    else:
        diversity_score = 0.1

    health_score = int(
        recent_score * 40 + retrieval_score * 30 + diversity_score * 30
    )
    health_score = max(0, min(100, health_score))

    if health_score > 70:
        health_label = "healthy"
    elif health_score > 40:
        health_label = "moderate"
    else:
        health_label = "needs attention"

    # Growth rate (memories per day over last 30 days)
    growth_rate = round(added_30d / 30, 2) if added_30d > 0 else 0.0

    _touch_memory_timestamp()

    return {
        "total_memories": mem_count,
        "total_observations": obs_count,
        "added_24h": added_24h,
        "added_7d": added_7d,
        "added_30d": added_30d,
        "stale_count": stale_count,
        "top_tags": top_tags_list,
        "unique_tags": unique_tags,
        "avg_retrieval_count": avg_retrieval,
        "growth_rate_per_day": growth_rate,
        "health_score": health_score,
        "health_label": health_label,
        "score_breakdown": {
            "recent_activity": round(recent_score * 40, 1),
            "retrieval_rate": round(retrieval_score * 30, 1),
            "tag_diversity": round(diversity_score * 30, 1),
        },
    }


def rebuild_tag_index() -> dict:
    """Force rebuild the tag co-occurrence matrix.

    Use when tag relationships seem stale or after bulk memory operations.
    The matrix is normally rebuilt lazily when dirty, but this forces an
    immediate rebuild.
    """
    try:
        _build_tag_cooccurrence()
        return {
            "result": "Tag co-occurrence matrix rebuilt",
            "unique_tags": len(_tag_counts),
            "tags_with_cooccurrence": len(_tag_cooccurrence),
        }
    except Exception as e:
        return {"error": f"Failed to rebuild tag index: {str(e)}"}


@mcp.tool()
@crash_proof
def maintenance(action: str, top_k: int | None = None, days: int | None = None,
                min_cluster_size: int | None = None,
                distance_threshold: float | None = None) -> dict:
    """Run a maintenance action on the memory system.

    Available actions:
      - "promotions": Find recurring patterns worth promoting to CLAUDE.md rules.
            Optional: top_k (default 5, range 1-50)
      - "stale": Find old memories with low retrieval counts.
            Optional: days (default 60), top_k (default 20)
      - "cluster": Group related memories into semantic clusters.
            Optional: min_cluster_size (default 3), distance_threshold (default 0.3)
      - "health": Generate comprehensive memory health metrics and score.
            No parameters.
      - "rebuild_tags": Force rebuild the tag co-occurrence matrix.
            No parameters.

    Args:
        action: The maintenance action to run (see above).
        top_k: Max results (used by promotions, stale).
        days: Age threshold in days (used by stale).
        min_cluster_size: Min memories per cluster (used by cluster).
        distance_threshold: Max cosine distance for clustering (used by cluster).
    """
    if action == "promotions":
        return suggest_promotions(top_k=top_k if top_k is not None else 5)
    elif action == "stale":
        return list_stale_memories(
            days=days if days is not None else 60,
            top_k=top_k if top_k is not None else 20,
        )
    elif action == "cluster":
        return cluster_knowledge(
            min_cluster_size=min_cluster_size if min_cluster_size is not None else 3,
            distance_threshold=distance_threshold if distance_threshold is not None else 0.3,
        )
    elif action == "health":
        return memory_health_report()
    elif action == "rebuild_tags":
        return rebuild_tag_index()
    else:
        return {
            "error": f"Unknown action: {action!r}",
            "valid_actions": {
                "promotions": "Find recurring patterns to promote to rules (top_k)",
                "stale": "Find old unretrieved memories (days, top_k)",
                "cluster": "Group related memories into clusters (min_cluster_size, distance_threshold)",
                "health": "Generate memory health metrics (no params)",
                "rebuild_tags": "Rebuild tag co-occurrence matrix (no params)",
            },
        }


# ──────────────────────────────────────────────────
# Unix Domain Socket Gateway
# ──────────────────────────────────────────────────


def _handle_socket_client(conn):
    """Handle a single UDS client connection: read JSON request, dispatch, respond."""
    try:
        conn.settimeout(5)
        buf = b""
        while b"\n" not in buf:
            chunk = conn.recv(65536)
            if not chunk:
                break
            buf += chunk

        if not buf:
            return

        try:
            req = json.loads(buf.decode("utf-8").strip())
        except (json.JSONDecodeError, UnicodeDecodeError):
            resp = {"ok": False, "error": "Invalid JSON request"}
            conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))
            return

        result = _dispatch_request(req)
        conn.sendall((json.dumps(result) + "\n").encode("utf-8"))
    except Exception as e:
        try:
            resp = {"ok": False, "error": str(e)}
            conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))
        except Exception:
            pass
    finally:
        conn.close()


def _dispatch_request(req):
    """Route a UDS request to the appropriate ChromaDB operation."""
    method = req.get("method", "")
    col_name = req.get("collection", "")
    params = req.get("params", {})

    try:
        if method == "ping":
            return {"ok": True, "result": "pong"}

        if method == "flush_queue":
            flushed = _flush_capture_queue()
            return {"ok": True, "result": flushed}

        # Collection-based operations require a valid collection name
        col_map = {
            "knowledge": collection,
            "observations": observations,
            "fix_outcomes": fix_outcomes,
            "web_pages": web_pages,
        }
        col = col_map.get(col_name)
        if col is None:
            return {"ok": False, "error": f"Unknown collection: {col_name}"}

        if method == "count":
            return {"ok": True, "result": col.count()}

        if method == "query":
            result = col.query(
                query_texts=params.get("query_texts", [""]),
                n_results=params.get("n_results", 5),
                include=params.get("include", ["metadatas", "distances"]),
            )
            # Convert ChromaDB result to JSON-serializable dict
            return {"ok": True, "result": _serialize_chromadb_result(result)}

        if method == "get":
            kwargs = {}
            if "ids" in params:
                kwargs["ids"] = params["ids"]
            if "limit" in params:
                kwargs["limit"] = params["limit"]
            kwargs["include"] = params.get("include", ["metadatas", "documents"])
            result = col.get(**kwargs)
            return {"ok": True, "result": _serialize_chromadb_result(result)}

        if method == "upsert":
            docs = params.get("documents", [])
            metas = params.get("metadatas", [])
            ids = params.get("ids", [])
            if docs and ids:
                batch_size = 100
                for i in range(0, len(docs), batch_size):
                    col.upsert(
                        documents=docs[i:i + batch_size],
                        metadatas=metas[i:i + batch_size] if metas else None,
                        ids=ids[i:i + batch_size],
                    )
                return {"ok": True, "result": len(docs)}
            return {"ok": False, "error": "upsert requires documents and ids"}

        if method == "delete":
            ids = params.get("ids", [])
            if ids:
                batch_size = 100
                for i in range(0, len(ids), batch_size):
                    col.delete(ids=ids[i:i + batch_size])
                return {"ok": True, "result": len(ids)}
            return {"ok": False, "error": "delete requires ids"}

        return {"ok": False, "error": f"Unknown method: {method}"}

    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _serialize_chromadb_result(result):
    """Convert ChromaDB query/get result to a plain dict for JSON serialization."""
    if result is None:
        return {}
    out = {}
    for key in ("ids", "documents", "metadatas", "distances", "embeddings"):
        if key in result and result[key] is not None:
            out[key] = result[key]
    return out


def _start_socket_server():
    """Bind a Unix Domain Socket and accept connections in a daemon thread."""
    global _socket_server

    # Remove stale socket file (prevents 'Address already in use')
    try:
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)
    except OSError:
        pass

    try:
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(SOCKET_PATH)
        srv.listen(8)
        srv.settimeout(1.0)  # Allow periodic shutdown checks
        _socket_server = srv
    except OSError as e:
        # Non-fatal: MCP tools still work, just no external gateway
        import sys
        print(f"[UDS] Failed to start socket server: {e}", file=sys.stderr)
        return

    def _accept_loop():
        while True:
            try:
                conn, _ = srv.accept()
                t = threading.Thread(target=_handle_socket_client, args=(conn,), daemon=True)
                t.start()
            except socket.timeout:
                continue
            except OSError:
                break  # Server socket closed

    t = threading.Thread(target=_accept_loop, daemon=True, name="uds-gateway")
    t.start()


def _cleanup_socket():
    """Close server socket and remove socket file on exit."""
    global _socket_server
    if _socket_server is not None:
        try:
            _socket_server.close()
        except Exception:
            pass
        _socket_server = None
    try:
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)
    except OSError:
        pass


atexit.register(_cleanup_socket)


if __name__ == "__main__":
    _ensure_initialized()
    _start_socket_server()
    try:
        mcp.run()
    except Exception as e:
        print(f"[MCP] Fatal: {e}", file=_sys.stderr)
        _sys.exit(1)
