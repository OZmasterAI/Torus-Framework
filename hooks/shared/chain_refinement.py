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
    generate_failure_lessons(outcomes)  -> List[FailureLesson]
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
class FailureLesson:
    """A lesson distilled from a failed fix chain (ReasoningBank-style).

    Captures what was tried, why it failed, and what should be tried instead,
    following the ReasoningBank approach of learning from both successes and
    failures to produce transferable reasoning artifacts.

    Attributes:
        error_pattern: The normalized error that triggered the chain.
        failed_strategy: The strategy that failed.
        failure_count: How many times this strategy failed on this error.
        success_count: How many times this strategy succeeded on this error.
        better_strategy: A strategy with higher success rate, if known.
        better_success_rate: Success rate of the better strategy.
        lesson: Human-readable lesson string.
        confidence: How confident the lesson is (0.0-1.0).
    """
    error_pattern: str
    failed_strategy: str
    failure_count: int = 0
    success_count: int = 0
    better_strategy: str = ""
    better_success_rate: float = 0.0
    lesson: str = ""
    confidence: float = 0.0


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

# Minimum failures before a lesson is generated (avoid noise)
MIN_FAILURES_FOR_LESSON = 2


# ── Outcome parsing ─────────────────────────────────────────────────────

def _normalize_error(error: str) -> str:
    """Normalize an error string for grouping.

    Strips file paths, line numbers, and timestamps to group
    semantically equivalent errors together.

    Handles both bare paths (/foo/bar.py) and Python traceback format
    (File "/foo/bar.py", line 42, in ...) where the path appears inside
    double quotes.  The quoted form is handled first so that the trailing
    comma is consumed along with the quote rather than being left as a
    stray character that breaks downstream matching.
    """
    if not error or not isinstance(error, str):
        return ""
    import re
    # Remove Python traceback file references: File "path/file.py"
    # Handles paths with spaces, commas, or other special chars inside quotes.
    normalized = re.sub(
        r'[Ff]ile\s+"[^"]*\.(?:py|js|ts|tsx|jsx|rs|go|java|rb|sh|c|cpp|h)"',
        'File <file>',
        error,
    )
    # Remove bare file paths (any common extension)
    normalized = re.sub(
        r'/[\w/.-]+\.(?:py|js|ts|tsx|jsx|rs|go|java|rb|sh|c|cpp|h)',
        '<file>',
        normalized,
    )
    # Remove line numbers
    normalized = re.sub(r'line \d+', 'line N', normalized)
    # Remove timestamps
    normalized = re.sub(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}', '<ts>', normalized)
    # Remove hex addresses
    normalized = re.sub(r'0x[0-9a-fA-F]+', '<addr>', normalized)
    # Remove numeric IDs (PIDs, ports, etc.) — standalone numbers of 4+ digits
    normalized = re.sub(r'\b\d{4,}\b', '<num>', normalized)
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


def _adaptive_min_recurrence(n_outcomes: int) -> int:
    """Compute an adaptive minimum recurrence threshold.

    Scales up the threshold for large datasets so that only truly
    persistent patterns (not statistical noise) are flagged.

    Scale:
        n < 20   -> 3  (floor: same as MIN_RECURRENCE)
        20-49    -> 4
        50-99    -> 5
        100-199  -> 6
        200+     -> 7

    The constant MIN_RECURRENCE is always the floor so callers that
    pass an explicit value still see deterministic behaviour.
    """
    if n_outcomes < 20:
        return MIN_RECURRENCE
    if n_outcomes < 50:
        return 4
    if n_outcomes < 100:
        return 5
    if n_outcomes < 200:
        return 6
    return 7


