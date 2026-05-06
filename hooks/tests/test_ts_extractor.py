"""Tests for shared/extractors/ts_extractor.py — TypeScript/JS regex-based extractor."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.extractors import Edge, Node
from shared.extractors.ts_extractor import extract_typescript


class TestImportStatements:
    """Test extraction of ES module import statements."""

    def test_extracts_named_imports(self, tmp_path):
        ts_file = tmp_path / "app.ts"
        ts_file.write_text(
            "import { Router, Request } from 'express';\n"
            "import { useState } from 'react';\n"
        )
        nodes, edges = extract_typescript(str(ts_file), str(tmp_path))
        # Should have a file node for app.ts
        file_nodes = [n for n in nodes if n.type == "file"]
        assert len(file_nodes) == 1
        assert file_nodes[0].name == "app.ts"
        # Should have import edges
        import_edges = [e for e in edges if e.relation == "imports"]
        assert len(import_edges) == 2
        assert any("express" in e.target for e in import_edges)
        assert any("react" in e.target for e in import_edges)

    def test_extracts_default_imports(self, tmp_path):
        ts_file = tmp_path / "main.ts"
        ts_file.write_text("import React from 'react';\nimport path from 'path';\n")
        nodes, edges = extract_typescript(str(ts_file), str(tmp_path))
        import_edges = [e for e in edges if e.relation == "imports"]
        assert len(import_edges) == 2
        assert any("react" in e.target for e in import_edges)
        assert any("path" in e.target for e in import_edges)

    def test_extracts_star_imports(self, tmp_path):
        ts_file = tmp_path / "utils.ts"
        ts_file.write_text("import * as fs from 'fs';\n")
        nodes, edges = extract_typescript(str(ts_file), str(tmp_path))
        import_edges = [e for e in edges if e.relation == "imports"]
        assert len(import_edges) == 1
        assert "fs" in import_edges[0].target


class TestRequireCalls:
    """Test extraction of CommonJS require() calls."""

    def test_extracts_require_calls(self, tmp_path):
        js_file = tmp_path / "server.js"
        js_file.write_text(
            "const express = require('express');\n"
            "const { join } = require('path');\n"
            "const config = require('./config');\n"
        )
        nodes, edges = extract_typescript(str(js_file), str(tmp_path))
        import_edges = [e for e in edges if e.relation == "imports"]
        assert len(import_edges) == 3
        sources = [e.target for e in import_edges]
        assert any("express" in s for s in sources)
        assert any("path" in s for s in sources)
        # Relative require should resolve to a path
        assert any("config" in s for s in sources)


class TestExportDeclarations:
    """Test extraction of export declarations."""

    def test_extracts_export_functions(self, tmp_path):
        ts_file = tmp_path / "utils.ts"
        ts_file.write_text(
            "export function handleRequest(req: Request) {\n"
            "  return req.body;\n"
            "}\n"
            "\n"
            "export function formatDate(d: Date): string {\n"
            "  return d.toISOString();\n"
            "}\n"
        )
        nodes, edges = extract_typescript(str(ts_file), str(tmp_path))
        fn_nodes = [n for n in nodes if n.type == "function"]
        assert len(fn_nodes) == 2
        names = {n.name for n in fn_nodes}
        assert "handleRequest" in names
        assert "formatDate" in names

    def test_extracts_export_classes(self, tmp_path):
        ts_file = tmp_path / "models.ts"
        ts_file.write_text(
            "export class UserService {\n"
            "  getUser() {}\n"
            "}\n"
            "\n"
            "export class AuthProvider {\n"
            "  authenticate() {}\n"
            "}\n"
        )
        nodes, edges = extract_typescript(str(ts_file), str(tmp_path))
        class_nodes = [n for n in nodes if n.type == "class"]
        assert len(class_nodes) == 2
        names = {n.name for n in class_nodes}
        assert "UserService" in names
        assert "AuthProvider" in names

    def test_extracts_export_default(self, tmp_path):
        ts_file = tmp_path / "component.tsx"
        ts_file.write_text(
            "function App() {\n  return <div />;\n}\n\nexport default App;\n"
        )
        nodes, edges = extract_typescript(str(ts_file), str(tmp_path))
        # export default should create a node
        fn_nodes = [n for n in nodes if n.type == "function"]
        assert len(fn_nodes) >= 1
        assert any(n.name == "App" for n in fn_nodes)

    def test_extracts_named_export_list(self, tmp_path):
        ts_file = tmp_path / "index.ts"
        ts_file.write_text("const A = 1;\nconst B = 2;\n\nexport { A, B };\n")
        nodes, edges = extract_typescript(str(ts_file), str(tmp_path))
        # Named exports from export { X, Y } should appear
        export_nodes = [n for n in nodes if n.name in ("A", "B")]
        assert len(export_nodes) >= 2


class TestRelativeImportResolution:
    """Test that relative imports resolve to actual files."""

    def test_resolves_relative_imports(self, tmp_path):
        # Create the target file
        (tmp_path / "utils.ts").write_text("export function helper() {}\n")
        # Create the importing file
        ts_file = tmp_path / "main.ts"
        ts_file.write_text("import { helper } from './utils';\n")

        nodes, edges = extract_typescript(str(ts_file), str(tmp_path))
        import_edges = [e for e in edges if e.relation == "imports"]
        assert len(import_edges) == 1
        # The target should resolve to the actual file path
        assert import_edges[0].target.endswith("utils.ts")

    def test_resolves_index_file(self, tmp_path):
        # Create a directory with index.ts
        subdir = tmp_path / "components"
        subdir.mkdir()
        (subdir / "index.ts").write_text("export const Button = 'btn';\n")

        ts_file = tmp_path / "app.ts"
        ts_file.write_text("import { Button } from './components';\n")

        nodes, edges = extract_typescript(str(ts_file), str(tmp_path))
        import_edges = [e for e in edges if e.relation == "imports"]
        assert len(import_edges) == 1
        assert "components" in import_edges[0].target

    def test_resolves_tsx_extension(self, tmp_path):
        (tmp_path / "Widget.tsx").write_text("export default function Widget() {}\n")
        ts_file = tmp_path / "page.tsx"
        ts_file.write_text("import Widget from './Widget';\n")

        nodes, edges = extract_typescript(str(ts_file), str(tmp_path))
        import_edges = [e for e in edges if e.relation == "imports"]
        assert len(import_edges) == 1
        assert import_edges[0].target.endswith("Widget.tsx")


class TestPackageImports:
    """Test handling of package (non-relative) imports."""

    def test_resolves_package_imports(self, tmp_path):
        ts_file = tmp_path / "api.ts"
        ts_file.write_text(
            "import express from 'express';\n"
            "import { z } from 'zod';\n"
            "import cors from 'cors';\n"
        )
        nodes, edges = extract_typescript(str(ts_file), str(tmp_path))
        import_edges = [e for e in edges if e.relation == "imports"]
        assert len(import_edges) == 3
        # Package imports should keep the package name as target
        targets = {e.target for e in import_edges}
        assert "express" in targets
        assert "zod" in targets
        assert "cors" in targets
        # Confidence should be 1.0 for direct imports
        assert all(e.confidence == 1.0 for e in import_edges)


class TestParseErrorHandling:
    """Test graceful handling of broken or binary files."""

    def test_handles_parse_error_gracefully(self, tmp_path):
        # Binary junk
        bad_file = tmp_path / "broken.ts"
        bad_file.write_bytes(b"\x00\x01\x02\xff\xfe" * 100)
        nodes, edges = extract_typescript(str(bad_file), str(tmp_path))
        # Should return empty rather than crash
        assert isinstance(nodes, list)
        assert isinstance(edges, list)

    def test_handles_empty_file(self, tmp_path):
        empty = tmp_path / "empty.ts"
        empty.write_text("")
        nodes, edges = extract_typescript(str(empty), str(tmp_path))
        # File node should still exist
        file_nodes = [n for n in nodes if n.type == "file"]
        assert len(file_nodes) == 1
        assert file_nodes[0].name == "empty.ts"

    def test_handles_nonexistent_file(self, tmp_path):
        nodes, edges = extract_typescript(
            str(tmp_path / "no_such_file.ts"), str(tmp_path)
        )
        assert nodes == []
        assert edges == []

    def test_handles_syntax_garbage(self, tmp_path):
        ts_file = tmp_path / "garbage.ts"
        ts_file.write_text("}{}{}{import {{{{ from '''';\nexport ;;; class {}}}}\n")
        nodes, edges = extract_typescript(str(ts_file), str(tmp_path))
        # Should not crash; may return partial results
        assert isinstance(nodes, list)
        assert isinstance(edges, list)


class TestEdgeAttributes:
    """Test that edges have correct metadata."""

    def test_edge_source_lines_are_correct(self, tmp_path):
        ts_file = tmp_path / "lines.ts"
        ts_file.write_text(
            "// comment\n"  # line 1
            "import { A } from './a';\n"  # line 2
            "\n"  # line 3
            "import { B } from 'b-pkg';\n"  # line 4
        )
        nodes, edges = extract_typescript(str(ts_file), str(tmp_path))
        import_edges = sorted(
            [e for e in edges if e.relation == "imports"], key=lambda e: e.source_line
        )
        assert len(import_edges) == 2
        assert import_edges[0].source_line == 2
        assert import_edges[1].source_line == 4

    def test_edge_source_is_file_name(self, tmp_path):
        ts_file = tmp_path / "entry.ts"
        ts_file.write_text("import { foo } from 'bar';\n")
        nodes, edges = extract_typescript(str(ts_file), str(tmp_path))
        assert edges[0].source == "entry.ts"


class TestRelativePaths:
    """Verify that all node file paths are relative to project root."""

    def test_node_file_is_relative(self, tmp_path):
        ts_file = tmp_path / "src" / "app.ts"
        ts_file.parent.mkdir(parents=True)
        ts_file.write_text("export function main() {}\n")
        nodes, edges = extract_typescript(str(ts_file), str(tmp_path))
        for node in nodes:
            assert not os.path.isabs(node.file), (
                f"Node file should be relative: {node.file}"
            )
        file_node = [n for n in nodes if n.type == "file"][0]
        assert file_node.file == "src/app.ts"
        fn_node = [n for n in nodes if n.type == "function"][0]
        assert fn_node.file == "src/app.ts"

    def test_relative_import_target_is_relative(self, tmp_path):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "utils.ts").write_text("export function helper() {}\n")
        (src_dir / "main.ts").write_text("import { helper } from './utils';\n")
        nodes, edges = extract_typescript(str(src_dir / "main.ts"), str(tmp_path))
        import_edges = [e for e in edges if e.relation == "imports"]
        assert len(import_edges) == 1
        assert not os.path.isabs(import_edges[0].target)
        assert import_edges[0].target == "src/utils.ts"
