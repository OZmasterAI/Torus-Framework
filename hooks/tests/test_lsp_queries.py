"""Tests for LSP query methods — integration tests against real pyright."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.lsp_client import LSPClient

ROOT_PATH = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
ROOT_URI = f"file://{ROOT_PATH}"
PYRIGHT_CMD = "pyright-langserver"
PYRIGHT_ARGS = ["--stdio"]

SCHEMA_FILE = os.path.join(ROOT_PATH, "toroidal-indexer", "indexer", "schema.py")


@pytest.fixture(scope="module")
def client():
    """Single pyright client reused across all query tests."""
    c = LSPClient(command=PYRIGHT_CMD, args=PYRIGHT_ARGS, root_uri=ROOT_URI)
    c.did_open(SCHEMA_FILE, "python")
    uri = f"file://{SCHEMA_FILE}"
    c.wait_for_diagnostics(uri, timeout=20.0)
    yield c
    c.did_close(SCHEMA_FILE)
    c.shutdown()


class TestDocumentSymbol:
    def test_returns_functions(self, client):
        symbols = client.document_symbol(SCHEMA_FILE)
        assert symbols is not None
        names = [s["name"] for s in symbols]
        assert "connect_code_graph" in names
        assert "init_code_tables" in names
        assert "upsert_node" in names
        assert "relate" in names

    def test_returns_symbol_kinds(self, client):
        symbols = client.document_symbol(SCHEMA_FILE)
        for s in symbols:
            assert "kind" in s
            assert "range" in s or "location" in s or "selectionRange" in s


class TestDefinition:
    def test_resolves_import(self, client):
        locations = client.definition(SCHEMA_FILE, line=6, character=25)
        assert locations is not None
        assert len(locations) > 0
        assert any("uri" in loc for loc in locations)

    def test_resolves_function_call(self, client):
        locations = client.definition(SCHEMA_FILE, line=27, character=10)
        assert locations is not None


def _sym_pos(sym):
    """Extract name position from either SymbolInformation or DocumentSymbol.

    SymbolInformation range starts at 'def '/'class ', so offset to the name.
    """
    if "selectionRange" in sym:
        return sym["selectionRange"]["start"]
    if "location" in sym:
        start = sym["location"]["range"]["start"]
        kind = sym.get("kind", 0)
        # Kind 12 = Function (def X), Kind 5 = Class (class X)
        offset = 4 if kind == 12 else 6 if kind == 5 else 0
        return {"line": start["line"], "character": start["character"] + offset}
    return sym.get("range", {}).get("start", {"line": 0, "character": 0})


class TestReferences:
    def test_finds_usages(self, client):
        symbols = client.document_symbol(SCHEMA_FILE)
        fn = next((s for s in symbols if s["name"] == "_node_key"), None)
        assert fn is not None
        pos = _sym_pos(fn)
        refs = client.references(
            SCHEMA_FILE, line=pos["line"], character=pos["character"]
        )
        assert refs is not None
        assert len(refs) >= 1


class TestHover:
    def test_returns_type_info(self, client):
        result = client.hover(SCHEMA_FILE, line=13, character=5)
        assert result is not None
        assert "contents" in result

    def test_hover_on_function(self, client):
        symbols = client.document_symbol(SCHEMA_FILE)
        fn = next((s for s in symbols if s["name"] == "relate"), None)
        assert fn is not None
        pos = _sym_pos(fn)
        result = client.hover(SCHEMA_FILE, line=pos["line"], character=pos["character"])
        assert result is not None


class TestCallHierarchy:
    def test_prepare_call_hierarchy(self, client):
        symbols = client.document_symbol(SCHEMA_FILE)
        fn = next((s for s in symbols if s["name"] == "relate"), None)
        assert fn is not None
        pos = _sym_pos(fn)
        items = client.prepare_call_hierarchy(
            SCHEMA_FILE, line=pos["line"], character=pos["character"]
        )
        assert items is not None
        assert len(items) >= 1
        assert items[0].get("name") == "relate"

    def test_incoming_calls(self, client):
        symbols = client.document_symbol(SCHEMA_FILE)
        fn = next((s for s in symbols if s["name"] == "_node_key"), None)
        assert fn is not None
        pos = _sym_pos(fn)
        items = client.prepare_call_hierarchy(
            SCHEMA_FILE, line=pos["line"], character=pos["character"]
        )
        if items:
            incoming = client.incoming_calls(items[0])
            assert incoming is not None
            assert len(incoming) >= 1

    def test_outgoing_calls(self, client):
        symbols = client.document_symbol(SCHEMA_FILE)
        fn = next((s for s in symbols if s["name"] == "upsert_node"), None)
        assert fn is not None
        pos = _sym_pos(fn)
        items = client.prepare_call_hierarchy(
            SCHEMA_FILE, line=pos["line"], character=pos["character"]
        )
        if items:
            outgoing = client.outgoing_calls(items[0])
            assert outgoing is not None


class TestImplementation:
    def test_implementation_returns_list(self, client):
        result = client.implementation(SCHEMA_FILE, line=13, character=5)
        assert result is None or isinstance(result, list)
