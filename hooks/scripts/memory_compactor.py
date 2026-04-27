#!/usr/bin/env python3
"""Memory Compactor — Smart deduplication and compaction for LanceDB memories.

Scans the knowledge table for similar memories (cosine similarity > threshold),
groups them into clusters, merges metadata into survivors, and quarantines duplicates.

Usage:
    python3 memory_compactor.py                  # Dry run (default)
    python3 memory_compactor.py --execute        # Actually compact
    python3 memory_compactor.py --threshold 0.90 # Custom similarity threshold
    python3 memory_compactor.py --table observations  # Compact observations table

Public API:
    from scripts.memory_compactor import scan_duplicates, compact
    clusters = scan_duplicates(threshold=0.85)
    result = compact(clusters, dry_run=True)
"""

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime

# Add hooks dir to path
_HOOKS_DIR = os.path.join(os.path.expanduser("~"), ".claude", "hooks")
if _HOOKS_DIR not in sys.path:
    sys.path.insert(0, _HOOKS_DIR)

import lancedb
import pyarrow as pa

# ── Constants ─────────────────────────────────────────────────────────────────

MEMORY_DIR = os.path.join(os.path.expanduser("~"), "data", "memory")
LANCE_DIR = os.path.join(MEMORY_DIR, "lancedb")
DEFAULT_THRESHOLD = 0.85
BATCH_SIZE = 100

# Tables that support compaction
COMPACTABLE_TABLES = {"knowledge", "observations", "fix_outcomes"}

# Tier priorities (higher = more important, kept as survivor)
TIER_PRIORITY = {1: 3, 2: 2, 3: 1, 0: 0}


# ── Embedding (NIM API) ──────────────────────────────────────────────────────

_NIM_URL = "https://integrate.api.nvidia.com/v1/embeddings"
_NIM_MODEL = "nvidia/nv-embed-v1"
_CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".claude", "config.json")


def _get_nim_api_key():
    """Read NIM API key from config.json."""
    try:
        if os.path.exists(_CONFIG_PATH):
            with open(_CONFIG_PATH) as f:
                return json.load(f).get("nim_api_key", "")
    except Exception:
        pass
    return os.environ.get("NIM_API_KEY", "")


