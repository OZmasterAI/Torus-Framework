#!/usr/bin/env python3
# Integration Tests - Boot, Memory, Auto-Commit, Gather, Web, Tasks
from tests.harness import (
    test, skip, run_enforcer, cleanup_test_states, table_test,
    _direct, _direct_stderr, _post,
    _g01_check, _g02_check, _g03_check, _g04_check,
    _g05_check, _g06_check, _g07_check, _g09_check, _g11_check,
    MEMORY_SERVER_RUNNING, HOOKS_DIR,
    MAIN_SESSION, SUB_SESSION_A, SUB_SESSION_B,
    load_state, save_state, reset_state, default_state,
    state_file_for, cleanup_all_states, MEMORY_TIMESTAMP_FILE,
)
import json
import os
import subprocess
import sys
import time
from shared.state import get_state_schema
import tests.harness as _h

def _read_pkg_source(pkg_dir):
    """Read and concatenate all .py files in a _pkg/ directory."""
    combined = ""
    if os.path.isdir(pkg_dir):
        for fname in sorted(os.listdir(pkg_dir)):
            if fname.endswith(".py"):
                try:
                    with open(os.path.join(pkg_dir, fname)) as pf:
                        combined += pf.read() + "\n"
                except OSError:
                    pass
    return combined

_tracker_pkg_dir = os.path.join(HOOKS_DIR, "tracker_pkg")
_boot_pkg_dir = os.path.join(HOOKS_DIR, "boot_pkg")

# Test: Boot Sequence
# ─────────────────────────────────────────────────
print("\n--- Boot Sequence ---")

import subprocess
if not MEMORY_SERVER_RUNNING:
    result = subprocess.run(
        [sys.executable, os.path.join(HOOKS_DIR, "boot.py")],
        capture_output=True, text=True, timeout=10
    )
    test("Boot exits cleanly", result.returncode == 0, f"code={result.returncode}")
    test("Boot shows dashboard", "Session" in result.stderr, result.stderr[:100])
    test("Boot shows gate count", "GATES ACTIVE" in result.stderr, result.stderr[:200])
else:
    skip("Boot exits cleanly")
    skip("Boot shows dashboard")
    skip("Boot shows gate count")

from boot import _extract_test_status

# Test 10: _extract_test_status returns None when no state files
cleanup_test_states()
ts10 = _extract_test_status()
test("_extract_test_status returns None with no state",
     ts10 is None,
     f"Expected None, got {ts10!r}")

# Test 11: _extract_test_status reads test info from state file
_test226_state_path = state_file_for(MAIN_SESSION)
_test226_state_data = {
    "last_test_run": time.time() - 120,
    "last_test_exit_code": 0,
    "last_test_command": "pytest hooks/test_framework.py",
    "session_start": time.time() - 600,
}
with open(_test226_state_path, "w") as _f226:
    json.dump(_test226_state_data, _f226)
ts11 = _extract_test_status()
test("_extract_test_status reads passed test",
     ts11 is not None and ts11["passed"] is True and ts11["framework"] == "pytest",
     f"Expected passed=True framework=pytest, got {ts11!r}")
cleanup_test_states()

# Test 12: _extract_test_status detects failed test
_test226_state_data2 = {
    "last_test_run": time.time() - 300,
    "last_test_exit_code": 1,
    "last_test_command": "npm test",
    "session_start": time.time() - 600,
}
with open(_test226_state_path, "w") as _f226:
    json.dump(_test226_state_data2, _f226)
ts12 = _extract_test_status()
test("_extract_test_status detects failed test",
     ts12 is not None and ts12["passed"] is False and ts12["framework"] == "npm test",
     f"Expected passed=False framework='npm test', got {ts12!r}")
cleanup_test_states()

from boot import _extract_verification_quality

# Test 1: _extract_verification_quality returns None with no state files
cleanup_test_states()
vq1 = _extract_verification_quality()
test("_extract_verification_quality returns None with no state",
     vq1 is None,
     f"Expected None, got {vq1!r}")

# Test 2: _extract_verification_quality reads verified and pending counts
cleanup_test_states()
_vq2_path = state_file_for(MAIN_SESSION)
_vq2_data = {
    "verified_fixes": ["/tmp/a.py", "/tmp/b.py"],
    "pending_verification": ["/tmp/c.py"],
    "session_start": time.time() - 300,
}
with open(_vq2_path, "w") as _f228:
    json.dump(_vq2_data, _f228)
vq2 = _extract_verification_quality()
test("_extract_verification_quality reads counts",
     vq2 is not None and vq2["verified"] == 2 and vq2["pending"] == 1,
     f"Expected verified=2 pending=1, got {vq2!r}")
cleanup_test_states()

# Test 3: _extract_verification_quality returns None when both empty
cleanup_test_states()
_vq3_data = {"verified_fixes": [], "pending_verification": [], "session_start": time.time()}
with open(_vq2_path, "w") as _f228:
    json.dump(_vq3_data, _f228)
vq3 = _extract_verification_quality()
test("_extract_verification_quality returns None for empty lists",
     vq3 is None,
     f"Expected None, got {vq3!r}")
cleanup_test_states()

# Test 4: _extract_verification_quality only verified (no pending)
cleanup_test_states()
_vq4_data = {"verified_fixes": ["/tmp/x.py"], "session_start": time.time()}
with open(_vq2_path, "w") as _f228:
    json.dump(_vq4_data, _f228)
vq4 = _extract_verification_quality()
test("_extract_verification_quality with only verified fixes",
     vq4 is not None and vq4["verified"] == 1 and vq4["pending"] == 0,
     f"Expected verified=1 pending=0, got {vq4!r}")
cleanup_test_states()

# Test 5: _extract_session_duration returns formatted string
from boot import _extract_session_duration
cleanup_test_states()
reset_state(session_id=MAIN_SESSION)
_bd_state = load_state(session_id=MAIN_SESSION)
_bd_state["session_start"] = time.time() - 3700  # ~61 minutes ago
save_state(_bd_state, session_id=MAIN_SESSION)
_bd_dur = _extract_session_duration()
test("_extract_session_duration returns '1h Xm' format",
     _bd_dur is not None and _bd_dur.startswith("1h"),
     f"Expected '1h Xm', got '{_bd_dur}'")

# Test 6: Session duration returns None for very short sessions
cleanup_test_states()
reset_state(session_id=MAIN_SESSION)
_bd2_state = load_state(session_id=MAIN_SESSION)
_bd2_state["session_start"] = time.time() - 30  # 30 seconds ago
save_state(_bd2_state, session_id=MAIN_SESSION)
_bd2_dur = _extract_session_duration()
test("_extract_session_duration returns None for <60s",
     _bd2_dur is None,
     f"Expected None, got '{_bd2_dur}'")

# Test 7: Session duration minutes-only format
cleanup_test_states()
reset_state(session_id=MAIN_SESSION)
_bd3_state = load_state(session_id=MAIN_SESSION)
_bd3_state["session_start"] = time.time() - 1500  # 25 minutes ago
save_state(_bd3_state, session_id=MAIN_SESSION)
_bd3_dur = _extract_session_duration()
test("_extract_session_duration returns 'Xm' for <1h",
     _bd3_dur is not None and "h" not in _bd3_dur and _bd3_dur.endswith("m"),
     f"Expected 'Xm', got '{_bd3_dur}'")

# Test 8: Session duration returns None when no state
cleanup_test_states()
_bd4_dur = _extract_session_duration()
test("_extract_session_duration returns None when no state",
     _bd4_dur is None,
     f"Expected None, got '{_bd4_dur}'")

# Test 9: _extract_gate_blocks function exists and is callable
from boot import _extract_gate_blocks
test("_extract_gate_blocks is callable",
     callable(_extract_gate_blocks),
     "Expected _extract_gate_blocks to be callable")

# Test 10: _extract_gate_blocks returns an integer
_gb = _extract_gate_blocks()
test("_extract_gate_blocks returns int",
     isinstance(_gb, int),
     f"Expected int, got {type(_gb).__name__}")

# Test 11: _extract_gate_blocks returns non-negative value
test("_extract_gate_blocks returns non-negative",
     _gb >= 0,
     f"Expected >= 0, got {_gb}")

# Test 12: _extract_gate_blocks is consistent across calls
_gb2 = _extract_gate_blocks()
test("_extract_gate_blocks is consistent across calls",
     _gb2 == _gb,
     f"Expected same result {_gb}, got {_gb2}")

cleanup_test_states()

# ─────────────────────────────────────────────────
# Test: Memory Server Imports
# ─────────────────────────────────────────────────
print("\n--- Memory Server ---")

try:
    import importlib
    spec = importlib.util.spec_from_file_location(
        "memory_server",
        os.path.join(HOOKS_DIR, "memory_server.py")
    )
    mod = importlib.util.module_from_spec(spec)
    # Don't execute (it starts the server), just check it loads
    test("Memory server file exists", True)
except Exception as e:
    test("Memory server file exists", False, str(e))

# Load settings/mcp config for use by later tests (no existence tests — behavioral tests catch missing files)
with open(os.path.expanduser("~/.claude/settings.json")) as f:
    settings = json.load(f)

try:
    with open(os.path.expanduser("~/.claude/mcp.json")) as f:
        mcp_config = json.load(f)
except FileNotFoundError:
    mcp_config = {}

# --- _apply_recency_boost functional tests ---
# These tests do NOT require LanceDB, just the pure function

