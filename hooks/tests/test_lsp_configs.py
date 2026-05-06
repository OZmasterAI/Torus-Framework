"""Tests for shared/lsp_configs.py — per-language LSP server configurations."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.lsp_configs import (
    CONFIGS,
    LSPServerConfig,
    get_config_for_file,
    is_server_available,
)


class TestLSPServerConfig:
    def test_python_config_exists(self):
        assert "python" in CONFIGS
        cfg = CONFIGS["python"]
        assert cfg.command == "pyright-langserver"
        assert cfg.args == ["--stdio"]
        assert cfg.language_id == "python"
        assert ".py" in cfg.extensions

    def test_typescript_config_exists(self):
        assert "typescript" in CONFIGS
        cfg = CONFIGS["typescript"]
        assert cfg.command == "typescript-language-server"
        assert cfg.args == ["--stdio"]
        assert cfg.language_id == "typescript"
        assert ".ts" in cfg.extensions
        assert ".tsx" in cfg.extensions

    def test_rust_config_exists(self):
        assert "rust" in CONFIGS
        cfg = CONFIGS["rust"]
        assert cfg.command == "rustup"
        assert "rust-analyzer" in cfg.args
        assert cfg.language_id == "rust"
        assert ".rs" in cfg.extensions


class TestExtensionRouting:
    def test_py_routes_to_python(self):
        cfg = get_config_for_file("hooks/shared/state.py")
        assert cfg is not None
        assert cfg.language_id == "python"

    def test_ts_routes_to_typescript(self):
        cfg = get_config_for_file("src/app.ts")
        assert cfg is not None
        assert cfg.language_id == "typescript"

    def test_tsx_routes_to_typescript(self):
        cfg = get_config_for_file("components/Button.tsx")
        assert cfg is not None
        assert cfg.language_id == "typescript"

    def test_rs_routes_to_rust(self):
        cfg = get_config_for_file("src/main.rs")
        assert cfg is not None
        assert cfg.language_id == "rust"

    def test_unknown_extension_returns_none(self):
        assert get_config_for_file("readme.md") is None
        assert get_config_for_file("data.json") is None
        assert get_config_for_file("Makefile") is None


class TestServerAvailability:
    def test_pyright_is_available(self):
        cfg = CONFIGS["python"]
        assert is_server_available(cfg) is True

    def test_typescript_server_is_available(self):
        cfg = CONFIGS["typescript"]
        assert is_server_available(cfg) is True

    def test_rust_analyzer_is_available(self):
        cfg = CONFIGS["rust"]
        assert is_server_available(cfg) is True

    def test_missing_server_returns_false(self):
        fake = LSPServerConfig(
            command="nonexistent-lsp-binary-xyz",
            args=[],
            language_id="fake",
            extensions=[".fake"],
            init_options={},
        )
        assert is_server_available(fake) is False
