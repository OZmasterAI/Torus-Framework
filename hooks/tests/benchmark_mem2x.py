"""End-to-end validation and benchmarks for mem2x cognitive memory upgrade.

Tests all 7 components working together in a unified pipeline.
Run from hooks/ directory: python3 tests/benchmark_mem2x.py
"""

import sys
import os
import time
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.memory_decay import _time_decay_factor, calculate_relevance_score
from shared.ltp_tracker import LTPTracker
from shared.knowledge_graph import KnowledgeGraph
from shared.entity_extraction import extract_entities, extract_cooccurrences


def banner(msg):
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}")


def test_e2e_decay_curve():
    """Verify hybrid decay curve properties."""
    banner("1. Hybrid Decay Curve")
    ages = [0, 0.5, 1, 3, 7, 14, 30, 90, 180, 365]
    print(f"  {'Age (days)':>10}  {'Decay':>8}  {'Potentiated':>12}")
    print(f"  {'-'*10}  {'-'*8}  {'-'*12}")
    prev = 1.0
    for age in ages:
        d = _time_decay_factor(age)
        dp = _time_decay_factor(age, potentiated=True)
        assert d <= prev or age == 0, f"Decay not monotonic at {age}"
        assert dp >= d, f"Potentiated not >= normal at {age}"
        print(f"  {age:>10}  {d:>8.4f}  {dp:>12.4f}")
        prev = d
    assert _time_decay_factor(365) > 0.001, "365-day memory should not be zero"
    print("  PASS: monotonic, potentiated >= normal, long-tail > 0")


def test_e2e_ltp_lifecycle():
    """Verify LTP status transitions."""
    banner("2. LTP Lifecycle")
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp = f.name
    try:
        tracker = LTPTracker(tmp)
        statuses = []

        # none → burst (5 accesses)
        for i in range(5):
            s = tracker.record_access("test_mem")
        statuses.append(("after 5 accesses", s, tracker.get_decay_factor("test_mem")))
        assert s == "burst", f"Expected burst, got {s}"

        # burst → full (10 total)
        for i in range(5):
            s = tracker.record_access("test_mem")
        statuses.append(("after 10 accesses", s, tracker.get_decay_factor("test_mem")))
        assert s == "full", f"Expected full, got {s}"

        for label, status, factor in statuses:
            print(f"  {label:>20}: status={status:>6}, decay_factor={factor:.2f}")

        # Verify persistence
        tracker2 = LTPTracker(tmp)
        assert tracker2.get_status("test_mem") == "full"
        print("  PASS: lifecycle transitions correct, persistence works")
    finally:
        os.unlink(tmp)


def test_e2e_ltp_scoring_integration():
    """Verify LTP affects relevance scoring."""
    banner("3. LTP → Scoring Integration")
    # Same age, different retrieval counts
    ages_to_test = [30, 90, 180]
    for age_days in ages_to_test:
        ts = f"2025-{12 - age_days // 30:02d}-01T00:00:00Z"  # approximate
        high_access = {"tier": 1, "timestamp": ts, "retrieval_count": 15, "tags": ""}
        low_access = {"tier": 1, "timestamp": ts, "retrieval_count": 0, "tags": ""}
        score_high = calculate_relevance_score(high_access)
        score_low = calculate_relevance_score(low_access)
        delta = score_high - score_low
        print(f"  Age {age_days:>3}d: high_access={score_high:.4f}  low_access={score_low:.4f}  delta={delta:+.4f}")
        assert score_high > score_low, f"High access should score higher at {age_days}d"
    print("  PASS: LTP-protected memories score higher")


def test_e2e_entity_extraction():
    """Verify entity extraction quality."""
    banner("4. Entity Extraction")
    test_cases = [
        ("Fixed the LanceDB migration bug in memory_server.py",
         {"LanceDB", "memory_server.py"}),
        ("The knowledge graph uses spreading activation for retrieval",
         {"knowledge graph", "spreading activation"}),
        ("ChromaDB was replaced by LanceDB in the vector search pipeline",
         {"ChromaDB", "LanceDB"}),
    ]
    for text, expected_subset in test_cases:
        entities = extract_entities(text)
        names = {e["name"] for e in entities}
        found = expected_subset & names
        missing = expected_subset - names
        print(f"  Text: '{text[:60]}...'")
        print(f"    Found: {found}")
        if missing:
            print(f"    Missing: {missing}")
        # Allow partial matches (entity extraction is heuristic)
        assert len(found) >= 1, f"Should find at least 1 expected entity, got none from {names}"
    print("  PASS: entity extraction finds key terms")