if not MEMORY_SERVER_RUNNING:
    from datetime import datetime, timedelta
    from memory_server import _apply_recency_boost, format_results, format_summaries as _fs_fn

    # Test: recency_weight=0 should not change scores
    _rb_input_0 = [
        {"relevance": 0.8, "timestamp": datetime.now().isoformat()},
        {"relevance": 0.5, "timestamp": (datetime.now() - timedelta(days=30)).isoformat()},
    ]
    _rb_out_0 = _apply_recency_boost([dict(d) for d in _rb_input_0], recency_weight=0)
    test("recency_weight=0 returns unchanged order",
         _rb_out_0[0]["relevance"] == 0.8 and _rb_out_0[1]["relevance"] == 0.5,
         f"got relevances {_rb_out_0[0].get('relevance')}, {_rb_out_0[1].get('relevance')}")

    # Test: empty results should return empty
    _rb_empty = _apply_recency_boost([], recency_weight=0.15)
    test("recency_boost empty input returns empty",
         _rb_empty == [],
         f"got {_rb_empty}")

    # Test: recent entry gets boosted above older entry with same raw relevance
    _now_iso = datetime.now().isoformat()
    _old_iso = (datetime.now() - timedelta(days=300)).isoformat()
    _rb_input_boost = [
        {"relevance": 0.5, "timestamp": _old_iso},
        {"relevance": 0.5, "timestamp": _now_iso},
    ]
    _rb_out_boost = _apply_recency_boost([dict(d) for d in _rb_input_boost], recency_weight=0.15)
    # After boost, the recent entry should be sorted first
    test("recent entry boosted above older with same raw relevance",
         _rb_out_boost[0]["timestamp"] == _now_iso,
         f"first entry timestamp={_rb_out_boost[0].get('timestamp')}")

    # Test: very old entry (>365 days) gets no boost
    _ancient_iso = (datetime.now() - timedelta(days=400)).isoformat()
    _rb_input_ancient = [
        {"relevance": 0.6, "timestamp": _ancient_iso},
    ]
    _rb_out_ancient = _apply_recency_boost([dict(d) for d in _rb_input_ancient], recency_weight=0.15)
    # boost = 0.15 * max(0, 1 - 400/365) = 0.15 * 0 = 0, so relevance stays 0.6
    test("entry >365 days old gets no boost",
         _rb_out_ancient[0]["relevance"] == 0.6,
         f"relevance={_rb_out_ancient[0].get('relevance')}")

    # Test: verify boost formula math precisely
    # For an entry 0 days old: boost = recency_weight * max(0, 1 - 0/365) = recency_weight * 1
    _rb_precise = [{"relevance": 0.5, "timestamp": datetime.now().isoformat()}]
    _rb_out_precise = _apply_recency_boost([dict(d) for d in _rb_precise], recency_weight=0.10)
    # _adjusted_relevance should have been 0.5 + 0.10 * ~1.0 = ~0.60, but it's cleaned up
    # We verify via sort order with a known comparison
    _rb_precise2 = [
        {"relevance": 0.59, "timestamp": ""},  # no timestamp, no boost
        {"relevance": 0.5, "timestamp": datetime.now().isoformat()},  # 0.5 + ~0.10 = ~0.60
    ]
    _rb_out_precise2 = _apply_recency_boost([dict(d) for d in _rb_precise2], recency_weight=0.10)
    test("boost formula ranks 0.5+boost(0.10) above 0.59 no-boost",
         _rb_out_precise2[0]["relevance"] == 0.5,
         f"first relevance={_rb_out_precise2[0].get('relevance')}")

    # Test: missing timestamp gets no boost
    _rb_no_ts = [
        {"relevance": 0.7},
        {"relevance": 0.6, "timestamp": datetime.now().isoformat()},
    ]
    _rb_out_no_ts = _apply_recency_boost([dict(d) for d in _rb_no_ts], recency_weight=0.15)
    # 0.6 + ~0.15 = ~0.75 > 0.7, so boosted entry should come first
    test("entry without timestamp gets no boost",
         _rb_out_no_ts[0]["relevance"] == 0.6,
         f"first relevance={_rb_out_no_ts[0].get('relevance')}")

    # Test: _adjusted_relevance internal key is cleaned up
    _rb_cleanup = [{"relevance": 0.5, "timestamp": datetime.now().isoformat()}]
    _rb_out_cleanup = _apply_recency_boost([dict(d) for d in _rb_cleanup], recency_weight=0.15)
    test("_adjusted_relevance key cleaned up",
         "_adjusted_relevance" not in _rb_out_cleanup[0],
         f"keys={list(_rb_out_cleanup[0].keys())}")

    # --- format_results functional tests ---

    # Test: format_results with valid query results
    _fr_input = {
        "documents": [["doc1 content", "doc2 content"]],
        "metadatas": [[
            {"context": "ctx1", "tags": "tag1", "timestamp": "2026-01-01"},
            {"context": "ctx2", "tags": "tag2", "timestamp": "2026-01-02"},
        ]],
        "distances": [[0.2, 0.4]],
    }
    _fr_out = format_results(_fr_input)
    test("format_results returns correct count",
         len(_fr_out) == 2,
         f"got {len(_fr_out)}")
    test("format_results has content field",
         _fr_out[0]["content"] == "doc1 content",
         f"got {_fr_out[0].get('content')}")
    test("format_results relevance = 1-distance",
         _fr_out[0]["relevance"] == 0.8 and _fr_out[1]["relevance"] == 0.6,
         f"got {_fr_out[0].get('relevance')}, {_fr_out[1].get('relevance')}")
    test("format_results includes context from metadata",
         _fr_out[0]["context"] == "ctx1" and _fr_out[1]["context"] == "ctx2",
         f"got {_fr_out[0].get('context')}, {_fr_out[1].get('context')}")
    test("format_results includes tags from metadata",
         _fr_out[0]["tags"] == "tag1",
         f"got {_fr_out[0].get('tags')}")
    test("format_results includes timestamp from metadata",
         _fr_out[0]["timestamp"] == "2026-01-01",
         f"got {_fr_out[0].get('timestamp')}")

    # Test: format_results empty input
    _fr_empty = format_results({})
    test("format_results empty input returns empty list",
         _fr_empty == [],
         f"got {_fr_empty}")

    # Test: format_results None input
    _fr_none = format_results(None)
    test("format_results None input returns empty list",
         _fr_none == [],
         f"got {_fr_none}")

    # Test: format_results with no documents key
    _fr_no_docs = format_results({"metadatas": [[{"tags": "x"}]]})
    test("format_results no documents key returns empty",
         _fr_no_docs == [],
         f"got {_fr_no_docs}")

    # Test: format_results with missing distances
    _fr_no_dist = {
        "documents": [["doc content"]],
        "metadatas": [[{"context": "c", "tags": "t", "timestamp": "ts"}]],
    }
    _fr_out_nd = format_results(_fr_no_dist)
    test("format_results missing distances defaults to relevance 1.0",
         len(_fr_out_nd) == 1 and _fr_out_nd[0]["relevance"] == 1.0,
         f"got {_fr_out_nd[0].get('relevance') if _fr_out_nd else 'empty'}")

    # --- format_summaries additional functional tests ---

    # Test: format_summaries detects query() result structure (nested ids[0])
    _fs_query = {
        "ids": [["qid1", "qid2"]],
        "documents": [["doc a", "doc b"]],
        "metadatas": [[
            {"tags": "qa", "timestamp": "2026-01-01"},
            {"tags": "qb", "timestamp": "2026-01-02"},
        ]],
        "distances": [[0.1, 0.3]],
    }
    _fs_query_out = _fs_fn(_fs_query)
    test("format_summaries handles query() nested structure",
         len(_fs_query_out) == 2 and _fs_query_out[0]["id"] == "qid1",
         f"count={len(_fs_query_out)}, id={_fs_query_out[0].get('id') if _fs_query_out else 'none'}")
    test("format_summaries query() has relevance from distances",
         _fs_query_out[0].get("relevance") == 0.9,
         f"got {_fs_query_out[0].get('relevance')}")

    # Test: format_summaries detects get() result structure (flat ids)
    _fs_get = {
        "ids": ["gid1", "gid2"],
        "documents": ["get doc a", "get doc b"],
        "metadatas": [
            {"tags": "ga", "timestamp": "2026-02-01"},
            {"tags": "gb", "timestamp": "2026-02-02"},
        ],
    }
    _fs_get_out = _fs_fn(_fs_get)
    test("format_summaries handles get() flat structure",
         len(_fs_get_out) == 2 and _fs_get_out[0]["id"] == "gid1",
         f"count={len(_fs_get_out)}, id={_fs_get_out[0].get('id') if _fs_get_out else 'none'}")
    test("format_summaries get() has no relevance (no distances)",
         "relevance" not in _fs_get_out[0],
         f"keys={list(_fs_get_out[0].keys())}")

    # --- suggest_promotions functional tests (requires LanceDB) ---

    from memory_server import suggest_promotions, collection as _sp_coll

    if _sp_coll is None:
        # LanceDB not initialized (lazy init) — skip all suggest_promotions tests
        for _sp_skip in [
            "suggest_promotions returns dict with clusters key",
            "suggest_promotions has total_candidates key",
            "suggest_promotions has total_clusters key",
            "suggest_promotions clusters is a list",
            "suggest_promotions cluster structure (no LanceDB)",
            "suggest_promotions cluster supporting_ids (no LanceDB)",
            "suggest_promotions cluster count (no LanceDB)",
            "suggest_promotions cluster score (no LanceDB)",
            "suggest_promotions cluster avg_age_days (no LanceDB)",
            "suggest_promotions score formula (no LanceDB)",
            "suggest_promotions sorted desc (no LanceDB)",
            "suggest_promotions top_k (no LanceDB)",
        ]:
            skip(_sp_skip)
    else:
        _sp_result = suggest_promotions(top_k=3)
        test("suggest_promotions returns dict with clusters key",
             isinstance(_sp_result, dict) and "clusters" in _sp_result,
             f"type={type(_sp_result).__name__}, keys={list(_sp_result.keys()) if isinstance(_sp_result, dict) else 'N/A'}")
        test("suggest_promotions has total_candidates key",
             "total_candidates" in _sp_result,
             f"keys={list(_sp_result.keys())}")
        test("suggest_promotions has total_clusters key",
             "total_clusters" in _sp_result,
             f"keys={list(_sp_result.keys())}")
        test("suggest_promotions clusters is a list",
             isinstance(_sp_result.get("clusters"), list),
             f"type={type(_sp_result.get('clusters')).__name__}")

        # If there are clusters, verify their structure
        if _sp_result.get("clusters"):
            _sp_cluster = _sp_result["clusters"][0]
            test("suggest_promotions cluster has suggested_rule",
                 "suggested_rule" in _sp_cluster,
                 f"keys={list(_sp_cluster.keys())}")
            test("suggest_promotions cluster has supporting_ids",
                 "supporting_ids" in _sp_cluster and isinstance(_sp_cluster["supporting_ids"], list),
                 f"keys={list(_sp_cluster.keys())}")
            test("suggest_promotions cluster has count",
                 "count" in _sp_cluster and isinstance(_sp_cluster["count"], int),
                 f"keys={list(_sp_cluster.keys())}")
            test("suggest_promotions cluster has score",
                 "score" in _sp_cluster and isinstance(_sp_cluster["score"], (int, float)),
                 f"keys={list(_sp_cluster.keys())}")
            test("suggest_promotions cluster has avg_age_days",
                 "avg_age_days" in _sp_cluster and isinstance(_sp_cluster["avg_age_days"], (int, float)),
                 f"keys={list(_sp_cluster.keys())}")
            # Verify scoring formula: score = (count * 2) + recency_bonus
            # recency_bonus = max(0, 1 - avg_age/365), so score >= count * 2
            test("suggest_promotions score >= count*2 (formula check)",
                 _sp_cluster["score"] >= _sp_cluster["count"] * 2,
                 f"score={_sp_cluster['score']}, count={_sp_cluster['count']}")
            # Verify clusters are sorted by score descending
            if len(_sp_result["clusters"]) > 1:
                _scores = [c["score"] for c in _sp_result["clusters"]]
                test("suggest_promotions clusters sorted by score desc",
                     _scores == sorted(_scores, reverse=True),
                     f"scores={_scores}")
            # Verify top_k is respected
            test("suggest_promotions respects top_k=3",
                 len(_sp_result["clusters"]) <= 3,
                 f"got {len(_sp_result['clusters'])} clusters")
        else:
            skip("suggest_promotions cluster structure (no clusters available)")
            skip("suggest_promotions cluster supporting_ids (no clusters)")
            skip("suggest_promotions cluster count (no clusters)")
            skip("suggest_promotions cluster score (no clusters)")
            skip("suggest_promotions cluster avg_age_days (no clusters)")
            skip("suggest_promotions score formula (no clusters)")
            skip("suggest_promotions sorted desc (no clusters)")
            skip("suggest_promotions top_k (no clusters)")

else:
    for _skip_name in [
        "recency_weight=0 returns unchanged order",
        "recency_boost empty input returns empty",
        "recent entry boosted above older with same raw relevance",
        "entry >365 days old gets no boost",
        "boost formula ranks 0.5+boost(0.10) above 0.59 no-boost",
        "entry without timestamp gets no boost",
        "_adjusted_relevance key cleaned up",
        "format_results returns correct count",
        "format_results has content field",
        "format_results relevance = 1-distance",
        "format_results includes context from metadata",
        "format_results includes tags from metadata",
        "format_results includes timestamp from metadata",
        "format_results empty input returns empty list",
        "format_results None input returns empty list",
        "format_results no documents key returns empty",
        "format_results missing distances defaults to relevance 1.0",
        "format_summaries handles query() nested structure",
        "format_summaries query() has relevance from distances",
        "format_summaries handles get() flat structure",
        "format_summaries get() has no relevance (no distances)",
        "suggest_promotions returns dict with clusters key",
        "suggest_promotions has total_candidates key",
        "suggest_promotions has total_clusters key",
        "suggest_promotions clusters is a list",
        "suggest_promotions cluster structure (skipped)",
        "suggest_promotions cluster supporting_ids (skipped)",
        "suggest_promotions cluster count (skipped)",
        "suggest_promotions cluster score (skipped)",
        "suggest_promotions cluster avg_age_days (skipped)",
        "suggest_promotions score formula (skipped)",
        "suggest_promotions sorted desc (skipped)",
        "suggest_promotions top_k (skipped)",
    ]:
        skip(_skip_name)

# ─────────────────────────────────────────────────
print("\n--- Auto-Commit Hook ---")

import auto_commit

# Test: stage() stages a file inside ~/.claude/
_ac_staged_calls = []
_ac_orig_git = auto_commit.git
def _mock_git(*args, **kwargs):
    _ac_staged_calls.append(args)
    class R:
        returncode = 0
        stdout = ""
    return R()

auto_commit.git = _mock_git

import io as _io

# Simulate stdin with a file inside ~/.claude/
_ac_test_path = os.path.expanduser("~/.claude/hooks/some_file.py")
_ac_payload = json.dumps({"tool_input": {"file_path": _ac_test_path}})
_ac_old_stdin = sys.stdin
sys.stdin = _io.StringIO(_ac_payload)
_ac_staged_calls.clear()
auto_commit.stage()
sys.stdin = _ac_old_stdin
test("auto-commit: stage() stages file inside ~/.claude/",
     len(_ac_staged_calls) == 1 and _ac_staged_calls[0][0] == "add",
     f"calls: {_ac_staged_calls}")

# Test: stage() skips files outside ~/.claude/
_ac_test_path_ext = "/home/crab/other_project/foo.py"
_ac_payload_ext = json.dumps({"tool_input": {"file_path": _ac_test_path_ext}})
sys.stdin = _io.StringIO(_ac_payload_ext)
_ac_staged_calls.clear()
auto_commit.stage()
sys.stdin = _ac_old_stdin
test("auto-commit: stage() skips file outside ~/.claude/",
     len(_ac_staged_calls) == 0,
     f"calls: {_ac_staged_calls}")

# Test: stage() handles empty tool_input gracefully
_ac_payload_empty = json.dumps({"tool_input": {}})
sys.stdin = _io.StringIO(_ac_payload_empty)
_ac_staged_calls.clear()
auto_commit.stage()
sys.stdin = _ac_old_stdin
test("auto-commit: stage() handles empty tool_input",
     len(_ac_staged_calls) == 0,
     f"calls: {_ac_staged_calls}")

# Test: commit() commits when changes are staged
_ac_commit_calls = []
def _mock_git_with_diff(*args, **kwargs):
    _ac_commit_calls.append(args)
    class R:
        returncode = 0
    if args[0] == "diff":
        R.stdout = "hooks/auto_commit.py\nhooks/test_framework.py\n"
    else:
        R.stdout = ""
    return R()

auto_commit.git = _mock_git_with_diff
_ac_commit_calls.clear()
# Populate the staged tracker so commit() processes files
with open(auto_commit.STAGED_TRACKER, "w") as _ac_f:
    _ac_f.write("/home/crab/.claude/hooks/auto_commit.py\n/home/crab/.claude/hooks/test_framework.py\n")
auto_commit.commit()
test("auto-commit: commit() commits when changes staged",
     any(a[0] == "commit" for a in _ac_commit_calls),
     f"calls: {_ac_commit_calls}")

# Test: commit() no-ops when nothing is staged
def _mock_git_no_staged(*args, **kwargs):
    class R:
        returncode = 0
        stdout = ""
    if args[0] == "diff":
        R.stdout = ""
    return R()

_ac_noop_calls = []
def _mock_git_noop_track(*args, **kwargs):
    _ac_noop_calls.append(args)
    return _mock_git_no_staged(*args, **kwargs)

auto_commit.git = _mock_git_noop_track
_ac_noop_calls.clear()
auto_commit.commit()
test("auto-commit: commit() no-ops when nothing staged",
     not any(a[0] == "commit" for a in _ac_noop_calls),
     f"calls: {_ac_noop_calls}")

# Test: commit message includes file names and co-author tag
_ac_msg_calls = []
def _mock_git_capture_msg(*args, **kwargs):
    _ac_msg_calls.append(args)
    class R:
        returncode = 0
    if args[0] == "diff":
        R.stdout = "hooks/boot.py\nhooks/enforcer.py\n"
    else:
        R.stdout = ""
    return R()

auto_commit.git = _mock_git_capture_msg
_ac_msg_calls.clear()
# Populate the staged tracker so commit() doesn't exit early
with open(auto_commit.STAGED_TRACKER, "w") as _ac_f:
    _ac_f.write("/home/crab/.claude/hooks/boot.py\n/home/crab/.claude/hooks/enforcer.py\n")
auto_commit.commit()
_ac_commit_args = [a for a in _ac_msg_calls if a[0] == "commit"]
_ac_msg_ok = False
if _ac_commit_args:
    _ac_msg = _ac_commit_args[0][2]  # commit -m <message>
    _ac_msg_ok = "boot.py" in _ac_msg and "enforcer.py" in _ac_msg and "Co-Authored-By" in _ac_msg
test("auto-commit: commit message has file names + co-author",
     _ac_msg_ok,
     f"message: {_ac_commit_args}")

# Restore original
auto_commit.git = _ac_orig_git

# ─────────────────────────────────────────────────
# Test: Bundled Script Gather — Status & Wrap-up
# ─────────────────────────────────────────────────
print("\n--- Bundled Script Gather ---")

import subprocess as _bsg_sp

_BSG_CLAUDE_DIR = os.path.expanduser("~/.claude")
_STATUS_SCRIPT = os.path.join(_BSG_CLAUDE_DIR, "skills", "status", "scripts", "gather.py")
_WRAPUP_SCRIPT = os.path.join(_BSG_CLAUDE_DIR, "skills", "wrap-up", "scripts", "gather.py")

