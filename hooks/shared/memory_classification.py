"""Memory Classification — tier classification and tag normalization.

Extracted from memory_server.py as part of Memory v2 Layered Redesign.

Public API:
    from shared.memory_classification import (
        classify_tier, salience_score, normalize_tags,
        inject_project_tag, build_project_prefix,
    )
"""

import json
import os
import re


# ── Salience scoring constants ──────────────────────────────────────────────

_TIER3_TAGS = {"type:auto-captured", "priority:low"}

_DECISION_KW = (
    "decision",
    "chose",
    "switched to",
    "instead of",
    "trade-off",
    "went with",
    "picked",
    "selected approach",
    "design:",
)
_HARDWON_KW = (
    "root cause",
    "finally fixed",
    "after debugging",
    "tracked down",
    "hard to find",
    "subtle bug",
    "race condition",
)
_IMPACT_KW = (
    "production",
    "shipped",
    "deployed",
    "breaking",
    "outage",
    "user-facing",
    "live system",
)
_HUMAN_TAGS = {"type:correction", "type:preference"}
_DECISION_TAGS = {"type:decision"}
_FIX_TAGS = {"type:fix"}
_RECURRENCE_TAGS = {"type:learning", "outcome:success"}


def salience_score(content: str, tags: str) -> float:
    """Calculate salience score (0.0-1.0) from content and tags."""
    tag_set = (
        {t.strip().lower() for t in tags.split(",") if t.strip()} if tags else set()
    )
    lower = content.lower()
    score = 0.0

    # Decision change (25%)
    if tag_set & _DECISION_TAGS or any(kw in lower for kw in _DECISION_KW):
        score += 0.25

    # Human-originated (20%)
    if tag_set & _HUMAN_TAGS:
        score += 0.20

    # Hard-won (15%)
    if tag_set & _FIX_TAGS or any(kw in lower for kw in _HARDWON_KW):
        score += 0.15

    # Recurrence (15%)
    if tag_set & _RECURRENCE_TAGS:
        score += 0.15

    # Real-world impact (15%)
    if "priority:critical" in tag_set or "priority:high" in tag_set:
        score += 0.15
    elif any(kw in lower for kw in _IMPACT_KW):
        score += 0.15

    # Connective density (10%) — more tags = more connections
    if len(tag_set) >= 5:
        score += 0.10
    elif len(tag_set) >= 3:
        score += 0.05

    return min(score, 1.0)


def classify_tier(content: str, tags: str) -> int:
    """Classify a memory into tier 1 (high), 2 (standard), or 3 (low).

    Pure function — no side effects. Uses salience scoring with 6 weighted
    signals inspired by thermal-memory.
    """
    tag_set = (
        {t.strip().lower() for t in tags.split(",") if t.strip()} if tags else set()
    )

    # Tier 3 fast path — low-value indicators
    if tag_set & _TIER3_TAGS:
        return 3

    score = salience_score(content, tags)

    # Short content with no salience signals = low value
    if len(content) < 50 and score <= 0.10:
        return 3

    # High-signal tags get a floor — trust explicit tagging
    _HIGH_SIGNAL_TAGS = {
        "type:fix",
        "type:decision",
        "type:correction",
        "type:preference",
        "priority:critical",
    }
    if tag_set & _HIGH_SIGNAL_TAGS:
        return 1

    if score >= 0.25:
        return 1
    if score <= 0.10:
        return 3
    return 2


# ── Memory Type Classification ────────────────────────────────────────────────

_REFERENCE_TAGS = {
    "type:decision",
    "type:preference",
    "type:correction",
    "type:index",
    "type:benchmark",
}
_REFERENCE_COMBO = {"type:learning"}  # only if also has outcome:success
_WORKING_TAGS = {"type:auto-captured", "needs-enrichment"}
_WORKING_ERROR = {"type:error"}  # only if NOT outcome:success
_SESSION_RE = re.compile(r"session\d+", re.IGNORECASE)


def classify_memory_type(content: str, tags: str) -> str:
    """Classify memory as 'reference', 'working', or '' (unclassified).

    Pure function — no side effects. Used as filter metadata, not for scoring.
    """
    tag_set = (
        {t.strip().lower() for t in tags.split(",") if t.strip()} if tags else set()
    )

    if tag_set & _REFERENCE_TAGS:
        return "reference"
    if tag_set & _REFERENCE_COMBO and "outcome:success" in tag_set:
        return "reference"

    sal = salience_score(content, tags)
    if sal >= 0.40:
        return "reference"

    if tag_set & _WORKING_TAGS:
        return "working"
    if tag_set & _WORKING_ERROR and "outcome:success" not in tag_set:
        return "working"
    if any(_SESSION_RE.match(t) for t in tag_set):
        return "working"

    if sal < 0.15 and len(content) < 200:
        return "working"

    return ""


# ── State Type Classification ────────────────────────────────────────────────
# High-precision keyword lists — conservative, prefer "" over false positives.
# Removed: session, active, branch (too ambiguous), rule (too common).

