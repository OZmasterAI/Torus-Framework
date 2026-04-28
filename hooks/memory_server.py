#!/usr/bin/env python3
"""Self-Healing Claude Framework — Memory MCP Server

A SurrealDB-embedded persistent memory system exposed as MCP tools.
Claude Code connects to this server and gets search_knowledge, remember_this,
get_memory, and maintenance as native tools.

The memory persists across sessions in ~/data/memory/surrealdb/, enabling cross-session
knowledge retention.

Run standalone: python3 memory_server.py
Used via MCP: configured in .claude/mcp.json

Migrated from ChromaDB → LanceDB (Session 232) → SurrealDB embedded (Session 719).
SurrealDB provides HNSW vector search, BM25 FTS, RELATE graph edges, and embedded mode.
"""

import asyncio
import atexit
import concurrent.futures
import functools
import hashlib
import json
import math
import os
import socket
import subprocess
import threading
import time
from datetime import datetime, timedelta

# Reduce thread pool sizes before libraries are imported.
# Defaults = CPU count per pool (8 each) = 52 threads + ~320MB in memory arenas.
# We process one query at a time, so 2 threads per pool is plenty.
os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")
os.environ.setdefault("MALLOC_ARENA_MAX", "2")

import ctypes as _ctypes
from surrealdb import Surreal, RecordID
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


# Network transport config — streamable-http is default, use --stdio or --sse to override
_NET_HOST = os.environ.get("MEMORY_SSE_HOST", "127.0.0.1")
_NET_PORT = int(os.environ.get("MEMORY_SSE_PORT", "8742"))
_PID_FILE = os.path.join(os.path.dirname(__file__), ".memory_server.pid")

# Detect transport mode from CLI args
import argparse as _argparse

_parser = _argparse.ArgumentParser(add_help=False)
_parser.add_argument(
    "--sse",
    action="store_true",
    default=False,
    help="Use SSE transport (deprecated in Claude Code 2.1.83+)",
)
_parser.add_argument(
    "--http",
    action="store_true",
    default=True,
    help="Use streamable-http transport (default, recommended)",
)
_parser.add_argument(
    "--stdio",
    action="store_true",
    default=False,
    help="Use stdio transport (for subprocess/pipe mode)",
)
_parser.add_argument("--port", type=int, default=_NET_PORT)
_parser.add_argument("--bootstrap-clusters", action="store_true", default=False)
_args, _ = _parser.parse_known_args()

# --stdio explicitly overrides --http default
if _args.stdio:
    _args.http = False

# Initialize MCP server (with host/port for network modes)
_network_mode = _args.sse or _args.http
if _network_mode:
    mcp = FastMCP("memory", host=_NET_HOST, port=_args.port, json_response=True)
else:
    mcp = FastMCP("memory")

# --- OAuth discovery stubs (Claude Code 2.1.85+ does RFC 9728 / RFC 8414 probing) ---
# The MCP spec says auth is OPTIONAL. When discovery returns 404, the client
# should fall back to default endpoints. We return 404 with proper JSON on all
# OAuth-related paths so Claude Code doesn't choke on plain-text "Not Found".
from starlette.requests import Request
from starlette.responses import Response, JSONResponse


@mcp.custom_route("/.well-known/oauth-authorization-server", methods=["GET"])
async def _oauth_as_metadata(request: Request) -> Response:
    """RFC 8414 — no authorization server configured."""
    return Response(status_code=404)


@mcp.custom_route("/.well-known/oauth-protected-resource", methods=["GET"])
async def _oauth_protected_resource(request: Request) -> Response:
    """RFC 9728 — resource is not protected."""
    return Response(status_code=404)


@mcp.custom_route("/.well-known/openid-configuration", methods=["GET"])
async def _openid_config(request: Request) -> Response:
    """OpenID Connect — not supported."""
    return Response(status_code=404)


@mcp.custom_route("/register", methods=["POST"])
async def _oauth_register(request: Request) -> Response:
    """RFC 7591 Dynamic Client Registration — not supported."""
    return Response(status_code=404)


@mcp.custom_route("/authorize", methods=["GET"])
async def _oauth_authorize(request: Request) -> Response:
    """OAuth authorize endpoint — not supported."""
    return Response(status_code=404)


@mcp.custom_route("/token", methods=["POST"])
async def _oauth_token(request: Request) -> Response:
    """OAuth token endpoint — not supported."""
    return Response(status_code=404)


# --- SSE reconnect fix ---
# When Claude Code's SSE connection drops and reconnects, it skips sending the
# MCP InitializeRequest and jumps straight to tool calls.  The default
# ServerSession._received_request raises RuntimeError for uninitialized sessions.
# This patch auto-initializes instead, so reconnects work transparently.
from mcp.server.session import ServerSession, InitializationState
import mcp.types as _mcp_types

_original_received_request = ServerSession._received_request


async def _patched_received_request(self, responder):
    """Allow tool requests on uninitialized SSE sessions by auto-initializing."""
    if self._initialization_state != InitializationState.Initialized and not isinstance(
        responder.request.root,
        (_mcp_types.InitializeRequest, _mcp_types.PingRequest),
    ):
        _sys.stderr.write(
            "[MCP] Auto-initializing session on reconnect "
            f"(got {type(responder.request.root).__name__} before InitializeRequest)\n"
        )
        self._initialization_state = InitializationState.Initialized
    return await _original_received_request(self, responder)


ServerSession._received_request = _patched_received_request
# --- end SSE reconnect fix ---


_libc = _ctypes.CDLL("libc.so.6", use_errno=True)
_malloc_trim = _libc.malloc_trim
_malloc_trim.argtypes = [_ctypes.c_int]
_malloc_trim.restype = _ctypes.c_int
_tool_call_counter = 0
_MALLOC_TRIM_INTERVAL = 50


def crash_proof(fn):
    """Wrap MCP tool: offloads sync body to thread pool, catches exceptions.

    Keeps uvicorn event loop free while embedding inference runs.
    """

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                _tool_executor, functools.partial(fn, *args, **kwargs)
            )
            global _tool_call_counter
            _tool_call_counter += 1
            if _tool_call_counter % _MALLOC_TRIM_INTERVAL == 0:
                _malloc_trim(0)
            return result
        except Exception as e:
            import traceback

            tb = traceback.format_exc()
            _sys.stderr.write(f"[MCP] {fn.__name__} error: {e}\n{tb}\n")
            return {"error": f"{fn.__name__} failed: {type(e).__name__}: {e}"}

    return wrapper


# Auto project-tagging: detect if MCP server was launched from a project directory
_SERVER_PROJECT = None
_SERVER_PROJECT_DIR = None
_SERVER_SUBPROJECT = None
_SERVER_SUBPROJECT_DIR = None
try:
    _sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "hooks"))
    from boot_pkg.util import detect_project

    _SERVER_PROJECT, _SERVER_PROJECT_DIR, _SERVER_SUBPROJECT, _SERVER_SUBPROJECT_DIR = (
        detect_project()
    )
except Exception:
    pass

# Persistent LanceDB storage
MEMORY_DIR = os.path.join(os.path.expanduser("~"), "data", "memory")
SURREAL_DIR = os.path.join(MEMORY_DIR, "surrealdb")
os.makedirs(SURREAL_DIR, exist_ok=True)

# Embedding model: nvidia/nv-embed-v1 via NIM API (4096-dim, 7B params, MTEB 69.3)
# API-based — no local model, near-zero RAM, ~1s per embed
_EMBEDDING_MODEL = "nvidia/nv-embed-v1"
_EMBEDDING_DIM = 4096
_embedding_fn = True  # Always "loaded" — API-based, no local model
_NIM_URL = "https://integrate.api.nvidia.com/v1/embeddings"
_NIM_KEY_FALLBACK = None

# Unix Domain Socket gateway for external consumers (hooks, dashboard)
SOCKET_PATH = os.path.join(os.path.expanduser("~"), ".claude", "hooks", ".memory.sock")
_socket_server = None  # threading server reference for cleanup
_uds_shutting_down = False  # prevents rebind during intentional shutdown
_socket_owner_pid = None  # PID that successfully bound the socket

# Lazy SurrealDB initialization
_surreal_db = None  # Surreal embedded connection
collection = None  # SurrealCollection wrapper for knowledge table
fix_outcomes = None  # SurrealCollection wrapper for fix_outcomes table
observations = None  # SurrealCollection wrapper for observations table
web_pages = None  # SurrealCollection wrapper for web_pages table
quarantine = None  # SurrealCollection wrapper for quarantine table
_clusters_coll = None  # SurrealCollection wrapper for clusters table
_surreal_degraded = False


from shared.surreal_collection import SurrealCollection, init_surreal_db


def _embed_texts(texts):
    """Embed a list of texts via NVIDIA NIM API (nv-embed-v1, 4096-dim).

    Returns list of lists of floats (4096-dim vectors).
    Falls back to zero vectors if API is unavailable.
    """
    import requests

    # Replace empty texts — NIM rejects them
    safe_texts = [t if t and t.strip() else "[empty]" for t in texts]
    try:
        resp = requests.post(
            _NIM_URL,
            headers={
                "Authorization": "Bearer "
                + _read_config_toggles().get("nim_api_key", ""),
                "Content-Type": "application/json",
            },
            json={
                "model": _EMBEDDING_MODEL,
                "input": safe_texts,
                "input_type": "passage",
                "encoding_format": "float",
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return [d["embedding"] for d in data["data"]]
    except Exception as e:
        print(f"[MCP] NIM embed error: {e}", file=_sys.stderr)
        return [[0.0] * _EMBEDDING_DIM for _ in texts]


def _embed_text(text):
    """Embed a single text string. Returns list of floats (768-dim)."""
    return _embed_texts([text])[0]


# Thread pool for offloading CPU-heavy MCP tool calls off the uvicorn event loop.
# Single worker serializes access to the non-thread-safe SentenceTransformer model.
_tool_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="mcp-tool"
)


def _init_surrealdb():
    """Lazy initialization of SurrealDB embedded connection and table wrappers."""
    global \
        _surreal_db, \
        collection, \
        fix_outcomes, \
        observations, \
        web_pages, \
        quarantine, \
        _clusters_coll, \
        _surreal_degraded
    if _surreal_db is not None:
        return
    try:
        print(
            f"[MCP] Embedding via NIM API: {_EMBEDDING_MODEL} ({_EMBEDDING_DIM}-dim)",
            file=_sys.stderr,
        )

        _surreal_db = Surreal(f"surrealkv://{SURREAL_DIR}")
        _surreal_db.use("memory", "main")

        colls = init_surreal_db(
            _surreal_db,
            embed_text=_embed_text,
            embed_texts=_embed_texts,
            embedding_dim=_EMBEDDING_DIM,
        )

        collection = colls["knowledge"]
        fix_outcomes = colls["fix_outcomes"]
        observations = colls["observations"]
        web_pages = colls["web_pages"]
        quarantine = colls["quarantine"]
        _clusters_coll = colls["clusters"]

        print(f"[MCP] SurrealDB initialized at {SURREAL_DIR}", file=_sys.stderr)
    except Exception as e:
        import traceback

        print(
            f"[MCP] SurrealDB init failed: {e}\n{traceback.format_exc()}",
            file=_sys.stderr,
        )
        _surreal_degraded = True


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
    r"^npm install\b",
    r"^pip install\b",
    r"^Successfully installed\b",
    r"^already satisfied\b",
    r"^up to date\b",
    r"^added .* packages?\b",
    r"^removing .* packages?\b",
    r"^npm WARN\b",
    r"^DEPRECATION\b",
    r"^Collecting \b",
    r"^Downloading \b",
    r"^Installing collected\b",
    r"^running setup\.py\b",
    r"^Building wheel\b",
    r"^Using cached\b",
    # Non-package noise (anchored full-line or start-of-content)
    r"^(?:OK|Done|Got it|Sure|Understood)[.!]?\s*$",  # empty acks
    r"^Session \d+ started\s*$",  # session boilerplate
    r"^(?:Reading|Writing|Editing) (?:file )?/\S",  # tool echo: requires absolute path
    r"^Traceback \(most recent call last\):\s*$",  # raw traceback header only
    r"^(?:Let me|I'll|I will) (?:check|look|read|search)\b.{0,30}$",  # filler: only short content
]
import re as _re

