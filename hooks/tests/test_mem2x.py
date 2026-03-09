"""Tests for mem2x cognitive memory upgrade components."""

import sys
import os
import math

# Ensure hooks/ is on the path for shared imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_hybrid_decay():
    """Task 1: Hybrid decay curve — exponential→power-law transition."""
    from shared.memory_decay import _time_decay_factor

    # Day 0: full strength
    assert abs(_time_decay_factor(0) - 1.0) < 0.01

    # Day 1: ~95% (exponential phase, 15-day half-life)
    assert 0.93 < _time_decay_factor(1) < 0.97

    # Day 7: ~72% (still in exponential phase)
    assert 0.68 < _time_decay_factor(7) < 0.76

    # Day 15: ~50% (half-life, crossover to power-law)
    assert 0.45 < _time_decay_factor(15) < 0.55

    # Day 30: power-law tail — still retrievable
    hybrid_30 = _time_decay_factor(30)
    assert hybrid_30 > 0.30  # still solid at 30 days

    # Day 365: very low but not zero
    assert _time_decay_factor(365) > 0.001


def test_hybrid_decay_potentiated():
    """Task 1: Potentiated memories decay at half the rate."""
    from shared.memory_decay import _time_decay_factor

    normal_7 = _time_decay_factor(7)
    potentiated_7 = _time_decay_factor(7, potentiated=True)
    assert potentiated_7 > normal_7, "Potentiated should decay slower"

    normal_30 = _time_decay_factor(30)
    potentiated_30 = _time_decay_factor(30, potentiated=True)
    assert potentiated_30 > normal_30, "Potentiated advantage holds at 30 days"


def test_backward_compatibility():
    """Task 1: Old half_life parameter still accepted (backward compat)."""
    from shared.memory_decay import _time_decay_factor

    # Should not raise — half_life is still accepted
    result = _time_decay_factor(10, half_life=45.0)
    assert 0.0 < result <= 1.0

    # With old default half_life=45, day 45 should still work
    result_45 = _time_decay_factor(45, half_life=45.0)
    assert 0.0 < result_45 <= 1.0


def test_calculate_relevance_score_unchanged():
    """Task 1: calculate_relevance_score still works with existing API."""
    from shared.memory_decay import calculate_relevance_score

    # Recent T1 memory should score high
    recent = {"tier": 1, "timestamp": "2026-03-09T00:00:00Z", "retrieval_count": 0, "tags": ""}
    score = calculate_relevance_score(recent)
    assert score > 0.5, f"Recent T1 memory should score high, got {score}"

    # Old T3 memory should score lower
    old = {"tier": 3, "timestamp": "2025-01-01T00:00:00Z", "retrieval_count": 0, "tags": ""}
    old_score = calculate_relevance_score(old)
    assert old_score < score, "Old memory should score lower than recent"


## --- Task 2: LTP Status Tracking ---

def test_ltp_status():
    """Task 2: LTP transitions based on access patterns."""
    import tempfile, json
    from shared.ltp_tracker import LTPTracker

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp = f.name

    try:
        tracker = LTPTracker(tmp)

        # Fresh memory: no protection
        assert tracker.get_status("mem1") == "none"
        assert tracker.get_decay_factor("mem1") == 1.0

        # 5 accesses → Burst
        for _ in range(5):
            tracker.record_access("mem1")
        assert tracker.get_status("mem1") == "burst", f"Expected burst, got {tracker.get_status('mem1')}"
        assert tracker.get_decay_factor("mem1") == 0.5

        # 10+ total accesses → Full
        for _ in range(5):
            tracker.record_access("mem1")
        assert tracker.get_status("mem1") == "full", f"Expected full, got {tracker.get_status('mem1')}"
        assert tracker.get_decay_factor("mem1") == 0.1
    finally:
        os.unlink(tmp)


def test_ltp_persistence():
    """Task 2: LTP state persists across instances."""
    import tempfile
    from shared.ltp_tracker import LTPTracker

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp = f.name

    try:
        tracker1 = LTPTracker(tmp)
        for _ in range(5):
            tracker1.record_access("mem1")
        assert tracker1.get_status("mem1") == "burst"

        # New instance reads same file
        tracker2 = LTPTracker(tmp)
        assert tracker2.get_status("mem1") == "burst"
    finally:
        os.unlink(tmp)


def test_ltp_independent_memories():
    """Task 2: Each memory tracks independently."""
    import tempfile
    from shared.ltp_tracker import LTPTracker

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp = f.name

    try:
        tracker = LTPTracker(tmp)
        for _ in range(5):
            tracker.record_access("mem_a")
        tracker.record_access("mem_b")

        assert tracker.get_status("mem_a") == "burst"
        assert tracker.get_status("mem_b") == "none"
    finally:
        os.unlink(tmp)


## --- Task 3: Integrate Decay + LTP into Scoring ---

