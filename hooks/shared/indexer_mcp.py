"""Backward-compat shim — canonical source is toroidal-indexer/indexer/mcp_queries.py."""

from indexer.mcp_queries import (
    code_blast_radius,
    code_callers,
    code_hubs,
    code_path,
    code_readers,
)

__all__ = [
    "code_blast_radius",
    "code_callers",
    "code_hubs",
    "code_path",
    "code_readers",
]