def _error_similarity(a: str, b: str) -> float:
    """Compute similarity between two normalised error strings.

    Uses Jaccard word-overlap as the base metric but applies the overlap
    coefficient (intersection / min-set-size) for very short errors
    (1-2 tokens) where Jaccard is artificially deflated by differing
    union sizes.

    Returns a float in [0.0, 1.0].
    """
    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    if not intersection:
        return 0.0
    union = words_a | words_b
    jaccard = len(intersection) / len(union)

    # For single- or two-token errors the overlap coefficient gives a
    # better signal: a single shared token between two one-word errors
    # gives jaccard = 0.5 (below the 0.4 threshold when union grows)
    # but overlap-coefficient = 1.0, which correctly marks them as
    # the same error class.
    max_tokens = max(len(words_a), len(words_b))
    if max_tokens <= 2:
        min_len = min(len(words_a), len(words_b))
        return len(intersection) / min_len  # overlap coefficient >= jaccard

    return jaccard


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
    # Track per-chain attempt order for avg_attempts_to_success
    chain_attempts: Dict[str, list] = {}

    for outcome in outcomes:
        fields = _extract_outcome_fields(outcome)
        strategy = fields.get("strategy", "")
        result = fields.get("result", "")
        error = fields.get("error", "")
        chain_id = fields.get("chain_id", "")

        if not strategy:
            continue

        if strategy not in strategy_data:
            strategy_data[strategy] = {
                "attempts": 0,
                "successes": 0,
                "failures": 0,
                "errors": set(),
            }

        data = strategy_data[strategy]
        data["attempts"] += 1
        data["errors"].add(_normalize_error(error))

        if result in ("success", "resolved", "fixed"):
            data["successes"] += 1
        elif result in ("failure", "failed", "unresolved"):
            data["failures"] += 1

        if chain_id:
            chain_attempts.setdefault(chain_id, []).append((strategy, result))

    # Compute avg_attempts_to_success: for each chain that contains a success
    # entry for this strategy, record the 1-indexed position of that success
    # within the chain (i.e. how many total attempts were needed, including
    # earlier failed attempts in the same chain).
    strategy_success_positions: Dict[str, list] = {}
    for chain_id, attempts in chain_attempts.items():
        for i, (strategy, result) in enumerate(attempts):
            if result in ("success", "resolved", "fixed"):
                # Position is 1-indexed: value=1 means first attempt succeeded
                strategy_success_positions.setdefault(strategy, []).append(i + 1)

    stats: Dict[str, StrategyStats] = {}
    for strategy, data in strategy_data.items():
        attempts = data["attempts"]
        successes = data["successes"]
        success_rate = successes / max(attempts, 1)
        positions = strategy_success_positions.get(strategy, [])
        avg_to_success = sum(positions) / len(positions) if positions else 0.0

        stats[strategy] = StrategyStats(
            strategy=strategy,
            attempts=attempts,
            successes=successes,
            failures=data["failures"],
            success_rate=round(success_rate, 4),
            avg_attempts_to_success=round(avg_to_success, 2),
            errors_addressed=len(data["errors"]),
        )

    return stats


def detect_recurring_failures(
    outcomes: List[dict],
    min_recurrence: Optional[int] = None,
) -> List[RecurringPattern]:
    """Find error patterns that recur across multiple fix chains.

    When *min_recurrence* is omitted (None) the threshold is computed
    adaptively based on the number of outcomes, scaling up for larger
    datasets to reduce noise.  Pass an explicit integer to override.

    Args:
        outcomes: List of fix_outcome dicts.
        min_recurrence: Minimum occurrences to flag, or None for adaptive.

    Returns:
        List of RecurringPattern objects, sorted by occurrence count descending.
    """
    # Resolve adaptive threshold when caller did not override
    if min_recurrence is None:
        min_recurrence = _adaptive_min_recurrence(len(outcomes))

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



# ── ReasoningBank-style failure learning ─────────────────────────────────

