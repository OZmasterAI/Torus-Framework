"""Memory Maintenance — Health Analysis for the Torus Memory System.

Provides ongoing health monitoring for the LanceDB knowledge collection
(currently ~929 memories). All functions are read-only; nothing is deleted
or modified. Results are pure recommendations.

Design constraints:
- Analysis only — no writes, no deletes, no quarantine moves
- Fail-open — every public function swallows exceptions and returns a
  degraded-but-valid result dict rather than raising
- Uses the UDS socket client (memory_socket.py) so it never creates a
  direct PersistentClient (avoids the Rust-backend segfault risk)
- Dedup quarantine was implemented in Session 120; this module treats
  quarantine as an informational counter only

Public API:
    from shared.memory_maintenance import (
        analyze_memory_health,   # Full health report
        cleanup_candidates,      # List of IDs safe to archive
    )

Usage:
    report = analyze_memory_health()
    print(report["summary"])          # plain-text overview
    print(report["recommendations"])  # list of strings

    candidates = cleanup_candidates()
    for c in candidates:
        print(c["id"], c["reason"], c["age_days"])
"""

import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Optional

# Ensure shared imports work when invoked directly
_HOOKS_DIR = os.path.join(os.path.expanduser("~"), ".claude", "hooks")
if _HOOKS_DIR not in sys.path:
    sys.path.insert(0, _HOOKS_DIR)

# ── Constants ─────────────────────────────────────────────────────────────────

# Age thresholds (days)
STALE_THRESHOLD_DAYS = 90    # memories older than this are candidates for review
ANCIENT_THRESHOLD_DAYS = 180 # memories older than this are strong archive candidates

# Tag category targets — categories with fewer than this share of total are "underrepresented"
UNDERREPRESENTED_SHARE = 0.03  # 3 % of total

# Minimum memories required for meaningful analysis
MIN_MEMORIES_FOR_ANALYSIS = 10

# Known session-reference patterns in content (old session anchors)
_SESSION_REF_RE = re.compile(
    r'\b(session\s*#?\s*\d{1,3}|session_?id|sprint[\s-]\d)\b',
    re.IGNORECASE,
)

# Patterns that indicate a memory describes a superseded state
_SUPERSEDED_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r'was\s+(fixed|resolved|deprecated)',
        r'no\s+longer\s+(needed|valid|applies)',
        r'replaced\s+by',
        r'obsolete',
        r'(the\s+)?old\s+(implementation|approach|strategy)',
        r'previously\s+(used|was)',
        r'before\s+(the|this)\s+(refactor|migration|change)',
        r'temporary\s+workaround',
    ]
]

# Well-known canonical tag prefixes used for category grouping
_CANONICAL_CATEGORIES = [
    "type:fix",
    "type:error",
    "type:feature",
    "type:learning",
    "type:decision",
    "type:audit",
    "type:correction",
    "area:framework",
    "area:infra",
    "area:testing",
    "area:frontend",
    "area:backend",
    "area:docs",
    "area:git",
    "area:memory-system",
    "priority:critical",
    "priority:high",
    "priority:medium",
    "priority:low",
    "outcome:success",
    "outcome:failed",
]

# Possible-dupe tag prefix injected by dedup (Session 120)
_POSSIBLE_DUPE_TAG_PREFIX = "possible-dupe:"


# ── Internal helpers ──────────────────────────────────────────────────────────


def _safe_fetch_all(collection_name="knowledge"):
    """Fetch all entries from a LanceDB collection via the UDS socket.

    Returns a list of dicts with keys: id, document, tags, timestamp, preview.
    Returns an empty list on any failure (fail-open).
    """
    try:
        from shared.memory_socket import get, count, WorkerUnavailable
        total = count(collection_name)
        if total == 0:
            return []

        raw = get(
            collection_name,
            limit=total,
            include=["documents", "metadatas"],
        )
        if not raw:
            return []

        ids = raw.get("ids") or []
        docs = raw.get("documents") or []
        metas = raw.get("metadatas") or []

        results = []
        for i, entry_id in enumerate(ids):
            doc = docs[i] if i < len(docs) else ""
            meta = metas[i] if i < len(metas) else {}
            results.append({
                "id": entry_id,
                "document": doc or "",
                "tags": meta.get("tags", ""),
                "timestamp": meta.get("timestamp", ""),
                "preview": meta.get("preview", ""),
                "session_time": meta.get("session_time", 0.0),
                "possible_dupe": meta.get("possible_dupe", ""),
            })

        return results
    except Exception:
        return []


