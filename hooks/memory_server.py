#!/usr/bin/env python3
"""Self-Healing Claude Framework — Memory MCP Server

A LanceDB-backed persistent memory system exposed as MCP tools.
Claude Code connects to this server and gets search_knowledge, remember_this,
get_memory, and maintenance as native tools.

The memory persists across sessions in ~/data/memory/lancedb/, enabling cross-session
knowledge retention.

Run standalone: python3 memory_server.py
Used via MCP: configured in .claude/mcp.json

Migrated from ChromaDB → LanceDB in Session 232.
LanceDB provides optimistic concurrency control (no more segfaults),
native TS bindings, and built-in BM25 FTS.
"""

import atexit
import functools
import hashlib
import json
import os
import socket
import subprocess
import threading
import time
from datetime import datetime, timedelta

import lancedb
import pyarrow as pa
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


# Persistent LanceDB storage
MEMORY_DIR = os.path.join(os.path.expanduser("~"), "data", "memory")
LANCE_DIR = os.path.join(MEMORY_DIR, "lancedb")
os.makedirs(LANCE_DIR, exist_ok=True)

# Embedding model: nomic-ai/nomic-embed-text-v2-moe (768-dim, 8192 tokens, ~67% MTEB)
# MoE architecture (305M active params), Matryoshka (truncatable to 256-dim)
_EMBEDDING_MODEL = "nomic-ai/nomic-embed-text-v2-moe"
_EMBEDDING_DIM = 768
_embedding_fn = None  # Lazy init — SentenceTransformer instance
TAGS_DB_PATH = os.path.join(MEMORY_DIR, "tags.db")

# Unix Domain Socket gateway for external consumers (hooks, dashboard)
SOCKET_PATH = os.path.join(
    os.path.expanduser("~"), ".claude", "hooks", ".memory.sock"
)
_socket_server = None  # threading server reference for cleanup
_uds_shutting_down = False  # prevents rebind during intentional shutdown

# Lazy LanceDB initialization
_lance_db = None  # lancedb.DBConnection
collection = None  # LanceCollection wrapper for knowledge table
fix_outcomes = None  # LanceCollection wrapper for fix_outcomes table
observations = None  # LanceCollection wrapper for observations table
web_pages = None  # LanceCollection wrapper for web_pages table
quarantine = None  # LanceCollection wrapper for quarantine table
_lance_degraded = False  # kept for backward compat (now means "lance degraded")


# ── Arrow Schemas for LanceDB Tables ───────────────────────────────────────

_KNOWLEDGE_SCHEMA = pa.schema([
    pa.field("id", pa.string()),
    pa.field("text", pa.string()),
    pa.field("vector", pa.list_(pa.float32(), _EMBEDDING_DIM)),
    pa.field("context", pa.string()),
    pa.field("tags", pa.string()),
    pa.field("timestamp", pa.string()),
    pa.field("session_time", pa.float64()),
    pa.field("preview", pa.string()),
    pa.field("primary_source", pa.string()),
    pa.field("related_urls", pa.string()),
    pa.field("source_method", pa.string()),
    pa.field("tier", pa.int32()),
    pa.field("retrieval_count", pa.int32()),
    pa.field("last_retrieved", pa.string()),
])

_FIX_OUTCOMES_SCHEMA = pa.schema([
    pa.field("id", pa.string()),
    pa.field("text", pa.string()),
    pa.field("vector", pa.list_(pa.float32(), _EMBEDDING_DIM)),
    pa.field("error_hash", pa.string()),
    pa.field("strategy_id", pa.string()),
    pa.field("chain_id", pa.string()),
    pa.field("outcome", pa.string()),
    pa.field("confidence", pa.string()),
    pa.field("attempts", pa.string()),
    pa.field("successes", pa.string()),
    pa.field("timestamp", pa.string()),
    pa.field("last_outcome_time", pa.string()),
    pa.field("banned", pa.string()),
    pa.field("bridged", pa.string()),
])

_OBSERVATIONS_SCHEMA = pa.schema([
    pa.field("id", pa.string()),
    pa.field("text", pa.string()),
    pa.field("vector", pa.list_(pa.float32(), _EMBEDDING_DIM)),
    pa.field("session_id", pa.string()),
    pa.field("tool_name", pa.string()),
    pa.field("timestamp", pa.string()),
    pa.field("session_time", pa.float64()),
    pa.field("has_error", pa.string()),
    pa.field("error_pattern", pa.string()),
    pa.field("preview", pa.string()),
])

_WEB_PAGES_SCHEMA = pa.schema([
    pa.field("id", pa.string()),
    pa.field("text", pa.string()),
    pa.field("vector", pa.list_(pa.float32(), _EMBEDDING_DIM)),
    pa.field("url", pa.string()),
    pa.field("title", pa.string()),
    pa.field("chunk_index", pa.string()),
    pa.field("total_chunks", pa.string()),
    pa.field("indexed_at", pa.string()),
    pa.field("content_hash", pa.string()),
    pa.field("word_count", pa.string()),
])

_QUARANTINE_SCHEMA = pa.schema([
    pa.field("id", pa.string()),
    pa.field("text", pa.string()),
    pa.field("vector", pa.list_(pa.float32(), _EMBEDDING_DIM)),
    pa.field("quarantine_reason", pa.string()),
    pa.field("quarantine_pair", pa.string()),
    pa.field("quarantined_at", pa.string()),
    pa.field("context", pa.string()),
    pa.field("tags", pa.string()),
    pa.field("timestamp", pa.string()),
    pa.field("session_time", pa.float64()),
    pa.field("preview", pa.string()),
])

_TABLE_SCHEMAS = {
    "knowledge": _KNOWLEDGE_SCHEMA,
    "fix_outcomes": _FIX_OUTCOMES_SCHEMA,
    "observations": _OBSERVATIONS_SCHEMA,
    "web_pages": _WEB_PAGES_SCHEMA,
    "quarantine": _QUARANTINE_SCHEMA,
}


def _embed_texts(texts):
    """Embed a list of texts using the loaded SentenceTransformer model.

    Returns list of lists of floats (768-dim vectors).
    Falls back to zero vectors if embedding model is unavailable.
    """
    if _embedding_fn is None:
        return [[0.0] * _EMBEDDING_DIM for _ in texts]
    try:
        vectors = _embedding_fn.encode(texts, show_progress_bar=False)
        return [v.tolist() for v in vectors]
    except Exception:
        return [[0.0] * _EMBEDDING_DIM for _ in texts]


def _embed_text(text):
    """Embed a single text string. Returns list of floats (768-dim)."""
    return _embed_texts([text])[0]


class LanceCollection:
    """LanceDB table wrapper with a familiar API surface.

    Provides query, get, upsert, update, delete, count methods.

    LanceDB cosine distance: 0 = identical, 2 = opposite (range 0-2).
    LanceDB cosine distance: 0 = identical, 2 = opposite (same range).
    No conversion needed — distance semantics match directly.
    """

    def __init__(self, table, schema, name):
        self._table = table
        self._schema = schema
        self._name = name
        # Build set of known column names for metadata handling
        self._meta_cols = {f.name for f in schema} - {"id", "text", "vector"}

    def count(self):
        """Return number of rows in the table."""
        try:
            return self._table.count_rows()
        except Exception:
            return 0

    def query(self, query_texts=None, n_results=5, include=None, where=None):
        """Semantic search. Returns nested results.

        Result format: {"ids": [[...]], "documents": [[...]], "metadatas": [[...]], "distances": [[...]]}
        """
        if include is None:
            include = ["metadatas", "distances"]
        text = query_texts[0] if query_texts else ""
        vector = _embed_text(text)

        try:
            q = self._table.search(vector).distance_type("cosine").limit(n_results)
            if where:
                sql_where = self._translate_where(where)
                if sql_where:
                    q = q.where(sql_where, prefilter=True)
            rows = q.to_list()
        except Exception:
            rows = []

        ids = [[r["id"] for r in rows]]
        result = {"ids": ids}

        if "documents" in include:
            result["documents"] = [[r.get("text", "") for r in rows]]
        if "distances" in include:
            result["distances"] = [[r.get("_distance", 1.0) for r in rows]]
        if "metadatas" in include:
            result["metadatas"] = [[self._row_to_meta(r) for r in rows]]
        if "embeddings" in include:
            result["embeddings"] = [[r.get("vector", []) for r in rows]]

        return result

    def get(self, ids=None, where=None, limit=None, offset=0, include=None):
        """Fetch by IDs or filter. Returns flat results.

        Result format: {"ids": [...], "documents": [...], "metadatas": [...]}
        """
        if include is None:
            include = ["metadatas", "documents"]

        try:
            if ids is not None and len(ids) > 0:
                # Fetch by specific IDs
                escaped = ", ".join(f"'{i}'" for i in ids)
                sql = f"id IN ({escaped})"
                rows = self._table.search().where(sql, prefilter=True).limit(len(ids) + 10).to_list()
                # Preserve requested order
                id_order = {i: idx for idx, i in enumerate(ids)}
                rows.sort(key=lambda r: id_order.get(r["id"], 999999))
            elif where:
                sql_where = self._translate_where(where)
                q = self._table.search().where(sql_where, prefilter=True)
                if limit:
                    q = q.limit(limit)
                else:
                    q = q.limit(10000)  # practical cap
                rows = q.to_list()
            elif limit:
                rows = self._table.search().limit(limit).to_list()
                if offset and offset > 0:
                    rows = rows[offset:]
            else:
                rows = self._table.search().limit(10000).to_list()
        except Exception:
            rows = []

        result = {"ids": [r["id"] for r in rows]}

        if "documents" in include:
            result["documents"] = [r.get("text", "") for r in rows]
        if "metadatas" in include:
            result["metadatas"] = [self._row_to_meta(r) for r in rows]
        if "embeddings" in include:
            result["embeddings"] = [r.get("vector", []) for r in rows]

        return result

    def upsert(self, documents=None, metadatas=None, ids=None):
        """Upsert records using LanceDB merge_insert."""
        if not ids or not documents:
            return
        records = []
        vectors = _embed_texts(documents)
        for i, doc_id in enumerate(ids):
            doc = documents[i] if i < len(documents) else ""
            meta = metadatas[i] if metadatas and i < len(metadatas) else {}
            record = self._build_record(doc_id, doc, vectors[i], meta)
            records.append(record)

        try:
            self._table.merge_insert("id") \
                .when_matched_update_all() \
                .when_not_matched_insert_all() \
                .execute(records)
        except Exception as e:
            # Fallback: try add (for new tables or if merge_insert fails)
            try:
                self._table.add(records)
            except Exception:
                print(f"[Lance] upsert failed for {self._name}: {e}", file=_sys.stderr)

    def update(self, ids=None, metadatas=None, documents=None):
        """Update metadata and/or documents for existing records.

        API: collection.update(ids=[...], metadatas=[...], documents=[...])
        LanceDB: fetch existing, merge, re-upsert (merge_insert pattern).
        """
        if not ids:
            return
        try:
            # Fetch existing records
            escaped = ", ".join(f"'{i}'" for i in ids)
            existing = self._table.search().where(f"id IN ({escaped})", prefilter=True).limit(len(ids) + 10).to_list()
            existing_map = {r["id"]: r for r in existing}

            records = []
            for i, doc_id in enumerate(ids):
                old = existing_map.get(doc_id, {})
                meta = metadatas[i] if metadatas and i < len(metadatas) else {}
                doc = documents[i] if documents and i < len(documents) else old.get("text", "")
                vector = old.get("vector", [0.0] * _EMBEDDING_DIM)

                # If document changed, re-embed
                if documents and i < len(documents) and documents[i] != old.get("text", ""):
                    vector = _embed_text(documents[i])

                # Merge: old metadata + new metadata
                merged_meta = self._row_to_meta(old)
                merged_meta.update(meta)

                record = self._build_record(doc_id, doc, vector, merged_meta)
                records.append(record)

            if records:
                self._table.merge_insert("id") \
                    .when_matched_update_all() \
                    .when_not_matched_insert_all() \
                    .execute(records)
        except Exception as e:
            print(f"[Lance] update failed for {self._name}: {e}", file=_sys.stderr)

    def delete(self, ids=None):
        """Delete records by IDs."""
        if not ids:
            return
        try:
            escaped = ", ".join(f"'{i}'" for i in ids)
            self._table.delete(f"id IN ({escaped})")
        except Exception as e:
            print(f"[Lance] delete failed for {self._name}: {e}", file=_sys.stderr)

    def _build_record(self, doc_id, text, vector, meta):
        """Build a typed record dict matching the Arrow schema."""
        record = {
            "id": str(doc_id),
            "text": str(text) if text else "",
            "vector": vector if vector and len(vector) == _EMBEDDING_DIM else [0.0] * _EMBEDDING_DIM,
        }
        # Fill metadata columns from schema
        for col_name in self._meta_cols:
            field = self._schema.field(col_name)
            val = meta.get(col_name)
            if pa.types.is_float64(field.type):
                try:
                    record[col_name] = float(val) if val is not None else 0.0
                except (ValueError, TypeError):
                    record[col_name] = 0.0
            elif pa.types.is_int32(field.type):
                try:
                    record[col_name] = int(val) if val is not None else 0
                except (ValueError, TypeError):
                    record[col_name] = 0
            else:
                record[col_name] = str(val) if val is not None else ""
        return record

    def _row_to_meta(self, row):
        """Extract metadata dict from a LanceDB row (exclude id, text, vector, _distance)."""
        meta = {}
        for col_name in self._meta_cols:
            val = row.get(col_name)
            if val is not None:
                meta[col_name] = val
        return meta

    @staticmethod
    def _translate_where(where):
        """Translate where-clause dict to a LanceDB SQL filter string.

        Examples:
            {"session_time": {"$lt": 123.4}} → "session_time < 123.4"
            {"error_hash": "abc"} → "error_hash = 'abc'"
            {"$and": [...]} → "(clause1) AND (clause2)"
        """
        if not where or not isinstance(where, dict):
            return ""

        parts = []
        for key, val in where.items():
            if key == "$and":
                sub_parts = []
                for sub in val:
                    translated = LanceCollection._translate_where(sub)
                    if translated:
                        sub_parts.append(f"({translated})")
                if sub_parts:
                    parts.append(" AND ".join(sub_parts))
            elif key == "$or":
                sub_parts = []
                for sub in val:
                    translated = LanceCollection._translate_where(sub)
                    if translated:
                        sub_parts.append(f"({translated})")
                if sub_parts:
                    parts.append(" OR ".join(sub_parts))
            elif isinstance(val, dict):
                # Operator clause: {"$lt": X}, {"$gte": X}, etc.
                op_map = {"$lt": "<", "$lte": "<=", "$gt": ">", "$gte": ">=",
                          "$eq": "=", "$ne": "!="}
                for op, sql_op in op_map.items():
                    if op in val:
                        v = val[op]
                        if isinstance(v, str):
                            parts.append(f"{key} {sql_op} '{v}'")
                        else:
                            parts.append(f"{key} {sql_op} {v}")
            else:
                # Exact match: {"error_hash": "abc"}
                if isinstance(val, str):
                    parts.append(f"{key} = '{val}'")
                else:
                    parts.append(f"{key} = {val}")

        return " AND ".join(parts)