def generate_failure_lessons(
    outcomes: List[dict],
    min_failures: int = MIN_FAILURES_FOR_LESSON,
) -> List[FailureLesson]:
    """Extract transferable lessons from failed fix chains (ReasoningBank-style).

    For each (error_pattern, strategy) pair where the strategy has failed
    at least *min_failures* times and has a success rate below
    INEFFECTIVE_THRESHOLD, generates a FailureLesson describing:
    - What was tried and how often it failed
    - Whether a better alternative exists
    - A structured lesson string for future reference

    The lesson format follows:
        "When encountering [error], strategy [X] fails because [reason].
         Try [Y] instead."

    This implements the core ReasoningBank insight: failures are not waste --
    they contain transferable negative knowledge that prevents repeating
    the same mistakes.

    Args:
        outcomes: List of fix_outcome dicts from memory.
        min_failures: Minimum failure count to generate a lesson (default 2).

    Returns:
        List of FailureLesson objects, sorted by confidence descending.
    """
    if not outcomes:
        return []

    # Group outcomes by (normalized_error, strategy)
    error_strategy_data: Dict[Tuple[str, str], dict] = {}

    for outcome in outcomes:
        fields = _extract_outcome_fields(outcome)
        error = _normalize_error(fields.get("error", ""))
        strategy = fields.get("strategy", "")
        result = fields.get("result", "")

        if not error or not strategy:
            continue

        key = (error, strategy)
        if key not in error_strategy_data:
            error_strategy_data[key] = {
                "failures": 0,
                "successes": 0,
                "attempts": 0,
            }

        data = error_strategy_data[key]
        data["attempts"] += 1
        if result in ("failure", "failed", "unresolved"):
            data["failures"] += 1
        elif result in ("success", "resolved", "fixed"):
            data["successes"] += 1

    # For each error pattern, find the best alternative strategy
    error_best_alt: Dict[str, Tuple[str, float]] = {}
    error_all_strategies: Dict[str, Dict[str, dict]] = {}

    for (error, strategy), data in error_strategy_data.items():
        if error not in error_all_strategies:
            error_all_strategies[error] = {}
        error_all_strategies[error][strategy] = data

    for error, strategies in error_all_strategies.items():
        best_strat = ""
        best_rate = 0.0
        for strat, data in strategies.items():
            if data["attempts"] < MIN_ATTEMPTS_FOR_STATS:
                continue
            rate = data["successes"] / max(data["attempts"], 1)
            if rate > best_rate:
                best_rate = rate
                best_strat = strat
        if best_strat:
            error_best_alt[error] = (best_strat, best_rate)

    # Generate lessons for ineffective strategies
    lessons = []
    for (error, strategy), data in error_strategy_data.items():
        failures = data["failures"]
        successes = data["successes"]
        attempts = data["attempts"]

        if failures < min_failures:
            continue

        success_rate = successes / max(attempts, 1)
        if success_rate >= INEFFECTIVE_THRESHOLD:
            continue  # Strategy is not clearly ineffective

        # Determine failure reason based on statistics
        if successes == 0:
            failure_reason = f"it has never succeeded ({failures} failures in {attempts} attempts)"
        else:
            failure_reason = (
                f"it succeeds only {success_rate:.0%} of the time "
                f"({successes}/{attempts} attempts)"
            )

        # Build lesson string
        best_alt = error_best_alt.get(error)
        if best_alt and best_alt[0] != strategy and best_alt[1] > success_rate:
            alt_name, alt_rate = best_alt
            lesson_str = (
                f"When encountering [{error}], strategy [{strategy}] fails because "
                f"{failure_reason}. Try [{alt_name}] instead "
                f"(success rate: {alt_rate:.0%})."
            )
            better_strategy = alt_name
            better_success_rate = alt_rate
        else:
            lesson_str = (
                f"When encountering [{error}], strategy [{strategy}] fails because "
                f"{failure_reason}. No proven alternative found yet -- "
                f"consider a novel approach."
            )
            better_strategy = ""
            better_success_rate = 0.0

        # Confidence: blend failure evidence with alternative quality
        failure_evidence = min(1.0, failures / 10.0) ** 0.5
        alt_quality = better_success_rate if better_strategy else 0.0
        confidence = round(min(1.0, 0.5 * failure_evidence + 0.5 * alt_quality), 4)

        lessons.append(FailureLesson(
            error_pattern=error,
            failed_strategy=strategy,
            failure_count=failures,
            success_count=successes,
            better_strategy=better_strategy,
            better_success_rate=round(better_success_rate, 4),
            lesson=lesson_str,
            confidence=confidence,
        ))

    lessons.sort(key=lambda l: l.confidence, reverse=True)
    return lessons