def _parse_timestamp(ts_str):
    """Parse an ISO8601 timestamp string, returning None on failure."""
    if not ts_str:
        return None
    try:
        clean = ts_str.replace("Z", "+00:00")
        return datetime.fromisoformat(clean)
    except (ValueError, TypeError):
        try:
            return datetime.fromisoformat(ts_str)
        except (ValueError, TypeError):
            return None


def _age_days(ts_str, now):
    """Return age in days for a timestamp string, or None if unparseable."""
    dt = _parse_timestamp(ts_str)
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    delta = now - dt
    return max(0.0, delta.total_seconds() / 86400)


def _split_tags(tags_str):
    """Split a comma-separated tags string into a list of stripped, non-empty tags."""
    if not tags_str:
        return []
    return [t.strip() for t in tags_str.split(",") if t.strip()]


def _has_session_reference(document):
    """Return True if the document contains an old session anchor like 'Session 42'."""
    return bool(_SESSION_REF_RE.search(document))


def _has_superseded_language(document):
    """Return True if the document uses language suggesting it describes a past state."""
    return any(p.search(document) for p in _SUPERSEDED_PATTERNS)


# ── Core analysis functions ───────────────────────────────────────────────────


def _count_stats(entries, now):
    """Compute count and age distribution statistics.

    Returns:
        {
            "total": int,
            "quarantine_count": int | None,
            "age_buckets": {
                "fresh_0_30d": int,
                "recent_31_90d": int,
                "aging_91_180d": int,
                "stale_181d_plus": int,
                "unknown_age": int,
            },
            "median_age_days": float | None,
            "oldest_age_days": float | None,
            "newest_age_days": float | None,
        }
    """
    buckets = {
        "fresh_0_30d": 0,
        "recent_31_90d": 0,
        "aging_91_180d": 0,
        "stale_181d_plus": 0,
        "unknown_age": 0,
    }
    ages = []

    for entry in entries:
        age = _age_days(entry["timestamp"], now)
        if age is None:
            buckets["unknown_age"] += 1
            continue
        ages.append(age)
        if age <= 30:
            buckets["fresh_0_30d"] += 1
        elif age <= 90:
            buckets["recent_31_90d"] += 1
        elif age <= 180:
            buckets["aging_91_180d"] += 1
        else:
            buckets["stale_181d_plus"] += 1

    median_age = None
    if ages:
        sorted_ages = sorted(ages)
        mid = len(sorted_ages) // 2
        if len(sorted_ages) % 2 == 0:
            median_age = (sorted_ages[mid - 1] + sorted_ages[mid]) / 2
        else:
            median_age = sorted_ages[mid]

    # Try to get quarantine count separately
    quarantine_count = None
    try:
        from shared.memory_socket import count as uds_count
        quarantine_count = uds_count("quarantine")
    except Exception:
        pass

    return {
        "total": len(entries),
        "quarantine_count": quarantine_count,
        "age_buckets": buckets,
        "median_age_days": round(median_age, 1) if median_age is not None else None,
        "oldest_age_days": round(max(ages), 1) if ages else None,
        "newest_age_days": round(min(ages), 1) if ages else None,
    }


