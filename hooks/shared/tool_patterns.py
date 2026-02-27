"""Tool call pattern analysis using Markov chains.

Reads the capture queue JSONL to build a Markov chain of tool call
sequences, identifies common workflows, detects unusual sequences,
and provides prediction / template helpers.

Public API
----------
load_sequences(queue_path)               -> List[List[str]]
build_markov_chain(sequences)            -> MarkovChain
predict_next_tool(recent_tools, ...)     -> List[Tuple[str, float]]
get_workflow_templates(...)              -> List[WorkflowTemplate]
detect_unusual_sequence(recent, ...)     -> Optional[AnomalyReport]
get_transition_matrix(queue_path)        -> Dict[str, Dict[str, float]]
get_tool_stats(queue_path)               -> Dict[str, Dict]
summarize_patterns(queue_path)           -> Dict

All heavy work is lazy — nothing is loaded until you call a function
that needs data.  Results are cached in module-level singletons so
repeated calls within one process are cheap.  The cache is invalidated
automatically when the queue file's mtime changes.
"""

import json
import math
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_QUEUE_PATH = os.path.join(
    os.path.expanduser("~"), ".claude", "hooks", ".capture_queue.jsonl"
)

# Minimum number of times a transition must appear to count as "learned"
_MIN_TRANSITION_COUNT = 2

# Sequence length bounds for workflow extraction
_MIN_WORKFLOW_LEN = 3
_MAX_WORKFLOW_LEN = 8

# A sequence is "unusual" if its joint log-probability is this many
# standard deviations below the mean of all learned sequence scores.
_ANOMALY_SIGMA_THRESHOLD = 2.0

# Laplace smoothing constant — prevents zero-probability transitions
_LAPLACE_ALPHA = 0.1

# Gap (seconds) within the same session that marks a new sequence boundary
_SESSION_BREAK_SECONDS = 300.0

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class WorkflowTemplate:
    """A recurring sub-sequence of tool calls representing a common workflow.

    Attributes:
        tools:      Ordered list of tool names in the template.
        count:      Number of times this exact n-gram was observed.
        frequency:  Fraction of all sequences that contain this n-gram (0-1).
        label:      Human-readable description of the workflow.
    """

    tools: List[str]
    count: int
    frequency: float
    label: str


@dataclass
class AnomalyReport:
    """Describes a tool sequence that deviates from learned patterns.

    Attributes:
        tools:                The input sequence that triggered the report.
        score:                Log-probability of the sequence (lower = more unusual).
        baseline_mean:        Mean log-probability of all training sequences.
        baseline_std:         Std deviation of training log-probabilities.
        sigma:                Standard deviations below mean (higher = more anomalous).
        reason:               Human-readable explanation.
        unusual_transitions:  List of (from_tool, to_tool) pairs with fewer than
                              _MIN_TRANSITION_COUNT training examples.
    """

    tools: List[str]
    score: float
    baseline_mean: float
    baseline_std: float
    sigma: float
    reason: str
    unusual_transitions: List[Tuple[str, str]]


@dataclass
class MarkovChain:
    """First-order Markov chain over tool names.

    Attributes:
        transitions:    transitions[A][B] = count of B following A.
        start_counts:   How many sequences began with each tool.
        total_starts:   Total number of sequences seen.
        vocabulary:     Set of all tool names seen.
        sequence_count: Total number of tool sequences used to build the chain.
    """

    transitions: Dict[str, Dict[str, int]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(int))
    )
    start_counts: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    total_starts: int = 0
    vocabulary: Set[str] = field(default_factory=set)
    sequence_count: int = 0


# ---------------------------------------------------------------------------
# Module-level cache
# ---------------------------------------------------------------------------

_chain_cache: Optional[MarkovChain] = None
_sequences_cache: Optional[List[List[str]]] = None
_cache_mtime: float = 0.0


def _invalidate_cache() -> None:
    """Clear all in-process caches (forces reload on next access)."""
    global _chain_cache, _sequences_cache, _cache_mtime
    _chain_cache = None
    _sequences_cache = None
    _cache_mtime = 0.0