def _init_lancedb():
    """Lazy initialization of LanceDB connection and table wrappers.

    Called from _ensure_initialized() on first MCP tool use.
    Safe to call multiple times — idempotent after first run.
    Uses nomic-ai/nomic-embed-text-v2-moe embedding model (768-dim, 8192 tokens).
    """
    global _lance_db, collection, fix_outcomes, observations, web_pages, quarantine, _lance_degraded, _embedding_fn
    if _lance_db is not None:
        return
    try:
        # Initialize embedding function (nomic-embed-text-v2-moe, 768-dim, 8192 tokens)
        try:
            from sentence_transformers import SentenceTransformer
            _embedding_fn = SentenceTransformer(_EMBEDDING_MODEL, trust_remote_code=True)
            print(f"[MCP] Embedding model loaded: {_EMBEDDING_MODEL} ({_EMBEDDING_DIM}-dim)", file=_sys.stderr)
        except Exception as ef_err:
            print(f"[MCP] Embedding model load failed: {ef_err}", file=_sys.stderr)
            _embedding_fn = None

        _lance_db = lancedb.connect(LANCE_DIR)

        def _open_or_create(name: str, schema):
            """Open table if exists, create with schema if not."""
            try:
                tbl = _lance_db.open_table(name)
            except Exception:
                tbl = _lance_db.create_table(name, schema=schema)
            return LanceCollection(tbl, schema, name)

        collection = _open_or_create("knowledge", _KNOWLEDGE_SCHEMA)
        fix_outcomes = _open_or_create("fix_outcomes", _FIX_OUTCOMES_SCHEMA)
        observations = _open_or_create("observations", _OBSERVATIONS_SCHEMA)
        web_pages = _open_or_create("web_pages", _WEB_PAGES_SCHEMA)
        quarantine = _open_or_create("quarantine", _QUARANTINE_SCHEMA)

        print(f"[MCP] LanceDB initialized at {LANCE_DIR}", file=_sys.stderr)
    except Exception as e:
        import traceback
        print(f"[MCP] LanceDB init failed: {e}\n{traceback.format_exc()}", file=_sys.stderr)
        _lance_degraded = True

# Progressive disclosure: preview length for search summaries
SUMMARY_LENGTH = 120

# Auto-capture settings
OBSERVATION_TTL_DAYS = 30
MAX_OBSERVATIONS = 5000
try:
    from shared.ramdisk import get_capture_queue
    CAPTURE_QUEUE_FILE = get_capture_queue()
except ImportError:
    CAPTURE_QUEUE_FILE = os.path.join(os.path.dirname(__file__), ".capture_queue.jsonl")
DIGEST_TAGS = "type:digest,auto-generated,area:framework"

# Ingestion filter: reject noise patterns
# Patterns are ^-anchored to match content that IS noise, not content ABOUT noise.
# This prevents false positives where memories discussing "npm install" get rejected.
MIN_CONTENT_LENGTH = 20
NOISE_PATTERNS = [
    # Package manager output (anchored to start of content)
    r"^npm install\b", r"^pip install\b", r"^Successfully installed\b",
    r"^already satisfied\b", r"^up to date\b", r"^added .* packages?\b",
    r"^removing .* packages?\b", r"^npm WARN\b", r"^DEPRECATION\b",
    r"^Collecting \b", r"^Downloading \b", r"^Installing collected\b",
    r"^running setup\.py\b", r"^Building wheel\b", r"^Using cached\b",
    # Non-package noise (anchored full-line or start-of-content)
    r"^(?:OK|Done|Got it|Sure|Understood)[.!]?\s*$",   # empty acks
    r"^Session \d+ started\s*$",                         # session boilerplate
    r"^(?:Reading|Writing|Editing) (?:file )?/\S",        # tool echo: requires absolute path
    r"^Traceback \(most recent call last\):\s*$",        # raw traceback header only
    r"^(?:Let me|I'll|I will) (?:check|look|read|search)\b.{0,30}$",  # filler: only short content
]
import re as _re
NOISE_REGEXES = [_re.compile(p, _re.IGNORECASE) for p in NOISE_PATTERNS]

# Near-dedup: cosine distance thresholds (tuned for nomic-embed-text-v2-moe 768-dim)
DEDUP_THRESHOLD = 0.12        # distance < 0.12 = hard skip (was 0.10 for 384-dim)
DEDUP_SOFT_THRESHOLD = 0.20   # 0.12-0.20 = save but tag as possible-dupe (was 0.15)
FIX_DEDUP_THRESHOLD = 0.05    # Stricter threshold for type:fix memories (was 0.03)
_FIX_DEDUP_EXEMPT = False      # DORMANT — flip True to skip dedup for all type:fix

# Citation URL extraction
MAX_CITATION_URLS = 4  # 1 primary + 3 related
MAX_URL_LENGTH = 500
DOMAIN_AUTHORITY = {
    "high": {"github.com", "docs.openzeppelin.com", "eips.ethereum.org",
             "developer.mozilla.org", "docs.soliditylang.org", "react.dev",
             "developer.x.com", "docs.python.org", "stackoverflow.com"},
    "medium": {"medium.com", "dev.to", "hackmd.io", "mirror.xyz"},
    "low": {"localhost", "127.0.0.1", "example.com", "0.0.0.0"},
}

# Observation promotion settings
MAX_PROMOTIONS_PER_CYCLE = 10
PROMOTION_TAGS = "type:auto-promoted,area:framework"


def generate_id(content: str) -> str:
    """Generate a deterministic ID from content alone.

    Using only content (no timestamp) means saving the same knowledge twice
    produces the same ID, which is treated as an upsert — preventing
    duplicate entries and unbounded database growth.
    """
    return hashlib.sha256(content.encode()).hexdigest()[:16]


# ── Auto Tier Classification ─────────────────────────────────────────────────
# Tier 1 = high-value (fixes, decisions, critical)
# Tier 2 = standard (default)
# Tier 3 = low-value (auto-captured, short, low-priority)

_TIER1_TAGS = {"type:fix", "type:decision", "priority:critical", "priority:high"}
_TIER3_TAGS = {"type:auto-captured", "priority:low"}
_TIER1_KEYWORDS = ("root cause", "breaking")


def _classify_tier(content: str, tags: str) -> int:
    """Classify a memory into tier 1 (high), 2 (standard), or 3 (low).

    Pure function — no side effects.  Called during remember_this() to
    assign a tier before upsert.
    """
    tag_set = {t.strip().lower() for t in tags.split(",") if t.strip()} if tags else set()
    if tag_set & _TIER1_TAGS:
        return 1
    lower = content.lower()
    if any(kw in lower for kw in _TIER1_KEYWORDS) or content.startswith("Fixed "):
        return 1
    if tag_set & _TIER3_TAGS:
        return 3
    if len(content) < 50:
        return 3
    return 2


# ── Tag Normalization ─────────────────────────────────────────────────────────
# Auto-corrects bare dimension values to canonical "dimension:value" format.
# Non-destructive: unknown tags pass through unchanged.

_BARE_TO_DIMENSION = {
    # type dimension
    "fix": "type:fix", "error": "type:error", "learning": "type:learning",
    "feature": "type:feature", "feature-request": "type:feature-request",
    "correction": "type:correction", "decision": "type:decision",
    "auto-captured": "type:auto-captured", "preference": "type:preference",
    "audit": "type:audit",
    # priority dimension
    "critical": "priority:critical", "high": "priority:high",
    "medium": "priority:medium", "low": "priority:low",
    # outcome dimension
    "success": "outcome:success", "failed": "outcome:failed",
}


def _normalize_tags(tags: str) -> str:
    """Normalize tags to canonical dimension:value format.

    Non-destructive — unknown tags pass through unchanged.
    Examples:
        "fix,high,framework" -> "type:fix,priority:high,framework"
        "type:fix,critical"  -> "type:fix,priority:critical"
        ""                   -> ""
    """
    if not tags:
        return tags
    parts = [t.strip() for t in tags.split(",") if t.strip()]
    normalized = []
    for tag in parts:
        lower = tag.lower()
        # Already dimensioned (contains ":") — pass through as-is
        if ":" in tag:
            normalized.append(tag)
        elif lower in _BARE_TO_DIMENSION:
            normalized.append(_BARE_TO_DIMENSION[lower])
        else:
            normalized.append(tag)
    return ",".join(normalized)


def _migrate_previews():
    """LEGACY: Preview backfill no longer needed — handled during LanceDB migration.
    Returns 0 (no-op).
    """
    return 0


_TIER_BACKFILL_MARKER = os.path.join(os.path.dirname(__file__), ".tier_backfill_done")


def _backfill_tiers():
    """LEGACY: Tier backfill no longer needed — handled during LanceDB migration.
    Returns 0 (no-op).
    """
    return 0


_EMBEDDING_MIGRATION_MARKER = os.path.join(os.path.dirname(__file__), ".embedding_migration_done")
_COLLECTION_NAMES = ["knowledge", "fix_outcomes", "observations", "web_pages", "quarantine"]


def _migrate_embeddings():
    """LEGACY: Embedding migration no longer needed — LanceDB stores vectors natively.
    Returns 0 (no-op).
    """
    return 0


# ──────────────────────────────────────────────────
# Citation URL Extraction
# ──────────────────────────────────────────────────
from urllib.parse import urlparse as _urlparse

# Regex for [source: URL] and [ref: URL] markers
_SOURCE_MARKER_RE = _re.compile(r'\[source:\s*(https?://[^\]\s]+)\s*\]', _re.IGNORECASE)
_REF_MARKER_RE = _re.compile(r'\[ref:\s*(https?://[^\]\s]+)\s*\]', _re.IGNORECASE)
# General URL regex for auto-extraction
_URL_RE = _re.compile(r'https?://[^\s<>\'")\]]+')


def _validate_url(url_str: str) -> str:
    """Validate and clean a URL string. Returns cleaned URL or empty string."""
    try:
        url_str = url_str.strip()
        # Strip trailing punctuation that often clings to URLs in text
        while url_str and url_str[-1] in '.,;:!?)':
            url_str = url_str[:-1]
        if len(url_str) > MAX_URL_LENGTH:
            return ""
        parsed = _urlparse(url_str)
        if parsed.scheme in ("http", "https") and parsed.netloc and "." in parsed.netloc:
            return url_str
        return ""
    except Exception:
        return ""


def _rank_url_authority(url: str) -> int:
    """Rank URL authority: 1=high, 2=medium, 3=low/unknown."""
    try:
        netloc = _urlparse(url).netloc.lower()
        # Strip port if present
        if ":" in netloc:
            netloc = netloc.split(":")[0]
        for domain in DOMAIN_AUTHORITY["high"]:
            if netloc == domain or netloc.endswith("." + domain):
                return 1
        for domain in DOMAIN_AUTHORITY["medium"]:
            if netloc == domain or netloc.endswith("." + domain):
                return 2
        for domain in DOMAIN_AUTHORITY["low"]:
            if netloc == domain or netloc.endswith("." + domain):
                return 3
        return 2  # Unknown domains default to medium
    except Exception:
        return 3


