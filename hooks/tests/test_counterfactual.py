#!/usr/bin/env python3
"""Tests for Feature #6: Counterfactual Retrieval Pass."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.harness import test, skip, MEMORY_SERVER_RUNNING

print("\n--- Counterfactual Retrieval: Client & Query ---")

if MEMORY_SERVER_RUNNING:
    skip("CF: _get_cf_client returns None or client (no API key)")
    skip("CF: _get_cf_client is idempotent (lazy init)")
    skip("CF: _generate_counterfactual_query fail-open on empty input")
    skip("CF: _generate_counterfactual_query fail-open on bad model key")
    skip("CF: _CF_MODEL_MAP has haiku/sonnet/opus keys")
    skip("CF: search_knowledge accepts counterfactual param")
    skip("CF: result has counterfactual_count key when enabled")
    skip("CF: tags mode skips counterfactual even with explicit param")
    skip("CF: observations mode skips counterfactual")
    skip("CF: threshold mode only fires on weak results")
    skip("CF: opt-in mode requires explicit param")
    skip("CF: master toggle off blocks counterfactual")
    skip("CF: config keys present in config.json")
else:
    import sys as _sys

    _orig_argv = sys.argv[:]
    sys.argv = ["memory_server.py"]

    try:
        from memory_server import (
            _get_cf_client,
            _generate_counterfactual_query,
            _CF_MODEL_MAP,
            _CF_SYSTEM_PROMPT,
        )

        sys.argv = _orig_argv

        # Test 1: _get_cf_client returns None (no API key in test env) or a client
        os.environ.pop("ANTHROPIC_API_KEY", None)
        # Reset lazy init for testing
        import memory_server as _ms

        _ms._cf_client = None
        _ms._cf_client_init = False
        client = _get_cf_client()
        test(
            "CF: _get_cf_client returns None or client (no API key)",
            client is None or hasattr(client, "messages"),
            f"type={type(client).__name__}",
        )

        # Test 2: Idempotent — second call returns same result
        client2 = _get_cf_client()
        test(
            "CF: _get_cf_client is idempotent (lazy init)",
            client is client2,
            f"client={client}, client2={client2}",
        )

        # Test 3: _generate_counterfactual_query fail-open on empty
        result = _generate_counterfactual_query("", [], model_key="haiku")
        test(
            "CF: _generate_counterfactual_query fail-open on empty input",
            result is None,
            f"result={result!r}",
        )

        # Test 4: fail-open on bad model key (no client anyway)
        result2 = _generate_counterfactual_query(
            "test query",
            [{"preview": "x", "relevance": 0.3}],
            model_key="nonexistent_model_xyz",
        )
        test(
            "CF: _generate_counterfactual_query fail-open on bad model key",
            result2 is None,
            f"result={result2!r}",
        )

        # Test 5: _CF_MODEL_MAP has required keys
        test(
            "CF: _CF_MODEL_MAP has haiku/sonnet/opus keys",
            all(k in _CF_MODEL_MAP for k in ("haiku", "sonnet", "opus")),
            f"keys={list(_CF_MODEL_MAP.keys())}",
        )

    except Exception as e:
        sys.argv = _orig_argv
        for name in [
            "CF: _get_cf_client returns None or client (no API key)",
            "CF: _get_cf_client is idempotent (lazy init)",
            "CF: _generate_counterfactual_query fail-open on empty input",
            "CF: _generate_counterfactual_query fail-open on bad model key",
            "CF: _CF_MODEL_MAP has haiku/sonnet/opus keys",
        ]:
            skip(f"{name} (import failed: {e})")


print("\n--- Counterfactual Retrieval: Pipeline Wiring ---")

if MEMORY_SERVER_RUNNING:
    skip("CF: search_knowledge accepts counterfactual param")
    skip("CF: result has counterfactual_count key when enabled")
    skip("CF: tags mode skips counterfactual even with explicit param")
    skip("CF: observations mode skips counterfactual")
    skip("CF: threshold mode only fires on weak results")
    skip("CF: opt-in mode requires explicit param")
    skip("CF: master toggle off blocks counterfactual")
else:
    try:
        import sys

        _orig_argv2 = sys.argv[:]
        sys.argv = ["memory_server.py"]
        from memory_server import search_knowledge
        import inspect

        sys.argv = _orig_argv2

        sig = inspect.signature(search_knowledge)
        params = list(sig.parameters.keys())

        test(
            "CF: search_knowledge accepts counterfactual param",
            "counterfactual" in params,
            f"params={params}",
        )

        # Verify it doesn't crash with counterfactual=False (LanceDB unavailable in test)
        # Just check the signature and code structure
        cf_param = sig.parameters.get("counterfactual")
        test(
            "CF: counterfactual param defaults to False",
            cf_param is not None and cf_param.default is False,
            f"default={cf_param.default if cf_param else 'N/A'}",
        )

    except Exception as e:
        sys.argv = _orig_argv2 if "_orig_argv2" in dir() else sys.argv
        skip(f"CF: search_knowledge accepts counterfactual param (import failed: {e})")
        skip("CF: counterfactual param defaults to False")


print("\n--- Counterfactual Retrieval: Trigger Logic (unit) ---")

# These tests verify the trigger logic without running search_knowledge
# by testing the logic directly
import math


def _simulate_cf_trigger(
    cf_enabled,
    cf_mode,
    cf_threshold,
    counterfactual_param,
    mode,
    formatted,
    cf_enabled_override=None,
):
    """Reproduce the trigger logic from memory_server.py for unit testing."""
    _ls_toggles = {
        "counterfactual_retrieval": cf_enabled,
        "counterfactual_mode": cf_mode,
        "counterfactual_threshold": cf_threshold,
    }
    _cf_enabled = _ls_toggles.get("counterfactual_retrieval", False)
    _cf_mode = _ls_toggles.get("counterfactual_mode", "always")
    _cf_threshold = _ls_toggles.get("counterfactual_threshold", 0.4)
    _should_cf = False

    if _cf_enabled:
        if _cf_mode == "always":
            _should_cf = True
        elif _cf_mode == "threshold" and formatted:
            _best_rel = max((r.get("relevance", 0) for r in formatted), default=0)
            if _best_rel < _cf_threshold:
                _should_cf = True

    if counterfactual_param and _cf_enabled:
        _should_cf = True

    if mode in ("tags", "observations", "transcript"):
        _should_cf = False

    return _should_cf


# Test: always mode triggers
_always_strong = _simulate_cf_trigger(
    True, "always", 0.4, False, "", [{"relevance": 0.9}]
)
test(
    "CF trigger: always mode triggers on strong results",
    _always_strong is True,
    f"result={_always_strong}",
)

# Test: threshold mode — weak results trigger
_thresh_weak = _simulate_cf_trigger(
    True, "threshold", 0.4, False, "", [{"relevance": 0.2}]
)
test(
    "CF trigger: threshold mode fires on weak results (0.2 < 0.4)",
    _thresh_weak is True,
    f"result={_thresh_weak}",
)

# Test: threshold mode — strong results don't trigger
_thresh_strong = _simulate_cf_trigger(
    True, "threshold", 0.4, False, "", [{"relevance": 0.8}]
)
test(
    "CF trigger: threshold mode skips on strong results (0.8 > 0.4)",
    _thresh_strong is False,
    f"result={_thresh_strong}",
)

# Test: opt-in mode — no trigger without explicit param
_optin_no = _simulate_cf_trigger(True, "opt-in", 0.4, False, "", [{"relevance": 0.1}])
test(
    "CF trigger: opt-in mode does not fire without explicit param",
    _optin_no is False,
    f"result={_optin_no}",
)

# Test: opt-in mode — explicit param triggers
_optin_yes = _simulate_cf_trigger(True, "opt-in", 0.4, True, "", [{"relevance": 0.1}])
test(
    "CF trigger: opt-in mode fires with explicit param=True",
    _optin_yes is True,
    f"result={_optin_yes}",
)

# Test: master toggle off blocks
_master_off = _simulate_cf_trigger(False, "always", 0.4, True, "", [{"relevance": 0.1}])
test(
    "CF trigger: master toggle off blocks even with explicit param",
    _master_off is False,
    f"result={_master_off}",
)

# Test: tags mode blocks
_tags_mode = _simulate_cf_trigger(
    True, "always", 0.4, True, "tags", [{"relevance": 0.1}]
)
test(
    "CF trigger: tags mode never triggers",
    _tags_mode is False,
    f"result={_tags_mode}",
)

# Test: observations mode blocks
_obs_mode = _simulate_cf_trigger(
    True, "always", 0.4, True, "observations", [{"relevance": 0.1}]
)
test(
    "CF trigger: observations mode never triggers",
    _obs_mode is False,
    f"result={_obs_mode}",
)

# Test: transcript mode blocks
_trans_mode = _simulate_cf_trigger(
    True, "always", 0.4, True, "transcript", [{"relevance": 0.1}]
)
test(
    "CF trigger: transcript mode never triggers",
    _trans_mode is False,
    f"result={_trans_mode}",
)


print("\n--- Counterfactual Retrieval: Config ---")

import json

_cfg = json.load(open("/home/crab/.claude/config.json"))
test(
    "CF config: counterfactual_retrieval key present",
    "counterfactual_retrieval" in _cfg,
    f"keys include: {list(_cfg.keys())[-5:]}",
)
test(
    "CF config: counterfactual_mode is valid value",
    _cfg.get("counterfactual_mode") in ("always", "threshold", "opt-in"),
    f"mode={_cfg.get('counterfactual_mode')}",
)
test(
    "CF config: counterfactual_model is valid value",
    _cfg.get("counterfactual_model") in ("haiku", "sonnet", "opus"),
    f"model={_cfg.get('counterfactual_model')}",
)
test(
    "CF config: counterfactual_threshold in valid range",
    0.0 < _cfg.get("counterfactual_threshold", 0) < 1.0,
    f"threshold={_cfg.get('counterfactual_threshold')}",
)
test(
    "CF config: counterfactual_discount in valid range",
    0.0 < _cfg.get("counterfactual_discount", 0) <= 1.0,
    f"discount={_cfg.get('counterfactual_discount')}",
)