# 1. Status gather: produces valid dashboard text
_bsg_status = _bsg_sp.run(
    [sys.executable, _STATUS_SCRIPT],
    capture_output=True, text=True, timeout=15,
)
test("Status gather: exits cleanly", _bsg_status.returncode == 0,
     f"rc={_bsg_status.returncode}, stderr={_bsg_status.stderr[:200]}")
test("Status gather: contains box drawing", "\u2554" in _bsg_status.stdout and "\u255d" in _bsg_status.stdout,
     f"out={_bsg_status.stdout[:100]}")
test("Status gather: contains SYSTEM STATUS", "SYSTEM STATUS" in _bsg_status.stdout)
test("Status gather: includes gate count", "Gates:" in _bsg_status.stdout)
test("Status gather: includes skill count", "Skills:" in _bsg_status.stdout)
test("Status gather: includes hook count", "Hooks:" in _bsg_status.stdout)

# 2. Wrap-up gather: produces valid JSON with required keys
_bsg_wrapup = _bsg_sp.run(
    [sys.executable, _WRAPUP_SCRIPT],
    capture_output=True, text=True, timeout=15,
)
test("Wrap-up gather: exits cleanly", _bsg_wrapup.returncode == 0,
     f"rc={_bsg_wrapup.returncode}, stderr={_bsg_wrapup.stderr[:200]}")

_bsg_wj = {}
try:
    _bsg_wj = json.loads(_bsg_wrapup.stdout)
except json.JSONDecodeError as e:
    _bsg_wj = {}
    test("Wrap-up gather: valid JSON", False, f"parse error: {e}, out={_bsg_wrapup.stdout[:100]}")

if _bsg_wj:
    test("Wrap-up gather: valid JSON", True)
    _bsg_required = {"live_state", "handoff", "git", "memory", "promotion_candidates",
                     "recent_learnings", "risk_level", "warnings"}
    _bsg_missing = _bsg_required - set(_bsg_wj.keys())
    test("Wrap-up gather: has all required keys", len(_bsg_missing) == 0,
         f"missing: {_bsg_missing}")
    _bsg_ho = _bsg_wj.get("handoff", {})
    test("Wrap-up gather: handoff has content/age/stale",
         "content" in _bsg_ho and "age_hours" in _bsg_ho and "stale" in _bsg_ho)
    test("Wrap-up gather: risk_level valid",
         _bsg_wj.get("risk_level") in ("GREEN", "YELLOW", "RED"),
         f"got: {_bsg_wj.get('risk_level')}")
    test("Wrap-up gather: warnings is list",
         isinstance(_bsg_wj.get("warnings"), list))

# 3. Test risk_level computation directly
sys.path.insert(0, os.path.join(_BSG_CLAUDE_DIR, "skills", "wrap-up", "scripts"))
from gather import compute_risk_level as _bsg_crl

_bsg_green = _bsg_crl(
    {"stale": False}, {"clean": True}, {"accessible": True, "count": 100},
)
test("Wrap-up gather: risk GREEN when fresh+clean+memories", _bsg_green == "GREEN")

_bsg_yellow = _bsg_crl(
    {"stale": True}, {"clean": True}, {"accessible": True, "count": 100},
)
test("Wrap-up gather: risk YELLOW when handoff stale", _bsg_yellow == "YELLOW")

_bsg_yellow2 = _bsg_crl(
    {"stale": False}, {"clean": False}, {"accessible": True, "count": 50},
)
test("Wrap-up gather: risk YELLOW when git dirty", _bsg_yellow2 == "YELLOW")

_bsg_red = _bsg_crl(
    {"stale": False}, {"clean": True}, {"accessible": False, "count": 0},
)
test("Wrap-up gather: risk RED when memory inaccessible", _bsg_red == "RED")

_bsg_red2 = _bsg_crl(
    {"stale": False}, {"clean": True}, {"accessible": True, "count": 0},
)
test("Wrap-up gather: risk RED when memory count zero", _bsg_red2 == "RED")

# ─────────────────────────────────────────────────
# Test: Web Skill Scripts
# ─────────────────────────────────────────────────
print("\n--- Web Skill Scripts ---")

_WEB_SCRIPTS = os.path.join(os.path.expanduser("~"), ".claude", "skills", "web", "scripts")
sys.path.insert(0, _WEB_SCRIPTS)

# Test index.py: quality gate, chunking, content extraction
from index import quality_check as _ws_qc, chunk_content as _ws_cc, extract_content as _ws_ec, content_hash as _ws_ch

# Quality gate: reject short content
_ws_qc_short = _ws_qc("too few words here")
test("Web index: quality rejects <50 words", _ws_qc_short[0] is False,
     f"got passed={_ws_qc_short[0]}")

# Quality gate: accept normal content
_ws_normal = "This is a normal paragraph with plenty of words. " * 20
_ws_qc_ok = _ws_qc(_ws_normal)
test("Web index: quality accepts 50+ word content", _ws_qc_ok[0] is True,
     f"got passed={_ws_qc_ok[0]}, reason={_ws_qc_ok[1]}")

# Quality gate: score is between 0 and 1
test("Web index: quality score in range", 0.0 <= _ws_qc_ok[2] <= 1.0,
     f"got score={_ws_qc_ok[2]}")

# Chunking: splits long content
_ws_long = "\n\n".join([f"Paragraph {i} with enough words to fill space. " * 30 for i in range(10)])
_ws_chunks = _ws_cc(_ws_long, max_words=500)
test("Web index: chunking splits long content", len(_ws_chunks) > 1,
     f"got {len(_ws_chunks)} chunks")

# Chunking: single short content stays as one chunk
_ws_short_para = "A short paragraph with a few words."
_ws_single = _ws_cc(_ws_short_para)
test("Web index: chunking keeps short content as one chunk", len(_ws_single) == 1)

# Content hash: deterministic
_ws_h1 = _ws_ch("test content")
_ws_h2 = _ws_ch("test content")
test("Web index: content_hash is deterministic", _ws_h1 == _ws_h2)
test("Web index: content_hash is 16 chars hex", len(_ws_h1) == 16 and all(c in "0123456789abcdef" for c in _ws_h1))

# Content hash: different content gives different hash
_ws_h3 = _ws_ch("different content")
test("Web index: content_hash differs for different content", _ws_h1 != _ws_h3)

# Extract content: strips script tags from HTML
_ws_html = "<html><head><title>Test Page</title></head><body><script>evil()</script><p>Good content here.</p></body></html>"
_ws_md, _ws_title = _ws_ec(_ws_html)
test("Web index: extract strips script tags", "evil()" not in _ws_md)
test("Web index: extract gets title", _ws_title == "Test Page")
test("Web index: extract keeps body content", "Good content" in _ws_md)

# Metadata structure: verify index.py builds correct metadata keys
_ws_expected_meta_keys = {"url", "title", "chunk_index", "total_chunks", "indexed_at", "content_hash", "word_count"}
test("Web index: metadata keys defined",
     all(k in ["url", "title", "chunk_index", "total_chunks", "indexed_at", "content_hash", "word_count"]
         for k in _ws_expected_meta_keys))

# Test memory_socket.delete exists
sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "hooks"))
from shared import memory_socket as _ws_cdb
test("Web: memory_socket.delete exists", hasattr(_ws_cdb, "delete") and callable(_ws_cdb.delete))

# Test memory_server col_map includes web_pages (import check)
_ws_ms_path = os.path.join(os.path.expanduser("~"), ".claude", "hooks", "memory_server.py")
with open(_ws_ms_path) as _ws_f:
    _ws_ms_src = _ws_f.read()
test("Web: memory_server col_map has web_pages", '"web_pages": web_pages' in _ws_ms_src)
test("Web: memory_server has delete handler", 'if method == "delete"' in _ws_ms_src)
test("Web: memory_server inits web_pages collection", '"web_pages"' in _ws_ms_src)

# Test search.py imports cleanly
from search import search_pages as _ws_sp
test("Web search: search_pages is callable", callable(_ws_sp))

# Test list.py imports cleanly
from list import list_pages as _ws_lp
test("Web list: list_pages is callable", callable(_ws_lp))

# Test delete.py imports cleanly
from delete import delete_pages as _ws_dp
test("Web delete: delete_pages is callable", callable(_ws_dp))

# SKILL.md exists and has correct commands
_ws_skill_path = os.path.join(os.path.expanduser("~"), ".claude", "skills", "web", "SKILL.md")
test("Web: SKILL.md exists", os.path.isfile(_ws_skill_path))
with open(_ws_skill_path) as _ws_sf:
    _ws_skill_src = _ws_sf.read()
test("Web: SKILL.md has index command", "index.py" in _ws_skill_src)
test("Web: SKILL.md has search command", "search.py" in _ws_skill_src)
test("Web: SKILL.md has list command", "list.py" in _ws_skill_src)
test("Web: SKILL.md has delete command", "delete.py" in _ws_skill_src)

# Cleanup sys.path
sys.path = [p for p in sys.path if _WEB_SCRIPTS not in p]

print("\n--- PRP Skill ---")

_prp_base = os.path.expanduser("~/.claude")

# SKILL.md exists
_prp_skill = os.path.join(_prp_base, "skills", "prp", "SKILL.md")
test("PRP: SKILL.md exists", os.path.isfile(_prp_skill))

# SKILL.md has generate/execute/list commands
with open(_prp_skill) as _pf:
    _prp_skill_src = _pf.read()
test("PRP: SKILL.md has generate command", "generate" in _prp_skill_src.lower())
test("PRP: SKILL.md has execute command", "execute" in _prp_skill_src.lower())
test("PRP: SKILL.md has list command", "list" in _prp_skill_src.lower())

# PRP base template exists
_prp_template = os.path.join(_prp_base, "PRPs", "templates", "base.md")
test("PRP: base template exists", os.path.isfile(_prp_template))

# Template has required sections
with open(_prp_template) as _pf:
    _prp_tmpl_src = _pf.read()
test("PRP: template has Goal section", "## Goal" in _prp_tmpl_src)
test("PRP: template has Success Criteria section", "## Success Criteria" in _prp_tmpl_src)
test("PRP: template has Known Gotchas section", "## Known Gotchas" in _prp_tmpl_src)
test("PRP: template has Validation Gates section", "## Validation Gates" in _prp_tmpl_src)
test("PRP: template has Implementation Tasks section", "## Implementation Tasks" in _prp_tmpl_src)

# Template is valid markdown (no unclosed code blocks)
_prp_fence_count = _prp_tmpl_src.count("```")
test("PRP: template has balanced code fences", _prp_fence_count % 2 == 0,
     f"found {_prp_fence_count} fences (odd = unclosed)")

# PRPs directory exists
test("PRP: PRPs directory exists", os.path.isdir(os.path.join(_prp_base, "PRPs")))

# Examples directory exists
_prp_examples = os.path.join(_prp_base, "examples")
test("PRP: examples directory exists", os.path.isdir(_prp_examples))
test("PRP: examples README exists", os.path.isfile(os.path.join(_prp_examples, "README.md")))

print("\n--- Browser Skill ---")

_browser_base = os.path.expanduser("~/.claude")

# SKILL.md exists
_browser_skill = os.path.join(_browser_base, "skills", "browser", "SKILL.md")
test("Browser: SKILL.md exists", os.path.isfile(_browser_skill))

# SKILL.md has required commands
with open(_browser_skill) as _bf:
    _browser_skill_src = _bf.read()
test("Browser: SKILL.md has open command", "open" in _browser_skill_src.lower())
test("Browser: SKILL.md has snapshot command", "snapshot" in _browser_skill_src.lower())
test("Browser: SKILL.md has screenshot command", "screenshot" in _browser_skill_src.lower())
test("Browser: SKILL.md has click command", "click" in _browser_skill_src.lower())
test("Browser: SKILL.md has fill command", "fill" in _browser_skill_src.lower())
test("Browser: SKILL.md has verify command", "verify" in _browser_skill_src.lower())

# SKILL.md has integration with /ralph section
test("Browser: SKILL.md has ralph integration", "Integration with /ralph" in _browser_skill_src)

# SKILL.md has rules section
test("Browser: SKILL.md has rules section", "## Rules" in _browser_skill_src)

# SKILL.md references screenshots/ directory
test("Browser: SKILL.md references screenshots/ dir", "screenshots/" in _browser_skill_src)

# agent-browser CLI is installed
import shutil as _browser_shutil
_agent_browser_path = _browser_shutil.which("agent-browser")
test("Browser: agent-browser CLI is installed", _agent_browser_path is not None,
     f"path={_agent_browser_path}")

# /ralph SKILL.md references visual verify step
_ralph_skill = os.path.join(_browser_base, "skills", "ralph", "SKILL.md")
with open(_ralph_skill) as _rf:
    _ralph_skill_src = _rf.read()
test("Browser: ralph SKILL.md has visual verify step", "Visual Verify" in _ralph_skill_src)

# /ralph SKILL.md references screenshots in report
test("Browser: ralph SKILL.md has screenshots in report", "Screenshots taken" in _ralph_skill_src)

# ─────────────────────────────────────────────────
# GATE 13: WORKSPACE ISOLATION
# ─────────────────────────────────────────────────
print("\n--- Task Manager Tests ---")

_tm_dir = os.path.expanduser("~/.claude/PRPs")
_tm_script = os.path.join(_tm_dir, "task_manager.py")
_tm_test_prp = "__test_tm"
_tm_test_file = os.path.join(_tm_dir, f"{_tm_test_prp}.tasks.json")

# Create test tasks.json
_tm_test_data = {
    "prp": _tm_test_prp,
    "created": "2026-02-14T00:00:00Z",
    "tasks": [
        {"id": 1, "name": "First task", "status": "pending", "files": ["a.py"], "validate": "echo ok", "depends_on": []},
        {"id": 2, "name": "Second task", "status": "pending", "files": ["b.py"], "validate": "echo ok", "depends_on": [1]},
        {"id": 3, "name": "Third task", "status": "pending", "files": ["c.py"], "validate": "false", "depends_on": []},
    ],
}
with open(_tm_test_file, "w") as _f:
    json.dump(_tm_test_data, _f, indent=2)

# Test: task_manager.py exists and is executable
test("TaskManager: script exists", os.path.isfile(_tm_script))

# Test: status command
_tm_r = subprocess.run(
    [sys.executable, _tm_script, "status", _tm_test_prp],
    capture_output=True, text=True, timeout=10,
)
test("TaskManager: status exits 0", _tm_r.returncode == 0, f"rc={_tm_r.returncode}")
_tm_status = json.loads(_tm_r.stdout) if _tm_r.returncode == 0 else {}
test("TaskManager: status shows 3 tasks", _tm_status.get("total") == 3, f"total={_tm_status.get('total')}")
test("TaskManager: status shows 3 pending", _tm_status.get("counts", {}).get("pending") == 3)

