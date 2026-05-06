"""Tests for shared/extractors/python_extractor.py — Python AST extraction."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.extractors.python_extractor import Edge, Node, extract_python


class TestExtractsImports:
    """Test import extraction (import X, from X import Y)."""

    def test_extracts_imports_from_file(self, tmp_path):
        src = tmp_path / "app.py"
        src.write_text("import os\nimport json\nfrom pathlib import Path\n")
        nodes, edges = extract_python(str(src), str(tmp_path))

        # File node always present
        file_nodes = [n for n in nodes if n.type == "file"]
        assert len(file_nodes) == 1
        assert file_nodes[0].file == "app.py"

        # Import edges: os, json, pathlib
        import_edges = [e for e in edges if e.relation == "imports"]
        imported_names = {e.target for e in import_edges}
        assert "os" in imported_names
        assert "json" in imported_names
        assert "pathlib" in imported_names

    def test_extracts_from_import_names(self, tmp_path):
        src = tmp_path / "mod.py"
        src.write_text("from collections import OrderedDict, defaultdict\n")
        nodes, edges = extract_python(str(src), str(tmp_path))

        import_edges = [e for e in edges if e.relation == "imports"]
        # Should import from 'collections'
        targets = {e.target for e in import_edges}
        assert "collections" in targets


class TestExtractsFunctions:
    """Test function definition extraction."""

    def test_extracts_function_definitions(self, tmp_path):
        src = tmp_path / "funcs.py"
        src.write_text(
            "def hello(name):\n    return f'Hello {name}'\n\ndef goodbye():\n    pass\n"
        )
        nodes, edges = extract_python(str(src), str(tmp_path))

        func_nodes = [n for n in nodes if n.type == "function"]
        func_names = {n.name for n in func_nodes}
        assert "hello" in func_names
        assert "goodbye" in func_names
        assert len(func_nodes) == 2

        # Check line numbers
        hello_node = [n for n in func_nodes if n.name == "hello"][0]
        assert hello_node.line == 1
        goodbye_node = [n for n in func_nodes if n.name == "goodbye"][0]
        assert goodbye_node.line == 4


class TestExtractsCalls:
    """Test function call extraction with resolution."""

    def test_extracts_function_calls_with_resolution(self, tmp_path):
        # Create a helper module that can be resolved
        helper = tmp_path / "helper.py"
        helper.write_text("def do_stuff(): pass\n")

        src = tmp_path / "caller.py"
        src.write_text(
            "from helper import do_stuff\n"
            "\n"
            "def main():\n"
            "    do_stuff()\n"
            "    print('done')\n"
        )
        nodes, edges = extract_python(str(src), str(tmp_path))

        call_edges = [e for e in edges if e.relation == "calls"]
        call_targets = {e.target for e in call_edges}
        assert "helper.py:do_stuff" in call_targets
        assert "print" in call_targets

    def test_cross_file_call_resolves_to_target_module(self, tmp_path):
        helper = tmp_path / "shared" / "state.py"
        helper.parent.mkdir(parents=True, exist_ok=True)
        helper.write_text("def load_state(): pass\ndef save_state(): pass\n")

        src = tmp_path / "tracker.py"
        src.write_text(
            "from shared.state import load_state, save_state\n"
            "\n"
            "def run():\n"
            "    s = load_state()\n"
            "    save_state()\n"
        )
        nodes, edges = extract_python(str(src), str(tmp_path))

        call_edges = [e for e in edges if e.relation == "calls"]
        call_targets = {e.target for e in call_edges}
        assert "shared/state.py:load_state" in call_targets
        assert "shared/state.py:save_state" in call_targets

        # Edge source should be the enclosing function, not the file
        for e in call_edges:
            if e.target in ("shared/state.py:load_state", "shared/state.py:save_state"):
                assert e.source == "run", f"Expected source='run', got '{e.source}'"

    def test_cross_file_call_unresolved_stays_bare(self, tmp_path):
        src = tmp_path / "app.py"
        src.write_text("from os.path import join\njoin('a','b')\n")
        nodes, edges = extract_python(str(src), str(tmp_path))

        call_edges = [e for e in edges if e.relation == "calls"]
        call_targets = {e.target for e in call_edges}
        assert "join" in call_targets

    def test_extracts_method_calls(self, tmp_path):
        src = tmp_path / "methods.py"
        src.write_text("import os\nresult = os.path.join('a', 'b')\n")
        nodes, edges = extract_python(str(src), str(tmp_path))

        call_edges = [e for e in edges if e.relation == "calls"]
        call_targets = {e.target for e in call_edges}
        # Should capture os.path.join as a call target
        assert any("join" in t for t in call_targets)


class TestExtractsFieldAccess:
    """Test dict key access detection as field reads/writes."""

    def test_extracts_dict_key_access_as_field(self, tmp_path):
        src = tmp_path / "fields.py"
        src.write_text(
            "state = {}\n"
            "val = state['counter']\n"
            "x = state.get('name', '')\n"
            "state['active'] = True\n"
        )
        nodes, edges = extract_python(str(src), str(tmp_path))

        read_edges = [e for e in edges if e.relation == "reads"]
        write_edges = [e for e in edges if e.relation == "writes"]

        read_targets = {e.target for e in read_edges}
        write_targets = {e.target for e in write_edges}

        assert "state.counter" in read_targets or "counter" in read_targets
        assert "state.name" in read_targets or "name" in read_targets
        assert "state.active" in write_targets or "active" in write_targets


class TestExtractsFilePaths:
    """Test file path string detection."""

    def test_extracts_file_path_strings(self, tmp_path):
        src = tmp_path / "paths.py"
        src.write_text(
            "from pathlib import Path\n"
            "f = open('config/settings.json')\n"
            "p = Path('data/output.csv')\n"
        )
        nodes, edges = extract_python(str(src), str(tmp_path))

        # File path references show up as edges with relation "reads"
        # targeting paths that contain '/'
        path_edges = [e for e in edges if e.relation == "reads" and "/" in e.target]
        path_targets = {e.target for e in path_edges}
        assert "config/settings.json" in path_targets
        assert "data/output.csv" in path_targets


class TestExtractsClasses:
    """Test class definition and inheritance extraction."""

    def test_extracts_class_inheritance(self, tmp_path):
        src = tmp_path / "classes.py"
        src.write_text(
            "class Animal:\n"
            "    pass\n"
            "\n"
            "class Dog(Animal):\n"
            "    pass\n"
            "\n"
            "class Poodle(Dog, Animal):\n"
            "    pass\n"
        )
        nodes, edges = extract_python(str(src), str(tmp_path))

        class_nodes = [n for n in nodes if n.type == "class"]
        class_names = {n.name for n in class_nodes}
        assert "Animal" in class_names
        assert "Dog" in class_names
        assert "Poodle" in class_names

        impl_edges = [e for e in edges if e.relation == "implements"]
        # Dog implements Animal
        dog_impl = [e for e in impl_edges if e.source == "Dog"]
        assert any(e.target == "Animal" for e in dog_impl)

        # Poodle implements Dog and Animal
        poodle_impl = [e for e in impl_edges if e.source == "Poodle"]
        poodle_targets = {e.target for e in poodle_impl}
        assert "Dog" in poodle_targets
        assert "Animal" in poodle_targets


class TestErrorHandling:
    """Test graceful handling of bad input."""

    def test_handles_syntax_error_gracefully(self, tmp_path):
        src = tmp_path / "bad.py"
        src.write_text("def broken(\n    # missing closing paren and colon\n")
        nodes, edges = extract_python(str(src), str(tmp_path))

        # Should return file node only, no crash
        assert len(nodes) >= 1
        file_nodes = [n for n in nodes if n.type == "file"]
        assert len(file_nodes) == 1
        assert len(edges) == 0

    def test_handles_missing_file(self, tmp_path):
        nodes, edges = extract_python(str(tmp_path / "nonexistent.py"), str(tmp_path))
        assert nodes == []
        assert edges == []


class TestModuleResolution:
    """Test module path resolution for imports."""

    def test_resolves_relative_imports(self, tmp_path):
        # Create package structure
        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "utils.py").write_text("def helper(): pass\n")
        (pkg / "main.py").write_text("from .utils import helper\n")

        nodes, edges = extract_python(str(pkg / "main.py"), str(tmp_path))

        import_edges = [e for e in edges if e.relation == "imports"]
        # Relative import should resolve to the actual file
        targets = {e.target for e in import_edges}
        assert any("mypkg/utils.py" in t or "utils" in t for t in targets)

    def test_resolves_dotted_module_to_file_path(self, tmp_path):
        # Create nested package
        pkg = tmp_path / "mylib"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        sub = pkg / "sub"
        sub.mkdir()
        (sub / "__init__.py").write_text("")
        (sub / "core.py").write_text("X = 1\n")

        src = tmp_path / "app.py"
        src.write_text("from mylib.sub.core import X\n")

        nodes, edges = extract_python(str(src), str(tmp_path))

        import_edges = [e for e in edges if e.relation == "imports"]
        targets = {e.target for e in import_edges}
        # Should resolve mylib.sub.core to mylib/sub/core.py
        assert any("mylib/sub/core.py" in t for t in targets)

    def test_handles_namespace_packages(self, tmp_path):
        # Package without __init__.py (namespace package / implicit)
        pkg = tmp_path / "nspkg"
        pkg.mkdir()
        (pkg / "mod.py").write_text("Y = 2\n")

        src = tmp_path / "user.py"
        src.write_text("from nspkg.mod import Y\n")

        nodes, edges = extract_python(str(src), str(tmp_path))

        import_edges = [e for e in edges if e.relation == "imports"]
        targets = {e.target for e in import_edges}
        # Even without __init__.py, should resolve nspkg/mod.py
        assert any("nspkg/mod.py" in t for t in targets)

    def test_stdlib_import_not_resolved_to_file(self, tmp_path):
        src = tmp_path / "stdlib_user.py"
        src.write_text("import os\nimport json\n")
        nodes, edges = extract_python(str(src), str(tmp_path))

        import_edges = [e for e in edges if e.relation == "imports"]
        # stdlib imports should NOT have file paths as targets
        for e in import_edges:
            assert "/" not in e.target  # no file path resolution for stdlib


class TestEnclosingFunctionTracking:
    """Test that call/read/write edges use the enclosing function as source."""

    def test_call_source_is_enclosing_function(self, tmp_path):
        src = tmp_path / "app.py"
        src.write_text("def run():\n    print('hello')\n")
        nodes, edges = extract_python(str(src), str(tmp_path))
        call_edges = [e for e in edges if e.relation == "calls"]
        assert any(e.source == "run" and e.target == "print" for e in call_edges)

    def test_module_level_call_source_is_file(self, tmp_path):
        src = tmp_path / "top.py"
        src.write_text("print('module level')\n")
        nodes, edges = extract_python(str(src), str(tmp_path))
        call_edges = [e for e in edges if e.relation == "calls"]
        assert any(e.source == "top.py" and e.target == "print" for e in call_edges)

    def test_nested_method_call_source(self, tmp_path):
        src = tmp_path / "cls.py"
        src.write_text("class Foo:\n    def bar(self):\n        print('in bar')\n")
        nodes, edges = extract_python(str(src), str(tmp_path))
        call_edges = [e for e in edges if e.relation == "calls"]
        assert any(e.source == "bar" and e.target == "print" for e in call_edges)

    def test_async_function_scope(self, tmp_path):
        src = tmp_path / "async_app.py"
        src.write_text("async def fetch():\n    print('async')\n")
        nodes, edges = extract_python(str(src), str(tmp_path))
        call_edges = [e for e in edges if e.relation == "calls"]
        assert any(e.source == "fetch" and e.target == "print" for e in call_edges)