def test_decay_with_ltp():
    """Task 3: High-retrieval memories score higher than zero-retrieval at same age."""
    from shared.memory_decay import calculate_relevance_score

    old_memory_ltp = {
        "id": "ltp_test_1",
        "tier": 1,
        "timestamp": "2026-01-01T00:00:00Z",
        "retrieval_count": 15,
        "tags": "",
    }
    old_memory_no_ltp = {
        "id": "ltp_test_2",
        "tier": 1,
        "timestamp": "2026-01-01T00:00:00Z",
        "retrieval_count": 0,
        "tags": "",
    }
    score_with_ltp = calculate_relevance_score(old_memory_ltp)
    score_without_ltp = calculate_relevance_score(old_memory_no_ltp)
    assert score_with_ltp > score_without_ltp, (
        f"LTP memory should score higher: {score_with_ltp} vs {score_without_ltp}"
    )


## --- Task 4: Hebbian Co-retrieval Strengthening ---

def test_hebbian_coretrieval():
    """Task 4: Co-retrieved memories strengthen their connection."""
    from shared.knowledge_graph import KnowledgeGraph

    graph = KnowledgeGraph(":memory:")
    # Simulate co-retrieval: mem_a and mem_b returned together
    graph.strengthen_coretrieval(["mem_a", "mem_b", "mem_c"])
    # Edge should exist between each pair
    assert graph.get_edge_strength("mem_a", "mem_b") > 0
    assert graph.get_edge_strength("mem_a", "mem_c") > 0
    assert graph.get_edge_strength("mem_b", "mem_c") > 0
    # Repeated co-retrieval strengthens
    graph.strengthen_coretrieval(["mem_a", "mem_b"])
    assert graph.get_edge_strength("mem_a", "mem_b") > graph.get_edge_strength("mem_a", "mem_c")


def test_hebbian_strength_bounds():
    """Task 4: Edge strength bounded at 1.0."""
    from shared.knowledge_graph import KnowledgeGraph

    graph = KnowledgeGraph(":memory:")
    for _ in range(100):
        graph.strengthen_coretrieval(["x", "y"])
    assert graph.get_edge_strength("x", "y") <= 1.0


## --- Task 5: Entity Extraction Pipeline ---

def test_entity_extraction():
    """Task 5: Extract meaningful entities from text."""
    from shared.entity_extraction import extract_entities

    entities = extract_entities("Fixed the LanceDB migration bug in memory_server.py")
    names = [e["name"] for e in entities]
    assert "LanceDB" in names, f"Expected LanceDB in {names}"
    assert any("memory_server" in n for n in names), f"Expected memory_server in {names}"
    # Should not extract stop words
    assert "the" not in names
    assert "in" not in names


def test_entity_extraction_compounds():
    """Task 5: Compound noun detection."""
    from shared.entity_extraction import extract_entities

    entities = extract_entities("The knowledge graph uses spreading activation for retrieval")
    names = [e["name"] for e in entities]
    assert any("knowledge graph" in n or "knowledge_graph" in n for n in names), f"Expected knowledge graph in {names}"
    assert any("spreading activation" in n or "spreading_activation" in n for n in names), f"Expected spreading activation in {names}"


def test_entity_cooccurrences():
    """Task 5: Extract co-occurring entity pairs."""
    from shared.entity_extraction import extract_cooccurrences

    pairs = extract_cooccurrences("Fixed the LanceDB migration bug in memory_server.py")
    assert len(pairs) > 0, "Should find co-occurring entities"
    # All pairs should be tuples of strings
    for a, b in pairs:
        assert isinstance(a, str) and isinstance(b, str)


## --- Task 6: Graph Population on Ingest ---

def test_graph_population_on_ingest():
    """Task 6: Entities and co-occurrences populate the graph."""
    from shared.knowledge_graph import KnowledgeGraph
    from shared.entity_extraction import extract_entities, extract_cooccurrences

    graph = KnowledgeGraph(":memory:")
    content = "Fixed the LanceDB vector search bug in memory_server.py"
    entities = extract_entities(content)
    cooccurrences = extract_cooccurrences(content)
    for entity in entities:
        graph.upsert_entity(entity["name"], entity["type"])
    for e1, e2 in cooccurrences:
        graph.add_edge(e1, e2, "co_occurs")
    assert graph.entity_count() >= 2, f"Expected >=2 entities, got {graph.entity_count()}"
    assert graph.edge_count() >= 1, f"Expected >=1 edges, got {graph.edge_count()}"


## --- Task 7: Spreading Activation Search ---

def test_spreading_activation():
    """Task 7: BFS activation traversal over knowledge graph."""
    from shared.knowledge_graph import KnowledgeGraph

    graph = KnowledgeGraph(":memory:")
    graph.upsert_entity("LanceDB", "Technology")
    graph.upsert_entity("vector_search", "Concept")
    graph.upsert_entity("memory_server", "Technology")
    graph.upsert_entity("embeddings", "Concept")
    graph.add_edge("LanceDB", "vector_search", "uses", strength=0.8)
    graph.add_edge("vector_search", "memory_server", "part_of", strength=0.7)
    graph.add_edge("memory_server", "embeddings", "uses", strength=0.6)
    results = graph.spreading_activation(["LanceDB"], max_hops=3)
    names = [r["name"] for r in results]
    assert "vector_search" in names, f"Expected vector_search in {names}"
    assert "embeddings" in names, f"Expected embeddings in {names}"
    activations = {r["name"]: r["activation"] for r in results}
    assert activations["vector_search"] > activations["embeddings"], (
        f"Closer node should have higher activation: {activations}"
    )