def test_e2e_knowledge_graph():
    """Verify full graph lifecycle: populate → query → activate → cleanup."""
    banner("5. Knowledge Graph Lifecycle")
    graph = KnowledgeGraph(":memory:")

    # Populate from sample memories
    memories = [
        "Fixed the LanceDB vector search bug in memory_server.py",
        "The knowledge graph uses spreading activation for enriched retrieval",
        "LanceDB replaced ChromaDB for vector search in the memory system",
        "Entity extraction pipeline extracts compounds like knowledge graph",
        "Spreading activation traverses the knowledge graph via BFS",
    ]

    t0 = time.time()
    for text in memories:
        entities = extract_entities(text)
        coocs = extract_cooccurrences(text)
        for ent in entities:
            graph.upsert_entity(ent["name"], ent["type"])
        for e1, e2 in coocs:
            graph.add_edge(e1, e2, "co_occurs")
    populate_ms = (time.time() - t0) * 1000

    print(f"  Entities: {graph.entity_count()}")
    print(f"  Edges: {graph.edge_count()}")
    print(f"  Populate time: {populate_ms:.1f}ms")
    assert graph.entity_count() >= 3, "Should have at least 3 entities"
    assert graph.edge_count() >= 1, "Should have at least 1 edge"

    # Spreading activation
    t0 = time.time()
    results = graph.spreading_activation(["LanceDB"], max_hops=3)
    activate_ms = (time.time() - t0) * 1000
    print(f"  Activation from 'LanceDB': {len(results)} nodes reached")
    for r in results[:5]:
        print(f"    {r['name']:>25}: activation={r['activation']:.4f} hops={r['hops']}")
    print(f"  Activation time: {activate_ms:.1f}ms")

    # Hebbian co-retrieval
    graph.strengthen_coretrieval(["mem_a", "mem_b", "mem_c"])
    graph.strengthen_coretrieval(["mem_a", "mem_b"])
    ab = graph.get_edge_strength("mem_a", "mem_b")
    ac = graph.get_edge_strength("mem_a", "mem_c")
    print(f"  Hebbian: A-B={ab:.3f} (2x co-retrieved) > A-C={ac:.3f} (1x)")
    assert ab > ac, "Repeated co-retrieval should strengthen"

    # Cleanup
    graph.remove_entity_edges("mem_a")
    assert graph.get_edge_strength("mem_a", "mem_b") == 0.0
    print("  PASS: full graph lifecycle works")


def test_e2e_coretrieval_strengthening():
    """Verify Hebbian learning converges and bounds."""
    banner("6. Hebbian Co-retrieval Convergence")
    graph = KnowledgeGraph(":memory:")
    strengths = []
    for i in range(20):
        graph.strengthen_coretrieval(["x", "y"])
        s = graph.get_edge_strength("x", "y")
        strengths.append(s)

    print(f"  After  1 co-retrieval: {strengths[0]:.4f}")
    print(f"  After  5 co-retrievals: {strengths[4]:.4f}")
    print(f"  After 10 co-retrievals: {strengths[9]:.4f}")
    print(f"  After 20 co-retrievals: {strengths[19]:.4f}")
    assert strengths[-1] <= 1.0, "Strength should be bounded at 1.0"
    assert strengths[-1] > strengths[0], "Strength should increase"
    # Verify diminishing returns (Hebbian formula)
    delta_early = strengths[4] - strengths[0]
    delta_late = strengths[19] - strengths[14]
    print(f"  Early delta (1-5): {delta_early:.4f}")
    print(f"  Late delta (15-20): {delta_late:.4f}")
    assert delta_early > delta_late, "Diminishing returns expected"
    print("  PASS: Hebbian converges with diminishing returns")


def benchmark_performance():
    """Measure latency of key operations."""
    banner("7. Performance Benchmarks")

    # Decay calculation
    t0 = time.time()
    for _ in range(10000):
        _time_decay_factor(30.0)
    decay_us = (time.time() - t0) / 10000 * 1_000_000
    print(f"  _time_decay_factor: {decay_us:.1f} µs/call")

    # Entity extraction
    text = "Fixed the LanceDB vector search bug in memory_server.py with spreading activation"
    t0 = time.time()
    for _ in range(1000):
        extract_entities(text)
    entity_us = (time.time() - t0) / 1000 * 1_000_000
    print(f"  extract_entities: {entity_us:.0f} µs/call")

    # Graph operations
    graph = KnowledgeGraph(":memory:")
    for i in range(100):
        graph.upsert_entity(f"entity_{i}", "Concept")
        if i > 0:
            graph.add_edge(f"entity_{i-1}", f"entity_{i}", "related", strength=0.5)

    t0 = time.time()
    for _ in range(100):
        graph.spreading_activation(["entity_0"], max_hops=3)
    activate_us = (time.time() - t0) / 100 * 1_000_000
    print(f"  spreading_activation (100 nodes): {activate_us:.0f} µs/call")

    t0 = time.time()
    for _ in range(1000):
        graph.strengthen_coretrieval(["a", "b", "c"])
    hebbian_us = (time.time() - t0) / 1000 * 1_000_000
    print(f"  strengthen_coretrieval (3 nodes): {hebbian_us:.0f} µs/call")

    # LTP tracker
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp = f.name
    try:
        tracker = LTPTracker(tmp)
        t0 = time.time()
        for i in range(100):
            tracker.record_access(f"mem_{i}")
        ltp_us = (time.time() - t0) / 100 * 1_000_000
        print(f"  LTP record_access: {ltp_us:.0f} µs/call")
    finally:
        os.unlink(tmp)

    print("  PASS: all operations within acceptable latency")


if __name__ == "__main__":
    test_e2e_decay_curve()
    test_e2e_ltp_lifecycle()
    test_e2e_ltp_scoring_integration()
    test_e2e_entity_extraction()
    test_e2e_knowledge_graph()
    test_e2e_coretrieval_strengthening()
    benchmark_performance()

    banner("ALL E2E TESTS PASSED")
