"""Backward-compat shim — canonical source is toroidal-indexer/indexer/lsp.py."""

from indexer.lsp import (
    LSP_CONFIDENCE,
    build_line_to_name_map,
    enrich_node_types,
    resolve_target_node,
    store_call_hierarchy_edges,
    store_definition_edges,
    store_implementation_edges,
)

__all__ = [
    "LSP_CONFIDENCE",
    "build_line_to_name_map",
    "enrich_node_types",
    "resolve_target_node",
    "store_call_hierarchy_edges",
    "store_definition_edges",
    "store_implementation_edges",
]