def _find_lesson_for_error(
    error: str,
    lessons: List[FailureLesson],
    current_strategy: str = "",
) -> Optional[FailureLesson]:
    """Find the most relevant lesson for a given error and strategy.

    Searches the lessons list for entries that match the error pattern
    (exact or similar) and optionally the current strategy. Returns the
    highest-confidence match, or None.

    Args:
        error: The normalized error to match.
        lessons: Pre-computed failure lessons.
        current_strategy: If provided, prefer lessons about this strategy.

    Returns:
        Best matching FailureLesson, or None.
    """
    if not error or not lessons:
        return None

    best_match: Optional[FailureLesson] = None
    best_score = 0.0

    for lesson in lessons:
        # Check error similarity
        if error == lesson.error_pattern:
            similarity = 1.0
        else:
            similarity = _error_similarity(error, lesson.error_pattern)
            if similarity < 0.4:
                continue

        # Strategy match bonus: if the lesson warns about the current strategy
        strategy_bonus = 0.2 if (current_strategy and lesson.failed_strategy == current_strategy) else 0.0

        score = similarity * lesson.confidence + strategy_bonus
        if score > best_score:
            best_score = score
            best_match = lesson

    return best_match


def suggest_refinement(
    error: str,
    outcomes: List[dict],
    current_strategy: str = "",
    lessons: Optional[List[FailureLesson]] = None,
) -> Optional[Refinement]:
    """Suggest a better strategy for handling a specific error.

    When *lessons* are provided (or can be generated from outcomes),
    checks them first for a quick answer before computing from scratch.
    This implements the ReasoningBank principle of reusing distilled
    failure knowledge to shortcut repeated analysis.

    Looks at historical outcomes for similar errors and recommends
    the strategy with the highest success rate if it's meaningfully
    better than the current one.

    Args:
        error: The error text to find a refinement for.
        outcomes: Historical fix_outcome data.
        current_strategy: The strategy currently being considered.
        lessons: Pre-computed failure lessons (optional; generated if None
                 and outcomes has enough data).

    Returns:
        A Refinement object if a better approach exists, None otherwise.
    """
    normalized_error = _normalize_error(error)
    if not normalized_error:
        return None

    # ── ReasoningBank shortcut: check lessons first ──────────────────
    if lessons is None and len(outcomes) >= MIN_FAILURES_FOR_LESSON * 2:
        lessons = generate_failure_lessons(outcomes)

    if lessons:
        lesson = _find_lesson_for_error(normalized_error, lessons, current_strategy)
        if lesson and lesson.better_strategy and lesson.confidence >= 0.3:
            if lesson.better_strategy != current_strategy:
                return Refinement(
                    error_pattern=normalized_error,
                    current_strategy=current_strategy,
                    suggested_strategy=lesson.better_strategy,
                    reason=(
                        f"Lesson learned: {lesson.failed_strategy} fails on this error "
                        f"({lesson.failure_count} failures). "
                        f"{lesson.better_strategy} has {lesson.better_success_rate:.0%} "
                        f"success rate."
                    ),
                    confidence=lesson.confidence,
                    evidence=[
                        f"lesson: {lesson.lesson}",
                        f"{lesson.failed_strategy}: {lesson.success_count} successes, "
                        f"{lesson.failure_count} failures",
                    ],
                )

    # ── Standard path: compute from outcomes directly ────────────────
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

        # Similarity: exact normalized match (best) or word overlap (fallback)
        if normalized_error != outcome_error:
            similarity = _error_similarity(normalized_error, outcome_error)
            if similarity < 0.4:
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
    best_alt_attempts = 0
    for strat, data in strategy_results.items():
        if strat == current_strategy:
            continue
        if data["attempts"] < MIN_ATTEMPTS_FOR_STATS:
            continue
        rate = data["successes"] / max(data["attempts"], 1)
        if rate > best_alt_rate:
            best_alt_rate = rate
            best_alt = strat
            best_alt_attempts = data["attempts"]

    if not best_alt:
        return None

    improvement = best_alt_rate - current_rate
    if improvement < MIN_IMPROVEMENT_DELTA:
        return None

    # Confidence: blend improvement magnitude with evidence strength.
    # - improvement_factor: linear scale from MIN_IMPROVEMENT_DELTA -> 0.5
    #   mapped to [0, 1].  Full contribution on 50%+ improvement.
    # - evidence_factor: sqrt-scaled sample count, saturates near 30 samples.
    # Blend: 60% improvement signal, 40% evidence weight.
    improvement_factor = min(1.0, (improvement - MIN_IMPROVEMENT_DELTA) / (0.5 - MIN_IMPROVEMENT_DELTA))
    evidence_factor = min(1.0, best_alt_attempts / 30.0) ** 0.5
    confidence = round(min(1.0, 0.6 * improvement_factor + 0.4 * evidence_factor), 4)

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
        confidence=confidence,
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

    # Trend: compare thirds for more granular trend detection
    third = total // 3
    if third >= 3:
        thirds = [outcomes[i*third:(i+1)*third] for i in range(3)]
        rates = []
        for t in thirds:
            rate = sum(
                1 for o in t
                if _extract_outcome_fields(o).get("result", "") in ("success", "resolved", "fixed")
            ) / max(len(t), 1)
            rates.append(rate)
        # Monotonic improvement/decline across all thirds
        if rates[2] - rates[0] > 0.15 and rates[1] >= rates[0]:
            trend = "improving"
        elif rates[0] - rates[2] > 0.15 and rates[1] <= rates[0]:
            trend = "declining"
        elif rates[2] - rates[0] > 0.05:
            trend = "slightly_improving"
        elif rates[0] - rates[2] > 0.05:
            trend = "slightly_declining"
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


