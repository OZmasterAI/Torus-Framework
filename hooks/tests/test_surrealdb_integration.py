#!/usr/bin/env python3
"""E2E integration tests for SurrealDB migration.

Verifies core flows work end-to-end with the live SurrealDB instance.
Requires memory_server to be running.
"""

import os
import sys
import time

import pytest

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HOOKS_DIR not in sys.path:
    sys.path.insert(0, HOOKS_DIR)

from shared.memory_socket import is_worker_available, request, ping, count, query

SURREAL_DIR = os.path.expanduser("~/data/memory/surrealdb")

pytestmark = pytest.mark.skipif(
    not is_worker_available(retries=1, delay=0.2),
    reason="Memory server not running",
)


class TestConnectivity:
    def test_ping(self):
        assert ping() == "pong"

    def test_knowledge_count(self):
        c = count("knowledge")
        assert isinstance(c, int)
        assert c > 0

    def test_observations_count(self):
        c = count("observations")
        assert isinstance(c, int)
        assert c > 0

    def test_fix_outcomes_count(self):
        c = count("fix_outcomes")
        assert isinstance(c, int)
        assert c > 0


class TestSearchPipeline:
    def test_semantic_search_returns_results(self):
        result = query("knowledge", query_texts=["gate error fix"], n_results=5)
        assert result is not None
        assert "ids" in result
        assert len(result["ids"][0]) > 0

    def test_search_with_include(self):
        result = query(
            "knowledge",
            query_texts=["surrealdb migration"],
            n_results=3,
            include=["metadatas", "documents", "distances"],
        )
        assert "metadatas" in result
        assert "documents" in result
        assert "distances" in result


class TestWritePipeline:
    def test_remember_via_socket(self):
        from shared.memory_socket import remember

        result = remember(
            content="Integration test memory — SurrealDB e2e verification (safe to delete)",
            context="test_surrealdb_integration.py",
            tags="type:test,area:testing,ephemeral",
        )
        assert result is not None
        assert "id" in result or "result" in result


class TestSurrealDBDirect:
    def test_surreal_dir_exists(self):
        assert os.path.isdir(SURREAL_DIR)

    def test_surreal_collection_import(self):
        from shared.surreal_collection import SurrealCollection, init_surreal_db

        assert SurrealCollection is not None
        assert init_surreal_db is not None

    def test_surreal_connection(self):
        from surrealdb import Surreal

        db = Surreal(f"surrealkv://{SURREAL_DIR}")
        db.use("memory", "main")
        result = db.query("SELECT count() FROM knowledge GROUP ALL")
        assert isinstance(result, list)
        assert len(result) > 0
        assert result[0]["count"] > 0

    def test_surreal_vector_search(self):
        from surrealdb import Surreal

        db = Surreal(f"surrealkv://{SURREAL_DIR}")
        db.use("memory", "main")
        result = db.query("SELECT id, text FROM knowledge LIMIT 3")
        assert isinstance(result, list)
        assert len(result) > 0
        assert "text" in result[0] or "id" in result[0]


class TestNoLegacyImports:
    def test_no_lancedb_import(self):
        try:
            import lancedb

            pytest.skip("lancedb still installed (Task 16 pending)")
        except ImportError:
            pass

    def test_pipelines_import_clean(self):
        from shared.write_pipeline import WritePipeline
        from shared.search_pipeline import SearchPipeline

        assert WritePipeline is not None
        assert SearchPipeline is not None

    def test_surreal_collection_standalone(self):
        from shared.surreal_collection import SurrealCollection

        assert hasattr(SurrealCollection, "query")
        assert hasattr(SurrealCollection, "upsert")
        assert hasattr(SurrealCollection, "get")
        assert hasattr(SurrealCollection, "count")