def _extract_citations(content: str, context: str) -> dict:
    """Extract citation URLs from content and context.

    Supports explicit markers [source: URL] and [ref: URL] plus
    auto-extraction of bare URLs. Returns dict with primary_source,
    related_urls (comma-separated), source_method, and clean_content.
    Entire function is fail-open: returns empty defaults on any error.
    """
    defaults = {
        "primary_source": "",
        "related_urls": "",
        "source_method": "none",
        "clean_content": content,
    }
    try:
        primary = ""
        refs = []
        clean = content

        # 1. Parse [source: URL] marker (take first match only)
        source_match = _SOURCE_MARKER_RE.search(clean)
        if source_match:
            candidate = _validate_url(source_match.group(1))
            if candidate:
                primary = candidate
            clean = _SOURCE_MARKER_RE.sub("", clean).strip()

        # 2. Parse [ref: URL] markers
        ref_matches = _REF_MARKER_RE.findall(clean)
        for ref_url in ref_matches:
            validated = _validate_url(ref_url)
            if validated and validated != primary:
                refs.append(validated)
        clean = _REF_MARKER_RE.sub("", clean).strip()

        method = "explicit" if (primary or refs) else "none"

        # 3. Auto-extract remaining URLs from content + context
        auto_urls = []
        combined_text = clean + " " + (context or "")
        for url_match in _URL_RE.findall(combined_text):
            validated = _validate_url(url_match)
            if not validated:
                continue
            if validated == primary or validated in refs:
                continue
            # Filter noise domains
            rank = _rank_url_authority(validated)
            if rank >= 3:
                continue  # Skip low-authority (localhost, example.com)
            auto_urls.append((rank, validated))

        # Sort auto URLs by authority (best first)
        auto_urls.sort(key=lambda x: x[0])

        # 4. If no explicit primary, promote best auto URL
        if not primary and auto_urls:
            primary = auto_urls[0][1]
            auto_urls = auto_urls[1:]
            method = "auto"
        elif not primary and not refs:
            method = "none"

        # 5. Merge refs + auto into related, cap at MAX_CITATION_URLS - 1
        all_related = refs + [u[1] for u in auto_urls]
        # Deduplicate while preserving order
        seen = set()
        deduped = []
        for u in all_related:
            if u not in seen and u != primary:
                seen.add(u)
                deduped.append(u)
        related = deduped[:MAX_CITATION_URLS - 1]

        return {
            "primary_source": primary,
            "related_urls": ",".join(related),
            "source_method": method,
            "clean_content": clean,
        }
    except Exception:
        return defaults


# ──────────────────────────────────────────────────
# FTS5 Hybrid Search Index
# ──────────────────────────────────────────────────
import sqlite3
import re


