"""Tests for search_pipeline query_vec passthrough in secondary search paths.

Verifies that action_patterns and observations use cached query_vector
instead of re-embedding via query_texts when available.
"""

import os
import sys

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HOOKS_DIR not in sys.path:
    sys.path.insert(0, HOOKS_DIR)

SHARED_DIR = os.path.join(HOOKS_DIR, "shared")
if SHARED_DIR not in sys.path:
    sys.path.insert(0, SHARED_DIR)


class FakeCollection:
    """Tracks whether query was called with query_vector or query_texts."""

    def __init__(self, results=None):
        self.last_call = {}
        self._results = results or {
            "ids": [[]],
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        }

    def query(self, **kwargs):
        self.last_call = kwargs
        return self._results

    def count(self):
        return 5


def test_action_patterns_uses_query_vec():
    """fix_outcomes.query should use query_vector when _query_vec is available."""
    from shared.search_pipeline import SearchPipeline

    fake_fo = FakeCollection()

    sp = SearchPipeline.__new__(SearchPipeline)
    sp.config = {}
    sp.graph = None
    sp.adaptive = None

    dummy_vec = [0.1] * 768

    helpers = {
        "format_summaries": lambda x: [],
        "fix_outcomes": fake_fo,
        "server_project": "",
        "server_subproject": "",
    }

    sp._action_patterns(
        [], "ImportError: no module named foo", helpers, _query_vec=dummy_vec
    )

    assert fake_fo.last_call.get("query_vector") is not None, (
        "fix_outcomes.query should receive query_vector when _query_vec is available"
    )


def test_action_patterns_falls_back_to_query_texts():
    """fix_outcomes.query should use query_texts when _query_vec is None."""
    from shared.search_pipeline import SearchPipeline

    fake_fo = FakeCollection()

    sp = SearchPipeline.__new__(SearchPipeline)
    sp.config = {}
    sp.graph = None
    sp.adaptive = None

    helpers = {
        "format_summaries": lambda x: [],
        "fix_outcomes": fake_fo,
        "server_project": "",
        "server_subproject": "",
    }

    sp._action_patterns(
        [], "ImportError: no module named foo", helpers, _query_vec=None
    )

    assert fake_fo.last_call.get("query_texts") is not None, (
        "fix_outcomes.query should use query_texts when _query_vec is None"
    )


def test_observations_accepts_query_vec():
    """_search_observations_internal should accept query_vec parameter."""
    import inspect
    from memory_server import _search_observations_internal

    sig = inspect.signature(_search_observations_internal)
    assert "query_vec" in sig.parameters, (
        "_search_observations_internal should accept query_vec parameter"
    )


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