def _tag_distribution(entries):
    """Analyse tag usage across all memories.

    Returns:
        {
            "total_unique_tags": int,
            "top_tags": [{"tag": str, "count": int, "share_pct": float}, ...],  # top 25
            "category_breakdown": {<category>: {"count": int, "share_pct": float}, ...},
            "underrepresented_categories": [<category>, ...],
            "untagged_count": int,
            "possible_dupe_count": int,
            "avg_tags_per_memory": float,
        }
    """
    tag_counter = Counter()
    total = len(entries)
    untagged = 0
    possible_dupe_count = 0
    tag_totals = 0

    for entry in entries:
        tags = _split_tags(entry["tags"])
        if not tags:
            untagged += 1
            continue
        tag_totals += len(tags)
        for tag in tags:
            tag_counter[tag] += 1
            if tag.startswith(_POSSIBLE_DUPE_TAG_PREFIX):
                possible_dupe_count += 1

    top_tags = [
        {
            "tag": tag,
            "count": cnt,
            "share_pct": round(cnt / total * 100, 1) if total else 0.0,
        }
        for tag, cnt in tag_counter.most_common(25)
    ]

    # Build canonical category breakdown
    category_breakdown = {}
    for cat in _CANONICAL_CATEGORIES:
        cnt = tag_counter.get(cat, 0)
        category_breakdown[cat] = {
            "count": cnt,
            "share_pct": round(cnt / total * 100, 1) if total else 0.0,
        }

    # Identify underrepresented canonical categories
    underrepresented = [
        cat for cat in _CANONICAL_CATEGORIES
        if category_breakdown[cat]["share_pct"] < UNDERREPRESENTED_SHARE * 100
    ]

    avg_tags = round(tag_totals / max(total - untagged, 1), 1)

    return {
        "total_unique_tags": len(tag_counter),
        "top_tags": top_tags,
        "category_breakdown": category_breakdown,
        "underrepresented_categories": underrepresented,
        "untagged_count": untagged,
        "possible_dupe_count": possible_dupe_count,
        "avg_tags_per_memory": avg_tags,
    }


def _similarity_groups(entries):
    """Group memories by tag overlap to identify clusters and gaps.

    Uses a lightweight tag-intersection approach rather than embedding
    similarity (keeps this module dependency-free from lancedb).

    Returns:
        {
            "clusters": [
                {
                    "label": str,           # primary shared tag
                    "size": int,
                    "member_ids": [str, ...]  # up to 10 shown
                },
                ...
            ],
            "singleton_count": int,     # memories that share no tags with others
            "largest_cluster_size": int,
            "cluster_count": int,
        }
    """
    # Build inverted index: tag -> list of entry IDs
    # Skip very generic tags that would create noise clusters
    _NOISE_TAGS = {
        "type:fix", "type:error", "type:feature", "type:learning",
        "type:decision", "outcome:success", "outcome:failed",
        "priority:high", "priority:medium", "priority:critical",
        "priority:low", "area:framework", "area:infra",
    }

    tag_to_ids = defaultdict(list)
    for entry in entries:
        for tag in _split_tags(entry["tags"]):
            if tag not in _NOISE_TAGS:
                tag_to_ids[tag].append(entry["id"])

    # Only keep tags that appear on >= 3 memories (meaningful cluster signal)
    clusters = []
    for tag, ids in sorted(tag_to_ids.items(), key=lambda x: -len(x[1])):
        if len(ids) < 3:
            continue
        clusters.append({
            "label": tag,
            "size": len(ids),
            "member_ids": ids[:10],
        })

    # Count singletons: entries whose tags all appear on only 1 memory
    clustered_ids = set()
    for c in clusters:
        clustered_ids.update(c["member_ids"])
    singleton_count = sum(
        1 for e in entries if e["id"] not in clustered_ids
    )

    return {
        "clusters": clusters[:30],  # cap at 30 for readability
        "singleton_count": singleton_count,
        "largest_cluster_size": clusters[0]["size"] if clusters else 0,
        "cluster_count": len(clusters),
    }


def _stale_memory_scan(entries, now):
    """Identify memories that look stale or outdated.

    Three signals:
    1. Age > STALE_THRESHOLD_DAYS AND content contains old session references
    2. Content uses language indicating a superseded state
    3. Tagged as possible-dupe (surviving the dedup soft zone)

    Returns:
        {
            "stale_count": int,
            "stale_entries": [
                {
                    "id": str,
                    "age_days": float,
                    "signals": [str, ...],
                    "preview": str,
                    "tags": str,
                },
                ...
            ],
        }
    """
    stale = []

    for entry in entries:
        age = _age_days(entry["timestamp"], now)
        signals = []

        doc = entry["document"]

        # Signal 1: old age with session reference
        if age is not None and age > STALE_THRESHOLD_DAYS:
            if _has_session_reference(doc):
                signals.append(f"age={age:.0f}d + session_reference")

        # Signal 2: superseded language
        if _has_superseded_language(doc):
            signals.append("superseded_language")

        # Signal 3: possible-dupe tag
        tags = _split_tags(entry["tags"])
        dupe_tags = [t for t in tags if t.startswith(_POSSIBLE_DUPE_TAG_PREFIX)]
        if dupe_tags:
            signals.append(f"possible_dupe={dupe_tags[0]}")

        if signals:
            stale.append({
                "id": entry["id"],
                "age_days": round(age, 1) if age is not None else None,
                "signals": signals,
                "preview": (entry["preview"] or doc[:100]).strip(),
                "tags": entry["tags"],
            })

    return {
        "stale_count": len(stale),
        "stale_entries": stale,
    }


