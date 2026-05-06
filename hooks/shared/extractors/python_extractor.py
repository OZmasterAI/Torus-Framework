"""Backward-compat shim — canonical source is toroidal-indexer/indexer/extractors/python.py."""

from indexer.extractors import Edge, Node
from indexer.extractors.python import extract_python

__all__ = ["Edge", "Node", "extract_python"]
