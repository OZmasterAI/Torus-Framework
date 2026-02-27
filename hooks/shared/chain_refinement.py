"""Causal Chain Auto-Refinement for the Torus self-healing framework.

Analyzes fix_outcomes data (from memory's causal chain system) to detect
patterns of repeated failures, ineffective strategies, and improvement
opportunities. Suggests refined approaches when the same error recurs.

Design:
- Pure functions over outcome data (no I/O, no side effects in core logic)
- Integrates with memory's fix_outcomes table for historical data
- Fail-open: all public functions return empty/neutral on error

Public API:
    analyze_outcomes(outcomes)          -> ChainAnalysis
    detect_recurring_failures(outcomes) -> List[RecurringPattern]
    suggest_refinement(error, outcomes) -> Optional[Refinement]
    get_strategy_effectiveness(outcomes) -> Dict[str, StrategyStats]
    compute_chain_health(outcomes)      -> ChainHealth
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ── Data containers ──────────────────────────────────────────────────────

@dataclass
class StrategyStats:
    """Aggregated stats for a single fix strategy.

    Attributes:
        strategy:     Name of the strategy.
        attempts:     Number of times this strategy was tried.
        successes:    Number of successful outcomes.
        failures:     Number of failed outcomes.
        success_rate: Fraction of attempts that succeeded.
        avg_attempts_to_success: Average chain length before success.
        errors_addressed: Set of unique error patterns addressed.
    """
    strategy: str
    attempts: int = 0
    successes: int = 0
    failures: int = 0
    success_rate: float = 0.0
    avg_attempts_to_success: float = 0.0
    errors_addressed: int = 0


@dataclass
class RecurringPattern:
    """A recurring failure pattern detected across outcomes.

    Attributes:
        error_pattern: The normalized error string.
        occurrence_count: How many times this error appeared.
        strategies_tried: List of strategies attempted.
        best_strategy: Strategy with highest success rate, if any.
        best_success_rate: Success rate of the best strategy.
        is_chronic: True if failure rate > 70% across all attempts.
    """
    error_pattern: str
    occurrence_count: int = 0
    strategies_tried: List[str] = field(default_factory=list)
    best_strategy: str = ""
    best_success_rate: float = 0.0
    is_chronic: bool = False


@dataclass
class Refinement:
    """A suggested refinement for handling a specific error.

    Attributes:
        error_pattern: The error being addressed.
        current_strategy: The strategy currently being used.
        suggested_strategy: The recommended alternative.
        reason: Human-readable explanation.
        confidence: How confident the suggestion is (0.0-1.0).
        evidence: Supporting data points.
    """
    error_pattern: str
    current_strategy: str
    suggested_strategy: str
    reason: str
    confidence: float
    evidence: List[str] = field(default_factory=list)


@dataclass
class ChainHealth:
    """Overall health metrics for the causal chain system.

    Attributes:
        total_chains: Total fix chains recorded.
        overall_success_rate: Global success rate.
        chronic_failures: Number of error patterns with >70% failure.
        strategy_diversity: Number of unique strategies used.
        improvement_trend: "improving", "declining", or "stable".
        health_score: 0-100 composite score.
        recommendations: List of actionable suggestions.
    """
    total_chains: int = 0
    overall_success_rate: float = 0.0
    chronic_failures: int = 0
    strategy_diversity: int = 0
    improvement_trend: str = "stable"
    health_score: float = 50.0
    recommendations: List[str] = field(default_factory=list)


# ── Constants ────────────────────────────────────────────────────────────

# An error pattern recurring more than this many times is "recurring"
MIN_RECURRENCE = 3

# A strategy with success rate below this is "ineffective"
INEFFECTIVE_THRESHOLD = 0.3

# An error pattern with failure rate above this is "chronic"
CHRONIC_FAILURE_THRESHOLD = 0.7

# Minimum attempts for a strategy to have reliable stats
MIN_ATTEMPTS_FOR_STATS = 3

# Strategy improvement must be at least this much better
MIN_IMPROVEMENT_DELTA = 0.15


# ── Outcome parsing ─────────────────────────────────────────────────────

def _normalize_error(error: str) -> str:
    """Normalize an error string for grouping.

    Strips file paths, line numbers, and timestamps to group
    semantically equivalent errors together.
    """
    if not error or not isinstance(error, str):
        return ""
    import re
    # Remove file paths
    normalized = re.sub(r'/[\w/.]+\.py', '<file>', error)
    # Remove line numbers
    normalized = re.sub(r'line \d+', 'line N', normalized)
    # Remove timestamps
    normalized = re.sub(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}', '<ts>', normalized)
    # Remove hex addresses
    normalized = re.sub(r'0x[0-9a-fA-F]+', '<addr>', normalized)
    # Collapse whitespace
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    return normalized.lower()


def _extract_outcome_fields(outcome: dict) -> dict:
    """Extract relevant fields from a fix_outcome entry.

    Handles both the LanceDB format and the dict format.
    """
    if not isinstance(outcome, dict):
        return {}

    return {
        "error": outcome.get("error_text", outcome.get("error", "")),
        "strategy": outcome.get("strategy", outcome.get("strategy_name", "")),
        "result": outcome.get("result", outcome.get("outcome", "")),
        "chain_id": outcome.get("chain_id", ""),
        "timestamp": outcome.get("timestamp", ""),
    }


# ── Core analysis ────────────────────────────────────────────────────────

def get_strategy_effectiveness(
    outcomes: List[dict],
) -> Dict[str, StrategyStats]:
    """Compute per-strategy effectiveness metrics.

    Args:
        outcomes: List of fix_outcome dicts from memory.

    Returns:
        Dict mapping strategy name -> StrategyStats.
    """
    strategy_data: Dict[str, dict] = {}

    for outcome in outcomes:
        fields = _extract_outcome_fields(outcome)
        strategy = fields.get("strategy", "")
        result = fields.get("result", "")
        error = fields.get("error", "")

        if not strategy:
            continue

        if strategy not in strategy_data:
            strategy_data[strategy] = {
                "attempts": 0,
                "successes": 0,
                "failures": 0,
                "errors": set(),
                "chain_lengths": [],
            }

        data = strategy_data[strategy]
        data["attempts"] += 1
        data["errors"].add(_normalize_error(error))

        if result in ("success", "resolved", "fixed"):
            data["successes"] += 1
        elif result in ("failure", "failed", "unresolved"):
            data["failures"] += 1

    stats: Dict[str, StrategyStats] = {}
    for strategy, data in strategy_data.items():
        attempts = data["attempts"]
        successes = data["successes"]
        success_rate = successes / max(attempts, 1)

        stats[strategy] = StrategyStats(
            strategy=strategy,
            attempts=attempts,
            successes=successes,
            failures=data["failures"],
            success_rate=round(success_rate, 4),
            errors_addressed=len(data["errors"]),
        )

    return stats


def detect_recurring_failures(
    outcomes: List[dict],
    min_recurrence: int = MIN_RECURRENCE,
) -> List[RecurringPattern]:
    """Find error patterns that recur across multiple fix chains.

    Args:
        outcomes: List of fix_outcome dicts.
        min_recurrence: Minimum occurrences to flag (default 3).

    Returns:
        List of RecurringPattern objects, sorted by occurrence count descending.
    """
    error_data: Dict[str, dict] = {}

    for outcome in outcomes:
        fields = _extract_outcome_fields(outcome)
        error = _normalize_error(fields.get("error", ""))
        strategy = fields.get("strategy", "")
        result = fields.get("result", "")

        if not error:
            continue

        if error not in error_data:
            error_data[error] = {
                "count": 0,
                "strategies": {},
                "total_successes": 0,
                "total_attempts": 0,
            }

        data = error_data[error]
        data["count"] += 1
        data["total_attempts"] += 1

        if strategy:
            if strategy not in data["strategies"]:
                data["strategies"][strategy] = {"attempts": 0, "successes": 0}
            data["strategies"][strategy]["attempts"] += 1

            if result in ("success", "resolved", "fixed"):
                data["strategies"][strategy]["successes"] += 1
                data["total_successes"] += 1

    patterns = []
    for error, data in error_data.items():
        if data["count"] < min_recurrence:
            continue

        # Find best strategy
        best_strategy = ""
        best_rate = 0.0
        for strat, strat_data in data["strategies"].items():
            rate = strat_data["successes"] / max(strat_data["attempts"], 1)
            if rate > best_rate:
                best_rate = rate
                best_strategy = strat

        failure_rate = 1.0 - (data["total_successes"] / max(data["total_attempts"], 1))

        patterns.append(RecurringPattern(
            error_pattern=error,
            occurrence_count=data["count"],
            strategies_tried=sorted(data["strategies"].keys()),
            best_strategy=best_strategy,
            best_success_rate=round(best_rate, 4),
            is_chronic=failure_rate > CHRONIC_FAILURE_THRESHOLD,
        ))

    patterns.sort(key=lambda p: p.occurrence_count, reverse=True)
    return patterns


def suggest_refinement(
    error: str,
    outcomes: List[dict],
    current_strategy: str = "",
) -> Optional[Refinement]:
    """Suggest a better strategy for handling a specific error.

    Looks at historical outcomes for similar errors and recommends
    the strategy with the highest success rate if it's meaningfully
    better than the current one.

    Args:
        error: The error text to find a refinement for.
        outcomes: Historical fix_outcome data.
        current_strategy: The strategy currently being considered.

    Returns:
        A Refinement object if a better approach exists, None otherwise.
    """
    normalized_error = _normalize_error(error)
    if not normalized_error:
        return None

    # Group outcomes by strategy for this error pattern
    strategy_results: Dict[str, dict] = {}

    for outcome in outcomes:
        fields = _extract_outcome_fields(outcome)
        outcome_error = _normalize_error(fields.get("error", ""))
        strategy = fields.get("strategy", "")
        result = fields.get("result", "")

        # Check if this outcome is for a similar error
        if not strategy or not outcome_error:
            continue

        # Simple similarity: shared words
        error_words = set(normalized_error.split())
        outcome_words = set(outcome_error.split())
        if len(error_words) == 0:
            continue
        overlap = len(error_words & outcome_words) / len(error_words)
        if overlap < 0.5:
            continue

        if strategy not in strategy_results:
            strategy_results[strategy] = {"attempts": 0, "successes": 0}

        strategy_results[strategy]["attempts"] += 1
        if result in ("success", "resolved", "fixed"):
            strategy_results[strategy]["successes"] += 1

    if not strategy_results:
        return None

    # Find best alternative strategy
    current_rate = 0.0
    if current_strategy and current_strategy in strategy_results:
        data = strategy_results[current_strategy]
        current_rate = data["successes"] / max(data["attempts"], 1)

    best_alt = ""
    best_alt_rate = 0.0
    for strat, data in strategy_results.items():
        if strat == current_strategy:
            continue
        if data["attempts"] < MIN_ATTEMPTS_FOR_STATS:
            continue
        rate = data["successes"] / max(data["attempts"], 1)
        if rate > best_alt_rate:
            best_alt_rate = rate
            best_alt = strat

    if not best_alt:
        return None

    improvement = best_alt_rate - current_rate
    if improvement < MIN_IMPROVEMENT_DELTA:
        return None

    confidence = min(1.0, improvement / 0.5)  # Scale: 0.15->0.3, 0.5->1.0
    evidence = []
    alt_data = strategy_results[best_alt]
    evidence.append(f"{best_alt}: {alt_data['successes']}/{alt_data['attempts']} succeeded")
    if current_strategy and current_strategy in strategy_results:
        cur_data = strategy_results[current_strategy]
        evidence.append(f"{current_strategy}: {cur_data['successes']}/{cur_data['attempts']} succeeded")

    return Refinement(
        error_pattern=normalized_error,
        current_strategy=current_strategy,
        suggested_strategy=best_alt,
        reason=(
            f"{best_alt} has {best_alt_rate:.0%} success rate vs "
            f"{current_rate:.0%} for {current_strategy or 'current approach'} "
            f"on similar errors (+{improvement:.0%} improvement)"
        ),
        confidence=round(confidence, 4),
        evidence=evidence,
    )


def compute_chain_health(
    outcomes: List[dict],
) -> ChainHealth:
    """Compute overall health metrics for the causal chain system.

    Args:
        outcomes: List of fix_outcome dicts.

    Returns:
        ChainHealth with composite score and recommendations.
    """
    if not outcomes:
        return ChainHealth(
            recommendations=["No fix outcomes recorded yet. Start using causal chains to build history."]
        )

    # Basic counts
    total = len(outcomes)
    successes = sum(
        1 for o in outcomes
        if _extract_outcome_fields(o).get("result", "") in ("success", "resolved", "fixed")
    )
    overall_rate = successes / max(total, 1)

    # Strategy diversity
    strategies = set()
    for o in outcomes:
        s = _extract_outcome_fields(o).get("strategy", "")
        if s:
            strategies.add(s)
    diversity = len(strategies)

    # Recurring patterns
    recurring = detect_recurring_failures(outcomes)
    chronic = sum(1 for p in recurring if p.is_chronic)

    # Trend: compare first half vs second half success rates
    mid = total // 2
    if mid >= 5:
        first_half = outcomes[:mid]
        second_half = outcomes[mid:]
        first_rate = sum(
            1 for o in first_half
            if _extract_outcome_fields(o).get("result", "") in ("success", "resolved", "fixed")
        ) / max(len(first_half), 1)
        second_rate = sum(
            1 for o in second_half
            if _extract_outcome_fields(o).get("result", "") in ("success", "resolved", "fixed")
        ) / max(len(second_half), 1)
        if second_rate - first_rate > 0.1:
            trend = "improving"
        elif first_rate - second_rate > 0.1:
            trend = "declining"
        else:
            trend = "stable"
    else:
        trend = "insufficient_data"

    # Health score (0-100)
    score = 0.0
    score += overall_rate * 40  # Success rate: 40 points
    score += min(1.0, diversity / 10) * 20  # Strategy diversity: 20 points
    score += max(0.0, 1.0 - (chronic / max(len(recurring), 1))) * 20  # Low chronic: 20 points
    score += (1.0 if trend == "improving" else 0.5 if trend == "stable" else 0.0) * 20  # Trend: 20 points
    score = round(min(100.0, score), 1)

    # Recommendations
    recs = []
    if overall_rate < 0.5:
        recs.append(
            f"Overall success rate is {overall_rate:.0%}. "
            "Review failing strategies and consider alternative approaches."
        )
    if chronic > 0:
        recs.append(
            f"{chronic} chronic failure pattern(s) detected. "
            "These errors persistently resist fixes — consider escalating or redesigning."
        )
    if diversity < 3 and total > 10:
        recs.append(
            f"Only {diversity} unique strategies used across {total} fix attempts. "
            "Greater strategy diversity may improve resolution rates."
        )
    if trend == "declining":
        recs.append(
            "Fix success rate is declining over time. "
            "Review recent changes for regressions in fix quality."
        )
    if not recs:
        recs.append("Causal chain system is healthy. Keep tracking outcomes for continuous improvement.")

    return ChainHealth(
        total_chains=total,
        overall_success_rate=round(overall_rate, 4),
        chronic_failures=chronic,
        strategy_diversity=diversity,
        improvement_trend=trend,
        health_score=score,
        recommendations=recs,
    )


def analyze_outcomes(
    outcomes: List[dict],
) -> dict:
    """Run a comprehensive analysis on fix outcomes.

    Combines strategy effectiveness, recurring failures, and chain health
    into a single report.

    Args:
        outcomes: List of fix_outcome dicts.

    Returns:
        Dict with keys:
            strategy_effectiveness: Dict[str, StrategyStats]
            recurring_failures: List[RecurringPattern]
            chain_health: ChainHealth
            summary: str (one-line plain text overview)
    """
    effectiveness = get_strategy_effectiveness(outcomes)
    recurring = detect_recurring_failures(outcomes)
    health = compute_chain_health(outcomes)

    # Build summary
    total_strats = len(effectiveness)
    ineffective = sum(
        1 for s in effectiveness.values()
        if s.attempts >= MIN_ATTEMPTS_FOR_STATS and s.success_rate < INEFFECTIVE_THRESHOLD
    )
    summary = (
        f"{health.total_chains} chains | "
        f"{health.overall_success_rate:.0%} success rate | "
        f"{total_strats} strategies ({ineffective} ineffective) | "
        f"{len(recurring)} recurring patterns ({health.chronic_failures} chronic) | "
        f"trend: {health.improvement_trend}"
    )

    return {
        "strategy_effectiveness": effectiveness,
        "recurring_failures": recurring,
        "chain_health": health,
        "summary": summary,
    }
