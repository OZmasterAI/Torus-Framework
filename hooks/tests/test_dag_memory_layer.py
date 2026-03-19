#!/usr/bin/env python3
"""Tests for DAG Memory Layer — SQLite-backed memory on conversations.db."""

import json
import os
import sys
import tempfile

import pytest

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
