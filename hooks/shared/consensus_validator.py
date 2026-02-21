"""Consensus-based validation for critical operations.

Cross-references multiple signals before allowing high-stakes actions such as
saving to memory, editing framework files, or committing code.

Public API
----------
check_memory_consensus(content, existing_memories) -> dict
    Verdict: "novel" | "duplicate" | "conflict", with confidence and reason.

check_edit_consensus(file_path, old_content, new_content) -> dict
    Safety assessment with confidence score and list of detected risks.

compute_confidence(signals) -> float
    Weighted mean of named signal scores, all in [0.0, 1.0].

recommend_action(confidence) -> str
    "allow" (>= 0.6), "ask" (0.3–0.59), or "block" (< 0.3).

Usage
-----
    from shared.consensus_validator import (
        check_memory_consensus,
        check_edit_consensus,
        compute_confidence,
        recommend_action,
    )
"""

from __future__ import annotations

import difflib
import re
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Files that require extra scrutiny during edit consensus checks
CRITICAL_FILES: frozenset[str] = frozenset(
    [
        "enforcer.py",
        "gate_result.py",
        "boot.py",
        "memory_server.py",
        "audit_log.py",
        "state.py",
        "error_normalizer.py",
        "secrets_filter.py",
        "settings.json",
        "sudoers",
    ]
)

# Thresholds for recommend_action
_THRESHOLD_BLOCK = 0.3
_THRESHOLD_ASK = 0.6

# Similarity ratio above which two strings are treated as duplicates
_DUPLICATE_RATIO = 0.85

# Similarity ratio above which content is considered "very similar but not
# quite duplicate" — may warrant a conflict check.
_NEAR_MATCH_RATIO = 0.55

# Signal weights used by compute_confidence when not overridden
_DEFAULT_WEIGHTS: dict[str, float] = {
    "memory_coverage": 0.30,
    "test_coverage": 0.25,
    "pattern_match": 0.25,
    "prior_success": 0.20,
}

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _normalise(text: str) -> str:
    """Lower-case, collapse whitespace for robust string comparison."""
    return re.sub(r"\s+", " ", text.strip().lower())


def _similarity(a: str, b: str) -> float:
    """SequenceMatcher ratio between two strings (0.0–1.0)."""
    return difflib.SequenceMatcher(None, _normalise(a), _normalise(b)).ratio()


def _extract_imports(source: str) -> list[str]:
    """Return bare import names from Python source (best-effort, no AST)."""
    imports: list[str] = []
    for line in source.splitlines():
        stripped = line.strip()
        m = re.match(r"^(?:import|from)\s+([\w.]+)", stripped)
        if m:
            imports.append(m.group(1).split(".")[0])
    return imports


def _is_critical_file(file_path: str) -> bool:
    """True if the file_path basename matches any entry in CRITICAL_FILES."""
    import os

    return os.path.basename(file_path) in CRITICAL_FILES


def _detect_broad_except(source: str) -> bool:
    """True if source contains a bare `except:` or `except Exception:`."""
    return bool(re.search(r"except\s*(?:Exception\s*)?\:", source))


def _detect_hardcoded_secret(source: str) -> bool:
    """Heuristic: flag obvious secret-like assignments."""
    patterns = [
        r'(?i)(password|secret|token|api_key)\s*=\s*["\'][^"\']{4,}["\']',
        r'(?i)(passwd|pwd)\s*=\s*["\'][^"\']{4,}["\']',
    ]
    for pat in patterns:
        if re.search(pat, source):
            return True
    return False


def _detect_debug_prints(source: str) -> bool:
    """True if source contains debug-style print statements."""
    return bool(re.search(r"\bprint\s*\(", source))


def _removed_public_functions(old: str, new: str) -> list[str]:
    """Return names of top-level functions/classes present in old but absent in new."""
    def _public_names(src: str) -> set[str]:
        names: set[str] = set()
        for m in re.finditer(r"^(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)", src, re.MULTILINE):
            name = m.group(1)
            if not name.startswith("_"):
                names.add(name)
        return names

    old_names = _public_names(old)
    new_names = _public_names(new)
    return sorted(old_names - new_names)


