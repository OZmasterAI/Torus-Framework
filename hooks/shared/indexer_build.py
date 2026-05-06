"""Backward-compat shim — canonical source is toroidal-indexer/indexer/build.py."""

from indexer.build import (
    full_build,
    get_changed_files,
    incremental_build,
)

__all__ = ["full_build", "get_changed_files", "incremental_build"]
