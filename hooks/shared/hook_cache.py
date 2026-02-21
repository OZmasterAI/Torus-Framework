"""Lightweight hook invocation cache for the Torus framework.

Provides three layers of caching to avoid redundant work within a single
hook invocation batch (each hook runs as its own process, so caches are
per-process / per-invocation):

1. Module cache  — imported gate modules, valid for the process lifetime
                   (gate files don't change mid-session under normal use)
2. State cache   — state file reads, with a configurable TTL (default 2 s)
                   State changes between tool calls but not within a single
                   gate dispatch, so a short TTL is safe.
3. Result cache  — GateResult values for identical (gate, tool, input_hash)
                   within a 1-second window.  Prevents duplicate work on
                   retried tool calls.

All caches also track hit/miss/eviction counts via cache_stats().

Usage::

    from shared.hook_cache import (
        get_cached_module,
        get_cached_state,
        set_cached_state,
        get_cached_result,
        set_cached_result,
        cache_stats,
        clear_cache,
    )

Thread-safety: NOT thread-safe. Each hook invocation is a single-threaded
process, so no locking is needed. Do not share a cache across threads.
"""

import importlib
import time
from typing import Optional

# ---------------------------------------------------------------------------
# Internal storage — module-level globals (per-process)
# ---------------------------------------------------------------------------

# Module cache: module_name -> module object
_module_cache: dict = {}

# State cache: session_id -> {"state": dict, "fetched_at": float}
_state_cache: dict = {}

# Result cache: (gate_name, tool_name, input_hash) -> {"result": GateResult, "stored_at": float}
_result_cache: dict = {}

# Stats counters
_stats: dict = {
    "module_hits": 0,
    "module_misses": 0,
    "state_hits": 0,
    "state_misses": 0,
    "state_evictions": 0,
    "result_hits": 0,
    "result_misses": 0,
    "result_evictions": 0,
}

# TTL constants (seconds, using time.monotonic())
_DEFAULT_STATE_TTL_S: float = 2.0       # 2 000 ms
_DEFAULT_RESULT_TTL_S: float = 1.0      # 1 000 ms


# ---------------------------------------------------------------------------
# 1. Module cache
# ---------------------------------------------------------------------------

def get_cached_module(module_name: str):
    """Import and cache a module by dotted name.

    On the first call the module is imported via importlib and stored.
    Subsequent calls within the same process return the cached object
    without any import overhead.

    Args:
        module_name: Dotted module path, e.g. ``"gates.gate_01_read_before_edit"``.

    Returns:
        The imported module object.

    Raises:
        ImportError: If the module cannot be imported (propagated as-is).
    """
    if module_name in _module_cache:
        _stats["module_hits"] += 1
        return _module_cache[module_name]

    _stats["module_misses"] += 1
    mod = importlib.import_module(module_name)
    _module_cache[module_name] = mod
    return mod


def invalidate_module(module_name: str) -> bool:
    """Remove a single module from the cache (e.g. after hot-reload).

    Returns True if the module was present and removed, False otherwise.
    """
    if module_name in _module_cache:
        del _module_cache[module_name]
        return True
    return False


# ---------------------------------------------------------------------------
# 2. State cache
# ---------------------------------------------------------------------------

def get_cached_state(session_id: str, ttl_ms: int = 2000) -> Optional[dict]:
    """Return a cached state dict if one exists and is within the TTL.

    This function does NOT read the state file itself — it only consults
    the in-memory cache.  Callers are responsible for populating the cache
    via ``set_cached_state`` after performing the actual disk read.

    Args:
        session_id: The session identifier used as the cache key.
        ttl_ms:     Maximum age of a cached entry in milliseconds.
                    Defaults to 2 000 ms (2 seconds).

    Returns:
        The cached state dict, or ``None`` if absent or expired.
    """
    entry = _state_cache.get(session_id)
    if entry is None:
        _stats["state_misses"] += 1
        return None

    ttl_s = ttl_ms / 1000.0
    age = time.monotonic() - entry["fetched_at"]
    if age > ttl_s:
        _stats["state_evictions"] += 1
        del _state_cache[session_id]
        return None

    _stats["state_hits"] += 1
    return entry["state"]


def set_cached_state(session_id: str, state: dict) -> None:
    """Store a freshly-read state dict in the cache.

    Overwrites any existing entry for this session_id.

    Args:
        session_id: The session identifier used as the cache key.
        state:      The state dict to cache (stored by reference — do not
                    mutate after passing in if you need a stable snapshot).
    """
    _state_cache[session_id] = {
        "state": state,
        "fetched_at": time.monotonic(),
    }