def _build_recommendations(count_stats, tag_dist, stale_scan, groups):
    """Generate human-readable recommendations from analysis results."""
    recs = []
    total = count_stats["total"]

    # Volume check
    if total > 1000:
        recs.append(
            f"Collection has {total} memories. Consider running deduplicate_sweep() "
            "to prune soft-duplicate entries before the count grows further."
        )

    # Age distribution
    buckets = count_stats["age_buckets"]
    stale_old = buckets.get("stale_181d_plus", 0)
    if stale_old > 50:
        recs.append(
            f"{stale_old} memories are older than 180 days. "
            "Review cleanup_candidates() for archive recommendations."
        )

    # Quarantine size
    qc = count_stats.get("quarantine_count")
    if qc is not None and qc > 200:
        recs.append(
            f"Quarantine collection holds {qc} entries. "
            "If confident in dedup accuracy, these can be permanently cleared."
        )

    # Untagged memories
    untagged = tag_dist.get("untagged_count", 0)
    if untagged > 0:
        recs.append(
            f"{untagged} memories have no tags. "
            "Tagging improves search recall and category health monitoring."
        )

    # Possible-dupe tags
    dupe_count = tag_dist.get("possible_dupe_count", 0)
    if dupe_count > 20:
        recs.append(
            f"{dupe_count} memories carry a 'possible-dupe' tag from the soft-dedup zone. "
            "Run deduplicate_sweep(dry_run=False) to quarantine confirmed duplicates."
        )

    # Underrepresented categories
    under = tag_dist.get("underrepresented_categories", [])
    if under:
        recs.append(
            f"Underrepresented tag categories (< {UNDERREPRESENTED_SHARE*100:.0f}% share): "
            + ", ".join(under[:8])
            + ". Consider whether gaps reflect genuine absence or missed tagging."
        )

    # Stale entries
    stale_cnt = stale_scan.get("stale_count", 0)
    if stale_cnt > 0:
        recs.append(
            f"{stale_cnt} memories show staleness signals (old session references, "
            "superseded language, or possible-dupe tags). See cleanup_candidates()."
        )

    # Large clusters
    if groups["largest_cluster_size"] > 50:
        top_cluster = groups["clusters"][0] if groups["clusters"] else {}
        recs.append(
            f"Tag cluster '{top_cluster.get('label', '?')}' has "
            f"{groups['largest_cluster_size']} members. "
            "High concentration may indicate a specific project dominated the corpus; "
            "verify those memories are still relevant."
        )

    if not recs:
        recs.append("Memory collection looks healthy. No urgent actions required.")

    return recs


# ── Public API ────────────────────────────────────────────────────────────────


