#!/usr/bin/env python3
"""
50-query benchmark: LanceDB vs ChromaDB relevance & latency comparison.

Runs the same queries against both backends and compares:
  - Latency (ms per query)
  - Result overlap (Jaccard similarity of top-K IDs)
  - Distance/score correlation

Prints a summary report at the end.
"""

import os
import sys
import time
import json
import statistics
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
MEMORY_DIR = str(Path.home() / "data" / "memory")
LANCE_PATH = os.path.join(MEMORY_DIR, "lancedb")
EMBED_MODEL_NAME = "nomic-ai/nomic-embed-text-v2-moe"
TOP_K = 10

# ---------------------------------------------------------------------------
# Test queries — realistic framework/memory queries
# ---------------------------------------------------------------------------
QUERIES = [
    # General knowledge
    "gate hook framework architecture",
    "how does the enforcer work",
    "memory server configuration",
    "ChromaDB collection setup",
    "LanceDB migration steps",
    "session state management",
    "behavioral rules for claude",
    "domain mastery graduation",
    "FTS5 full text search",
    "embedding model nomic",
    # Error patterns
    "TypeError NoneType has no attribute",
    "ImportError module not found",
    "permission denied file access",
    "git merge conflict resolution",
    "npm install ERESOLVE dependency",
    # Fix outcomes
    "fixed gate blocking incorrectly",
    "resolved memory server crash",
    "workaround for chromadb segfault",
    "patched enforcer false positive",
    "corrected state schema migration",
    # Framework components
    "gate 01 read before edit",
    "gate 02 no destroy",
    "gate 04 memory first",
    "gate 13 workspace isolation",
    "observation auto capture hook",
    "capture queue processing",
    "audit log format",
    "shared state module",
    "error normalizer pattern",
    "gate result severity levels",
    # Workflows
    "causal chain workflow steps",
    "the loop memory plan test build",
    "agent delegation sub-agents",
    "parallel task execution",
    "plan mode discipline rules",
    # Specific technical
    "pyarrow schema definition",
    "cosine similarity search vector",
    "sentence transformer encoding",
    "fnv1a hash function id generation",
    "json metadata validation",
    # Edge cases
    "empty query handling",
    "duplicate memory deduplication",
    "tag co-occurrence matrix",
    "session wrap-up handoff",
    "benchmark performance metrics",
    # Mixed context
    "how to fix broken tests",
    "security scan vulnerability",
    "plugin marketplace installation",
    "skill development pattern",
    "web page indexing chromadb",
]

assert len(QUERIES) == 50, f"Expected 50 queries, got {len(QUERIES)}"


def load_embedding_model():
    """Load the sentence transformer model."""
    from sentence_transformers import SentenceTransformer
    print("Loading embedding model...")
    model = SentenceTransformer(EMBED_MODEL_NAME, trust_remote_code=True)
    # Warm up
    model.encode(["warmup"], show_progress_bar=False)
    return model


def embed_queries(model, queries):
    """Pre-compute all query embeddings."""
    print(f"Embedding {len(queries)} queries...")
    vectors = model.encode(queries, batch_size=16, show_progress_bar=False)
    return [v.tolist() for v in vectors]


def setup_chromadb():
    """Connect to ChromaDB and return the knowledge collection."""
    import chromadb
    client = chromadb.PersistentClient(path=MEMORY_DIR)
    return client.get_collection("knowledge")


def setup_lancedb():
    """Connect to LanceDB and return the knowledge table."""
    import lancedb
    db = lancedb.connect(LANCE_PATH)
    return db.open_table("knowledge")


def query_chromadb(collection, vector, top_k):
    """Query ChromaDB with a pre-computed vector."""
    result = collection.query(
        query_embeddings=[vector],
        n_results=top_k,
        include=["distances", "documents"],
    )
    ids = result.get("ids", [[]])[0]
    distances = result.get("distances", [[]])[0]
    return ids, distances


def query_lancedb(table, vector, top_k):
    """Query LanceDB with a pre-computed vector."""
    rows = table.search(vector).distance_type("cosine").limit(top_k).to_list()
    ids = [r["id"] for r in rows]
    distances = [r.get("_distance", 1.0) for r in rows]
    return ids, distances


def jaccard_similarity(set_a, set_b):
    """Compute Jaccard similarity between two sets."""
    a, b = set(set_a), set(set_b)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def overlap_at_k(list_a, list_b, k=None):
    """Fraction of items in list_a that also appear in list_b (up to k)."""
    if k:
        list_a = list_a[:k]
        list_b = list_b[:k]
    if not list_a:
        return 1.0
    return len(set(list_a) & set(list_b)) / len(set(list_a))