def _import_drift(old: str, new: str) -> list[str]:
    """Return imports present in old but entirely removed in new (possible breakage)."""
    old_imports = set(_extract_imports(old))
    new_imports = set(_extract_imports(new))
    return sorted(old_imports - new_imports)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_memory_consensus(
    content: str,
    existing_memories: list[Any],
) -> dict:
    """Assess whether *content* is novel, a duplicate, or conflicts with existing memories.

    Args:
        content:           The candidate memory string to evaluate.
        existing_memories: Iterable of existing memory objects.  Each element
                           may be a plain string or a dict/object with a
                           ``content``, ``preview``, or ``text`` key.

    Returns:
        dict with keys:
          - verdict:    "novel" | "duplicate" | "conflict"
          - confidence: float 0.0–1.0 (how certain we are of the verdict)
          - reason:     human-readable explanation
          - top_match:  similarity score of the closest existing memory (float)
    """
    if not content or not content.strip():
        return {
            "verdict": "novel",
            "confidence": 0.5,
            "reason": "Empty or blank content — cannot compare; treated as novel.",
            "top_match": 0.0,
        }

    def _get_text(mem: Any) -> str:
        if isinstance(mem, str):
            return mem
        if isinstance(mem, dict):
            for key in ("content", "preview", "text", "body"):
                if key in mem and isinstance(mem[key], str):
                    return mem[key]
        return str(mem)

    top_ratio = 0.0
    top_text = ""

    for mem in existing_memories:
        text = _get_text(mem)
        if not text:
            continue
        ratio = _similarity(content, text)
        if ratio > top_ratio:
            top_ratio = ratio
            top_text = text

    # --- Classify ---------------------------------------------------------
    # Negation/polarity check runs first — a high-similarity pair with opposing
    # polarity is a conflict, not a duplicate.
    if top_ratio >= _NEAR_MATCH_RATIO:
        content_norm = _normalise(content)
        top_norm = _normalise(top_text)

        negation_re = re.compile(r"\b(not|never|false|incorrect|wrong|broken)\b")
        new_has_negation = bool(negation_re.search(content_norm))
        old_has_negation = bool(negation_re.search(top_norm))

        if new_has_negation != old_has_negation:
            return {
                "verdict": "conflict",
                "confidence": 0.55 + (top_ratio - _NEAR_MATCH_RATIO) * 0.5,
                "reason": (
                    f"Content is {top_ratio:.0%} similar to an existing memory "
                    "but differs in negation/polarity — possible contradiction."
                ),
                "top_match": top_ratio,
            }

    if top_ratio >= _DUPLICATE_RATIO:
        return {
            "verdict": "duplicate",
            "confidence": min(1.0, top_ratio),
            "reason": (
                f"Content is {top_ratio:.0%} similar to an existing memory — "
                "likely a duplicate; skipping saves dedup noise."
            ),
            "top_match": top_ratio,
        }

    if _NEAR_MATCH_RATIO <= top_ratio < _DUPLICATE_RATIO:
        # Near-match without negation flip → treat as novel update
        return {
            "verdict": "novel",
            "confidence": 0.65,
            "reason": (
                f"Content is {top_ratio:.0%} similar to an existing memory "
                "but adds or refines information — considered novel."
            ),
            "top_match": top_ratio,
        }

    # Low similarity — genuinely new
    confidence = 0.8 if top_ratio < 0.2 else 0.70
    return {
        "verdict": "novel",
        "confidence": confidence,
        "reason": (
            f"No sufficiently similar memory found (best match: {top_ratio:.0%}). "
            "Content appears genuinely new."
        ),
        "top_match": top_ratio,
    }


