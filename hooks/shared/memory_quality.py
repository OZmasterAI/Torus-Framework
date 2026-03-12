"""Write-time memory quality scoring. Scores 0.0-1.0 on actionability, specificity, completeness."""

import re

# Identifier patterns: file paths, function names, error codes
_PATH_RE = re.compile(r"[/~]\S+\.\w{1,5}")
_FUNC_RE = re.compile(r"\b\w+\(\)")
_ERROR_RE = re.compile(r"\b(?:Error|Exception|FAIL|BLOCKED|Traceback)\b", re.IGNORECASE)
_LINE_REF_RE = re.compile(r"\bline\s*\d+\b", re.IGNORECASE)

# Causal language
_CAUSAL_RE = re.compile(
    r"\b(?:because|caused by|fixed by|due to|reason:|root cause|resolved by)\b",
    re.IGNORECASE,
)

# Outcome indicators
_OUTCOME_RE = re.compile(
    r"\b(?:outcome:|result:|success|failed|resolved|verified|tested|confirmed|rejected)\b",
    re.IGNORECASE,
)

# Self-containedness: has structure (colons, newlines, multiple sentences)
_STRUCTURE_RE = re.compile(r"(?::\s|\n|\..*\.)")

QUALITY_THRESHOLD = 0.3


def quality_score(content: str) -> float:
    """Score memory content on actionability, specificity, completeness. Returns 0.0-1.0."""
    if not content or len(content.strip()) < 20:
        return 0.0

    score = 0.0
    text = content.strip()

    # Identifier density (0-0.35)
    id_signals = 0
    if _PATH_RE.search(text):
        id_signals += 1
    if _FUNC_RE.search(text):
        id_signals += 1
    if _ERROR_RE.search(text):
        id_signals += 1
    if _LINE_REF_RE.search(text):
        id_signals += 1
    score += min(0.35, id_signals * 0.12)

    # Causal language (0-0.25)
    if _CAUSAL_RE.search(text):
        score += 0.25

    # Outcome presence (0-0.25)
    if _OUTCOME_RE.search(text):
        score += 0.25

    # Self-containedness / structure (0-0.15)
    if _STRUCTURE_RE.search(text):
        score += 0.10
    if len(text) > 100:
        score += 0.05

    return round(min(score, 1.0), 2)
