"""In-memory search result cache with TTL and invalidation.

Provides a lightweight caching layer for repeated search queries within
a session. Typical use: when Claude searches for the same concept
multiple times during a fix cycle, this avoids redundant embedding
computation (~30ms per search).

Cache is purely in-memory (no persistence). Each memory_server process
gets its own cache. TTL ensures staleness is bounded.

Usage:
    from shared.search_cache import SearchCache

    cache = SearchCache(ttl_seconds=120, max_entries=200)

    # Check cache first
    key = cache.make_key(query, top_k=15, mode="semantic")
    hit = cache.get(key)
    if hit is not None:
        return hit  # Cache hit

    # Compute result
    result = expensive_search(query)
    cache.put(key, result)

    # Invalidate on write
    cache.invalidate()
"""

import hashlib
import time
from typing import Any, Dict, Optional


class SearchCache:
    """TTL-based in-memory cache for search results."""

    def __init__(self, ttl_seconds: float = 120.0, max_entries: int = 200):
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._hits = 0
        self._misses = 0
        self._invalidations = 0

    def make_key(self, query: str, **kwargs) -> str:
        """Build a stable cache key from query + params.

        Args:
            query: Search query string
            **kwargs: Additional parameters (top_k, mode, table, etc.)

        Returns:
            16-char hex key (first 64 bits of SHA-256)
        """
        parts = [query.strip().lower()]
        for k in sorted(kwargs.keys()):
            parts.append(f"{k}={kwargs[k]}")
        raw = "|".join(parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def get(self, key: str) -> Optional[Any]:
        """Get cached result if it exists and hasn't expired.

        Returns None on miss or expiry.
        """
        entry = self._cache.get(key)
        if entry is None:
            self._misses += 1
            return None
        if time.monotonic() - entry["stored_at"] > self._ttl:
            del self._cache[key]
            self._misses += 1
            return None
        self._hits += 1
        return entry["value"]

    def put(self, key: str, value: Any) -> None:
        """Store a result in the cache.

        Evicts oldest entries if max_entries is exceeded.
        """
        # Evict if at capacity
        if len(self._cache) >= self._max_entries:
            self._evict_oldest()
        self._cache[key] = {
            "value": value,
            "stored_at": time.monotonic(),
        }

    def invalidate(self) -> None:
        """Clear the entire cache (call after remember_this or writes)."""
        self._cache.clear()
        self._invalidations += 1

    def _evict_oldest(self) -> None:
        """Remove the oldest 25% of entries."""
        if not self._cache:
            return
        entries = sorted(self._cache.items(), key=lambda kv: kv[1]["stored_at"])
        evict_count = max(1, len(entries) // 4)
        for key, _ in entries[:evict_count]:
            del self._cache[key]

    def stats(self) -> dict:
        """Return cache statistics."""
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self._hits / total if total > 0 else 0.0,
            "cached": len(self._cache),
            "max_entries": self._max_entries,
            "ttl_seconds": self._ttl,
            "invalidations": self._invalidations,
        }

    def __len__(self) -> int:
        return len(self._cache)
