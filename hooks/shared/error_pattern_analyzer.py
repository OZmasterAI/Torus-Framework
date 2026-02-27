"""Error pattern analysis across sessions for the Torus self-healing framework.

Analyses error messages extracted from audit log entries to identify recurring
issues, correlations between errors, and preventive measures.

Audit log entries are JSONL with keys:
  id, timestamp, gate, tool, decision, reason, session_id, state_keys, severity

Key functions:
  extract_pattern(error_msg)          -- normalise error to a stable pattern string
  analyze_errors(entries)             -- full analysis from audit log entries
  top_patterns(entries, n)            -- most frequent patterns (top-N list)
  correlate_errors(entries)           -- find correlated error pairs
  suggest_prevention(pattern)         -- human-readable prevention tip per pattern
"""

import re
from collections import Counter, defaultdict
from typing import Dict, List, Tuple


# ---------------------------------------------------------------------------
# Pattern definitions
# ---------------------------------------------------------------------------

# Each entry: (compiled regex, canonical pattern label, category, root-cause class)
# category: gate-block | python-error | filesystem | import | syntax | environmental | transient
# root-cause: user-error | framework-bug | environmental | transient
_PATTERN_TABLE: List[Tuple] = [
    # Gate-enforcement patterns
    (re.compile(r"must Read .{0,80} before edit", re.I),
     "gate1:read-before-edit", "gate-block", "user-error"),
    (re.compile(r"(?:rm\s*-rf|DROP TABLE|reset --hard|force.?push|no.?destroy)", re.I),
     "gate2:destructive-command", "gate-block", "user-error"),
    (re.compile(r"deploy.*no tests|tests.*before deploy|run.*test.*before", re.I),
     "gate3:deploy-without-tests", "gate-block", "user-error"),
    (re.compile(r"memory.*not.*queried|query.*memory.*first|search_knowledge.*before", re.I),
     "gate4:memory-not-queried", "gate-block", "user-error"),
    (re.compile(r"verify.*before.*more|proof.*before.*fixed|evidence.*fix|claim.*fixed.*without", re.I),
     "gate5:proof-missing", "gate-block", "user-error"),
    (re.compile(r"save.*to.*memory|remember.*fix|verified.*fix.*not.*saved", re.I),
     "gate6:fix-not-saved", "gate-block", "user-error"),
    (re.compile(r"critical file|high.?risk file|sensitive.*file", re.I),
     "gate7:critical-file-access", "gate-block", "user-error"),
    (re.compile(r"temporal|date.*wrong|future.*date|stale.*date", re.I),
     "gate8:temporal-awareness", "gate-block", "user-error"),
    (re.compile(r"strategy.*banned|ineffective.*strategy|proven.*fail", re.I),
     "gate9:banned-strategy", "gate-block", "user-error"),
    (re.compile(r"expensive model|cost.*guard|opus.*without.*justif", re.I),
     "gate10:expensive-model", "gate-block", "user-error"),
    (re.compile(r"rate limit|too many tool calls|runaway|rolling window.*exceeded", re.I),
     "gate11:rate-limit", "gate-block", "user-error"),
    (re.compile(r"workspace.*claimed|file.*locked|concurrent edit|isolation.*violation", re.I),
     "gate13:workspace-conflict", "gate-block", "user-error"),
    (re.compile(r"confidence.*low|not.*ready.*deploy|readiness.*check", re.I),
     "gate14:confidence-low", "gate-block", "user-error"),
    (re.compile(r"causal chain|query_fix_history.*before|fix_history.*required", re.I),
     "gate15:causal-chain-skipped", "gate-block", "user-error"),
    (re.compile(r"code quality|debug print|hardcoded secret|broad except|bad pattern", re.I),
     "gate16:code-quality", "gate-block", "user-error"),

    # Python errors
    (re.compile(r"ModuleNotFoundError|ImportError|No module named", re.I),
     "python:import-error", "import", "environmental"),
    (re.compile(r"SyntaxError|invalid syntax|unexpected indent|unexpected EOF", re.I),
     "python:syntax-error", "syntax", "user-error"),
    (re.compile(r"AttributeError", re.I),
     "python:attribute-error", "python-error", "user-error"),
    (re.compile(r"TypeError", re.I),
     "python:type-error", "python-error", "user-error"),
    (re.compile(r"KeyError", re.I),
     "python:key-error", "python-error", "user-error"),
    (re.compile(r"ValueError", re.I),
     "python:value-error", "python-error", "user-error"),
    (re.compile(r"IndexError|list index out of range", re.I),
     "python:index-error", "python-error", "user-error"),
    (re.compile(r"RecursionError|maximum recursion", re.I),
     "python:recursion-error", "python-error", "user-error"),
    (re.compile(r"MemoryError|SIGSEGV|segmentation fault", re.I),
     "python:memory-error", "python-error", "environmental"),
    (re.compile(r"Traceback|Exception|raise\s+\w+Error", re.I),
     "python:uncaught-exception", "python-error", "framework-bug"),

    # Filesystem / I/O
    (re.compile(r"No such file or directory|FileNotFoundError|file not found", re.I),
     "fs:file-not-found", "filesystem", "user-error"),
    (re.compile(r"Permission denied|PermissionError|EACCES", re.I),
     "fs:permission-denied", "filesystem", "environmental"),
    (re.compile(r"IsADirectoryError|NotADirectoryError|is a directory", re.I),
     "fs:directory-error", "filesystem", "user-error"),
    (re.compile(r"OSError|IOError|disk full|no space left", re.I),
     "fs:io-error", "filesystem", "environmental"),

    # Network / transient
    (re.compile(r"ConnectionRefused|ECONNREFUSED|connection refused", re.I),
     "net:connection-refused", "environmental", "transient"),
    (re.compile(r"timeout|ETIMEDOUT|timed out", re.I),
     "net:timeout", "environmental", "transient"),
    (re.compile(r"SSL|certificate|TLS", re.I),
     "net:ssl-error", "environmental", "transient"),

    # Test failures
    (re.compile(r"FAILED|AssertionError|assert.*failed|test.*failed|exit code [^0]", re.I),
     "test:assertion-failure", "python-error", "user-error"),
    (re.compile(r"no tests found|empty test suite", re.I),
     "test:no-tests", "python-error", "user-error"),
]