_EPHEMERAL_KEYWORDS = frozenset(
    {
        "running",
        "pid",
        "port",
        "alive",
        "tmux",
        "process",
        "listening",
        "started",
        "restarted",
        "connected",
        "mounted",
        "socket",
        "daemon",
        "localhost",
        "worktree",
        "spawned",
    }
)

_CONCEPTUAL_KEYWORDS = frozenset(
    {
        "decision",
        "pattern",
        "architecture",
        "always",
        "never",
        "design",
        "principle",
        "standard",
        "convention",
        "preference",
        "correction",
        "strategy",
        "policy",
        "guideline",
        "invariant",
        "tradeoff",
        "deprecated",
    }
)

_STATE_CONCEPTUAL_TAGS = {
    "type:decision",
    "type:preference",
    "type:correction",
    "type:benchmark",
}


def classify_state_type(content: str, tags: str) -> str:
    """Classify memory as 'ephemeral', 'conceptual', or '' (unclassified).

    Pure function — no side effects. Deterministic keyword scanner.
    Orthogonal to memory_type (reference/working).
    """
    tag_set = (
        {t.strip().lower() for t in tags.split(",") if t.strip()} if tags else set()
    )
    tokens = set(content.lower().split())

    eph_hits = len(tokens & _EPHEMERAL_KEYWORDS)
    con_hits = len(tokens & _CONCEPTUAL_KEYWORDS)

    # Tag signals boost conceptual
    if tag_set & _STATE_CONCEPTUAL_TAGS:
        con_hits += 2

    # auto-captured lowers ephemeral threshold
    eph_threshold = 1 if "type:auto-captured" in tag_set else 2

    if eph_hits >= eph_threshold and eph_hits > con_hits:
        return "ephemeral"
    if con_hits >= 2 and con_hits > eph_hits:
        return "conceptual"
    return ""


# ── Tag Normalization ─────────────────────────────────────────────────────────

_BARE_TO_DIMENSION = {
    # type dimension
    "fix": "type:fix",
    "error": "type:error",
    "learning": "type:learning",
    "feature": "type:feature",
    "feature-request": "type:feature-request",
    "correction": "type:correction",
    "decision": "type:decision",
    "auto-captured": "type:auto-captured",
    "preference": "type:preference",
    "audit": "type:audit",
    # priority dimension
    "critical": "priority:critical",
    "high": "priority:high",
    "medium": "priority:medium",
    "low": "priority:low",
    # outcome dimension
    "success": "outcome:success",
    "failed": "outcome:failed",
}


def normalize_tags(tags: str) -> str:
    """Normalize tags to canonical dimension:value format.

    Non-destructive — unknown tags pass through unchanged.
    Examples:
        "fix,high,framework" -> "type:fix,priority:high,framework"
        "type:fix,critical"  -> "type:fix,priority:critical"
        ""                   -> ""
    """
    if not tags:
        return tags
    parts = [t.strip() for t in tags.split(",") if t.strip()]
    normalized = []
    for tag in parts:
        lower = tag.lower()
        if ":" in tag:
            normalized.append(tag)
        elif lower in _BARE_TO_DIMENSION:
            normalized.append(_BARE_TO_DIMENSION[lower])
        else:
            normalized.append(tag)
    return ",".join(normalized)


def inject_project_tag(tags, server_project, server_subproject=None):
    """Auto-append project:<name> and subproject:<name> tags if applicable.

    Args:
        tags: Existing comma-separated tag string
        server_project: Project name (or None/empty to skip)
        server_subproject: Subproject name (or None/empty to skip)
    """
    if not server_project:
        return tags
    proj_tag = f"project:{server_project}"
    if proj_tag not in (tags or ""):
        tags = f"{tags},{proj_tag}" if tags else proj_tag
    if server_subproject:
        sub_tag = f"subproject:{server_subproject}"
        if sub_tag not in (tags or ""):
            tags = f"{tags},{sub_tag}" if tags else sub_tag
    return tags


def build_project_prefix(
    server_project, server_subproject=None, project_dir=None, subproject_dir=None
):
    """Build '[project #N]' or '[project/sub #N]' prefix from project state.

    Args:
        server_project: Project name (or None/empty to return "")
        server_subproject: Subproject name (optional)
        project_dir: Project directory path (for reading session count)
        subproject_dir: Subproject directory path (takes precedence over project_dir)
    """
    if not server_project:
        return ""
    eff_dir = subproject_dir or project_dir
    eff_name = (
        f"{server_project}/{server_subproject}" if server_subproject else server_project
    )
    session_num = "?"
    if eff_dir:
        state_file = os.path.join(eff_dir, ".claude-state.json")
        try:
            with open(state_file) as f:
                state = json.load(f)
            session_num = state.get("session_count", "?")
        except Exception:
            pass
    return f"[{eff_name} #{session_num}] "