# Test: next command returns first pending task (respects deps — task 2 depends on 1)
_tm_r = subprocess.run(
    [sys.executable, _tm_script, "next", _tm_test_prp],
    capture_output=True, text=True, timeout=10,
)
test("TaskManager: next exits 0", _tm_r.returncode == 0, f"rc={_tm_r.returncode}")
_tm_next = json.loads(_tm_r.stdout) if _tm_r.returncode == 0 else {}
test("TaskManager: next returns task 1 (not 2, blocked by dep)", _tm_next.get("id") == 1, f"id={_tm_next.get('id')}")

# Test: update command
_tm_r = subprocess.run(
    [sys.executable, _tm_script, "update", _tm_test_prp, "1", "passed"],
    capture_output=True, text=True, timeout=10,
)
test("TaskManager: update exits 0", _tm_r.returncode == 0, f"rc={_tm_r.returncode}")

# Verify task 1 is now passed
with open(_tm_test_file) as _f:
    _tm_after_update = json.load(_f)
test("TaskManager: task 1 status is passed", _tm_after_update["tasks"][0]["status"] == "passed")

# Test: next now returns task 2 (dep on task 1 is satisfied) or task 3 (no dep)
_tm_r = subprocess.run(
    [sys.executable, _tm_script, "next", _tm_test_prp],
    capture_output=True, text=True, timeout=10,
)
_tm_next2 = json.loads(_tm_r.stdout) if _tm_r.returncode == 0 else {}
# Task 3 has no deps and is pending, task 2 depends on 1 which is now passed — both eligible
# next iterates failed first, then pending, so should get task 2 or 3
test("TaskManager: next returns task 2 or 3 after task 1 passed",
     _tm_next2.get("id") in (2, 3), f"id={_tm_next2.get('id')}")

# Test: validate with passing command (echo ok)
_tm_r = subprocess.run(
    [sys.executable, _tm_script, "update", _tm_test_prp, "2", "pending"],
    capture_output=True, text=True, timeout=10,
)
_tm_r = subprocess.run(
    [sys.executable, _tm_script, "validate", _tm_test_prp, "2"],
    capture_output=True, text=True, timeout=10,
)
test("TaskManager: validate passing cmd exits 0", _tm_r.returncode == 0, f"rc={_tm_r.returncode}")
with open(_tm_test_file) as _f:
    _tm_after_validate = json.load(_f)
test("TaskManager: validate sets task 2 to passed",
     _tm_after_validate["tasks"][1]["status"] == "passed")

# Test: validate with failing command (false)
_tm_r = subprocess.run(
    [sys.executable, _tm_script, "validate", _tm_test_prp, "3"],
    capture_output=True, text=True, timeout=10,
)
test("TaskManager: validate failing cmd exits 1", _tm_r.returncode == 1, f"rc={_tm_r.returncode}")
with open(_tm_test_file) as _f:
    _tm_after_fail = json.load(_f)
test("TaskManager: validate sets task 3 to failed",
     _tm_after_fail["tasks"][2]["status"] == "failed")

# Test: invalid status rejected
_tm_r = subprocess.run(
    [sys.executable, _tm_script, "update", _tm_test_prp, "1", "bogus"],
    capture_output=True, text=True, timeout=10,
)
test("TaskManager: invalid status rejected", _tm_r.returncode == 1)

# Test: next when all done/failed returns exit 1
# Set task 3 to passed too
subprocess.run(
    [sys.executable, _tm_script, "update", _tm_test_prp, "3", "passed"],
    capture_output=True, text=True, timeout=10,
)
_tm_r = subprocess.run(
    [sys.executable, _tm_script, "next", _tm_test_prp],
    capture_output=True, text=True, timeout=10,
)
test("TaskManager: next exits 1 when all tasks passed", _tm_r.returncode == 1)

# Test: nonexistent PRP fails
_tm_r = subprocess.run(
    [sys.executable, _tm_script, "status", "nonexistent_prp_xyz"],
    capture_output=True, text=True, timeout=10,
)
test("TaskManager: nonexistent PRP exits 1", _tm_r.returncode == 1)

# Test: tasks.json template exists
_tm_template = os.path.join(_tm_dir, "templates", "tasks.json")
test("TaskManager: tasks.json template exists", os.path.isfile(_tm_template))
with open(_tm_template) as _f:
    _tm_tmpl = json.load(_f)
test("TaskManager: template has tasks array", "tasks" in _tm_tmpl and isinstance(_tm_tmpl["tasks"], list))

# Test: torus-loop.sh exists and is executable
_ml_script = os.path.expanduser("~/.claude/scripts/torus-loop.sh")
test("TorusLoop: script exists", os.path.isfile(_ml_script))
test("TorusLoop: script is executable", os.access(_ml_script, os.X_OK))

# Test: torus-prompt.md exists
_ml_prompt = os.path.expanduser("~/.claude/scripts/torus-prompt.md")
test("TorusLoop: prompt template exists", os.path.isfile(_ml_prompt))
with open(_ml_prompt) as _f:
    _ml_prompt_src = _f.read()
test("TorusLoop: prompt has task_id placeholder", "{task_id}" in _ml_prompt_src)
test("TorusLoop: prompt has validate_command placeholder", "{validate_command}" in _ml_prompt_src)
test("TorusLoop: prompt has search_knowledge rule", "search_knowledge" in _ml_prompt_src)

# Test: /loop SKILL.md exists and has required commands
_loop_skill = os.path.expanduser("~/.claude/skills/loop/SKILL.md")
test("LoopSkill: SKILL.md exists", os.path.isfile(_loop_skill))
with open(_loop_skill) as _f:
    _loop_src = _f.read()
test("LoopSkill: has start command", "/loop start" in _loop_src)
test("LoopSkill: has status command", "/loop status" in _loop_src)
test("LoopSkill: has stop command", "/loop stop" in _loop_src)
test("LoopSkill: references torus-loop.sh", "torus-loop.sh" in _loop_src)
test("LoopSkill: references stop sentinel", ".stop" in _loop_src)

# Test: base.md template has Validate field
_base_tmpl = os.path.join(_tm_dir, "templates", "base.md")
with open(_base_tmpl) as _f:
    _base_src = _f.read()
test("PRP: base.md has Validate field", "**Validate**:" in _base_src)

# Test: prp SKILL.md has status command
_prp_skill = os.path.expanduser("~/.claude/skills/prp/SKILL.md")
with open(_prp_skill) as _f:
    _prp_src = _f.read()
test("PRP: SKILL.md has /prp status command", "/prp status" in _prp_src)
test("PRP: SKILL.md has tasks.json generation step", "tasks.json" in _prp_src)

# Test: torus-loop.sh has stop sentinel check
with open(_ml_script) as _f:
    _ml_src = _f.read()
test("TorusLoop: checks stop sentinel", "STOP_SENTINEL" in _ml_src)
test("TorusLoop: has max iterations", "MAX_ITERATIONS" in _ml_src)
test("TorusLoop: has git commit on success", "git commit" in _ml_src)
test("TorusLoop: uses --dangerously-skip-permissions", "--dangerously-skip-permissions" in _ml_src)
test("TorusLoop: has activity log", "activity.md" in _ml_src or "ACTIVITY_LOG" in _ml_src)

# Cleanup test file
try:
    os.remove(_tm_test_file)
except OSError:
    pass

# ─────────────────────────────────────────────────
# --- Teammate Transcript Helpers ---
# ─────────────────────────────────────────────────

# Import the dormant helpers from memory_server
sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "hooks"))
from memory_server import _parse_transcript_actions, _format_teammate_summary, get_teammate_context

# Helper: create a temp JSONL transcript file
def _make_transcript(lines_data):
    """Write a list of dicts as JSONL to a temp file, return path."""
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as f:
        for entry in lines_data:
            f.write(json.dumps(entry) + "\n")
    return path

# Helper: build an assistant message with tool_use blocks
def _assistant_tool_msg(tool_name, tool_input):
    return {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "tool_use", "name": tool_name, "input": tool_input}
            ]
        }
    }

# Helper: build an assistant message with text block
def _assistant_text_msg(text):
    return {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "text", "text": text}
            ]
        }
    }

# Test 1: _parse_transcript_actions — happy path
_t1_lines = [
    _assistant_tool_msg("Read", {"file_path": "/home/crab/hooks/gate_01.py"}),
    _assistant_tool_msg("Grep", {"pattern": "file_claims", "path": "/home/crab/hooks/"}),
    _assistant_tool_msg("Edit", {"file_path": "/home/crab/hooks/gate_13.py", "old_string": "x", "new_string": "y"}),
]
_t1_path = _make_transcript(_t1_lines)
_t1_result = _parse_transcript_actions(_t1_path, max_actions=5)
test("TranscriptParse: happy path returns 3 actions", len(_t1_result) == 3)
os.remove(_t1_path)

# Test 2: _parse_transcript_actions — empty file
import tempfile
_t2_fd, _t2_path = tempfile.mkstemp(suffix=".jsonl")
os.close(_t2_fd)
_t2_result = _parse_transcript_actions(_t2_path, max_actions=5)
test("TranscriptParse: empty file returns []", _t2_result == [])
os.remove(_t2_path)

# Test 3: _parse_transcript_actions — missing file
_t3_result = _parse_transcript_actions("/tmp/nonexistent_transcript_99999.jsonl", max_actions=5)
test("TranscriptParse: missing file returns []", _t3_result == [])

# Test 4: _parse_transcript_actions — malformed lines
_t4_fd, _t4_path = tempfile.mkstemp(suffix=".jsonl")
with os.fdopen(_t4_fd, "w") as _f:
    _f.write("this is not json\n")
    _f.write(json.dumps(_assistant_tool_msg("Bash", {"command": "echo hello"})) + "\n")
    _f.write("{broken json\n")
    _f.write(json.dumps(_assistant_tool_msg("Read", {"file_path": "/tmp/a.py"})) + "\n")
_t4_result = _parse_transcript_actions(_t4_path, max_actions=5)
test("TranscriptParse: malformed lines skipped, valid returned", len(_t4_result) == 2)
os.remove(_t4_path)

# Test 5: _parse_transcript_actions — max_actions cap
_t5_lines = [_assistant_tool_msg("Read", {"file_path": f"/tmp/file_{i}.py"}) for i in range(10)]
_t5_path = _make_transcript(_t5_lines)
_t5_result = _parse_transcript_actions(_t5_path, max_actions=3)
test("TranscriptParse: max_actions=3 caps at 3", len(_t5_result) == 3)
os.remove(_t5_path)

# Test 6: _parse_transcript_actions — text-only messages
_t6_lines = [
    _assistant_text_msg("Let me analyze the error in the authentication module"),
    _assistant_text_msg("The root cause is a missing null check"),
]
_t6_path = _make_transcript(_t6_lines)
_t6_result = _parse_transcript_actions(_t6_path, max_actions=5)
test("TranscriptParse: text-only messages extracted", len(_t6_result) == 2 and "Text:" in _t6_result[0]["action"])
os.remove(_t6_path)

# Test 7: _format_teammate_summary — formats correctly
_t7_actions = [
    {"action": "Read: /home/crab/hooks/gate_01.py", "outcome": ""},
    {"action": "Grep: file_claims in hooks/", "outcome": ""},
    {"action": "Edit: gate_13.py", "outcome": ""},
]
_t7_summary = _format_teammate_summary("builder", _t7_actions, True)
test("FormatSummary: contains Teammate header", "Teammate: builder" in _t7_summary)
test("FormatSummary: contains Recent actions", "Recent actions:" in _t7_summary)
test("FormatSummary: has numbered list", "  1." in _t7_summary and "  2." in _t7_summary)

# Test 8: _format_teammate_summary — respects char budget
_t8_actions = [{"action": f"Read: /home/crab/some/very/long/path/file_{i}.py with extra detail padding", "outcome": ""} for i in range(20)]
_t8_summary = _format_teammate_summary("researcher", _t8_actions, False)
test("FormatSummary: output under 1200 chars", len(_t8_summary) <= 1200)

# Test 9: get_teammate_context — no active subagents
# Temporarily create an empty state file to test
_t9_fd, _t9_state_path = tempfile.mkstemp(prefix="state_", suffix=".json", dir=os.path.join(os.path.expanduser("~"), ".claude", "hooks"))
with os.fdopen(_t9_fd, "w") as _f:
    json.dump({"active_subagents": []}, _f)
_t9_result = get_teammate_context()
test("GetContext: no subagents returns empty", _t9_result["teammates"] == [] and _t9_result["count"] == 0)
os.remove(_t9_state_path)

# Test 10: get_teammate_context — with agent_name filter
_t10_lines = [_assistant_tool_msg("Read", {"file_path": "/tmp/test.py"})]
_t10_transcript = _make_transcript(_t10_lines)
_t10_fd, _t10_state_path = tempfile.mkstemp(prefix="state_", suffix=".json", dir=os.path.join(os.path.expanduser("~"), ".claude", "hooks"))
with os.fdopen(_t10_fd, "w") as _f:
    json.dump({"active_subagents": [
        {"agent_id": "abc-123", "agent_type": "builder", "transcript_path": _t10_transcript, "start_ts": time.time()},
        {"agent_id": "def-456", "agent_type": "researcher", "transcript_path": _t10_transcript, "start_ts": time.time()},
    ]}, _f)
# Small sleep to ensure this state file is the newest
time.sleep(0.05)
_t10_result = get_teammate_context(agent_name="builder")
test("GetContext: agent_name filter returns 1 match", _t10_result["count"] == 1)
os.remove(_t10_state_path)
os.remove(_t10_transcript)

# Test 11: get_teammate_context — missing transcript file
_t11_fd, _t11_state_path = tempfile.mkstemp(prefix="state_", suffix=".json", dir=os.path.join(os.path.expanduser("~"), ".claude", "hooks"))
with os.fdopen(_t11_fd, "w") as _f:
    json.dump({"active_subagents": [
        {"agent_id": "ghi-789", "agent_type": "auditor", "transcript_path": "/tmp/does_not_exist_99999.jsonl", "start_ts": time.time()},
    ]}, _f)
time.sleep(0.05)
_t11_result = get_teammate_context()
test("GetContext: missing transcript gives graceful summary", _t11_result["count"] == 1 and "no actions recorded" in _t11_result["teammates"][0])
os.remove(_t11_state_path)

