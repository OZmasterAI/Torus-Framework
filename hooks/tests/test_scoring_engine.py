"""TDD tests for the scoring engine — Phase 1 of Memory v2 Layered Redesign.

Tests the pure score_result() function that replaces 6 separate scoring stages
in the monolith (keyword overlap, recency boost, tier boost, access boost,
LTP-aware scoring, composite reranker).
"""

import math
import pytest
from datetime import datetime, timezone, timedelta

from shared.scoring_engine import (
    ScoringContext,
    score_result,
    _SEARCH_ACCESS_CAP,
    _SEARCH_ACCESS_COEFF,
)


def _now_iso():
    """Return current UTC time as ISO string."""
    return datetime.now(tz=timezone.utc).isoformat()


def _ago_iso(days):
    """Return ISO timestamp for `days` ago."""
    dt = datetime.now(tz=timezone.utc) - timedelta(days=days)
    return dt.isoformat()


def _make_result(tier=1, timestamp=None, retrieval_count=0, tags="", id="mem_1"):
    """Build a minimal result dict for scoring."""
    return {
        "id": id,
        "tier": tier,
        "timestamp": timestamp or _now_iso(),
        "retrieval_count": retrieval_count,
        "tags": tags,
        "relevance": 0.8,
        "preview": "test memory content",
    }


def _make_ctx(**overrides):
    """Build a ScoringContext with sensible defaults."""
    defaults = dict(
        ltp_factors={},
        graph_scores={},
        query_tags="",
        project="test",
        server_subproject="",
        query="",
        ltp_blend=0.3,
        half_life=15.0,
    )
    defaults.update(overrides)
    return ScoringContext(**defaults)


# ── Test 1: Basic scoring range ──────────────────────────────────────────


def test_score_result_basic():
    """A T1 fresh memory with base_similarity=0.8 scores between 0.7 and 1.0."""
    result = _make_result(tier=1, timestamp=_now_iso(), retrieval_count=0)
    ctx = _make_ctx()
    score = score_result(result, base_similarity=0.8, ctx=ctx)
    assert 0.7 < score <= 1.0, f"Expected 0.7-1.0, got {score}"


# ── Test 2: Determinism ──────────────────────────────────────────────────


def test_score_deterministic():
    """Same inputs always produce the same score (within float precision)."""
    ts = _ago_iso(30)  # Far enough back that microsecond drift is negligible
    result = _make_result(tier=2, timestamp=ts, retrieval_count=5, tags="type:fix")
    ctx = _make_ctx(query_tags="type:fix")
    score1 = score_result(result, base_similarity=0.6, ctx=ctx)
    score2 = score_result(result, base_similarity=0.6, ctx=ctx)
    assert math.isclose(score1, score2, rel_tol=1e-9), (
        f"Non-deterministic: {score1} != {score2}"
    )


# ── Test 3: Access counted once ──────────────────────────────────────────


def test_access_counted_once():
    """retrieval_count=100 should add ~0.03 (capped), not triple-counted."""
    result = _make_result(tier=2, timestamp=_now_iso(), retrieval_count=100)
    ctx = _make_ctx()
    score = score_result(result, base_similarity=0.5, ctx=ctx)
    # Access boost: min(0.03, 0.008 * log1p(100)) = min(0.03, 0.037) = 0.03
    # With monolith-matching cap of 0.03, score stays conservative
    assert score < 0.95, (
        f"Score too high ({score}) — access may be counted multiple times"
    )


# ── Test 4: Tier multipliers ─────────────────────────────────────────────


def test_tier_multipliers():
    """T1 scores highest, T2 middle, T3 lowest (via multiplicative tier base)."""
    ts = _ago_iso(10)
    ctx = _make_ctx()
    s1 = score_result(_make_result(tier=1, timestamp=ts), 0.7, ctx)
    s2 = score_result(_make_result(tier=2, timestamp=ts), 0.7, ctx)
    s3 = score_result(_make_result(tier=3, timestamp=ts), 0.7, ctx)
    assert s1 > s2 > s3, f"Tier ordering violated: T1={s1}, T2={s2}, T3={s3}"


# ── Test 5: Recency bonus ────────────────────────────────────────────────


def test_recency_bonus():
    """Memories <7 days old get +0.10 recency bonus; >=7 days get 0."""
    ctx = _make_ctx()
    fresh = _make_result(tier=2, timestamp=_ago_iso(3))
    old = _make_result(tier=2, timestamp=_ago_iso(10))
    s_fresh = score_result(fresh, 0.5, ctx)
    s_old = score_result(old, 0.5, ctx)
    # Fresh should be notably higher due to recency bonus + less decay
    assert s_fresh > s_old, f"Fresh ({s_fresh}) should beat old ({s_old})"
    # Specifically test the +0.10 recency gap beyond just decay difference
    # The recency bonus should be approximately 0.10
    # We verify this by checking a very fresh memory vs 8-day-old
    very_fresh = _make_result(tier=2, timestamp=_now_iso())
    just_past = _make_result(tier=2, timestamp=_ago_iso(8))
    s_vf = score_result(very_fresh, 0.5, ctx)
    s_jp = score_result(just_past, 0.5, ctx)
    # The difference should include ~0.10 from recency bonus
    assert (s_vf - s_jp) > 0.05, f"Recency gap too small: {s_vf - s_jp}"


