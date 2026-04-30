"""Tests for SurrealCollection — SurrealDB table wrapper with ChromaDB-compatible API."""

import os
import shutil
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from surrealdb import Surreal, RecordID

TEST_DB_DIR = "/tmp/test_surreal_collection"


@pytest.fixture(scope="module")
def db():
    if os.path.exists(TEST_DB_DIR):
        shutil.rmtree(TEST_DB_DIR)
    conn = Surreal(f"surrealkv://{TEST_DB_DIR}")
    conn.use("test_ns", "test_db")
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def collection(db):
    from shared.surreal_collection import SurrealCollection

    fields = {
        "text": "string",
        "vector": "array<float>",
        "tier": "int",
        "tags": "string",
        "timestamp": "string",
        "preview": "string",
    }
    coll = SurrealCollection(
        db=db,
        table_name="test_coll",
        fields=fields,
        embedding_dim=4,
    )
    return coll


# ── Task 2: CRUD tests ──────────────────────────────────────────────


class TestCount:
    def test_empty_count(self, collection):
        assert collection.count() == 0

    def test_count_after_inserts(self, collection):
        collection.upsert(
            ids=["c1", "c2", "c3"],
            documents=["doc one", "doc two", "doc three"],
            vectors=[[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]],
            metadatas=[{"tier": 1}, {"tier": 2}, {"tier": 3}],
        )
        assert collection.count() == 3


class TestUpsert:
    def test_upsert_creates(self, collection):
        collection.upsert(
            ids=["u1"],
            documents=["upsert test"],
            vectors=[[0.5, 0.5, 0, 0]],
            metadatas=[{"tier": 1, "tags": "type:test"}],
        )
        result = collection.get(ids=["u1"])
        assert result["ids"] == ["u1"]
        assert result["documents"][0] == "upsert test"
        assert result["metadatas"][0]["tier"] == 1

    def test_upsert_updates_not_duplicates(self, collection):
        before = collection.count()
        collection.upsert(
            ids=["u1"],
            documents=["upsert UPDATED"],
            vectors=[[0.6, 0.4, 0, 0]],
            metadatas=[{"tier": 5, "tags": "type:updated"}],
        )
        after = collection.count()
        assert after == before, f"Upsert created duplicate: {before} -> {after}"
        result = collection.get(ids=["u1"])
        assert result["documents"][0] == "upsert UPDATED"
        assert result["metadatas"][0]["tier"] == 5


class TestGet:
    def test_get_by_ids(self, collection):
        result = collection.get(ids=["c1", "c2"])
        assert set(result["ids"]) == {"c1", "c2"}
        assert len(result["documents"]) == 2
        assert len(result["metadatas"]) == 2

    def test_get_single(self, collection):
        result = collection.get(ids=["c1"])
        assert result["ids"] == ["c1"]
        assert result["documents"][0] == "doc one"

    def test_get_nonexistent(self, collection):
        result = collection.get(ids=["nonexistent_xyz"])
        assert result["ids"] == []

    def test_get_returns_flat_format(self, collection):
        result = collection.get(ids=["c1"])
        assert isinstance(result["ids"], list)
        assert not isinstance(result["ids"][0], list), (
            "get() should return flat, not nested"
        )


class TestUpdate:
    def test_update_metadata(self, collection):
        collection.update(ids=["c1"], metadatas=[{"tier": 99}])
        result = collection.get(ids=["c1"])
        assert result["metadatas"][0]["tier"] == 99
        assert result["documents"][0] == "doc one", "Update should not change document"

    def test_update_preserves_other_fields(self, collection):
        collection.upsert(
            ids=["upd_test"],
            documents=["preserve me"],
            vectors=[[0.1, 0.2, 0.3, 0.4]],
            metadatas=[{"tier": 1, "tags": "type:fix", "preview": "short"}],
        )
        collection.update(ids=["upd_test"], metadatas=[{"tier": 10}])
        result = collection.get(ids=["upd_test"])
        meta = result["metadatas"][0]
        assert meta["tier"] == 10
        assert meta.get("tags") == "type:fix", "Other metadata should be preserved"


class TestDelete:
    def test_delete_removes_record(self, collection):
        collection.upsert(
            ids=["del1"],
            documents=["delete me"],
            vectors=[[0, 0, 0, 1]],
            metadatas=[{"tier": 0}],
        )
        before = collection.count()
        collection.delete(ids=["del1"])
        after = collection.count()
        assert after == before - 1

    def test_delete_makes_get_return_empty(self, collection):
        collection.upsert(
            ids=["del2"],
            documents=["also delete me"],
            vectors=[[0, 0, 1, 1]],
            metadatas=[{"tier": 0}],
        )
        collection.delete(ids=["del2"])
        result = collection.get(ids=["del2"])
        assert result["ids"] == []


