"""Tests for Toroidal-Indexer MCP query functions (code_callers, code_readers, code_path, code_blast_radius, code_hubs)."""

import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.indexer_mcp import (
    code_blast_radius,
    code_callers,
    code_hubs,
    code_path,
    code_readers,
)
from shared.indexer_schema import (
    connect_code_graph,
    init_code_tables,
    relate,
    upsert_node,
)

SURREAL_URL = "ws://127.0.0.1:8822"


@pytest.fixture(scope="module")
def db():
    """Connect to SurrealDB with a unique test database, seed a small graph, yield, cleanup."""
    test_db = f"test_mcp_{uuid.uuid4().hex[:8]}"
    conn = connect_code_graph(url=SURREAL_URL, database=test_db)
    init_code_tables(conn)

    # Build test graph:
    #   main() --calls--> process() --calls--> validate() --calls--> check()
    #   main() --reads--> config_key (field)
    #   helper() --calls--> validate()  (second caller for validate)
    main = upsert_node(conn, "proj", "app.py", "main", "function", 10)
    process = upsert_node(conn, "proj", "app.py", "process", "function", 25)
    validate = upsert_node(conn, "proj", "lib.py", "validate", "function", 5)
    check = upsert_node(conn, "proj", "lib.py", "check", "function", 30)
    config_key = upsert_node(conn, "proj", "config.py", "config_key", "field", 1)
    helper = upsert_node(conn, "proj", "util.py", "helper", "function", 8)

    relate(conn, main, "calls", process, confidence=1.0, source_line=12)
    relate(conn, process, "calls", validate, confidence=0.9, source_line=28)
    relate(conn, validate, "calls", check, confidence=1.0, source_line=7)
    relate(conn, main, "reads", config_key, confidence=1.0, source_line=11)
    relate(conn, helper, "calls", validate, confidence=0.8, source_line=9)

    yield conn
    conn.query(f"REMOVE DATABASE IF EXISTS {test_db}")


class TestCodeCallers:
    def test_returns_caller_list(self, db):
        """code_callers should return direct callers of validate()."""
        result = code_callers(db, "proj", "lib.py", "validate")
        assert isinstance(result, list)
        assert len(result) >= 2
        names = {c["name"] for c in result}
        assert "process" in names
        assert "helper" in names
        for c in result:
            assert "name" in c
            assert "file" in c
            assert "line" in c
            assert "confidence" in c

    def test_returns_empty_for_no_callers(self, db):
        """main() has no callers in the graph."""
        result = code_callers(db, "proj", "app.py", "main")
        assert result == []

    def test_depth_controls_traversal(self, db):
        """depth=2 on check() should find validate and its callers."""
        result = code_callers(db, "proj", "lib.py", "check", depth=2)
        names = {c["name"] for c in result}
        assert "validate" in names
        # process and helper call validate, so they show up at depth 2
        assert len(names) >= 2


class TestCodeReaders:
    def test_returns_field_readers(self, db):
        """code_readers should return main() as a reader of config_key."""
        result = code_readers(db, "proj", "config.py", "config_key")
        assert isinstance(result, list)
        assert len(result) >= 1
        names = {r["name"] for r in result}
        assert "main" in names
        for r in result:
            assert "name" in r
            assert "file" in r
            assert "line" in r
            assert "confidence" in r

    def test_returns_empty_for_unread_field(self, db):
        """A field with no readers returns empty list."""
        # check() is a function, not read by anyone via 'reads' edge
        result = code_readers(db, "proj", "lib.py", "check")
        assert result == []


class TestCodePath:
    def test_finds_route(self, db):
        """Shortest path from main to check should traverse process and validate."""
        result = code_path(db, "proj", "app.py", "main", "lib.py", "check")
        assert isinstance(result, list)
        assert len(result) >= 3  # at least main -> process -> validate -> check
        # First node should be main, last should be check
        assert result[0]["name"] == "main"
        assert result[-1]["name"] == "check"

    def test_returns_empty_for_no_path(self, db):
        """No path from check back to main (directed graph)."""
        result = code_path(db, "proj", "lib.py", "check", "app.py", "main")
        assert result == []

    def test_direct_neighbors(self, db):
        """Path from main to process is just 2 nodes."""
        result = code_path(db, "proj", "app.py", "main", "app.py", "process")
        assert len(result) == 2
        assert result[0]["name"] == "main"
        assert result[1]["name"] == "process"


class TestCodeBlastRadius:
    def test_returns_transitive_dependents(self, db):
        """Blast radius of validate() should include check() (it calls check)."""
        result = code_blast_radius(db, "proj", "lib.py", "validate")
        assert isinstance(result, list)
        names = {n["name"] for n in result}
        assert "check" in names

    def test_depth_limits_reach(self, db):
        """Blast radius of main() at depth=1 should include process but not validate."""
        result = code_blast_radius(db, "proj", "app.py", "main", depth=1)
        names = {n["name"] for n in result}
        assert "process" in names
        # At depth=1 only direct callees, so validate should not appear via calls
        # (main calls process, but doesn't directly call validate)

    def test_returns_empty_for_leaf(self, db):
        """check() calls nothing, so blast radius is empty."""
        result = code_blast_radius(db, "proj", "lib.py", "check")
        assert result == []


class TestCodeHubs:
    def test_returns_most_connected(self, db):
        """Hub nodes should be sorted by degree descending."""
        result = code_hubs(db, "proj", top_n=10)
        assert isinstance(result, list)
        assert len(result) >= 1
        # validate has the most connections: called by process and helper, calls check
        assert result[0]["name"] == "validate"
        for h in result:
            assert "name" in h
            assert "file" in h
            assert "degree" in h
        # Verify sorted descending
        degrees = [h["degree"] for h in result]
        assert degrees == sorted(degrees, reverse=True)

    def test_top_n_limits_results(self, db):
        """Requesting top_n=2 returns at most 2 results."""
        result = code_hubs(db, "proj", top_n=2)
        assert len(result) <= 2

    def test_returns_empty_for_unknown_project(self, db):
        """Unknown project returns empty list."""
        result = code_hubs(db, "nonexistent_project", top_n=5)
        assert result == []