NOISE_REGEXES = [_re.compile(p, _re.IGNORECASE) for p in NOISE_PATTERNS]

# Near-dedup: cosine distance thresholds (tuned for nv-embed-v1 4096-dim)
DEDUP_THRESHOLD = 0.12  # distance < 0.12 = hard skip (was 0.10 for 384-dim)
DEDUP_SOFT_THRESHOLD = 0.20  # 0.12-0.20 = save but tag as possible-dupe (was 0.15)
FIX_DEDUP_THRESHOLD = 0.05  # Stricter threshold for type:fix memories (was 0.03)
_FIX_DEDUP_EXEMPT = False  # DORMANT — flip True to skip dedup for all type:fix

# Citation URL extraction
MAX_CITATION_URLS = 4  # 1 primary + 3 related
MAX_URL_LENGTH = 500
DOMAIN_AUTHORITY = {
    "high": {
        "github.com",
        "docs.openzeppelin.com",
        "eips.ethereum.org",
        "developer.mozilla.org",
        "docs.soliditylang.org",
        "react.dev",
        "developer.x.com",
        "docs.python.org",
        "stackoverflow.com",
    },
    "medium": {"medium.com", "dev.to", "hackmd.io", "mirror.xyz"},
    "low": {"localhost", "127.0.0.1", "example.com", "0.0.0.0"},
}

# Observation promotion settings
MAX_PROMOTIONS_PER_CYCLE = 50
PROMOTION_TAGS = "type:auto-promoted,area:framework"


def generate_id(content: str) -> str:
    """Generate a deterministic ID from content alone.

    Using only content (no timestamp) means saving the same knowledge twice
    produces the same ID, which is treated as an upsert — preventing
    duplicate entries and unbounded database growth.
    """
    return hashlib.sha256(content.encode()).hexdigest()[:16]


from shared.memory_classification import (
    classify_tier as _classify_tier,
    classify_memory_type as _classify_memory_type,
    classify_state_type as _classify_state_type,
    salience_score as _salience_score,
    normalize_tags as _normalize_tags,
    inject_project_tag as _mc_inject_project_tag,
    build_project_prefix as _mc_build_project_prefix,
)


def _inject_project_tag(tags):
    return _mc_inject_project_tag(tags, _SERVER_PROJECT, _SERVER_SUBPROJECT)


def _build_project_prefix():
    return _mc_build_project_prefix(
        _SERVER_PROJECT, _SERVER_SUBPROJECT, _SERVER_PROJECT_DIR, _SERVER_SUBPROJECT_DIR
    )


# ──────────────────────────────────────────────────
# Citation URL Extraction
# ──────────────────────────────────────────────────
from urllib.parse import urlparse as _urlparse

# Regex for [source: URL] and [ref: URL] markers
_SOURCE_MARKER_RE = _re.compile(r"\[source:\s*(https?://[^\]\s]+)\s*\]", _re.IGNORECASE)
_REF_MARKER_RE = _re.compile(r"\[ref:\s*(https?://[^\]\s]+)\s*\]", _re.IGNORECASE)
# General URL regex for auto-extraction
_URL_RE = _re.compile(r'https?://[^\s<>\'")\]]+')


def _validate_url(url_str: str) -> str:
    """Validate and clean a URL string. Returns cleaned URL or empty string."""
    try:
        url_str = url_str.strip()
        # Strip trailing punctuation that often clings to URLs in text
        while url_str and url_str[-1] in ".,;:!?)":
            url_str = url_str[:-1]
        if len(url_str) > MAX_URL_LENGTH:
            return ""
        parsed = _urlparse(url_str)
        if (
            parsed.scheme in ("http", "https")
            and parsed.netloc
            and "." in parsed.netloc
        ):
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
        related = deduped[: MAX_CITATION_URLS - 1]

        return {
            "primary_source": primary,
            "related_urls": ",".join(related),
            "source_method": method,
            "clean_content": clean,
        }
    except Exception:
        return defaults


from shared.search_helpers import detect_query_mode


def _detect_query_mode(query, routing="default"):
    return detect_query_mode(query, routing)


from shared.search_helpers import merge_results


def _merge_results(fts_results, lance_summaries, top_k=15):
    return merge_results(fts_results, lance_summaries, top_k)


# Lazy initialization — only run when module is used as a server, not when imported
# for testing. LanceDB uses optimistic concurrency control (no more segfaults).
_preview_migrated = False
_tag_count = 0
_initialized = False
_initializing = False  # True during _ensure_initialized() — watchdog skips strikes
_init_lock = threading.Lock()  # Serializes warmup thread vs tool call initialization
_init_done = threading.Event()  # Signaled when initialization completes
_knowledge_graph = None  # KnowledgeGraph instance (initialized lazily)
_ltp_tracker = None  # LTPTracker instance (initialized lazily)
_adaptive_weights = None  # AdaptiveWeights instance (initialized lazily)
_last_search_ids = []  # IDs from last search_knowledge call (for implicit feedback)
_search_pipeline = None  # SearchPipeline instance (initialized lazily)
_write_pipeline = None  # WritePipeline instance (initialized lazily)

# --- Counterfactual retrieval client (lazy init) ---
_cf_client = None
_cf_client_init = False


def _get_cf_client():
    """Lazy-init Anthropic client for counterfactual retrieval. Returns None on failure."""
    global _cf_client, _cf_client_init
    if _cf_client_init:
        return _cf_client
    _cf_client_init = True
    try:
        import anthropic

        _cf_client = anthropic.Anthropic(timeout=5.0)
        return _cf_client
    except Exception:
        return None


_CF_SYSTEM_PROMPT = (
    "You generate alternative search queries for a memory retrieval system. "
    "Given the original query and initial results, produce ONE short search query "
    "(under 15 words) that would find related but DIFFERENT memories — "
    "focus on causes, consequences, or prerequisites the initial results miss. "
    "Reply with ONLY the query, nothing else."
)

_CF_MODEL_MAP = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6-20250514",
    "opus": "claude-opus-4-6-20250514",
}