class TagIndex:
    """Minimal SQLite tag index for boolean AND/OR tag search.

    LanceDB is the source of truth; this is a derived read-optimized cache.
    Keyword search is handled by LanceDB native FTS (BM25).
    """

    def __init__(self, db_path=":memory:"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        if db_path != ":memory:":
            self.conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self):
        c = self.conn
        c.execute("""CREATE TABLE IF NOT EXISTS tags (
            memory_id TEXT,
            tag TEXT
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_tags_mid ON tags(memory_id)")
        c.execute("CREATE TABLE IF NOT EXISTS sync_meta (key TEXT PRIMARY KEY, value TEXT)")
        c.commit()

    def is_synced(self, lance_count):
        """Check if tag index is in sync with LanceDB by entry count."""
        row = self.conn.execute(
            "SELECT value FROM sync_meta WHERE key='sync_count'"
        ).fetchone()
        if row is None:
            return False
        return int(row[0]) == lance_count

    def _update_sync_count(self, count):
        self.conn.execute(
            "INSERT OR REPLACE INTO sync_meta (key, value) VALUES ('sync_count', ?)",
            (str(count),),
        )
        self.conn.commit()

    def reset_and_rebuild(self, lance_collection):
        """Drop all tables and rebuild from LanceDB (corruption recovery)."""
        self.conn.execute("DROP TABLE IF EXISTS tags")
        self.conn.execute("DROP TABLE IF EXISTS sync_meta")
        self.conn.commit()
        self._create_tables()
        return self.build_from_lance(lance_collection)

    def build_from_lance(self, lance_collection):
        """Rebuild tags table from LanceDB. Returns entry count."""
        count = lance_collection.count()
        if count == 0:
            return 0
        all_data = lance_collection.get(limit=count, include=["metadatas"])
        if not all_data or not all_data.get("ids"):
            return 0
        ids = all_data["ids"]
        metas = all_data.get("metadatas", [])

        with self._lock:
            self.conn.execute("DELETE FROM tags")
            rows = []
            for i, mid in enumerate(ids):
                meta = metas[i] if i < len(metas) else {}
                tags_str = meta.get("tags", "") if meta else ""
                if tags_str:
                    for tag in tags_str.split(","):
                        tag = tag.strip()
                        if tag:
                            rows.append((mid, tag))
            self.conn.executemany("INSERT INTO tags VALUES (?, ?)", rows)
            self._update_sync_count(len(ids))
        return len(ids)


    def add_tags(self, memory_id, tags_str):
        """Add/update tags for a single memory (called on remember_this)."""
        if not tags_str:
            return
        with self._lock:
            self.conn.execute("DELETE FROM tags WHERE memory_id = ?", (memory_id,))
            rows = [(memory_id, t.strip()) for t in tags_str.split(",") if t.strip()]
            self.conn.executemany("INSERT INTO tags VALUES (?, ?)", rows)
            # Increment sync count
            row = self.conn.execute(
                "SELECT value FROM sync_meta WHERE key='sync_count'"
            ).fetchone()
            if row:
                self._update_sync_count(int(row[0]) + 1)
            else:
                self.conn.commit()

    def remove(self, memory_id):
        """Remove tags for a memory (used by dedup sweep)."""
        with self._lock:
            self.conn.execute("DELETE FROM tags WHERE memory_id = ?", (memory_id,))
            self.conn.commit()

    def tag_search(self, tags_list, match_all=False, top_k=15):
        """Boolean tag search. Returns list of memory_id strings."""
        if not tags_list:
            return []
        placeholders = ",".join("?" * len(tags_list))
        with self._lock:
            if match_all:
                sql = f"""SELECT memory_id FROM tags
                    WHERE tag IN ({placeholders})
                    GROUP BY memory_id HAVING COUNT(DISTINCT tag) = ?
                    LIMIT ?"""
                rows = self.conn.execute(sql, (*tags_list, len(tags_list), top_k)).fetchall()
            else:
                sql = f"""SELECT DISTINCT memory_id FROM tags
                    WHERE tag IN ({placeholders})
                    LIMIT ?"""
                rows = self.conn.execute(sql, (*tags_list, top_k)).fetchall()
        return [r[0] for r in rows]


def _detect_query_mode(query, routing="default"):
    """Route queries to the appropriate search engine.

    Args:
        query:   The search query string.
        routing: Routing strategy — "default" (current heuristics),
                 "fast" (expanded FTS5 keyword routing),
                 "full_hybrid" (both engines for all queries).

    Returns one of: 'tags', 'keyword', 'semantic', 'hybrid'.
    """
    q = query.strip()
    ql = q.lower()

    # Tag queries: always FTS5 regardless of routing
    if ql.startswith("tag:") or ql.startswith("tags:"):
        return "tags"

    # Full Hybrid: everything else goes through both engines
    if routing == "full_hybrid":
        return "hybrid"

    # Keyword: quoted phrases or boolean operators
    if '"' in q or " AND " in q or " OR " in q:
        return "keyword"

    words = q.split()

    # Keyword: 1-2 word queries (likely identifiers or exact terms)
    if len(words) <= 2:
        return "keyword"

    # Fast mode: catch technical 3-4 word queries for FTS5
    if routing == "fast" and len(words) <= 4:
        # Underscores or dots → identifiers (gate_timing, memory_server.py)
        if any("_" in w or "." in w for w in words):
            return "keyword"
        # CamelCase → class/module names (LanceDB, FTS5Index)
        if any(c.isupper() for w in words for c in w[1:]):
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


_TIER_BOOST = {1: 0.05, 2: 0.0, 3: -0.02}


def _apply_tier_boost(results):
    """Boost high-value (tier 1) memories and penalise low-value (tier 3).

    Reads tier from each entry's metadata.  Entries without a tier field
    default to tier 2 (no change).  Re-sorts by adjusted relevance.
    """
    if not results:
        return results
    for entry in results:
        raw = entry.get("relevance", 0) or 0
        tier = entry.get("tier", 2)
        if not isinstance(tier, int):
            try:
                tier = int(tier)
            except (ValueError, TypeError):
                tier = 2
        entry["_tier_adjusted"] = raw + _TIER_BOOST.get(tier, 0.0)
    results.sort(key=lambda x: x.get("_tier_adjusted", 0), reverse=True)
    for entry in results:
        entry.pop("_tier_adjusted", None)
    return results


_ACCESS_BOOST_CAP = 0.03


def _apply_access_boost(results):
    """Tiebreaker boost for frequently-retrieved memories (max +0.03).

    Log-scaled so diminishing returns: 1 retrieval ≈ +0.01, 10 ≈ +0.02, 50+ ≈ +0.03.
    """
    if not results:
        return results
    import math
    for entry in results:
        raw = entry.get("relevance", 0) or 0
        rc = int(entry.get("retrieval_count", 0))
        boost = min(_ACCESS_BOOST_CAP, 0.008 * math.log1p(rc)) if rc > 0 else 0.0
        entry["_access_adjusted"] = raw + boost
    results.sort(key=lambda x: x.get("_access_adjusted", 0), reverse=True)
    for entry in results:
        entry.pop("_access_adjusted", None)
    return results


_STOPWORDS = {"the", "a", "an", "is", "it", "to", "in", "of", "and", "for"}


def _rerank_keyword_overlap(results, query, boost_weight=0.05):
    """Post-retrieval reranker: boost results that contain exact query terms.

    Adds boost_weight * (matched_terms / total_terms) to each result's relevance.
    Works on all search modes, giving keyword signal to semantic-only results.
    """
    if not results or not query or boost_weight <= 0:
        return results
    terms = [w.lower() for w in query.split() if w.lower() not in _STOPWORDS]
    if not terms:
        return results
    total = len(terms)
    for entry in results:
        text = (entry.get("preview", "") + " " + entry.get("tags", "")).lower()
        matched = sum(1 for t in terms if t in text)
        if matched > 0:
            entry["relevance"] = entry.get("relevance", 0) + boost_weight * (matched / total)
    results.sort(key=lambda x: x.get("relevance", 0), reverse=True)
    return results


def _merge_results(fts_results, lance_summaries, top_k=15):
    """Merge FTS5 and LanceDB results using Reciprocal Rank Fusion (RRF).

    RRF gives each engine equal weight: score = sum(1/(k+rank)) across engines.
    Items appearing in both engines naturally score ~2x higher.
    k=60 is the standard RRF constant (dampens rank position differences).
    """
    k = 60  # RRF smoothing constant
    scores = {}   # memory_id -> rrf_score
    entries = {}  # memory_id -> best entry dict
    sources = {}  # memory_id -> set of source names

    # Score vector results by rank
    for rank, entry in enumerate(lance_summaries, start=1):
        mid = entry.get("id", "")
        if not mid:
            continue
        scores[mid] = scores.get(mid, 0) + 1 / (k + rank)
        entries[mid] = dict(entry)
        sources[mid] = {"semantic"}

    # Score FTS5 results by rank
    for rank, entry in enumerate(fts_results, start=1):
        mid = entry.get("id", "")
        if not mid:
            continue
        scores[mid] = scores.get(mid, 0) + 1 / (k + rank)
        if mid not in entries:
            entries[mid] = dict(entry)
        sources.setdefault(mid, set()).add("keyword")

    # Inject RRF score as relevance and set match label
    for mid, entry in entries.items():
        entry["relevance"] = scores[mid]
        entry["match"] = "both" if len(sources[mid]) > 1 else sources[mid].pop()

    results = list(entries.values())
    results.sort(key=lambda x: x.get("relevance", 0), reverse=True)

    return results[:top_k]


# Lazy initialization — only run when module is used as a server, not when imported
# for testing. LanceDB uses optimistic concurrency control (no more segfaults).
_preview_migrated = False
tag_index = TagIndex(db_path=TAGS_DB_PATH)
_tag_count = 0
_initialized = False
_lance_fts_ready = False  # True once LanceDB FTS index is built
_SERVER_START_TIME = time.time()  # Module load time — used for uptime reporting


def _lance_fts_to_summary(row):
    """Convert a LanceDB FTS result row to the standard summary dict format."""
    entry = {
        "id": row.get("id", ""),
        "preview": row.get("preview", row.get("text", "")[:SUMMARY_LENGTH]),
        "tags": row.get("tags", ""),
        "timestamp": row.get("timestamp", ""),
        "fts_score": round(row.get("_score", 0.0), 4),
    }
    url = row.get("primary_source", "")
    if url:
        entry["url"] = url
    return entry


def _lance_keyword_search(query, top_k=15):
    """LanceDB native BM25 keyword search. Falls back to empty on error."""
    if not _lance_fts_ready or collection is None:
        return []
    try:
        rows = collection._table.search(query).limit(top_k).to_list()
        return [_lance_fts_to_summary(r) for r in rows]
    except Exception:
        return []


def _generate_fuzzy_variants(term: str, max_distance: int = 1) -> list:
    """Generate spelling variants within edit distance for fuzzy matching."""
    if len(term) <= 2:
        return [term]

    variants = {term}
    alphabet = 'abcdefghijklmnopqrstuvwxyz0123456789_'

    # Deletions (remove one char)
    for i in range(len(term)):
        variants.add(term[:i] + term[i+1:])

    # Substitutions (replace one char)
    for i in range(len(term)):
        for c in alphabet:
            if c != term[i]:
                variants.add(term[:i] + c + term[i+1:])

    # Transpositions (swap adjacent chars)
    for i in range(len(term) - 1):
        variants.add(term[:i] + term[i+1] + term[i] + term[i+2:])

    return list(variants)


def _fuzzy_keyword_search(query: str, table_name: str = "knowledge", top_k: int = 10):
    """Search with fuzzy term expansion for typo tolerance.

    Splits query into terms, generates edit-distance-1 variants,
    queries LanceDB FTS with expanded terms, boosts exact matches 2x.
    """
    if not _lance_fts_ready:
        return []

    global collection, observations, fix_outcomes, web_pages
    tbl_map = {
        "knowledge": collection,
        "observations": observations,
        "fix_outcomes": fix_outcomes,
        "web_pages": web_pages,
    }
    tbl_coll = tbl_map.get(table_name, collection)
    if tbl_coll is None:
        return []

    terms = query.lower().split()
    if not terms:
        return []

    # Generate fuzzy variants for each term
    all_variants = []
    exact_terms = set(terms)
    for term in terms:
        all_variants.extend(_generate_fuzzy_variants(term))

    # Build OR query with all variants (LanceDB FTS supports OR)
    expanded_query = " OR ".join(set(all_variants))

    try:
        rows = tbl_coll._table.search(expanded_query, query_type="fts").limit(top_k * 2).to_list()
        if not rows:
            return []

        # Boost exact matches 2x
        scored_results = []
        for row in rows:
            text_lower = str(row.get("text", "")).lower()
            boost = 1.0
            for term in exact_terms:
                if term in text_lower:
                    boost = 2.0
                    break
            scored_results.append({
                "id": str(row.get("id", "")),
                "text": str(row.get("text", ""))[:500],
                "relevance": float(row.get("_score", 0.5)) * boost,
                "tags": str(row.get("tags", "")),
                "match_type": "exact" if boost > 1.0 else "fuzzy",
            })

        scored_results.sort(key=lambda x: x["relevance"], reverse=True)
        return scored_results[:top_k]
    except Exception:
        return []


def _tag_ids_to_summaries(memory_ids, collection_ref=None):
    """Fetch full metadata from LanceDB for a list of memory IDs."""
    if not memory_ids:
        return []
    coll = collection_ref or collection
    if coll is None:
        return []
    try:
        data = coll.get(ids=list(memory_ids), include=["metadatas"])
        results = []
        for i, mid in enumerate(data.get("ids", [])):
            meta = data["metadatas"][i] if i < len(data.get("metadatas", [])) else {}
            entry = {
                "id": mid,
                "preview": meta.get("preview", ""),
                "tags": meta.get("tags", ""),
                "timestamp": meta.get("timestamp", ""),
            }
            url = meta.get("primary_source", "")
            if url:
                entry["url"] = url
            results.append(entry)
        return results
    except Exception:
        return []


def _ensure_initialized():
    """Run one-time initialization (LanceDB + TagIndex + LanceDB FTS).

    Called lazily on first MCP tool use or explicitly at server startup.
    Safe to call multiple times — idempotent after first run.
    """
    global _preview_migrated, tag_index, _tag_count, _initialized, _lance_fts_ready
    if _initialized:
        return
    _init_lancedb()
    if collection is None:
        print("[MCP] LanceDB unavailable — starting in degraded mode.", file=_sys.stderr)
        _initialized = True
        return

    # Build LanceDB native FTS index on text column
    try:
        collection._table.create_fts_index("text", replace=True)
        _lance_fts_ready = True
    except Exception:
        pass  # FTS is optional — keyword search degrades gracefully

    # Check if persisted tag index is already synced with LanceDB
    lance_count = collection.count()
    if tag_index.is_synced(lance_count):
        _tag_count = lance_count
        _initialized = True
        return  # Skip rebuild — tag index is current

    _tag_count = tag_index.build_from_lance(collection)
    _initialized = True

# ──────────────────────────────────────────────────
# Tag Co-occurrence Matrix (lazy-built, cached)
# ──────────────────────────────────────────────────
_tag_cooccurrence: dict[str, dict[str, int]] = {}  # tag_a -> {tag_b: count}
_tag_counts: dict[str, int] = {}  # tag -> total memories with this tag
_tag_cooccurrence_dirty: bool = True  # rebuild on first use


def _build_tag_cooccurrence():
    """Build tag co-occurrence matrix from tag index.

    Scans all memory tags, counts how often tag pairs appear together.
    Called lazily on first search or explicitly via rebuild_tag_index().
    """
    global _tag_cooccurrence, _tag_counts, _tag_cooccurrence_dirty

    conn = tag_index.conn
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
    """Format query results into readable dicts."""
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
    """Format query results into compact summaries (id + preview).

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
            entry["tier"] = meta.get("tier", 2)
            entry["retrieval_count"] = int(meta.get("retrieval_count", 0))
            if meta.get("primary_source"):
                entry["url"] = meta["primary_source"]
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
    """Read the capture queue and upsert all observations to LanceDB.

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
            # Batch upsert (LanceDB handles dedup via merge_insert)
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

            # Promote high-value expired observations to curated knowledge (scoped criteria)
            promoted = 0

            def _promote_observation(doc, meta, criterion_tag):
                """Upsert a promoted observation into knowledge collection."""
                nonlocal promoted
                if promoted >= MAX_PROMOTIONS_PER_CYCLE:
                    return
                promo_id = hashlib.sha256(f"promoted:{doc}".encode()).hexdigest()[:16]
                promo_preview = doc[:SUMMARY_LENGTH].replace("\n", " ")
                if len(doc) > SUMMARY_LENGTH:
                    promo_preview += "..."
                collection.upsert(
                    documents=[doc],
                    metadatas=[{
                        "context": "auto-promoted from observation",
                        "tags": f"{PROMOTION_TAGS},{criterion_tag}",
                        "timestamp": datetime.now().isoformat(),
                        "session_time": time.time(),
                        "preview": promo_preview,
                        "original_error_pattern": meta.get("error_pattern", ""),
                    }],
                    ids=[promo_id],
                )
                promoted += 1

            # Criterion 1: Standalone errors (never fixed in same session)
            # Group by session, track which tools succeeded after errors
            session_success_tools = {}  # session_id -> set of tool names that succeeded
            session_errors = []  # (index, doc, meta) of error observations
            for i, doc in enumerate(exp_docs):
                meta = exp_metas[i] if i < len(exp_metas) else {}
                sid = meta.get("session_id", "")
                has_error = meta.get("has_error", "false")
                if has_error == "true" or meta.get("error_pattern", ""):
                    session_errors.append((i, doc, meta))
                else:
                    # Track successful tool uses per session
                    if sid:
                        session_success_tools.setdefault(sid, set()).add(meta.get("tool_name", ""))

            for idx, doc, meta in session_errors:
                if promoted >= MAX_PROMOTIONS_PER_CYCLE:
                    break
                sid = meta.get("session_id", "")
                tool = meta.get("tool_name", "")
                # Only promote if no subsequent success for same tool in same session
                if sid and tool and tool in session_success_tools.get(sid, set()):
                    continue  # Tool succeeded later — skip
                _promote_observation(doc, meta, "criterion:standalone-error")

            # Criterion 2: Cross-session file churn
            file_sessions = {}  # file_path -> set of session_ids
            for i, doc in enumerate(exp_docs):
                meta = exp_metas[i] if i < len(exp_metas) else {}
                sid = meta.get("session_id", "")
                tool = meta.get("tool_name", "")
                if tool in ("Edit", "Write") and sid:
                    parts = doc.split(":", 1)
                    if len(parts) > 1:
                        fp = parts[1].strip().split(" ")[0]
                        if fp:
                            file_sessions.setdefault(fp, set()).add(sid)

            for fp, sids in sorted(file_sessions.items(), key=lambda x: -len(x[1])):
                if promoted >= MAX_PROMOTIONS_PER_CYCLE:
                    break
                if len(sids) >= 5:
                    churn_doc = f"High-churn file: {fp} (edited in {len(sids)} sessions)"
                    _promote_observation(churn_doc, {}, "criterion:file-churn")

            # Criterion 3: Repeated command patterns (non-test, non-commit)
            cmd_counts = {}  # command -> count
            for i, doc in enumerate(exp_docs):
                meta = exp_metas[i] if i < len(exp_metas) else {}
                if meta.get("tool_name") != "Bash":
                    continue
                cmd = doc.split(":", 1)[1].strip() if ":" in doc else doc
                cmd = cmd[:200]  # Normalize length
                # Skip test and commit commands
                if any(kw in cmd for kw in ["pytest", "test_framework", "npm test", "cargo test", "go test", "git commit"]):
                    continue
                cmd_counts[cmd] = cmd_counts.get(cmd, 0) + 1

            for cmd, cnt in sorted(cmd_counts.items(), key=lambda x: -x[1]):
                if promoted >= MAX_PROMOTIONS_PER_CYCLE:
                    break
                if cnt >= 3:
                    repeat_doc = f"Repeated command: {cmd} ({cnt} occurrences)"
                    _promote_observation(repeat_doc, {}, "criterion:repeated-command")

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
                    # Returns in insertion order by default
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


def _search_observations_internal(query, top_k=20, recency_weight=0):
    """Internal helper to search observations collection.

    Used by search_knowledge mode="observations", mode="all", and auto-fallback.
    Returns dict with "results" list in same format as knowledge results.
    """
    try:
        _flush_capture_queue()
        obs_count = observations.count()
        if obs_count == 0:
            return {"results": [], "total_observations": 0}

        actual_k = min(top_k, obs_count)
        results = observations.query(query_texts=[query], n_results=actual_k)
        formatted = format_summaries(results)

        # Label all results as coming from observations
        for entry in formatted:
            entry["source"] = "observations"

        return {
            "results": formatted,
            "total_observations": obs_count,
        }
    except Exception:
        return {"results": [], "total_observations": 0, "error": "Observation search failed"}


@mcp.tool()
@crash_proof
def search_knowledge(query: str, top_k: int = 15, mode: str = "", recency_weight: float = 0.15, match_all: bool = False) -> dict:
    """Search memory for relevant information. Use before starting any task.

    Args:
        query: What to search for (semantic search)
        top_k: Number of results to return (default 15)
        mode: Force search mode ("keyword", "semantic", "hybrid", "tags", "observations", "all", "code"). Empty = auto-detect.
        recency_weight: Boost for recent results (0.0-1.0, default 0.15). 0 disables.
        match_all: For tag mode only — if true, all tags must be present (default false).
    """
    _ensure_initialized()
    if _lance_degraded:
        return {"error": "LanceDB unavailable — running in degraded mode", "degraded": True}
    recency_weight = max(0.0, min(1.0, recency_weight))
    top_k = _validate_top_k(top_k, default=15, min_val=1, max_val=500)
    count = collection.count()
    if count == 0:
        return {"results": [], "total_memories": 0, "message": "Memory is empty. Start building knowledge with remember_this()."}

    # Read config toggles once for the pipeline (needed by routing + enrichment)
    _config_path = os.path.join(os.path.expanduser("~"), ".claude", "config.json")
    _ls_toggles = {}
    try:
        if os.path.isfile(_config_path):
            with open(_config_path, "r") as _lsf:
                _ls_toggles = json.load(_lsf)
    except Exception:
        # Fall back to LIVE_STATE.json for backward compat
        _live_state_path = os.path.join(os.path.expanduser("~"), ".claude", "LIVE_STATE.json")
        try:
            if os.path.isfile(_live_state_path):
                with open(_live_state_path, "r") as _lsf:
                    _ls_toggles = json.load(_lsf)
        except Exception:
            pass

    VALID_MODES = {"keyword", "semantic", "hybrid", "tags", "observations", "all", "transcript"}
    if mode and mode not in VALID_MODES:
        mode = ""  # Invalid mode falls back to auto-detect
    if not mode:
        _routing = _ls_toggles.get("search_routing", "default")
        mode = _detect_query_mode(query, routing=_routing)

    # Query alias expansion: historical name mappings
    QUERY_ALIASES = {
        "torus": "megaman",
        "megaman": "torus",
    }
    query_lower = query.lower()
    for alias_from, alias_to in QUERY_ALIASES.items():
        if alias_from in query_lower and alias_to not in query_lower:
            query = f"{query} {alias_to}"
            break

    # Handle observations-only mode
    if mode == "observations":
        result = _search_observations_internal(query, top_k, recency_weight)
        result["mode"] = "observations"
        result["query"] = query
        result["total_memories"] = count
        _touch_memory_timestamp()
        return result

    # Handle transcript mode: search L2t FTS5, then read raw L0 JSONL
    if mode == "transcript":
        _touch_memory_timestamp()
        _transcript_enabled = _ls_toggles.get("transcript_l0", False)
        if not _transcript_enabled:
            return {
                "results": [],
                "mode": "transcript",
                "query": query,
                "total_memories": count,
                "source": "transcript_l0",
                "disabled": True,
                "hint": "Enable with transcript_l0: true in config.json",
            }
        transcript_results = []
        try:
            _term_db = os.path.join(os.path.expanduser("~"), ".claude",
                                    "integrations", "terminal-history",
                                    "terminal_history.db")
            if os.path.isfile(_term_db):
                _term_dir = os.path.join(os.path.expanduser("~"), ".claude",
                                         "integrations", "terminal-history")
                if _term_dir not in _sys.path:
                    _sys.path.insert(0, _term_dir)
                from db import search_fts as _t_search_fts
                from db import get_raw_transcript_window as _get_raw_window
                hits = _t_search_fts(_term_db, query, limit=10)
                # Deduplicate by session_id, keep best-ranked per session
                seen_sessions = {}
                for hit in hits:
                    sid = hit.get("session_id", "")
                    if sid and sid not in seen_sessions:
                        seen_sessions[sid] = hit.get("timestamp", "")
                # Get raw transcript windows for top 3 sessions
                for sid, ts in list(seen_sessions.items())[:3]:
                    window = _get_raw_window(sid, around_timestamp=ts,
                                             window_minutes=10, max_records=30)
                    transcript_results.append(window)
        except Exception:
            pass
        return {
            "results": transcript_results,
            "mode": "transcript",
            "query": query,
            "total_memories": count,
            "source": "transcript_l0",
        }

    actual_k = min(top_k, count)

    if mode == "tags":
        # Strip tag:/tags: prefix and parse
        tag_query = re.sub(r"^tags?:\s*", "", query, flags=re.IGNORECASE)
        tags_list = [t.strip() for t in tag_query.split(",") if t.strip()]
        tag_ids = tag_index.tag_search(tags_list, match_all=match_all, top_k=actual_k)
        formatted = _tag_ids_to_summaries(tag_ids)
    elif mode == "keyword":
        formatted = _lance_keyword_search(query, top_k=actual_k)
    elif mode == "hybrid":
        # Both engines, merged via RRF
        fts_results = _lance_keyword_search(query, top_k=actual_k)
        lance_results = collection.query(
            query_texts=[query], n_results=actual_k,
            include=["metadatas", "distances"],
        )
        lance_summaries = format_summaries(lance_results)
        formatted = _merge_results(fts_results, lance_summaries, top_k=actual_k)
    else:
        # Semantic (default)
        results = collection.query(
            query_texts=[query], n_results=actual_k,
            include=["metadatas", "distances"],
        )
        formatted = format_summaries(results)

    _terminal_l2_always = _ls_toggles.get("terminal_l2_always", True)
    _tg_l3_always = _ls_toggles.get("tg_l3_always", False)
    _enrichment_enabled = _ls_toggles.get("context_enrichment", False)
    _tg_enrichment_enabled = _ls_toggles.get("tg_enrichment", False)

    # Terminal History L2: search based on toggle
    terminal_l2_count = 0
    _run_terminal_l2 = _terminal_l2_always or (
        formatted and all(r.get("relevance", 0) < 0.3 for r in formatted if not r.get("linked"))
    )
    if _run_terminal_l2:
        try:
            _term_db_path_l2 = os.path.join(os.path.expanduser("~"), ".claude",
                                            "integrations", "terminal-history",
                                            "terminal_history.db")
            if os.path.isfile(_term_db_path_l2):
                _term_dir_l2 = os.path.join(os.path.expanduser("~"), ".claude",
                                            "integrations", "terminal-history")
                if _term_dir_l2 not in _sys.path:
                    _sys.path.insert(0, _term_dir_l2)
                from db import search_fts as _search_fts
                for tr in _search_fts(_term_db_path_l2, query, limit=5):
                    _bm25 = abs(float(tr.get("bm25", 0)))
                    _relevance = min(1.0, _bm25 / 20.0)
                    _entry = {
                        "id": f"term_{tr.get('session_id', '?')[:12]}",
                        "preview": (tr.get("text", "")[:120] + "...") if len(tr.get("text", "")) > 120 else tr.get("text", ""),
                        "relevance": round(_relevance, 4),
                        "source": "terminal_l2",
                        "timestamp": tr.get("timestamp", ""),
                    }
                    if tr.get("tags"):
                        _entry["tags"] = tr["tags"]
                    if tr.get("linked_memory_ids"):
                        _entry["linked_memory_ids"] = tr["linked_memory_ids"]
                    formatted.append(_entry)
                    terminal_l2_count += 1
        except Exception:
            pass  # Terminal history search is optional

    # L0 Raw Transcript cascade: when toggle is on, pull raw JSONL windows
    # between L2 (terminal history) and L3 (telegram)
    transcript_l0_count = 0
    _transcript_l0_enabled = _ls_toggles.get("transcript_l0", False)
    if _transcript_l0_enabled and mode not in ("tags", "observations"):
        # Only cascade if current results are weak (< 0.3) or always-on
        _l0_weak = not formatted or all(
            r.get("relevance", 0) < 0.3 for r in formatted
            if not r.get("linked") and not r.get("tag_expanded")
        )
        if _l0_weak:
            try:
                _term_db_l0 = os.path.join(os.path.expanduser("~"), ".claude",
                                           "integrations", "terminal-history",
                                           "terminal_history.db")
                if os.path.isfile(_term_db_l0):
                    _term_dir_l0 = os.path.join(os.path.expanduser("~"), ".claude",
                                                "integrations", "terminal-history")
                    if _term_dir_l0 not in _sys.path:
                        _sys.path.insert(0, _term_dir_l0)
                    from db import search_fts as _l0_search_fts
                    from db import get_raw_transcript_window as _l0_get_raw_window
                    _l0_hits = _l0_search_fts(_term_db_l0, query, limit=6)
                    # Deduplicate by session_id
                    _l0_seen_sessions = {}
                    for _l0_hit in _l0_hits:
                        _l0_sid = _l0_hit.get("session_id", "")
                        if _l0_sid and _l0_sid not in _l0_seen_sessions:
                            _l0_seen_sessions[_l0_sid] = _l0_hit.get("timestamp", "")
                    # Get raw transcript windows for top 2 sessions
                    for _l0_sid, _l0_ts in list(_l0_seen_sessions.items())[:2]:
                        _l0_window = _l0_get_raw_window(
                            _l0_sid, around_timestamp=_l0_ts,
                            window_minutes=10, max_records=20
                        )
                        if _l0_window and _l0_window.get("records"):
                            # Compress into a single result entry
                            _l0_preview = "; ".join(
                                r.get("summary", r.get("text", ""))[:80]
                                for r in _l0_window.get("records", [])[:3]
                            )
                            formatted.append({
                                "id": f"l0_{_l0_sid[:16]}",
                                "preview": _l0_preview[:200],
                                "relevance": 0.22,
                                "source": "transcript_l0",
                                "timestamp": _l0_ts,
                                "session_id": _l0_sid,
                                "record_count": len(_l0_window.get("records", [])),
                            })
                            transcript_l0_count += 1
            except Exception:
                pass  # L0 transcript cascade is optional

    # Tag expansion: find co-occurring tags and merge additional results
    tag_expanded = False
    expanded_tags = []
    try:
        expanded_tags = _get_expanded_tags(query)
        if expanded_tags:
            seen_ids = {r.get("id") for r in formatted if r.get("id")}
            tag_ids = tag_index.tag_search(expanded_tags, match_all=False, top_k=actual_k)
            tag_results = _tag_ids_to_summaries(tag_ids)
            if tag_results:
                for tr in tag_results:
                    tid = tr.get("id", "")
                    if tid and tid not in seen_ids:
                        tr["tag_expanded"] = True
                        formatted.append(tr)
                        seen_ids.add(tid)
                tag_expanded = True

            # Terminal L2 tag search: find terminal records matching expanded tags
            try:
                _term_db_path = os.path.join(os.path.expanduser("~"), ".claude",
                                             "integrations", "terminal-history",
                                             "terminal_history.db")
                if os.path.isfile(_term_db_path):
                    _term_dir = os.path.join(os.path.expanduser("~"), ".claude",
                                             "integrations", "terminal-history")
                    if _term_dir not in _sys.path:
                        _sys.path.insert(0, _term_dir)
                    from db import search_by_tags as _search_by_tags
                    _tag_term_results = _search_by_tags(_term_db_path, expanded_tags, limit=3)
                    for ttr in _tag_term_results:
                        _tid = f"term_tag_{ttr.get('session_id', '?')[:12]}"
                        if _tid not in seen_ids:
                            formatted.append({
                                "id": _tid,
                                "preview": (ttr.get("text", "")[:120] + "...") if len(ttr.get("text", "")) > 120 else ttr.get("text", ""),
                                "relevance": 0.25,
                                "source": "terminal_l2",
                                "timestamp": ttr.get("timestamp", ""),
                                "tags": ttr.get("tags", ""),
                                "tag_expanded": True,
                            })
                            seen_ids.add(_tid)
            except Exception:
                pass  # Terminal tag search is optional
    except Exception:
        pass  # Tag expansion failure must not break search

    # Keyword overlap reranker — gives keyword signal to all modes
    try:
        formatted = _rerank_keyword_overlap(formatted, query)
    except Exception:
        pass  # Reranker failure must not break search

    # Apply recency boost and re-sort
    if recency_weight > 0:
        formatted = _apply_recency_boost(formatted, recency_weight)

    # Apply tier boost: tier 1 (+0.05), tier 3 (-0.02)
    try:
        formatted = _apply_tier_boost(formatted)
    except Exception:
        pass  # Tier boost failure must not break search

    # Apply access-count boost: tiebreaker for frequently-retrieved memories (max +0.03)
    try:
        formatted = _apply_access_boost(formatted)
    except Exception:
        pass  # Access boost failure must not break search

    # Trim to requested top_k after expansion
    formatted = formatted[:top_k]

    # "all" mode: also search observations and merge
    if mode == "all":
        # Reserve ~1/3 of budget for observations so they actually appear
        obs_budget = max(3, top_k // 3)
        knowledge_budget = top_k - obs_budget
        formatted = formatted[:knowledge_budget]  # Trim knowledge to make room
        obs_results = _search_observations_internal(query, obs_budget, recency_weight=0)
        obs_formatted = obs_results.get("results", [])
        # Label and merge observation results (dedup by ID)
        seen_ids = {r.get("id") for r in formatted if r.get("id")}
        for obs in obs_formatted:
            oid = obs.get("id", "")
            if oid and oid not in seen_ids:
                obs["source"] = "observations"
                formatted.append(obs)
                seen_ids.add(oid)

    # Auto-fallback: if knowledge returned 0 results and mode was auto-detected, try observations
    if len(formatted) == 0 and mode not in ("tags", "observations", "all"):
        obs_results = _search_observations_internal(query, min(top_k, 10), recency_weight=0)
        obs_formatted = obs_results.get("results", [])
        if obs_formatted:
            for obs in obs_formatted:
                obs["source"] = "observations"
                obs["fallback"] = True
            formatted = obs_formatted
            mode = mode + "+fallback"

    _touch_memory_timestamp()

    # Trim to requested top_k after all merging
    formatted = formatted[:top_k]

    # --- Hybrid Memory Linking: co-retrieve linked memories ---
    linked_memories_count = 0
    try:
        # Collect linked IDs from resolves: and resolved_by: tags
        organic_ids = {r.get("id") for r in formatted if r.get("id")}
        linked_ids = set()
        for r in formatted:
            r_tags = r.get("tags", "") or ""
            for tag in r_tags.split(","):
                tag = tag.strip()
                if tag.startswith("resolves:"):
                    lid = tag.split(":", 1)[1].strip()
                    if lid and lid not in organic_ids:
                        linked_ids.add(lid)
                elif tag.startswith("resolved_by:"):
                    lid = tag.split(":", 1)[1].strip()
                    if lid and lid not in organic_ids:
                        linked_ids.add(lid)

            # Terminal L2 linked_memory_ids: memory IDs linked to terminal records
            r_linked = r.get("linked_memory_ids", "") or ""
            if r_linked and r.get("source") == "terminal_l2":
                for mid in r_linked.split(","):
                    mid = mid.strip()
                    if mid and mid not in organic_ids:
                        linked_ids.add(mid)

        # Batch fetch linked memories
        if linked_ids:
            linked_results = collection.get(
                ids=list(linked_ids),
                include=["metadatas", "documents"],
            )
            if linked_results and linked_results.get("ids"):
                l_ids = linked_results["ids"]
                l_metas = linked_results.get("metadatas") or [{}] * len(l_ids)
                l_docs = linked_results.get("documents") or [""] * len(l_ids)
                for i, lid in enumerate(l_ids):
                    meta = l_metas[i] if i < len(l_metas) else {}
                    doc = l_docs[i] if i < len(l_docs) else ""
                    preview = meta.get("preview", "") or (doc[:120] + "..." if doc and len(doc) > 120 else doc)
                    formatted.append({
                        "id": lid,
                        "preview": preview,
                        "tags": meta.get("tags", ""),
                        "timestamp": meta.get("timestamp", ""),
                        "linked": True,
                    })
                    linked_memories_count += 1
    except Exception:
        pass  # Fail-open: linking errors don't break search

    # Telegram L3: search based on toggle
    tg_fallback_count = 0
    _run_tg_l3 = _tg_l3_always or (
        formatted and all(r.get("relevance", 0) < 0.3 for r in formatted if not r.get("linked"))
    )
    if _run_tg_l3:
        try:
            _tg_search = os.path.join(os.path.expanduser("~"), ".claude", "integrations",
                                      "telegram-bot", "search.py")
            if os.path.isfile(_tg_search):
                _tg_result = subprocess.run(
                    [_sys.executable, _tg_search, query, "--json", "--limit", "5"],
                    capture_output=True, text=True, timeout=8, stdin=subprocess.DEVNULL,
                )
                if _tg_result.returncode == 0 and _tg_result.stdout.strip():
                    _tg_data = json.loads(_tg_result.stdout)
                    for tr in _tg_data.get("results", []):
                        # Normalize BM25: FTS5 rank is negative, more negative = better
                        _bm25 = abs(float(tr.get("bm25", 0)))
                        _relevance = min(1.0, _bm25 / 20.0) if _bm25 > 0 else 0.2
                        formatted.append({
                            "id": f"tg_{tr.get('msg_id', '?')}",
                            "preview": (tr.get("text", "")[:120] + "...") if len(tr.get("text", "")) > 120 else tr.get("text", ""),
                            "relevance": round(_relevance, 4),
                            "source": "telegram_l3",
                            "timestamp": tr.get("date", ""),
                        })
                        tg_fallback_count += 1
        except Exception:
            pass  # Telegram fallback is optional

    # Final trim: enforce top_k budget after all sources (L3, linked) have been appended
    formatted = formatted[:top_k]

    # Session context enrichment: attach conversation context to vector search hits
    enrichment_count = 0
    try:
        if _enrichment_enabled:
            _term_db = os.path.join(os.path.expanduser("~"), ".claude", "integrations",
                                    "terminal-history", "terminal_history.db")
            if os.path.isfile(_term_db):
                # Lazy import to avoid overhead when enrichment is off
                _term_db_dir = os.path.join(os.path.expanduser("~"), ".claude",
                                            "integrations", "terminal-history")
                if _term_db_dir not in _sys.path:
                    _sys.path.insert(0, _term_db_dir)
                from db import get_context_by_timestamp as _get_ctx

                for r in list(formatted):
                    if r.get("linked") or r.get("source", "").startswith("terminal_"):
                        continue  # Don't enrich already-linked or terminal results
                    ts = r.get("timestamp", "")
                    if not ts:
                        continue
                    ctx = _get_ctx(_term_db, ts, window_minutes=30, limit=3)
                    if ctx:
                        ctx_text = " | ".join(
                            f"[{c['role']}] {c['text'][:80]}" for c in ctx
                        )
                        r["session_context"] = ctx_text[:300]
                        enrichment_count += 1
    except Exception:
        pass  # Enrichment is optional, never break search

    # TG context enrichment: attach Telegram messages around search hit timestamps
    tg_enrichment_count = 0
    try:
        if _tg_enrichment_enabled:
            _tg_db = os.path.join(os.path.expanduser("~"), ".claude", "integrations",
                                  "telegram-bot", "msg_log.db")
            if os.path.isfile(_tg_db):
                _tg_db_dir = os.path.join(os.path.expanduser("~"), ".claude",
                                          "integrations", "telegram-bot")
                if _tg_db_dir not in _sys.path:
                    _sys.path.insert(0, _tg_db_dir)
                from db import get_context_by_timestamp as _get_tg_ctx

                for r in list(formatted):
                    if r.get("linked") or r.get("source", "").startswith("telegram_"):
                        continue  # Don't enrich already-linked or TG results
                    ts = r.get("timestamp", "")
                    if not ts:
                        continue
                    tg_ctx = _get_tg_ctx(_tg_db, ts, window_minutes=30, limit=3)
                    if tg_ctx:
                        tg_ctx_text = " | ".join(
                            f"[{c['sender']}] {c['text'][:80]}" for c in tg_ctx
                        )
                        r["tg_context"] = tg_ctx_text[:300]
                        tg_enrichment_count += 1
    except Exception:
        pass  # TG enrichment is optional, never break search

    result = {
        "results": formatted,
        "total_memories": count,
        "query": query,
        "mode": mode,
    }
    if linked_memories_count > 0:
        result["linked_memories_count"] = linked_memories_count
    if tg_fallback_count > 0:
        result["telegram_l3_count"] = tg_fallback_count
    if terminal_l2_count > 0:
        result["terminal_l2_count"] = terminal_l2_count
    if transcript_l0_count > 0:
        result["transcript_l0_count"] = transcript_l0_count
    if enrichment_count > 0:
        result["enrichment_count"] = enrichment_count
    if tg_enrichment_count > 0:
        result["tg_enrichment_count"] = tg_enrichment_count
    if tag_expanded:
        result["tag_expanded"] = True
        result["expanded_tags"] = expanded_tags
    return result


def _bridge_to_fix_outcomes(content, context, tags):
    """Bridge remember_this to fix_outcomes when type:fix tag is detected.

    Extracts error info from content, creates a fix_outcomes entry if one
    doesn't already exist (dedup: manual record_outcome takes priority).
    Returns dict with chain_id on success, None on skip/failure.
    """
    try:
        if fix_outcomes is None:
            return None

        # Try to extract error pattern from content
        # Common patterns: "Fixed KeyError ...", "Fixed ImportError ..."
        import re
        error_match = re.search(
            r'(?:Fixed|Resolved|fixed|resolved)\s+(\S+(?:Error|Exception|FAILED|error)\S*)',
            content
        )
        error_text = error_match.group(1) if error_match else content[:100]

        # Extract strategy from content if possible
        strategy_match = re.search(
            r'(?:using|via|by|with)\s+(.+?)(?:\.|,|$)',
            content
        )
        strategy_id = strategy_match.group(1).strip()[:80] if strategy_match else "auto-bridged"

        normalized, error_hash = error_signature(error_text)
        strategy_hash = fnv1a_hash(strategy_id)
        chain_id = f"{error_hash}_{strategy_hash}"

        # Dedup: skip if manual record_outcome already exists for this chain
        try:
            existing = fix_outcomes.get(ids=[chain_id])
            if (existing and existing.get("documents") and len(existing["documents"]) > 0):
                meta = existing["metadatas"][0] if existing.get("metadatas") else {}
                if meta.get("outcome") in ("success", "failure"):
                    return None  # Manual chain already recorded — defer
        except Exception:
            pass

        # Determine outcome: type:fix usually means success
        outcome = "success"
        if any(kw in tags for kw in ("outcome:failed", "outcome:failure")):
            outcome = "failure"

        successes = 1 if outcome == "success" else 0
        attempts = 1
        confidence = _compute_confidence(successes, attempts)

        fix_outcomes.upsert(
            documents=[normalized],
            metadatas=[{
                "error_hash": error_hash,
                "strategy_id": strategy_id,
                "chain_id": chain_id,
                "outcome": outcome,
                "confidence": str(round(confidence, 4)),
                "attempts": str(attempts),
                "successes": str(successes),
                "timestamp": str(time.time()),
                "last_outcome_time": str(time.time()),
                "bridged": "true",
            }],
            ids=[chain_id],
        )
        return {"chain_id": chain_id, "outcome": outcome}
    except Exception:
        return None


def _check_dedup(content, tags=""):
    """Check if content is a near-duplicate of existing knowledge.

    Returns None if unique, or a dict:
      - {"blocked": True, "existing_id": ..., "distance": ...} if hard-dedup
      - {"soft_dupe_tag": "possible-dupe:ID"} if in soft zone
    """
    if _FIX_DEDUP_EXEMPT and "type:fix" in tags:
        return None
    try:
        cnt = collection.count()
        if cnt == 0:
            return None
        similar = collection.query(
            query_texts=[content], n_results=1,
            include=["distances"],
        )
        if (similar and similar.get("distances") and similar["distances"][0]
                and similar["distances"][0][0] is not None):
            dist = similar["distances"][0][0]
            existing_id = similar["ids"][0][0]
            threshold = FIX_DEDUP_THRESHOLD if "type:fix" in tags else DEDUP_THRESHOLD
            if dist < threshold:
                return {"blocked": True, "existing_id": existing_id, "distance": round(dist, 4)}
            elif dist < DEDUP_SOFT_THRESHOLD:
                return {"soft_dupe_tag": f"possible-dupe:{existing_id}"}
    except Exception:
        pass
    return None


@mcp.tool()
@crash_proof
def fuzzy_search(query: str, top_k: int = 10, table: str = "knowledge") -> dict:
    """Search memory with typo tolerance and boosted relevance.

    Like search_knowledge but handles misspellings and typos by expanding
    search terms with edit-distance variants. Exact matches get 2x boost.

    Args:
        query: Search query (typos OK)
        top_k: Max results (default 10)
        table: Table to search (knowledge, observations, fix_outcomes)
    """
    _ensure_initialized()
    if _lance_degraded:
        return {"error": "LanceDB unavailable — running in degraded mode", "degraded": True}

    if not query or not query.strip():
        return {"error": "Empty query"}

    valid_tables = {"knowledge", "observations", "fix_outcomes", "web_pages"}
    if table not in valid_tables:
        table = "knowledge"

    top_k = _validate_top_k(top_k, default=10, min_val=1, max_val=100)
    results = _fuzzy_keyword_search(query.strip(), table, top_k)
    return {"query": query, "table": table, "results": results, "count": len(results)}


@mcp.tool()
@crash_proof
def remember_this(content: str, context: str = "", tags: str = "", force: bool = False) -> dict:
    """Save something to persistent memory. Use after every fix, discovery, or decision.

    Args:
        content: The knowledge to remember (be specific and detailed)
        context: What you were doing when you learned this
        tags: Comma-separated tags for categorization (e.g., "bug,fix,auth")
        force: Skip dedup check entirely (escape hatch if threshold is wrong)
    """
    _ensure_initialized()
    if _lance_degraded:
        return {"error": "LanceDB unavailable — running in degraded mode", "degraded": True}
    # Cap metadata strings to 500 chars
    if len(context) > 500:
        context = context[:497] + "..."
    if len(tags) > 500:
        tags = tags[:497] + "..."
    # --- Tag normalization: bare tags → dimensioned tags ---
    tags = _normalize_tags(tags)
    # --- Ingestion filter: reject noise ---
    # force=True skips both noise filter AND dedup (escape hatch for false positives)
    if len(content.strip()) < MIN_CONTENT_LENGTH:
        return {
            "result": "Rejected: content too short (minimum 20 characters)",
            "rejected": True,
            "total_memories": collection.count(),
        }

    if not force:
        _content_len = len(content.strip())
        for noise_re in NOISE_REGEXES:
            if noise_re.search(content):
                # Length exemption: substantive content (>85 chars) starting with
                # noise words is likely a real finding, not package manager output.
                # Noise output maxes ~81 chars; valid knowledge starts at ~90+.
                if _content_len > 85:
                    break
                return {
                    "result": f"Rejected: matches noise pattern ('{noise_re.pattern}')",
                    "rejected": True,
                    "total_memories": collection.count(),
                }

    # --- Near-dedup: tiered threshold with soft-dupe tagging ---
    _soft_dupe_tag = None  # set if in soft zone (0.10-0.15)
    dedup_result = _check_dedup(content, tags) if not force else None
    if dedup_result:
        if dedup_result.get("blocked"):
            return {
                "result": "Deduplicated: very similar memory already exists",
                "deduplicated": True,
                "existing_id": dedup_result["existing_id"],
                "distance": dedup_result["distance"],
                "total_memories": collection.count(),
            }
        elif dedup_result.get("soft_dupe_tag"):
            _soft_dupe_tag = dedup_result["soft_dupe_tag"]

    # Citation URL extraction (fail-open)
    citation = _extract_citations(content, context)
    content = citation["clean_content"]
    primary_source = citation["primary_source"]
    related_urls = citation["related_urls"]
    source_method = citation["source_method"]

    doc_id = generate_id(content)
    timestamp = datetime.now().isoformat()

    # Pre-compute preview for progressive disclosure (stored in metadata)
    preview = content[:SUMMARY_LENGTH].replace("\n", " ")
    if len(content) > SUMMARY_LENGTH:
        preview += "..."

    now = time.time()

    # Append soft-dupe tag if in borderline zone
    if _soft_dupe_tag:
        tags = f"{tags},{_soft_dupe_tag}" if tags else _soft_dupe_tag

    # Auto tier classification
    tier = _classify_tier(content, tags)

    collection.upsert(
        documents=[content],
        metadatas=[{
            "context": context,
            "tags": tags,
            "timestamp": timestamp,
            "session_time": now,
            "preview": preview,
            "primary_source": primary_source,
            "related_urls": related_urls,
            "source_method": source_method,
            "tier": tier,
        }],
        ids=[doc_id],
    )

    # Update tag index
    tag_index.add_tags(doc_id, tags)

    # Mark tag co-occurrence matrix as dirty (new tags may change co-occurrence rates)
    global _tag_cooccurrence_dirty
    if tags:
        _tag_cooccurrence_dirty = True

    _touch_memory_timestamp()

    # --- Hybrid Memory Linking: resolves:ID → resolved_by:ID bidirectional link ---
    resolves_id = None
    link_warning = None
    try:
        if tags:
            resolves_tags = [t.strip() for t in tags.split(",") if t.strip().startswith("resolves:")]
            if len(resolves_tags) > 1:
                link_warning = f"Multiple resolves: tags found; using first: {resolves_tags[0]}"
            if resolves_tags:
                resolves_id = resolves_tags[0].split(":", 1)[1].strip()
                if not resolves_id:
                    resolves_id = None
                    link_warning = "resolves: tag has empty ID"
    except Exception as e:
        link_warning = f"Tag parse error: {e}"
        resolves_id = None

    # Validate target exists and create bidirectional link
    linked_to = None
    if resolves_id:
        try:
            target = collection.get(ids=[resolves_id], include=["metadatas"])
            if not target or not target.get("ids") or len(target["ids"]) == 0:
                link_warning = f"resolves:{resolves_id} — target memory not found"
                resolves_id = None
            else:
                # Create bidirectional link: update target's tags with resolved_by:NEW_ID
                target_meta = target["metadatas"][0] if target.get("metadatas") else {}
                target_tags = target_meta.get("tags", "") or ""
                back_link = f"resolved_by:{doc_id}"

                if back_link not in target_tags:
                    new_tags = f"{target_tags},{back_link}" if target_tags else back_link
                    if len(new_tags) > 500:
                        link_warning = f"Tag overflow (>{500} chars) — skipped resolved_by: back-link on target"
                    else:
                        target_meta_updated = dict(target_meta)
                        target_meta_updated["tags"] = new_tags
                        collection.update(ids=[resolves_id], metadatas=[target_meta_updated])

                        # Update tag index for updated target tags
                        try:
                            tag_index.add_tags(resolves_id, new_tags)
                        except Exception:
                            pass  # Tag index sync failure is non-critical

                linked_to = resolves_id
        except Exception as e:
            link_warning = f"Linking error: {e}"
            resolves_id = None

    # Option B bridge: auto-write to fix_outcomes when type:fix tag detected
    bridge_result = None
    if tags and "type:fix" in tags:
        bridge_result = _bridge_to_fix_outcomes(content, context, tags)

    result = {
        "result": "Memory stored successfully!",
        "id": doc_id,
        "total_memories": collection.count(),
        "timestamp": timestamp,
    }
    if bridge_result:
        result["fix_outcome_bridged"] = True
        result["bridge_chain_id"] = bridge_result.get("chain_id", "")

    # Hybrid linking response fields
    if linked_to:
        result["linked_to"] = linked_to
    if link_warning:
        result["link_warning"] = link_warning
    if tags and "type:fix" in tags and not resolves_id and not linked_to:
        result["hint"] = "Tip: add a resolves:MEMORY_ID tag to link this fix to the problem memory it resolves"

    return result


# DORMANT — saves ~70 tokens/prompt. Uncomment @mcp.tool() to reactivate.
# @mcp.tool()
@crash_proof
def deduplicate_sweep(dry_run: bool = True, threshold: float = 0.15) -> dict:
    """Batch scan for duplicate memories. Dry-run by default — shows candidates without acting.

    Args:
        dry_run: If True (default), only report candidate pairs. If False, move dupes to quarantine.
        threshold: Cosine distance threshold for duplicate detection (default 0.15)
    """
    _ensure_initialized()
    if _lance_degraded:
        return {"error": "LanceDB unavailable — running in degraded mode"}
    threshold = _validate_distance_threshold(threshold, default=0.15, min_val=0.03, max_val=0.5)

    count = collection.count()
    if count == 0:
        return {"candidates": [], "moved": 0, "message": "No memories to scan"}

    # Export backup before any changes
    backup_file = os.path.join(MEMORY_DIR, f"dedup_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    all_data = collection.get(limit=count, include=["documents", "metadatas", "embeddings"])
    with open(backup_file, "w") as f:
        # Embeddings are lists of floats — JSON-serializable
        json.dump({
            "ids": all_data.get("ids", []),
            "documents": all_data.get("documents", []),
            "metadatas": all_data.get("metadatas", []),
            "count": count,
            "exported_at": datetime.now().isoformat(),
        }, f)

    # Scan for duplicates
    candidates = []
    seen_pairs = set()
    ids = all_data.get("ids", [])
    docs = all_data.get("documents", []) or []
    metas = all_data.get("metadatas", []) or []

    for i, doc in enumerate(docs):
        if not doc:
            continue
        try:
            similar = collection.query(
                query_texts=[doc], n_results=2,
                include=["distances"],
            )
            if not similar or not similar.get("distances") or not similar["distances"][0]:
                continue
            # First result is self (distance ~0), second is nearest neighbor
            for j, (sid, sdist) in enumerate(zip(similar["ids"][0], similar["distances"][0])):
                if sid == ids[i]:
                    continue  # skip self
                if sdist < threshold:
                    pair_key = tuple(sorted([ids[i], sid]))
                    if pair_key not in seen_pairs:
                        seen_pairs.add(pair_key)
                        candidates.append({
                            "id_a": ids[i],
                            "id_b": sid,
                            "distance": round(sdist, 4),
                            "preview_a": (metas[i].get("preview", "") if i < len(metas) else "")[:80],
                        })
        except Exception:
            continue

    moved = 0
    if not dry_run and quarantine is not None:
        for cand in candidates:
            try:
                # Move the second item (id_b) to quarantine
                victim_id = cand["id_b"]
                victim = collection.get(ids=[victim_id], include=["documents", "metadatas"])
                if victim and victim.get("ids") and victim["ids"]:
                    v_doc = victim["documents"][0] if victim.get("documents") else ""
                    v_meta = victim["metadatas"][0] if victim.get("metadatas") else {}
                    v_meta["quarantine_reason"] = f"dedup_sweep:distance={cand['distance']}"
                    v_meta["quarantine_pair"] = cand["id_a"]
                    v_meta["quarantined_at"] = datetime.now().isoformat()
                    quarantine.upsert(documents=[v_doc], metadatas=[v_meta], ids=[victim_id])
                    collection.delete(ids=[victim_id])
                    # Remove from tag index
                    try:
                        tag_index.remove(victim_id)
                    except Exception:
                        pass
                    moved += 1
            except Exception:
                continue

    return {
        "candidates": candidates[:100],  # Cap report at 100 pairs
        "total_candidates": len(candidates),
        "moved": moved,
        "dry_run": dry_run,
        "threshold": threshold,
        "backup_file": backup_file,
        "total_memories": collection.count(),
    }




@mcp.tool()
@crash_proof
def get_memory(id: str) -> dict:
    """Retrieve full content for a specific memory by ID.

    Use after search_knowledge to get complete details for relevant entries.

    Args:
        id: The memory ID (from search results)
    """
    _ensure_initialized()
    if _lance_degraded:
        return {"error": "LanceDB unavailable — running in degraded mode", "degraded": True}
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

                # Citation URLs
                primary = meta.get("primary_source", "")
                related = meta.get("related_urls", "")
                if primary or related:
                    entry["citations"] = {
                        "primary_source": primary,
                        "related_urls": [u.strip() for u in related.split(",") if u.strip()],
                        "source_method": meta.get("source_method", ""),
                    }

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



# DORMANT — saves ~50 tokens/prompt. Uncomment @mcp.tool() to reactivate.
# @mcp.tool()
@crash_proof
def delete_memory(id: str) -> dict:
    """Delete a memory by ID. Use for removing sensitive or incorrect data.

    Args:
        id: The memory ID to delete (from search results). Comma-separated for batch delete.
    """
    if _lance_degraded:
        return {"error": "LanceDB unavailable — running in degraded mode", "degraded": True}
    try:
        ids = [i.strip() for i in id.split(",") if i.strip()]
        if not ids:
            return {"error": "No valid ID provided"}
        existing = collection.get(ids=ids)
        found = existing.get("ids", []) if existing else []
        if not found:
            return {"error": f"No memories found with ids: {ids}"}
        collection.delete(ids=found)
        return {"deleted": found, "count": len(found)}
    except Exception as e:
        return {"error": f"Failed to delete memory: {str(e)}"}




# DORMANT (Session 86) — zero usage across 86 sessions, observation data accessible via search_knowledge(mode="all")
# Re-add @mcp.tool() and @crash_proof to reactivate, then restart MCP server.
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
    _ensure_initialized()
    if _lance_degraded:
        return {"error": "LanceDB unavailable — running in degraded mode", "degraded": True}
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
    _ensure_initialized()
    if _lance_degraded:
        return {"error": "LanceDB unavailable — running in degraded mode", "degraded": True}
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
    _ensure_initialized()
    if _lance_degraded:
        return {"error": "LanceDB unavailable — running in degraded mode", "degraded": True}
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


@mcp.tool()
@crash_proof
def health_check() -> dict:
    """Return lightweight server health metrics.

    Returns server uptime, table row counts, last write timestamp,
    embedding model status, LanceDB connection status, Tags DB status,
    total memory count, and disk usage of ~/data/memory/lancedb/.

    No heavy queries — reads only cached globals and filesystem metadata.
    """
    now = time.time()
    uptime_s = int(now - _SERVER_START_TIME)
    uptime_str = f"{uptime_s // 3600}h {(uptime_s % 3600) // 60}m {uptime_s % 60}s"

    # Table counts — cheap .count() calls on cached LanceCollection wrappers
    table_counts = {}
    for name, col in [
        ("knowledge", collection),
        ("observations", observations),
        ("fix_outcomes", fix_outcomes),
        ("web_pages", web_pages),
        ("quarantine", quarantine),
    ]:
        try:
            table_counts[name] = col.count() if col is not None else -1
        except Exception:
            table_counts[name] = -1

    total_count = sum(v for v in table_counts.values() if v >= 0)

    # Last write timestamp from sideband file
    last_write = None
    try:
        if os.path.exists(MEMORY_TIMESTAMP_FILE):
            with open(MEMORY_TIMESTAMP_FILE) as f:
                data = json.load(f)
                ts = data.get("timestamp")
                if ts:
                    last_write = datetime.fromtimestamp(float(ts)).isoformat()
    except Exception:
        pass

    # Disk usage of lancedb directory
    disk_bytes = 0
    try:
        if os.path.isdir(LANCE_DIR):
            for dirpath, _dirs, files in os.walk(LANCE_DIR):
                for fname in files:
                    try:
                        disk_bytes += os.path.getsize(os.path.join(dirpath, fname))
                    except OSError:
                        pass
    except Exception:
        disk_bytes = -1

    return {
        "status": "ok" if not _lance_degraded else "degraded",
        "uptime": uptime_str,
        "uptime_seconds": uptime_s,
        "table_counts": table_counts,
        "total_memories": total_count,
        "last_write": last_write,
        "embedding_model": "loaded" if _embedding_fn is not None else "not_loaded",
        "lancedb": "connected" if (_lance_db is not None and not _lance_degraded) else ("degraded" if _lance_degraded else "not_connected"),
        "tags_db": "ok" if os.path.exists(TAGS_DB_PATH) else "missing",
        "disk_usage_mb": round(disk_bytes / (1024 * 1024), 2) if disk_bytes >= 0 else -1,
        "initialized": _initialized,
    }


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
            tag_ids = tag_index.tag_search([tag], match_all=False, top_k=200)
            tag_results = _tag_ids_to_summaries(tag_ids)
            for r in tag_results:
                if r.get("id") and r["id"] not in [c["id"] for c in candidates]:
                    candidates.append(r)
        except Exception:
            continue

    if not candidates:
        return {"clusters": [], "message": "No promotable memories found (need type:error, type:learning, or type:correction tags)."}

    # Get embeddings for clustering
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

    # Cluster similar memories using cosine distance
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
    """Group related memories into semantic clusters using vector distance queries.

    Uses a union-find algorithm over neighbor queries to discover
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
    # Process in batches to avoid overwhelming the database
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

    # Queue stats (merged from memory_stats)
    queue_lines = 0
    queue_bytes = 0
    try:
        if os.path.exists(CAPTURE_QUEUE_FILE):
            queue_bytes = os.path.getsize(CAPTURE_QUEUE_FILE)
            with open(CAPTURE_QUEUE_FILE, "r") as f:
                queue_lines = sum(1 for _ in f)
    except Exception:
        pass

    return {
        "total_memories": mem_count,
        "total_observations": obs_count,
        "total_fix_outcomes": fix_outcomes.count(),
        "tag_index_count": _tag_count,
        "capture_queue_lines": queue_lines,
        "capture_queue_bytes": queue_bytes,
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


def _batch_rename_memories():
    """Rename megaman→torus in all memory content and tags. One-time migration."""
    CONTENT_REPLACEMENTS = [
        ("Megaman Framework", "Torus Framework"),
        ("Megaman-Framework", "Torus-Framework"),
        ("megaman-framework", "torus-framework"),
        ("megaman framework", "torus framework"),
        ("Megaman framework", "Torus framework"),
        ("megaman-loop", "torus-loop"),
        ("megaman_loop", "torus_loop"),
        ("of Megaman", "of Torus"),
        ("for Megaman", "for Torus"),
        ("the Megaman", "the Torus"),
        ("our Megaman", "our Torus"),
        ("in Megaman", "in Torus"),
        ("Megaman memory", "Torus memory"),
        ("Megaman v2", "Torus v2"),
        ("megaman v2", "torus v2"),
        ("~/Desktop/megaman-framework", "~/Desktop/torus-framework"),
        ("/megaman-framework/", "/torus-framework/"),
    ]
    TAG_REPLACEMENTS = [("megaman-loop", "torus-loop"), ("megaman", "torus")]

    all_data = collection.get(include=["documents", "metadatas"])
    ids = all_data["ids"]
    docs = all_data["documents"] or []
    metas = all_data["metadatas"] or []

    content_updated = 0
    tag_updated = 0
    updated_ids = []

    for doc_id, doc, meta in zip(ids, docs, metas):
        if not doc:
            continue
        tags = (meta or {}).get("tags", "") or ""
        if "megaman" not in doc.lower() and "megaman" not in tags.lower():
            continue

        new_doc = doc
        for old, new in CONTENT_REPLACEMENTS:
            new_doc = new_doc.replace(old, new)

        new_tags = tags
        for old_tag, new_tag in TAG_REPLACEMENTS:
            new_tags = new_tags.replace(old_tag, new_tag)

        doc_changed = new_doc != doc
        tags_changed = new_tags != tags

        if doc_changed or tags_changed:
            update_kwargs = {"ids": [doc_id]}
            if doc_changed:
                update_kwargs["documents"] = [new_doc]
                content_updated += 1
            if tags_changed:
                new_meta = dict(meta) if meta else {}
                new_meta["tags"] = new_tags
                update_kwargs["metadatas"] = [new_meta]
                tag_updated += 1
            collection.update(**update_kwargs)
            updated_ids.append(doc_id[:8])

    # Rebuild FTS index to reflect changes
    if content_updated > 0 or tag_updated > 0:
        try:
            rebuild_tag_index()
        except Exception:
            pass

    return {
        "content_updated": content_updated,
        "tag_updated": tag_updated,
        "updated_ids": updated_ids,
        "message": f"Renamed megaman→torus: {content_updated} content, {tag_updated} tags",
    }


def _gate_effectiveness_report() -> dict:
    """Analyze gate effectiveness from the most recent session state.

    Reads gate_effectiveness from state files and computes per-gate scores.
    Returns suggestions for gates that may need tuning.
    """
    import glob as _glob
    state_dir = os.path.join(os.path.expanduser("~"), ".claude", "hooks")
    # Also check ramdisk
    ramdisk_dir = f"/run/user/{os.getuid()}/claude-hooks"
    search_dirs = [ramdisk_dir, state_dir] if os.path.isdir(ramdisk_dir) else [state_dir]

    effectiveness = {}
    for sdir in search_dirs:
        pattern = os.path.join(sdir, "state_*.json")
        for fpath in _glob.glob(pattern):
            try:
                with open(fpath) as f:
                    data = json.load(f)
                ge = data.get("gate_effectiveness", {})
                for gate, stats in ge.items():
                    if gate not in effectiveness:
                        effectiveness[gate] = {"blocks": 0, "overrides": 0, "prevented": 0}
                    for k in ("blocks", "overrides", "prevented"):
                        effectiveness[gate][k] += stats.get(k, 0)
            except Exception:
                continue

    if not effectiveness:
        return {"message": "No gate effectiveness data found", "gates": {}}

    results = {}
    suggestions = []
    for gate, stats in sorted(effectiveness.items()):
        blocks = stats["blocks"]
        overrides = stats["overrides"]
        prevented = stats["prevented"]
        total_resolved = prevented + overrides
        eff_pct = round(100 * prevented / total_resolved) if total_resolved > 0 else None
        results[gate] = {
            "blocks": blocks,
            "overrides": overrides,
            "prevented": prevented,
            "effectiveness_pct": eff_pct,
        }
        if total_resolved >= 3 and eff_pct is not None and eff_pct < 50:
            suggestions.append(f"{gate} at {eff_pct}% — consider loosening thresholds")

    return {
        "gates": results,
        "suggestions": suggestions,
        "message": f"Analyzed {len(results)} gates" + (f", {len(suggestions)} need attention" if suggestions else ""),
    }


# DORMANT — saves ~180 tokens/prompt. Uncomment @mcp.tool() to reactivate.
# @mcp.tool()
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
    if _lance_degraded:
        return {"error": "LanceDB unavailable — running in degraded mode", "degraded": True}
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
    elif action == "batch_rename":
        return _batch_rename_memories()
    elif action == "gate_effectiveness":
        return _gate_effectiveness_report()
    else:
        return {
            "error": f"Unknown action: {action!r}",
            "valid_actions": {
                "promotions": "Find recurring patterns to promote to rules (top_k)",
                "stale": "Find old unretrieved memories (days, top_k)",
                "cluster": "Group related memories into clusters (min_cluster_size, distance_threshold)",
                "health": "Generate memory health metrics (no params)",
                "rebuild_tags": "Rebuild tag co-occurrence matrix (no params)",
                "batch_rename": "Rename megaman→torus in all memory content and tags",
                "gate_effectiveness": "Analyze gate block effectiveness from session state",
            },
        }


# ──────────────────────────────────────────────────
# Teammate Transcript Helpers (DORMANT — add @mcp.tool() to activate)
# ──────────────────────────────────────────────────


def _parse_transcript_actions(transcript_path: str, max_actions: int = 5) -> list:
    """Parse a JSONL transcript file and extract recent assistant actions.

    Reads from the end of the file to get the most recent actions first.
    Extracts tool uses (name + truncated input) and text blocks from
    assistant messages. Skips user and progress messages.

    Returns list of {"action": str, "outcome": str} dicts, most recent first.
    """
    if not transcript_path:
        return []
    try:
        with open(transcript_path, "r") as f:
            lines = f.readlines()
    except (FileNotFoundError, OSError, PermissionError):
        return []

    if not lines:
        return []

    actions = []
    # Process lines in reverse to get most recent first
    for line in reversed(lines):
        if len(actions) >= max_actions:
            break
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue

        msg_type = entry.get("type", "")
        if msg_type != "assistant":
            continue

        # Extract from content blocks
        content = entry.get("message", {}).get("content", [])
        if isinstance(content, str):
            # Plain text assistant message
            preview = content[:100].replace("\n", " ")
            if preview:
                actions.append({"action": f"Text: {preview}", "outcome": ""})
            continue

        if not isinstance(content, list):
            continue

        for block in content:
            if len(actions) >= max_actions:
                break
            block_type = block.get("type", "")

            if block_type == "tool_use":
                tool_name = block.get("name", "unknown")
                tool_input = block.get("input", {})
                # Extract the most informative field from input
                hint = ""
                if isinstance(tool_input, dict):
                    for key in ("file_path", "command", "pattern", "query", "path", "content", "prompt"):
                        val = tool_input.get(key, "")
                        if val:
                            hint = str(val)[:80].replace("\n", " ")
                            break
                    if not hint:
                        # Fallback: first string value
                        for v in tool_input.values():
                            if isinstance(v, str) and v:
                                hint = v[:80].replace("\n", " ")
                                break
                action_str = f"{tool_name}: {hint}" if hint else tool_name
                actions.append({"action": action_str, "outcome": ""})

            elif block_type == "text":
                text = block.get("text", "")
                preview = text[:100].replace("\n", " ")
                if preview:
                    actions.append({"action": f"Text: {preview}", "outcome": ""})

    return actions[:max_actions]


def _format_teammate_summary(agent_type: str, actions: list, is_active: bool) -> str:
    """Format a teammate's actions into a structured summary.

    Output is hard-capped at 1200 chars (~300 tokens) to keep summaries compact.

    Args:
        agent_type: The type/role of the teammate (e.g., "builder", "researcher").
        actions: List of {"action": str, "outcome": str} dicts from _parse_transcript_actions.
        is_active: Whether the agent is currently running.
    """
    status = "active" if is_active else "finished"
    header = f"Teammate: {agent_type} ({status}, {len(actions)} turns)"

    if not actions:
        return header + "\n  (no actions recorded)"

    lines = [header, "Recent actions:"]
    for i, act in enumerate(actions, 1):
        action_text = act.get("action", "unknown")
        # Truncate individual action lines to ~120 chars
        if len(action_text) > 120:
            action_text = action_text[:117] + "..."
        lines.append(f"  {i}. {action_text}")

    result = "\n".join(lines)
    # Hard cap at 1200 chars
    if len(result) > 1200:
        result = result[:1197] + "..."
    return result


def get_teammate_context(agent_name: str = "", max_actions: int = 5) -> dict:
    """Get compressed summaries of teammate transcripts for cross-agent visibility.

    DORMANT: This function is not registered as an MCP tool. To activate,
    add @mcp.tool() and @crash_proof decorators above this function and
    restart the MCP server.

    Args:
        agent_name: Optional filter — match by agent_type or agent_id substring.
                    If empty, summarizes all active teammates.
        max_actions: Maximum number of recent actions to extract per teammate.

    Returns:
        dict with {"teammates": [str, ...], "count": int}
    """
    import glob as _glob

    # Reuse the same pattern as subagent_context.py:find_current_session_state()
    state_dir = os.path.join(os.path.expanduser("~"), ".claude", "hooks")
    try:
        pattern = os.path.join(state_dir, "state_*.json")
        files = _glob.glob(pattern)
        if not files:
            return {"teammates": [], "count": 0}
        files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
        with open(files[0]) as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError, IndexError):
        return {"teammates": [], "count": 0}

    active_subagents = state.get("active_subagents", [])
    if not active_subagents:
        return {"teammates": [], "count": 0}

    # Filter if agent_name provided
    if agent_name:
        matched = [
            sa for sa in active_subagents
            if agent_name.lower() in sa.get("agent_type", "").lower()
            or agent_name.lower() in sa.get("agent_id", "").lower()
        ]
    else:
        matched = active_subagents

    summaries = []
    for sa in matched:
        transcript_path = sa.get("transcript_path", "")
        agent_type = sa.get("agent_type", "unknown")
        actions = _parse_transcript_actions(transcript_path, max_actions=max_actions)
        # Determine if still active (has a start_ts, no end marker)
        is_active = bool(sa.get("start_ts", 0))
        summary = _format_teammate_summary(agent_type, actions, is_active)
        summaries.append(summary)

    return {"teammates": summaries, "count": len(summaries)}


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


def _backup_database():
    """Create a consistent backup of the LanceDB directory.

    LanceDB stores data as immutable Lance files, so a directory copy is safe.
    Returns dict with backup_path and size_bytes.
    """
    import shutil

    if not os.path.isdir(LANCE_DIR):
        raise RuntimeError(f"LanceDB directory not found: {LANCE_DIR}")

    bak_path = os.path.join(MEMORY_DIR, "lancedb.backup")
    tmp_path = bak_path + ".tmp"

    # Remove stale tmp if exists
    if os.path.exists(tmp_path):
        shutil.rmtree(tmp_path)

    try:
        shutil.copytree(LANCE_DIR, tmp_path)
        # Atomic swap: remove old backup, rename tmp
        if os.path.exists(bak_path):
            shutil.rmtree(bak_path)
        os.rename(tmp_path, bak_path)
    except Exception:
        if os.path.exists(tmp_path):
            shutil.rmtree(tmp_path, ignore_errors=True)
        raise

    # Calculate total size
    total_size = 0
    for dirpath, _dirnames, filenames in os.walk(bak_path):
        for f in filenames:
            total_size += os.path.getsize(os.path.join(dirpath, f))

    return {"backup_path": bak_path, "size_bytes": total_size}


def _dispatch_request(req):
    """Route a UDS request to the appropriate LanceDB operation."""
    method = req.get("method", "")
    col_name = req.get("collection", "")
    params = req.get("params", {})

    try:
        if method == "ping":
            return {"ok": True, "result": "pong"}

        if method == "flush_queue":
            flushed = _flush_capture_queue()
            return {"ok": True, "result": flushed}

        if method == "backup":
            result = _backup_database()
            return {"ok": True, "result": result}

        if method == "auto_remember":
            content = params.get("content", "")
            context = params.get("context", "")
            tags = params.get("tags", "")
            if not content or len(content.strip()) < MIN_CONTENT_LENGTH:
                return {"ok": True, "result": {"saved": False, "reason": "content too short"}}
            # Dedup check
            dedup = _check_dedup(content, tags)
            if dedup and dedup.get("blocked"):
                return {"ok": True, "result": {"saved": False, "reason": "deduplicated",
                        "existing_id": dedup["existing_id"], "distance": dedup["distance"]}}
            # Cap metadata
            if len(context) > 500:
                context = context[:497] + "..."
            if len(tags) > 500:
                tags = tags[:497] + "..."
            # Append soft-dupe tag if borderline
            if dedup and dedup.get("soft_dupe_tag"):
                tags = f"{tags},{dedup['soft_dupe_tag']}" if tags else dedup["soft_dupe_tag"]
            doc_id = generate_id(content)
            timestamp = datetime.now().isoformat()
            preview = content[:SUMMARY_LENGTH].replace("\n", " ")
            if len(content) > SUMMARY_LENGTH:
                preview += "..."
            now = time.time()
            collection.upsert(
                documents=[content],
                metadatas=[{
                    "context": context, "tags": tags, "timestamp": timestamp,
                    "session_time": now, "preview": preview,
                    "primary_source": "", "related_urls": "", "source_method": "auto_remember",
                }],
                ids=[doc_id],
            )
            tag_index.add_tags(doc_id, tags)
            return {"ok": True, "result": {"saved": True, "id": doc_id}}

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
            # Convert result to JSON-serializable dict
            return {"ok": True, "result": _serialize_result(result)}

        if method == "get":
            kwargs = {}
            if "ids" in params:
                kwargs["ids"] = params["ids"]
            if "limit" in params:
                kwargs["limit"] = params["limit"]
            kwargs["include"] = params.get("include", ["metadatas", "documents"])
            result = col.get(**kwargs)
            return {"ok": True, "result": _serialize_result(result)}

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


def _serialize_result(result):
    """Convert query/get result to a plain dict for JSON serialization."""
    if result is None:
        return {}
    out = {}
    for key in ("ids", "documents", "metadatas", "distances", "embeddings"):
        if key in result and result[key] is not None:
            out[key] = result[key]
    return out


def _bind_uds_socket():
    """Create, bind, and return a new UDS server socket."""
    if os.path.exists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCKET_PATH)
    srv.listen(8)
    srv.settimeout(1.0)
    return srv