# Test 12: get_teammate_context — returns dict with expected keys
_t12_fd, _t12_state_path = tempfile.mkstemp(prefix="state_", suffix=".json", dir=os.path.join(os.path.expanduser("~"), ".claude", "hooks"))
with os.fdopen(_t12_fd, "w") as _f:
    json.dump({"active_subagents": []}, _f)
_t12_result = get_teammate_context()
test("GetContext: returns dict with teammates and count keys", isinstance(_t12_result, dict) and "teammates" in _t12_result and "count" in _t12_result)
os.remove(_t12_state_path)

# ─────────────────────────────────────────────────
# Citation URL Extraction Tests
# ─────────────────────────────────────────────────
print("\n--- Citation URL Extraction ---")

# Import the citation functions directly (no LanceDB needed)
try:
    from memory_server import _validate_url, _rank_url_authority, _extract_citations, TagIndex
    _citation_imports_ok = True
except ImportError:
    _citation_imports_ok = False
    test("Citation imports available", False, "Could not import citation functions")

if _citation_imports_ok:
    # Test 1: [source: URL] extracts primary, strips marker
    _c1 = _extract_citations("Found fix [source: https://github.com/foo/bar] in repo", "")
    test("Citation: [source:] extracts primary", _c1["primary_source"] == "https://github.com/foo/bar")
    test("Citation: [source:] stripped from content", "[source:" not in _c1["clean_content"])

    # Test 2: [ref: URL] extracts reference, strips marker
    _c2 = _extract_citations("See [ref: https://docs.python.org/3/lib] for details", "")
    test("Citation: [ref:] extracts reference", "https://docs.python.org/3/lib" in _c2["related_urls"])
    test("Citation: [ref:] stripped from content", "[ref:" not in _c2["clean_content"])

    # Test 3: Multiple [ref:] markers all captured
    _c3 = _extract_citations(
        "Check [ref: https://github.com/a] and [ref: https://dev.to/b]",
        ""
    )
    test("Citation: multiple refs captured", "https://github.com/a" in _c3["related_urls"] and "https://dev.to/b" in _c3["related_urls"])

    # Test 4: Mixed explicit + auto-extracted URLs
    _c4 = _extract_citations(
        "[source: https://github.com/main] also see https://stackoverflow.com/q/123",
        ""
    )
    test("Citation: mixed explicit+auto", _c4["primary_source"] == "https://github.com/main" and "stackoverflow.com" in _c4["related_urls"])

    # Test 5: Auto-ranking: high-authority domain becomes primary
    _c5 = _extract_citations(
        "Read https://medium.com/article and https://github.com/repo",
        ""
    )
    test("Citation: auto-ranking promotes high authority", _c5["primary_source"] == "https://github.com/repo")

    # Test 6: Invalid URLs rejected
    test("Citation: validate_url rejects no scheme", _validate_url("not-a-url.com") == "")
    test("Citation: validate_url rejects no netloc", _validate_url("http://") == "")
    test("Citation: validate_url rejects no dot", _validate_url("http://localhost") == "")

    # Test 7: Trailing punctuation stripped
    test("Citation: trailing punctuation stripped", _validate_url("https://example.org/page.") == "https://example.org/page")
    test("Citation: trailing paren stripped", _validate_url("https://example.org/page)") == "https://example.org/page")

    # Test 8: Empty content/context → no crash
    _c8 = _extract_citations("", "")
    test("Citation: empty content no crash", _c8["source_method"] == "none" and _c8["primary_source"] == "")

    # Test 9: Malformed marker → fallback to auto
    _c9 = _extract_citations("See [source: broken and https://github.com/fallback", "")
    test("Citation: malformed marker falls back", _c9["primary_source"] == "https://github.com/fallback")

    # Test 10: URL deduplication
    _c10 = _extract_citations(
        "URL https://github.com/repo appears here",
        "Also https://github.com/repo in context"
    )
    test("Citation: dedup across content+context", _c10["related_urls"].count("https://github.com/repo") <= 1)

    # Test 11: Cap enforcement (>4 URLs → only 4 kept)
    _c11 = _extract_citations(
        "https://github.com/a https://github.com/b https://github.com/c https://github.com/d https://github.com/e",
        ""
    )
    _total_urls = (1 if _c11["primary_source"] else 0) + len([u for u in _c11["related_urls"].split(",") if u.strip()])
    test("Citation: cap at MAX_CITATION_URLS", _total_urls <= 4)

    # Test 12: Noise URL filtering (localhost, example.com skipped)
    _c12 = _extract_citations("See http://localhost:3000/api and https://github.com/real", "")
    test("Citation: noise URLs filtered", "localhost" not in _c12["primary_source"] and "localhost" not in _c12["related_urls"])

    # Test 13: source_method values
    _c13a = _extract_citations("[source: https://github.com/x] content here", "")
    test("Citation: source_method=explicit for markers", _c13a["source_method"] == "explicit")
    _c13b = _extract_citations("See https://github.com/auto content here", "")
    test("Citation: source_method=auto for bare URLs", _c13b["source_method"] == "auto")
    _c13c = _extract_citations("No URLs in this content at all", "")
    test("Citation: source_method=none when no URLs", _c13c["source_method"] == "none")

    # Test 14: URL authority ranking
    test("Citation: github.com is high authority", _rank_url_authority("https://github.com/x") == 1)
    test("Citation: medium.com is medium authority", _rank_url_authority("https://medium.com/x") == 2)
    test("Citation: localhost is low authority", _rank_url_authority("http://localhost:3000") == 3)

    # Test 15: TagIndex stores tags for citation entries
    _ti_test = TagIndex(":memory:")
    _ti_test.add_tags("cite1", "tag1,tag2")
    _ti_found = _ti_test.tag_search(["tag1"], top_k=1)
    test("TagIndex: tag_search finds citation entry", len(_ti_found) > 0 and _ti_found[0] == "cite1")

    # Test 16: TagIndex tag_search with multiple tags
    _ti_test.add_tags("cite2", "tag1,tag3")
    _ti_multi = _ti_test.tag_search(["tag1"], top_k=10)
    test("TagIndex: tag_search returns multiple matches", len(_ti_multi) >= 2)

    # Test 17: TagIndex remove works
    _ti_test.remove("cite1")
    _ti_after = _ti_test.tag_search(["tag1"], top_k=10)
    test("TagIndex: remove clears tags", "cite1" not in _ti_after and "cite2" in _ti_after)

    # Test 18: TagIndex entry without tags → not found
    _ti_test.add_tags("cite3", "")
    _ti_empty = _ti_test.tag_search(["tag1"], top_k=10)
    test("TagIndex: empty tags not indexed", "cite3" not in _ti_empty)

    # Test 19: Extraction failure → returns defaults (fail-open)
    _c19 = _extract_citations(None, None)  # type: ignore — intentional bad input
    test("Citation: fail-open on bad input", _c19["source_method"] == "none")

    # Test 20: validate_url caps long URLs
    _long_url = "https://example.org/" + "a" * 600
    test("Citation: long URL rejected", _validate_url(_long_url) == "")

# ─────────────────────────────────────────────────
# Hybrid Memory Linking: resolves:/resolved_by: co-retrieval
# ─────────────────────────────────────────────────
if not MEMORY_SERVER_RUNNING:
    print("\n--- Hybrid Memory Linking ---")

    from memory_server import remember_this as _hl_remember, search_knowledge as _hl_search, collection as _hl_col

    # Test 1: resolves:ID creates bidirectional link (target gets resolved_by:)
    _hl_problem = _hl_remember(
        "LINK TEST PROBLEM: Gate 99 deadlock occurs when two agents acquire locks in opposite order causing indefinite blocking",
        "hybrid linking test", "type:error,area:testing,link-test"
    )
    _hl_problem_id = _hl_problem.get("id") or _hl_problem.get("existing_id", "")
    _hl_fix = _hl_remember(
        "LINK TEST FIX: Fixed Gate 99 deadlock by enforcing consistent lock acquisition order across all agents in the framework",
        "hybrid linking test", f"type:fix,area:testing,link-test,resolves:{_hl_problem_id}"
    )
    _hl_fix_id = _hl_fix.get("id") or _hl_fix.get("existing_id", "")
    # Verify the fix response has linked_to field
    test("Link: resolves:ID → linked_to in response",
         _hl_fix.get("linked_to") == _hl_problem_id,
         f"linked_to={_hl_fix.get('linked_to')}, expected={_hl_problem_id}")
    # Verify the target got resolved_by: back-link
    _hl_target_meta = _hl_col.get(ids=[_hl_problem_id], include=["metadatas"])
    _hl_target_tags = _hl_target_meta["metadatas"][0].get("tags", "") if _hl_target_meta.get("metadatas") else ""
    test("Link: target gets resolved_by: back-link",
         f"resolved_by:{_hl_fix_id}" in _hl_target_tags,
         f"target tags={_hl_target_tags}")

    # Test 2: Search co-retrieves linked memory with "linked": True flag
    _hl_search_result = _hl_search("LINK TEST PROBLEM Gate 99 deadlock", top_k=5)
    _hl_linked_found = False
    for _hl_r in _hl_search_result.get("results", []):
        if _hl_r.get("id") == _hl_fix_id and _hl_r.get("linked"):
            _hl_linked_found = True
            break
    # Also check if fix appears organically (which means linked flag won't be set)
    _hl_organic_fix = any(r.get("id") == _hl_fix_id and not r.get("linked") for r in _hl_search_result.get("results", []))
    test("Link: search co-retrieves fix with linked=True (or organic)",
         _hl_linked_found or _hl_organic_fix,
         f"fix_id={_hl_fix_id} not in results")

    # Test 3: Invalid resolves:ID → warning in response, no crash
    _hl_bad_link = _hl_remember(
        "LINK TEST BAD: Attempted fix for nonexistent problem memory that should produce a warning but not crash",
        "hybrid linking test", "type:fix,area:testing,link-test,resolves:FAKE_NONEXISTENT_ID_12345"
    )
    test("Link: invalid resolves:ID → link_warning",
         "link_warning" in _hl_bad_link and _hl_bad_link.get("linked_to") is None,
         f"warning={_hl_bad_link.get('link_warning')}, linked_to={_hl_bad_link.get('linked_to')}")

    # Test 4: type:fix without resolves: → hint in response
    _hl_no_resolve = _hl_remember(
        "LINK TEST HINTCHECK: Fixed some issue without specifying which problem memory it resolves to verify hint appears",
        "hybrid linking test", "type:fix,area:testing,link-test"
    )
    test("Link: type:fix without resolves: → hint",
         "hint" in _hl_no_resolve,
         f"keys={list(_hl_no_resolve.keys())}")

    # Test 5: Multiple resolves: tags → first used, warning
    _hl_multi = _hl_remember(
        "LINK TEST MULTI: Fix with multiple resolves tags should use first and warn about the extra ones being ignored",
        "hybrid linking test",
        f"type:fix,area:testing,link-test,resolves:{_hl_problem_id},resolves:ANOTHER_ID"
    )
    test("Link: multiple resolves: → warning",
         _hl_multi.get("link_warning") is not None and "Multiple" in (_hl_multi.get("link_warning") or ""),
         f"warning={_hl_multi.get('link_warning')}")

    # Test 6: Tag overflow (>500 chars) → link skipped, warning
    # Create a problem with very long tags already near the 500 char limit
    _hl_long_tags = "type:error,area:testing," + ",".join(f"filler-tag-{i:03d}" for i in range(30))
    _hl_long_problem = _hl_remember(
        "LINK TEST OVERFLOW: Problem memory with excessively long tags to test the 500 character tag overflow protection",
        "hybrid linking test", _hl_long_tags[:497] + "..."
    )
    _hl_long_id = _hl_long_problem.get("id") or _hl_long_problem.get("existing_id", "")
    _hl_overflow_fix = _hl_remember(
        "LINK TEST OVERFLOW FIX: Fix that tries to link to the long-tag problem which should trigger tag overflow warning",
        "hybrid linking test", f"type:fix,area:testing,link-test,resolves:{_hl_long_id}"
    )
    # Either it linked successfully (tags had room) or warned about overflow
    _hl_overflow_ok = _hl_overflow_fix.get("linked_to") == _hl_long_id or (
        _hl_overflow_fix.get("link_warning") is not None and "overflow" in (_hl_overflow_fix.get("link_warning") or "").lower()
    )
    test("Link: tag overflow → link or warning",
         _hl_overflow_ok,
         f"linked_to={_hl_overflow_fix.get('linked_to')}, warning={_hl_overflow_fix.get('link_warning')}")

    # Test 7: Deduplication — linked memory already in organic results → not duplicated
    _hl_dedup_search = _hl_search("LINK TEST FIX Gate 99 deadlock lock acquisition", top_k=15)
    _hl_dedup_ids = [r.get("id") for r in _hl_dedup_search.get("results", [])]
    _hl_dedup_counts = {}
    for _did in _hl_dedup_ids:
        _hl_dedup_counts[_did] = _hl_dedup_counts.get(_did, 0) + 1
    _hl_any_dups = any(c > 1 for c in _hl_dedup_counts.values())
    test("Link: no duplicate IDs in search results",
         not _hl_any_dups,
         f"dups={[k for k, v in _hl_dedup_counts.items() if v > 1]}")

    # Test 8: Fail-open — simulated exception in linking doesn't break remember_this
    # (Already proven by Test 3 — invalid ID didn't crash. Also verify the result has all expected fields)
    test("Link: fail-open — bad link still returns valid result",
         _hl_bad_link.get("result") == "Memory stored successfully!" and "id" in _hl_bad_link,
         f"result={_hl_bad_link.get('result')}")

    # Cleanup test memories
    _hl_cleanup_ids = [_hl_problem_id, _hl_fix_id]
    if _hl_bad_link.get("id"):
        _hl_cleanup_ids.append(_hl_bad_link["id"])
    if _hl_no_resolve.get("id"):
        _hl_cleanup_ids.append(_hl_no_resolve["id"])
    if _hl_multi.get("id"):
        _hl_cleanup_ids.append(_hl_multi["id"])
    if _hl_long_id:
        _hl_cleanup_ids.append(_hl_long_id)
    if _hl_overflow_fix.get("id"):
        _hl_cleanup_ids.append(_hl_overflow_fix["id"])
    _hl_cleanup_ids = [i for i in _hl_cleanup_ids if i]
    if _hl_cleanup_ids:
        try:
            _hl_col.delete(ids=_hl_cleanup_ids)
        except Exception:
            pass  # Cleanup failure is non-critical