def _generate_counterfactual_query(original_query, initial_results, model_key="haiku"):
    """Ask LLM for an alternative query based on initial results. Returns str or None."""
    client = _get_cf_client()
    if not client:
        return None
    try:
        # Build compact context from top-5 results
        context_lines = []
        for r in initial_results[:5]:
            preview = r.get("preview", "")[:120]
            rel = r.get("relevance", 0)
            context_lines.append(f"[{rel:.2f}] {preview}")
        context_block = "\n".join(context_lines)

        user_msg = (
            f"Original query: {original_query}\n\nInitial results:\n{context_block}"
        )

        model_id = _CF_MODEL_MAP.get(model_key, _CF_MODEL_MAP["haiku"])
        response = client.messages.create(
            model=model_id,
            max_tokens=80,
            temperature=0.7,
            system=_CF_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        cf_query = response.content[0].text.strip()
        # Sanity: reject empty or absurdly long responses
        if not cf_query or len(cf_query) > 200:
            return None
        return cf_query
    except Exception:
        return None  # Fail-open: any error → skip counterfactual


_SERVER_START_TIME = time.time()  # Module load time — used for uptime reporting


def _keyword_search(query, top_k=15):
    if collection is None:
        return []
    results = collection.keyword_search(query, top_k=top_k)
    for r in results:
        text = r.get("text", "")
        r["summary"] = (
            text[:SUMMARY_LENGTH] + "..." if len(text) > SUMMARY_LENGTH else text
        )
    return results


from shared.search_helpers import (
    fuzzy_keyword_search as _sh_fuzzy,
    generate_fuzzy_variants as _generate_fuzzy_variants,
)


def _fuzzy_keyword_search(query: str, table_name: str = "knowledge", top_k: int = 10):
    return _sh_fuzzy(
        query,
        table_name,
        top_k,
        collections={
            "knowledge": collection,
            "observations": observations,
            "fix_outcomes": fix_outcomes,
            "web_pages": web_pages,
        },
        fts_ready=True,
    )


from shared.search_helpers import tag_ids_to_summaries as _sh_tag_ids_to_summaries


def _tag_ids_to_summaries(memory_ids, collection_ref=None):
    return _sh_tag_ids_to_summaries(memory_ids, collection_ref or collection)


from shared.error_normalizer import fnv1a_hash as _fnv1a_hash


def _cluster_label(content: str) -> str:
    """Extract top-3 meaningful words from content for a cluster label."""
    import re as _re_cl
    from collections import Counter as _Counter_cl

    _stop = {
        "this",
        "that",
        "with",
        "from",
        "have",
        "been",
        "were",
        "will",
        "would",
        "could",
        "should",
        "their",
        "there",
        "they",
        "which",
        "when",
        "what",
        "where",
        "than",
        "then",
        "also",
        "about",
        "into",
        "more",
        "some",
        "such",
        "only",
        "other",
        "each",
        "just",
        "like",
        "over",
        "very",
        "after",
        "before",
        "between",
        "under",
        "again",
        "does",
        "done",
        "make",
        "made",
        "most",
        "much",
        "must",
        "need",
    }
    words = _re_cl.findall(r"[a-zA-Z_]{4,}", content.lower())
    counts = _Counter_cl(w for w in words if w not in _stop)
    top = [w for w, _ in counts.most_common(3)]
    return " / ".join(top) if top else "misc"


CLUSTER_THRESHOLD = 0.7


def _surreal_cluster_assign(vec_list, content=""):
    if _clusters_coll is None or not vec_list:
        return ""
    try:
        import numpy as np

        vec = np.array(vec_list, dtype=np.float32)
        norm = np.linalg.norm(vec)
        if norm < 1e-10:
            return ""
        vec_norm = (vec / norm).tolist()

        rows = _clusters_coll._db.query(
            "SELECT *, vector::distance::knn() AS dist FROM clusters "
            "WHERE centroid <|1, COSINE|> $vec ORDER BY dist ASC",
            {"vec": vec_norm},
        )
        now = datetime.now().isoformat()

        if rows and (1 - rows[0].get("dist", 1.0)) >= CLUSTER_THRESHOLD:
            cid = _clusters_coll._extract_id(rows[0])
            old_count = rows[0].get("member_count", 1)
            old_centroid = np.array(rows[0].get("centroid", vec_norm), dtype=np.float32)
            new_count = old_count + 1
            new_centroid = (
                old_centroid * old_count + np.array(vec_norm, dtype=np.float32)
            ) / new_count
            c_norm = np.linalg.norm(new_centroid)
            if c_norm > 1e-10:
                new_centroid = new_centroid / c_norm
            _clusters_coll._db.query(
                "UPDATE clusters:$id SET centroid=$c, member_count=$n, updated_at=$t",
                {"id": cid, "c": new_centroid.tolist(), "n": new_count, "t": now},
            )
            return cid
        else:
            new_id = f"cl_{_fnv1a_hash(content)}"
            label = _cluster_label(content)
            _clusters_coll.upsert(
                ids=[new_id],
                vectors=[vec_norm],
                documents=[""],
                metadatas=[
                    {
                        "member_count": 1,
                        "label": label,
                        "created_at": now,
                        "updated_at": now,
                    }
                ],
            )
            return new_id
    except Exception:
        return ""


def _ensure_initialized():
    """Run one-time initialization (SurrealDB + Knowledge Graph + LTP).

    Called lazily on first MCP tool use or explicitly at server startup.
    Safe to call multiple times — idempotent after first run.
    """
    global _preview_migrated, _tag_count, _initialized
    global _knowledge_graph, _ltp_tracker, _adaptive_weights
    global _initializing
    if _initialized:
        return
    if _initializing:
        # Warmup thread is running — wait for it to finish (up to 5 min)
        _init_done.wait(timeout=300)
        return
    with _init_lock:
        if _initialized:
            return  # Completed while we waited for the lock
        _initializing = True
    _t_total = time.monotonic()
    _init_surrealdb()
    _t_model = time.monotonic()
    if collection is None:
        print(
            "[MCP] SurrealDB unavailable — starting in degraded mode.", file=_sys.stderr
        )
        _initialized = True
        _initializing = False
        _init_done.set()
        return

    _t_fts = time.monotonic()

    # Initialize knowledge graph and LTP tracker (fail-open)
    try:
        from shared.knowledge_graph import KnowledgeGraph

        _kg_path = os.path.join(MEMORY_DIR, "knowledge_graph.db")
        _knowledge_graph = KnowledgeGraph(_kg_path)
    except Exception:
        _knowledge_graph = None
    try:
        from shared.ltp_tracker import LTPTracker

        _ltp_tracker = LTPTracker()
    except Exception:
        _ltp_tracker = None

    # Initialize adaptive weights (fail-open)
    try:
        from shared.memory_replay import AdaptiveWeights

        _adaptive_weights = AdaptiveWeights()
    except Exception:
        _adaptive_weights = None

    # Session-start memory replay cycle (fail-open)
    try:
        if _knowledge_graph and _ltp_tracker and collection:
            from shared.memory_replay import run_replay_cycle

            _cutoff = time.time() - 30 * 86400  # 30 days
            _recent = collection.get(
                where={"session_time": {"$gt": _cutoff}},
                limit=50,
                include=["metadatas"],
            )
            if _recent and _recent.get("ids"):
                _replay_mems = []
                for i, _rid in enumerate(_recent["ids"]):
                    _m = (
                        _recent["metadatas"][i]
                        if i < len(_recent.get("metadatas", []))
                        else {}
                    )
                    _replay_mems.append(
                        {
                            "id": _rid,
                            "tier": _m.get("tier", 2),
                            "retrieval_count": _m.get("retrieval_count", 0),
                            "session_time": _m.get("session_time", 0),
                            "timestamp": _m.get("timestamp", ""),
                            "tags": _m.get("tags", ""),
                        }
                    )
                _replay_stats = run_replay_cycle(
                    _replay_mems,
                    ltp_tracker=_ltp_tracker,
                    knowledge_graph=_knowledge_graph,
                    collection=collection,
                )
                if any(v > 0 for v in _replay_stats.values()):
                    print(f"[MCP] Replay: {_replay_stats}", file=_sys.stderr)
    except Exception:
        pass  # Replay failure must not block initialization

    # Sync tag count from collection
    _tag_count = collection.count()

    # Initialize pipeline instances (fail-open — fall back to inline logic)
    _init_pipelines()

    _t_done = time.monotonic()
    print(
        f"[MCP] Startup: model={_t_model - _t_total:.1f}s  fts={_t_fts - _t_model:.1f}s  rest={_t_done - _t_fts:.1f}s  total={_t_done - _t_total:.1f}s",
        file=_sys.stderr,
    )
    _initialized = True
    _initializing = False
    _init_done.set()


def _init_pipelines():
    """Create SearchPipeline + WritePipeline instances with current globals."""
    global _search_pipeline, _write_pipeline
    try:
        from shared.search_pipeline import SearchPipeline
        from shared.write_pipeline import WritePipeline

        _config = _read_config_toggles()
        _search_helpers = {
            "format_summaries": format_summaries,
            "keyword_search": _keyword_search,
            "merge_results": _merge_results,
            "detect_query_mode": _detect_query_mode,
            "search_observations_internal": _search_observations_internal,
            "get_expanded_tags": _get_expanded_tags,
            "tag_ids_to_summaries": _tag_ids_to_summaries,
            "generate_counterfactual_query": _generate_counterfactual_query,
            "touch_memory_timestamp": _touch_memory_timestamp,
            "validate_top_k": _validate_top_k,
            "fix_outcomes": fix_outcomes,
            "server_project": _SERVER_PROJECT,
            "server_subproject": _SERVER_SUBPROJECT,
            "embed_text": _embed_text,
        }
        _search_pipeline = SearchPipeline(
            collection=collection,
            graph=_knowledge_graph,
            ltp=_ltp_tracker,
            adaptive=_adaptive_weights,
            config=_config,
            helpers=_search_helpers,
        )
        _write_helpers = {
            "normalize_tags": _normalize_tags,
            "inject_project_tag": _inject_project_tag,
            "build_project_prefix": _build_project_prefix,
            "check_dedup": _check_dedup,
            "classify_tier": _classify_tier,
            "classify_memory_type": _classify_memory_type,
            "classify_state_type": _classify_state_type,
            "memory_classify_mode": _config.get("memory_classify_mode", "tags_only"),
            "extract_citations": _extract_citations,
            "bridge_to_fix_outcomes": _bridge_to_fix_outcomes,
            "touch_memory_timestamp": _touch_memory_timestamp,
            "generate_id": generate_id,
            "embed_text": _embed_text,
            "noise_regexes": NOISE_REGEXES,
            "min_content_length": MIN_CONTENT_LENGTH,
            "summary_length": SUMMARY_LENGTH,
            "server_project": _SERVER_PROJECT,
            "server_subproject": _SERVER_SUBPROJECT,
            "embed_text": _embed_text,
        }
        _write_pipeline = WritePipeline(
            collection=collection,
            graph=_knowledge_graph,
            config=_config,
            helpers=_write_helpers,
        )
    except Exception as e:
        print(f"[MCP] Pipeline init failed (will use inline): {e}", file=_sys.stderr)


_config_cache = {}
_config_cache_ts = 0.0
_CONFIG_CACHE_TTL = 60  # seconds


def _read_config_toggles():
    """Read config toggles from config.json (cached, refreshes every 60s)."""
    global _config_cache, _config_cache_ts
    now = time.time()
    if _config_cache and (now - _config_cache_ts) < _CONFIG_CACHE_TTL:
        return _config_cache
    _config_path = os.path.join(os.path.expanduser("~"), ".claude", "config.json")
    try:
        if os.path.isfile(_config_path):
            with open(_config_path, "r") as f:
                _config_cache = json.load(f)
                _config_cache_ts = now
                return _config_cache
    except Exception:
        pass
    _live_state_path = os.path.join(
        os.path.expanduser("~"), ".claude", "LIVE_STATE.json"
    )
    try:
        if os.path.isfile(_live_state_path):
            with open(_live_state_path, "r") as f:
                _config_cache = json.load(f)
                _config_cache_ts = now
                return _config_cache
    except Exception:
        pass
    return _config_cache or {}


def _get_expanded_tags(query):
    if collection is None:
        return []
    try:
        words = [w for w in query.lower().split() if len(w) > 3]
        if not words:
            return []
        expanded = set()
        for word in words:
            tag_ids = collection.tag_search([word], match_all=False, top_k=20)
            for tid in tag_ids:
                try:
                    data = collection.get(ids=[tid], include=["metadatas"])
                    if data and data.get("metadatas"):
                        for tag in (data["metadatas"][0].get("tags", "") or "").split(
                            ","
                        ):
                            tag = tag.strip()
                            if tag and tag.lower() not in query.lower():
                                expanded.add(tag)
                except Exception:
                    pass
        return list(expanded)[:15]
    except Exception:
        return []


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
            if meta.get("source_session_id"):
                entry["source_session_id"] = meta["source_session_id"]
            if meta.get("source_observation_ids"):
                entry["source_observation_ids"] = meta["source_observation_ids"]
            if meta.get("cluster_id"):
                entry["cluster_id"] = meta["cluster_id"]
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
            collection.update(
                ids=retrieval_update_ids, metadatas=retrieval_update_metas
            )
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

        # Parse and batch-deduplicate before upsert
        docs, metas, ids = [], [], []
        seen_ids = set()
        for line in lines:
            try:
                obs = json.loads(line.strip())
                if "document" in obs and "id" in obs:
                    oid = obs["id"]
                    if oid in seen_ids:
                        continue
                    seen_ids.add(oid)
                    docs.append(obs["document"])
                    metas.append(obs.get("metadata", {}))
                    ids.append(oid)
            except (json.JSONDecodeError, KeyError):
                continue  # skip corrupted lines

        if docs:
            # Batch upsert (LanceDB handles dedup via merge_insert)
            batch_size = 100
            for i in range(0, len(docs), batch_size):
                observations.upsert(
                    documents=docs[i : i + batch_size],
                    metadatas=metas[i : i + batch_size],
                    ids=ids[i : i + batch_size],
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
                digest_parts.append(
                    f"Bash error rate: {rate}% ({bash_errors}/{bash_total})"
                )
            if top_errors:
                digest_parts.append(
                    f"Top errors: {', '.join(f'{e}:{c}' for e, c in top_errors)}"
                )
            if top_files:
                digest_parts.append(
                    f"Top files: {', '.join(f'{f}:{c}' for f, c in top_files[:5])}"
                )

            digest_text = "\n".join(digest_parts)

            # Save digest to curated knowledge collection
            digest_id = hashlib.sha256(digest_text.encode()).hexdigest()[:16]
            collection.upsert(
                documents=[digest_text],
                metadatas=[
                    {
                        "context": "auto-capture compaction digest",
                        "tags": DIGEST_TAGS,
                        "timestamp": datetime.now().isoformat(),
                        "session_time": time.time(),
                    }
                ],
                ids=[digest_id],
            )

            # Promote high-value expired observations to curated knowledge (scoped criteria)
            promoted = 0

            def _promote_observation(doc, meta, criterion_tag, obs_id=""):
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
                    metadatas=[
                        {
                            "context": "auto-promoted from observation",
                            "tags": f"{PROMOTION_TAGS},{criterion_tag}",
                            "timestamp": datetime.now().isoformat(),
                            "session_time": time.time(),
                            "preview": promo_preview,
                            "original_error_pattern": meta.get("error_pattern", ""),
                            "source_session_id": meta.get("session_id", ""),
                            "source_observation_ids": obs_id,
                        }
                    ],
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
                        session_success_tools.setdefault(sid, set()).add(
                            meta.get("tool_name", "")
                        )

            for idx, doc, meta in session_errors:
                if promoted >= MAX_PROMOTIONS_PER_CYCLE:
                    break
                sid = meta.get("session_id", "")
                tool = meta.get("tool_name", "")
                # Only promote if no subsequent success for same tool in same session
                if sid and tool and tool in session_success_tools.get(sid, set()):
                    continue  # Tool succeeded later — skip
                _promote_observation(
                    doc,
                    meta,
                    "criterion:standalone-error",
                    exp_ids[idx] if idx < len(exp_ids) else "",
                )

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
                    churn_doc = (
                        f"High-churn file: {fp} (edited in {len(sids)} sessions)"
                    )
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
                if any(
                    kw in cmd
                    for kw in [
                        "pytest",
                        "test_framework",
                        "npm test",
                        "cargo test",
                        "go test",
                        "git commit",
                    ]
                ):
                    continue
                cmd_counts[cmd] = cmd_counts.get(cmd, 0) + 1

            for cmd, cnt in sorted(cmd_counts.items(), key=lambda x: -x[1]):
                if promoted >= MAX_PROMOTIONS_PER_CYCLE:
                    break
                if cnt >= 3:
                    repeat_doc = f"Repeated command: {cmd} ({cnt} occurrences)"
                    _promote_observation(repeat_doc, {}, "criterion:repeated-command")

            # Criterion 4: Resolved errors (error followed by success for same tool = fix pattern)
            # These are the inverse of Criterion 1 — captures "what worked" not just "what broke"
            for idx, doc, meta in session_errors:
                if promoted >= MAX_PROMOTIONS_PER_CYCLE:
                    break
                sid = meta.get("session_id", "")
                tool = meta.get("tool_name", "")
                # Only promote if the tool DID succeed later in the same session
                if sid and tool and tool in session_success_tools.get(sid, set()):
                    fix_doc = f"Resolved error pattern ({tool}): {doc}"
                    _promote_observation(
                        fix_doc,
                        meta,
                        "criterion:resolved-error",
                        exp_ids[idx] if idx < len(exp_ids) else "",
                    )

            # Delete expired observations
            if exp_ids:
                batch_size = 100
                for i in range(0, len(exp_ids), batch_size):
                    observations.delete(ids=exp_ids[i : i + batch_size])

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
                        observations.delete(ids=old_ids[i : i + batch_size])
            except Exception:
                pass

    except Exception:
        pass  # Compaction failure must not crash the server


def _search_observations_internal(query, top_k=20, recency_weight=0, query_vec=None):
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
        results = observations.query(
            query_texts=[query] if not query_vec else None,
            query_vector=query_vec,
            n_results=actual_k,
        )
        formatted = format_summaries(results)

        # Label all results as coming from observations
        for entry in formatted:
            entry["source"] = "observations"

        return {
            "results": formatted,
            "total_observations": obs_count,
        }
    except Exception:
        return {
            "results": [],
            "total_observations": 0,
            "error": "Observation search failed",
        }


@mcp.tool()
@crash_proof
def search_knowledge(
    query: str,
    top_k: int = 15,
    mode: str = "",
    recency_weight: float = 0.15,
    match_all: bool = False,
    counterfactual: bool = False,
    memory_type: str = "",
    state_type: str = "",
) -> dict:
    """Search memory for relevant information. Use before starting any task.

    Args:
        query: What to search for (semantic search)
        top_k: Number of results to return (default 15)
        mode: Force search mode ("keyword", "semantic", "hybrid", "tags", "observations", "all", "code"). Empty = auto-detect.
        recency_weight: Boost for recent results (0.0-1.0, default 0.15). 0 disables.
        match_all: For tag mode only — if true, all tags must be present (default false).
        counterfactual: Force counterfactual retrieval pass (default false). Behavior depends on counterfactual_mode in config: "always" (every search), "threshold" (weak results only), "opt-in" (this param only).
        memory_type: Filter by memory type ("reference", "working", or "" for all). Default "" returns all.
        state_type: Filter by state type ("ephemeral", "conceptual", or "" for all). Default "" returns all.
    """
    global _last_search_ids
    _ensure_initialized()
    if _surreal_degraded:
        return {
            "error": "Storage unavailable ��� running in degraded mode",
            "degraded": True,
        }

    # Delegate to SearchPipeline (with inline fallback)
    if _search_pipeline is not None:
        # Refresh config toggles (they may change between calls)
        _search_pipeline.config = _read_config_toggles()
        # Refresh mutable helpers that may change
        _search_pipeline.h["fix_outcomes"] = fix_outcomes
        _search_pipeline.h["server_project"] = _SERVER_PROJECT
        _search_pipeline.h["server_subproject"] = _SERVER_SUBPROJECT
        result = _search_pipeline.search(
            query,
            top_k=top_k,
            mode=mode,
            recency_weight=recency_weight,
            match_all=match_all,
            counterfactual=counterfactual,
            memory_type=memory_type,
            state_type=state_type,
        )
        # Track search result IDs for implicit feedback (fail-open)
        try:
            _last_search_ids = [
                r.get("id", "") for r in result.get("results", [])[:10] if r.get("id")
            ]
        except Exception:
            _last_search_ids = []
        return result

    # Pipeline not initialized — return error
    return {
        "error": "Search pipeline not initialized",
        "results": [],
        "total_memories": 0,
    }


# Dead code below removed — inline fallback replaced by SearchPipeline


def _extract_error_text(content, context):
    """Extract error description from fix content. Cascade, first match wins."""
    import re

    # A: Fixed/Resolved + ErrorName/Exception/FAILED
    m = re.search(
        r"(?:Fixed|Resolved|fixed|resolved)\s+(\S+(?:Error|Exception|FAILED|error)\S*)",
        content,
    )
    if m:
        return m.group(1)
    # B: Fixed [thing] bug/issue/problem/failure/crash/regression/mismatch/dead code
    m = re.search(
        r"(?:Fixed|Resolved|fixed|resolved)\s+(.+?\b(?:bug|issue|problem|failure|crash|regression|mismatch|dead\s*code))",
        content,
    )
    if m:
        return m.group(1).strip()[:120]
    # C: Fixed Gate N / Fixed component.method()
    m = re.search(
        r"(?:Fixed|Resolved|fixed|resolved)\s+((?:Gate\s*\d+|[A-Za-z_]+\.[A-Za-z_]+(?:\(\))?)\S*)",
        content,
    )
    if m:
        return m.group(1).strip()[:120]
    # D: BUG FIX: / CRITICAL FIX: / FIX: description
    m = re.search(
        r"(?:BUG\s+FIX|CRITICAL\s+FIX|FIX)\s*[:\-]\s*(.+?)(?:\.|,|\n|$)", content
    )
    if m:
        return m.group(1).strip()[:120]
    # E: Fixed [description] — broad catch, skip noise phrases
    m = re.search(r"(?:Fixed|Resolved|fixed|resolved)\s+(.+?)(?:\.|,|\n|$)", content)
    if m:
        txt = m.group(1).strip()
        noise = {
            "the test",
            "the bug",
            "the issue",
            "the code",
            "the file",
            "the error",
            "it",
            "this",
        }
        if len(txt) > 5 and txt.lower() not in noise:
            return txt[:120]
    # F: Context field as fallback
    if context and len(context.strip()) > 5:
        return context.strip()[:120]
    # G: First 100 chars of content
    return content[:100]


def _extract_strategy(content):
    """Extract fix strategy from content. Cascade, first match wins."""
    import re

    # S1: by/via + action phrase (verb-oriented)
    m = re.search(
        r"\b(?:by|via)\s+((?:adding|removing|changing|replacing|setting|updating|patching|using|wrapping|moving|renaming|splitting|merging|importing|exporting|converting|switching|reverting)\b.+?)(?:\.|,|\n|$)",
        content,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()
    # S2: Solution:/Resolution:/Workaround: + description (not BUG FIX: or CRITICAL FIX:)
    m = re.search(
        r"(?<!\bBUG\s)(?<!\bCRITICAL\s)(?<!\bM-\d\s)(?:Fix|Solution|Resolution|Workaround)\s*[:\-]\s*(.+?)(?:\.|,|\n|$)",
        content,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()
    # S3: Added/Changed/Replaced/Removed/Set/Updated/Patched + description
    m = re.search(
        r"\b((?:Added|Changed|Replaced|Removed|Set|Updated|Patched|Renamed|Wrapped|Moved|Reverted|Converted|Switched)\s+.+?)(?:\.|,|\n|$)",
        content,
    )
    if m:
        return m.group(1).strip()
    # S4: X → Y / X changed to Y / replaced X with Y
    m = re.search(r"(\S+\s*(?:→|->|changed\s+to|replaced\s+with)\s+\S+)", content)
    if m:
        return m.group(1).strip()
    return None


def _normalize_strategy(raw):
    """Normalize raw strategy text into a short hyphenated strategy_id."""
    if not raw:
        return "auto-bridged"
    fillers = {
        "the",
        "a",
        "an",
        "in",
        "to",
        "for",
        "of",
        "on",
        "at",
        "is",
        "was",
        "and",
        "or",
        "that",
        "this",
        "it",
    }
    words = raw.lower().split()
    words = [w for w in words if w not in fillers and len(w) > 1]
    if not words:
        return "auto-bridged"
    result = "-".join(words[:5])
    return result[:60] if len(result) > 60 else result


def _bridge_to_fix_outcomes(content, context, tags):
    """Bridge remember_this to fix_outcomes when type:fix tag is detected.

    Extracts error info from content, creates a fix_outcomes entry if one
    doesn't already exist (dedup: manual record_outcome takes priority).
    Returns dict with chain_id on success, None on skip/failure.
    """
    try:
        if fix_outcomes is None:
            return None

        error_text = _extract_error_text(content, context)
        raw_strategy = _extract_strategy(content)
        strategy_id = _normalize_strategy(raw_strategy)

        normalized, error_hash = error_signature(error_text)
        strategy_hash = fnv1a_hash(strategy_id)
        chain_id = f"{error_hash}_{strategy_hash}"

        # Dedup: skip if manual record_outcome already exists for this chain
        try:
            existing = fix_outcomes.get(ids=[chain_id])
            if (
                existing
                and existing.get("documents")
                and len(existing["documents"]) > 0
            ):
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
            metadatas=[
                {
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
                }
            ],
            ids=[chain_id],
        )
        return {"chain_id": chain_id, "outcome": outcome}
    except Exception:
        return None


def _check_dedup(content, tags="", query_vector=None):
    """Check if content is a near-duplicate of existing knowledge.

    Returns None if unique, or a dict:
      - {"blocked": True, "existing_id": ..., "distance": ...} if hard-dedup
      - {"soft_dupe_tag": "possible-dupe:ID"} if in soft zone

    Args:
        query_vector: Pre-computed embedding vector. Skips re-embedding if provided.
    """
    if _FIX_DEDUP_EXEMPT and "type:fix" in tags:
        return None
    try:
        cnt = collection.count()
        if cnt == 0:
            return None
        _query_kwargs = {"n_results": 1, "include": ["distances"]}
        if query_vector is not None:
            _query_kwargs["query_vector"] = query_vector
        else:
            _query_kwargs["query_texts"] = [content]
        similar = collection.query(**_query_kwargs)
        if (
            similar
            and similar.get("distances")
            and similar["distances"][0]
            and similar["distances"][0][0] is not None
        ):
            dist = similar["distances"][0][0]
            existing_id = similar["ids"][0][0]
            threshold = FIX_DEDUP_THRESHOLD if "type:fix" in tags else DEDUP_THRESHOLD
            if dist < threshold:
                return {
                    "blocked": True,
                    "existing_id": existing_id,
                    "distance": round(dist, 4),
                }
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
    if _surreal_degraded:
        return {
            "error": "Storage unavailable ��� running in degraded mode",
            "degraded": True,
        }

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
def remember_this(
    content: str,
    context: str = "",
    tags: str = "",
    force: bool = False,
    source_session_id: str = "",
    source_observation_ids: str = "",
) -> dict:
    """Save something to persistent memory. Use after every fix, discovery, or decision.

    Args:
        content: The knowledge to remember (max 800 chars — concise key facts only, not full research)
        context: What you were doing when you learned this
        tags: Comma-separated tags for categorization (e.g., "bug,fix,auth")
        force: Skip dedup check entirely (escape hatch if threshold is wrong)
        source_session_id: Session ID to record provenance (auto-detected if omitted)
        source_observation_ids: Comma-separated observation IDs this knowledge was derived from
    """
    _ensure_initialized()
    if _surreal_degraded:
        return {
            "error": "Storage unavailable ��� running in degraded mode",
            "degraded": True,
        }

    # Delegate to WritePipeline (with inline fallback)
    if _write_pipeline is not None:
        _write_pipeline.h["server_project"] = _SERVER_PROJECT
        _write_pipeline.h["server_subproject"] = _SERVER_SUBPROJECT
        result = _write_pipeline.write(
            content,
            context=context,
            tags=tags,
            force=force,
            source_session_id=source_session_id,
            source_observation_ids=source_observation_ids,
        )

        # RELATE: knowledge->derived_from->observation (fail-open)
        if (
            source_observation_ids
            and not result.get("rejected")
            and not result.get("deduplicated")
        ):
            try:
                doc_id = result.get("id", "")
                if _surreal_db is not None and doc_id:
                    for oid in source_observation_ids.split(","):
                        oid = oid.strip()
                        if oid:
                            _surreal_db.query(
                                "RELATE $from->derived_from->$to SET timestamp=time::now()",
                                {
                                    "from": RecordID("knowledge", doc_id),
                                    "to": RecordID("observation", oid),
                                },
                            )
            except Exception:
                pass

        return result

    # Pipeline not initialized — return error
    return {"error": "Write pipeline not initialized", "total_memories": 0}


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
    if _surreal_degraded:
        return {"error": "Storage unavailable ��� running in degraded mode"}
    threshold = _validate_distance_threshold(
        threshold, default=0.15, min_val=0.03, max_val=0.5
    )

    count = collection.count()
    if count == 0:
        return {"candidates": [], "moved": 0, "message": "No memories to scan"}

    # Export backup before any changes
    backup_file = os.path.join(
        MEMORY_DIR, f"dedup_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    all_data = collection.get(
        limit=count, include=["documents", "metadatas", "embeddings"]
    )
    with open(backup_file, "w") as f:
        # Embeddings are lists of floats — JSON-serializable
        json.dump(
            {
                "ids": all_data.get("ids", []),
                "documents": all_data.get("documents", []),
                "metadatas": all_data.get("metadatas", []),
                "count": count,
                "exported_at": datetime.now().isoformat(),
            },
            f,
        )

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
                query_texts=[doc],
                n_results=2,
                include=["distances"],
            )
            if (
                not similar
                or not similar.get("distances")
                or not similar["distances"][0]
            ):
                continue
            # First result is self (distance ~0), second is nearest neighbor
            for j, (sid, sdist) in enumerate(
                zip(similar["ids"][0], similar["distances"][0])
            ):
                if sid == ids[i]:
                    continue  # skip self
                if sdist < threshold:
                    pair_key = tuple(sorted([ids[i], sid]))
                    if pair_key not in seen_pairs:
                        seen_pairs.add(pair_key)
                        candidates.append(
                            {
                                "id_a": ids[i],
                                "id_b": sid,
                                "distance": round(sdist, 4),
                                "preview_a": (
                                    metas[i].get("preview", "")
                                    if i < len(metas)
                                    else ""
                                )[:80],
                            }
                        )
        except Exception:
            continue

    moved = 0
    if not dry_run and quarantine is not None:
        for cand in candidates:
            try:
                # Move the second item (id_b) to quarantine
                victim_id = cand["id_b"]
                victim = collection.get(
                    ids=[victim_id], include=["documents", "metadatas"]
                )
                if victim and victim.get("ids") and victim["ids"]:
                    v_doc = victim["documents"][0] if victim.get("documents") else ""
                    v_meta = victim["metadatas"][0] if victim.get("metadatas") else {}
                    v_meta["quarantine_reason"] = (
                        f"dedup_sweep:distance={cand['distance']}"
                    )
                    v_meta["quarantine_pair"] = cand["id_a"]
                    v_meta["quarantined_at"] = datetime.now().isoformat()
                    quarantine.upsert(
                        documents=[v_doc], metadatas=[v_meta], ids=[victim_id]
                    )
                    collection.delete(ids=[victim_id])
                    # Transfer graph edges from duplicate to survivor, then deactivate (fail-open)
                    try:
                        if _knowledge_graph:
                            _knowledge_graph.transfer_edges(victim_id, cand["id_a"])
                            _knowledge_graph.deactivate_entity(victim_id)
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
    if _surreal_degraded:
        return {
            "error": "Storage unavailable ��� running in degraded mode",
            "degraded": True,
        }
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
            if (
                result.get("metadatas")
                and i < len(result["metadatas"])
                and result["metadatas"][i]
            ):
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
                        "related_urls": [
                            u.strip() for u in related.split(",") if u.strip()
                        ],
                        "source_method": meta.get("source_method", ""),
                    }

                # L0 evidence pointer
                source_sid = meta.get("source_session_id", "")
                if source_sid:
                    entry["source_l0"] = {
                        "session_id": source_sid,
                        "hint": f"Raw transcript: ~/.claude/projects/*/sessions/{source_sid}.jsonl",
                    }

                # Observation evidence pointers
                obs_ids_str = meta.get("source_observation_ids", "")
                if obs_ids_str:
                    entry["source_observations"] = [
                        oid.strip() for oid in obs_ids_str.split(",") if oid.strip()
                    ]

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

        # Implicit feedback: if retrieved ID was in last search results, signal positive (fail-open)
        try:
            if _adaptive_weights and _last_search_ids:
                for _fid in ids:
                    if _fid in _last_search_ids:
                        _adaptive_weights.record_signal("ltp_blend", True)
                        _adaptive_weights.record_signal("graph_discount", True)
                        break  # one signal per get_memory call
        except Exception:
            pass

        _touch_memory_timestamp()
        # Single ID: return single entry (backward compatible)
        return (
            entries[0]
            if len(entries) == 1
            else {"memories": entries, "count": len(entries)}
        )

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
    if _surreal_degraded:
        return {
            "error": "Storage unavailable ��� running in degraded mode",
            "degraded": True,
        }
    try:
        ids = [i.strip() for i in id.split(",") if i.strip()]
        if not ids:
            return {"error": "No valid ID provided"}
        existing = collection.get(ids=ids)
        found = existing.get("ids", []) if existing else []
        if not found:
            return {"error": f"No memories found with ids: {ids}"}
        collection.delete(ids=found)
        # Clean up knowledge graph edges for deleted memories (fail-open)
        try:
            if _knowledge_graph:
                for did in found:
                    _knowledge_graph.remove_entity_edges(did)
                    _knowledge_graph.deactivate_entity(did)
        except Exception:
            pass
        return {"deleted": found, "count": len(found)}
    except Exception as e:
        return {"error": f"Failed to delete memory: {str(e)}"}


# DORMANT (Session 86) — zero usage across 86 sessions, observation data accessible via search_knowledge(mode="all")
# Re-add @mcp.tool() and @crash_proof to reactivate, then restart MCP server.
def timeline(
    anchor_id: str = "",
    anchor_time: str = "",
    window_minutes: int = 10,
    limit: int = 20,
) -> dict:
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
        return {
            "results": [],
            "total_observations": 0,
            "message": "No observations yet.",
        }

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
        return {
            "results": [],
            "window": f"±{window_minutes}min",
            "anchor": anchor_epoch,
        }

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
    if _surreal_degraded:
        return {
            "error": "Storage unavailable ��� running in degraded mode",
            "degraded": True,
        }
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
        metadatas=[
            {
                "error_hash": error_hash,
                "strategy_id": strategy_id,
                "chain_id": chain_id,
                "outcome": "pending",
                "confidence": str(round(confidence, 4)),
                "attempts": str(attempts),
                "successes": str(successes),
                "timestamp": str(time.time()),
                "last_outcome_time": "",
            }
        ],
        ids=[chain_id],
    )

    # RELATE: attempt->tried_for->error (fail-open)
    try:
        if _surreal_db is not None:
            _surreal_db.query(
                "RELATE $from->tried_for->$to SET strategy=$s, timestamp=time::now()",
                {
                    "from": RecordID("attempt", chain_id),
                    "to": RecordID("error", error_hash),
                    "s": strategy_id,
                },
            )
    except Exception:
        pass

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
    if _surreal_degraded:
        return {
            "error": "Storage unavailable ��� running in degraded mode",
            "degraded": True,
        }
    if outcome not in ("success", "failure"):
        return {"error": "outcome must be 'success' or 'failure'"}

    try:
        existing = fix_outcomes.get(ids=[chain_id])
        if (
            not existing
            or not existing.get("documents")
            or len(existing["documents"]) == 0
        ):
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
            metadatas=[
                {
                    **meta,
                    "outcome": outcome,
                    "confidence": str(round(confidence, 4)),
                    "successes": str(successes),
                    "banned": str(banned),
                    "last_outcome_time": str(time.time()),
                }
            ],
        )

        # RELATE: fix->resolved/failed_on->error (fail-open)
        try:
            error_hash = meta.get("error_hash", "")
            if _surreal_db is not None and error_hash:
                if outcome == "success":
                    _surreal_db.query(
                        "RELATE $from->resolved->$to SET confidence=$c, chain_id=$chain, timestamp=time::now()",
                        {
                            "from": RecordID("fix", chain_id),
                            "to": RecordID("error", error_hash),
                            "c": confidence,
                            "chain": chain_id,
                        },
                    )
                else:
                    _surreal_db.query(
                        "RELATE $from->failed_on->$to SET chain_id=$chain, timestamp=time::now()",
                        {
                            "from": RecordID("fix", chain_id),
                            "to": RecordID("error", error_hash),
                            "chain": chain_id,
                        },
                    )
        except Exception:
            pass

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
    if _surreal_degraded:
        return {
            "error": "Storage unavailable ��� running in degraded mode",
            "degraded": True,
        }
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
                    result["observation_note"] = (
                        "No fix history found. Showing related observations."
                    )
        except Exception:
            pass

    return result