def analyze_memory_health():
    """Run a full health analysis of the knowledge memory collection.

    Checks memory count, tag distribution, age distribution, tag clusters,
    underrepresented categories, and stale memory signals. Read-only.

    Returns:
        {
            "timestamp": float,           # epoch seconds
            "duration_ms": float,
            "status": "ok" | "degraded" | "error",
            "error": str | None,          # populated only on failure
            "count_stats": { ... },       # see _count_stats
            "tag_distribution": { ... },  # see _tag_distribution
            "similarity_groups": { ... }, # see _similarity_groups
            "stale_scan": { ... },        # see _stale_memory_scan
            "recommendations": [str, ...],
            "summary": str,               # one-line plain-text overview
        }

    Fails open: on any error, returns a minimal dict with status="error"
    and the error message rather than raising.
    """
    t0 = time.monotonic()
    now = datetime.now(timezone.utc)

    try:
        entries = _safe_fetch_all("knowledge")
        if not entries:
            return {
                "timestamp": time.time(),
                "duration_ms": round((time.monotonic() - t0) * 1000, 2),
                "status": "degraded",
                "error": (
                    "Could not fetch entries — UDS worker may be offline "
                    "or collection empty"
                ),
                "count_stats": {"total": 0},
                "tag_distribution": {},
                "similarity_groups": {},
                "stale_scan": {"stale_count": 0, "stale_entries": []},
                "recommendations": [
                    "Memory worker appears offline. Start memory_server.py and retry."
                ],
                "summary": "Degraded — no entries retrieved",
            }

        count_stats = _count_stats(entries, now)
        tag_dist = _tag_distribution(entries)
        groups = _similarity_groups(entries)
        stale_scan = _stale_memory_scan(entries, now)
        recs = _build_recommendations(count_stats, tag_dist, stale_scan, groups)

        total = count_stats["total"]
        stale_cnt = stale_scan["stale_count"]
        median_age = count_stats.get("median_age_days")
        if median_age is not None:
            summary = (
                f"{total} memories | median age {median_age:.0f}d | "
                f"{stale_cnt} stale | {tag_dist['untagged_count']} untagged | "
                f"{tag_dist['possible_dupe_count']} possible-dupes"
            )
        else:
            summary = (
                f"{total} memories | {stale_cnt} stale | "
                f"{tag_dist['untagged_count']} untagged"
            )

        status = "ok"
        if stale_cnt > 50 or tag_dist["untagged_count"] > 20:
            status = "degraded"

        duration_ms = round((time.monotonic() - t0) * 1000, 2)
        return {
            "timestamp": time.time(),
            "duration_ms": duration_ms,
            "status": status,
            "error": None,
            "count_stats": count_stats,
            "tag_distribution": tag_dist,
            "similarity_groups": groups,
            "stale_scan": stale_scan,
            "recommendations": recs,
            "summary": summary,
        }

    except Exception as exc:
        import traceback
        return {
            "timestamp": time.time(),
            "duration_ms": round((time.monotonic() - t0) * 1000, 2),
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}",
            "count_stats": {},
            "tag_distribution": {},
            "similarity_groups": {},
            "stale_scan": {"stale_count": 0, "stale_entries": []},
            "recommendations": [],
            "summary": f"Error during analysis: {exc}",
        }


