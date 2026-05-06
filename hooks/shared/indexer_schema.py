"""Backward-compat shim — canonical source is toroidal-indexer/indexer/schema.py."""

from indexer.schema import (
    NAMESPACE,
    SURREAL_URL,
    VALID_RELATIONS,
    _node_key,
    connect_code_graph,
    dedup_nodes,
    delete_file_nodes,
    get_callers,
    get_readers,
    init_code_tables,
    relate,
    upsert_node,
)

__all__ = [
    "NAMESPACE",
    "SURREAL_URL",
    "VALID_RELATIONS",
    "_node_key",
    "connect_code_graph",
    "dedup_nodes",
    "delete_file_nodes",
    "get_callers",
    "get_readers",
    "init_code_tables",
    "relate",
    "upsert_node",
]