# ── Test 6: Project affinity ─────────────────────────────────────────────


def test_project_affinity():
    """Memory tagged with current project gets 2x multiplier, capped at 1.0."""
    ctx = _make_ctx(project="myproject")
    tagged = _make_result(
        tier=1, timestamp=_now_iso(), tags="project:myproject,type:fix"
    )
    untagged = _make_result(tier=1, timestamp=_now_iso(), tags="type:fix")
    s_tagged = score_result(tagged, 0.5, ctx)
    s_untagged = score_result(untagged, 0.5, ctx)
    assert s_tagged > s_untagged, (
        f"Project affinity not applied: {s_tagged} vs {s_untagged}"
    )
    # Score should be capped at 1.0
    s_high = score_result(tagged, 0.9, ctx)
    assert s_high <= 1.0, f"Score exceeded 1.0: {s_high}"


# ── Test 7: LTP blending ─────────────────────────────────────────────────


def test_ltp_blending():
    """Base similarity blended with LTP score at 0.3 ratio."""
    ctx = _make_ctx(ltp_factors={"mem_1": 0.5}, ltp_blend=0.3)
    result = _make_result(tier=1, timestamp=_now_iso(), id="mem_1")

    # With LTP factor 0.5 (potentiated), the LTP score component should
    # influence the final score via blending: (1-0.3)*base + 0.3*ltp_score
    s_ltp = score_result(result, 0.7, ctx)

    # Compare with no LTP (factor = 1.0, not potentiated)
    ctx_no_ltp = _make_ctx(ltp_factors={}, ltp_blend=0.3)
    s_no_ltp = score_result(result, 0.7, ctx_no_ltp)

    # The scores should differ because LTP blending changes the composite
    assert s_ltp != s_no_ltp, f"LTP blending had no effect: {s_ltp} == {s_no_ltp}"


# ── Test 8: Graph bonus capped ───────────────────────────────────────────


def test_graph_bonus_capped():
    """Graph proximity score is capped at 0.06."""
    ctx_high = _make_ctx(graph_scores={"mem_1": 0.20})
    ctx_low = _make_ctx(graph_scores={"mem_1": 0.03})
    ctx_none = _make_ctx(graph_scores={})

    result = _make_result(id="mem_1")
    s_high = score_result(result, 0.5, ctx_high)
    s_low = score_result(result, 0.5, ctx_low)
    s_none = score_result(result, 0.5, ctx_none)

    # High graph score should be capped — not much more than low
    graph_delta_high = s_high - s_none
    graph_delta_low = s_low - s_none
    assert graph_delta_high <= 0.07, (
        f"Graph bonus exceeded cap: delta={graph_delta_high}"
    )
    assert graph_delta_low <= 0.07, f"Graph bonus exceeded cap: delta={graph_delta_low}"
    assert graph_delta_high > 0, "Graph bonus should be positive"


# ── Test 9: Score always in [0, 1] ───────────────────────────────────────


def test_score_bounds():
    """Score is always clamped to [0.0, 1.0] regardless of inputs."""
    # Extreme high inputs
    result = _make_result(
        tier=1,
        timestamp=_now_iso(),
        retrieval_count=10000,
        tags="project:test,type:fix,area:backend",
    )
    ctx = _make_ctx(
        ltp_factors={"mem_1": 0.1},
        graph_scores={"mem_1": 1.0},
        query_tags="type:fix,area:backend",
        project="test",
    )
    score = score_result(result, 0.99, ctx)
    assert 0.0 <= score <= 1.0, f"Score out of bounds: {score}"

    # Very old, low tier, no signals
    old_result = _make_result(
        tier=3, timestamp=_ago_iso(365), retrieval_count=0, tags=""
    )
    ctx_empty = _make_ctx()
    score_low = score_result(old_result, 0.01, ctx_empty)
    assert 0.0 <= score_low <= 1.0, f"Score out of bounds: {score_low}"


# ── Test 10: Keyword overlap bonus ───────────────────────────────────────


def test_keyword_overlap():
    """Keyword overlap with query terms adds a small bonus."""
    ctx = _make_ctx(query="lancedb embeddings search")
    result_match = _make_result(tags="lancedb,embeddings")
    result_match["preview"] = "lancedb vector embeddings for search"
    result_no_match = _make_result(tags="unrelated")
    result_no_match["preview"] = "something completely different"

    s_match = score_result(result_match, 0.5, ctx)
    s_no_match = score_result(result_no_match, 0.5, ctx)
    assert s_match > s_no_match, (
        f"Keyword match ({s_match}) should score higher than no match ({s_no_match})"
    )


