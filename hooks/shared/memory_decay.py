"""Memory Decay and Relevance Scoring for the Torus Memory System.

Provides time-decay relevance scoring for LanceDB memory entries.
All functions are pure — no side effects, no I/O.

Public API:
    from shared.memory_decay import (
        calculate_relevance_score,   # Score a single memory entry (0.0–1.0)
        rank_memories,               # Sort a list by relevance descending
        identify_stale_memories,     # Return entries below threshold
    )
"""

import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Tier base scores (T1=critical/curated, T2=standard, T3=auto-captured)
TIER_BASE: Dict[int, float] = {1: 1.0, 2: 0.7, 3: 0.4}
TIER_BASE_DEFAULT = 0.4  # fallback for unknown tiers

# Half-life for exponential decay (days). 45 days → ~50% score at 45d, ~6% at 180d.
DEFAULT_HALF_LIFE_DAYS: float = 45.0

# Caps and weights for individual score components
_MAX_ACCESS_BOOST = 0.20    # log-scaled access boost ceiling
_RECENCY_BOOST = 0.10       # flat bonus for memories < 7 days old
_RECENCY_WINDOW_DAYS = 7
_MAX_TAG_BONUS = 0.15       # bonus for matching query context tags


def _parse_timestamp(ts: str) -> Optional[datetime]:
    """Parse ISO timestamp string to UTC datetime; return None on failure."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError):
        return None


def _age_days(timestamp_str: str) -> float:
    """Return age of a memory in days; 0.0 on parse failure (treat as fresh)."""
    now = datetime.now(tz=timezone.utc)
    dt = _parse_timestamp(timestamp_str)
    if dt is None:
        return 0.0
    return max(0.0, (now - dt).total_seconds() / 86400.0)


def _time_decay_factor(age_days: float, half_life: float = DEFAULT_HALF_LIFE_DAYS) -> float:
    """Exponential decay: 1.0 at age=0, 0.5 at age=half_life."""
    return math.pow(0.5, age_days / half_life)


def _access_boost(retrieval_count: int) -> float:
    """Log-scaled boost for frequently accessed memories, capped at _MAX_ACCESS_BOOST."""
    return min(_MAX_ACCESS_BOOST, 0.05 * math.log1p(max(0, int(retrieval_count or 0))))


def _tag_relevance_bonus(entry_tags: str, query_context: Optional[str]) -> float:
    """Bonus for tag overlap between memory and query context, up to _MAX_TAG_BONUS."""
    if not query_context or not entry_tags:
        return 0.0
    context_tags = {t.strip().lower() for t in query_context.split(",") if t.strip()}
    memory_tags = {t.strip().lower() for t in entry_tags.split(",") if t.strip()}
    if not context_tags or not memory_tags:
        return 0.0
    overlap = len(context_tags & memory_tags)
    return min(_MAX_TAG_BONUS, overlap * (_MAX_TAG_BONUS / max(1, len(context_tags))))


def calculate_relevance_score(
    memory_entry: Dict[str, Any],
    query_context: Optional[str] = None,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
) -> float:
    """Score a memory entry's current relevance (0.0–1.0).

    Components:
    - Base score from tier (T1=1.0, T2=0.7, T3=0.4)
    - Exponential time decay (half-life configurable, default 45 days)
    - Access boost: log-scaled bonus for high retrieval_count (max +0.20)
    - Recency boost: flat +0.10 for memories < 7 days old
    - Tag relevance: bonus if entry tags overlap with query_context (max +0.15)

    Args:
        memory_entry: Dict with keys: tier, timestamp, retrieval_count, tags
        query_context: Comma-separated tags describing the current query context
        half_life_days: Days until base score halves (default 45)

    Returns:
        float in [0.0, 1.0]
    """
    tier = int(memory_entry.get("tier") or 3)
    base = TIER_BASE.get(tier, TIER_BASE_DEFAULT)

    age = _age_days(str(memory_entry.get("timestamp") or ""))
    decay = _time_decay_factor(age, half_life_days)

    access = _access_boost(int(memory_entry.get("retrieval_count") or 0))
    recency = _RECENCY_BOOST if age < _RECENCY_WINDOW_DAYS else 0.0
    tag_bonus = _tag_relevance_bonus(
        str(memory_entry.get("tags") or ""), query_context
    )

    return max(0.0, min(1.0, base * decay + access + recency + tag_bonus))


def rank_memories(
    memories: List[Dict[str, Any]],
    query_context: Optional[str] = None,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
) -> List[Dict[str, Any]]:
    """Return memories sorted by relevance score descending.

    Each returned dict is augmented with a '_relevance_score' key.
    The original list is not modified.

    Args:
        memories: List of memory entry dicts
        query_context: Comma-separated tags for tag relevance scoring
        half_life_days: Decay half-life in days

    Returns:
        New list sorted by relevance descending
    """
    scored = []
    for m in memories:
        entry = dict(m)
        entry["_relevance_score"] = calculate_relevance_score(m, query_context, half_life_days)
        scored.append(entry)
    scored.sort(key=lambda x: x["_relevance_score"], reverse=True)
    return scored


def identify_stale_memories(
    memories: List[Dict[str, Any]],
    threshold: float = 0.2,
    query_context: Optional[str] = None,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
) -> List[Dict[str, Any]]:
    """Return memories whose relevance score falls below threshold.

    These are candidates for archival or quarantine.

    Args:
        memories: List of memory entry dicts
        threshold: Relevance cutoff (default 0.2)
        query_context: Optional query context for tag scoring
        half_life_days: Decay half-life in days

    Returns:
        List of memory dicts (with '_relevance_score') below threshold
    """
    stale = []
    for m in memories:
        score = calculate_relevance_score(m, query_context, half_life_days)
        if score < threshold:
            entry = dict(m)
            entry["_relevance_score"] = score
            stale.append(entry)
    return stale
