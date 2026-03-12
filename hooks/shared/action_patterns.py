"""Action patterns: structured trigger->action->outcome memories from fix_outcomes."""

import re
import time
from datetime import datetime

_ERROR_SIGNALS = re.compile(
    r"(?:error|exception|fail|blocked|broken|crash|traceback|bug|not found|denied|timeout|refused)",
    re.IGNORECASE,
)


def is_error_query(query: str) -> bool:
    """Detect if a search query looks like an error/fix lookup."""
    return bool(_ERROR_SIGNALS.search(query))


def extract_pattern(doc_text: str, meta: dict) -> dict:
    """Extract an action pattern from a fix_outcomes entry."""
    confidence = 0.0
    try:
        confidence = float(meta.get("confidence", 0))
    except (ValueError, TypeError):
        pass

    # Apply temporal decay to confidence (30-day half-life)
    timestamp = meta.get("timestamp", "")
    if timestamp:
        try:
            age_days = (
                time.time() - datetime.fromisoformat(timestamp).timestamp()
            ) / 86400
            confidence *= 0.5 ** (age_days / 30)
        except (ValueError, TypeError):
            pass

    return {
        "trigger": doc_text.strip(),
        "action": meta.get("strategy_id", "unknown"),
        "outcome": meta.get("outcome", "pending"),
        "confidence": round(confidence, 3),
        "chain_id": meta.get("chain_id", ""),
        "attempts": int(meta.get("attempts", 0) or 0),
    }


def format_pattern(pattern: dict) -> str:
    """Format an action pattern for display in search results."""
    outcome_icon = (
        "+"
        if pattern["outcome"] == "success"
        else "-"
        if pattern["outcome"] == "failed"
        else "?"
    )
    return (
        f"Previously: [{outcome_icon}] {pattern['trigger'][:80]} "
        f"-> {pattern['action']} "
        f"(outcome: {pattern['outcome']}, confidence: {pattern['confidence']:.2f})"
    )


def rank_patterns(patterns: list) -> list:
    """Sort action patterns: successful first, then by confidence descending."""

    def sort_key(p):
        outcome_rank = (
            0 if p["outcome"] == "success" else 1 if p["outcome"] == "pending" else 2
        )
        return (outcome_rank, -p["confidence"])

    return sorted(patterns, key=sort_key)
