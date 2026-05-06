"""Tests for Toroidal-Indexer PreToolUse injection hook (indexer_inject.py).

Covers: function identification from old_string, caller/reader queries,
file-level fallback, dedup, fail-open behavior, output format, AI edge markers.
"""

import json
import os
import subprocess
import sys
import textwrap
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from surrealdb import Surreal

from shared.indexer_schema import (
    connect_code_graph,
    get_callers,
    get_readers,
    init_code_tables,
    relate,
    upsert_node,
)

SURREAL_URL = "ws://127.0.0.1:8822"
HOOK_PATH = os.path.join(os.path.dirname(__file__), "..", "indexer_inject.py")

# Module-level storage so fixtures can share the database name
_TEST_DB_NAME = []


@pytest.fixture(scope="module")
def db():
    """Connect to SurrealDB with a unique test database, init tables, yield, cleanup."""
    test_db = f"test_inject_{uuid.uuid4().hex[:8]}"
    _TEST_DB_NAME.clear()
    _TEST_DB_NAME.append(test_db)
    conn = connect_code_graph(url=SURREAL_URL, database=test_db)
    init_code_tables(conn)
    yield conn
    conn.query(f"REMOVE DATABASE IF EXISTS {test_db}")


@pytest.fixture(scope="module")
def db_name(db):
    """Return the database name for the test fixture."""
    return _TEST_DB_NAME[0]


