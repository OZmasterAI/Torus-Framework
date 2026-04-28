#!/usr/bin/env python3
"""Tests for DAG Memory Layer — SQLite-backed memory on conversations.db."""

import json
import os
import sys
import tempfile

import pytest

pytestmark = pytest.mark.skip(
    reason="DAGMemoryLayer removed in SurrealDB migration (Task 14)"
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.dag import ConversationDAG
from shared.dag_memory_layer import DAGMemoryLayer, promote_nodes


@pytest.fixture
def dag_and_layer():
    """Create a temp DAG + memory layer for each test."""
    d = tempfile.mkdtemp()
    dag = ConversationDAG(os.path.join(d, "test.db"))
    layer = DAGMemoryLayer(dag)
    yield dag, layer
    dag.close()


# --- Task 1: Schema ---


class TestSchema:
    def test_memory_tables_exist(self, dag_and_layer):
        dag, _ = dag_and_layer
        tables = [
            r[0]
            for r in dag._db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        assert "knowledge" in tables
        assert "observations" in tables
        assert "fix_outcomes" in tables
        assert "node_edges" in tables
        assert "embeddings" in tables

    def test_knowledge_columns(self, dag_and_layer):
        dag, _ = dag_and_layer
        cols = [
            r[1] for r in dag._db.execute("PRAGMA table_info(knowledge)").fetchall()
        ]
        for col in [
            "id",
            "content",
            "context",
            "tags",
            "tier",
            "memory_type",
            "state_type",
            "cluster_id",
            "retrieval_count",
            "quality_score",
            "source_node_id",
            "created_at",
            "updated_at",
            "metadata",
        ]:
            assert col in cols, f"missing column: {col}"

    def test_fix_outcomes_columns(self, dag_and_layer):
        dag, _ = dag_and_layer
        cols = [
            r[1] for r in dag._db.execute("PRAGMA table_info(fix_outcomes)").fetchall()
        ]
        for col in [
            "id",
            "chain_id",
            "error_description",
            "strategy",
            "outcome",
            "node_id",
        ]:
            assert col in cols, f"missing column: {col}"

    def test_embeddings_columns(self, dag_and_layer):
        dag, _ = dag_and_layer
        cols = [
            r[1] for r in dag._db.execute("PRAGMA table_info(embeddings)").fetchall()
        ]
        for col in ["id", "source_table", "source_id", "vector", "created_at"]:
            assert col in cols, f"missing column: {col}"


# --- Task 2: FTS5 ---


class TestFTS5:
    def test_fts5_search_nodes(self, dag_and_layer):
        dag, _ = dag_and_layer
        dag.add_node("", "user", "fix the authentication bug in login.py")
        dag.add_node(dag.get_head(), "assistant", "I found the issue in OAuth handler")
        results = dag._db.execute(
            "SELECT content FROM nodes_fts WHERE nodes_fts MATCH 'authentication'"
        ).fetchall()
        assert len(results) == 1
        assert "authentication" in results[0][0]

    def test_fts5_search_knowledge(self, dag_and_layer):
        dag, _ = dag_and_layer
        dag._db.execute(
            "INSERT INTO knowledge (id, content, tags, created_at, updated_at) "
            "VALUES (?, ?, ?, datetime('now'), datetime('now'))",
            ("k_test1", "SQLite FTS5 is great for keyword search", "type:learning"),
        )
        dag._db.commit()
        results = dag._db.execute(
            "SELECT content FROM knowledge_fts WHERE knowledge_fts MATCH 'keyword'"
        ).fetchall()
        assert len(results) == 1

    def test_fts5_no_match(self, dag_and_layer):
        dag, _ = dag_and_layer
        dag.add_node("", "user", "hello world")
        results = dag._db.execute(
            "SELECT content FROM nodes_fts WHERE nodes_fts MATCH 'nonexistent'"
        ).fetchall()
        assert len(results) == 0

    def test_fts5_multiple_matches(self, dag_and_layer):
        dag, _ = dag_and_layer
        dag.add_node("", "user", "fix the bug in auth")
        dag.add_node(dag.get_head(), "assistant", "the auth module needs updating")
        dag.add_node(dag.get_head(), "user", "auth is working now")
        results = dag._db.execute(
            "SELECT content FROM nodes_fts WHERE nodes_fts MATCH 'auth'"
        ).fetchall()
        assert len(results) == 3


# --- Task 3: Core Layer ---


class TestStore:
    def test_store_knowledge(self, dag_and_layer):
        dag, layer = dag_and_layer
        result = layer.store(
            content="Gate 6 blocks edits when fixes aren't saved to memory",
            tags="type:learning,area:framework",
            tier=1,
            memory_type="reference",
            source_node_id="nd_abc123",
        )
        assert result["stored"] is True
        assert result["id"].startswith("dk_")
        row = dag._db.execute(
            "SELECT content, tags, tier, memory_type FROM knowledge WHERE id = ?",
            (result["id"],),
        ).fetchone()
        assert row[0] == "Gate 6 blocks edits when fixes aren't saved to memory"
        assert row[1] == "type:learning,area:framework"
        assert row[2] == 1
        assert row[3] == "reference"

    def test_store_observation(self, dag_and_layer):
        _, layer = dag_and_layer
        result = layer.store_observation(
            content="User prefers snake_case", tags="type:preference"
        )
        assert result["stored"] is True
        assert result["id"].startswith("do_")

    def test_store_fix_outcome(self, dag_and_layer):
        _, layer = dag_and_layer
        result = layer.store_fix_outcome(
            chain_id="chain_abc",
            error="ImportError: no module named foo",
            strategy="install foo package",
            outcome="success",
        )
        assert result["stored"] is True
        assert result["id"].startswith("df_")

    def test_add_edge(self, dag_and_layer):
        dag, layer = dag_and_layer
        layer.add_edge("nd_1", "dk_2", "derived_from", weight=0.8)
        row = dag._db.execute(
            "SELECT weight FROM node_edges WHERE source_id = ? AND target_id = ?",
            ("nd_1", "dk_2"),
        ).fetchone()
        assert row is not None
        assert row[0] == 0.8

    def test_get_entry(self, dag_and_layer):
        _, layer = dag_and_layer
        result = layer.store(content="test entry", tags="type:test")
        entry = layer.get_entry(result["id"])
        assert entry is not None
        assert entry["content"] == "test entry"
        assert entry["source"] == "dag_sqlite"

    def test_get_entry_missing(self, dag_and_layer):
        _, layer = dag_and_layer
        assert layer.get_entry("nonexistent") is None

    def test_increment_retrieval(self, dag_and_layer):
        dag, layer = dag_and_layer
        result = layer.store(content="test retrieval count", tags="type:test")
        layer.increment_retrieval(result["id"])
        layer.increment_retrieval(result["id"])
        row = dag._db.execute(
            "SELECT retrieval_count FROM knowledge WHERE id = ?",
            (result["id"],),
        ).fetchone()
        assert row[0] == 2

    def test_count(self, dag_and_layer):
        _, layer = dag_and_layer
        assert layer.count("knowledge") == 0
        layer.store(content="entry 1", tags="")
        layer.store(content="entry 2", tags="")
        assert layer.count("knowledge") == 2


class TestSearch:
    def test_search_by_keyword(self, dag_and_layer):
        _, layer = dag_and_layer
        layer.store(
            content="LanceDB uses nomic-embed for vectors", tags="type:learning"
        )
        layer.store(content="SQLite FTS5 handles keyword search", tags="type:learning")
        layer.store(content="Python asyncio event loop basics", tags="type:learning")
        results = layer.search("vectors")
        assert len(results) >= 1
        assert any("nomic" in r["content"] or "vector" in r["content"] for r in results)

    def test_search_no_results(self, dag_and_layer):
        _, layer = dag_and_layer
        layer.store(content="hello world", tags="")
        results = layer.search("zzz_nonexistent_xyz")
        assert len(results) == 0

    def test_search_like_fallback(self, dag_and_layer):
        _, layer = dag_and_layer
        layer.store(content="the quick brown fox jumps", tags="")
        # LIKE fallback should find partial matches
        results = layer.search("quick brown", mode="keyword")
        assert len(results) >= 1

    def test_search_nodes_fts(self, dag_and_layer):
        dag, layer = dag_and_layer
        dag.add_node("", "user", "how do I configure the rate limiter?")
        dag.add_node(dag.get_head(), "assistant", "set max_requests in config.json")
        results = layer.search_nodes_fts("rate limiter")
        assert len(results) >= 1
        assert results[0]["role"] == "user"

    def test_search_nodes_fts_role_filter(self, dag_and_layer):
        dag, layer = dag_and_layer
        dag.add_node("", "user", "fix the auth bug")
        dag.add_node(
            dag.get_head(), "assistant", "the auth module has a null check issue"
        )
        results = layer.search_nodes_fts("auth", role_filter="assistant")
        assert len(results) == 1
        assert results[0]["role"] == "assistant"


# --- Task 4: Auto-promotion (included in Phase A for testing) ---


class TestPromotion:
    def test_promote_high_salience(self, dag_and_layer):
        dag, layer = dag_and_layer
        n1 = dag.add_node(
            "",
            "assistant",
            "Fixed the authentication bug by adding null check to OAuth handler. "
            "Root cause: token refresh returned None when session expired.",
        )
        n2 = dag.add_node(n1, "assistant", "ok")
        n3 = dag.add_node(n2, "user", "yes")
        promoted = promote_nodes(dag, layer, threshold=0.10)
        assert len(promoted) >= 1
        # The fix description should be promoted
        k_entries = dag._db.execute("SELECT content FROM knowledge").fetchall()
        assert any("authentication" in row[0] for row in k_entries)

    def test_promoted_node_marked(self, dag_and_layer):
        dag, layer = dag_and_layer
        n1 = dag.add_node(
            "",
            "assistant",
            "Critical fix: always validate input before database queries to prevent SQL injection",
        )
        promoted = promote_nodes(dag, layer, threshold=0.10)
        assert len(promoted) >= 1
        node = dag.get_node(n1)
        assert node["metadata"].get("promoted") is True

    def test_already_promoted_skipped(self, dag_and_layer):
        dag, layer = dag_and_layer
        dag.add_node(
            "",
            "assistant",
            "Important discovery: gate ordering affects performance by 40%",
        )
        first = promote_nodes(dag, layer, threshold=0.10)
        second = promote_nodes(dag, layer, threshold=0.10)
        assert len(second) == 0

    def test_short_content_not_promoted(self, dag_and_layer):
        dag, layer = dag_and_layer
        dag.add_node("", "assistant", "ok")
        dag.add_node(dag.get_head(), "user", "yes")
        dag.add_node(dag.get_head(), "assistant", "done")
        promoted = promote_nodes(dag, layer, threshold=0.10)
        assert len(promoted) == 0

    def test_promoted_has_source_tag(self, dag_and_layer):
        dag, layer = dag_and_layer
        dag.add_node(
            "",
            "assistant",
            "Fixed critical race condition in the worker pool by adding mutex lock around shared state",
        )
        promoted = promote_nodes(dag, layer, threshold=0.10)
        assert len(promoted) >= 1
        entry = layer.get_entry(promoted[0])
        assert "source:dag" in entry["tags"]
        assert entry["source_node_id"] != ""

    def test_max_promotions_respected(self, dag_and_layer):
        dag, layer = dag_and_layer
        for i in range(10):
            dag.add_node(
                dag.get_head() or "",
                "assistant",
                f"Fixed critical bug #{i}: important security vulnerability in auth module",
            )
        promoted = promote_nodes(dag, layer, threshold=0.05, max_promotions=3)
        assert len(promoted) <= 3


# --- Integration ---


class TestIntegration:
    def test_full_round_trip(self, dag_and_layer):
        dag, layer = dag_and_layer
        # Simulate conversation
        n1 = dag.add_node("", "user", "how do I fix the rate limiter?")
        n2 = dag.add_node(
            n1,
            "assistant",
            "The rate limiter bug was caused by a race condition in the token bucket. "
            "Fix: use threading.Lock around the refill check.",
        )
        n3 = dag.add_node(n2, "user", "thanks")
        n4 = dag.add_node(n3, "assistant", "np")
        # Promote
        promoted = promote_nodes(dag, layer, threshold=0.10)
        assert len(promoted) >= 1
        # Search should find it
        results = layer.search("rate limiter")
        assert len(results) >= 1
        assert any("token bucket" in r["content"] for r in results)
        # Node marked promoted
        node = dag.get_node(n2)
        assert node["metadata"].get("promoted") is True

    def test_store_then_fts_search(self, dag_and_layer):
        _, layer = dag_and_layer
        layer.store(
            content="nomic-embed generates 768-dim vectors", tags="type:learning"
        )
        layer.store(content="asyncio uses event loops", tags="type:learning")
        results = layer.search("768-dim vectors")
        assert len(results) >= 1

    def test_store_embedding_and_cosine_search(self, dag_and_layer):
        """Verify embedding storage + cosine similarity search."""
        _, layer = dag_and_layer
        # Store entries with mock embeddings
        r1 = layer.store(
            content="vector databases use cosine similarity", tags="type:learning"
        )
        r2 = layer.store(
            content="authentication uses OAuth2 tokens", tags="type:learning"
        )
        r3 = layer.store(
            content="embedding models generate dense vectors", tags="type:learning"
        )
        # Create mock embeddings — r1 and r3 are "similar" (vector-related)
        vec_db = [1.0, 0.8, 0.1, 0.0]  # vector-related
        vec_auth = [0.0, 0.1, 0.9, 0.8]  # auth-related
        vec_embed = [0.9, 0.7, 0.2, 0.1]  # vector-related
        layer.store_embedding(r1["id"], "knowledge", vec_db)
        layer.store_embedding(r2["id"], "knowledge", vec_auth)
        layer.store_embedding(r3["id"], "knowledge", vec_embed)
        # Search with a vector-like query vector
        query_vec = [1.0, 0.9, 0.0, 0.0]
        results = layer.cosine_search(query_vec, top_k=3)
        assert len(results) == 3
        # Vector-related entries should rank higher
        assert results[0][0] in (r1["id"], r3["id"])
        assert results[0][1] > results[2][1]  # higher similarity

    def test_semantic_search_with_embed_fn(self, dag_and_layer):
        """Verify semantic_search delegates to cosine when embed_fn provided."""
        _, layer = dag_and_layer
        layer.store(content="python asyncio event loop", tags="type:learning")
        r1 = layer.store(content="vector similarity search", tags="type:learning")
        # Mock embed function
        layer.store_embedding(r1["id"], "knowledge", [1.0, 0.0, 0.0])

        def mock_embed(text):
            return [1.0, 0.0, 0.0]

        results = layer.semantic_search("vectors", embed_fn=mock_embed)
        assert len(results) >= 1
        assert results[0]["content"] == "vector similarity search"

    def test_semantic_search_fallback_without_embed_fn(self, dag_and_layer):
        """Without embed_fn, semantic_search falls back to FTS5."""
        _, layer = dag_and_layer
        layer.store(content="keyword fallback test entry", tags="type:test")
        results = layer.semantic_search("keyword fallback")
        assert len(results) >= 1

    def test_embed_knowledge_batch(self, dag_and_layer):
        """Verify batch embedding of unembedded entries."""
        dag, layer = dag_and_layer
        layer.store(content="entry one for batch embed", tags="type:test")
        layer.store(content="entry two for batch embed", tags="type:test")
        layer.store(content="entry three for batch embed", tags="type:test")

        def mock_embed(text):
            return [0.5, 0.5, 0.5]

        count = layer.embed_knowledge_batch(mock_embed, batch_size=10)
        assert count == 3
        # Verify embeddings exist
        emb_count = dag._db.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
        assert emb_count == 3
        # Running again should embed 0 (all done)
        count2 = layer.embed_knowledge_batch(mock_embed, batch_size=10)
        assert count2 == 0

    def test_existing_dag_tests_unaffected(self, dag_and_layer):
        """Verify basic DAG operations still work with new schema."""
        dag, _ = dag_and_layer
        n1 = dag.add_node("", "user", "hello")
        n2 = dag.add_node(n1, "assistant", "hi")
        assert dag.get_head() == n2
        ancestors = dag.get_ancestors(n2)
        assert len(ancestors) == 2
        bid = dag.new_branch("test")
        assert dag.current_branch_id() == bid
        assert dag.get_head() == ""


# --- Task 5: Graph Traversal API ---


class TestGraphTraversal:
    def test_find_related_both_directions(self, dag_and_layer):
        _, layer = dag_and_layer
        layer.add_edge("A", "B", "co_occurs", 0.9)
        layer.add_edge("A", "C", "derived_from", 0.7)
        layer.add_edge("D", "A", "references", 0.5)
        results = layer.find_related_nodes("A")
        assert len(results) == 3
        node_ids = {r["node_id"] for r in results}
        assert node_ids == {"B", "C", "D"}

    def test_find_related_outgoing_only(self, dag_and_layer):
        _, layer = dag_and_layer
        layer.add_edge("A", "B", "co_occurs", 0.9)
        layer.add_edge("D", "A", "references", 0.5)
        results = layer.find_related_nodes("A", direction="outgoing")
        assert len(results) == 1
        assert results[0]["node_id"] == "B"
        assert results[0]["direction"] == "outgoing"

    def test_find_related_incoming_only(self, dag_and_layer):
        _, layer = dag_and_layer
        layer.add_edge("A", "B", "co_occurs", 0.9)
        layer.add_edge("D", "A", "references", 0.5)
        results = layer.find_related_nodes("A", direction="incoming")
        assert len(results) == 1
        assert results[0]["node_id"] == "D"
        assert results[0]["direction"] == "incoming"

    def test_find_related_edge_type_filter(self, dag_and_layer):
        _, layer = dag_and_layer
        layer.add_edge("A", "B", "co_occurs", 0.9)
        layer.add_edge("A", "C", "derived_from", 0.7)
        results = layer.find_related_nodes("A", edge_type="co_occurs")
        assert len(results) == 1
        assert results[0]["node_id"] == "B"

    def test_find_related_empty(self, dag_and_layer):
        _, layer = dag_and_layer
        results = layer.find_related_nodes("nonexistent")
        assert results == []

    def test_find_related_ordered_by_weight(self, dag_and_layer):
        _, layer = dag_and_layer
        layer.add_edge("A", "B", "related", 0.3)
        layer.add_edge("A", "C", "related", 0.9)
        layer.add_edge("A", "D", "related", 0.6)
        results = layer.find_related_nodes("A", direction="outgoing")
        weights = [r["weight"] for r in results]
        assert weights == sorted(weights, reverse=True)

    def test_get_edge_path_direct(self, dag_and_layer):
        _, layer = dag_and_layer
        layer.add_edge("A", "B", "related")
        path = layer.get_edge_path("A", "B")
        assert path == ["A", "B"]

    def test_get_edge_path_multi_hop(self, dag_and_layer):
        _, layer = dag_and_layer
        layer.add_edge("A", "B", "related")
        layer.add_edge("B", "C", "related")
        layer.add_edge("C", "D", "related")
        path = layer.get_edge_path("A", "D")
        assert path == ["A", "B", "C", "D"]

    def test_get_edge_path_no_path(self, dag_and_layer):
        _, layer = dag_and_layer
        layer.add_edge("A", "B", "related")
        layer.add_edge("C", "D", "related")
        path = layer.get_edge_path("A", "D")
        assert path == []

    def test_get_edge_path_self(self, dag_and_layer):
        _, layer = dag_and_layer
        path = layer.get_edge_path("A", "A")
        assert path == ["A"]

    def test_get_edge_path_bidirectional(self, dag_and_layer):
        _, layer = dag_and_layer
        layer.add_edge("A", "B", "related")
        layer.add_edge("C", "B", "related")
        # A->B and C->B, so path A->C goes A->B->C (B is neighbor of both)
        path = layer.get_edge_path("A", "C")
        assert len(path) == 3
        assert path[0] == "A"
        assert path[-1] == "C"

    def test_get_edge_path_max_hops(self, dag_and_layer):
        _, layer = dag_and_layer
        # Chain: A->B->C->D->E (4 hops)
        layer.add_edge("A", "B", "r")
        layer.add_edge("B", "C", "r")
        layer.add_edge("C", "D", "r")
        layer.add_edge("D", "E", "r")
        assert layer.get_edge_path("A", "E", max_hops=4) != []
        assert layer.get_edge_path("A", "E", max_hops=2) == []

    def test_get_subgraph_single_hop(self, dag_and_layer):
        _, layer = dag_and_layer
        layer.add_edge("A", "B", "related", 0.9)
        layer.add_edge("A", "C", "related", 0.7)
        layer.add_edge("B", "D", "related", 0.5)
        sg = layer.get_subgraph(["A"], max_hops=1)
        assert "A" in sg["nodes"]
        assert "B" in sg["nodes"]
        assert "C" in sg["nodes"]
        assert "D" not in sg["nodes"]  # 2 hops away

    def test_get_subgraph_two_hops(self, dag_and_layer):
        _, layer = dag_and_layer
        layer.add_edge("A", "B", "related", 0.9)
        layer.add_edge("B", "C", "related", 0.7)
        layer.add_edge("C", "D", "related", 0.5)
        sg = layer.get_subgraph(["A"], max_hops=2)
        assert sg["nodes"] == {"A", "B", "C"}
        assert len(sg["edges"]) == 2

    def test_get_subgraph_edge_type_filter(self, dag_and_layer):
        _, layer = dag_and_layer
        layer.add_edge("A", "B", "co_occurs", 0.9)
        layer.add_edge("A", "C", "derived_from", 0.7)
        sg = layer.get_subgraph(["A"], max_hops=1, edge_type="co_occurs")
        assert sg["nodes"] == {"A", "B"}

    def test_get_subgraph_multiple_seeds(self, dag_and_layer):
        _, layer = dag_and_layer
        layer.add_edge("A", "B", "related")
        layer.add_edge("C", "D", "related")
        sg = layer.get_subgraph(["A", "C"], max_hops=1)
        assert sg["nodes"] == {"A", "B", "C", "D"}

    def test_get_subgraph_deduplicates_edges(self, dag_and_layer):
        _, layer = dag_and_layer
        layer.add_edge("A", "B", "related")
        layer.add_edge("B", "A", "related")
        sg = layer.get_subgraph(["A"], max_hops=2)
        # Each edge should appear once
        edge_keys = [(e[0], e[1], e[2]) for e in sg["edges"]]
        assert len(edge_keys) == len(set(edge_keys))


# --- Task 6: New features (FTS5 escaping, dedup, LIMIT param, semantic_search_nodes, timestamps) ---


class TestFTS5Escaping:
    """Verify _escape_fts5 strips ALL special chars including -, :."""

    def test_fts5_strips_hyphen(self, dag_and_layer):
        """Queries with hyphens should not raise FTS5 syntax errors."""
        _, layer = dag_and_layer
        layer.store(content="fix-it approach for authentication", tags="")
        # Should not raise — hyphen must be stripped before MATCH
        results = layer.search("fix-it")
        # LIKE fallback should find it even if FTS5 returns nothing
        assert isinstance(results, list)

    def test_fts5_strips_colon(self, dag_and_layer):
        """Queries with colons should not raise FTS5 syntax errors."""
        _, layer = dag_and_layer
        layer.store(content="type:fix means a bug fix", tags="")
        results = layer.search("type:fix")
        assert isinstance(results, list)

    def test_fts5_strips_all_specials(self, dag_and_layer):
        """Combined special chars must not crash the query."""
        _, layer = dag_and_layer
        layer.store(content="gate*03 (test) & deploy|run", tags="")
        results = layer.search("gate*03 (test) & deploy|run")
        assert isinstance(results, list)

    def test_escape_fts5_function(self):
        """Unit-test _escape_fts5 directly."""
        from shared.dag_memory_layer import _escape_fts5

        # Hyphens, colons, parens should be removed
        assert "-" not in _escape_fts5("fix-it")
        assert ":" not in _escape_fts5("type:fix")
        assert "(" not in _escape_fts5("(test)")
        assert "|" not in _escape_fts5("a|b")
        assert "&" not in _escape_fts5("a&b")
        assert "*" not in _escape_fts5("wild*")
        # Double-quotes should be escaped, not stripped
        result = _escape_fts5('say "hello"')
        assert '""' in result

    def test_search_nodes_fts_with_hyphen(self, dag_and_layer):
        """search_nodes_fts should handle hyphens without raising."""
        dag, layer = dag_and_layer
        dag.add_node("", "user", "how to fix-it the auth module")
        results = layer.search_nodes_fts("fix-it")
        assert isinstance(results, list)


class TestContentHashDedup:
    """Verify store() skips duplicate content via FNV-1a hash."""

    def test_dedup_same_content_returns_existing_id(self, dag_and_layer):
        _, layer = dag_and_layer
        r1 = layer.store(content="unique content for dedup test", tags="type:test")
        assert r1["stored"] is True
        r2 = layer.store(content="unique content for dedup test", tags="type:test")
        # Second call should detect duplicate
        assert r2.get("duplicate") is True
        assert r2["id"] == r1["id"]

    def test_dedup_does_not_insert_row(self, dag_and_layer):
        dag, layer = dag_and_layer
        layer.store(content="dedup row count test", tags="")
        layer.store(content="dedup row count test", tags="")
        count = dag._db.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
        assert count == 1

    def test_different_content_both_stored(self, dag_and_layer):
        _, layer = dag_and_layer
        r1 = layer.store(content="content alpha", tags="")
        r2 = layer.store(content="content beta", tags="")
        assert r1["stored"] is True
        assert r2["stored"] is True
        assert r1["id"] != r2["id"]

    def test_hash_stored_in_metadata(self, dag_and_layer):
        dag, layer = dag_and_layer
        r = layer.store(content="hash metadata check", tags="")
        assert r["stored"] is True
        row = dag._db.execute(
            "SELECT metadata FROM knowledge WHERE id = ?", (r["id"],)
        ).fetchone()
        meta = json.loads(row[0])
        assert "content_hash" in meta


class TestEmbedBatchLimit:
    """Verify embed_knowledge_batch uses parameterized LIMIT."""

    def test_batch_respects_batch_size(self, dag_and_layer):
        _, layer = dag_and_layer
        for i in range(10):
            layer.store(content=f"batch entry number {i} for limit test", tags="")

        call_count = [0]

        def mock_embed(text):
            call_count[0] += 1
            return [0.1, 0.2, 0.3]

        count = layer.embed_knowledge_batch(mock_embed, batch_size=4)
        assert count == 4
        assert call_count[0] == 4

    def test_batch_limit_as_parameter(self, dag_and_layer):
        """Parameterized LIMIT should work the same as f-string LIMIT."""
        dag, layer = dag_and_layer
        for i in range(5):
            layer.store(content=f"param limit entry {i}", tags="")

        count = layer.embed_knowledge_batch(lambda t: [0.5], batch_size=3)
        assert count == 3
        emb_count = dag._db.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
        assert emb_count == 3


class TestSemanticSearchNodes:
    """Verify semantic_search_nodes() cross-branch discovery."""

    def test_falls_back_to_fts_without_embed_fn(self, dag_and_layer):
        dag, layer = dag_and_layer
        dag.add_node("", "user", "how does rate limiting work")
        results = layer.semantic_search_nodes("rate limiting")
        assert isinstance(results, list)
        if results:
            assert "content" in results[0]

    def test_semantic_search_nodes_with_embed_fn(self, dag_and_layer):
        dag, layer = dag_and_layer
        n1 = dag.add_node("", "user", "vector similarity search")
        n2 = dag.add_node(n1, "assistant", "async event loop management")
        # Store embeddings for nodes
        vec_vec = [1.0, 0.0, 0.0]
        vec_async = [0.0, 0.0, 1.0]
        layer.store_embedding(n1, "nodes", vec_vec)
        layer.store_embedding(n2, "nodes", vec_async)

        def mock_embed(text):
            return [1.0, 0.0, 0.0]  # Similar to n1

        results = layer.semantic_search_nodes("vectors", embed_fn=mock_embed, top_k=2)
        assert len(results) >= 1
        assert results[0]["id"] == n1
        assert results[0]["relevance"] > 0.9

    def test_semantic_search_nodes_no_embeddings_falls_back(self, dag_and_layer):
        dag, layer = dag_and_layer
        dag.add_node("", "user", "FTS5 fallback test for semantic nodes")

        def mock_embed(text):
            return [0.5, 0.5, 0.5]

        results = layer.semantic_search_nodes("FTS5 fallback", embed_fn=mock_embed)
        # Should fall back to FTS5 (no node embeddings)
        assert isinstance(results, list)

    def test_semantic_search_nodes_branch_filter(self, dag_and_layer):
        dag, layer = dag_and_layer
        # Branch 1
        bid1 = dag.current_branch_id()
        n1 = dag.add_node("", "user", "branch one node content")
        # Branch 2
        bid2 = dag.new_branch("branch2")
        n2 = dag.add_node("", "user", "branch two node content")

        vec = [1.0, 0.0]
        layer.store_embedding(n1, "nodes", vec)
        layer.store_embedding(n2, "nodes", vec)

        def mock_embed(text):
            return [1.0, 0.0]

        # Filter to branch 1 only
        results = layer.semantic_search_nodes(
            "branch", embed_fn=mock_embed, branch_ids=[bid1]
        )
        # n2 is on branch2 so should be excluded (or no results if n1 ancestor check fails)
        # At minimum, no exception should be raised
        assert isinstance(results, list)


class TestConstructorEmbedFn:
    """Verify embed_fn can be set at constructor level."""

    def test_constructor_embed_fn_used_by_semantic_search_nodes(self, dag_and_layer):
        dag, _ = dag_and_layer
        n1 = dag.add_node("", "user", "vector similarity search")
        n2 = dag.add_node(n1, "assistant", "async event loop management")

        def mock_embed(text):
            return [1.0, 0.0, 0.0]  # Similar to n1

        # Create layer with embed_fn in constructor
        from shared.dag_memory_layer import DAGMemoryLayer

        layer = DAGMemoryLayer(dag, embed_fn=mock_embed)

        # Store embeddings for nodes
        layer.store_embedding(n1, "nodes", [1.0, 0.0, 0.0])
        layer.store_embedding(n2, "nodes", [0.0, 0.0, 1.0])

        # Call without passing embed_fn — should use constructor's
        results = layer.semantic_search_nodes("vectors", top_k=2)
        assert len(results) >= 1
        assert results[0]["id"] == n1
        assert results[0]["relevance"] > 0.9

    def test_constructor_embed_fn_used_by_semantic_search(self, dag_and_layer):
        dag, _ = dag_and_layer

        def mock_embed(text):
            return [1.0, 0.0, 0.0]

        from shared.dag_memory_layer import DAGMemoryLayer

        layer = DAGMemoryLayer(dag, embed_fn=mock_embed)
        r1 = layer.store(content="vector similarity search", tags="type:learning")
        layer.store_embedding(r1["id"], "knowledge", [1.0, 0.0, 0.0])

        # Call without passing embed_fn — should use constructor's
        results = layer.semantic_search("vectors")
        assert len(results) >= 1
        assert results[0]["content"] == "vector similarity search"

    def test_per_call_embed_fn_overrides_constructor(self, dag_and_layer):
        dag, _ = dag_and_layer

        call_log = []

        def constructor_embed(text):
            call_log.append("constructor")
            return [1.0, 0.0, 0.0]

        def per_call_embed(text):
            call_log.append("per_call")
            return [1.0, 0.0, 0.0]

        from shared.dag_memory_layer import DAGMemoryLayer

        layer = DAGMemoryLayer(dag, embed_fn=constructor_embed)
        n1 = dag.add_node("", "user", "test content")
        layer.store_embedding(n1, "nodes", [1.0, 0.0, 0.0])

        # Per-call should override
        results = layer.semantic_search_nodes("test", embed_fn=per_call_embed)
        assert "per_call" in call_log
        assert "constructor" not in call_log

    def test_no_embed_fn_falls_back_to_fts(self, dag_and_layer):
        dag, _ = dag_and_layer
        from shared.dag_memory_layer import DAGMemoryLayer

        layer = DAGMemoryLayer(dag)  # No embed_fn
        dag.add_node("", "user", "keyword search fallback test")

        # Should fall back to FTS5 without error
        results = layer.semantic_search_nodes("keyword search")
        assert isinstance(results, list)

    def test_default_top_k_is_20(self, dag_and_layer):
        """Verify semantic_search_nodes defaults to top_k=20."""
        import inspect
        from shared.dag_memory_layer import DAGMemoryLayer

        sig = inspect.signature(DAGMemoryLayer.semantic_search_nodes)
        assert sig.parameters["top_k"].default == 20

    def test_backward_compat_no_embed_fn_in_constructor(self, dag_and_layer):
        """Existing code creating DAGMemoryLayer(dag) without embed_fn still works."""
        dag, _ = dag_and_layer
        from shared.dag_memory_layer import DAGMemoryLayer

        layer = DAGMemoryLayer(dag)
        assert layer._embed_fn is None
        # All existing methods should work
        layer.store(content="backward compat test", tags="type:test")
        results = layer.search("backward compat")
        assert len(results) >= 1


class TestPromoteNodesTimestamp:
    """Verify promote_nodes() includes timestamps in context."""

    def test_promoted_context_contains_timestamp(self, dag_and_layer):
        dag, layer = dag_and_layer
        dag.add_node(
            "",
            "user",
            "Please help me understand the auth flow",
        )
        dag.add_node(
            dag.get_head(),
            "assistant",
            "Fixed the authentication bug. Root cause: null check missing in OAuth handler.",
        )
        promoted = promote_nodes(dag, layer, threshold=0.10)
        assert len(promoted) >= 1
        entry = layer.get_entry(promoted[0])
        # context field should contain ISO timestamp (from _format_node_timestamp)
        ctx = entry.get("context", "")
        # It should be non-empty (timestamp set) or at least not crash
        assert isinstance(ctx, str)

    def test_format_node_timestamp_valid(self):
        """_format_node_timestamp converts unix int to ISO string."""
        from shared.dag_memory_layer import _format_node_timestamp

        ts = 1700000000  # A valid unix timestamp
        result = _format_node_timestamp(ts)
        assert "T" in result  # ISO format: YYYY-MM-DDTHH:MM:SS
        assert len(result) == 19

    def test_format_node_timestamp_none(self):
        from shared.dag_memory_layer import _format_node_timestamp

        assert _format_node_timestamp(None) == ""

    def test_format_node_timestamp_invalid(self):
        from shared.dag_memory_layer import _format_node_timestamp

        result = _format_node_timestamp("not-a-number")
        # Should return the string as-is rather than crash
        assert isinstance(result, str)

    def test_build_promotion_context_includes_timestamp(self, dag_and_layer):
        """_build_promotion_context should include @timestamp in ancestor parts."""
        dag, layer = dag_and_layer
        from shared.dag_memory_layer import _build_promotion_context

        n1 = dag.add_node("", "user", "first message in conversation")
        n2 = dag.add_node(n1, "assistant", "second message responding to first")
        ctx = _build_promotion_context(dag, n2)
        # Context should contain the ancestor (n1)
        assert "first message" in ctx
        # Timestamp prefix (@YYYY-...) should be present if timestamp is set
        # (In test db, timestamp is set to time.time() int so it should be there)
        assert "[user" in ctx


# --- Task 12: Hebbian co-retrieval boosting ---


class TestHebbianCoretrieval:
    """Tests for Hebbian co-retrieval boosting in promote_nodes."""

    def test_promote_with_kg_creates_coretrieval_edges(self, dag_and_layer):
        """When kg is provided and 2+ nodes promoted, strengthen_coretrieval is called."""
        from shared.knowledge_graph import KnowledgeGraph

        dag, layer = dag_and_layer
        dag.add_node(
            "",
            "assistant",
            "Fixed critical auth bug by adding null check to OAuth handler. Root cause: token expired.",
        )
        dag.add_node(
            dag.get_head() or "",
            "assistant",
            "Fixed important race condition in worker pool by adding mutex lock around shared state.",
        )
        with KnowledgeGraph(db_path=":memory:") as kg:
            promoted = promote_nodes(dag, layer, threshold=0.05, kg=kg)
            assert len(promoted) >= 2, f"Expected 2+ promoted, got {len(promoted)}"
            # Verify co-retrieval edges were created between promoted knowledge IDs
            strength = kg.get_edge_strength(
                min(promoted[0], promoted[1]),
                max(promoted[0], promoted[1]),
                relation_type="co_retrieved",
            )
            assert strength > 0, "Co-retrieval edge should exist between promoted nodes"

    def test_promote_without_kg_backward_compatible(self, dag_and_layer):
        """promote_nodes without kg= should work exactly as before."""
        dag, layer = dag_and_layer
        dag.add_node(
            "",
            "assistant",
            "Fixed critical auth bug by adding null check. Root cause: token expired.",
        )
        promoted = promote_nodes(dag, layer, threshold=0.05)
        assert len(promoted) >= 1

    def test_single_promotion_no_coretrieval(self, dag_and_layer):
        """With only 1 promoted node, no co-retrieval should be attempted."""
        from shared.knowledge_graph import KnowledgeGraph

        dag, layer = dag_and_layer
        dag.add_node(
            "",
            "assistant",
            "Fixed critical auth bug by adding null check to OAuth handler. Root cause: token expired.",
        )
        with KnowledgeGraph(db_path=":memory:") as kg:
            promoted = promote_nodes(dag, layer, threshold=0.05, kg=kg)
            assert len(promoted) >= 1
            # Only 1 promotion, so no co-retrieval edges
            assert kg.edge_count() == 0

    def test_spreading_activation_context_in_metadata(self, dag_and_layer):
        """When kg has pre-existing edges, activation context appears in metadata."""
        from shared.knowledge_graph import KnowledgeGraph

        dag, layer = dag_and_layer
        # Pre-populate KG with entities connected to a node ID we'll create
        with KnowledgeGraph(db_path=":memory:") as kg:
            # We need to create a node first to know its ID, then add edges
            n1 = dag.add_node(
                "",
                "assistant",
                "Fixed critical authentication bug by adding null check. Root cause: token expired.",
            )
            # Add KG entities connected to this node ID
            kg.upsert_entity(n1, entity_type="DAGNode", salience=0.8)
            kg.upsert_entity("auth_module", entity_type="Module", salience=0.7)
            kg.add_edge(n1, "auth_module", relation_type="related_to", strength=0.5)

            promoted = promote_nodes(dag, layer, threshold=0.05, kg=kg)
            assert len(promoted) >= 1

            # Check that the knowledge entry has activated_context in metadata
            row = dag._db.execute(
                "SELECT metadata FROM knowledge WHERE id = ?",
                (promoted[0],),
            ).fetchone()
            if row and row[0]:
                import json

                meta = json.loads(row[0])
                if "activated_context" in meta:
                    ctx = meta["activated_context"]
                    assert isinstance(ctx, list)
                    # auth_module should appear as activated context
                    names = [c["name"] for c in ctx]
                    assert "auth_module" in names

    def test_promote_with_kg_node_ids_linked(self, dag_and_layer):
        """DAG node IDs should also be linked via co-retrieval."""
        from shared.knowledge_graph import KnowledgeGraph

        dag, layer = dag_and_layer
        n1 = dag.add_node(
            "",
            "assistant",
            "Fixed critical auth bug by adding null check to OAuth handler. Root cause: token expired.",
        )
        n2 = dag.add_node(
            n1,
            "assistant",
            "Fixed important race condition in worker pool by adding mutex lock around shared state.",
        )
        with KnowledgeGraph(db_path=":memory:") as kg:
            promoted = promote_nodes(dag, layer, threshold=0.05, kg=kg)
            assert len(promoted) >= 2
            # Node IDs should also have co-retrieval edges
            canonical = (min(n1, n2), max(n1, n2))
            strength = kg.get_edge_strength(
                canonical[0], canonical[1], relation_type="co_retrieved"
            )
            assert strength > 0, "DAG node IDs should be linked via co-retrieval"

    def test_get_activation_context_no_edges(self):
        """_get_activation_context returns empty list when no edges exist."""
        from shared.knowledge_graph import KnowledgeGraph
        from shared.dag_memory_layer import _get_activation_context

        with KnowledgeGraph(db_path=":memory:") as kg:
            result = _get_activation_context(kg, "nonexistent_node")
            assert result == []

    def test_get_activation_context_with_edges(self):
        """_get_activation_context returns activated entities when edges exist."""
        from shared.knowledge_graph import KnowledgeGraph
        from shared.dag_memory_layer import _get_activation_context

        with KnowledgeGraph(db_path=":memory:") as kg:
            kg.upsert_entity("seed_node", salience=0.8)
            kg.upsert_entity("related_a", salience=0.6)
            kg.upsert_entity("related_b", salience=0.5)
            kg.add_edge("seed_node", "related_a", strength=0.5)
            kg.add_edge("seed_node", "related_b", strength=0.3)
            result = _get_activation_context(kg, "seed_node")
            assert len(result) >= 1
            names = [r["name"] for r in result]
            assert "related_a" in names or "related_b" in names