def cleanup_candidates():
    """Return a list of memory IDs that are safe candidates for archiving.

    Selection criteria (three tiers, in priority order):
    1. STRONG: age > ANCIENT_THRESHOLD_DAYS AND (session reference OR superseded language)
    2. MODERATE: age > STALE_THRESHOLD_DAYS AND superseded language
    3. SOFT: possible-dupe tag present (soft-dedup zone survivors)

    No memory is modified. Callers may pass these IDs to deduplicate_sweep()
    or a future archive tool.

    Returns:
        [
            {
                "id": str,
                "tier": "strong" | "moderate" | "soft",
                "reason": str,
                "age_days": float | None,
                "preview": str,
                "tags": str,
            },
            ...
        ]
    Sorted by tier (strong first) then by age descending (oldest first).
    Fails open: returns [] on any error.
    """
    try:
        entries = _safe_fetch_all("knowledge")
        if not entries:
            return []

        now = datetime.now(timezone.utc)
        candidates = []
        seen_ids = set()

        for entry in entries:
            if entry["id"] in seen_ids:
                continue

            age = _age_days(entry["timestamp"], now)
            doc = entry["document"]
            tags = _split_tags(entry["tags"])
            dupe_tags = [t for t in tags if t.startswith(_POSSIBLE_DUPE_TAG_PREFIX)]

            has_session_ref = _has_session_reference(doc)
            has_superseded = _has_superseded_language(doc)

            tier = None
            reason_parts = []

            # Tier 1: STRONG — very old with explicit session reference or superseded language
            if age is not None and age > ANCIENT_THRESHOLD_DAYS:
                if has_session_ref:
                    tier = "strong"
                    reason_parts.append(
                        f"age={age:.0f}d > {ANCIENT_THRESHOLD_DAYS}d + session_reference"
                    )
                elif has_superseded:
                    tier = "strong"
                    reason_parts.append(
                        f"age={age:.0f}d > {ANCIENT_THRESHOLD_DAYS}d + superseded_language"
                    )

            # Tier 2: MODERATE — stale with superseded language
            if (
                tier is None
                and age is not None
                and age > STALE_THRESHOLD_DAYS
                and has_superseded
            ):
                tier = "moderate"
                reason_parts.append(
                    f"age={age:.0f}d > {STALE_THRESHOLD_DAYS}d + superseded_language"
                )

            # Tier 3: SOFT — possible-dupe tag
            if tier is None and dupe_tags:
                tier = "soft"
                reason_parts.append(f"possible_dupe_tag={dupe_tags[0]}")

            if tier is not None:
                preview = (entry["preview"] or doc[:100]).strip()
                candidates.append({
                    "id": entry["id"],
                    "tier": tier,
                    "reason": "; ".join(reason_parts),
                    "age_days": round(age, 1) if age is not None else None,
                    "preview": preview[:120],
                    "tags": entry["tags"],
                })
                seen_ids.add(entry["id"])

        # Sort: strong first, then moderate, then soft; within each tier oldest first
        tier_order = {"strong": 0, "moderate": 1, "soft": 2}
        candidates.sort(
            key=lambda c: (
                tier_order.get(c["tier"], 9),
                -(c["age_days"] or 0),
            )
        )
        return candidates

    except Exception:
        return []


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Torus Memory Maintenance — read-only health analysis"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output full report as JSON"
    )
    parser.add_argument(
        "--candidates", action="store_true",
        help="Show cleanup candidates only (skip full analysis)"
    )
    parser.add_argument(
        "--top", type=int, default=20,
        help="Max candidates to show (default: 20)"
    )
    args = parser.parse_args()

    if args.candidates:
        candidates = cleanup_candidates()
        if args.json:
            print(json.dumps(candidates[:args.top], indent=2))
        else:
            print(
                f"Cleanup candidates ({min(len(candidates), args.top)} "
                f"of {len(candidates)}):"
            )
            for c in candidates[:args.top]:
                age_str = (
                    f"{c['age_days']:.0f}d" if c["age_days"] is not None else "age=?"
                )
                print(
                    f"  [{c['tier'].upper():8s}] {c['id']}  {age_str}  {c['reason']}"
                )
                print(f"             preview: {c['preview'][:80]}")
    else:
        report = analyze_memory_health()

        if args.json:
            # Omit stale_entries list from JSON to keep output manageable
            compact = dict(report)
            if "stale_scan" in compact:
                compact["stale_scan"] = {
                    k: v for k, v in compact["stale_scan"].items()
                    if k != "stale_entries"
                }
            print(json.dumps(compact, indent=2))
        else:
            status = report["status"].upper()
            print(f"Memory Health: {status} ({report['duration_ms']:.0f}ms)")
            print(f"  {report['summary']}")
            print()

            cs = report.get("count_stats", {})
            buckets = cs.get("age_buckets", {})
            if buckets:
                print("Age distribution:")
                print(f"  0-30d   : {buckets.get('fresh_0_30d', 0)}")
                print(f"  31-90d  : {buckets.get('recent_31_90d', 0)}")
                print(f"  91-180d : {buckets.get('aging_91_180d', 0)}")
                print(f"  181d+   : {buckets.get('stale_181d_plus', 0)}")
                print(f"  unknown : {buckets.get('unknown_age', 0)}")
                if cs.get("quarantine_count") is not None:
                    print(f"  quarantine: {cs['quarantine_count']}")
                print()

            td = report.get("tag_distribution", {})
            if td:
                print(
                    f"Tags: {td.get('total_unique_tags', 0)} unique | "
                    f"avg {td.get('avg_tags_per_memory', 0)} per memory | "
                    f"{td.get('untagged_count', 0)} untagged | "
                    f"{td.get('possible_dupe_count', 0)} possible-dupes"
                )
                under = td.get("underrepresented_categories", [])
                if under:
                    print(f"  Underrepresented: {', '.join(under[:6])}")
                print()

            sg = report.get("similarity_groups", {})
            if sg:
                print(
                    f"Tag clusters: {sg.get('cluster_count', 0)} clusters | "
                    f"largest={sg.get('largest_cluster_size', 0)} | "
                    f"singletons={sg.get('singleton_count', 0)}"
                )
                print()

            recs = report.get("recommendations", [])
            if recs:
                print("Recommendations:")
                for r in recs:
                    print(f"  - {r}")