def invalidate_state(session_id: str) -> bool:
    """Remove a single session's state from the cache.

    Useful after ``save_state`` so the next read fetches fresh data.

    Returns True if the entry was present and removed, False otherwise.
    """
    if session_id in _state_cache:
        del _state_cache[session_id]
        return True
    return False


# ---------------------------------------------------------------------------
# 3. Result cache
# ---------------------------------------------------------------------------

def get_cached_result(gate_name: str, tool_name: str, input_hash: str):
    """Return a cached GateResult if one exists within the 1-second window.

    Args:
        gate_name:  Short gate identifier, e.g. ``"gate_01_read_before_edit"``.
        tool_name:  Claude Code tool name, e.g. ``"Edit"``.
        input_hash: A short hash of the tool input (caller provides this).
                    Use ``hashlib.md5(json.dumps(tool_input, sort_keys=True).encode()).hexdigest()[:16]``
                    or any stable digest.

    Returns:
        The cached ``GateResult``, or ``None`` if absent or expired.
    """
    key = (gate_name, tool_name, input_hash)
    entry = _result_cache.get(key)
    if entry is None:
        _stats["result_misses"] += 1
        return None

    age = time.monotonic() - entry["stored_at"]
    if age > _DEFAULT_RESULT_TTL_S:
        _stats["result_evictions"] += 1
        del _result_cache[key]
        return None

    _stats["result_hits"] += 1
    return entry["result"]


def set_cached_result(gate_name: str, tool_name: str, input_hash: str, result) -> None:
    """Store a GateResult in the result cache.

    Args:
        gate_name:  Short gate identifier.
        tool_name:  Claude Code tool name.
        input_hash: A short hash of the tool input.
        result:     A ``GateResult`` instance.
    """
    key = (gate_name, tool_name, input_hash)
    _result_cache[key] = {
        "result": result,
        "stored_at": time.monotonic(),
    }


def invalidate_result(gate_name: str, tool_name: str, input_hash: str) -> bool:
    """Remove a specific result entry from the cache.

    Returns True if the entry was present and removed, False otherwise.
    """
    key = (gate_name, tool_name, input_hash)
    if key in _result_cache:
        del _result_cache[key]
        return True
    return False


# ---------------------------------------------------------------------------
# 4. Cache stats
# ---------------------------------------------------------------------------

def cache_stats() -> dict:
    """Return a snapshot of all hit/miss/eviction counters.

    Returns a new dict so callers cannot accidentally mutate the live stats.

    Example return value::

        {
            "module_hits": 12,
            "module_misses": 3,
            "module_cached": 3,
            "state_hits": 8,
            "state_misses": 2,
            "state_evictions": 1,
            "state_cached": 1,
            "result_hits": 5,
            "result_misses": 4,
            "result_evictions": 0,
            "result_cached": 4,
        }
    """
    return {
        **_stats,
        "module_cached": len(_module_cache),
        "state_cached": len(_state_cache),
        "result_cached": len(_result_cache),
    }


# ---------------------------------------------------------------------------
# 5. Full reset
# ---------------------------------------------------------------------------

def clear_cache() -> None:
    """Clear all three caches and reset all counters.

    Useful in tests or when an external event makes all cached data stale
    (e.g. a gate file reload or session reset).
    """
    _module_cache.clear()
    _state_cache.clear()
    _result_cache.clear()
    for key in list(_stats.keys()):
        _stats[key] = 0


# ---------------------------------------------------------------------------
# Convenience: evict all expired entries without clearing live data
# ---------------------------------------------------------------------------

def evict_expired(state_ttl_ms: int = 2000) -> dict:
    """Scan all caches and evict entries that have exceeded their TTL.

    Returns counts of evicted entries per cache layer::

        {"state": 2, "result": 1}

    This is provided for monitoring/debugging; normal use does not require
    explicit eviction because ``get_cached_state`` and ``get_cached_result``
    already perform lazy eviction on access.
    """
    now = time.monotonic()
    state_ttl_s = state_ttl_ms / 1000.0
    evicted = {"state": 0, "result": 0}

    expired_state = [sid for sid, entry in _state_cache.items()
                     if now - entry["fetched_at"] > state_ttl_s]
    for sid in expired_state:
        del _state_cache[sid]
        _stats["state_evictions"] += 1
        evicted["state"] += 1

    expired_result = [key for key, entry in _result_cache.items()
                      if now - entry["stored_at"] > _DEFAULT_RESULT_TTL_S]
    for key in expired_result:
        del _result_cache[key]
        _stats["result_evictions"] += 1
        evicted["result"] += 1

    return evicted