@mcp.tool()
@crash_proof
def traverse_graph(start_id: str, depth: int = 2, direction: str = "both") -> dict:
    """Traverse graph edges from a starting node to find connected memories.

    Args:
        start_id: The record ID to start from (e.g., "dk_abc123" for knowledge, or "hash_xyz" for error)
        depth: How many hops to traverse (default 2, max 5)
        direction: "out" (forward edges), "in" (reverse edges), or "both" (default)
    """
    _ensure_initialized()
    if _surreal_degraded:
        return {
            "error": "Storage unavailable — running in degraded mode",
            "degraded": True,
        }
    if _surreal_db is None:
        return {"error": "SurrealDB not initialized"}

    depth = max(1, min(depth, 5))
    if direction not in ("out", "in", "both"):
        direction = "both"

    edges_out = []
    edges_in = []

    try:
        # Determine possible tables from ID prefix
        tables = ["knowledge"]
        if start_id.startswith("obs_"):
            tables = ["observation"]
        elif start_id.startswith("dk_"):
            tables = ["knowledge"]
        else:
            tables = ["attempt", "fix", "error"]

        edge_types = ["tried_for", "resolved", "failed_on", "derived_from"]

        if direction in ("out", "both"):
            for table in tables:
                for edge_type in edge_types:
                    results = _surreal_db.query(
                        f"SELECT * FROM {edge_type} WHERE in = type::thing($table, $id)",
                        {"table": table, "id": start_id},
                    )
                    for r in results if isinstance(results, list) else []:
                        edges_out.append(
                            {
                                "edge_type": edge_type,
                                "from_table": table,
                                "target": str(r.get("out", "")),
                                "metadata": {
                                    k: v
                                    for k, v in r.items()
                                    if k not in ("id", "in", "out")
                                },
                            }
                        )

        if direction in ("in", "both"):
            for table in tables:
                for edge_type in edge_types:
                    results = _surreal_db.query(
                        f"SELECT * FROM {edge_type} WHERE out = type::thing($table, $id)",
                        {"table": table, "id": start_id},
                    )
                    for r in results if isinstance(results, list) else []:
                        edges_in.append(
                            {
                                "edge_type": edge_type,
                                "from_table": table,
                                "source": str(r.get("in", "")),
                                "metadata": {
                                    k: v
                                    for k, v in r.items()
                                    if k not in ("id", "in", "out")
                                },
                            }
                        )

    except Exception as e:
        return {"error": f"Graph traversal failed: {str(e)}"}

    return {
        "start_id": start_id,
        "direction": direction,
        "depth": depth,
        "edges_out": edges_out,
        "edges_in": edges_in,
        "total_edges": len(edges_out) + len(edges_in),
    }


