"""Memory Consolidation — Merge, promote, and archive memories.

Complements memory_maintenance.py (read-only analysis) with actionable
consolidation operations. All functions return recommendations by default;
no side effects unless explicitly requested.

Public API:
    from shared.memory_consolidation import (
        find_merge_candidates, generate_merged_content,
        find_promotion_candidates, find_archive_candidates,
        run_consolidation_analysis,
    )
"""

import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ConsolidationAction:
    action: str            # "merge", "promote", "archive", "skip"
    memory_ids: List[str] = field(default_factory=list)
    reason: str = ""
    new_content: str = ""  # for merge: the combined content
    confidence: float = 0.0


@dataclass
class ConsolidationReport:
    timestamp: float = 0.0
    duration_ms: float = 0.0
    merges: List[ConsolidationAction] = field(default_factory=list)
    promotions: List[ConsolidationAction] = field(default_factory=list)
    archives: List[ConsolidationAction] = field(default_factory=list)
    summary: str = ""


# Thresholds
PROMOTION_RELEVANCE = 0.7
PROMOTION_MIN_ACCESSES = 10
ARCHIVE_RELEVANCE = 0.15
MERGE_SIMILARITY = 0.5  # Jaccard word overlap threshold
MAX_MERGE_GROUP = 5
MAX_ACTIONS_PER_TYPE = 50


def _sentence_split(text):
    """Split text into sentences (simple heuristic)."""
    if not text:
        return []
    return [s.strip() for s in re.split(r'[.!?\n]+', text) if s.strip() and len(s.strip()) > 10]


def _word_set(text):
    """Extract lowercase word set from text."""
    if not text:
        return set()
    return set(re.findall(r'\b\w{3,}\b', text.lower()))


def _jaccard(a, b):
    """Jaccard similarity between two sets."""
    if not a or not b:
        return 0.0
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def find_merge_candidates(entries, threshold=MERGE_SIMILARITY):
    """Find groups of semantically similar memories to merge.

    Uses word overlap (Jaccard similarity) for lightweight grouping
    without requiring embedding computation.

    Args:
        entries: List of dicts with 'id', 'document', 'tags' keys.
        threshold: Minimum Jaccard similarity to consider as merge candidate.

    Returns:
        List of ConsolidationAction with action="merge".
    """
    try:
        if not entries or len(entries) < 2:
            return []

        # Precompute word sets
        word_sets = [(e, _word_set(e.get("document", ""))) for e in entries]

        # Group by similarity (greedy clustering)
        used = set()
        groups = []
        for i, (ei, wi) in enumerate(word_sets):
            if ei["id"] in used or not wi:
                continue
            group = [ei]
            used.add(ei["id"])
            for j, (ej, wj) in enumerate(word_sets):
                if i == j or ej["id"] in used or not wj:
                    continue
                if _jaccard(wi, wj) >= threshold:
                    group.append(ej)
                    used.add(ej["id"])
                    if len(group) >= MAX_MERGE_GROUP:
                        break
            if len(group) >= 2:
                groups.append(group)

        actions = []
        for group in groups[:MAX_ACTIONS_PER_TYPE]:
            merged = generate_merged_content([e.get("document", "") for e in group])
            actions.append(ConsolidationAction(
                action="merge",
                memory_ids=[e["id"] for e in group],
                reason=f"Jaccard similarity >= {threshold:.2f} across {len(group)} memories",
                new_content=merged,
                confidence=min(0.9, 0.5 + len(group) * 0.1),
            ))
        return actions
    except Exception:
        return []


def generate_merged_content(documents):
    """Create merged content from multiple memory documents with dedup.

    Combines sentences from all documents, deduplicating near-identical
    sentences (> 80% word overlap).

    Args:
        documents: List of document text strings.

    Returns:
        Merged text string.
    """
    try:
        if not documents:
            return ""
        if len(documents) == 1:
            return documents[0]

        all_sentences = []
        seen_word_sets = []
        for doc in documents:
            for sent in _sentence_split(doc):
                ws = _word_set(sent)
                if not ws:
                    continue
                # Check for near-duplicate
                is_dupe = False
                for seen_ws in seen_word_sets:
                    if _jaccard(ws, seen_ws) > 0.8:
                        is_dupe = True
                        break
                if not is_dupe:
                    all_sentences.append(sent)
                    seen_word_sets.append(ws)

        return ". ".join(all_sentences) + "." if all_sentences else documents[0]
    except Exception:
        return documents[0] if documents else ""