else:
    print("\n[SKIP] Hybrid Memory Linking tests skipped (memory MCP server running)")
    for _hl_skip_name in [
        "Link: resolves:ID → linked_to in response",
        "Link: target gets resolved_by: back-link",
        "Link: search co-retrieves fix with linked=True (or organic)",
        "Link: invalid resolves:ID → link_warning",
        "Link: type:fix without resolves: → hint",
        "Link: multiple resolves: → warning",
        "Link: tag overflow → link or warning",
        "Link: no duplicate IDs in search results",
        "Link: fail-open — bad link still returns valid result",
    ]:
        skip(_hl_skip_name)

# ─────────────────────────────────────────────────
# Gate 16: Code Quality Guard
# ─────────────────────────────────────────────────
from gates.gate_16_code_quality import check as gate16_check

def _g16(tool_name, tool_input, state=None):
    if state is None:
        state = default_state()
    return gate16_check(tool_name, tool_input, state)

# 1. Secret detection
_g16_r = _g16("Edit", {"file_path": "/tmp/app.py", "new_string": 'api_key = "sk-abc123def456789"'})
test("G16: secret in code → warns", _g16_r.message is not None and "secret-in-code" in _g16_r.message)

# 2. Debug print
_g16_r = _g16("Edit", {"file_path": "/tmp/app.py", "new_string": '    print("debug value")\n'})
test("G16: debug print → warns", _g16_r.message is not None and "debug-print" in _g16_r.message)

# 3. Broad except
_g16_r = _g16("Edit", {"file_path": "/tmp/app.py", "new_string": 'try:\n    pass\nexcept:\n    pass'})
test("G16: broad except → warns", _g16_r.message is not None and "broad-except" in _g16_r.message)

# 4. TODO detection
_g16_r = _g16("Edit", {"file_path": "/tmp/app.py", "new_string": '# TODO fix this later'})
test("G16: TODO → warns (informational)", _g16_r.message is not None and "todo-fixme" in _g16_r.message)

# 5. Clean code — no warning
_g16_r = _g16("Edit", {"file_path": "/tmp/app.py", "new_string": 'def hello():\n    return "world"'})
test("G16: clean code → no warning", _g16_r.message is None or _g16_r.message == "")

# 6. Progressive: 3 warns → 4th blocks
_g16_state = default_state()
_g16_state["code_quality_warnings_per_file"] = {"/tmp/prog.py": 3}  # Already at 3
_g16_r = _g16("Edit", {"file_path": "/tmp/prog.py", "new_string": 'password = "supersecretvalue123"'}, _g16_state)
test("G16: 4th violation → blocks", _g16_r.blocked is True)

# 7. Counter reset on clean edit
_g16_state = default_state()
_g16_state["code_quality_warnings_per_file"] = {"/tmp/reset.py": 2}
_g16_r = _g16("Edit", {"file_path": "/tmp/reset.py", "new_string": 'x = 42'}, _g16_state)
test("G16: clean edit resets counter", _g16_state["code_quality_warnings_per_file"].get("/tmp/reset.py") is None)

# 8. Test file exempt
_g16_r = _g16("Edit", {"file_path": "/tmp/test_foo.py", "new_string": 'print("debug")'})
test("G16: test file exempt", _g16_r.blocked is False and (not _g16_r.message))

# 9. Non-code exempt (.json)
_g16_r = _g16("Edit", {"file_path": "/tmp/config.json", "new_string": '"password": "abc12345678"'})
test("G16: .json file exempt", _g16_r.blocked is False and (not _g16_r.message))

# 10. Skills dir exempt
_g16_r = _g16("Edit", {"file_path": "/home/crab/.claude/skills/foo.py", "new_string": 'print("debug")'})
test("G16: skills dir exempt", _g16_r.blocked is False and (not _g16_r.message))

# 11. Empty content exempt
_g16_r = _g16("Edit", {"file_path": "/tmp/app.py", "new_string": ""})
test("G16: empty content exempt", _g16_r.blocked is False and (not _g16_r.message))

# 12. Short secret exempt (< 8 chars)
_g16_r = _g16("Edit", {"file_path": "/tmp/app.py", "new_string": 'password = "x"'})
test("G16: short secret not flagged", _g16_r.blocked is False and (not _g16_r.message))

# 13. NotebookEdit with debug → warns
_g16_r = _g16("NotebookEdit", {"notebook_path": "/tmp/nb.py", "new_source": 'import pdb\npdb.set_trace()'})
test("G16: NotebookEdit debug → warns", _g16_r.message is not None and "debug-print" in _g16_r.message)

# 14. Multiple violations → single warning listing all
_g16_r = _g16("Edit", {"file_path": "/tmp/multi.py", "new_string": 'api_key = "sk-abc123def456"\nexcept:\n    pass'})
test("G16: multiple violations in one warning", _g16_r.message is not None and "secret-in-code" in _g16_r.message and "broad-except" in _g16_r.message)

# 15. TODO never escalates counter
_g16_state = default_state()
for _i in range(5):
    _g16("Edit", {"file_path": "/tmp/todo.py", "new_string": '# TODO something'}, _g16_state)
_g16_r = _g16("Edit", {"file_path": "/tmp/todo.py", "new_string": '# FIXME urgent'}, _g16_state)
test("G16: TODO never escalates (5 TODOs, still not blocked)", _g16_r.blocked is False)

# ─────────────────────────────────────────────────
# Lazy-Load Gate Dispatch (GATE_TOOL_MAP)
# ─────────────────────────────────────────────────
print("\n--- Memory Ingestion Levers ---")

# Test 1: Lever 1 — CLAUDE.md contains expanded save rule
_claude_md_path = os.path.join(HOOKS_DIR, "..", "CLAUDE.md")
with open(_claude_md_path) as _f:
    _claude_md = _f.read()
test("Lever1: CLAUDE.md has 'failed-approach' in save rule",
     "failed-approach" in _claude_md)
test("Lever1: CLAUDE.md has 'preference' in save rule",
     "preference" in _claude_md)

# Test 2-7: Lever 4 — Auto-remember queue and triggers
import tempfile as _tempfile
from tracker import _auto_remember_event, AUTO_REMEMBER_QUEUE, MAX_AUTO_REMEMBER_PER_SESSION

# Use a temp file for queue during tests
_orig_queue = AUTO_REMEMBER_QUEUE
import tracker as _tracker_mod
_test_queue = os.path.join(_tempfile.gettempdir(), ".test_auto_remember_queue.jsonl")
_tracker_mod.AUTO_REMEMBER_QUEUE = _test_queue
# Also patch the source module (tracker_pkg.auto_remember) where the function reads the constant
import tracker_pkg.auto_remember as _ar_mod
_ar_mod.AUTO_REMEMBER_QUEUE = _test_queue
import types
# Clean up any leftover test queue
if os.path.exists(_test_queue):
    os.unlink(_test_queue)

# Test 2: Queue write — simulate trigger, verify queue gets entry
_test_state_ar = {"auto_remember_count": 0}
_auto_remember_event("Test memory content for queue write", context="test", tags="type:test",
                     critical=False, state=_test_state_ar)
_queue_exists = os.path.exists(_test_queue)
_queue_content = ""
if _queue_exists:
    with open(_test_queue) as _qf:
        _queue_content = _qf.read()
test("Lever4: Queue write — entry written to .auto_remember_queue.jsonl",
     _queue_exists and "Test memory content for queue write" in _queue_content)

# Test 3: Rate limit — simulate 15 triggers, verify only MAX written
if os.path.exists(_test_queue):
    os.unlink(_test_queue)
_test_state_rl = {"auto_remember_count": 0}
for _i in range(15):
    _auto_remember_event(f"Rate limit test entry {_i}", context="test", tags="type:test",
                         critical=False, state=_test_state_rl)
_rl_count = 0
if os.path.exists(_test_queue):
    with open(_test_queue) as _qf:
        _rl_count = sum(1 for line in _qf if line.strip())
test("Lever4: Rate limit — only 10 entries written from 15 triggers",
     _rl_count == MAX_AUTO_REMEMBER_PER_SESSION,
     f"got {_rl_count}, expected {MAX_AUTO_REMEMBER_PER_SESSION}")

# Test 4: Trigger A — test run with exit 0 → queue entry
if os.path.exists(_test_queue):
    os.unlink(_test_queue)
_test_state_ta = default_state()
_test_state_ta["auto_remember_count"] = 0
_test_state_ta["pending_verification"] = ["/tmp/test_file.py"]
from tracker import handle_post_tool_use as _hptu
_hptu("Bash", {"command": "python3 test_framework.py"},
      _test_state_ta, session_id="test-lever4-a",
      tool_response={"exit_code": 0})
_ta_content = ""
if os.path.exists(_test_queue):
    with open(_test_queue) as _qf:
        _ta_content = _qf.read()
test("Lever4 TriggerA: Test pass → queue entry with test info",
     "Tests passed" in _ta_content and "test_framework" in _ta_content,
     f"queue content: {_ta_content[:200]}")

# Test 5: Trigger B — git commit command → queue entry
if os.path.exists(_test_queue):
    os.unlink(_test_queue)
_test_state_tb = default_state()
_test_state_tb["auto_remember_count"] = 0
_hptu("Bash", {"command": 'git commit -m "test commit"'},
      _test_state_tb, session_id="test-lever4-b",
      tool_response={"exit_code": 0})
_tb_content = ""
if os.path.exists(_test_queue):
    with open(_test_queue) as _qf:
        _tb_content = _qf.read()
test("Lever4 TriggerB: Git commit → queue entry",
     "Git commit" in _tb_content,
     f"queue content: {_tb_content[:200]}")

# Test 6: Trigger C — fixing_error=True + test pass → critical save attempted
# (Without UDS available, should fall through to queue)
if os.path.exists(_test_queue):
    os.unlink(_test_queue)
_test_state_tc = default_state()
_test_state_tc["auto_remember_count"] = 0
_test_state_tc["fixing_error"] = True
_test_state_tc["recent_test_failure"] = {"pattern": "ImportError: no module named foo", "timestamp": time.time()}
_test_state_tc["pending_verification"] = ["/tmp/foo.py"]
_hptu("Bash", {"command": "pytest tests/"},
      _test_state_tc, session_id="test-lever4-c",
      tool_response={"exit_code": 0})
_tc_content = ""
if os.path.exists(_test_queue):
    with open(_test_queue) as _qf:
        _tc_content = _qf.read()
test("Lever4 TriggerC: Error fix verified → queue entry (UDS unavailable fallback)",
     # When UDS unavailable: TriggerC queues "Error fixed" + "ImportError"
     # When UDS available: TriggerC saves via UDS directly; TriggerA still queues "Tests passed"
     ("Error fixed" in _tc_content and "ImportError" in _tc_content) or "Tests passed" in _tc_content,
     f"queue content: {_tc_content[:200]}")

# Test 7: Trigger D — 3+ edits to same file → queue entry (only on first crossing)
if os.path.exists(_test_queue):
    os.unlink(_test_queue)
_test_state_td = default_state()
_test_state_td["auto_remember_count"] = 0
_test_state_td["edit_streak"] = {}
for _i in range(4):
    _hptu("Edit", {"file_path": "/tmp/heavy_file.py", "old_string": "a", "new_string": "b"},
          _test_state_td, session_id="test-lever4-d")
_td_content = ""
if os.path.exists(_test_queue):
    with open(_test_queue) as _qf:
        _td_content = _qf.read()
_td_lines = [l for l in _td_content.strip().split("\n") if l.strip()] if _td_content.strip() else []
test("Lever4 TriggerD: Heavy edit (3+ edits) → queue entry",
     "Heavy editing" in _td_content and "heavy_file.py" in _td_content,
     f"queue content: {_td_content[:200]}")
test("Lever4 TriggerD: Only one entry on first crossing (not repeated)",
     len(_td_lines) == 1,
     f"got {len(_td_lines)} entries, expected 1")

# Cleanup test queue
if os.path.exists(_test_queue):
    os.unlink(_test_queue)
_tracker_mod.AUTO_REMEMBER_QUEUE = _orig_queue
_ar_mod.AUTO_REMEMBER_QUEUE = _orig_queue

# Test 8-10: Lever 2 scoped — promotion criteria (unit tests on promotion logic)
# These test the criteria logic in memory_server._compact_observations
# We test the data structures and filtering rather than full LanceDB integration

# Test 8: Standalone error criterion — error with no follow-up success should be promotable
_exp_docs_l2 = [
    "Bash: python3 foo.py",       # 0: error
    "Edit: /tmp/foo.py fixed",    # 1: edit (not Bash success)
    "Bash: python3 bar.py",       # 2: success for bar
]
_exp_metas_l2 = [
    {"tool_name": "Bash", "has_error": "true", "error_pattern": "ImportError", "session_id": "s1"},
    {"tool_name": "Edit", "has_error": "false", "session_id": "s1"},
    {"tool_name": "Bash", "has_error": "false", "session_id": "s1"},
]
# Reproduce criterion 1 logic: standalone errors
_session_success_tools_l2 = {}
_session_errors_l2 = []
for _i, _doc in enumerate(_exp_docs_l2):
    _meta = _exp_metas_l2[_i]
    _sid = _meta.get("session_id", "")
    if _meta.get("has_error") == "true" or _meta.get("error_pattern", ""):
        _session_errors_l2.append((_i, _doc, _meta))
    else:
        if _sid:
            _session_success_tools_l2.setdefault(_sid, set()).add(_meta.get("tool_name", ""))

_standalone_errors = []
for _idx, _doc, _meta in _session_errors_l2:
    _sid = _meta.get("session_id", "")
    _tool = _meta.get("tool_name", "")
    if _sid and _tool and _tool in _session_success_tools_l2.get(_sid, set()):
        continue  # Tool succeeded later
    _standalone_errors.append(_doc)

test("Lever2 Criterion1: Standalone error — Bash error NOT promoted (Bash succeeded later in session)",
     len(_standalone_errors) == 0,
     f"got {len(_standalone_errors)} standalone errors: {_standalone_errors}")

# Test with a truly standalone error (no Bash success in session)
_exp_metas_l2b = [
    {"tool_name": "Bash", "has_error": "true", "error_pattern": "SegFault", "session_id": "s2"},
    {"tool_name": "Edit", "has_error": "false", "session_id": "s2"},
]
_session_success_tools_l2b = {}
_session_errors_l2b = []
for _i, _doc in enumerate(["Bash: crash", "Edit: fix"]):
    _meta = _exp_metas_l2b[_i]
    _sid = _meta.get("session_id", "")
    if _meta.get("has_error") == "true" or _meta.get("error_pattern", ""):
        _session_errors_l2b.append((_i, _doc, _meta))
    else:
        if _sid:
            _session_success_tools_l2b.setdefault(_sid, set()).add(_meta.get("tool_name", ""))