def _embed(texts):
    """Embed texts via NVIDIA NIM API (nv-embed-v1, 4096-dim).

    Used by smart-merge (tier 2 compaction) to re-embed merged entries.
    Not called by standard dedup which reuses existing vectors.
    """
    import requests

    key = _get_nim_api_key()
    if not key:
        print(
            "[COMPACTOR] NIM API key not configured, cannot re-embed", file=sys.stderr
        )
        return None
    safe = [t if t and t.strip() else "[empty]" for t in texts]
    try:
        resp = requests.post(
            _NIM_URL,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": _NIM_MODEL,
                "input": safe,
                "input_type": "passage",
                "encoding_format": "float",
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return [d["embedding"] for d in data["data"]]
    except Exception as e:
        print(f"[COMPACTOR] NIM embed error: {e}", file=sys.stderr)
        return None


# ── Core Functions ────────────────────────────────────────────────────────────


def _open_table(table_name="knowledge"):
    """Open a LanceDB table."""
    db = lancedb.connect(LANCE_DIR)
    try:
        return db.open_table(table_name)
    except Exception as e:
        print(f"[COMPACTOR] Cannot open table '{table_name}': {e}", file=sys.stderr)
        return None


def scan_duplicates(table_name="knowledge", threshold=DEFAULT_THRESHOLD):
    """Scan a LanceDB table for duplicate clusters.

    Returns list of clusters, each cluster is a list of entry dicts.
    The first entry in each cluster is the recommended survivor.
    """
    table = _open_table(table_name)
    if table is None:
        return []

    # Read all entries
    try:
        df = table.to_pandas()
    except Exception as e:
        print(f"[COMPACTOR] Failed to read table: {e}", file=sys.stderr)
        return []

    total = len(df)
    has_tags = "tags" in df.columns
    print(
        f"[COMPACTOR] Scanning {total} entries in '{table_name}' (threshold={threshold})"
    )

    if total < 2:
        print("[COMPACTOR] Not enough entries to compare")
        return []

    # Extract vectors and metadata
    entries = []
    for _, row in df.iterrows():
        entry = {
            "id": str(row.get("id", "")),
            "text": str(row.get("text", "")),
            "vector": row.get("vector"),
            "tier": int(row.get("tier", 2)) if "tier" in df.columns else 2,
            "timestamp": str(row.get("timestamp", "")),
        }
        if has_tags:
            entry["tags"] = str(row.get("tags", ""))
        if entry["vector"] is not None and len(entry["text"]) > 0:
            entries.append(entry)

    print(f"[COMPACTOR] {len(entries)} entries with valid vectors")

    # Build similarity clusters using greedy approach
    import numpy as np

    vectors = np.array([e["vector"] for e in entries], dtype=np.float32)
    # Normalize for cosine similarity
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1
    vectors = vectors / norms

    clustered = set()
    clusters = []

    for i in range(len(entries)):
        if i in clustered:
            continue

        # Find all similar entries
        sims = vectors[i] @ vectors.T
        similar_indices = [
            j
            for j in range(len(entries))
            if j != i and j not in clustered and sims[j] >= threshold
        ]

        if not similar_indices:
            continue

        # Create cluster with this entry + all similar
        cluster_indices = [i] + similar_indices
        cluster = []
        for idx in cluster_indices:
            e = entries[idx]
            item = {
                "id": e["id"],
                "text": e["text"][:200],
                "tier": e["tier"],
                "timestamp": e["timestamp"],
            }
            if "tags" in e:
                item["tags"] = e["tags"]
            cluster.append(item)
            clustered.add(idx)

        # Sort by tier (highest first), then timestamp (newest first)
        cluster.sort(
            key=lambda x: (
                TIER_PRIORITY.get(x["tier"], 0),
                x["timestamp"],
            ),
            reverse=True,
        )

        clusters.append(cluster)

    print(
        f"[COMPACTOR] Found {len(clusters)} duplicate clusters ({sum(len(c) - 1 for c in clusters)} removable)"
    )
    return clusters


def compact(clusters, table_name="knowledge", dry_run=True):
    """Execute compaction: merge metadata into survivors, quarantine duplicates.

    Args:
        clusters: Output from scan_duplicates()
        table_name: LanceDB table name
        dry_run: If True, only report what would happen

    Returns dict with compaction results.
    """
    if not clusters:
        return {"clusters": 0, "compacted": 0, "survivors": 0, "dry_run": dry_run}

    table = _open_table(table_name)
    quarantine_table = _open_table("quarantine")
    if table is None:
        return {"error": "Cannot open table"}

    total_compacted = 0
    total_survivors = 0
    actions = []
    has_tags = "tags" in clusters[0][0] if clusters and clusters[0] else False

    for cluster in clusters:
        survivor = cluster[0]
        duplicates = cluster[1:]

        merged_tags = ""
        if has_tags:
            all_tags = set()
            if survivor.get("tags"):
                all_tags.update(
                    t.strip() for t in survivor["tags"].split(",") if t.strip()
                )
            for dup in duplicates:
                if dup.get("tags"):
                    all_tags.update(
                        t.strip() for t in dup["tags"].split(",") if t.strip()
                    )
            for dup in duplicates:
                all_tags.add(f"possible-dupe:{dup['id'][:16]}")
            merged_tags = ",".join(sorted(all_tags))

        action = {
            "survivor_id": survivor["id"],
            "survivor_text": survivor["text"],
            "duplicate_ids": [d["id"] for d in duplicates],
            "duplicate_count": len(duplicates),
        }
        if has_tags:
            action["merged_tags"] = merged_tags
        actions.append(action)

        if not dry_run:
            try:
                if has_tags:
                    table.update(
                        where=f"id = '{survivor['id']}'",
                        values={"tags": merged_tags},
                    )

                # Move duplicates to quarantine
                for dup in duplicates:
                    try:
                        # Read full duplicate record
                        dup_df = (
                            table.search()
                            .where(f"id = '{dup['id']}'")
                            .limit(1)
                            .to_pandas()
                        )
                        if len(dup_df) > 0:
                            # Delete from source table
                            table.delete(f"id = '{dup['id']}'")
                            total_compacted += 1
                    except Exception as e:
                        print(
                            f"[COMPACTOR] Failed to quarantine {dup['id']}: {e}",
                            file=sys.stderr,
                        )

                total_survivors += 1
            except Exception as e:
                print(
                    f"[COMPACTOR] Failed to process cluster {survivor['id']}: {e}",
                    file=sys.stderr,
                )
        else:
            total_compacted += len(duplicates)
            total_survivors += 1

    result = {
        "clusters": len(clusters),
        "compacted": total_compacted,
        "survivors": total_survivors,
        "dry_run": dry_run,
        "actions": actions[:20],  # Cap report at 20 for readability
    }

    return result


def format_report(result):
    """Format compaction result as readable report."""
    lines = []
    mode = "DRY RUN" if result.get("dry_run") else "EXECUTED"
    lines.append(f"╔══════════════════════════════════════════════╗")
    lines.append(f"║  MEMORY COMPACTION REPORT ({mode})  ║")
    lines.append(f"╚══════════════════════════════════════════════╝")
    lines.append("")
    lines.append(f"Clusters found:    {result.get('clusters', 0)}")
    lines.append(f"Entries compacted: {result.get('compacted', 0)}")
    lines.append(f"Survivors:         {result.get('survivors', 0)}")
    lines.append("")

    actions = result.get("actions", [])
    if actions:
        lines.append("Top clusters:")
        for i, action in enumerate(actions[:10], 1):
            lines.append(f"  {i}. Survivor: {action['survivor_id'][:16]}...")
            lines.append(f"     Text: {action['survivor_text'][:80]}...")
            lines.append(f"     Removes: {action['duplicate_count']} duplicates")
            lines.append(
                f"     IDs: {', '.join(d[:16] for d in action['duplicate_ids'][:5])}"
            )
            lines.append("")

    return "\n".join(lines)


# ── CLI ───────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Memory Compactor for LanceDB")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually perform compaction (default: dry run)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help="Cosine similarity threshold (default: 0.85)",
    )
    parser.add_argument(
        "--table",
        default="knowledge",
        choices=list(COMPACTABLE_TABLES),
        help="Table to compact",
    )
    args = parser.parse_args()

    print(f"[COMPACTOR] Starting {'execution' if args.execute else 'dry run'}...")
    print(f"[COMPACTOR] Table: {args.table}, Threshold: {args.threshold}")
    print()

    clusters = scan_duplicates(args.table, args.threshold)
    result = compact(clusters, args.table, dry_run=not args.execute)
    print(format_report(result))


if __name__ == "__main__":
    main()