@mcp.tool()
@crash_proof
def find_pattern(strategy_or_error: str, pattern_type: str = "failed_strategy") -> dict:
    """Find patterns in fix history using graph edges.

    Args:
        strategy_or_error: Strategy name or error text to search for
        pattern_type: "failed_strategy" (strategies that keep failing), "successful_strategy" (what works), or "error_cascade" (errors linked to same strategy)
    """
    _ensure_initialized()
    if _surreal_degraded:
        return {
            "error": "Storage unavailable — running in degraded mode",
            "degraded": True,
        }
    if _surreal_db is None:
        return {"error": "SurrealDB not initialized"}

    if pattern_type not in ("failed_strategy", "successful_strategy", "error_cascade"):
        pattern_type = "failed_strategy"

    results = []

    try:
        if pattern_type == "failed_strategy":
            rows = _surreal_db.query(
                "SELECT *, in AS fix_node, out AS error_node FROM failed_on WHERE chain_id CONTAINS $s OR in.strategy = $s",
                {"s": strategy_or_error},
            )
            if not rows or not isinstance(rows, list):
                # Fallback: search fix_outcomes by strategy
                fo = fix_outcomes.get(where={"strategy_id": strategy_or_error})
                if fo and fo.get("metadatas"):
                    for meta in fo["metadatas"]:
                        if (
                            meta.get("outcome") == "failure"
                            or float(meta.get("confidence", 1)) < 0.18
                        ):
                            results.append(
                                {
                                    "strategy_id": meta.get("strategy_id", ""),
                                    "error_hash": meta.get("error_hash", ""),
                                    "confidence": float(meta.get("confidence", 0)),
                                    "attempts": int(meta.get("attempts", 0)),
                                    "pattern": "repeatedly_failing",
                                }
                            )
            else:
                for r in rows:
                    results.append(
                        {
                            "fix_node": str(r.get("fix_node", "")),
                            "error_node": str(r.get("error_node", "")),
                            "chain_id": r.get("chain_id", ""),
                            "timestamp": str(r.get("timestamp", "")),
                            "pattern": "failed_edge",
                        }
                    )

        elif pattern_type == "successful_strategy":
            rows = _surreal_db.query(
                "SELECT *, in AS fix_node, out AS error_node FROM resolved WHERE chain_id CONTAINS $s OR in.strategy = $s",
                {"s": strategy_or_error},
            )
            if not rows or not isinstance(rows, list):
                fo = fix_outcomes.get(where={"strategy_id": strategy_or_error})
                if fo and fo.get("metadatas"):
                    for meta in fo["metadatas"]:
                        if (
                            meta.get("outcome") == "success"
                            or float(meta.get("confidence", 0)) > 0.5
                        ):
                            results.append(
                                {
                                    "strategy_id": meta.get("strategy_id", ""),
                                    "error_hash": meta.get("error_hash", ""),
                                    "confidence": float(meta.get("confidence", 0)),
                                    "successes": int(meta.get("successes", 0)),
                                    "pattern": "proven_effective",
                                }
                            )
            else:
                for r in rows:
                    results.append(
                        {
                            "fix_node": str(r.get("fix_node", "")),
                            "error_node": str(r.get("error_node", "")),
                            "chain_id": r.get("chain_id", ""),
                            "confidence": r.get("confidence", 0),
                            "pattern": "resolved_edge",
                        }
                    )

        elif pattern_type == "error_cascade":
            _, error_hash = error_signature(strategy_or_error)
            rows = _surreal_db.query(
                "SELECT *, in AS attempt_node FROM tried_for WHERE out = type::thing('error', $hash)",
                {"hash": error_hash},
            )
            if isinstance(rows, list):
                for r in rows:
                    results.append(
                        {
                            "attempt_node": str(r.get("attempt_node", "")),
                            "strategy": r.get("strategy", ""),
                            "timestamp": str(r.get("timestamp", "")),
                            "pattern": "attempted_strategy",
                        }
                    )

    except Exception as e:
        return {"error": f"Pattern search failed: {str(e)}"}

    return {
        "query": strategy_or_error,
        "pattern_type": pattern_type,
        "results": results,
        "count": len(results),
    }