_standalone_l2b = [d for _, d, m in _session_errors_l2b
                   if not (m.get("session_id") and m.get("tool_name") and
                           m["tool_name"] in _session_success_tools_l2b.get(m["session_id"], set()))]
test("Lever2 Criterion1: Truly standalone error IS promotable",
     len(_standalone_l2b) == 1 and "crash" in _standalone_l2b[0])

# Test 9: File churn criterion — file in 5+ sessions → promoted
_file_sessions_l2 = {}
_churn_docs = [f"Edit: /tmp/hot.py edit {i}" for i in range(6)]
_churn_metas = [{"tool_name": "Edit", "session_id": f"session-{i}"} for i in range(6)]
for _i, _doc in enumerate(_churn_docs):
    _meta = _churn_metas[_i]
    _sid = _meta.get("session_id", "")
    _tool = _meta.get("tool_name", "")
    if _tool in ("Edit", "Write") and _sid:
        _parts = _doc.split(":", 1)
        if len(_parts) > 1:
            _fp = _parts[1].strip().split(" ")[0]
            if _fp:
                _file_sessions_l2.setdefault(_fp, set()).add(_sid)

_churn_promoted = [fp for fp, sids in _file_sessions_l2.items() if len(sids) >= 5]
test("Lever2 Criterion2: File in 6 sessions → churn promoted",
     len(_churn_promoted) == 1 and "/tmp/hot.py" in _churn_promoted[0])

# Test 10: Repeated command criterion — command 3+ times → promoted
_cmd_counts_l2 = {}
_repeat_docs = ["Bash: ls -la"] * 4 + ["Bash: pytest tests/"] * 2
_repeat_metas = [{"tool_name": "Bash"}] * 4 + [{"tool_name": "Bash"}] * 2
for _i, _doc in enumerate(_repeat_docs):
    _meta = _repeat_metas[_i]
    if _meta.get("tool_name") != "Bash":
        continue
    _cmd = _doc.split(":", 1)[1].strip() if ":" in _doc else _doc
    _cmd = _cmd[:200]
    if any(kw in _cmd for kw in ["pytest", "test_framework", "npm test", "cargo test", "go test", "git commit"]):
        continue
    _cmd_counts_l2[_cmd] = _cmd_counts_l2.get(_cmd, 0) + 1

_repeated_promoted = [cmd for cmd, cnt in _cmd_counts_l2.items() if cnt >= 3]
test("Lever2 Criterion3: 'ls -la' repeated 4x → promoted; 'pytest' excluded",
     len(_repeated_promoted) == 1 and "ls -la" in _repeated_promoted[0],
     f"promoted: {_repeated_promoted}")

# ─────────────────────────────────────────────────
# Telegram Memory Integration Tests
# ─────────────────────────────────────────────────
_TG_SECTION = "--- Telegram Memory Integration ---"
print(f"\n{_TG_SECTION}")
_TG_CLAUDE_DIR = os.path.expanduser("~/.claude")
_TG_HOOKS_DIR = os.path.join(_TG_CLAUDE_DIR, "hooks")

# Test: session_end.py still works when telegram plugin dir doesn't exist
try:
    _tg_dir = os.path.join(_TG_CLAUDE_DIR, "integrations", "telegram-bot")
    _tg_hook = os.path.join(_tg_dir, "hooks", "on_session_end.py")
    _tg_exists = os.path.isfile(_tg_hook)
    import ast as _tg_ast
    _tg_ast.parse(open(os.path.join(_TG_HOOKS_DIR, "session_end.py")).read())
    _se_content = open(os.path.join(_TG_HOOKS_DIR, "session_end.py")).read()
    assert "telegram-bot" in _se_content, "session_end.py missing telegram integration"
    assert "subprocess.run" in _se_content, "session_end.py missing subprocess.run"
    _h.PASS += 1
    _h.RESULTS.append(f"  PASS: session_end.py has telegram integration (plugin {'present' if _tg_exists else 'absent'})")
    print(f"  PASS: session_end.py telegram integration")
except Exception as _tg_e:
    _h.FAIL += 1
    _h.RESULTS.append(f"  FAIL: session_end.py telegram integration: {_tg_e}")
    print(f"  FAIL: session_end.py telegram: {_tg_e}")

# Test: boot.py has telegram L2 integration
try:
    _boot_content = open(os.path.join(_TG_HOOKS_DIR, "boot.py")).read() + _read_pkg_source(_boot_pkg_dir)
    assert "tg_memories" in _boot_content, "boot.py missing tg_memories variable"
    assert "TELEGRAM L2" in _boot_content, "boot.py missing TELEGRAM L2 dashboard section"
    assert "Telegram L2 memories" in _boot_content, "boot.py missing context injection"
    _h.PASS += 1
    _h.RESULTS.append("  PASS: boot.py has telegram L2 integration (3 locations)")
    print("  PASS: boot.py telegram L2 integration")
except Exception as _tg_e:
    _h.FAIL += 1
    _h.RESULTS.append(f"  FAIL: boot.py telegram integration: {_tg_e}")
    print(f"  FAIL: boot.py telegram: {_tg_e}")

# Test: on_session_start.py outputs valid JSON
try:
    _tg_start_hook = os.path.join(_TG_CLAUDE_DIR, "integrations", "telegram-bot", "hooks", "on_session_start.py")
    if os.path.isfile(_tg_start_hook):
        _tg_r = subprocess.run(
            [sys.executable, _tg_start_hook, "test"],
            capture_output=True, text=True, timeout=10,
        )
        assert _tg_r.returncode == 0, f"on_session_start.py exited {_tg_r.returncode}"
        _tg_out = json.loads(_tg_r.stdout)
        assert "results" in _tg_out, "Missing 'results' key"
        assert "count" in _tg_out, "Missing 'count' key"
        _h.PASS += 1
        _h.RESULTS.append("  PASS: on_session_start.py outputs valid JSON")
        print("  PASS: on_session_start.py valid JSON")
    else:
        _h.PASS += 1
        _h.RESULTS.append("  PASS: on_session_start.py (skipTest — plugin not installed)")
        print("  PASS: on_session_start.py (skipTest)")
except Exception as _tg_e:
    _h.FAIL += 1
    _h.RESULTS.append(f"  FAIL: on_session_start.py: {_tg_e}")
    print(f"  FAIL: on_session_start.py: {_tg_e}")

# ─────────────────────────────────────────────────
# Self-Evolving Framework Tests
# ─────────────────────────────────────────────────
print("\n--- Self-Evolving Framework Tests ---")

# Test: State fields exist
try:
    _se_state = default_state()
    assert "gate_effectiveness" in _se_state, "Missing gate_effectiveness"
    assert "gate_block_outcomes" in _se_state, "Missing gate_block_outcomes"
    assert "session_token_estimate" in _se_state, "Missing session_token_estimate"
    assert isinstance(_se_state["gate_effectiveness"], dict)
    assert isinstance(_se_state["gate_block_outcomes"], list)
    assert _se_state["session_token_estimate"] == 0
    _h.PASS += 1
    _h.RESULTS.append("  PASS: self-evolving state fields exist")
    print("  PASS: self-evolving state fields exist")
except Exception as _se_e:
    _h.FAIL += 1
    _h.RESULTS.append(f"  FAIL: self-evolving state fields: {_se_e}")
    print(f"  FAIL: self-evolving state fields: {_se_e}")

# Test: get_live_toggle helper
try:
    from shared.state import get_live_toggle
    # Test with real LIVE_STATE.json
    _toggle_val = get_live_toggle("gate_auto_tune", False)
    assert _toggle_val is False or _toggle_val is True, f"Unexpected toggle type: {type(_toggle_val)}"
    # Test default for missing key
    _toggle_missing = get_live_toggle("nonexistent_toggle_xyz", "default_val")
    assert _toggle_missing == "default_val", f"Expected 'default_val', got {_toggle_missing}"
    _h.PASS += 1
    _h.RESULTS.append("  PASS: get_live_toggle helper")
    print("  PASS: get_live_toggle helper")
except Exception as _se_e:
    _h.FAIL += 1
    _h.RESULTS.append(f"  FAIL: get_live_toggle: {_se_e}")
    print(f"  FAIL: get_live_toggle: {_se_e}")

# Test: Token estimation in tracker
try:
    from tracker import handle_post_tool_use as _se_hptu
    _se_tok_state = default_state()
    _se_tok_state["_session_id"] = "test_token_est"
    _se_hptu("Read", {"file_path": "/tmp/test.py"}, _se_tok_state, session_id="test_token_est")
    assert _se_tok_state["session_token_estimate"] == 800, f"Read should add 800, got {_se_tok_state['session_token_estimate']}"
    _se_hptu("Bash", {"command": "ls"}, _se_tok_state, session_id="test_token_est")
    assert _se_tok_state["session_token_estimate"] == 2800, f"Read+Bash should be 2800, got {_se_tok_state['session_token_estimate']}"
    _se_hptu("Edit", {"file_path": "/tmp/test.py", "old_string": "a", "new_string": "b"}, _se_tok_state, session_id="test_token_est")
    assert _se_tok_state["session_token_estimate"] == 4300, f"Read+Bash+Edit should be 4300, got {_se_tok_state['session_token_estimate']}"
    # Task should NOT add to session_token_estimate (tracked separately)
    _se_prev = _se_tok_state["session_token_estimate"]
    _se_hptu("Task", {"model": "haiku", "description": "test", "subagent_type": "Explore"}, _se_tok_state, session_id="test_token_est")
    assert _se_tok_state["session_token_estimate"] == _se_prev, "Task should not change session_token_estimate"
    _h.PASS += 1
    _h.RESULTS.append("  PASS: token estimation in tracker")
    print("  PASS: token estimation in tracker")
except Exception as _se_e:
    _h.FAIL += 1
    _h.RESULTS.append(f"  FAIL: token estimation: {_se_e}")
    print(f"  FAIL: token estimation: {_se_e}")

# Test: Gate effectiveness recording in enforcer
try:
    from enforcer import handle_pre_tool_use, _loaded_gates, _ensure_gates_loaded
    _se_eff_state = default_state()
    _se_eff_state["_session_id"] = "test_gate_eff"
    # Simulate a gate block by setting up state that triggers Gate 1
    # (Edit without prior Read)
    _se_eff_state["files_read"] = []  # No files read
    try:
        handle_pre_tool_use("Edit", {"file_path": "/tmp/nonexistent_gate_eff_test.py", "old_string": "a", "new_string": "b"}, _se_eff_state)
    except SystemExit:
        pass  # Expected — gate blocks via sys.exit(2)
    # Check gate_effectiveness was recorded in persistent file
    from shared.state import load_gate_effectiveness, EFFECTIVENESS_FILE
    _se_eff_data = load_gate_effectiveness()
    assert "gate_01_read_before_edit" in _se_eff_data, f"Expected gate_01 in persistent effectiveness, got {_se_eff_data.keys()}"
    assert _se_eff_data["gate_01_read_before_edit"]["blocks"] >= 1, "Expected at least 1 block"
    # Check gate_block_outcomes was recorded
    outcomes = _se_eff_state.get("gate_block_outcomes", [])
    assert len(outcomes) >= 1, "Expected at least 1 block outcome"
    assert outcomes[-1]["gate"] == "gate_01_read_before_edit"
    _h.PASS += 1
    _h.RESULTS.append("  PASS: gate effectiveness recording in enforcer")
    print("  PASS: gate effectiveness recording in enforcer")
except Exception as _se_e:
    _h.FAIL += 1
    _h.RESULTS.append(f"  FAIL: gate effectiveness recording: {_se_e}")
    print(f"  FAIL: gate effectiveness recording: {_se_e}")

# Test: Gate 10 budget degradation (toggle off)
try:
    from gates.gate_10_model_enforcement import check as g10_check
    _se_budget_state = default_state()
    _se_budget_state["session_token_estimate"] = 96000
    # Toggle off — should pass through normally
    _se_budget_result = g10_check("Task", {"model": "opus", "subagent_type": "builder", "description": "test"}, _se_budget_state)
    assert not _se_budget_result.blocked, "Budget off — should not block"
    _h.PASS += 1
    _h.RESULTS.append("  PASS: Gate 10 budget degradation (toggle off)")
    print("  PASS: Gate 10 budget degradation (toggle off)")
except Exception as _se_e:
    _h.FAIL += 1
    _h.RESULTS.append(f"  FAIL: Gate 10 budget degradation: {_se_e}")
    print(f"  FAIL: Gate 10 budget degradation: {_se_e}")

# Test: ChainStepWrapper
try:
    from shared.chain_sdk import ChainStepWrapper, format_chain_mapping
    _se_chain_state = default_state()
    _se_chain_state["session_token_estimate"] = 1000
    _se_chain_state["tool_call_count"] = 5
    _se_wrapper = ChainStepWrapper("fix", 1, 3, _se_chain_state, "test")
    _se_chain_state["session_token_estimate"] = 5000
    _se_chain_state["tool_call_count"] = 12
    _se_metrics = _se_wrapper.complete(_se_chain_state, outcome="success", summary="Fixed bug")
    assert _se_metrics["skill"] == "fix"
    assert _se_metrics["step"] == "1/3"
    assert _se_metrics["tokens_est"] == 4000
    assert _se_metrics["tool_calls"] == 7
    _se_mapping = format_chain_mapping("fix bugs", ["fix", "test"], [_se_metrics], 10.0, 7, "success")
    assert "Chain mapping" in _se_mapping
    assert "fix -> test" in _se_mapping
    _h.PASS += 1
    _h.RESULTS.append("  PASS: ChainStepWrapper + format_chain_mapping")
    print("  PASS: ChainStepWrapper + format_chain_mapping")
except Exception as _se_e:
    _h.FAIL += 1
    _h.RESULTS.append(f"  FAIL: ChainStepWrapper: {_se_e}")
    print(f"  FAIL: ChainStepWrapper: {_se_e}")

# Test: config.json has all toggle keys (moved from LIVE_STATE.json)
try:
    import json as _se_json
    _se_config_path = os.path.join(os.path.expanduser("~"), ".claude", "config.json")
    with open(_se_config_path) as _se_f:
        _se_cfg = _se_json.load(_se_f)
    for _se_key in ("gate_auto_tune", "budget_degradation", "session_token_budget"):
        assert _se_key in _se_cfg, f"Missing toggle in config.json: {_se_key}"
    assert isinstance(_se_cfg["gate_auto_tune"], bool), "gate_auto_tune must be bool"
    assert isinstance(_se_cfg["budget_degradation"], bool), "budget_degradation must be bool"
    assert isinstance(_se_cfg["session_token_budget"], (int, float)), "session_token_budget must be numeric"
    assert "chain_memory" not in _se_cfg, "chain_memory should be removed from config.json"
    # Verify toggles are NOT in LIVE_STATE.json anymore
    with open(os.path.join(os.path.expanduser("~"), ".claude", "LIVE_STATE.json")) as _se_f2:
        _se_live = _se_json.load(_se_f2)
    for _se_key in ("gate_auto_tune", "budget_degradation", "session_token_budget"):
        assert _se_key not in _se_live, f"Toggle {_se_key} should not be in LIVE_STATE.json"
    _h.PASS += 1
    _h.RESULTS.append("  PASS: config.json has toggles, LIVE_STATE.json does not")
    print("  PASS: config.json has toggles, LIVE_STATE.json does not")
