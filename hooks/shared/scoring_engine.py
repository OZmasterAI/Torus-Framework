"""Scoring Engine — Layer 2 of the Memory v2 Layered Redesign.

Single composite scorer that replaces 6 separate scoring stages:
  1. _rerank_keyword_overlap()
  2. _apply_recency_boost()
  3. _apply_tier_boost()
  4. _apply_access_boost()
  5. LTP-aware scoring block
  6. _rerank_composite()

All signals are computed exactly once and combined in one pass.
Pure function — no I/O, no side effects, fully unit-testable.

Public API:
    from shared.scoring_engine import ScoringContext, score_result
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional

from shared.memory_decay import (
    TIER_BASE,
    TIER_BASE_DEFAULT,
    DEFAULT_HALF_LIFE_DAYS,
    _age_days,
    _time_decay_factor,
    _access_boost,
    _tag_relevance_bonus,
    _RECENCY_BOOST,
    _RECENCY_WINDOW_DAYS,
    _MAX_ACCESS_BOOST,
    _MAX_TAG_BONUS,
)

# Graph proximity cap (from _rerank_composite)
_MAX_GRAPH_BONUS = 0.06

# Keyword overlap weight (from _rerank_keyword_overlap)
_KEYWORD_BOOST_WEIGHT = 0.05

# Stopwords for keyword matching (from memory_server.py)
_STOPWORDS = {"the", "a", "an", "is", "it", "to", "in", "of", "and", "for"}


@dataclass
class ScoringContext:
    """All external signals needed for scoring, gathered once per search."""

    ltp_factors: Dict[str, float]  # id -> decay factor (1.0/0.5/0.33/0.1)
    graph_scores: Dict[str, float]  # id -> graph proximity score
    query_tags: str  # comma-separated query context tags
    project: str  # current project name
    query: str = ""  # raw query string for keyword overlap
    ltp_blend: float = 0.3  # from AdaptiveWeights
    half_life: float = DEFAULT_HALF_LIFE_DAYS  # decay half-life


def _keyword_overlap_bonus(preview: str, tags: str, query: str) -> float:
    """Keyword overlap between query terms and result text.

    Matches _rerank_keyword_overlap logic: boost_weight * (matched/total).
    """
    if not query:
        return 0.0
    terms = [w.lower() for w in query.split() if w.lower() not in _STOPWORDS]
    if not terms:
        return 0.0
    text = (preview + " " + tags).lower()
    matched = sum(1 for t in terms if t in text)
    if matched == 0:
        return 0.0
    return _KEYWORD_BOOST_WEIGHT * (matched / len(terms))


def score_result(
    result: dict,
    base_similarity: float,
    ctx: ScoringContext,
) -> float:
    """Single composite relevance score. All signals, one pass, one sort.

    Replaces the 6 sequential scoring stages in the monolith. Each signal
    is computed exactly once (no double/triple counting).

    Args:
        result: Memory result dict with keys: id, tier, timestamp,
                retrieval_count, tags, preview
        base_similarity: Raw vector similarity from LanceDB (0.0-1.0)
        ctx: ScoringContext with LTP factors, graph scores, etc.

    Returns:
        float in [0.0, 1.0] — composite relevance score
    """
    mem_id = result.get("id", "")

    # ── Tier (multiplicative base — once) ──
    tier = int(result.get("tier") or 3)
    tier_mult = TIER_BASE.get(tier, TIER_BASE_DEFAULT)

    # ── Time decay (hybrid exp+power-law — once) ──
    age = _age_days(str(result.get("timestamp") or ""))
    ltp_factor = ctx.ltp_factors.get(mem_id, 1.0)
    potentiated = ltp_factor < 1.0
    decay = _time_decay_factor(age, ctx.half_life, potentiated=potentiated)

    # Scale decay further by LTP factor for full 4-level gradation
    if potentiated and ltp_factor < 0.5:
        decay = decay ** (ltp_factor / 0.5)

    # ── LTP blending ──
    # ltp_score = tier_base * decay (from calculate_relevance_score)
    ltp_score = tier_mult * decay
    blended = base_similarity * (1 - ctx.ltp_blend) + ltp_score * ctx.ltp_blend

    # ── Additive signals (each computed exactly once) ──
    retrieval_count = int(result.get("retrieval_count") or 0)
    access = _access_boost(retrieval_count)
    recency = _RECENCY_BOOST if age < _RECENCY_WINDOW_DAYS else 0.0
    tag_bonus = _tag_relevance_bonus(str(result.get("tags") or ""), ctx.query_tags)
    graph_bonus = min(_MAX_GRAPH_BONUS, ctx.graph_scores.get(mem_id, 0.0))
    keyword_bonus = _keyword_overlap_bonus(
        result.get("preview", ""), result.get("tags", ""), ctx.query
    )

    # ── Project affinity (multiplicative) ──
    project_mult = 1.0
    tags_str = result.get("tags", "")
    if ctx.project and f"project:{ctx.project}" in tags_str:
        project_mult = 2.0

    composite = (
        blended + access + recency + tag_bonus + graph_bonus + keyword_bonus
    ) * project_mult

    return max(0.0, min(1.0, composite))