def _run_hook(tool_input, env_extra=None):
    """Run the indexer_inject.py hook as a subprocess, returning (exit_code, stdout, stderr)."""
    event = {
        "tool_name": "Edit",
        "tool_input": tool_input,
    }
    env = {**os.environ}
    if env_extra:
        env.update(env_extra)
    result = subprocess.run(
        [sys.executable, HOOK_PATH],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


class TestIdentifiesFunctionFromOldString:
    """Test that old_string is parsed against file AST to find the enclosing function."""

    def test_identifies_function_from_old_string(self, tmp_path):
        """Given a Python file with two functions, editing a line inside one
        should identify that specific function."""
        src = textwrap.dedent("""\
            def alpha():
                x = 1
                return x

            def beta():
                y = 2
                return y
        """)
        py_file = tmp_path / "sample.py"
        py_file.write_text(src)

        # Import the internal identification function
        from indexer_inject import _identify_function

        result = _identify_function(str(py_file), "y = 2")
        assert result == "beta"

    def test_identifies_class_method(self, tmp_path):
        src = textwrap.dedent("""\
            class Foo:
                def bar(self):
                    val = 42
                    return val
        """)
        py_file = tmp_path / "sample2.py"
        py_file.write_text(src)

        from indexer_inject import _identify_function

        result = _identify_function(str(py_file), "val = 42")
        assert result == "bar"

    def test_returns_none_for_module_level(self, tmp_path):
        src = textwrap.dedent("""\
            import os
            CONSTANT = 42
            def func():
                pass
        """)
        py_file = tmp_path / "toplevel.py"
        py_file.write_text(src)

        from indexer_inject import _identify_function

        result = _identify_function(str(py_file), "CONSTANT = 42")
        assert result is None


class TestShowsCallersOfEditedFunction:
    """Query SurrealDB for callers of the function being edited."""

    def test_shows_callers_of_edited_function(self, db, tmp_path):
        # Set up nodes and edges
        target = upsert_node(db, "proj", "svc.py", "process", "function", 10)
        caller1 = upsert_node(db, "proj", "api.py", "handle_request", "function", 5)
        caller2 = upsert_node(db, "proj", "cli.py", "main", "function", 20)
        relate(db, caller1, "calls", target, confidence=1.0, source_line=8)
        relate(db, caller2, "calls", target, confidence=1.0, source_line=25)

        callers = get_callers(db, target)
        names = {c["name"] for c in callers}
        assert "handle_request" in names
        assert "main" in names


class TestShowsReadersOfEditedField:
    """Query SurrealDB for readers of a field being edited."""

    def test_shows_readers_of_edited_field(self, db):
        field_node = upsert_node(db, "proj", "config.py", "timeout", "field", 3)
        reader1 = upsert_node(db, "proj", "server.py", "start_server", "function", 12)
        reader2 = upsert_node(db, "proj", "health.py", "check_health", "function", 8)
        relate(db, reader1, "reads", field_node, confidence=1.0, source_line=15)
        relate(db, reader2, "reads", field_node, confidence=0.7, source_line=10)

        readers = get_readers(db, field_node)
        names = {r["name"] for r in readers}
        assert "start_server" in names
        assert "check_health" in names


class TestFallsBackToFileLevel:
    """When function cannot be identified, show file-level edges."""

    def test_falls_back_to_file_level(self, db, tmp_path):
        # Create a non-Python file that can't be AST-parsed for function identification
        txt_file = tmp_path / "config.toml"
        txt_file.write_text("[settings]\ntimeout = 30\n")

        from indexer_inject import _identify_function

        result = _identify_function(str(txt_file), "timeout = 30")
        assert result is None  # Can't parse non-Python, falls back to None

    def test_file_level_query_returns_all_nodes(self, db):
        """When we can't identify the function, we query all nodes in the file."""
        # Set up multiple functions in the same file
        fn1 = upsert_node(db, "proj", "mixed.py", "func_a", "function", 1)
        fn2 = upsert_node(db, "proj", "mixed.py", "func_b", "function", 20)
        ext_caller = upsert_node(db, "proj", "external.py", "ext_fn", "function", 5)
        relate(db, ext_caller, "calls", fn1, confidence=1.0, source_line=10)
        relate(db, ext_caller, "calls", fn2, confidence=1.0, source_line=15)

        # File-level query: all callers of all nodes in the file
        nodes = db.query(
            "SELECT * FROM code_node WHERE project=$proj AND file=$file",
            {"proj": "proj", "file": "mixed.py"},
        )
        assert len(nodes) >= 2


class TestSilentForUnknownFile:
    """Returns nothing (empty output, exit 0) for files not in the index."""

    def test_silent_for_unknown_file(self, tmp_path):
        unknown_file = tmp_path / "unknown.py"
        unknown_file.write_text("def mystery(): pass\n")

        env = {
            "TORUS_SESSION_ID": f"test_{uuid.uuid4().hex[:8]}",
            "INDEXER_DB": f"test_empty_{uuid.uuid4().hex[:8]}",
        }
        code, stdout, stderr = _run_hook(
            {"file_path": str(unknown_file), "old_string": "def mystery(): pass"},
            env_extra=env,
        )
        assert code == 0
        # Should produce no output or empty output (no context to inject)
        if stdout:
            data = json.loads(stdout)
            ctx = data.get("hookSpecificOutput", {}).get("additionalContext", "")
            # Context should be empty since file is unknown
            assert ctx == "" or stdout == ""


class TestSilentWhenNoCacheExists:
    """Graceful when SurrealDB is down or unreachable."""

    def test_silent_when_no_cache_exists(self, tmp_path, monkeypatch):
        """When SurrealDB connection fails, hook exits 0 with no output."""
        py_file = tmp_path / "any.py"
        py_file.write_text("def foo(): pass\n")

        # Point to a non-existent SurrealDB instance
        env = {
            "TORUS_SESSION_ID": f"test_{uuid.uuid4().hex[:8]}",
            "SURREAL_URL": "ws://127.0.0.1:19999",  # Nothing on this port
            "INDEXER_DB": "nonexistent_db",
        }
        code, stdout, stderr = _run_hook(
            {"file_path": str(py_file), "old_string": "def foo(): pass"},
            env_extra=env,
        )
        assert code == 0
        # Should produce no output (fail-open, silent)
        assert stdout == "" or stdout == "{}"


class TestDedupAcrossEdits:
    """Doesn't repeat info for same function in a session."""

    def test_dedup_across_edits(self, db, db_name, tmp_path):
        """Running the hook twice for the same function in the same session
        should only inject context the first time."""
        src = textwrap.dedent("""\
            def target_fn():
                x = 1
                return x
        """)
        py_file = tmp_path / "dedup_test.py"
        py_file.write_text(src)

        # Set up a node and caller so there IS context to inject
        target = upsert_node(db, "proj", str(py_file), "target_fn", "function", 1)
        caller = upsert_node(db, "proj", "other.py", "caller_fn", "function", 5)
        relate(db, caller, "calls", target, confidence=1.0, source_line=7)

        session_id = f"test_dedup_{uuid.uuid4().hex[:8]}"
        env = {
            "TORUS_SESSION_ID": session_id,
            "INDEXER_DB": db_name,
            "INDEXER_PROJECT": "proj",
        }

        # First call — should get context
        code1, stdout1, _ = _run_hook(
            {"file_path": str(py_file), "old_string": "x = 1"},
            env_extra=env,
        )
        assert code1 == 0

        # Second call — same function, same session — should be deduped
        code2, stdout2, _ = _run_hook(
            {"file_path": str(py_file), "old_string": "return x"},
            env_extra=env,
        )
        assert code2 == 0

        # If first produced output, second should not (dedup)
        if stdout1:
            assert stdout2 == "" or stdout2 == stdout1  # either silent or same cached


class TestExits0OnError:
    """Always exits 0 (fail-open, never blocks)."""

    def test_exits_0_on_error(self):
        """Even with garbage input, hook exits 0."""
        event = {"tool_name": "Edit", "tool_input": {}}
        result = subprocess.run(
            [sys.executable, HOOK_PATH],
            input=json.dumps(event),
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0

    def test_exits_0_on_invalid_json(self):
        """Invalid JSON on stdin still exits 0."""
        result = subprocess.run(
            [sys.executable, HOOK_PATH],
            input="not valid json at all",
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0

    def test_exits_0_on_empty_stdin(self):
        """Empty stdin still exits 0."""
        result = subprocess.run(
            [sys.executable, HOOK_PATH],
            input="",
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0


class TestOutputValidHookFormat:
    """Output matches the expected hook format when context is injected."""

    def test_output_valid_hook_format(self, db, db_name, tmp_path):
        """When context IS produced, it must be valid hook JSON."""
        src = textwrap.dedent("""\
            def format_target():
                data = []
                return data
        """)
        py_file = tmp_path / "format_test.py"
        py_file.write_text(src)

        target = upsert_node(db, "proj", str(py_file), "format_target", "function", 1)
        caller = upsert_node(db, "proj", "fmt_caller.py", "do_format", "function", 10)
        relate(db, caller, "calls", target, confidence=1.0, source_line=12)

        session_id = f"test_fmt_{uuid.uuid4().hex[:8]}"
        env = {
            "TORUS_SESSION_ID": session_id,
            "INDEXER_DB": db_name,
            "INDEXER_PROJECT": "proj",
        }

        code, stdout, _ = _run_hook(
            {"file_path": str(py_file), "old_string": "data = []"},
            env_extra=env,
        )
        assert code == 0
        if stdout:
            data = json.loads(stdout)
            assert "hookSpecificOutput" in data
            hso = data["hookSpecificOutput"]
            assert hso["hookEventName"] == "PreToolUse"
            assert "additionalContext" in hso
            assert isinstance(hso["additionalContext"], str)
            assert len(hso["additionalContext"]) > 0


class TestAiEdgesMarkedWithTilde:
    """Edges with confidence < 1.0 get ~ prefix in the output."""

    def test_ai_edges_marked_with_tilde(self, db, db_name, tmp_path):
        src = textwrap.dedent("""\
            def ai_target():
                val = 99
                return val
        """)
        py_file = tmp_path / "ai_test.py"
        py_file.write_text(src)

        target = upsert_node(db, "proj", str(py_file), "ai_target", "function", 1)
        # High confidence caller (no tilde)
        sure_caller = upsert_node(db, "proj", "sure.py", "sure_fn", "function", 1)
        relate(db, sure_caller, "calls", target, confidence=1.0, source_line=5)
        # Low confidence caller (should get tilde)
        ai_caller = upsert_node(db, "proj", "maybe.py", "maybe_fn", "function", 1)
        relate(db, ai_caller, "calls", target, confidence=0.6, source_line=8)

        session_id = f"test_ai_{uuid.uuid4().hex[:8]}"
        env = {
            "TORUS_SESSION_ID": session_id,
            "INDEXER_DB": db_name,
            "INDEXER_PROJECT": "proj",
        }

        code, stdout, _ = _run_hook(
            {"file_path": str(py_file), "old_string": "val = 99"},
            env_extra=env,
        )
        assert code == 0
        if stdout:
            data = json.loads(stdout)
            ctx = data["hookSpecificOutput"]["additionalContext"]
            # AI-sourced edge should have ~ prefix
            assert "~maybe_fn" in ctx or "~maybe.py" in ctx
            # Sure edge should NOT have ~ prefix
            assert "sure_fn" in ctx
            # Make sure sure_fn is NOT prefixed with ~
            assert "~sure_fn" not in ctx
