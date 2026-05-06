"""Tests for shared/indexer_lsp.py — LSP-to-graph bridge."""

import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.indexer_lsp import (
    build_line_to_name_map,
    resolve_target_node,
    store_call_hierarchy_edges,
    store_definition_edges,
    store_implementation_edges,
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
    test_db = f"test_lsp_bridge_{uuid.uuid4().hex[:8]}"
    conn = connect_code_graph(url=SURREAL_URL, database=test_db)
    init_code_tables(conn)
    yield conn
    conn.query(f"REMOVE DATABASE IF EXISTS {test_db}")


class TestBuildLineToNameMap:
    def test_maps_lines_to_names(self):
        symbols = [
            {
                "name": "foo",
                "kind": 12,
                "location": {
                    "uri": "file:///test.py",
                    "range": {
                        "start": {"line": 5, "character": 0},
                        "end": {"line": 10, "character": 0},
                    },
                },
            },
            {
                "name": "Bar",
                "kind": 5,
                "location": {
                    "uri": "file:///test.py",
                    "range": {
                        "start": {"line": 12, "character": 0},
                        "end": {"line": 20, "character": 0},
                    },
                },
            },
        ]
        mapping = build_line_to_name_map(symbols)
        assert mapping[5] == "foo"
        assert mapping[12] == "Bar"

    def test_empty_symbols_returns_empty_map(self):
        assert build_line_to_name_map([]) == {}

    def test_document_symbol_format(self):
        symbols = [
            {
                "name": "helper",
                "kind": 12,
                "range": {
                    "start": {"line": 3, "character": 0},
                    "end": {"line": 8, "character": 0},
                },
                "selectionRange": {
                    "start": {"line": 3, "character": 4},
                    "end": {"line": 3, "character": 10},
                },
            },
        ]
        mapping = build_line_to_name_map(symbols)
        assert mapping[3] == "helper"


class TestResolveTargetNode:
    def test_resolves_known_symbol(self, db):
        symbols = [
            {
                "name": "load_state",
                "kind": 12,
                "location": {
                    "uri": "file:///project/hooks/shared/state.py",
                    "range": {
                        "start": {"line": 10, "character": 0},
                        "end": {"line": 20, "character": 0},
                    },
                },
            },
        ]
        node_id = resolve_target_node(
            db,
            project="test_proj",
            target_uri="file:///project/hooks/shared/state.py",
            target_line=10,
            target_symbols=symbols,
            project_root="/project",
        )
        assert node_id is not None
        result = db.query("SELECT * FROM $id", {"id": node_id})
        assert result[0]["name"] == "load_state"

    def test_returns_none_for_unknown_line(self, db):
        symbols = [
            {
                "name": "known",
                "kind": 12,
                "location": {
                    "uri": "file:///project/x.py",
                    "range": {
                        "start": {"line": 5, "character": 0},
                        "end": {"line": 10, "character": 0},
                    },
                },
            },
        ]
        node_id = resolve_target_node(
            db,
            project="test_proj",
            target_uri="file:///project/x.py",
            target_line=99,
            target_symbols=symbols,
            project_root="/project",
        )
        assert node_id is None


class TestStoreDefinitionEdges:
    def test_creates_imports_edge(self, db):
        src_node = upsert_node(db, "test_proj", "main.py", "main.py", "file", 0)
        tgt_node = upsert_node(
            db, "test_proj", "hooks/shared/state.py", "load_state", "function", 10
        )
        target_symbols = [
            {
                "name": "load_state",
                "kind": 12,
                "location": {
                    "uri": "file:///project/hooks/shared/state.py",
                    "range": {
                        "start": {"line": 10, "character": 0},
                        "end": {"line": 20, "character": 0},
                    },
                },
            },
        ]
        definition_results = [
            {
                "source_name": "main.py",
                "source_line": 1,
                "target_uri": "file:///project/hooks/shared/state.py",
                "target_line": 10,
            }
        ]
        count = store_definition_edges(
            db,
            project="test_proj",
            file_path="main.py",
            definition_results=definition_results,
            target_symbols_cache={
                "file:///project/hooks/shared/state.py": target_symbols
            },
            project_root="/project",
        )
        assert count >= 1
        edges = db.query(
            "SELECT * FROM imports WHERE in=$src AND out=$tgt",
            {"src": src_node, "tgt": tgt_node},
        )
        assert len(edges) == 1
        assert edges[0]["confidence"] == 0.9

    def test_confidence_is_0_9(self, db):
        upsert_node(db, "test_proj", "a.py", "a.py", "file", 0)
        upsert_node(db, "test_proj", "b.py", "helper", "function", 5)
        target_symbols = [
            {
                "name": "helper",
                "kind": 12,
                "location": {
                    "uri": "file:///project/b.py",
                    "range": {
                        "start": {"line": 5, "character": 0},
                        "end": {"line": 10, "character": 0},
                    },
                },
            },
        ]
        definition_results = [
            {
                "source_name": "a.py",
                "source_line": 2,
                "target_uri": "file:///project/b.py",
                "target_line": 5,
            }
        ]
        store_definition_edges(
            db,
            project="test_proj",
            file_path="a.py",
            definition_results=definition_results,
            target_symbols_cache={"file:///project/b.py": target_symbols},
            project_root="/project",
        )
        edges = db.query("SELECT * FROM imports WHERE confidence=0.9")
        assert len(edges) >= 1


class TestStoreImplementationEdges:
    def test_creates_implements_edge(self, db):
        impl_node = upsert_node(
            db, "test_proj", "impl.py", "ConcreteHandler", "class", 5
        )
        trait_node = upsert_node(db, "test_proj", "base.py", "BaseHandler", "class", 1)
        target_symbols = [
            {
                "name": "BaseHandler",
                "kind": 5,
                "location": {
                    "uri": "file:///project/base.py",
                    "range": {
                        "start": {"line": 1, "character": 0},
                        "end": {"line": 10, "character": 0},
                    },
                },
            },
        ]
        impl_results = [
            {
                "source_name": "ConcreteHandler",
                "source_file": "impl.py",
                "target_uri": "file:///project/base.py",
                "target_line": 1,
            }
        ]
        count = store_implementation_edges(
            db,
            project="test_proj",
            impl_results=impl_results,
            target_symbols_cache={"file:///project/base.py": target_symbols},
            project_root="/project",
        )
        assert count >= 1
        edges = db.query(
            "SELECT * FROM implements WHERE in=$src AND out=$tgt",
            {"src": impl_node, "tgt": trait_node},
        )
        assert len(edges) == 1
        assert edges[0]["confidence"] == 0.9


class TestStoreCallHierarchyEdges:
    def test_creates_calls_edge(self, db):
        caller = upsert_node(db, "test_proj", "main.py", "main", "function", 1)
        callee = upsert_node(db, "test_proj", "utils.py", "do_work", "function", 10)
        call_results = [
            {
                "caller_file": "main.py",
                "caller_name": "main",
                "callee_file": "utils.py",
                "callee_name": "do_work",
                "source_line": 5,
            }
        ]
        count = store_call_hierarchy_edges(
            db, project="test_proj", call_results=call_results
        )
        assert count >= 1
        edges = db.query(
            "SELECT * FROM calls WHERE in=$src AND out=$tgt",
            {"src": caller, "tgt": callee},
        )
        assert len(edges) == 1
        assert edges[0]["confidence"] == 0.9


class TestDedupWithTier1:
    def test_tier1_edge_not_downgraded(self, db):
        src = upsert_node(db, "test_proj", "dedup_src.py", "caller", "function", 1)
        tgt = upsert_node(db, "test_proj", "dedup_tgt.py", "callee", "function", 5)
        relate(db, src, "calls", tgt, confidence=1.0, source_line=3)
        call_results = [
            {
                "caller_file": "dedup_src.py",
                "caller_name": "caller",
                "callee_file": "dedup_tgt.py",
                "callee_name": "callee",
                "source_line": 3,
            }
        ]
        store_call_hierarchy_edges(db, project="test_proj", call_results=call_results)
        edges = db.query(
            "SELECT * FROM calls WHERE in=$src AND out=$tgt",
            {"src": src, "tgt": tgt},
        )
        assert len(edges) == 1
        assert edges[0]["confidence"] == 1.0