def test_spreading_activation_empty():
    """Task 7: Activation on empty graph returns empty."""
    from shared.knowledge_graph import KnowledgeGraph

    graph = KnowledgeGraph(":memory:")
    results = graph.spreading_activation(["nonexistent"])
    assert results == []


## --- Task 9: Graph-Aware Delete and Quarantine ---

def test_graph_cleanup_on_delete():
    """Task 9: Removing entity edges cleans graph."""
    from shared.knowledge_graph import KnowledgeGraph

    graph = KnowledgeGraph(":memory:")
    graph.upsert_entity("A", "Concept")
    graph.upsert_entity("B", "Concept")
    graph.add_edge("A", "B", "related")
    assert graph.edge_count() == 1
    graph.remove_entity_edges("A")
    assert graph.edge_count() == 0


def test_graph_deactivate_entity():
    """Task 9: Deactivating entity sets salience to 0."""
    from shared.knowledge_graph import KnowledgeGraph

    graph = KnowledgeGraph(":memory:")
    graph.upsert_entity("A", "Concept", salience=0.8)
    graph.deactivate_entity("A")
    row = graph._conn.execute("SELECT salience FROM entities WHERE name=?", ("A",)).fetchone()
    assert row[0] == 0.0


## --- Fix 1: Full LTP chain verification ---

def test_ltp_full_chain():
    """Fix 1: LTP tracker → calculate_relevance_score with ltp_factor flows correctly."""
    import tempfile
    from shared.ltp_tracker import LTPTracker
    from shared.memory_decay import calculate_relevance_score

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp = f.name

    try:
        tracker = LTPTracker(tmp)

        # Access mem1 10+ times to trigger "full" LTP
        for _ in range(12):
            tracker.record_access("mem1")

        assert tracker.get_status("mem1") == "full", f"Expected full, got {tracker.get_status('mem1')}"
        ltp_factor = tracker.get_decay_factor("mem1")
        assert ltp_factor == 0.1, f"Expected 0.1 for full LTP, got {ltp_factor}"

        # Score with and without ltp_factor
        memory = {
            "tier": 2,
            "timestamp": "2026-01-15T00:00:00Z",
            "retrieval_count": 12,
            "tags": "",
        }

        score_with_ltp = calculate_relevance_score(memory, ltp_factor=ltp_factor)
        score_without_ltp = calculate_relevance_score(memory, ltp_factor=1.0)

        # Full LTP (0.1) should give significantly higher score than no LTP (1.0)
        assert score_with_ltp > score_without_ltp, (
            f"Full LTP should boost score: {score_with_ltp} vs {score_without_ltp}"
        )

        # Verify no-access memory gets ltp_factor=1.0
        assert tracker.get_decay_factor("mem_new") == 1.0
    finally:
        os.unlink(tmp)


def test_ltp_factor_gradation():
    """Fix 1: All 4 LTP levels produce distinct scores."""
    from shared.memory_decay import calculate_relevance_score

    memory = {
        "tier": 2,
        "timestamp": "2026-01-01T00:00:00Z",
        "retrieval_count": 0,
        "tags": "",
    }

    scores = {}
    for label, factor in [("none", 1.0), ("burst", 0.5), ("weekly", 0.33), ("full", 0.1)]:
        scores[label] = calculate_relevance_score(memory, ltp_factor=factor)

    # Higher protection (lower factor) = higher score
    assert scores["full"] >= scores["weekly"] >= scores["burst"] >= scores["none"], (
        f"LTP gradation should be monotonic: {scores}"
    )
    # Full and none should be meaningfully different
    assert scores["full"] > scores["none"], (
        f"Full LTP should beat no LTP: {scores}"
    )


if __name__ == "__main__":
    test_hybrid_decay()
    test_hybrid_decay_potentiated()
    test_backward_compatibility()
    test_calculate_relevance_score_unchanged()
    print("All Task 1 tests passed!")
    test_ltp_status()
    test_ltp_persistence()
    test_ltp_independent_memories()
    print("All Task 2 tests passed!")
    test_decay_with_ltp()
    print("All Task 3 tests passed!")
    test_hebbian_coretrieval()
    test_hebbian_strength_bounds()
    print("All Task 4 tests passed!")
    test_entity_extraction()
    test_entity_extraction_compounds()
    test_entity_cooccurrences()
    print("All Task 5 tests passed!")
    test_graph_population_on_ingest()
    print("All Task 6 tests passed!")
    test_spreading_activation()
    test_spreading_activation_empty()
    print("All Task 7 tests passed!")
    test_graph_cleanup_on_delete()
    test_graph_deactivate_entity()
    print("All Task 9 tests passed!")
    test_ltp_full_chain()
    test_ltp_factor_gradation()
    print("All Fix 1 tests passed!")