# ── Test 11: Project affinity exactly 2x (not 4x double-apply bug) ────


def test_project_affinity_exactly_2x():
    """Project-matching memory gets exactly 2x boost, not 4x (bug: double application)."""
    ctx = _make_ctx(project="myproject")
    result_with = _make_result(tier=2, timestamp=_ago_iso(10), tags="project:myproject")
    result_without = _make_result(tier=2, timestamp=_ago_iso(10), tags="")

    s_with = score_result(result_with, 0.4, ctx)
    s_without = score_result(result_without, 0.4, ctx)

    # The ratio should be approximately 2.0 (project_mult), not 4.0
    ratio = s_with / s_without if s_without > 0 else float("inf")
    assert 1.8 < ratio < 2.3, f"Project boost ratio should be ~2.0, got {ratio}"


# ── Test 12: Access boost uses monolith-matching coefficients ────────


def test_access_boost_monolith_cap():
    """Access boost capped at 0.03 (monolith), not 0.20 (memory_decay replay)."""
    assert _SEARCH_ACCESS_CAP == 0.03, f"Cap should be 0.03, got {_SEARCH_ACCESS_CAP}"
    assert _SEARCH_ACCESS_COEFF == 0.008, (
        f"Coeff should be 0.008, got {_SEARCH_ACCESS_COEFF}"
    )

    # retrieval_count=100: 0.008 * log1p(100) = 0.008 * 4.615 = 0.0369 → capped at 0.03
    result_high = _make_result(tier=2, timestamp=_ago_iso(10), retrieval_count=100)
    result_zero = _make_result(tier=2, timestamp=_ago_iso(10), retrieval_count=0)
    ctx = _make_ctx()
    s_high = score_result(result_high, 0.5, ctx)
    s_zero = score_result(result_zero, 0.5, ctx)
    access_delta = s_high - s_zero
    assert access_delta <= 0.035, (
        f"Access delta {access_delta} exceeds cap 0.03 — regression"
    )
    assert access_delta > 0, "Access boost should be positive for rc=100"


# ── Test 13: Subproject 1.5x boost ──────────────────────────────────


def test_subproject_boost():
    """Subproject matching adds 1.5x multiplier on top of project 2.0x."""
    ctx = _make_ctx(project="torus", server_subproject="hooks")
    result_both = _make_result(
        tier=2, timestamp=_ago_iso(10), tags="project:torus,subproject:hooks,type:fix"
    )
    result_proj_only = _make_result(
        tier=2, timestamp=_ago_iso(10), tags="project:torus,type:fix"
    )
    result_none = _make_result(tier=2, timestamp=_ago_iso(10), tags="type:fix")

    s_both = score_result(result_both, 0.3, ctx)
    s_proj = score_result(result_proj_only, 0.3, ctx)
    s_none = score_result(result_none, 0.3, ctx)

    # project only: 2.0x, project+subproject: 3.0x
    proj_ratio = s_proj / s_none if s_none > 0 else float("inf")
    both_ratio = s_both / s_none if s_none > 0 else float("inf")
    assert 1.8 < proj_ratio < 2.3, f"Project ratio should be ~2.0, got {proj_ratio}"
    assert 2.7 < both_ratio < 3.3, f"Both ratio should be ~3.0, got {both_ratio}"


# ── Test 14: query_tags derive function ─────────────────────────────


def test_derive_query_tags():
    """_derive_query_tags extracts matching tags from result set."""
    from shared.search_pipeline import _derive_query_tags

    results = [
        {"tags": "type:fix,area:backend,priority:high"},
        {"tags": "type:learning,area:frontend"},
        {"tags": "type:error,outcome:failed"},
    ]

    # "fix backend" → "fix" (3 chars, skipped), "backend" matches "area:backend"
    tags = _derive_query_tags("fix backend error", results)
    assert "area:backend" in tags, f"Should find area:backend, got: {tags}"
    assert "type:error" in tags, f"Should find type:error, got: {tags}"

    # Words ≤3 chars are skipped
    tags_short = _derive_query_tags("fix err", results)
    assert tags_short == "", f"Short words should be skipped, got: {tags_short}"

    # Empty inputs
    assert _derive_query_tags("", results) == ""
    assert _derive_query_tags("something", []) == ""


def test_query_tags_affect_scoring():
    """Non-empty query_tags should increase score for matching results."""
    ts = _ago_iso(10)
    result = _make_result(tier=2, timestamp=ts, tags="type:fix,area:backend")

    ctx_with = _make_ctx(query_tags="type:fix,area:backend")
    ctx_without = _make_ctx(query_tags="")

    s_with = score_result(result, 0.5, ctx_with)
    s_without = score_result(result, 0.5, ctx_without)
    assert s_with > s_without, f"query_tags should boost score: {s_with} vs {s_without}"