def _start_socket_server():
    """Bind a Unix Domain Socket and accept connections in a daemon thread."""
    global _socket_server

    try:
        srv = _bind_uds_socket()
        _socket_server = srv
    except OSError as e:
        # Non-fatal: MCP tools still work, just no external gateway
        print(f"[UDS] Failed to start socket server: {e}", file=_sys.stderr)
        return

    def _accept_loop():
        nonlocal srv
        while True:
            try:
                conn, _ = srv.accept()
                t = threading.Thread(target=_handle_socket_client, args=(conn,), daemon=True)
                t.start()
            except socket.timeout:
                # Proactive watchdog: detect deleted socket file
                if not os.path.exists(SOCKET_PATH):
                    print("[UDS] Socket file missing, rebinding", file=_sys.stderr)
                    try:
                        srv.close()
                    except Exception:
                        pass
                    try:
                        srv = _bind_uds_socket()
                        _socket_server = srv
                    except OSError as e:
                        print(f"[UDS] Watchdog rebind failed: {e}", file=_sys.stderr)
                continue
            except OSError as e:
                if _uds_shutting_down:
                    break
                # Reactive rebind on accept() failure
                print(f"[UDS] Accept error, rebinding: {e}", file=_sys.stderr)
                try:
                    srv.close()
                except Exception:
                    pass
                time.sleep(1)
                try:
                    srv = _bind_uds_socket()
                    _socket_server = srv
                except OSError as rebind_err:
                    print(f"[UDS] Rebind failed, retrying in 5s: {rebind_err}", file=_sys.stderr)
                    time.sleep(5)

    t = threading.Thread(target=_accept_loop, daemon=True, name="uds-gateway")
    t.start()


def _cleanup_socket():
    """Close server socket and remove socket file on exit."""
    global _socket_server, _uds_shutting_down
    _uds_shutting_down = True
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
    # Defer _ensure_initialized() to first tool call — mcp.run() must start
    # immediately so Claude Code's MCP handshake doesn't timeout (~25s model load).
    _start_socket_server()
    try:
        mcp.run()
    except Exception as e:
        print(f"[MCP] Fatal: {e}", file=_sys.stderr)
        _sys.exit(1)
