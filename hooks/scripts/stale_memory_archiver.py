#!/usr/bin/env python3
"""Stale Memory Archiver — Identifies and demotes old, low-value memories.

Scans LanceDB knowledge table for memories that are:
1. Older than a configurable threshold (default 90 days)
2. Likely low-value based on heuristics (short text, no tags, low tier)

Demoted memories get moved to tier 3 (low priority) so they rank lower
in search results without being deleted.

Usage:
    python3 stale_memory_archiver.py                    # Dry run
    python3 stale_memory_archiver.py --execute          # Actually demote
    python3 stale_memory_archiver.py --days 60          # Custom age threshold
    python3 stale_memory_archiver.py --min-text-len 50  # Custom text threshold

Public API:
    from scripts.stale_memory_archiver import scan_stale, archive_stale
    stale = scan_stale(days=90, min_text_len=30)
    result = archive_stale(stale, dry_run=True)
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

# Add hooks dir to path
_HOOKS_DIR = os.path.join(os.path.expanduser("~"), ".claude", "hooks")
if _HOOKS_DIR not in sys.path:
    sys.path.insert(0, _HOOKS_DIR)

MEMORY_DIR = os.path.join(os.path.expanduser("~"), "data", "memory")
LANCE_DIR = os.path.join(MEMORY_DIR, "lancedb")

# Heuristic weights for staleness scoring
SCORE_AGE_WEIGHT = 0.4       # Age contributes 40%
SCORE_LENGTH_WEIGHT = 0.3    # Short text = more likely stale
SCORE_TAGS_WEIGHT = 0.15     # No tags = more likely stale
SCORE_TIER_WEIGHT = 0.15     # Already low tier = more likely stale

# Thresholds
DEFAULT_AGE_DAYS = 90
DEFAULT_MIN_TEXT_LEN = 30
STALE_SCORE_THRESHOLD = 0.6  # Entries scoring above this are "stale"


def _open_table(table_name="knowledge"):
    """Open a LanceDB table."""
    try:
        import lancedb
        db = lancedb.connect(LANCE_DIR)
        return db.open_table(table_name)
    except Exception as e:
        print(f"[ARCHIVER] Cannot open table '{table_name}': {e}", file=sys.stderr)
        return None


def _parse_timestamp(ts_str):
    """Parse an ISO timestamp string to datetime. Returns None on failure."""
    if not ts_str:
        return None
    for fmt in ["%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]:
        try:
            return datetime.strptime(ts_str[:26], fmt)
        except (ValueError, TypeError):
            continue
    return None


def _staleness_score(age_days, text_len, has_tags, tier, max_age_days=365):
    """Compute a staleness score from 0.0 (fresh) to 1.0 (very stale).

    Factors:
    - Age: linear scale, capped at max_age_days
    - Text length: shorter = more likely stale/low-value
    - Tags: no tags = slightly more likely stale
    - Tier: already tier 3 = already low priority (skip)
    """
    # Already tier 3 — no need to demote further
    if tier >= 3:
        return 0.0

    age_score = min(1.0, age_days / max_age_days) if max_age_days > 0 else 0.0
    length_score = max(0.0, 1.0 - (text_len / 200.0))  # Longer = less stale
    tags_score = 0.0 if has_tags else 1.0
    tier_score = 0.0 if tier == 1 else 0.5  # Tier 1 is important

    return (
        age_score * SCORE_AGE_WEIGHT
        + length_score * SCORE_LENGTH_WEIGHT
        + tags_score * SCORE_TAGS_WEIGHT
        + tier_score * SCORE_TIER_WEIGHT
    )


def scan_stale(table_name="knowledge", days=DEFAULT_AGE_DAYS, min_text_len=DEFAULT_MIN_TEXT_LEN):
    """Scan for stale memories that should be demoted.

    Args:
        table_name: LanceDB table to scan
        days: Age threshold in days
        min_text_len: Minimum text length (shorter = more likely stale)

    Returns:
        List of dicts: [{id, text_preview, age_days, staleness_score, tier, tags}]
    """
    table = _open_table(table_name)
    if table is None:
        return []

    try:
        df = table.to_pandas()
    except Exception as e:
        print(f"[ARCHIVER] Failed to read table: {e}", file=sys.stderr)
        return []

    now = datetime.now()
    cutoff = now - timedelta(days=days)
    stale_entries = []

    for _, row in df.iterrows():
        ts_str = str(row.get("timestamp", ""))
        ts = _parse_timestamp(ts_str)
        if ts is None or ts > cutoff:
            continue  # Not old enough

        text = str(row.get("text", ""))
        tags = str(row.get("tags", ""))
        tier = int(row.get("tier", 2)) if "tier" in df.columns else 2
        age_days = (now - ts).days

        score = _staleness_score(
            age_days=age_days,
            text_len=len(text),
            has_tags=bool(tags.strip()),
            tier=tier,
        )

        if score >= STALE_SCORE_THRESHOLD:
            stale_entries.append({
                "id": str(row.get("id", "")),
                "text_preview": text[:100],
                "age_days": age_days,
                "staleness_score": round(score, 3),
                "tier": tier,
                "tags": tags[:50] if tags else "",
                "text_len": len(text),
            })

    # Sort by staleness score descending
    stale_entries.sort(key=lambda x: x["staleness_score"], reverse=True)

    print(f"[ARCHIVER] Found {len(stale_entries)} stale entries "
          f"(>{days} days, score>{STALE_SCORE_THRESHOLD}) out of {len(df)} total")

    return stale_entries


def archive_stale(stale_entries, table_name="knowledge", dry_run=True):
    """Demote stale entries to tier 3.

    Args:
        stale_entries: Output from scan_stale()
        table_name: LanceDB table
        dry_run: If True, only report what would happen

    Returns:
        Dict with archival results.
    """
    if not stale_entries:
        return {"archived": 0, "dry_run": dry_run}

    if dry_run:
        return {
            "archived": len(stale_entries),
            "dry_run": True,
            "entries": stale_entries[:20],
        }

    table = _open_table(table_name)
    if table is None:
        return {"error": "Cannot open table"}

    archived = 0
    for entry in stale_entries:
        try:
            table.update(
                where=f"id = '{entry['id']}'",
                values={"tier": 3},
            )
            archived += 1
        except Exception as e:
            print(f"[ARCHIVER] Failed to demote {entry['id']}: {e}", file=sys.stderr)

    return {
        "archived": archived,
        "dry_run": False,
        "entries": stale_entries[:20],
    }


def format_report(stale_entries, result):
    """Format archival result as readable report."""
    mode = "DRY RUN" if result.get("dry_run") else "EXECUTED"
    lines = [
        f"Stale Memory Archiver Report ({mode})",
        "=" * 50,
        f"Entries to demote: {result.get('archived', 0)}",
        "",
    ]

    if stale_entries:
        lines.append("Top stale entries:")
        for i, entry in enumerate(stale_entries[:15], 1):
            lines.append(
                f"  {i}. [{entry['staleness_score']:.2f}] "
                f"age={entry['age_days']}d tier={entry['tier']} "
                f"len={entry['text_len']}"
            )
            lines.append(f"     {entry['text_preview'][:80]}...")
        lines.append("")

    lines.append("=" * 50)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Stale Memory Archiver")
    parser.add_argument("--execute", action="store_true", help="Actually demote (default: dry run)")
    parser.add_argument("--days", type=int, default=DEFAULT_AGE_DAYS, help=f"Age threshold (default: {DEFAULT_AGE_DAYS})")
    parser.add_argument("--min-text-len", type=int, default=DEFAULT_MIN_TEXT_LEN, help=f"Min text length (default: {DEFAULT_MIN_TEXT_LEN})")
    parser.add_argument("--table", default="knowledge", help="Table to scan")
    args = parser.parse_args()

    print(f"[ARCHIVER] Starting {'execution' if args.execute else 'dry run'}...")
    print(f"[ARCHIVER] Table: {args.table}, Age: {args.days}d")
    print()

    stale = scan_stale(args.table, args.days, args.min_text_len)
    result = archive_stale(stale, args.table, dry_run=not args.execute)
    print(format_report(stale, result))


if __name__ == "__main__":
    main()