def check_edit_consensus(
    file_path: str,
    old_content: str,
    new_content: str,
) -> dict:
    """Evaluate the safety of replacing *old_content* with *new_content* in *file_path*.

    Checks performed:
    - Whether the file is in the CRITICAL_FILES set
    - Import additions/removals that could break dependents
    - Public API removals (functions/classes dropped)
    - Broad exception patterns introduced
    - Hardcoded secrets introduced
    - Debug print statements introduced
    - Magnitude of the diff (large rewrites score lower)

    Args:
        file_path:   Path (or basename) of the file being edited.
        old_content: Current file content as a string.
        new_content: Proposed file content as a string.

    Returns:
        dict with keys:
          - safe:       bool (True when confidence >= _THRESHOLD_ASK)
          - confidence: float 0.0–1.0
          - risks:      list[str] of detected risk descriptions
          - is_critical: bool (True if the file is in CRITICAL_FILES)
    """
    risks: list[str] = []
    is_critical = _is_critical_file(file_path)

    # 1. Critical file penalty
    if is_critical:
        risks.append(
            f"File '{file_path}' is in the critical-files list — extra caution required."
        )

    # 2. Import drift — removals that may break callers
    dropped_imports = _import_drift(old_content, new_content)
    if dropped_imports:
        risks.append(
            f"Imports removed that were present before: {', '.join(dropped_imports)}. "
            "This may break modules that depend on them."
        )

    # 3. Public API removals
    removed_fns = _removed_public_functions(old_content, new_content)
    if removed_fns:
        risks.append(
            f"Public functions/classes removed: {', '.join(removed_fns)}. "
            "Callers referencing these names will break."
        )

    # 4. Broad except introduced
    had_broad = _detect_broad_except(old_content)
    has_broad = _detect_broad_except(new_content)
    if has_broad and not had_broad:
        risks.append(
            "Broad 'except' clause introduced — this can swallow unexpected errors silently."
        )

    # 5. Hardcoded secrets introduced
    had_secret = _detect_hardcoded_secret(old_content)
    has_secret = _detect_hardcoded_secret(new_content)
    if has_secret and not had_secret:
        risks.append(
            "Potential hardcoded secret/credential introduced (password, token, api_key)."
        )

    # 6. Debug prints introduced
    had_print = _detect_debug_prints(old_content)
    has_print = _detect_debug_prints(new_content)
    if has_print and not had_print:
        risks.append("Debug print() statement(s) introduced — should be removed before shipping.")

    # 7. Diff magnitude (large changes are riskier)
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm=""))
    changed_lines = sum(1 for l in diff if l.startswith(("+", "-")) and not l.startswith(("+++", "---")))
    total_lines = max(len(old_lines), len(new_lines), 1)
    change_fraction = changed_lines / total_lines

    if change_fraction > 0.6:
        risks.append(
            f"Large rewrite detected: {change_fraction:.0%} of lines changed. "
            "Full rewrites carry elevated regression risk."
        )
    elif change_fraction > 0.35:
        risks.append(
            f"Moderate diff size: {change_fraction:.0%} of lines changed — review carefully."
        )

    # --- Confidence scoring -----------------------------------------------
    # Start from 1.0 and penalise each detected risk
    _PENALTIES: dict[str, float] = {
        "critical_file": 0.15,
        "import_removal": 0.20,
        "api_removal": 0.25,
        "broad_except": 0.15,
        "hardcoded_secret": 0.30,
        "debug_print": 0.10,
        "large_rewrite": 0.15,
        "moderate_diff": 0.05,
    }

    confidence = 1.0
    if is_critical:
        confidence -= _PENALTIES["critical_file"]
    if dropped_imports:
        confidence -= _PENALTIES["import_removal"]
    if removed_fns:
        confidence -= _PENALTIES["api_removal"]
    if has_broad and not had_broad:
        confidence -= _PENALTIES["broad_except"]
    if has_secret and not had_secret:
        confidence -= _PENALTIES["hardcoded_secret"]
    if has_print and not had_print:
        confidence -= _PENALTIES["debug_print"]
    if change_fraction > 0.6:
        confidence -= _PENALTIES["large_rewrite"]
    elif change_fraction > 0.35:
        confidence -= _PENALTIES["moderate_diff"]

    confidence = max(0.0, min(1.0, confidence))

    return {
        "safe": confidence >= _THRESHOLD_ASK,
        "confidence": confidence,
        "risks": risks,
        "is_critical": is_critical,
    }


def compute_confidence(signals: dict) -> float:
    """Compute a weighted confidence score from named signal values.

    Each signal value must be in [0.0, 1.0].  Recognised signal names are
    weighted according to _DEFAULT_WEIGHTS; unrecognised names are included
    with equal weight.

    Args:
        signals: dict mapping signal name -> float score (0.0–1.0).

    Returns:
        Weighted average confidence in [0.0, 1.0].  Returns 0.5 for empty input.

    Examples:
        >>> compute_confidence({"memory_coverage": 0.8, "test_coverage": 0.6})
        0.72...
        >>> compute_confidence({})
        0.5
        >>> compute_confidence({"custom": 0.9, "other": 0.1})
        0.5
    """
    if not signals:
        return 0.5

    total_weight = 0.0
    weighted_sum = 0.0

    for name, value in signals.items():
        # Clamp value to [0, 1]
        value = max(0.0, min(1.0, float(value)))
        weight = _DEFAULT_WEIGHTS.get(name, 1.0 / max(len(signals), 1))
        weighted_sum += value * weight
        total_weight += weight

    if total_weight == 0.0:
        return 0.5

    return max(0.0, min(1.0, weighted_sum / total_weight))


def recommend_action(confidence: float) -> str:
    """Map a confidence score to a recommended action.

    Thresholds:
        >= 0.6  → "allow"   (proceed autonomously)
        0.3–0.59 → "ask"    (request user confirmation)
        < 0.3   → "block"   (refuse / escalate)

    Args:
        confidence: Float in [0.0, 1.0] from compute_confidence or a consensus check.

    Returns:
        One of "allow", "ask", or "block".
    """
    if confidence >= _THRESHOLD_ASK:
        return "allow"
    if confidence >= _THRESHOLD_BLOCK:
        return "ask"
    return "block"