@mcp.tool()
@crash_proof
def health_check() -> dict:
    """Return lightweight server health metrics.

    Returns server uptime, table row counts, last write timestamp,
    embedding model status, LanceDB connection status, Tags DB status,
    total memory count, and disk usage of ~/data/memory/surrealdb/.

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

    # Disk usage of surrealdb directory
    disk_bytes = 0
    try:
        if os.path.isdir(SURREAL_DIR):
            for dirpath, _dirs, files in os.walk(SURREAL_DIR):
                for fname in files:
                    try:
                        disk_bytes += os.path.getsize(os.path.join(dirpath, fname))
                    except OSError:
                        pass
    except Exception:
        disk_bytes = -1

    return {
        "status": "ok" if not _surreal_degraded else "degraded",
        "uptime": uptime_str,
        "uptime_seconds": uptime_s,
        "table_counts": table_counts,
        "total_memories": total_count,
        "last_write": last_write,
        "embedding_model": "loaded" if _embedding_fn is not None else "not_loaded",
        "surrealdb": "connected"
        if (_surreal_db is not None and not _surreal_degraded)
        else ("degraded" if _surreal_degraded else "not_connected"),
        "tags_db": "integrated",
        "disk_usage_mb": round(disk_bytes / (1024 * 1024), 2)
        if disk_bytes >= 0
        else -1,
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
            tag_ids = collection.tag_search([tag], match_all=False, top_k=200)
            tag_results = _tag_ids_to_summaries(tag_ids)
            for r in tag_results:
                if r.get("id") and r["id"] not in [c["id"] for c in candidates]:
                    candidates.append(r)
        except Exception:
            continue

    if not candidates:
        return {
            "clusters": [],
            "message": "No promotable memories found (need type:error, type:learning, or type:correction tags).",
        }

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

        scored_clusters.append(
            {
                "suggested_rule": best_preview[:200],
                "supporting_ids": member_id_list,
                "count": member_count,
                "score": round(score, 3),
                "avg_age_days": round(avg_age, 1),
            }
        )

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
            return {
                "results": [],
                "total_memories": count,
                "message": "No memories found matching criteria.",
            }

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

            stale.append(
                {
                    "id": mid,
                    "preview": preview[:100],
                    "age_days": age_days,
                    "retrieval_count": retrieval_count,
                    "last_retrieved": meta.get("last_retrieved", "never"),
                    "tags": meta.get("tags", ""),
                }
            )

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


def cluster_knowledge(
    min_cluster_size: int = 3, distance_threshold: float = 0.3
) -> dict:
    """Group related memories into semantic clusters using vector distance queries.

    Uses a union-find algorithm over neighbor queries to discover
    clusters of related knowledge. Useful for finding themes, redundancies,
    and knowledge gaps.

    Args:
        min_cluster_size: Minimum memories in a cluster to be returned (default 3)
        distance_threshold: Max cosine distance to consider memories related (default 0.3, range 0.05-0.8)
    """
    min_cluster_size = max(2, min(min_cluster_size, 20))
    distance_threshold = _validate_distance_threshold(
        distance_threshold, default=0.3, min_val=0.05, max_val=0.8
    )

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
        return {
            "clusters": [],
            "total_memories": n,
            "message": f"Not enough memories ({n}) for clustering.",
        }

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
            neighbor_dists = (
                neighbors["distances"][0] if neighbors.get("distances") else []
            )

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
            words = re.findall(r"[a-zA-Z_]{4,}", doc.lower())
            all_words.extend(words)

        # Common tags: tags appearing in >30% of cluster members
        tag_counts = Counter(all_tags)
        common_tags = [
            tag
            for tag, cnt in tag_counts.most_common(10)
            if cnt >= max(2, len(members) * 0.3)
        ]

        # Topic label: top 3 most frequent meaningful words (exclude stop words)
        stop_words = {
            "this",
            "that",
            "with",
            "from",
            "have",
            "been",
            "were",
            "will",
            "would",
            "could",
            "should",
            "their",
            "there",
            "they",
            "which",
            "when",
            "what",
            "where",
            "than",
            "then",
            "also",
            "about",
            "into",
            "more",
            "some",
            "such",
            "only",
            "other",
            "each",
            "just",
            "like",
            "over",
            "very",
            "after",
            "before",
            "between",
            "under",
            "again",
            "does",
            "done",
            "make",
            "made",
            "most",
            "much",
            "must",
            "need",
            "none",
            "true",
            "false",
        }
        word_counts = Counter(w for w in all_words if w not in stop_words)
        top_words = [w for w, _ in word_counts.most_common(3)]
        topic = " / ".join(top_words) if top_words else "misc"

        # Sample preview: first member's content snippet
        sample_idx = members[0]
        sample_doc = (
            docs[sample_idx] if sample_idx < len(docs) and docs[sample_idx] else ""
        )
        sample_preview = sample_doc[:SUMMARY_LENGTH].replace("\n", " ")
        if len(sample_doc) > SUMMARY_LENGTH:
            sample_preview += "..."

        result_clusters.append(
            {
                "cluster_id": f"cluster_{len(result_clusters)}",
                "topic": topic,
                "size": len(members),
                "common_tags": common_tags,
                "member_ids": member_ids,
                "sample_preview": sample_preview,
            }
        )

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


def _bootstrap_clusters() -> None:
    """One-time: assign all existing memories to clusters.

    Run with: python memory_server.py --bootstrap-clusters
    O(n) with centroid cache in memory — safe even for thousands of memories.
    """
    _ensure_initialized()
    if not _clusters_coll:
        print("Bootstrap: clusters collection unavailable", file=_sys.stderr)
        return
    if not collection:
        print("Bootstrap: collection unavailable", file=_sys.stderr)
        return

    count = collection.count()
    print(f"Bootstrap: assigning clusters to {count} memories...", file=_sys.stderr)

    all_data = collection.get(
        limit=count, include=["metadatas", "documents", "embeddings"]
    )
    if not all_data or not all_data.get("ids"):
        print("Bootstrap: no memories found", file=_sys.stderr)
        return

    ids = all_data["ids"]
    docs = all_data.get("documents") or []
    embeddings = all_data.get("embeddings") or []
    processed = 0

    for i, doc_id in enumerate(ids):
        doc = docs[i] if i < len(docs) else ""
        if not doc:
            continue
        try:
            if i < len(embeddings) and embeddings[i]:
                import numpy as np

                vec = np.array(embeddings[i], dtype=np.float32)
            else:
                vec = _embed_text(doc)
            cid = _surreal_cluster_assign(vec, doc)
            if cid:
                collection.update(ids=[doc_id], metadatas=[{"cluster_id": cid}])
                processed += 1
        except Exception as e:
            print(f"Bootstrap: failed for {doc_id}: {e}", file=_sys.stderr)

    print(
        f"Bootstrap: done — {processed}/{len(ids)} memories assigned", file=_sys.stderr
    )


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

    health_score = int(recent_score * 40 + retrieval_score * 30 + diversity_score * 30)
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
        "unique_tags": unique_tags,
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


def rebuild_tags() -> dict:
    """No-op — tags are stored directly in SurrealDB records."""
    return {"result": "No-op: tags stored in SurrealDB records directly"}


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
            rebuild_tags()
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
    search_dirs = (
        [ramdisk_dir, state_dir] if os.path.isdir(ramdisk_dir) else [state_dir]
    )

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
                        effectiveness[gate] = {
                            "blocks": 0,
                            "overrides": 0,
                            "prevented": 0,
                        }
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
        eff_pct = (
            round(100 * prevented / total_resolved) if total_resolved > 0 else None
        )
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
        "message": f"Analyzed {len(results)} gates"
        + (f", {len(suggestions)} need attention" if suggestions else ""),
    }


# DORMANT — saves ~180 tokens/prompt. Uncomment @mcp.tool() to reactivate.
# @mcp.tool()
@crash_proof
def maintenance(
    action: str,
    top_k: int | None = None,
    days: int | None = None,
    min_cluster_size: int | None = None,
    distance_threshold: float | None = None,
) -> dict:
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
    if _surreal_degraded:
        return {
            "error": "Storage unavailable ��� running in degraded mode",
            "degraded": True,
        }
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
            distance_threshold=distance_threshold
            if distance_threshold is not None
            else 0.3,
        )
    elif action == "health":
        return memory_health_report()
    elif action == "rebuild_tags":
        return rebuild_tags()
    elif action == "optimize":
        return _optimize_tables()
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
                "optimize": "Compact tables and remove orphaned old version files (no params)",
                "batch_rename": "Rename megaman→torus in all memory content and tags",
                "gate_effectiveness": "Analyze gate block effectiveness from session state",
            },
        }


# ──────────────────────────────────────────────────


def _optimize_tables() -> dict:
    """SurrealDB maintenance — report table counts."""
    if _surreal_db is None:
        return {"action": "optimize", "error": "SurrealDB not initialized"}
    results = {}
    for name, coll in [
        ("knowledge", collection),
        ("fix_outcomes", fix_outcomes),
        ("observations", observations),
        ("web_pages", web_pages),
        ("quarantine", quarantine),
    ]:
        if coll:
            results[name] = {"rows": coll.count(), "status": "ok"}
    return {"action": "optimize", "tables": results}


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
                    for key in (
                        "file_path",
                        "command",
                        "pattern",
                        "query",
                        "path",
                        "content",
                        "prompt",
                    ):
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
            sa
            for sa in active_subagents
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

    if not os.path.isdir(SURREAL_DIR):
        raise RuntimeError(f"SurrealDB directory not found: {SURREAL_DIR}")

    bak_path = os.path.join(MEMORY_DIR, "surrealdb.backup")
    tmp_path = bak_path + ".tmp"

    # Remove stale tmp if exists
    if os.path.exists(tmp_path):
        shutil.rmtree(tmp_path)

    try:
        shutil.copytree(SURREAL_DIR, tmp_path)
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

        if method == "optimize":
            result = _optimize_tables()
            return {"ok": True, "result": result}

        if method == "auto_remember":
            content = params.get("content", "")
            context = params.get("context", "")
            tags = params.get("tags", "")
            tags = _normalize_tags(tags)
            tags = _inject_project_tag(tags)
            if not content or len(content.strip()) < MIN_CONTENT_LENGTH:
                return {
                    "ok": True,
                    "result": {"saved": False, "reason": "content too short"},
                }
            # Dedup check
            dedup = _check_dedup(content, tags)
            if dedup and dedup.get("blocked"):
                return {
                    "ok": True,
                    "result": {
                        "saved": False,
                        "reason": "deduplicated",
                        "existing_id": dedup["existing_id"],
                        "distance": dedup["distance"],
                    },
                }
            # Cap metadata
            if len(context) > 500:
                context = context[:497] + "..."
            if len(tags) > 500:
                tags = tags[:497] + "..."
            # Append soft-dupe tag if borderline
            if dedup and dedup.get("soft_dupe_tag"):
                tags = (
                    f"{tags},{dedup['soft_dupe_tag']}"
                    if tags
                    else dedup["soft_dupe_tag"]
                )
            doc_id = generate_id(content)
            timestamp = datetime.now().isoformat()
            preview = content[:SUMMARY_LENGTH].replace("\n", " ")
            if len(content) > SUMMARY_LENGTH:
                preview += "..."
            now = time.time()
            collection.upsert(
                documents=[content],
                metadatas=[
                    {
                        "context": context,
                        "tags": tags,
                        "timestamp": timestamp,
                        "session_time": now,
                        "preview": preview,
                        "primary_source": "",
                        "related_urls": "",
                        "source_method": "auto_remember",
                    }
                ],
                ids=[doc_id],
            )
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
                        documents=docs[i : i + batch_size],
                        metadatas=metas[i : i + batch_size] if metas else None,
                        ids=ids[i : i + batch_size],
                    )
                return {"ok": True, "result": len(docs)}
            return {"ok": False, "error": "upsert requires documents and ids"}

        if method == "delete":
            ids = params.get("ids", [])
            if ids:
                batch_size = 100
                for i in range(0, len(ids), batch_size):
                    col.delete(ids=ids[i : i + batch_size])
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
    """Create, bind, and return a new UDS server socket.

    Probe-connects before unlinking to avoid stealing a live server's socket.
    Returns None if another server is already listening.
    """
    global _socket_owner_pid
    if os.path.exists(SOCKET_PATH):
        # Probe: is another server already listening?
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            probe.settimeout(1.0)
            probe.connect(SOCKET_PATH)
            # Connection succeeded — another server is live
            probe.close()
            print(
                "[UDS] Another server is live on socket, skipping UDS bind",
                file=_sys.stderr,
            )
            return None
        except (ConnectionRefusedError, FileNotFoundError, OSError):
            # Stale socket — safe to unlink
            probe.close()
            try:
                os.unlink(SOCKET_PATH)
            except FileNotFoundError:
                pass
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCKET_PATH)
    srv.listen(8)
    srv.settimeout(1.0)
    _socket_owner_pid = os.getpid()
    print(f"[UDS] Bound socket (pid={_socket_owner_pid})", file=_sys.stderr)
    return srv


def _start_socket_server():
    """Bind a Unix Domain Socket and accept connections in a daemon thread."""
    global _socket_server

    try:
        srv = _bind_uds_socket()
        if srv is None:
            print(
                "[UDS] Skipping UDS server (another instance owns the socket)",
                file=_sys.stderr,
            )
            return
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
                t = threading.Thread(
                    target=_handle_socket_client, args=(conn,), daemon=True
                )
                t.start()
            except socket.timeout:
                # Proactive watchdog: detect deleted socket file
                if not os.path.exists(SOCKET_PATH):
                    print("[UDS] Socket file missing, rebinding", file=_sys.stderr)
                    try:
                        srv.close()
                    except Exception:
                        pass
                    new_srv = _bind_uds_socket()
                    if new_srv is None:
                        print(
                            "[UDS] Another server took the socket, exiting accept loop",
                            file=_sys.stderr,
                        )
                        return
                    try:
                        srv = new_srv
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
                new_srv = _bind_uds_socket()
                if new_srv is None:
                    print(
                        "[UDS] Another server took the socket, exiting accept loop",
                        file=_sys.stderr,
                    )
                    return
                srv = new_srv
                _socket_server = srv

    t = threading.Thread(target=_accept_loop, daemon=True, name="uds-gateway")
    t.start()


def _cleanup_socket():
    """Close server socket and remove socket file on exit.

    Only unlinks the socket file if this process is the one that bound it,
    preventing session 2's exit from killing session 1's connection.
    """
    global _socket_server, _uds_shutting_down
    _uds_shutting_down = True
    if _socket_server is not None:
        try:
            _socket_server.close()
        except Exception:
            pass
        _socket_server = None
    # Only unlink if we own the socket
    if _socket_owner_pid == os.getpid():
        try:
            if os.path.exists(SOCKET_PATH):
                os.unlink(SOCKET_PATH)
        except OSError:
            pass


atexit.register(_cleanup_socket)


# ──────────────────────────────────────────────────
# SSE Health Watchdog — detect runaway threads/CPU and self-restart
# ──────────────────────────────────────────────────

_WATCHDOG_INTERVAL = 30  # seconds between checks
_WATCHDOG_CPU_THRESHOLD = 80.0  # % CPU averaged over interval
_WATCHDOG_THREAD_THRESHOLD = 20  # max active threads before alarm
_WATCHDOG_STRIKES_TO_RESTART = 3  # consecutive bad checks before restart


def _start_sse_watchdog():
    """Monitor process health and self-restart if SSE transport degrades.

    Detects: accumulated dead SSE connections causing thread buildup and CPU spin.
    Action: logs warning, then graceful self-restart via os.execv after N strikes.
    """
    import resource

    _strikes = 0
    _last_cpu = time.monotonic()
    _last_usage = resource.getrusage(resource.RUSAGE_SELF)

    def _watchdog_loop():
        nonlocal _strikes, _last_cpu, _last_usage

        while True:
            time.sleep(_WATCHDOG_INTERVAL)
            try:
                # Measure CPU usage over the interval
                now = time.monotonic()
                usage = resource.getrusage(resource.RUSAGE_SELF)
                elapsed = now - _last_cpu
                if elapsed < 1:
                    continue
                cpu_time = (usage.ru_utime - _last_usage.ru_utime) + (
                    usage.ru_stime - _last_usage.ru_stime
                )
                cpu_pct = (cpu_time / elapsed) * 100.0
                _last_cpu = now
                _last_usage = usage

                # Count active threads
                thread_count = threading.active_count()

                unhealthy = (
                    cpu_pct > _WATCHDOG_CPU_THRESHOLD
                    or thread_count > _WATCHDOG_THREAD_THRESHOLD
                )

                # Skip strike counting during model loading / init
                if _initializing or not _initialized:
                    if unhealthy:
                        _sys.stderr.write(
                            f"[WATCHDOG] Init in progress, skipping strike: "
                            f"CPU={cpu_pct:.1f}% threads={thread_count}\n"
                        )
                    _strikes = 0
                    continue

                if unhealthy:
                    _strikes += 1
                    _sys.stderr.write(
                        f"[WATCHDOG] Strike {_strikes}/{_WATCHDOG_STRIKES_TO_RESTART}: "
                        f"CPU={cpu_pct:.1f}% threads={thread_count}\n"
                    )
                else:
                    if _strikes > 0:
                        _sys.stderr.write(
                            f"[WATCHDOG] Recovered: CPU={cpu_pct:.1f}% threads={thread_count}\n"
                        )
                    _strikes = 0

                if _strikes >= _WATCHDOG_STRIKES_TO_RESTART:
                    _sys.stderr.write(
                        f"[WATCHDOG] High load: {_strikes} consecutive strikes "
                        f"(CPU={cpu_pct:.1f}% threads={thread_count}) — logging only\n"
                    )
                    with open("/tmp/memory_server_debug.log", "a") as f:
                        f.write(
                            f"[{datetime.now().isoformat()}] PID={os.getpid()} "
                            f"WATCHDOG high load: CPU={cpu_pct:.1f}% threads={thread_count}\n"
                        )
                    _strikes = 0  # reset after logging
            except Exception as e:
                _sys.stderr.write(f"[WATCHDOG] Error: {e}\n")

    t = threading.Thread(target=_watchdog_loop, daemon=True, name="sse-watchdog")
    t.start()
    _sys.stderr.write("[WATCHDOG] SSE health monitor started\n")


# ──────────────────────────────────────────────────
# Agent Coordination (agent_channel.py v2 wrapper)
# ──────────────────────────────────────────────────


@mcp.tool()
@crash_proof
def agent_coordination(
    action: str,
    title: str = "",
    description: str = "",
    created_by: str = "",
    assigned_to: str = "",
    priority: int = 5,
    tags: str = "",
    depends_on: str = "",
    required_role: str = "",
    goal: str = "",
    parent_task_id: str = "",
    task_id: str = "",
    result: str = "",
    role: str = "",
    tag: str = "",
    agent_id: str = "",
    status: str = "",
    msg_type: str = "info",
    content: str = "",
    to_agent: str = "all",
    since_minutes: int = 60,
) -> dict:
    """Unified agent task and messaging coordination.

    Actions:
      create_task   — Create a task (title, created_by required)
      list_tasks    — List tasks (optional: status, agent_id, tag)
      claim_task    — Claim next pending task (agent_id required, optional: role, tag)
      complete_task — Complete a task (task_id, result required)
      send_message  — Send a message (content required, optional: to_agent, msg_type)
      read_messages — Read recent messages (optional: agent_id, since_minutes)
    """
    _ac_path = os.path.join(os.path.dirname(os.path.abspath(__file__)))
    if _ac_path not in _sys.path:
        _sys.path.insert(0, _ac_path)
    try:
        from shared.agent_channel import (
            create_task as _ac_create,
            list_tasks as _ac_list,
            claim_next_task as _ac_claim,
            complete_task as _ac_complete,
            post_message as _ac_post,
            read_messages as _ac_read,
        )
    except ImportError as e:
        return {"error": f"agent_channel import failed: {e}"}

    action = action.strip().lower().replace("-", "_")

    if action == "create_task":
        if not title:
            return {"error": "title is required for create_task"}
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
        tid = _ac_create(
            title=title,
            description=description or "",
            created_by=created_by or "main",
            priority=priority,
            tags=tag_list,
            assigned_to=assigned_to or None,
            depends_on=depends_on or None,
            required_role=required_role or None,
            goal=goal or None,
            parent_task_id=parent_task_id or None,
            notify=bool(assigned_to),
        )
        if tid:
            return {"task_id": tid, "title": title, "status": "pending"}
        return {"error": "Failed to create task"}

    elif action == "list_tasks":
        tasks = _ac_list(
            status=status or None,
            agent_id=agent_id or None,
            tag=tag or None,
            parent_task_id=parent_task_id or None,
        )
        return {"tasks": tasks, "count": len(tasks)}

    elif action == "claim_task":
        if not agent_id:
            return {"error": "agent_id is required for claim_task"}
        task = _ac_claim(agent_id, role=role or None, tag=tag or "")
        if task:
            return {"claimed": True, "task": task}
        return {"claimed": False, "message": "No tasks available"}

    elif action == "complete_task":
        if not task_id:
            return {"error": "task_id is required for complete_task"}
        ok = _ac_complete(task_id, result or "", broadcast=True)
        return {"completed": ok, "task_id": task_id}

    elif action == "send_message":
        if not content:
            return {"error": "content is required for send_message"}
        ok = _ac_post(
            from_agent=agent_id or "main",
            msg_type=msg_type,
            content=content,
            to_agent=to_agent,
        )
        return {"sent": ok}

    elif action == "read_messages":
        import time as _ac_time

        since_ts = _ac_time.time() - (since_minutes * 60)
        msgs = _ac_read(since_ts, agent_id=agent_id or None)
        return {"messages": msgs, "count": len(msgs)}

    else:
        return {
            "error": f"Unknown action: {action}",
            "valid_actions": [
                "create_task",
                "list_tasks",
                "claim_task",
                "complete_task",
                "send_message",
                "read_messages",
            ],
        }


if __name__ == "__main__":
    # Debug log for MCP init diagnosis (added session 469)
    _dbg_log = "/tmp/memory_server_debug.log"

    # PID file guard — prevent double-launch (added session 83)
    def _check_pid_guard():
        """Check if another instance is already running. Exit if so."""
        if os.path.exists(_PID_FILE):
            try:
                with open(_PID_FILE) as f:
                    old_pid = int(f.read().strip())
                # Check if that process is still alive
                os.kill(old_pid, 0)
                # Process alive — check it's actually memory_server
                import subprocess as _sp

                cmdline = _sp.run(
                    ["ps", "-p", str(old_pid), "-o", "args="],
                    capture_output=True,
                    text=True,
                    timeout=2,
                ).stdout.strip()
                if "memory_server" in cmdline:
                    _sys.stderr.write(
                        f"[MCP] memory_server already running (PID {old_pid}). Exiting.\n"
                    )
                    with open(_dbg_log, "a") as f:
                        f.write(
                            f"[{datetime.now().isoformat()}] PID={os.getpid()} ABORTED: "
                            f"existing instance PID {old_pid} still running\n"
                        )
                    _sys.exit(0)
            except (OSError, ValueError, Exception):
                pass  # Stale PID file or dead process — safe to proceed

    def _write_pid():
        """Write current PID to file and register cleanup."""
        with open(_PID_FILE, "w") as f:
            f.write(str(os.getpid()))
        atexit.register(_remove_pid)

    def _remove_pid():
        """Remove PID file on clean exit."""
        try:
            os.remove(_PID_FILE)
        except OSError:
            pass

    _check_pid_guard()
    _write_pid()

    with open(_dbg_log, "a") as _f:
        _f.write(
            f"[{datetime.now().isoformat()}] PID={os.getpid()} args={_sys.argv} starting\n"
        )

    # Background warmup: load embedding model + LanceDB while uvicorn starts.
    # This eliminates the 80-160s cold-start timeout on first tool call.
    def _background_warmup():
        try:
            _sys.stderr.write("[WARMUP] Starting background initialization...\n")
            _ensure_initialized()
            # Run a dummy embedding to fully warm the model (JIT/kernel caches).
            # Without this, the first real search_knowledge call pays a >30s penalty.
            if _embedding_fn is not None:
                _sys.stderr.write("[WARMUP] Running dummy embedding to warm model...\n")
                _embed_text("warmup")
                _sys.stderr.write("[WARMUP] Embedding model warm\n")
            _sys.stderr.write(
                "[WARMUP] Background initialization complete — server ready\n"
            )
        except Exception as e:
            _sys.stderr.write(
                f"[WARMUP] Background init failed (will retry on first call): {e}\n"
            )

    import threading as _startup_threading

    _startup_threading.Thread(
        target=_background_warmup, daemon=True, name="warmup"
    ).start()

    _start_socket_server()
    with open(_dbg_log, "a") as _f:
        _f.write(
            f"[{datetime.now().isoformat()}] PID={os.getpid()} socket server done\n"
        )
    if _args.bootstrap_clusters:
        _bootstrap_clusters()
        _sys.exit(0)
    if _args.stdio:
        _mode = "stdio"
    elif _args.sse:
        _mode = "sse"
    else:
        _mode = "streamable-http"
    if _network_mode:
        _sys.stderr.write(
            f"[MCP] Starting {_mode} transport on {_NET_HOST}:{_args.port}\n"
        )
        _start_sse_watchdog()
    with open(_dbg_log, "a") as _f:
        _f.write(
            f"[{datetime.now().isoformat()}] PID={os.getpid()} calling mcp.run(transport={_mode})\n"
        )
    try:
        mcp.run(transport=_mode)
    except Exception as e:
        with open(_dbg_log, "a") as _f:
            import traceback

            _f.write(f"[{datetime.now().isoformat()}] PID={os.getpid()} FATAL: {e}\n")
            _f.write(traceback.format_exc() + "\n")
        _sys.stderr.write(f"[MCP] Fatal: {e}\n")
        _sys.exit(1)