def _detect_strategy_combos(outcomes):
    """Find strategies that succeed together in the same chain.

    Returns list of (strategy_a, strategy_b, joint_success_rate) tuples
    for combos with >= 3 co-occurrences and success rate > 0.6.
    """
    from collections import defaultdict

    chain_strategies = defaultdict(list)
    chain_results = {}

    for outcome in outcomes:
        fields = _extract_outcome_fields(outcome)
        chain_id = fields.get("chain_id", "")
        strategy = fields.get("strategy", "")
        result = fields.get("result", "")
        if chain_id and strategy:
            chain_strategies[chain_id].append(strategy)
            if result in ("success", "resolved", "fixed"):
                chain_results[chain_id] = True
            elif chain_id not in chain_results:
                chain_results[chain_id] = False

    combo_stats = defaultdict(lambda: {"count": 0, "successes": 0})
    for chain_id, strategies in chain_strategies.items():
        unique = sorted(set(strategies))
        success = chain_results.get(chain_id, False)
        for i, a in enumerate(unique):
            for b in unique[i + 1:]:
                key = (a, b)
                combo_stats[key]["count"] += 1
                if success:
                    combo_stats[key]["successes"] += 1

    combos = []
    for (a, b), stats in combo_stats.items():
        if stats["count"] >= 3:
            rate = stats["successes"] / stats["count"]
            if rate > 0.6:
                combos.append((a, b, round(rate, 4)))

    combos.sort(key=lambda x: x[2], reverse=True)
    return combos


def analyze_outcomes(
    outcomes: List[dict],
) -> dict:
    """Run a comprehensive analysis on fix outcomes.

    Combines strategy effectiveness, recurring failures, failure lessons,
    and chain health into a single report.

    Args:
        outcomes: List of fix_outcome dicts.

    Returns:
        Dict with keys:
            strategy_effectiveness: Dict[str, StrategyStats]
            recurring_failures: List[RecurringPattern]
            failure_lessons: List[FailureLesson]
            chain_health: ChainHealth
            summary: str (one-line plain text overview)
    """
    effectiveness = get_strategy_effectiveness(outcomes)
    recurring = detect_recurring_failures(outcomes)
    health = compute_chain_health(outcomes)
    lessons = generate_failure_lessons(outcomes)

    # Detect strategy combos (strategies that succeed together in chains)
    strategy_combos = _detect_strategy_combos(outcomes)

    # Build summary
    total_strats = len(effectiveness)
    ineffective = sum(
        1 for s in effectiveness.values()
        if s.attempts >= MIN_ATTEMPTS_FOR_STATS and s.success_rate < INEFFECTIVE_THRESHOLD
    )
    combo_note = f", {len(strategy_combos)} effective combos" if strategy_combos else ""
    lesson_note = f", {len(lessons)} lessons" if lessons else ""
    summary = (
        f"{health.total_chains} chains | "
        f"{health.overall_success_rate:.0%} success rate | "
        f"{total_strats} strategies ({ineffective} ineffective{combo_note}) | "
        f"{len(recurring)} recurring patterns ({health.chronic_failures} chronic) | "
        f"trend: {health.improvement_trend}{lesson_note}"
    )

    return {
        "strategy_effectiveness": effectiveness,
        "recurring_failures": recurring,
        "failure_lessons": lessons,
        "strategy_combos": strategy_combos,
        "chain_health": health,
        "summary": summary,
    }