def _queue_mtime(queue_path: str) -> float:
    """Return the mtime of the queue file, or 0.0 if it does not exist."""
    try:
        return os.path.getmtime(queue_path)
    except OSError:
        return 0.0


def _needs_refresh(queue_path: str) -> bool:
    """Return True if the queue file is newer than the in-process cache."""
    return _queue_mtime(queue_path) > _cache_mtime


# ---------------------------------------------------------------------------
# Queue loading
# ---------------------------------------------------------------------------


def load_sequences(
    queue_path: str = _DEFAULT_QUEUE_PATH,
    skip_tools: Optional[Set[str]] = None,
) -> List[List[str]]:
    """Parse the capture queue JSONL and split into per-session tool sequences.

    A new sequence boundary is introduced:
    - When the ``session_id`` field changes, OR
    - When the time gap between two consecutive entries in the same session
      exceeds ``_SESSION_BREAK_SECONDS`` (default 5 minutes).

    Tool names in ``skip_tools`` are silently removed from sequences — they
    do not cause sequence breaks.  The default skips ``UserPrompt`` and
    ``PreCompact`` because they represent user input / compaction events
    rather than agent tool-call behaviour.

    Args:
        queue_path: Absolute path to the capture queue JSONL file.
        skip_tools: Set of tool names to omit.  Defaults to
                    ``{"UserPrompt", "PreCompact"}``.

    Returns:
        List of sequences.  Each sequence is a list of tool name strings.
        Sequences with fewer than 2 tools are discarded.
    """
    if skip_tools is None:
        skip_tools = {"UserPrompt", "PreCompact"}

    if not os.path.exists(queue_path):
        return []

    raw_entries: List[Dict] = []
    try:
        with open(queue_path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        raw_entries.append(obj)
                except json.JSONDecodeError:
                    continue
    except (IOError, OSError):
        return []

    # Sort chronologically so time-gap detection works correctly
    raw_entries.sort(key=lambda e: e.get("metadata", {}).get("session_time", 0))

    sequences: List[List[str]] = []
    current_seq: List[str] = []
    prev_session: str = ""
    prev_time: float = 0.0

    for entry in raw_entries:
        meta = entry.get("metadata", {})
        tool_name = meta.get("tool_name", "")
        session_id = meta.get("session_id", "")
        session_time = float(meta.get("session_time", 0))

        if not tool_name:
            continue
        if tool_name in skip_tools:
            continue

        # Detect sequence boundary (session change or long idle gap)
        new_session = session_id != prev_session
        time_gap = (
            bool(prev_time)
            and (session_time - prev_time) >= _SESSION_BREAK_SECONDS
        )

        if (new_session or time_gap) and current_seq:
            if len(current_seq) >= 2:
                sequences.append(current_seq)
            current_seq = []

        current_seq.append(tool_name)
        prev_session = session_id
        prev_time = session_time

    # Flush the last open sequence
    if current_seq and len(current_seq) >= 2:
        sequences.append(current_seq)

    return sequences


# ---------------------------------------------------------------------------
# Markov chain construction
# ---------------------------------------------------------------------------


def build_markov_chain(sequences: List[List[str]]) -> MarkovChain:
    """Build a first-order Markov chain from a list of tool-call sequences.

    For each sequence the chain records:
    - A start count for the first tool.
    - A transition count for every consecutive (tools[i], tools[i+1]) pair.

    Args:
        sequences: List of tool-name lists, e.g. from ``load_sequences()``.

    Returns:
        A populated ``MarkovChain`` instance.
    """
    chain = MarkovChain(
        transitions=defaultdict(lambda: defaultdict(int)),
        start_counts=defaultdict(int),
    )

    for seq in sequences:
        if not seq:
            continue
        chain.sequence_count += 1
        chain.total_starts += 1
        chain.vocabulary.add(seq[0])
        chain.start_counts[seq[0]] += 1

        for i in range(len(seq) - 1):
            src = seq[i]
            dst = seq[i + 1]
            chain.vocabulary.add(src)
            chain.vocabulary.add(dst)
            chain.transitions[src][dst] += 1

    return chain


# ---------------------------------------------------------------------------
# Probability helpers (internal)
# ---------------------------------------------------------------------------


def _transition_probability(
    chain: MarkovChain,
    from_tool: str,
    to_tool: str,
) -> float:
    """Laplace-smoothed probability of ``from_tool`` -> ``to_tool``.

    Smoothing over the full vocabulary ensures that unseen transitions
    receive a small non-zero probability rather than zero, which prevents
    -inf log-probabilities on unseen sequences.
    """
    vocab_size = max(len(chain.vocabulary), 1)
    row = chain.transitions.get(from_tool, {})
    row_total = sum(row.values()) + _LAPLACE_ALPHA * vocab_size
    return (row.get(to_tool, 0) + _LAPLACE_ALPHA) / row_total


def _sequence_log_probability(chain: MarkovChain, tools: List[str]) -> float:
    """Log-probability of a sequence under the trained Markov model.

    Combines a Laplace-smoothed start probability with product of all
    transition probabilities.

    Returns:
        Log-probability (always <= 0).  Returns ``-inf`` for empty sequences
        or an untrained chain.
    """
    if not tools or not chain.vocabulary:
        return float("-inf")

    vocab_size = max(len(chain.vocabulary), 1)

    # Start probability
    start_total = chain.total_starts + _LAPLACE_ALPHA * vocab_size
    start_count = chain.start_counts.get(tools[0], 0)
    log_p = math.log((start_count + _LAPLACE_ALPHA) / start_total)

    for i in range(len(tools) - 1):
        p = _transition_probability(chain, tools[i], tools[i + 1])
        log_p += math.log(p)

    return log_p


def _score_all_sequences(
    chain: MarkovChain,
    sequences: List[List[str]],
) -> List[float]:
    """Return the log-probability score for each sequence."""
    return [_sequence_log_probability(chain, seq) for seq in sequences]


def _std(values: List[float]) -> float:
    """Population standard deviation of a list of floats."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    return math.sqrt(sum((v - mean) ** 2 for v in values) / n)


# ---------------------------------------------------------------------------
# Public API — predict_next_tool
# ---------------------------------------------------------------------------


def predict_next_tool(
    recent_tools: List[str],
    queue_path: str = _DEFAULT_QUEUE_PATH,
    top_k: int = 5,
) -> List[Tuple[str, float]]:
    """Predict the most likely next tool given a recent sequence.

    Uses the last element of ``recent_tools`` as the current Markov state
    and returns the top-k most probable next tools with their probabilities.

    If ``recent_tools`` is empty, returns the top-k most common starting
    tools instead.

    Args:
        recent_tools: Ordered list of recently called tool names.
                      Only the *last* element is used for the prediction.
        queue_path:   Path to the capture queue JSONL (for lazy loading).
        top_k:        Maximum number of predictions to return.

    Returns:
        List of ``(tool_name, probability)`` tuples, sorted descending by
        probability.  Probabilities are normalised so they sum to 1.0 over
        the full vocabulary.  Returns ``[]`` if the chain has no vocabulary.
    """
    chain = _get_chain(queue_path)
    if not chain.vocabulary:
        return []

    vocab_size = max(len(chain.vocabulary), 1)

    if not recent_tools:
        # No context — rank by start-state distribution
        start_total = chain.total_starts + _LAPLACE_ALPHA * vocab_size
        probs = {
            t: (chain.start_counts.get(t, 0) + _LAPLACE_ALPHA) / start_total
            for t in chain.vocabulary
        }
    else:
        last_tool = recent_tools[-1]
        row = chain.transitions.get(last_tool, {})
        row_total = sum(row.values()) + _LAPLACE_ALPHA * vocab_size
        probs = {
            t: (row.get(t, 0) + _LAPLACE_ALPHA) / row_total
            for t in chain.vocabulary
        }

    sorted_probs = sorted(probs.items(), key=lambda x: x[1], reverse=True)
    return sorted_probs[:top_k]


# ---------------------------------------------------------------------------
# Public API — get_workflow_templates
# ---------------------------------------------------------------------------

# Canonical labels for well-known tool patterns (checked as contiguous sub-sequences)
_WORKFLOW_LABELS: List[Tuple[List[str], str]] = [
    (["mcp__memory__search_knowledge", "Read", "Edit"],  "memory-guided edit"),
    (["mcp__memory__search_knowledge", "Read", "Write"], "memory-guided write"),
    (["Read", "Edit", "Bash"],                           "read-edit-test"),
    (["Read", "Write", "Bash"],                          "read-write-test"),
    (["Bash", "Edit", "Bash"],                           "test-fix-test"),
    (["Bash", "Write", "Bash"],                          "test-write-test"),
    (["Glob", "Read", "Edit"],                           "search-read-edit"),
    (["Grep", "Read", "Edit"],                           "grep-read-edit"),
    (["Read", "Edit"],                                   "read-then-edit"),
    (["Edit", "Bash"],                                   "edit-then-test"),
    (["Write", "Bash"],                                  "write-then-test"),
    (["mcp__memory__search_knowledge"],                  "memory-lookup"),
    (["mcp__memory__remember_this"],                     "memory-save"),
]


def _label_for_template(tools: List[str]) -> str:
    """Return the best matching human-readable label for a tool sequence.

    Checks each known pattern as a contiguous sub-sequence.  Falls back to
    a description based on the most-called tool in the sequence.
    """
    for pattern, label in _WORKFLOW_LABELS:
        plen = len(pattern)
        if plen <= len(tools):
            for start in range(len(tools) - plen + 1):
                if tools[start : start + plen] == pattern:
                    return label

    if tools:
        from collections import Counter
        dominant = Counter(tools).most_common(1)[0][0]
        return f"{dominant}-centric workflow"
    return "mixed workflow"


def _extract_ngrams(sequence: List[str], n: int) -> List[List[str]]:
    """Slide a window of size ``n`` over ``sequence`` and return all n-grams."""
    return [sequence[i : i + n] for i in range(len(sequence) - n + 1)]


def get_workflow_templates(
    queue_path: str = _DEFAULT_QUEUE_PATH,
    min_count: int = 2,
    max_templates: int = 20,
) -> List[WorkflowTemplate]:
    """Identify the most common tool-call workflows from the capture queue.

    Extracts all n-grams of length ``_MIN_WORKFLOW_LEN`` to
    ``_MAX_WORKFLOW_LEN`` from the learned sequences, counts how often each
    appears, and returns the most frequent ones as ``WorkflowTemplate``
    objects.

    Args:
        queue_path:    Path to the capture queue JSONL.
        min_count:     Minimum number of occurrences to include a template.
        max_templates: Maximum number of templates to return.

    Returns:
        List of ``WorkflowTemplate`` objects sorted by count descending.
    """
    sequences = _get_sequences(queue_path)
    if not sequences:
        return []

    from collections import Counter
    ngram_counts: Counter = Counter()

    for seq in sequences:
        for n in range(_MIN_WORKFLOW_LEN, min(_MAX_WORKFLOW_LEN + 1, len(seq) + 1)):
            for ngram in _extract_ngrams(seq, n):
                ngram_counts[tuple(ngram)] += 1

    total_sequences = len(sequences)
    templates: List[WorkflowTemplate] = []
    for ngram_tuple, count in ngram_counts.items():
        if count < min_count:
            continue
        tools = list(ngram_tuple)
        templates.append(
            WorkflowTemplate(
                tools=tools,
                count=count,
                frequency=count / total_sequences,
                label=_label_for_template(tools),
            )
        )

    # Sort by count descending, then by sequence length descending for tie-breaking
    templates.sort(key=lambda t: (t.count, len(t.tools)), reverse=True)

    # Deduplicate exact key matches
    seen: Set[Tuple[str, ...]] = set()
    deduped: List[WorkflowTemplate] = []
    for tmpl in templates:
        key = tuple(tmpl.tools)
        if key not in seen:
            seen.add(key)
            deduped.append(tmpl)

    return deduped[:max_templates]


# ---------------------------------------------------------------------------
# Public API — detect_unusual_sequence
# ---------------------------------------------------------------------------


def detect_unusual_sequence(
    recent_tools: List[str],
    queue_path: str = _DEFAULT_QUEUE_PATH,
    sigma_threshold: float = _ANOMALY_SIGMA_THRESHOLD,
) -> Optional[AnomalyReport]:
    """Detect whether a tool sequence deviates from learned patterns.

    Detection approach:
    1. Score the candidate sequence using the Markov chain log-probability.
    2. Compare that score against the empirical distribution of scores for
       all training sequences (mean and standard deviation).
    3. Flag as anomalous when the score is more than ``sigma_threshold``
       standard deviations below the mean.
    4. Independently, list any individual transitions that appear fewer
       than ``_MIN_TRANSITION_COUNT`` times in the training data.  Two or
       more such transitions also trigger an anomaly report.

    Args:
        recent_tools:    Ordered list of tool names to evaluate.
        queue_path:      Path to the capture queue JSONL.
        sigma_threshold: Number of std deviations below mean to flag.

    Returns:
        An ``AnomalyReport`` if the sequence is unusual, or ``None`` if it
        looks normal — or if there are fewer than 5 training sequences
        (not enough data to make meaningful judgements).
    """
    if len(recent_tools) < 2:
        return None

    chain = _get_chain(queue_path)
    if not chain.vocabulary or chain.sequence_count < 5:
        return None

    sequences = _get_sequences(queue_path)
    scores = _score_all_sequences(chain, sequences)
    if not scores:
        return None

    mean_score = sum(scores) / len(scores)
    std_score = _std(scores)
    seq_score = _sequence_log_probability(chain, recent_tools)

    # Identify rare transitions
    unusual_transitions: List[Tuple[str, str]] = []
    for i in range(len(recent_tools) - 1):
        src, dst = recent_tools[i], recent_tools[i + 1]
        count = chain.transitions.get(src, {}).get(dst, 0)
        if count < _MIN_TRANSITION_COUNT:
            unusual_transitions.append((src, dst))

    # Sigma: how many std deviations below the mean
    if std_score > 0:
        sigma = (mean_score - seq_score) / std_score
    else:
        sigma = 0.0 if seq_score >= mean_score else float("inf")

    is_anomalous = sigma >= sigma_threshold or len(unusual_transitions) >= 2

    if not is_anomalous:
        return None

    if unusual_transitions:
        pairs_str = ", ".join(f"{a}->{b}" for a, b in unusual_transitions[:3])
        extra = (
            f" ({len(unusual_transitions) - 3} more)"
            if len(unusual_transitions) > 3
            else ""
        )
        reason = (
            f"Sequence contains {len(unusual_transitions)} rare transition(s): "
            f"{pairs_str}{extra}. "
            f"Log-probability {seq_score:.2f} is {sigma:.1f}\u03c3 below learned mean."
        )
    else:
        reason = (
            f"Sequence log-probability {seq_score:.2f} is {sigma:.1f}\u03c3 below "
            f"learned mean {mean_score:.2f} (threshold {sigma_threshold}\u03c3)."
        )

    return AnomalyReport(
        tools=recent_tools,
        score=seq_score,
        baseline_mean=mean_score,
        baseline_std=std_score,
        sigma=sigma,
        reason=reason,
        unusual_transitions=unusual_transitions,
    )


# ---------------------------------------------------------------------------
# Supplemental helpers
# ---------------------------------------------------------------------------


def get_transition_matrix(
    queue_path: str = _DEFAULT_QUEUE_PATH,
) -> Dict[str, Dict[str, float]]:
    """Return the Laplace-smoothed transition probability matrix.

    Args:
        queue_path: Path to the capture queue JSONL.

    Returns:
        Dict mapping ``from_tool`` -> ``{to_tool: probability}``.
        All probabilities for a given ``from_tool`` sum to 1.0.
    """
    chain = _get_chain(queue_path)
    vocab_size = max(len(chain.vocabulary), 1)
    result: Dict[str, Dict[str, float]] = {}

    for src in chain.vocabulary:
        row = chain.transitions.get(src, {})
        row_total = sum(row.values()) + _LAPLACE_ALPHA * vocab_size
        result[src] = {
            dst: (row.get(dst, 0) + _LAPLACE_ALPHA) / row_total
            for dst in chain.vocabulary
        }
    return result


def get_tool_stats(
    queue_path: str = _DEFAULT_QUEUE_PATH,
) -> Dict[str, Dict]:
    """Per-tool statistics: call count, top successors, top predecessors.

    Args:
        queue_path: Path to the capture queue JSONL.

    Returns:
        Dict mapping ``tool_name`` -> dict with keys:
          - ``call_count``:        int
          - ``top_successors``:    list of (tool, count) tuples, top 3
          - ``top_predecessors``:  list of (tool, count) tuples, top 3
    """
    chain = _get_chain(queue_path)
    sequences = _get_sequences(queue_path)

    call_counts: Dict[str, int] = defaultdict(int)
    predecessors: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for seq in sequences:
        for i, tool in enumerate(seq):
            call_counts[tool] += 1
            if i > 0:
                predecessors[tool][seq[i - 1]] += 1

    stats: Dict[str, Dict] = {}
    for tool in chain.vocabulary:
        successors = sorted(
            chain.transitions.get(tool, {}).items(),
            key=lambda x: x[1],
            reverse=True,
        )[:3]
        preds = sorted(
            predecessors.get(tool, {}).items(),
            key=lambda x: x[1],
            reverse=True,
        )[:3]
        stats[tool] = {
            "call_count": call_counts.get(tool, 0),
            "top_successors": successors,
            "top_predecessors": preds,
        }
    return stats


def summarize_patterns(queue_path: str = _DEFAULT_QUEUE_PATH) -> Dict:
    """High-level summary of all learned patterns.

    Convenience wrapper that combines chain metadata, top workflow
    templates, per-tool statistics, and the single most likely next
    tool for each vocabulary item.

    Args:
        queue_path: Path to the capture queue JSONL.

    Returns:
        Dict with keys:
          - ``vocabulary_size``:    int
          - ``sequence_count``:     int
          - ``workflow_templates``: list of template dicts
          - ``tool_stats``:         dict from ``get_tool_stats()``
          - ``top_predictions``:    dict mapping each tool -> most likely next tool
    """
    chain = _get_chain(queue_path)
    templates = get_workflow_templates(queue_path)
    tool_stats = get_tool_stats(queue_path)

    top_predictions: Dict[str, Optional[str]] = {}
    for tool in chain.vocabulary:
        preds = predict_next_tool([tool], queue_path, top_k=1)
        top_predictions[tool] = preds[0][0] if preds else None

    return {
        "vocabulary_size": len(chain.vocabulary),
        "sequence_count": chain.sequence_count,
        "workflow_templates": [
            {
                "tools": t.tools,
                "count": t.count,
                "frequency": round(t.frequency, 4),
                "label": t.label,
            }
            for t in templates
        ],
        "tool_stats": tool_stats,
        "top_predictions": top_predictions,
    }


# ---------------------------------------------------------------------------
# Private lazy-loading helpers
# ---------------------------------------------------------------------------


def _get_sequences(queue_path: str = _DEFAULT_QUEUE_PATH) -> List[List[str]]:
    """Return cached sequences, refreshing from disk if the queue has changed."""
    global _sequences_cache, _cache_mtime, _chain_cache

    if _sequences_cache is None or _needs_refresh(queue_path):
        _sequences_cache = load_sequences(queue_path)
        _cache_mtime = _queue_mtime(queue_path)
        # Downstream caches are stale too
        _chain_cache = None

    return _sequences_cache


def _get_chain(queue_path: str = _DEFAULT_QUEUE_PATH) -> MarkovChain:
    """Return the cached MarkovChain, rebuilding from sequences if needed."""
    global _chain_cache

    sequences = _get_sequences(queue_path)
    if _chain_cache is None:
        _chain_cache = build_markov_chain(sequences)

    return _chain_cache