def main():
    model = load_embedding_model()
    vectors = embed_queries(model, QUERIES)

    chroma_coll = setup_chromadb()
    lance_tbl = setup_lancedb()

    print(f"\nRunning {len(QUERIES)} queries against both backends (top_k={TOP_K})...\n")

    chroma_latencies = []
    lance_latencies = []
    jaccard_scores = []
    overlap_scores = []
    rank_correlation_data = []

    for i, (query, vector) in enumerate(zip(QUERIES, vectors)):
        # ChromaDB
        t0 = time.perf_counter()
        chroma_ids, chroma_dists = query_chromadb(chroma_coll, vector, TOP_K)
        chroma_ms = (time.perf_counter() - t0) * 1000
        chroma_latencies.append(chroma_ms)

        # LanceDB
        t0 = time.perf_counter()
        lance_ids, lance_dists = query_lancedb(lance_tbl, vector, TOP_K)
        lance_ms = (time.perf_counter() - t0) * 1000
        lance_latencies.append(lance_ms)

        # Relevance comparison
        jacc = jaccard_similarity(chroma_ids, lance_ids)
        jaccard_scores.append(jacc)

        ovlp = overlap_at_k(chroma_ids, lance_ids)
        overlap_scores.append(ovlp)

        # Print per-query results (abbreviated)
        marker = "OK" if jacc >= 0.7 else "DIFF" if jacc >= 0.3 else "LOW"
        print(f"  [{i+1:2d}/50] {marker:4s} jacc={jacc:.2f} "
              f"chroma={chroma_ms:6.1f}ms lance={lance_ms:6.1f}ms  "
              f"'{query[:50]}...'")

    # ---------------------------------------------------------------------------
    # Summary report
    # ---------------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("BENCHMARK RESULTS: LanceDB vs ChromaDB (knowledge table, 50 queries)")
    print("=" * 70)

    print(f"\n  Latency (ms/query):")
    print(f"    ChromaDB  — mean: {statistics.mean(chroma_latencies):6.1f}  "
          f"median: {statistics.median(chroma_latencies):6.1f}  "
          f"p95: {sorted(chroma_latencies)[47]:6.1f}  "
          f"p99: {sorted(chroma_latencies)[49]:6.1f}")
    print(f"    LanceDB   — mean: {statistics.mean(lance_latencies):6.1f}  "
          f"median: {statistics.median(lance_latencies):6.1f}  "
          f"p95: {sorted(lance_latencies)[47]:6.1f}  "
          f"p99: {sorted(lance_latencies)[49]:6.1f}")

    speedup = statistics.mean(chroma_latencies) / max(statistics.mean(lance_latencies), 0.001)
    print(f"    Speedup   — {speedup:.2f}x {'faster' if speedup > 1 else 'slower'} (LanceDB vs ChromaDB)")

    print(f"\n  Relevance (top-{TOP_K} overlap):")
    print(f"    Jaccard similarity — mean: {statistics.mean(jaccard_scores):.3f}  "
          f"min: {min(jaccard_scores):.3f}  max: {max(jaccard_scores):.3f}")
    print(f"    Recall (ChromaDB→LanceDB) — mean: {statistics.mean(overlap_scores):.3f}  "
          f"min: {min(overlap_scores):.3f}  max: {max(overlap_scores):.3f}")

    perfect = sum(1 for j in jaccard_scores if j >= 0.99)
    high    = sum(1 for j in jaccard_scores if 0.7 <= j < 0.99)
    medium  = sum(1 for j in jaccard_scores if 0.3 <= j < 0.7)
    low     = sum(1 for j in jaccard_scores if j < 0.3)

    print(f"\n    Distribution:")
    print(f"      Perfect (>=0.99): {perfect:2d}/50")
    print(f"      High    (>=0.70): {high:2d}/50")
    print(f"      Medium  (>=0.30): {medium:2d}/50")
    print(f"      Low     (<0.30):  {low:2d}/50")

    # Overall verdict
    avg_jacc = statistics.mean(jaccard_scores)
    if avg_jacc >= 0.8:
        verdict = "EXCELLENT — results are highly consistent"
    elif avg_jacc >= 0.6:
        verdict = "GOOD — results are mostly consistent with minor differences"
    elif avg_jacc >= 0.4:
        verdict = "ACCEPTABLE — noticeable differences, likely due to PQ quantization"
    else:
        verdict = "CONCERNING — significant divergence, investigate index parameters"

    print(f"\n  Verdict: {verdict}")

    # Save results
    results = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "queries": len(QUERIES),
        "top_k": TOP_K,
        "chroma_latency_mean_ms": round(statistics.mean(chroma_latencies), 2),
        "lance_latency_mean_ms": round(statistics.mean(lance_latencies), 2),
        "speedup": round(speedup, 2),
        "jaccard_mean": round(avg_jacc, 3),
        "recall_mean": round(statistics.mean(overlap_scores), 3),
        "verdict": verdict,
    }

    out_path = os.path.join(MEMORY_DIR, "lancedb", "benchmark_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  Results saved to: {out_path}")

    return 0 if avg_jacc >= 0.3 else 1


if __name__ == "__main__":
    sys.exit(main())