# ── Task 3: Vector search + BM25 + where-clauses ────────────────────


@pytest.fixture(scope="module")
def search_collection(db):
    from shared.surreal_collection import SurrealCollection

    fields = {
        "text": "string",
        "vector": "array<float>",
        "tier": "int",
        "tags": "string",
    }
    coll = SurrealCollection(
        db=db,
        table_name="search_coll",
        fields=fields,
        embedding_dim=4,
    )
    coll.init_indexes()
    coll.upsert(
        ids=["s1", "s2", "s3", "s4", "s5"],
        documents=[
            "The framework gate system enforces safety checks",
            "Memory server stores knowledge vectors for retrieval",
            "SurrealDB migration replaces LanceDB backend",
            "Python testing with pytest and fixtures",
            "Git branching strategy for feature development",
        ],
        vectors=[
            [1.0, 0.0, 0.0, 0.0],
            [0.9, 0.1, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ],
        metadatas=[
            {"tier": 1, "tags": "type:fix"},
            {"tier": 2, "tags": "type:learning"},
            {"tier": 3, "tags": "type:feature"},
            {"tier": 1, "tags": "type:test"},
            {"tier": 2, "tags": "type:learning"},
        ],
    )
    return coll


class TestVectorSearch:
    def test_query_returns_nested_format(self, search_collection):
        result = search_collection.query(query_vector=[1.0, 0.0, 0.0, 0.0], n_results=3)
        assert isinstance(result["ids"][0], list), "query() should return nested format"
        assert len(result["ids"][0]) <= 3

    def test_query_ordered_by_similarity(self, search_collection):
        result = search_collection.query(query_vector=[1.0, 0.0, 0.0, 0.0], n_results=3)
        assert result["ids"][0][0] == "s1", (
            f"Closest should be s1, got {result['ids'][0][0]}"
        )
        assert result["ids"][0][1] == "s2", (
            f"Second should be s2, got {result['ids'][0][1]}"
        )

    def test_query_returns_distances(self, search_collection):
        result = search_collection.query(
            query_vector=[1.0, 0.0, 0.0, 0.0],
            n_results=3,
            include=["distances"],
        )
        dists = result["distances"][0]
        assert dists[0] < dists[1], "First result should have smaller distance"
        assert all(d >= 0 for d in dists), "Distances should be non-negative"

    def test_query_returns_metadatas(self, search_collection):
        result = search_collection.query(
            query_vector=[1.0, 0.0, 0.0, 0.0],
            n_results=2,
            include=["metadatas", "documents"],
        )
        assert "metadatas" in result
        assert "documents" in result
        assert len(result["metadatas"][0]) == 2

    def test_query_with_where_filter(self, search_collection):
        result = search_collection.query(
            query_vector=[1.0, 0.0, 0.0, 0.0],
            n_results=5,
            where={"tier": {"$gte": 2}},
        )
        ids = result["ids"][0]
        assert "s1" not in ids, "s1 has tier=1, should be filtered out"
        assert "s4" not in ids, "s4 has tier=1, should be filtered out"

    def test_query_with_compound_where(self, search_collection):
        result = search_collection.query(
            query_vector=[1.0, 0.0, 0.0, 0.0],
            n_results=5,
            where={"$and": [{"tier": {"$gte": 2}}, {"tags": {"$eq": "type:learning"}}]},
        )
        ids = result["ids"][0]
        for rid in ids:
            r = search_collection.get(ids=[rid])
            assert r["metadatas"][0]["tier"] >= 2
            assert r["metadatas"][0]["tags"] == "type:learning"


class TestKeywordSearch:
    def test_keyword_returns_results(self, search_collection):
        results = search_collection.keyword_search("framework gate", top_k=3)
        assert len(results) > 0
        assert "id" in results[0]
        assert "score" in results[0]

    def test_keyword_scores_ordering(self, search_collection):
        results = search_collection.keyword_search("memory server knowledge", top_k=5)
        if len(results) >= 2:
            scores = [r["score"] for r in results]
            assert scores == sorted(scores, reverse=True), (
                "Results should be ordered by score DESC"
            )

    def test_keyword_no_results_for_gibberish(self, search_collection):
        results = search_collection.keyword_search("xyzzyplughtwisty", top_k=3)
        assert len(results) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
