#!/usr/bin/env python3
"""Tests for shared/memory_consolidation.py"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.memory_consolidation import (
    find_merge_candidates, generate_merged_content,
    find_promotion_candidates, find_archive_candidates,
    run_consolidation_analysis, ConsolidationAction, ConsolidationReport,
)

passed = failed = 0

def test(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name} — {detail}")


print("\n--- Consolidation: find_merge_candidates ---")

entries = [
    {"id": "a1", "document": "The gate router uses Q-learning to reorder gates by block probability for optimal early exit", "tags": ""},
    {"id": "a2", "document": "Gate router Q-learning reorders gates based on their block probability to enable early exit performance", "tags": ""},
    {"id": "a3", "document": "Python best practices for testing include pytest fixtures and parametrize decorators", "tags": ""},
]
merges = find_merge_candidates(entries, threshold=0.4)
test("Found merge group for similar docs", len(merges) >= 1, f"got {len(merges)} groups")
if merges:
    test("Merge group has 2 IDs", len(merges[0].memory_ids) == 2, f"got {merges[0].memory_ids}")
    test("Dissimilar doc not merged", "a3" not in merges[0].memory_ids)

# Empty/single input
test("Empty returns empty", find_merge_candidates([]) == [])
test("Single returns empty", find_merge_candidates([{"id": "x", "document": "test"}]) == [])

print("\n--- Consolidation: generate_merged_content ---")

docs = [
    "The memory system uses LanceDB for vector storage. It supports semantic search.",
    "LanceDB is used for vector storage in the memory system. Cosine similarity is the distance metric.",
]
merged = generate_merged_content(docs)
test("Merged content non-empty", len(merged) > 0)
test("Contains unique info", "cosine" in merged.lower() or "distance" in merged.lower(),
     f"merged: {merged[:100]}")

# Dedup check
docs2 = [
    "The sky is blue and the grass is green.",
    "The sky is blue and the grass is green.",
]
merged2 = generate_merged_content(docs2)
test("Near-duplicate sentences deduped", merged2.count("sky is blue") <= 1,
     f"count={merged2.count('sky is blue')}")

print("\n--- Consolidation: find_promotion_candidates ---")

entries_promo = [
    {"id": "p1", "tier": 2, "retrieval_count": 15, "tags": "type:fix", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ")},
    {"id": "p2", "tier": 1, "retrieval_count": 20, "tags": "type:fix", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ")},
    {"id": "p3", "tier": 2, "retrieval_count": 2, "tags": "", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ")},
]
promos = find_promotion_candidates(entries_promo)
# p1 should qualify (tier 2, high accesses, recent = high relevance)
# p2 should not (already tier 1)
# p3 should not (low accesses)
test("High-access tier-2 promoted", any(p.memory_ids == ["p1"] for p in promos), f"promos={[p.memory_ids for p in promos]}")
test("Tier 1 not promoted", not any(p.memory_ids == ["p2"] for p in promos))
test("Low-access not promoted", not any(p.memory_ids == ["p3"] for p in promos))

print("\n--- Consolidation: find_archive_candidates ---")

from datetime import datetime, timezone, timedelta
old_ts = (datetime.now(timezone.utc) - timedelta(days=200)).strftime("%Y-%m-%dT%H:%M:%SZ")
entries_archive = [
    {"id": "ar1", "tier": 3, "retrieval_count": 0, "tags": "", "timestamp": old_ts},
    {"id": "ar2", "tier": 1, "retrieval_count": 0, "tags": "", "timestamp": old_ts},
]
archives = find_archive_candidates(entries_archive)
# ar1 and ar2 both old with 0 retrievals, should have low relevance
test("Old low-retrieval archived", len(archives) >= 1, f"got {len(archives)}")

# LTP protection prevents archival
archives_ltp = find_archive_candidates(entries_archive, ltp_statuses={"ar1": "full", "ar2": "full"})
test("LTP prevents archive", len(archives_ltp) == 0, f"got {len(archives_ltp)}")

print("\n--- Consolidation: run_consolidation_analysis ---")

all_entries = entries + entries_promo + entries_archive
report = run_consolidation_analysis(all_entries)
test("Report is ConsolidationReport", isinstance(report, ConsolidationReport))
test("Summary non-empty", len(report.summary) > 0)
test("Duration tracked", report.duration_ms >= 0)
test("Timestamp set", report.timestamp > 0)

print(f"\n{'='*40}")
print(f"Memory Consolidation: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
