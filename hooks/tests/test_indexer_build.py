"""Tests for Toroidal-Indexer build system (full + incremental)."""

import os
import subprocess
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from surrealdb import Surreal

from shared.indexer_build import full_build, get_changed_files, incremental_build
from shared.indexer_schema import connect_code_graph, init_code_tables

SURREAL_URL = "ws://127.0.0.1:8822"


@pytest.fixture(scope="module")
def db():
    test_db = f"test_build_{uuid.uuid4().hex[:8]}"
    conn = connect_code_graph(url=SURREAL_URL, database=test_db)
    init_code_tables(conn)
    yield conn
    conn.query(f"REMOVE DATABASE IF EXISTS {test_db}")


@pytest.fixture
def project(tmp_path):
    """Create a minimal Python project in tmp_path."""
    (tmp_path / "main.py").write_text(
        "from utils import helper\n\ndef main():\n    helper()\n"
    )
    (tmp_path / "utils.py").write_text("def helper():\n    return 42\n")
    (tmp_path / "README.md").write_text("# skip me")
    subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "."],
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-m", "init", "--no-gpg-sign"],
        capture_output=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "t@t",
        },
    )
    return tmp_path


class TestFullBuild:
    def test_indexes_all_python_files(self, db, project):
        stats = full_build(db, str(project), "test_proj")
        assert stats["files_indexed"] >= 2
        nodes = db.query(
            "SELECT * FROM code_node WHERE project=$p",
            {"p": "test_proj"},
        )
        names = {n["name"] for n in nodes}
        assert "main" in names
        assert "helper" in names

    def test_creates_edges(self, db, project):
        full_build(db, str(project), "test_proj2")
        nodes = db.query(
            "SELECT id, ->calls->code_node AS calls_out, ->imports->code_node AS imports_out "
            "FROM code_node WHERE project=$p",
            {"p": "test_proj2"},
        )
        total_edges = sum(
            len(n.get("calls_out", []) or []) + len(n.get("imports_out", []) or [])
            for n in nodes
        )
        assert total_edges > 0

    def test_skips_non_source_files(self, db, project):
        full_build(db, str(project), "test_proj3")
        nodes = db.query(
            "SELECT * FROM code_node WHERE project=$p AND file CONTAINS 'README'",
            {"p": "test_proj3"},
        )
        assert len(nodes) == 0


class TestRoutesByExtension:
    def test_routes_rust_files(self, db, tmp_path):
        (tmp_path / "lib.rs").write_text("pub fn greet() {}\n")
        stats = full_build(db, str(tmp_path), "rust_proj")
        assert stats["files_indexed"] >= 1
        nodes = db.query(
            "SELECT * FROM code_node WHERE project=$p AND name='greet'",
            {"p": "rust_proj"},
        )
        assert len(nodes) >= 1

    def test_routes_typescript_files(self, db, tmp_path):
        (tmp_path / "app.ts").write_text("export function render() {}\n")
        stats = full_build(db, str(tmp_path), "ts_proj")
        assert stats["files_indexed"] >= 1
        nodes = db.query(
            "SELECT * FROM code_node WHERE project=$p AND name='render'",
            {"p": "ts_proj"},
        )
        assert len(nodes) >= 1


class TestIncrementalBuild:
    def test_only_reindexes_changed_files(self, db, project):
        full_build(db, str(project), "incr_proj")
        initial = db.query(
            "SELECT * FROM code_node WHERE project=$p", {"p": "incr_proj"}
        )
        # Modify utils.py and do incremental build
        (project / "utils.py").write_text(
            "def helper():\n    return 99\n\ndef new_fn():\n    pass\n"
        )
        stats = incremental_build(db, str(project), "incr_proj", ["utils.py"])
        assert stats["files_indexed"] == 1
        nodes = db.query(
            "SELECT * FROM code_node WHERE project=$p AND name='new_fn'",
            {"p": "incr_proj"},
        )
        assert len(nodes) >= 1

    def test_delete_before_reindex_prevents_stale(self, db, tmp_path):
        (tmp_path / "stale.py").write_text("def old_func():\n    pass\n")
        full_build(db, str(tmp_path), "stale_proj")
        assert (
            len(
                db.query(
                    "SELECT * FROM code_node WHERE project=$p AND name='old_func'",
                    {"p": "stale_proj"},
                )
            )
            >= 1
        )
        (tmp_path / "stale.py").write_text("def new_func():\n    pass\n")
        incremental_build(db, str(tmp_path), "stale_proj", ["stale.py"])
        assert (
            len(
                db.query(
                    "SELECT * FROM code_node WHERE project=$p AND name='old_func'",
                    {"p": "stale_proj"},
                )
            )
            == 0
        )
        assert (
            len(
                db.query(
                    "SELECT * FROM code_node WHERE project=$p AND name='new_func'",
                    {"p": "stale_proj"},
                )
            )
            >= 1
        )


class TestSkipsGitignored:
    def test_skips_gitignored_files(self, db, tmp_path):
        (tmp_path / ".gitignore").write_text("build/\n*.pyc\n")
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        (build_dir / "generated.py").write_text("def gen():\n    pass\n")
        (tmp_path / "real.py").write_text("def real():\n    pass\n")
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        stats = full_build(db, str(tmp_path), "gi_proj")
        nodes = db.query(
            "SELECT * FROM code_node WHERE project=$p AND name='gen'",
            {"p": "gi_proj"},
        )
        assert len(nodes) == 0
        nodes_real = db.query(
            "SELECT * FROM code_node WHERE project=$p AND name='real'",
            {"p": "gi_proj"},
        )
        assert len(nodes_real) >= 1


class TestGetChangedFiles:
    def test_returns_changed_file_list(self, project):
        (project / "new_file.py").write_text("x = 1\n")
        subprocess.run(["git", "-C", str(project), "add", "."], capture_output=True)
        subprocess.run(
            ["git", "-C", str(project), "commit", "-m", "add new", "--no-gpg-sign"],
            capture_output=True,
            env={
                **os.environ,
                "GIT_AUTHOR_NAME": "test",
                "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "test",
                "GIT_COMMITTER_EMAIL": "t@t",
            },
        )
        changed = get_changed_files(str(project))
        assert "new_file.py" in changed
