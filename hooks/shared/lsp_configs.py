"""Backward-compat shim — canonical source is toroidal-indexer/indexer/lsp_configs.py."""

from indexer.lsp_configs import (
    CONFIGS,
    LSPServerConfig,
    get_config_for_file,
    is_server_available,
)

__all__ = ["CONFIGS", "LSPServerConfig", "get_config_for_file", "is_server_available"]