def find_promotion_candidates(entries, ltp_statuses=None):
    """Find memories worthy of tier promotion.

    Criteria: relevance_score > PROMOTION_RELEVANCE AND
    retrieval_count >= PROMOTION_MIN_ACCESSES AND tier != 1.

    Args:
        entries: List of dicts with 'id', 'tier', 'retrieval_count', 'tags', 'timestamp'.
        ltp_statuses: Optional dict mapping memory_id -> LTP status string.

    Returns:
        List of ConsolidationAction with action="promote".
    """
    try:
        from shared.memory_decay import calculate_relevance_score
    except ImportError:
        return []

    try:
        actions = []
        for entry in entries:
            tier = int(entry.get("tier") or 3)
            if tier == 1:
                continue  # already top tier
            retrieval_count = int(entry.get("retrieval_count") or 0)
            if retrieval_count < PROMOTION_MIN_ACCESSES:
                continue

            score = calculate_relevance_score(entry)
            if score < PROMOTION_RELEVANCE:
                continue

            # Extra confidence from LTP status
            ltp = (ltp_statuses or {}).get(entry.get("id", ""), "none")
            ltp_boost = {"full": 0.3, "weekly": 0.2, "burst": 0.1, "none": 0.0}.get(ltp, 0.0)
            confidence = min(1.0, 0.5 + ltp_boost + (score - PROMOTION_RELEVANCE))

            reasons = [f"relevance={score:.2f}", f"accesses={retrieval_count}"]
            if ltp != "none":
                reasons.append(f"ltp={ltp}")

            actions.append(ConsolidationAction(
                action="promote",
                memory_ids=[entry["id"]],
                reason=f"Tier {tier}→1: {', '.join(reasons)}",
                confidence=round(confidence, 4),
            ))
            if len(actions) >= MAX_ACTIONS_PER_TYPE:
                break
        return actions
    except Exception:
        return []


def find_archive_candidates(entries, ltp_statuses=None):
    """Find memories safe to archive (low relevance, no LTP protection).

    Args:
        entries: List of memory entry dicts.
        ltp_statuses: Optional dict mapping memory_id -> LTP status.

    Returns:
        List of ConsolidationAction with action="archive".
    """
    try:
        from shared.memory_decay import calculate_relevance_score
    except ImportError:
        return []

    try:
        actions = []
        for entry in entries:
            mid = entry.get("id", "")
            ltp = (ltp_statuses or {}).get(mid, "none")
            if ltp != "none":
                continue  # LTP-protected: never archive

            score = calculate_relevance_score(entry)
            if score >= ARCHIVE_RELEVANCE:
                continue

            actions.append(ConsolidationAction(
                action="archive",
                memory_ids=[mid],
                reason=f"relevance={score:.3f} < {ARCHIVE_RELEVANCE} and no LTP",
                confidence=round(min(1.0, (ARCHIVE_RELEVANCE - score) / ARCHIVE_RELEVANCE), 4),
            ))
            if len(actions) >= MAX_ACTIONS_PER_TYPE:
                break
        return actions
    except Exception:
        return []


def run_consolidation_analysis(entries, ltp_statuses=None):
    """Run full consolidation analysis. Returns ConsolidationReport.

    Read-only: all operations are recommendations, not side effects.
    """
    t0 = time.monotonic()
    report = ConsolidationReport(timestamp=time.time())

    try:
        report.merges = find_merge_candidates(entries)
        report.promotions = find_promotion_candidates(entries, ltp_statuses)
        report.archives = find_archive_candidates(entries, ltp_statuses)

        n_merge = sum(len(a.memory_ids) for a in report.merges)
        n_promote = len(report.promotions)
        n_archive = len(report.archives)
        report.summary = (
            f"{len(entries)} memories analyzed | "
            f"{len(report.merges)} merge groups ({n_merge} memories) | "
            f"{n_promote} promotions | {n_archive} archives"
        )
    except Exception as e:
        report.summary = f"Error during consolidation analysis: {e}"

    report.duration_ms = round((time.monotonic() - t0) * 1000, 2)
    return report
