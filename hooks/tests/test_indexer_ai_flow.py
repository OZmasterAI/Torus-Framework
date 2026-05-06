"""Tests for Toroidal-Indexer Tier 3: pass-to-pass data flow."""

import json
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "..", "toroidal-indexer")
)

from shared.indexer_schema import (
    connect_code_graph,
    init_code_tables,
    upsert_node,
    relate,
)
from scripts.ai_pass import (
    _store_edges,
    format_edges_for_prompt,
    get_edges_for_files,
    get_graph_summary,
    _pass2_prompt,
    _pass3_prompt,
)

SURREAL_URL = "ws://127.0.0.1:8822"


@pytest.fixture(scope="module")
def db():
    test_db = f"test_ai_flow_{uuid.uuid4().hex[:8]}"
    conn = connect_code_graph(url=SURREAL_URL, database=test_db)
    init_code_tables(conn)
    yield conn
    conn.query(f"REMOVE DATABASE IF EXISTS {test_db}")


@pytest.fixture(scope="module")
def seeded_db(db):
    """Seed with some Pass 1-style edges."""
    edges = [
        {
            "source": "main.py:main",
            "target": "utils.py:helper",
            "relation": "calls",
            "confidence": 0.8,
            "line": 5,
        },
        {
            "source": "main.py:main",
            "target": "config.py:load",
            "relation": "calls",
            "confidence": 0.8,
            "line": 10,
        },
        {
            "source": "main.py:main",
            "target": "utils.py:utils",
            "relation": "imports",
            "confidence": 0.8,
            "line": 1,
        },
        {
            "source": "config.py:load",
            "target": "settings.json:settings.json",
            "relation": "reads",
            "confidence": 0.8,
            "line": 15,
        },
        {
            "source": "test_main.py:TestMain",
            "target": "main.py:main",
            "relation": "calls",
            "confidence": 0.8,
            "line": 8,
        },
    ]
    _store_edges(db, "test_flow", edges, force_confidence=0.8, pass_num=1)
    return db


class TestGetEdgesForFiles:
    def test_returns_edges_for_specified_files(self, seeded_db):
        edges = get_edges_for_files(seeded_db, "test_flow", ["main.py"])
        assert len(edges) >= 3  # main.py is source in 3 edges, target in 1

    def test_returns_edges_where_file_is_target(self, seeded_db):
        edges = get_edges_for_files(seeded_db, "test_flow", ["utils.py"])
        assert len(edges) >= 1  # utils.py is target in calls and imports

    def test_returns_empty_for_unknown_file(self, seeded_db):
        edges = get_edges_for_files(seeded_db, "test_flow", ["nonexistent.py"])
        assert edges == []

    def test_multiple_files(self, seeded_db):
        edges = get_edges_for_files(seeded_db, "test_flow", ["main.py", "config.py"])
        assert len(edges) >= 4

    def test_edge_has_required_fields(self, seeded_db):
        edges = get_edges_for_files(seeded_db, "test_flow", ["main.py"])
        assert len(edges) > 0
        for edge in edges:
            assert "source" in edge
            assert "target" in edge
            assert "relation" in edge


class TestGetGraphSummary:
    def test_returns_node_count(self, seeded_db):
        summary = get_graph_summary(seeded_db, "test_flow")
        assert summary["node_count"] > 0

    def test_returns_edge_counts_by_relation(self, seeded_db):
        summary = get_graph_summary(seeded_db, "test_flow")
        assert "edge_counts" in summary
        assert isinstance(summary["edge_counts"], dict)
        assert summary["edge_counts"].get("calls", 0) > 0

    def test_returns_top_hubs(self, seeded_db):
        summary = get_graph_summary(seeded_db, "test_flow")
        assert "top_hubs" in summary
        assert isinstance(summary["top_hubs"], list)
        if summary["top_hubs"]:
            hub = summary["top_hubs"][0]
            assert "name" in hub
            assert "degree" in hub

    def test_returns_isolated_nodes(self, seeded_db):
        summary = get_graph_summary(seeded_db, "test_flow")
        assert "isolated_nodes" in summary
        assert isinstance(summary["isolated_nodes"], list)

    def test_summary_is_compact(self, seeded_db):
        summary = get_graph_summary(seeded_db, "test_flow")
        serialized = json.dumps(summary)
        assert len(serialized) < 10000  # should be well under 10KB


class TestFormatEdgesForPrompt:
    def test_empty_edges(self):
        assert format_edges_for_prompt([]) == "(no edges)"

    def test_formats_edges(self):
        edges = [
            {"source": "a.py:f", "target": "b.py:g", "relation": "calls"},
        ]
        result = format_edges_for_prompt(edges)
        assert "a.py:f" in result
        assert "b.py:g" in result
        assert "calls" in result

    def test_truncates_at_max_chars(self):
        edges = [
            {
                "source": f"mod{i}.py:fn{i}",
                "target": f"mod{i + 1}.py:fn{i + 1}",
                "relation": "calls",
            }
            for i in range(200)
        ]
        result = format_edges_for_prompt(edges, max_chars=500)
        assert "[... and" in result
        assert len(result) <= 600  # some slack for the truncation message


class TestPassToPassDataFlow:
    def test_pass1_edges_appear_in_pass2_prompt(self, seeded_db):
        edges = get_edges_for_files(seeded_db, "test_flow", ["main.py"])
        prompt = _pass2_prompt(["main.py", "utils.py"], edges, "/project")
        assert "main.py" in prompt
        assert "utils.py" in prompt

    def test_graph_summary_feeds_pass3(self, seeded_db):
        summary = get_graph_summary(seeded_db, "test_flow")
        prompt = _pass3_prompt(summary, "/project")
        assert str(summary["node_count"]) in prompt