# Fallback for anything unmatched
_FALLBACK_PATTERN = "other:unclassified"
_FALLBACK_CATEGORY = "other"
_FALLBACK_ROOT_CAUSE = "unknown"


# ---------------------------------------------------------------------------
# Prevention tips
# ---------------------------------------------------------------------------

_PREVENTION_MAP: Dict[str, str] = {
    "gate1:read-before-edit": (
        "Always call Read on a file before editing it — Gate 1 enforces this. "
        "Use the Read tool first, then Edit/Write."
    ),
    "gate2:destructive-command": (
        "Avoid rm -rf, DROP TABLE, reset --hard, and force push. "
        "Use safer alternatives: move files to trash, use transactions, git revert."
    ),
    "gate3:deploy-without-tests": (
        "Run the test suite (python3 test_framework.py) before any deploy command. "
        "Gate 3 requires a passing test run in the same session."
    ),
    "gate4:memory-not-queried": (
        "Call search_knowledge() at the start of every task — Gate 4 checks for "
        "a recent memory query before allowing Edit/Write."
    ),
    "gate5:proof-missing": (
        "After fixing a bug, show test output proving the fix works before "
        "claiming it is resolved. Never skip the verify step."
    ),
    "gate6:fix-not-saved": (
        "After verifying a fix, call remember_this() to persist it. "
        "Gate 6 warns when confirmed fixes are not saved to memory."
    ),
    "gate7:critical-file-access": (
        "Extra care required for auth, config, enforcer, and memory_server files. "
        "Always query search_knowledge first, then read the file fully before editing."
    ),
    "gate8:temporal-awareness": (
        "Check today's date before referencing timestamps. "
        "Use the provided currentDate context rather than hard-coding dates."
    ),
    "gate9:banned-strategy": (
        "Query query_fix_history() before attempting a fix to check if the "
        "strategy has already been proven ineffective."
    ),
    "gate10:expensive-model": (
        "Justify Opus model usage explicitly. Prefer Sonnet for routine tasks. "
        "Gate 10 blocks Opus calls without a stated justification."
    ),
    "gate11:rate-limit": (
        "Slow down tool call loops — Gate 11 enforces a rolling window limit. "
        "Batch work, avoid tight retry loops, and wait between repeated calls."
    ),
    "gate13:workspace-conflict": (
        "Only one agent should edit a file at a time. "
        "Check .file_claims.json before editing shared files in multi-agent sessions."
    ),
    "gate14:confidence-low": (
        "Verify all test outputs and memory checks before proceeding to deploy. "
        "Confidence escalates based on completed proof steps."
    ),
    "gate15:causal-chain-skipped": (
        "Call query_fix_history('error text') before attempting any fix. "
        "Gate 15 blocks edits after a test failure until this step is done."
    ),
    "gate16:code-quality": (
        "Remove debug print statements, never hard-code secrets, and avoid "
        "bare 'except:' clauses. Gate 16 warns and eventually blocks these patterns."
    ),
    "python:import-error": (
        "Check that the dependency is installed (pip install <pkg>) and that "
        "sys.path includes the correct hooks/ directory."
    ),
    "python:syntax-error": (
        "Validate new code with 'python3 -c \"import ast; ast.parse(...)\"' "
        "before saving. Use a linter or the Read+verify pattern."
    ),
    "python:attribute-error": (
        "Verify the object type before accessing attributes. "
        "Check for None returns and use getattr(obj, key, default) defensively."
    ),
    "python:type-error": (
        "Check argument types at function boundaries. "
        "Use isinstance() guards or type hints with a runtime checker."
    ),
    "python:key-error": (
        "Use dict.get(key, default) instead of dict[key]. "
        "Validate required keys exist before processing."
    ),
    "python:value-error": (
        "Validate input values before passing them to functions. "
        "Add range/format checks at data ingestion points."
    ),
    "python:index-error": (
        "Guard list/array access with bounds checks. "
        "Use slicing or len() comparisons before indexing."
    ),
    "python:recursion-error": (
        "Add a recursion depth limit or convert to an iterative approach. "
        "Check for circular references in data structures."
    ),
    "python:memory-error": (
        "Reduce memory footprint: process data in chunks, avoid loading "
        "entire large files into memory at once."
    ),
    "python:uncaught-exception": (
        "Add targeted exception handling and log the full traceback. "
        "Avoid broad 'except Exception: pass' — catch specific exceptions."
    ),
    "fs:file-not-found": (
        "Use os.path.exists() before opening files. "
        "Prefer absolute paths and verify working directory assumptions."
    ),
    "fs:permission-denied": (
        "Check file ownership and mode (ls -la). "
        "Do not run hooks as root unnecessarily; fix permissions instead."
    ),
    "fs:directory-error": (
        "Use os.path.isfile() / os.path.isdir() before operations. "
        "Create parent directories with os.makedirs(path, exist_ok=True)."
    ),
    "fs:io-error": (
        "Wrap file I/O in try/except (IOError, OSError). "
        "Check available disk space and handle partial writes gracefully."
    ),
    "net:connection-refused": (
        "Verify the target service is running before connecting. "
        "Add retry logic with exponential back-off for transient failures."
    ),
    "net:timeout": (
        "Increase timeout thresholds or add retry logic. "
        "Check network connectivity and server health first."
    ),
    "net:ssl-error": (
        "Verify certificates are up-to-date and CA bundles are installed. "
        "Check system time accuracy for certificate validity windows."
    ),
    "test:assertion-failure": (
        "Read the full assertion message to understand what value was expected. "
        "Run the specific failing test in isolation for a cleaner traceback."
    ),
    "test:no-tests": (
        "Ensure test files follow the expected naming convention and "
        "that the test discovery path is correct."
    ),
    _FALLBACK_PATTERN: (
        "Review the full error message in context. "
        "Search memory with search_knowledge() for prior instances of this issue."
    ),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_pattern(error_msg: str) -> str:
    """Normalise an error message to a stable pattern label.

    Strips variable content (paths, numbers, timestamps) and matches the
    result against the pattern table.  Returns a canonical string such as
    'gate1:read-before-edit' or 'fs:file-not-found'.  Falls back to
    'other:unclassified' for messages that do not match any known pattern.

    Args:
        error_msg: Raw error or reason string from an audit log entry.

    Returns:
        Canonical pattern label string.
    """
    if not error_msg or not isinstance(error_msg, str):
        return _FALLBACK_PATTERN

    # Quick normalisation: collapse whitespace, but keep case for regex matching
    text = re.sub(r"\s+", " ", error_msg).strip()

    for compiled, label, _category, _root_cause in _PATTERN_TABLE:
        if compiled.search(text):
            return label

    return _FALLBACK_PATTERN


def _classify(pattern: str) -> Tuple[str, str]:
    """Return (category, root_cause) for a known pattern label."""
    for _compiled, label, category, root_cause in _PATTERN_TABLE:
        if label == pattern:
            return category, root_cause
    return _FALLBACK_CATEGORY, _FALLBACK_ROOT_CAUSE


def analyze_errors(entries: List[Dict]) -> Dict:
    """Full error pattern analysis from a list of audit log entry dicts.

    Processes every entry whose decision is 'block' or 'warn' and extracts
    pattern labels from the 'reason' field.  Returns a comprehensive report
    including frequencies, root-cause breakdown, category breakdown, and
    per-pattern prevention suggestions.

    Args:
        entries: List of audit log entry dicts (from parse_audit_log /
                 parse_audit_dir in session_analytics).

    Returns:
        Dict with keys:
          - total_errors:         int  -- total block+warn events analysed
          - pattern_counts:       dict -- pattern -> count (desc)
          - category_breakdown:   dict -- category -> count
          - root_cause_breakdown: dict -- root_cause -> count
          - top_patterns:         list of (pattern, count) -- top 10
          - suggestions:          dict -- pattern -> prevention tip
          - session_breakdown:    dict -- session_id -> {pattern -> count}
    """
    pattern_counts: Counter = Counter()
    category_counts: Counter = Counter()
    root_cause_counts: Counter = Counter()
    # session_id -> Counter of patterns
    session_map: Dict[str, Counter] = defaultdict(Counter)

    total = 0
    for entry in entries:
        decision = entry.get("decision", "pass")
        if decision not in ("block", "warn"):
            continue
        reason = entry.get("reason") or entry.get("message") or ""
        if not isinstance(reason, str):
            reason = str(reason)

        pattern = extract_pattern(reason)
        category, root_cause = _classify(pattern)

        pattern_counts[pattern] += 1
        category_counts[category] += 1
        root_cause_counts[root_cause] += 1
        total += 1

        sid = entry.get("session_id") or "unknown"
        session_map[sid][pattern] += 1

    # Build suggestions only for patterns actually observed
    suggestions = {p: suggest_prevention(p) for p in pattern_counts}

    return {
        "total_errors": total,
        "pattern_counts": dict(pattern_counts.most_common()),
        "category_breakdown": dict(category_counts.most_common()),
        "root_cause_breakdown": dict(root_cause_counts.most_common()),
        "top_patterns": pattern_counts.most_common(10),
        "suggestions": suggestions,
        "session_breakdown": {
            sid: dict(counter.most_common())
            for sid, counter in session_map.items()
        },
    }


def top_patterns(entries: List[Dict], n: int = 10) -> List[Tuple[str, int]]:
    """Return the N most common error patterns from audit log entries.

    Considers only 'block' and 'warn' decisions.

    Args:
        entries: List of audit log entry dicts.
        n:       Maximum number of patterns to return (default 10).

    Returns:
        List of (pattern_label, count) tuples, sorted by count descending.
        Empty list if no block/warn entries exist.
    """
    counts: Counter = Counter()
    for entry in entries:
        if entry.get("decision") not in ("block", "warn"):
            continue
        reason = entry.get("reason") or entry.get("message") or ""
        if not isinstance(reason, str):
            reason = str(reason)
        counts[extract_pattern(reason)] += 1
    return counts.most_common(n)


def correlate_errors(entries: List[Dict]) -> List[Dict]:
    """Find pairs of error patterns that tend to occur close together.

    For each block/warn event, examines a look-ahead window of up to 5
    subsequent block/warn events in the same session to identify co-occurring
    pattern pairs.  Returns pairs sorted by co-occurrence count.

    Args:
        entries: List of audit log entry dicts in chronological order.

    Returns:
        List of dicts, each with keys:
          - pattern_a:       str -- first pattern label
          - pattern_b:       str -- second pattern label
          - count:           int -- number of times the pair co-occurred
          - example_session: str -- one session_id where the pair was observed
        Sorted by count descending.  Empty list if fewer than two error events.
    """
    WINDOW = 5  # look-ahead events

    # Collect only block/warn events with extracted patterns
    error_events: List[Dict] = []
    for entry in entries:
        if entry.get("decision") not in ("block", "warn"):
            continue
        reason = entry.get("reason") or entry.get("message") or ""
        if not isinstance(reason, str):
            reason = str(reason)
        error_events.append({
            "pattern": extract_pattern(reason),
            "session_id": entry.get("session_id") or "unknown",
            "ts": entry.get("timestamp", ""),
        })

    if len(error_events) < 2:
        return []

    pair_counts: Counter = Counter()
    pair_sessions: Dict[Tuple[str, str], str] = {}

    for i, ev in enumerate(error_events):
        a = ev["pattern"]
        # Look at next WINDOW events
        window_end = min(len(error_events), i + 1 + WINDOW)
        for j in range(i + 1, window_end):
            ev2 = error_events[j]
            # Only correlate within the same session when session_id is known
            sid_a = ev["session_id"]
            sid_b = ev2["session_id"]
            if sid_a != "unknown" and sid_b != "unknown" and sid_a != sid_b:
                continue
            b = ev2["pattern"]
            # Canonical pair order to avoid counting (A,B) and (B,A) separately
            pair = (min(a, b), max(a, b))
            pair_counts[pair] += 1
            if pair not in pair_sessions:
                pair_sessions[pair] = sid_a if sid_a != "unknown" else sid_b

    results = []
    for (a, b), count in pair_counts.most_common():
        results.append({
            "pattern_a": a,
            "pattern_b": b,
            "count": count,
            "example_session": pair_sessions.get((a, b), "unknown"),
        })
    return results


def suggest_prevention(pattern: str) -> str:
    """Return a human-readable prevention tip for a given pattern label.

    Args:
        pattern: Pattern label as returned by extract_pattern().

    Returns:
        String describing how to prevent the error.  Falls back to a generic
        tip for unknown patterns.
    """
    return _PREVENTION_MAP.get(pattern, _PREVENTION_MAP[_FALLBACK_PATTERN])


# ---------------------------------------------------------------------------
# Convenience: frequency table from raw error strings
# ---------------------------------------------------------------------------


def frequency_from_strings(error_msgs: List[str]) -> Dict[str, int]:
    """Count pattern occurrences from a plain list of error message strings.

    Convenience wrapper for callers that already have raw messages rather
    than audit log entry dicts.

    Args:
        error_msgs: List of raw error/reason strings.

    Returns:
        Dict mapping pattern_label -> count, sorted descending.
    """
    counts: Counter = Counter()
    for msg in error_msgs:
        counts[extract_pattern(msg)] += 1
    return dict(counts.most_common())
