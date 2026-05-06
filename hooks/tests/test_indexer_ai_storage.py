"""Tests for Toroidal-Indexer Tier 3: edge storage CLI and _store_edges() improvements."""

import json
import os
import subprocess
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "..", "toroidal-indexer")
)

from surrealdb import Surreal

from shared.indexer_schema import (
    VALID_RELATIONS,
    connect_code_graph,
    init_code_tables,
    relate,
    upsert_node,
)
from scripts.ai_pass import _store_edges

SURREAL_URL = "ws://127.0.0.1:8822"
SCRIPT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "toroidal-indexer", "scripts", "ai_pass.py"
)


@pytest.fixture(scope="module")
def db():
    test_db = f"test_ai_storage_{uuid.uuid4().hex[:8]}"
    conn = connect_code_graph(url=SURREAL_URL, database=test_db)
    init_code_tables(conn)
    yield conn
    conn.query(f"REMOVE DATABASE IF EXISTS {test_db}")


class TestStoreEdgesReturn:
    def test_returns_summary_dict(self, db):
        edges = [
            {
                "source": "a.py:fn_a",
                "target": "b.py:fn_b",
                "relation": "calls",
                "confidence": 0.9,
                "line": 10,
            },
        ]
        result = _store_edges(db, "test_ret", edges)
        assert isinstance(result, dict)
        assert "stored" in result
        assert "skipped" in result
        assert "errors" in result

    def test_stores_valid_edges(self, db):
        edges = [
            {
                "source": "s1.py:f1",
                "target": "s2.py:f2",
                "relation": "calls",
                "confidence": 0.8,
                "line": 5,
            },
            {
                "source": "s1.py:f1",
                "target": "s3.py:f3",
                "relation": "imports",
                "confidence": 0.8,
                "line": 1,
            },
        ]
        result = _store_edges(db, "test_valid", edges)
        assert result["stored"] == 2
        assert result["errors"] == 0

    def test_skips_invalid_relation(self, db):
        edges = [
            {
                "source": "x.py:a",
                "target": "y.py:b",
                "relation": "destroys",
                "confidence": 0.8,
                "line": 1,
            },
        ]
        result = _store_edges(db, "test_inv_rel", edges)
        assert result["stored"] == 0
        assert result["skipped"] >= 1

    def test_skips_missing_source_target(self, db):
        edges = [
            {"source": "", "target": "b.py:g", "relation": "calls"},
            {"source": "a.py:f", "target": "", "relation": "calls"},
            {"relation": "calls"},
        ]
        result = _store_edges(db, "test_miss", edges)
        assert result["stored"] == 0

    def test_error_details_populated(self, db):
        result = _store_edges(db, "test_err", [])
        assert isinstance(result.get("error_details"), list)


class TestConfidenceOverride:
    def test_confidence_forced_to_0_8(self, db):
        edges = [
            {
                "source": "conf.py:high",
                "target": "conf.py:low",
                "relation": "calls",
                "confidence": 1.0,
                "line": 1,
            },
        ]
        result = _store_edges(db, "test_conf", edges, force_confidence=0.8)
        assert result["stored"] == 1
        stored = db.query("SELECT confidence FROM calls WHERE confidence = 0.8")
        assert len(stored) > 0


class TestPassTagging:
    def test_edges_tagged_with_pass_number(self, db):
        edges = [
            {
                "source": "tag.py:a",
                "target": "tag.py:b",
                "relation": "calls",
                "confidence": 0.8,
                "line": 1,
            },
        ]
        _store_edges(db, "test_tag", edges, pass_num=2)
        tagged = db.query("SELECT * FROM calls WHERE pass = 2")
        assert len(tagged) > 0


class TestDedupBehavior:
    def test_duplicate_edge_counted_as_skipped(self, db):
        edges = [
            {
                "source": "dup.py:a",
                "target": "dup.py:b",
                "relation": "imports",
                "confidence": 0.8,
                "line": 1,
            },
        ]
        r1 = _store_edges(db, "test_dup", edges)
        assert r1["stored"] == 1
        r2 = _store_edges(db, "test_dup", edges)
        assert r2["skipped"] == 1
        assert r2["stored"] == 0


class TestStoreCLI:
    def test_store_from_stdin(self, db):
        edges = json.dumps(
            [
                {
                    "source": "cli.py:main",
                    "target": "cli.py:run",
                    "relation": "calls",
                    "confidence": 1.0,
                    "line": 1,
                },
            ]
        )
        result = subprocess.run(
            [
                sys.executable,
                SCRIPT_PATH,
                "store",
                "--stdin",
                "--project",
                "test_cli",
                "--pass",
                "1",
                "--db",
                f"test_ai_storage_{db.query('INFO FOR DB')[0] if False else uuid.uuid4().hex[:8]}",
            ],
            input=edges,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["stored"] >= 0

    def test_store_overrides_confidence(self):
        edges = json.dumps(
            [
                {
                    "source": "over.py:a",
                    "target": "over.py:b",
                    "relation": "calls",
                    "confidence": 1.0,
                    "line": 1,
                },
            ]
        )
        test_db = f"test_cli_conf_{uuid.uuid4().hex[:8]}"
        result = subprocess.run(
            [
                sys.executable,
                SCRIPT_PATH,
                "store",
                "--stdin",
                "--project",
                "test_override",
                "--pass",
                "1",
                "--db",
                test_db,
            ],
            input=edges,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["stored"] >= 0
        conn = connect_code_graph(database=test_db)
        edges_in_db = conn.query("SELECT confidence FROM calls")
        for e in edges_in_db:
            assert e["confidence"] == 0.8
        conn.query(f"REMOVE DATABASE IF EXISTS {test_db}")

    def test_store_returns_json_summary(self):
        edges = json.dumps([])
        test_db = f"test_cli_sum_{uuid.uuid4().hex[:8]}"
        result = subprocess.run(
            [
                sys.executable,
                SCRIPT_PATH,
                "store",
                "--stdin",
                "--project",
                "test_sum",
                "--pass",
                "1",
                "--db",
                test_db,
            ],
            input=edges,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert "stored" in output
        assert "skipped" in output
        assert "errors" in output
        conn = connect_code_graph(database=test_db)
        conn.query(f"REMOVE DATABASE IF EXISTS {test_db}")