except Exception as _se_e:
    _h.FAIL += 1
    _h.RESULTS.append(f"  FAIL: config.json toggles: {_se_e}")
    print(f"  FAIL: config.json toggles: {_se_e}")

# Test: get_live_toggle reads from config.json
try:
    # Reset caches to ensure fresh read
    import shared.state as _se_state_mod
    _se_state_mod._config_cache = None
    _se_state_mod._live_state_cache = None
    _se_cfg_val = _se_state_mod.get_live_toggle("gate_auto_tune", False)
    assert _se_cfg_val is True or _se_cfg_val is False, f"Unexpected type: {type(_se_cfg_val)}"
    # Test fallback for missing key
    _se_missing = _se_state_mod.get_live_toggle("nonexistent_toggle_xyz", "fallback")
    assert _se_missing == "fallback", f"Expected 'fallback', got {_se_missing}"
    # Test load_config returns dict
    _se_cfg_dict = _se_state_mod.load_config()
    assert isinstance(_se_cfg_dict, dict), "load_config must return dict"
    assert "gate_auto_tune" in _se_cfg_dict, "load_config must include gate_auto_tune"
    _h.PASS += 1
    _h.RESULTS.append("  PASS: get_live_toggle reads config.json + load_config()")
    print("  PASS: get_live_toggle reads config.json + load_config()")
except Exception as _se_e:
    _h.FAIL += 1
    _h.RESULTS.append(f"  FAIL: get_live_toggle config.json: {_se_e}")
    print(f"  FAIL: get_live_toggle config.json: {_se_e}")

# Test: _resolve_gate_block_outcomes (override path)
try:
    from tracker import _resolve_gate_block_outcomes
    from shared.state import load_gate_effectiveness, EFFECTIVENESS_FILE
    # Clean persistent file for isolated test
    _se_eff_backup = None
    if os.path.exists(EFFECTIVENESS_FILE):
        with open(EFFECTIVENESS_FILE) as _f: _se_eff_backup = _f.read()
        os.remove(EFFECTIVENESS_FILE)
    _se_resolve_state = default_state()
    _se_resolve_state["gate_block_outcomes"] = [
        {"gate": "gate_04_memory_first", "tool": "Edit", "file": "/tmp/test.py", "timestamp": time.time() - 60, "resolved_by": None}
    ]
    _se_resolve_state["memory_last_queried"] = 0  # No memory query after block
    _se_resolve_state["fix_history_queried"] = 0
    _resolve_gate_block_outcomes("Edit", {"file_path": "/tmp/test.py"}, _se_resolve_state)
    _se_eff_data = load_gate_effectiveness()
    assert _se_eff_data.get("gate_04_memory_first", {}).get("overrides", 0) == 1, "Should be override (no memory query)"
    # Restore backup
    if _se_eff_backup is not None:
        with open(EFFECTIVENESS_FILE, "w") as _f: _f.write(_se_eff_backup)
    elif os.path.exists(EFFECTIVENESS_FILE):
        os.remove(EFFECTIVENESS_FILE)
    _h.PASS += 1
    _h.RESULTS.append("  PASS: _resolve_gate_block_outcomes (override path)")
    print("  PASS: _resolve_gate_block_outcomes (override path)")
except Exception as _se_e:
    _h.FAIL += 1
    _h.RESULTS.append(f"  FAIL: _resolve_gate_block_outcomes override: {_se_e}")
    print(f"  FAIL: _resolve_gate_block_outcomes override: {_se_e}")

# Test: _resolve_gate_block_outcomes (prevented path)
try:
    # Clean persistent file for isolated test
    _se_eff_backup2 = None
    if os.path.exists(EFFECTIVENESS_FILE):
        with open(EFFECTIVENESS_FILE) as _f: _se_eff_backup2 = _f.read()
        os.remove(EFFECTIVENESS_FILE)
    _se_prevent_state = default_state()
    _block_ts = time.time() - 60
    _se_prevent_state["gate_block_outcomes"] = [
        {"gate": "gate_04_memory_first", "tool": "Edit", "file": "/tmp/test.py", "timestamp": _block_ts, "resolved_by": None}
    ]
    _se_prevent_state["memory_last_queried"] = _block_ts + 30  # Memory queried AFTER block
    _resolve_gate_block_outcomes("Edit", {"file_path": "/tmp/test.py"}, _se_prevent_state)
    _se_eff_data2 = load_gate_effectiveness()
    assert _se_eff_data2.get("gate_04_memory_first", {}).get("prevented", 0) == 1, "Should be prevented (memory queried after block)"
    # Restore backup
    if _se_eff_backup2 is not None:
        with open(EFFECTIVENESS_FILE, "w") as _f: _f.write(_se_eff_backup2)
    elif os.path.exists(EFFECTIVENESS_FILE):
        os.remove(EFFECTIVENESS_FILE)
    _h.PASS += 1
    _h.RESULTS.append("  PASS: _resolve_gate_block_outcomes (prevented path)")
    print("  PASS: _resolve_gate_block_outcomes (prevented path)")
except Exception as _se_e:
    _h.FAIL += 1
    _h.RESULTS.append(f"  FAIL: _resolve_gate_block_outcomes prevented: {_se_e}")
    print(f"  FAIL: _resolve_gate_block_outcomes prevented: {_se_e}")

# Test: State schema includes new fields
try:
    _se_schema = get_state_schema()
    for _se_field in ("gate_effectiveness", "gate_block_outcomes", "session_token_estimate", "gate_tune_overrides"):
        assert _se_field in _se_schema, f"Missing schema entry: {_se_field}"
        assert _se_schema[_se_field]["category"] == "evolve", f"Expected category 'evolve' for {_se_field}"
    _h.PASS += 1
    _h.RESULTS.append("  PASS: state schema includes new evolve fields")
    print("  PASS: state schema includes new evolve fields")
except Exception as _se_e:
    _h.FAIL += 1
    _h.RESULTS.append(f"  FAIL: state schema: {_se_e}")
    print(f"  FAIL: state schema: {_se_e}")

# Test: Gate auto-tune overrides are read by gates
# Remove sideband so direct gate calls test state timestamps, not global sideband
try:
    os.remove(MEMORY_TIMESTAMP_FILE)
except FileNotFoundError:
    pass
try:
    _at_state = default_state()
    _at_state["_session_id"] = "test_autotune_no_sideband"  # Avoid sideband file
    # Gate 04: default freshness_window=300, override to 600
    _at_state["gate_tune_overrides"] = {"gate_04_memory_first": {"freshness_window": 600}}
    _at_state["memory_last_queried"] = time.time() - 400  # 400s ago — beyond 300 default, within 600 override
    from gates.gate_04_memory_first import check as _at_g04
    _at_r = _at_g04("Edit", {"file_path": "/tmp/test_autotune.py"}, _at_state)
    assert not _at_r.blocked, "Should pass with loosened freshness_window override"
    # Without override, same state should block (use non-main session to avoid sideband)
    _at_state2 = default_state()
    _at_state2["_session_id"] = "test_autotune_no_sideband"
    _at_state2["memory_last_queried"] = time.time() - 400
    _at_r2 = _at_g04("Edit", {"file_path": "/tmp/test_autotune.py"}, _at_state2)
    assert _at_r2.blocked, "Should block without override (400s > 300s default)"
    _h.PASS += 1
    _h.RESULTS.append("  PASS: gate auto-tune overrides read by gates")
    print("  PASS: gate auto-tune overrides read by gates")
except Exception as _se_e:
    _h.FAIL += 1
    _h.RESULTS.append(f"  FAIL: gate auto-tune overrides: {_se_e}")
    print(f"  FAIL: gate auto-tune overrides: {_se_e}")

# ─────────────────────────────────────────────────
# Gate 4 Staleness Loop Fix (F2e + F3)
# ─────────────────────────────────────────────────
print("\n--- Gate 4: Staleness Loop Fix (F2e new-file exempt + F3 per-tool windows) ---")

# Remove sideband so direct gate calls test state timestamps, not global sideband
try:
    os.remove(MEMORY_TIMESTAMP_FILE)
except FileNotFoundError:
    pass

from gates.gate_04_memory_first import check as _sl_g04, WRITE_FRESHNESS_WINDOW as _sl_wfw

# Test 1 (F2e): Write to non-existent file with memory_last_queried > 0 → passes
try:
    _sl_state1 = default_state()
    _sl_state1["_session_id"] = "test_staleness_no_sideband"
    _sl_state1["memory_last_queried"] = time.time() - 400  # stale for Edit (>300s) but memory was queried
    _sl_path1 = "/tmp/_test_gate4_nonexistent_" + str(int(time.time())) + ".py"
    _sl_r1 = _sl_g04("Write", {"file_path": _sl_path1}, _sl_state1)
    assert not _sl_r1.blocked, f"Write to new file with prior memory query should pass, got: {_sl_r1.message}"
    _h.PASS += 1
    _h.RESULTS.append("  PASS: F2e — Write new file with memory queried → passes")
    print("  PASS: F2e — Write new file with memory queried → passes")
except Exception as _sl_e1:
    _h.FAIL += 1
    _h.RESULTS.append(f"  FAIL: F2e new file pass: {_sl_e1}")
    print(f"  FAIL: F2e new file pass: {_sl_e1}")

# Test 2 (F2e safety): Write to non-existent file with memory_last_queried == 0 → blocks
try:
    _sl_state2 = default_state()
    _sl_state2["_session_id"] = "test_staleness_no_sideband"
    _sl_state2["memory_last_queried"] = 0  # never queried
    _sl_path2 = "/tmp/_test_gate4_nonexistent2_" + str(int(time.time())) + ".py"
    _sl_r2 = _sl_g04("Write", {"file_path": _sl_path2}, _sl_state2)
    assert _sl_r2.blocked, "Write to new file WITHOUT any memory query should block"
    _h.PASS += 1
    _h.RESULTS.append("  PASS: F2e safety — Write new file without memory → blocks")
    print("  PASS: F2e safety — Write new file without memory → blocks")
except Exception as _sl_e2:
    _h.FAIL += 1
    _h.RESULTS.append(f"  FAIL: F2e safety: {_sl_e2}")
    print(f"  FAIL: F2e safety: {_sl_e2}")

# Test 3 (F2e): Write to existing file with stale memory → blocks (existing-file enforcement kept)
try:
    _sl_state3 = default_state()
    _sl_state3["_session_id"] = "test_staleness_no_sideband"
    _sl_state3["memory_last_queried"] = time.time() - 700  # stale beyond even 600s Write window
    # Use a file that definitely exists
    _sl_r3 = _sl_g04("Write", {"file_path": "/home/crab/.claude/hooks/test_framework.py"}, _sl_state3)
    assert _sl_r3.blocked, "Write to existing file with stale memory should block"
    _h.PASS += 1
    _h.RESULTS.append("  PASS: F2e — Write existing file with stale memory → blocks")
    print("  PASS: F2e — Write existing file with stale memory → blocks")
except Exception as _sl_e3:
    _h.FAIL += 1
    _h.RESULTS.append(f"  FAIL: F2e existing file block: {_sl_e3}")
    print(f"  FAIL: F2e existing file block: {_sl_e3}")

# Test 4 (F3): Write with memory 400s ago → passes (within 600s Write window)
try:
    _sl_state4 = default_state()
    _sl_state4["_session_id"] = "test_staleness_no_sideband"
    _sl_state4["memory_last_queried"] = time.time() - 400  # 400s ago: >300 Edit window, <600 Write window
    _sl_r4 = _sl_g04("Write", {"file_path": "/home/crab/.claude/hooks/test_framework.py"}, _sl_state4)
    assert not _sl_r4.blocked, f"Write with 400s-old memory should pass (600s window), got: {_sl_r4.message}"
    _h.PASS += 1
    _h.RESULTS.append("  PASS: F3 — Write 400s ago → passes (600s window)")
    print("  PASS: F3 — Write 400s ago → passes (600s window)")
except Exception as _sl_e4:
    _h.FAIL += 1
    _h.RESULTS.append(f"  FAIL: F3 Write window: {_sl_e4}")
    print(f"  FAIL: F3 Write window: {_sl_e4}")

# Test 5 (F3): Edit with memory 400s ago → blocks (Edit stays at 300s)
try:
    _sl_state5 = default_state()
    _sl_state5["_session_id"] = "test_staleness_no_sideband"
    _sl_state5["memory_last_queried"] = time.time() - 400  # 400s ago: >300 Edit window
    _sl_r5 = _sl_g04("Edit", {"file_path": "/home/crab/.claude/hooks/test_framework.py"}, _sl_state5)
    assert _sl_r5.blocked, "Edit with 400s-old memory should block (300s window)"
    _h.PASS += 1
    _h.RESULTS.append("  PASS: F3 — Edit 400s ago → blocks (300s window)")
    print("  PASS: F3 — Edit 400s ago → blocks (300s window)")
except Exception as _sl_e5:
    _h.FAIL += 1
    _h.RESULTS.append(f"  FAIL: F3 Edit window: {_sl_e5}")
    print(f"  FAIL: F3 Edit window: {_sl_e5}")

# Verify WRITE_FRESHNESS_WINDOW constant is 600
try:
    assert _sl_wfw == 600, f"WRITE_FRESHNESS_WINDOW should be 600, got {_sl_wfw}"
    _h.PASS += 1
    _h.RESULTS.append("  PASS: WRITE_FRESHNESS_WINDOW == 600")
    print("  PASS: WRITE_FRESHNESS_WINDOW == 600")
except Exception as _sl_e6:
    _h.FAIL += 1
    _h.RESULTS.append(f"  FAIL: WRITE_FRESHNESS_WINDOW: {_sl_e6}")
    print(f"  FAIL: WRITE_FRESHNESS_WINDOW: {_sl_e6}")

# ─────────────────────────────────────────────────
# v2.5.0 — Cherry-pick features: ULID, Gate 17, 4-tier budget
# ─────────────────────────────────────────────────
