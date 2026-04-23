#!/usr/bin/env python3
"""Tests for shared/skill_search.py — BM25 + embedding hybrid search."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.skill_search import BM25Index, EmbeddingIndex, HybridSearch

passed = failed = 0


def test(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name} -- {detail}")


# ── Test corpus ──
SKILLS = {
    "commit": "Quick git commit with auto-generated message. Stage changes, create commit.",
    "review": "Code quality and convention check. Analyze diffs, suggest improvements.",
    "test": "Run, write, and debug tests. Execute test suites, report failures.",
    "brainstorm": "Design exploration and option generation. Generate multiple approaches.",
    "implement": "Execute implementation plans. Write code following TDD approach.",
    "wrap-up": "Session end protocol. Save state, write summary, commit changes.",
    "learn": "Learn from URLs or topics. Research and save findings to memory.",
    "benchmark": "Measure and track framework performance metrics over time.",
}


# ── BM25 Index ──
print("\n--- skill_search: BM25 Index ---")

bm25 = BM25Index()
for name, desc in SKILLS.items():
    bm25.add(name, f"{name} {desc}")

results = bm25.search("git commit message", top_k=3)
test("BM25 returns results", len(results) > 0)
test(
    "BM25 commit ranked first",
    results[0][0] == "commit",
    f"got {results[0][0] if results else 'empty'}",
)
test("BM25 returns tuples (name, score)", len(results[0]) == 2)
test("BM25 scores are floats", isinstance(results[0][1], float))

# Should match test for "test suites failures"
results2 = bm25.search("test suites failures", top_k=3)
test(
    "BM25 test query matches test skill",
    results2[0][0] == "test",
    f"got {results2[0][0] if results2 else 'empty'}",
)

# Empty query
results3 = bm25.search("", top_k=3)
test("BM25 empty query returns empty", len(results3) == 0)

# Rebuild after add
bm25.add("deploy", "Deploy application to production servers")
results4 = bm25.search("deploy production", top_k=1)
test(
    "BM25 finds newly added skill",
    results4[0][0] == "deploy",
    f"got {results4[0][0] if results4 else 'empty'}",
)


# ── Embedding Index ──
print("\n--- skill_search: Embedding Index ---")

emb = EmbeddingIndex()
for name, desc in SKILLS.items():
    emb.add(name, f"{name} {desc}")

results = emb.search("version control commit changes", top_k=3)
test("Embedding returns results", len(results) > 0)
test(
    "Embedding commit in top 3",
    "commit" in [r[0] for r in results],
    f"got {[r[0] for r in results]}",
)
test(
    "Embedding scores between 0 and 1",
    all(0 <= r[1] <= 1.01 for r in results),
    f"scores: {[r[1] for r in results]}",
)

# Semantic match: "improve code quality" should rank review high
results2 = emb.search("improve code quality review", top_k=3)
test(
    "Embedding review for quality query",
    "review" in [r[0] for r in results2],
    f"got {[r[0] for r in results2]}",
)

# Empty index search
emb_empty = EmbeddingIndex()
results3 = emb_empty.search("anything", top_k=3)
test("Empty embedding index returns empty", len(results3) == 0)


# ── Hybrid Search ──
print("\n--- skill_search: Hybrid Search ---")

hybrid = HybridSearch()
for name, desc in SKILLS.items():
    hybrid.add(name, f"{name} {desc}")

results = hybrid.search("git commit message", top_k=3)
test("Hybrid returns results", len(results) > 0)
test(
    "Hybrid commit ranked high",
    "commit" in [r[0] for r in results[:2]],
    f"got {[r[0] for r in results]}",
)
test("Hybrid returns (name, score) tuples", len(results[0]) == 2)

# top_k respected
results2 = hybrid.search("code", top_k=2)
test("Hybrid top_k respected", len(results2) <= 2, f"got {len(results2)}")

# Performance test scores
results3 = hybrid.search("measure performance speed latency", top_k=3)
test(
    "Hybrid benchmark for perf query",
    "benchmark" in [r[0] for r in results3],
    f"got {[r[0] for r in results3]}",
)


# ── Custom weights ──
print("\n--- skill_search: Custom weights ---")

hybrid_bm25_heavy = HybridSearch(bm25_weight=0.9, embedding_weight=0.1)
for name, desc in SKILLS.items():
    hybrid_bm25_heavy.add(name, f"{name} {desc}")

results = hybrid_bm25_heavy.search("commit", top_k=1)
test(
    "BM25-heavy finds exact keyword match",
    results[0][0] == "commit",
    f"got {results[0][0] if results else 'empty'}",
)


print(f"\n{'=' * 40}")
print(f"skill_search: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
