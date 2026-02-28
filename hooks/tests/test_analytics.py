#!/usr/bin/env python3
# Mentor, Analytics MCP, Session Analytics, Extended Metrics
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
import tests.harness as _h

print('\n--- Mentor System: Tracker Mentor (A) ---')

try:
    from tracker_pkg.mentor import Signal, MentorVerdict, evaluate as mentor_evaluate
    from tracker_pkg.mentor import _eval_bash, _eval_edit, _eval_search, _eval_progress
    from tracker_pkg.mentor import _compute_verdict

    # Signal dataclass construction
    _ms1 = Signal("test_pass", 1.0, 2.0, "Tests passed")
    test("Mentor: Signal construction",
         _ms1.name == "test_pass" and _ms1.value == 1.0 and _ms1.weight == 2.0,
         f"got name={_ms1.name} value={_ms1.value}")

    # MentorVerdict construction
    _mv1 = MentorVerdict("proceed", 0.85, [_ms1], "All good")
    test("Mentor: MentorVerdict construction",
         _mv1.action == "proceed" and _mv1.score == 0.85,
         f"got action={_mv1.action} score={_mv1.score}")

    # _eval_bash: test pass
    _bash_signals = _eval_bash("Bash", {"command": "pytest tests/"}, {"exit_code": 0},
                               {"error_pattern_counts": {}, "edit_streak": {}})
    test("Mentor: _eval_bash test pass signal",
         any(s.name == "test_pass" and s.value == 1.0 for s in _bash_signals),
         f"signals={[(s.name, s.value) for s in _bash_signals]}")

    # _eval_bash: test fail
    _bash_fail = _eval_bash("Bash", {"command": "pytest tests/"}, {"exit_code": 1},
                            {"error_pattern_counts": {}, "edit_streak": {}})
    test("Mentor: _eval_bash test fail signal",
         any(s.name == "test_fail" and s.value == 0.0 for s in _bash_fail),
         f"signals={[(s.name, s.value) for s in _bash_fail]}")

    # _eval_bash: error loop detection
    _bash_errloop = _eval_bash("Bash", {"command": "ls"}, {},
                               {"error_pattern_counts": {"ImportError": 4}, "edit_streak": {}})
    test("Mentor: _eval_bash error loop detection",
         any(s.name == "error_loop" for s in _bash_errloop),
         f"signals={[(s.name, s.value) for s in _bash_errloop]}")

    # _eval_bash: verification quality weak
    _bash_weak = _eval_bash("Bash", {"command": "ls -la"}, {},
                            {"error_pattern_counts": {}, "edit_streak": {}})
    test("Mentor: _eval_bash weak verification",
         any(s.name == "verification_quality" and s.value == 0.1 for s in _bash_weak),
         f"signals={[(s.name, s.value) for s in _bash_weak]}")

    # _eval_bash: verification quality strong
    _bash_strong = _eval_bash("Bash", {"command": "python3 test_framework.py"}, {},
                              {"error_pattern_counts": {}, "edit_streak": {}})
    test("Mentor: _eval_bash strong verification",
         any(s.name == "verification_quality" and s.value == 1.0 for s in _bash_strong),
         f"signals={[(s.name, s.value) for s in _bash_strong]}")

    # _eval_bash: non-Bash returns empty
    _bash_skip = _eval_bash("Edit", {}, {}, {})
    test("Mentor: _eval_bash skips non-Bash", len(_bash_skip) == 0, f"got {len(_bash_skip)}")

    # _eval_edit: churn detection
    _edit_churn = _eval_edit("Edit", {"file_path": "/tmp/foo.py", "old_string": "a", "new_string": "b"}, {},
                             {"edit_streak": {"/tmp/foo.py": 6}})
    test("Mentor: _eval_edit churn detection",
         any(s.name == "edit_churn" for s in _edit_churn),
         f"signals={[(s.name, s.value) for s in _edit_churn]}")

    # _eval_edit: no churn below threshold
    _edit_nochurn = _eval_edit("Edit", {"file_path": "/tmp/foo.py"}, {},
                               {"edit_streak": {"/tmp/foo.py": 2}})
    test("Mentor: _eval_edit no churn below threshold",
         not any(s.name == "edit_churn" for s in _edit_nochurn),
         f"signals={[(s.name, s.value) for s in _edit_nochurn]}")

    # _eval_edit: revert detection
    _edit_revert = _eval_edit("Edit", {"file_path": "/tmp/foo.py", "old_string": "x" * 100, "new_string": "y"},
                              {}, {"edit_streak": {}})
    test("Mentor: _eval_edit revert detection",
         any(s.name == "possible_revert" for s in _edit_revert),
         f"signals={[(s.name, s.value) for s in _edit_revert]}")

    # _eval_edit: large edit
    _edit_large = _eval_edit("Edit", {"file_path": "/tmp/foo.py", "old_string": "x" * 600, "new_string": "y" * 600},
                             {}, {"edit_streak": {}})
    test("Mentor: _eval_edit large edit advisory",
         any(s.name == "large_edit" for s in _edit_large),
         f"signals={[(s.name, s.value) for s in _edit_large]}")

    # _eval_edit: non-edit returns empty
    _edit_skip = _eval_edit("Bash", {}, {}, {})
    test("Mentor: _eval_edit skips non-edit", len(_edit_skip) == 0, f"got {len(_edit_skip)}")

    # _eval_search: empty results
    _search_empty = _eval_search("Grep", {}, "", {"mentor_signals": []})
    test("Mentor: _eval_search empty results",
         any(s.name == "empty_search" for s in _search_empty),
         f"signals={[(s.name, s.value) for s in _search_empty]}")

    # _eval_search: non-empty results
    _search_ok = _eval_search("Grep", {}, "found: 5 matches", {"mentor_signals": []})
    test("Mentor: _eval_search non-empty results",
         not any(s.name == "empty_search" for s in _search_ok),
         f"signals={[(s.name, s.value) for s in _search_ok]}")

    # _eval_search: stuck detection (3+ empties in a row)
    _search_stuck = _eval_search("Grep", {}, "", {
        "mentor_signals": [
            {"name": "empty_search", "value": 0.4},
            {"name": "empty_search", "value": 0.4},
        ]
    })
    test("Mentor: _eval_search stuck detection",
         any(s.name == "search_stuck" for s in _search_stuck),
         f"signals={[(s.name, s.value) for s in _search_stuck]}")

    # _eval_search: non-search returns empty
    _search_skip = _eval_search("Bash", {}, {}, {})
    test("Mentor: _eval_search skips non-search", len(_search_skip) == 0, f"got {len(_search_skip)}")

    # _eval_progress: fires every 10th call
    _prog_skip = _eval_progress("Bash", {}, {}, {"tool_call_count": 7})
    test("Mentor: _eval_progress skips non-10th call", len(_prog_skip) == 0, f"got {len(_prog_skip)}")

    # _compute_verdict: proceed threshold
    _v_proceed = _compute_verdict([Signal("test_pass", 1.0, 2.0, "ok")])
    test("Mentor: verdict proceed (score >= 0.7)",
         _v_proceed.action == "proceed" and _v_proceed.score >= 0.7,
         f"action={_v_proceed.action} score={_v_proceed.score}")

    # _compute_verdict: warn threshold
    _v_warn = _compute_verdict([Signal("churn", 0.3, 2.0, "bad"), Signal("ok", 0.5, 1.0, "meh")])
    test("Mentor: verdict warn (0.3 <= score < 0.5)",
         _v_warn.action == "warn",
         f"action={_v_warn.action} score={_v_warn.score:.2f}")

    # _compute_verdict: escalate threshold
    _v_escalate = _compute_verdict([Signal("fail", 0.0, 3.0, "total fail"), Signal("loop", 0.1, 2.0, "stuck")])
    test("Mentor: verdict escalate (score < 0.3)",
         _v_escalate.action == "escalate" and _v_escalate.score < 0.3,
         f"action={_v_escalate.action} score={_v_escalate.score:.2f}")

    # _compute_verdict: empty signals = proceed
    _v_empty = _compute_verdict([])
    test("Mentor: empty signals = proceed",
         _v_empty.action == "proceed" and _v_empty.score == 1.0,
         f"action={_v_empty.action}")

    # evaluate: state updates
    _eval_state = {"tool_call_count": 1, "error_pattern_counts": {}, "edit_streak": {},
                   "mentor_signals": [], "mentor_escalation_count": 0}
    _eval_v = mentor_evaluate("Bash", {"command": "pytest"}, {"exit_code": 0}, _eval_state)
    test("Mentor: evaluate updates state mentor_last_verdict",
         _eval_state.get("mentor_last_verdict") == "proceed",
         f"got {_eval_state.get('mentor_last_verdict')}")
    test("Mentor: evaluate updates state mentor_last_score",
         _eval_state.get("mentor_last_score", 0) >= 0.7,
         f"got {_eval_state.get('mentor_last_score')}")

    # evaluate: escalation counter increments
    _esc_state = {"tool_call_count": 1, "error_pattern_counts": {"err": 5}, "edit_streak": {},
                  "mentor_signals": [], "mentor_escalation_count": 0}
    _esc_v = mentor_evaluate("Bash", {"command": "pytest"}, {"exit_code": 1}, _esc_state)
    test("Mentor: escalation counter increments on escalate",
         _esc_state.get("mentor_escalation_count", 0) >= 1 if _esc_v and _esc_v.action == "escalate" else True,
         f"count={_esc_state.get('mentor_escalation_count')} action={_esc_v.action if _esc_v else 'None'}")

    # evaluate: escalation counter resets on proceed
    _reset_state = {"tool_call_count": 1, "error_pattern_counts": {}, "edit_streak": {},
                    "mentor_signals": [], "mentor_escalation_count": 5}
    _reset_v = mentor_evaluate("Bash", {"command": "pytest"}, {"exit_code": 0}, _reset_state)
    test("Mentor: escalation counter resets on proceed",
         _reset_state.get("mentor_escalation_count") == 0,
         f"count={_reset_state.get('mentor_escalation_count')}")

    # evaluate: fail-open (bad state — None state is handled gracefully, no crash)
    _fo_result = mentor_evaluate("Bash", None, None, None)
    test("Mentor: evaluate fail-open on bad input",
         _fo_result is None or isinstance(_fo_result, MentorVerdict),
         f"got {_fo_result}")

except Exception as _mentor_e:
    _h.FAIL += 1
    _h.RESULTS.append(f"  FAIL: Mentor Tracker (A) tests: {_mentor_e}")
    print(f"  FAIL: Mentor Tracker (A) tests: {_mentor_e}")

print('\n--- Mentor System: Hindsight Gate (B) ---')

try:
    from gates.gate_19_hindsight import check as g19_check, GATE_NAME as G19_NAME, WATCHED_TOOLS as G19_TOOLS
    from shared.gate_registry import GATE_MODULES as _g19_reg
    from shared.gate_router import GATE_TOOL_MAP as _g19_router
    from enforcer import GATE_TOOL_MAP as _g19_enforcer, GATE_DEPENDENCIES as _g19_deps

    # 3-point registration
    test("Gate 19: registered in gate_registry",
         "gates.gate_19_hindsight" in _g19_reg,
         f"modules={_g19_reg}")
    test("Gate 19: registered in gate_router",
         "gates.gate_19_hindsight" in _g19_router,
         f"keys={list(_g19_router.keys())}")
    test("Gate 19: registered in enforcer GATE_TOOL_MAP",
         "gates.gate_19_hindsight" in _g19_enforcer,
         f"keys={list(_g19_enforcer.keys())}")
    test("Gate 19: registered in enforcer GATE_DEPENDENCIES",
         "gate_19_hindsight" in _g19_deps,
         f"keys={list(_g19_deps.keys())}")

    # Watches correct tools
    test("Gate 19: watches Edit/Write/NotebookEdit",
         G19_TOOLS == {"Edit", "Write", "NotebookEdit"},
         f"got {G19_TOOLS}")

    # Skips non-PreToolUse
    _g19r1 = g19_check("Edit", {"file_path": "/tmp/foo.py"}, {}, event_type="PostToolUse")
    test("Gate 19: skips non-PreToolUse", not _g19r1.blocked, f"blocked={_g19r1.blocked}")

    # Skips non-watched tools
    _g19r2 = g19_check("Bash", {"command": "ls"}, {}, event_type="PreToolUse")
    test("Gate 19: skips non-watched tools", not _g19r2.blocked, f"blocked={_g19r2.blocked}")

    # Skips when toggle is off (patch get_live_toggle to return False for all mentor toggles)
    import gates.gate_19_hindsight as _g19_mod
    _g19_orig_toggle = _g19_mod.get_live_toggle
    _g19_mod.get_live_toggle = lambda key, *a, **kw: False
    _g19r3 = g19_check("Edit", {"file_path": "/tmp/foo.py"}, {
        "mentor_last_score": 0.1, "mentor_escalation_count": 5
    }, event_type="PreToolUse")
    _g19_mod.get_live_toggle = _g19_orig_toggle
    test("Gate 19: skips when toggle off", not _g19r3.blocked, f"blocked={_g19r3.blocked}")

    # Skips when fixing_error == True (Gate 15 territory)
    _g19r4 = g19_check("Edit", {"file_path": "/tmp/foo.py"}, {
        "fixing_error": True, "mentor_last_score": 0.1, "mentor_escalation_count": 5
    }, event_type="PreToolUse")
    test("Gate 19: skips when fixing_error=True", not _g19r4.blocked, f"blocked={_g19r4.blocked}")

    # Skips exempt files (test files)
    _g19r5 = g19_check("Edit", {"file_path": "/tmp/test_foo.py"}, {
        "mentor_last_score": 0.1, "mentor_escalation_count": 5
    }, event_type="PreToolUse")
    test("Gate 19: skips exempt test files", not _g19r5.blocked, f"blocked={_g19r5.blocked}")

    # Does not read Gate 5 fields (pending_verification, edit_streak)
    _g19_dep_reads = _g19_deps.get("gate_19_hindsight", {}).get("reads", [])
    test("Gate 19: never reads pending_verification",
         "pending_verification" not in _g19_dep_reads,
         f"reads={_g19_dep_reads}")
    test("Gate 19: never reads edit_streak",
         "edit_streak" not in _g19_dep_reads,
         f"reads={_g19_dep_reads}")

    # Does not read Gate 15 fields for decisions (only reads fixing_error to SKIP)
    test("Gate 19: reads fixing_error only to skip",
         "fixing_error" in _g19_dep_reads,
         f"reads={_g19_dep_reads}")
    test("Gate 19: never reads fix_history_queried",
         "fix_history_queried" not in _g19_dep_reads,
         f"reads={_g19_dep_reads}")
    test("Gate 19: never reads recent_test_failure",
         "recent_test_failure" not in _g19_dep_reads,
         f"reads={_g19_dep_reads}")

    # Gate 19 writes nothing
    _g19_dep_writes = _g19_deps.get("gate_19_hindsight", {}).get("writes", [])
    test("Gate 19: writes no state fields",
         len(_g19_dep_writes) == 0,
         f"writes={_g19_dep_writes}")

    # Gate 19 before Gate 11 (rate limit always last)
    _g19_idx = _g19_reg.index("gates.gate_19_hindsight")
    _g11_idx = _g19_reg.index("gates.gate_11_rate_limit")
    test("Gate 19: before Gate 11 in registry",
         _g19_idx < _g11_idx,
         f"g19_idx={_g19_idx} g11_idx={_g11_idx}")

except Exception as _g19_e:
    _h.FAIL += 1
    _h.RESULTS.append(f"  FAIL: Hindsight Gate (B) tests: {_g19_e}")
    print(f"  FAIL: Hindsight Gate (B) tests: {_g19_e}")

print('\n--- Mentor System: Outcome Chains (D) ---')

try:
    from tracker_pkg.outcome_chains import evaluate as chains_evaluate

    # Fires only every 10th call
    _oc_skip = chains_evaluate("Bash", {}, {}, {"tool_call_count": 7, "tool_call_counts": {}, "total_tool_calls": 20})
    test("Chains: skips non-10th call", _oc_skip is None, f"got {_oc_skip}")

    # Fires on 10th call
    _oc_state10 = {"tool_call_count": 10, "tool_call_counts": {"Read": 5, "Edit": 3, "Bash": 2}, "total_tool_calls": 10}
    _oc_fire = chains_evaluate("Bash", {}, {}, _oc_state10)
    test("Chains: fires on 10th call", _oc_fire is not None, f"got {_oc_fire}")

    # Stuck loop detection
    _oc_stuck_state = {"tool_call_count": 20, "tool_call_counts": {"Edit": 18, "Read": 2}, "total_tool_calls": 20}
    _oc_stuck = chains_evaluate("Edit", {}, {}, _oc_stuck_state)
    test("Chains: stuck loop detection",
         _oc_stuck is not None and _oc_stuck.get("pattern") == "stuck",
         f"got {_oc_stuck}")
    test("Chains: stuck loop score <= 0.3",
         _oc_stuck is not None and _oc_stuck.get("score", 1.0) <= 0.3,
         f"score={_oc_stuck.get('score') if _oc_stuck else 'None'}")

    # Churn detection (Edit=10/20=50%, Write=3 -> combined edit_ratio=65% > 60%, Bash=2 < 13*0.3=3.9 -> churn)
    _oc_churn_state = {"tool_call_count": 20, "tool_call_counts": {"Edit": 10, "Write": 3, "Bash": 2, "Read": 5}, "total_tool_calls": 20}
    _oc_churn = chains_evaluate("Edit", {}, {}, _oc_churn_state)
    test("Chains: churn detection",
         _oc_churn is not None and _oc_churn.get("pattern") == "churn",
         f"got {_oc_churn}")

    # Healthy pattern
    _oc_healthy_state = {"tool_call_count": 30, "tool_call_counts": {"Read": 10, "Edit": 8, "Bash": 7, "Grep": 5}, "total_tool_calls": 30}
    _oc_healthy = chains_evaluate("Bash", {}, {}, _oc_healthy_state)
    test("Chains: healthy pattern detection",
         _oc_healthy is not None and _oc_healthy.get("pattern") == "healthy",
         f"got {_oc_healthy}")
    test("Chains: healthy score >= 0.8",
         _oc_healthy is not None and _oc_healthy.get("score", 0) >= 0.8,
         f"score={_oc_healthy.get('score') if _oc_healthy else 'None'}")

    # State updates
    _oc_update_state = {"tool_call_count": 10, "tool_call_counts": {"Read": 5, "Edit": 3, "Bash": 2}, "total_tool_calls": 10}
    chains_evaluate("Bash", {}, {}, _oc_update_state)
    test("Chains: updates mentor_chain_pattern in state",
         "mentor_chain_pattern" in _oc_update_state,
         f"keys={list(_oc_update_state.keys())}")
    test("Chains: updates mentor_chain_score in state",
         "mentor_chain_score" in _oc_update_state,
         f"keys={list(_oc_update_state.keys())}")

    # Skips when too few calls
    _oc_low = chains_evaluate("Bash", {}, {}, {"tool_call_count": 10, "tool_call_counts": {"Read": 3}, "total_tool_calls": 5})
    test("Chains: skips when total < 10", _oc_low is None, f"got {_oc_low}")

except Exception as _oc_e:
    _h.FAIL += 1
    _h.RESULTS.append(f"  FAIL: Outcome Chains (D) tests: {_oc_e}")
    print(f"  FAIL: Outcome Chains (D) tests: {_oc_e}")

print('\n--- Mentor System: Memory Mentor (E) ---')

try:
    from tracker_pkg.mentor_memory import evaluate as mem_evaluate, _extract_query_context, _query_uds

    # Standalone: no dependency on Module A
    _mm_result = mem_evaluate("Bash", {"command": "pytest"}, {}, {"recent_test_failure": None, "current_strategy_id": ""})
    test("MemMentor: standalone operation (no Module A dependency)",
         _mm_result is None,  # No UDS socket in test = None
         f"got {_mm_result}")

    # Fail-open: handles missing UDS socket gracefully
    _mm_uds = _query_uds("test query", n_results=1)
    test("MemMentor: fail-open when UDS socket missing",
         _mm_uds is None,
         f"got {_mm_uds}")

    # Context extraction: error pattern
    _mm_ctx1 = _extract_query_context("Bash", {}, {}, {"recent_test_failure": {"pattern": "ImportError"}, "current_strategy_id": ""})
    test("MemMentor: extracts error pattern context",
         "ImportError" in _mm_ctx1,
         f"got '{_mm_ctx1}'")

    # Context extraction: file path
    _mm_ctx2 = _extract_query_context("Edit", {"file_path": "/home/test/foo.py"}, {}, {"recent_test_failure": None, "current_strategy_id": ""})
    test("MemMentor: extracts file path context",
         "foo.py" in _mm_ctx2,
         f"got '{_mm_ctx2}'")

    # Context extraction: command
    _mm_ctx3 = _extract_query_context("Bash", {"command": "pytest tests/test_auth.py"}, {}, {"recent_test_failure": None, "current_strategy_id": ""})
    test("MemMentor: extracts command context",
         "pytest" in _mm_ctx3,
         f"got '{_mm_ctx3}'")

    # Context extraction: strategy
    _mm_ctx4 = _extract_query_context("Edit", {}, {}, {"recent_test_failure": None, "current_strategy_id": "fix-type-cast"})
    test("MemMentor: extracts strategy context",
         "fix-type-cast" in _mm_ctx4,
         f"got '{_mm_ctx4}'")

    # Context extraction: empty = empty string
    _mm_ctx5 = _extract_query_context("Read", {}, {}, {"recent_test_failure": None, "current_strategy_id": ""})
    test("MemMentor: empty context returns empty string",
         _mm_ctx5 == "",
         f"got '{_mm_ctx5}'")

    # Fail-open with bad state
    _mm_bad = mem_evaluate("Bash", None, None, None)
    test("MemMentor: fail-open on bad state", _mm_bad is None, f"got {_mm_bad}")

except Exception as _mm_e:
    _h.FAIL += 1
    _h.RESULTS.append(f"  FAIL: Memory Mentor (E) tests: {_mm_e}")
    print(f"  FAIL: Memory Mentor (E) tests: {_mm_e}")

print('\n--- Mentor System: Integration ---')

try:
    from shared.state import default_state as _mentor_default_state, get_state_schema as _mentor_schema

    _mds = _mentor_default_state()

    # State defaults present
    test("Mentor integration: mentor_last_verdict in default_state",
         "mentor_last_verdict" in _mds and _mds["mentor_last_verdict"] == "proceed",
         f"got {_mds.get('mentor_last_verdict')}")
    test("Mentor integration: mentor_last_score in default_state",
         "mentor_last_score" in _mds and _mds["mentor_last_score"] == 1.0,
         f"got {_mds.get('mentor_last_score')}")
    test("Mentor integration: mentor_escalation_count in default_state",
         "mentor_escalation_count" in _mds and _mds["mentor_escalation_count"] == 0,
         f"got {_mds.get('mentor_escalation_count')}")
    test("Mentor integration: mentor_signals in default_state",
         "mentor_signals" in _mds and _mds["mentor_signals"] == [],
         f"got {_mds.get('mentor_signals')}")
    test("Mentor integration: mentor_warned_this_cycle in default_state",
         "mentor_warned_this_cycle" in _mds and _mds["mentor_warned_this_cycle"] == False,
         f"got {_mds.get('mentor_warned_this_cycle')}")
    test("Mentor integration: mentor_chain_pattern in default_state",
         "mentor_chain_pattern" in _mds and _mds["mentor_chain_pattern"] == "",
         f"got {_mds.get('mentor_chain_pattern')}")
    test("Mentor integration: mentor_chain_score in default_state",
         "mentor_chain_score" in _mds and _mds["mentor_chain_score"] == 1.0,
         f"got {_mds.get('mentor_chain_score')}")
    test("Mentor integration: mentor_memory_match in default_state",
         "mentor_memory_match" in _mds and _mds["mentor_memory_match"] is None,
         f"got {_mds.get('mentor_memory_match')}")
    test("Mentor integration: mentor_historical_context in default_state",
         "mentor_historical_context" in _mds and _mds["mentor_historical_context"] == "",
         f"got {_mds.get('mentor_historical_context')}")

    # Schema entries present
    _mschema = _mentor_schema()
    for _mf in ["mentor_last_verdict", "mentor_last_score", "mentor_escalation_count",
                 "mentor_signals", "mentor_warned_this_cycle", "mentor_chain_pattern",
                 "mentor_chain_score", "mentor_memory_match", "mentor_historical_context"]:
        test(f"Mentor integration: {_mf} in state schema",
             _mf in _mschema and _mschema[_mf].get("category") == "mentor",
             f"present={_mf in _mschema}")

    # All toggles off = no mentor output (verify orchestrator toggle checks)
    from shared.state import get_live_toggle as _glt_mentor
    test("Mentor integration: mentor_tracker toggle exists and is False",
         _glt_mentor("mentor_tracker") == False,
         f"got {_glt_mentor('mentor_tracker')}")
    test("Mentor integration: mentor_hindsight_gate toggle exists and is False",
         _glt_mentor("mentor_hindsight_gate") == False,
         f"got {_glt_mentor('mentor_hindsight_gate')}")
    test("Mentor integration: mentor_outcome_chains toggle exists and is False",
         _glt_mentor("mentor_outcome_chains") == False,
         f"got {_glt_mentor('mentor_outcome_chains')}")
    test("Mentor integration: mentor_memory toggle exists and is False",
         _glt_mentor("mentor_memory") == False,
         f"got {_glt_mentor('mentor_memory')}")

except Exception as _mint_e:
    _h.FAIL += 1
    _h.RESULTS.append(f"  FAIL: Mentor Integration tests: {_mint_e}")
    print(f"  FAIL: Mentor Integration tests: {_mint_e}")

cleanup_test_states()

# ─────────────────────────────────────────────────
# Upgrade C: Mentor Analytics Nudges
# ─────────────────────────────────────────────────
print('\n--- Upgrade C: Mentor Analytics Nudges ---')

try:
    from tracker_pkg.mentor_analytics import evaluate as _ma_eval, _TRIGGERS as _ma_triggers

    # 1. Gate file edit triggers gate_dashboard nudge
    _ma_state1 = {"total_tool_calls": 10, "analytics_last_used": {}}
    _ma_msgs1 = _ma_eval("Edit", {"file_path": "/home/crab/.claude/hooks/gates/gate_04.py"}, {}, _ma_state1)
    test("UpgradeC: gate edit triggers gate_dashboard nudge",
         any("gate_dashboard" in m for m in _ma_msgs1),
         f"msgs={_ma_msgs1}")

    # 2. Skill file edit triggers skill_health nudge
    _ma_msgs2 = _ma_eval("Edit", {"file_path": "/home/crab/.claude/skills/benchmark/SKILL.md"}, {}, _ma_state1)
    test("UpgradeC: skill edit triggers skill_health nudge",
         any("skill_health" in m for m in _ma_msgs2),
         f"msgs={_ma_msgs2}")

    # 3. Enforcer edit triggers gate_timing nudge
    _ma_msgs3 = _ma_eval("Edit", {"file_path": "/home/crab/.claude/hooks/enforcer.py"}, {}, _ma_state1)
    test("UpgradeC: enforcer edit triggers gate_timing nudge",
         any("gate_timing" in m for m in _ma_msgs3),
         f"msgs={_ma_msgs3}")

    # 4. Non-framework file → no nudge (except periodic)
    _ma_state4 = {"total_tool_calls": 10, "analytics_last_used": {}}
    _ma_msgs4 = _ma_eval("Edit", {"file_path": "/home/crab/Desktop/app.py"}, {}, _ma_state4)
    test("UpgradeC: non-framework edit → no path-based nudge",
         not any("gate_dashboard" in m or "skill_health" in m or "gate_timing" in m for m in _ma_msgs4),
         f"msgs={_ma_msgs4}")

    # 5. Cooldown: recent analytics call suppresses nudge
    import time as _ma_time
    _ma_state5 = {"total_tool_calls": 10, "analytics_last_used": {"gate_dashboard": _ma_time.time()}}
    _ma_msgs5 = _ma_eval("Edit", {"file_path": "/home/crab/.claude/hooks/gates/gate_04.py"}, {}, _ma_state5)
    test("UpgradeC: cooldown suppresses nudge after recent analytics call",
         not any("gate_dashboard" in m for m in _ma_msgs5),
         f"msgs={_ma_msgs5}")

    # 6. Periodic checkpoint at 50th tool call
    _ma_state6 = {"total_tool_calls": 50, "analytics_last_used": {}}
    _ma_msgs6 = _ma_eval("Read", {"file_path": "/tmp/test.py"}, {}, _ma_state6)
    test("UpgradeC: periodic checkpoint at 50th tool call",
         any("session_summary" in m for m in _ma_msgs6),
         f"msgs={_ma_msgs6}")

    # 7. Read tool → no path-based nudge (only Edit/Write trigger)
    _ma_state7 = {"total_tool_calls": 10, "analytics_last_used": {}}
    _ma_msgs7 = _ma_eval("Read", {"file_path": "/home/crab/.claude/hooks/gates/gate_04.py"}, {}, _ma_state7)
    test("UpgradeC: Read tool → no nudge",
         not any("gate_dashboard" in m for m in _ma_msgs7),
         f"msgs={_ma_msgs7}")

except Exception as _ma_e:
    _h.FAIL += 1
    _h.RESULTS.append(f"  FAIL: Upgrade C tests: {_ma_e}")
    print(f"  FAIL: Upgrade C tests: {_ma_e}")

# ─────────────────────────────────────────────────
# Upgrade F: Gate 6 Analytics Advisory (REMOVED)
# Analytics counter was removed — Gate 6 no longer tracks framework edits
# without analytics queries. The deadlock path to nonexistent analytics server is eliminated.
# ─────────────────────────────────────────────────
print('\n--- Upgrade F: Gate 6 Analytics Advisory (removed) ---')
test("UpgradeF: analytics counter removed from Gate 6",
     not hasattr(__import__('gates.gate_06_save_fix', fromlist=['ANALYTICS_ESCALATION_THRESHOLD']), 'ANALYTICS_ESCALATION_THRESHOLD'),
     "ANALYTICS_ESCALATION_THRESHOLD should not exist in gate_06")

cleanup_test_states()

# ─────────────────────────────────────────────────
# Analytics MCP: Enforcer Exemption
# ─────────────────────────────────────────────────
print("\n--- Analytics MCP: Enforcer Exemption ---")

try:
    from enforcer import is_analytics_tool, is_always_allowed, ANALYTICS_TOOL_PREFIX

    test("is_analytics_tool: recognises analytics tool",
         is_analytics_tool("mcp__analytics__framework_health") == True)
    test("is_analytics_tool: rejects memory tool",
         is_analytics_tool("mcp__memory__search") == False)
    test("is_analytics_tool: rejects plain tool",
         is_analytics_tool("Edit") == False)
    test("is_analytics_tool: rejects empty string",
         is_analytics_tool("") == False)
    test("is_always_allowed: analytics tool is always allowed",
         is_always_allowed("mcp__analytics__session_summary") == True)
    test("is_always_allowed: analytics all_metrics is allowed",
         is_always_allowed("mcp__analytics__all_metrics") == True)
    test("ANALYTICS_TOOL_PREFIX is correct",
         ANALYTICS_TOOL_PREFIX == "mcp__analytics__")

except Exception as _amcp_e:
    _h.FAIL += 1
    _h.RESULTS.append(f"  FAIL: Analytics MCP enforcer exemption tests: {_amcp_e}")
    print(f"  FAIL: Analytics MCP enforcer exemption tests: {_amcp_e}")

# ─────────────────────────────────────────────────
# Analytics MCP: Gate 11 Exemption
# ─────────────────────────────────────────────────
print("\n--- Analytics MCP: Gate 11 Exemption ---")

try:
    from gates.gate_11_rate_limit import check as _g11_analytics_check

    # Analytics tool should not be blocked and should not add to rate window
    _g11a_state = {"rate_window_timestamps": [], "session_start": time.time() - 60}
    _g11a_result = _g11_analytics_check("mcp__analytics__framework_health", {}, _g11a_state)
    test("Gate 11: analytics tool → not blocked", not _g11a_result.blocked)
    test("Gate 11: analytics tool → no timestamp appended",
         len(_g11a_state.get("rate_window_timestamps", [])) == 0,
         f"got {len(_g11a_state.get('rate_window_timestamps', []))} timestamps")

    # Non-analytics tool should still append timestamp
    _g11b_state = {"rate_window_timestamps": [], "session_start": time.time() - 60}
    _g11b_result = _g11_analytics_check("Edit", {"file_path": "/tmp/test.py"}, _g11b_state)
    test("Gate 11: normal tool still appends timestamp",
         len(_g11b_state.get("rate_window_timestamps", [])) == 1)

except Exception as _g11a_e:
    _h.FAIL += 1
    _h.RESULTS.append(f"  FAIL: Analytics MCP Gate 11 exemption tests: {_g11a_e}")
    print(f"  FAIL: Analytics MCP Gate 11 exemption tests: {_g11a_e}")

# ─────────────────────────────────────────────────
# Analytics MCP: Session Auto-Detection
# ─────────────────────────────────────────────────
print("\n--- Analytics MCP: Session Auto-Detection ---")

try:
    from analytics_server import _detect_session_id, _resolve_session_id

    # _detect_session_id should return a string (may be "default" if no state files)
    _detected_sid = _detect_session_id()
    test("_detect_session_id returns string", isinstance(_detected_sid, str))
    test("_detect_session_id returns non-empty", len(_detected_sid) > 0)

    # _resolve_session_id with empty string should auto-detect
    _resolved = _resolve_session_id("")
    test("_resolve_session_id('') auto-detects", _resolved == _detected_sid)

    # _resolve_session_id with explicit ID should pass through
    _explicit = _resolve_session_id("my-explicit-session")
    test("_resolve_session_id passes explicit ID through",
         _explicit == "my-explicit-session")

except Exception as _asd_e:
    _h.FAIL += 1
    _h.RESULTS.append(f"  FAIL: Analytics MCP session auto-detection tests: {_asd_e}")
    print(f"  FAIL: Analytics MCP session auto-detection tests: {_asd_e}")

# ─────────────────────────────────────────────────
# Analytics MCP: Search Tools (telegram, terminal, web)
# ─────────────────────────────────────────────────
print("\n--- Analytics MCP: Search Tools ---")

try:
    from analytics_server import telegram_search
    from search_server import terminal_history_search, transcript_context

    # Telegram search: empty query → empty results
    _tg_empty = telegram_search("")
    test("telegram_search('') returns empty results",
         isinstance(_tg_empty, dict) and _tg_empty.get("count") == 0
         and _tg_empty.get("results") == [] and _tg_empty.get("source") == "telegram_fts")

    # Telegram search: real query → dict with expected keys
    _tg_result = telegram_search("test")
    test("telegram_search('test') returns dict with count/results keys",
         isinstance(_tg_result, dict) and "count" in _tg_result
         and "results" in _tg_result and "source" in _tg_result)

    # Telegram search: limit clamping → no crash
    _tg_clamp = telegram_search("test", limit=100)
    test("telegram_search limit=100 clamped, no crash",
         isinstance(_tg_clamp, dict) and "count" in _tg_clamp)

    # Terminal history search: empty query → empty results
    _th_empty = terminal_history_search("")
    test("terminal_history_search('') returns empty results",
         isinstance(_th_empty, dict) and _th_empty.get("count") == 0
         and _th_empty.get("results") == [] and _th_empty.get("source") == "terminal_fts")

    # Terminal history search: real query → dict with expected keys
    _th_result = terminal_history_search("python")
    test("terminal_history_search('python') returns dict with count/results keys",
         isinstance(_th_result, dict) and "count" in _th_result
         and "results" in _th_result and "source" in _th_result)

    # Terminal history search: negative limit clamped to 1
    _th_clamp = terminal_history_search("x", limit=-1)
    test("terminal_history_search limit=-1 clamped to 1, no crash",
         isinstance(_th_clamp, dict) and "count" in _th_clamp)

    # transcript_context: empty session_id → error
    _tc_empty = transcript_context("")
    test("transcript_context('') returns error dict",
         isinstance(_tc_empty, dict) and "error" in _tc_empty
         and _tc_empty.get("source") == "transcript_l0")

    # transcript_context: nonexistent session → error or disabled
    _tc_missing = transcript_context("nonexistent-session-id-000")
    test("transcript_context(nonexistent) returns error or disabled",
         isinstance(_tc_missing, dict) and _tc_missing.get("source") == "transcript_l0"
         and ("error" in _tc_missing or _tc_missing.get("disabled")))

    # transcript_context: real session → records list or disabled
    import glob as _tc_glob
    _tc_jsonls = _tc_glob.glob(os.path.join(
        os.path.expanduser("~"), ".claude", "projects", "-home-crab--claude", "*.jsonl"))
    if _tc_jsonls:
        _tc_sid = os.path.basename(_tc_jsonls[0]).replace(".jsonl", "")
        _tc_real = transcript_context(_tc_sid, max_records=5)
        test("transcript_context(real_session) returns records or disabled",
             isinstance(_tc_real, dict) and _tc_real.get("source") == "transcript_l0"
             and ("records" in _tc_real or _tc_real.get("disabled")))
    else:
        test("transcript_context(real_session) — SKIP no JSONL files found", True)

except Exception as _ast_e:
    _h.FAIL += 1
    _h.RESULTS.append(f"  FAIL: Analytics MCP search tools tests: {_ast_e}")
    print(f"  FAIL: Analytics MCP search tools tests: {_ast_e}")

# ── L0 Transcript Functions (direct import) ──────────────────────────────
print("\n--- L0 Transcript Functions ---")
try:
    _term_hist_dir = os.path.join(os.path.expanduser("~"), ".claude",
                                  "integrations", "terminal-history")
    if _term_hist_dir not in sys.path:
        sys.path.insert(0, _term_hist_dir)
    from db import _summarize_record, _window_around_timestamp, get_raw_transcript_window

    # _summarize_record: text message
    _sr_text = _summarize_record({
        "type": "user", "timestamp": "2026-02-25T10:00:00",
        "message": {"role": "user", "content": "hello world"}
    })
    test("_summarize_record(text msg) extracts role and text",
         _sr_text.get("role") == "user" and _sr_text.get("text") == "hello world")

    # _summarize_record: tool_use block
    _sr_tool = _summarize_record({
        "type": "assistant", "timestamp": "2026-02-25T10:00:01",
        "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Read", "input": {"file_path": "/tmp/x"}}
        ]}
    })
    test("_summarize_record(tool_use) extracts tool name",
         _sr_tool.get("content_blocks") and _sr_tool["content_blocks"][0].get("name") == "Read")

    # _summarize_record: tool_result block
    _sr_result = _summarize_record({
        "type": "user", "timestamp": "2026-02-25T10:00:02",
        "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "abc123", "content": "output data here"}
        ]}
    })
    test("_summarize_record(tool_result) extracts output preview",
         _sr_result.get("content_blocks")
         and _sr_result["content_blocks"][0].get("output_preview") == "output data here")

    # _summarize_record: truncation
    _sr_long = _summarize_record({
        "type": "user", "timestamp": "2026-02-25T10:00:03",
        "message": {"role": "user", "content": "x" * 1000}
    })
    test("_summarize_record truncates text at 500 chars",
         len(_sr_long.get("text", "")) == 500)

    # _summarize_record: progress record
    _sr_prog = _summarize_record({
        "type": "progress", "timestamp": "2026-02-25T10:00:04",
        "data": {"type": "hook_progress", "hookEvent": "PreToolUse", "hookName": "enforcer"}
    })
    test("_summarize_record(progress) extracts hook_event",
         _sr_prog.get("hook_event") == "PreToolUse")

    # _window_around_timestamp: filters correctly
    _wt_records = [
        {"timestamp": "2026-02-25T10:00:00", "type": "a"},
        {"timestamp": "2026-02-25T10:05:00", "type": "b"},
        {"timestamp": "2026-02-25T10:10:00", "type": "c"},
        {"timestamp": "2026-02-25T10:30:00", "type": "d"},
        {"timestamp": "2026-02-25T11:00:00", "type": "e"},
    ]
    _wt_filtered = _window_around_timestamp(_wt_records, "2026-02-25T10:05:00", window_minutes=6)
    _wt_types = [r["type"] for r in _wt_filtered]
    test("_window_around_timestamp filters ±6min correctly",
         "a" in _wt_types and "b" in _wt_types and "c" in _wt_types
         and "d" not in _wt_types and "e" not in _wt_types)

    # _window_around_timestamp: bad timestamp falls back to last 30
    _wt_fallback = _window_around_timestamp(_wt_records, "not-a-timestamp", window_minutes=5)
    test("_window_around_timestamp bad timestamp falls back to last records",
         len(_wt_fallback) == len(_wt_records))  # all 5 since < 30

    # get_raw_transcript_window: missing file
    _grw_missing = get_raw_transcript_window("nonexistent-uuid-000")
    test("get_raw_transcript_window(missing) returns error dict",
         isinstance(_grw_missing, dict) and "error" in _grw_missing
         and _grw_missing.get("source") == "transcript_l0")

    # get_raw_transcript_window: real session
    import glob as _grw_glob
    _grw_jsonls = _grw_glob.glob(os.path.join(
        os.path.expanduser("~"), ".claude", "projects", "-home-crab--claude", "*.jsonl"))
    if _grw_jsonls:
        _grw_sid = os.path.basename(_grw_jsonls[0]).replace(".jsonl", "")
        _grw_real = get_raw_transcript_window(_grw_sid, max_records=5)
        test("get_raw_transcript_window(real) returns records",
             isinstance(_grw_real, dict) and "records" in _grw_real
             and isinstance(_grw_real["records"], list)
             and _grw_real.get("record_count", 0) <= 5
             and _grw_real.get("total_in_session", 0) > 0)
    else:
        test("get_raw_transcript_window(real) — SKIP no JSONL files", True)

except Exception as _l0_e:
    _h.FAIL += 1
    _h.RESULTS.append(f"  FAIL: L0 Transcript Functions tests: {_l0_e}")
    print(f"  FAIL: L0 Transcript Functions tests: {_l0_e}")

# ─────────────────────────────────────────────────
# Capability Registry Tests
# ─────────────────────────────────────────────────
print("\n--- Capability Registry ---")

from shared.capability_registry import (
    match_agent, recommend_model, get_agent_info,
    check_agent_permission, define_agent_acl, get_agent_acl,
    AGENT_CAPABILITIES, TASK_REQUIREMENTS,
)

# Test 1: match_agent returns builder for feature-implementation
_cr_match1 = match_agent("feature-implementation")
test(
    "CapabilityRegistry: match_agent returns builder for feature-implementation",
    _cr_match1 == "builder",
    f"Expected 'builder', got {_cr_match1!r}",
)

# Test 2: match_agent returns researcher for research tasks
_cr_match2 = match_agent("research")
test(
    "CapabilityRegistry: match_agent returns researcher for research",
    _cr_match2 == "researcher",
    f"Expected 'researcher', got {_cr_match2!r}",
)

# Test 3: match_agent returns None for unknown task type
_cr_match3 = match_agent("nonexistent-task-type-xyz")
test(
    "CapabilityRegistry: match_agent returns None for unknown task",
    _cr_match3 is None,
    f"Expected None, got {_cr_match3!r}",
)

# Test 4: match_agent respects exclude list
# When sole capable agent is excluded, returns None (correct behavior)
_cr_match4 = match_agent("feature-implementation", exclude=["builder"])
test(
    "CapabilityRegistry: match_agent returns None when only match excluded",
    _cr_match4 is None,
    f"Expected None when builder excluded, got {_cr_match4!r}",
)

# Test 5: recommend_model returns valid model ID
_cr_model1 = recommend_model("researcher")
test(
    "CapabilityRegistry: recommend_model returns haiku for researcher",
    "haiku" in _cr_model1,
    f"Expected haiku model ID, got {_cr_model1!r}",
)

# Test 6: recommend_model falls back to sonnet for unknown agent
_cr_model2 = recommend_model("unknown-agent-xyz")
test(
    "CapabilityRegistry: recommend_model falls back to sonnet for unknown",
    "sonnet" in _cr_model2,
    f"Expected sonnet fallback, got {_cr_model2!r}",
)

# Test 7: get_agent_info returns correct structure
_cr_info1 = get_agent_info("builder")
test(
    "CapabilityRegistry: get_agent_info returns complete info for builder",
    _cr_info1 is not None
    and "skills" in _cr_info1
    and "model_id" in _cr_info1
    and "implement" in _cr_info1["skills"],
    f"Got {_cr_info1}",
)

# Test 8: get_agent_info returns None for unknown agent
_cr_info2 = get_agent_info("nonexistent-agent")
test(
    "CapabilityRegistry: get_agent_info returns None for unknown agent",
    _cr_info2 is None,
    f"Expected None, got {_cr_info2!r}",
)

# Test 9: check_agent_permission allows explorer to Read
_cr_perm1 = check_agent_permission("explorer", "Read")
test(
    "CapabilityRegistry: explorer is allowed to Read",
    _cr_perm1 is True,
    f"Expected True, got {_cr_perm1!r}",
)

# Test 10: check_agent_permission denies explorer from Edit
_cr_perm2 = check_agent_permission("explorer", "Edit")
test(
    "CapabilityRegistry: explorer is denied Edit",
    _cr_perm2 is False,
    f"Expected False, got {_cr_perm2!r}",
)

# Test 11: check_agent_permission denies unknown agent type
_cr_perm3 = check_agent_permission("nonexistent-agent", "Read")
test(
    "CapabilityRegistry: unknown agent denied by default",
    _cr_perm3 is False,
    f"Expected False, got {_cr_perm3!r}",
)

# Test 12: check_agent_permission blocks destructive bash commands
_cr_perm4 = check_agent_permission("builder", "Bash", file_path="rm -rf /")
test(
    "CapabilityRegistry: builder blocked from rm -rf via Bash",
    _cr_perm4 is False,
    f"Expected False, got {_cr_perm4!r}",
)

# Test 13: test-writer path restriction enforced
_cr_perm5 = check_agent_permission("test-writer", "Edit", file_path="/src/main.py")
_cr_perm6 = check_agent_permission("test-writer", "Edit", file_path="test_main.py")
test(
    "CapabilityRegistry: test-writer restricted to test files",
    _cr_perm5 is False and _cr_perm6 is True,
    f"non-test={_cr_perm5}, test={_cr_perm6}",
)

# Test 14: define_agent_acl runtime override works
from shared.capability_registry import _ACL_OVERRIDES
_cr_prev_override = _ACL_OVERRIDES.pop("__test_agent__", None)
define_agent_acl("__test_agent__", allowed_tools=["Read", "Grep"], denied_tools=[], allowed_paths=["*"])
_cr_perm7 = check_agent_permission("__test_agent__", "Read")
_cr_perm8 = check_agent_permission("__test_agent__", "Edit")
test(
    "CapabilityRegistry: define_agent_acl runtime override works",
    _cr_perm7 is True and _cr_perm8 is False,
    f"Read={_cr_perm7}, Edit={_cr_perm8}",
)
_ACL_OVERRIDES.pop("__test_agent__", None)

# ─────────────────────────────────────────────────
# Extended EventBus Tests
# ─────────────────────────────────────────────────
print("\n--- EventBus Extended ---")

import shared.event_bus as _eb2

# Reset for clean state
_eb2.clear()

# Test 1: unsubscribe removes handler
_eb2_recv = []
_eb2_handler = lambda e: _eb2_recv.append(e)
_eb2.subscribe(_eb2.EventType.GATE_FIRED, _eb2_handler)
_eb2_removed = _eb2.unsubscribe(_eb2.EventType.GATE_FIRED, _eb2_handler)
_eb2.publish(_eb2.EventType.GATE_FIRED, {"gate": "test"}, persist=False)
test(
    "EventBus: unsubscribe removes handler and returns True",
    _eb2_removed is True and len(_eb2_recv) == 0,
    f"removed={_eb2_removed}, recv_len={len(_eb2_recv)}",
)

# Test 2: unsubscribe returns False for unknown handler
_eb2_removed2 = _eb2.unsubscribe(_eb2.EventType.GATE_FIRED, lambda e: None)
test(
    "EventBus: unsubscribe returns False for unknown handler",
    _eb2_removed2 is False,
    f"Expected False, got {_eb2_removed2}",
)

# Test 3: get_stats returns correct structure
_eb2.clear()
_eb2.publish(_eb2.EventType.GATE_FIRED, {"g": 1}, persist=False)
_eb2.publish(_eb2.EventType.GATE_BLOCKED, {"g": 2}, persist=False)
_eb2.publish(_eb2.EventType.GATE_FIRED, {"g": 3}, persist=False)
_eb2_stats = _eb2.get_stats()
test(
    "EventBus: get_stats returns correct publish counts",
    _eb2_stats["total_published"] == 3
    and _eb2_stats["events_in_buffer"] == 3
    and _eb2_stats["by_type"].get(_eb2.EventType.GATE_FIRED) == 2
    and _eb2_stats["by_type"].get(_eb2.EventType.GATE_BLOCKED) == 1,
    f"stats={_eb2_stats}",
)

# Test 4: clear resets all state
_eb2.clear()
_eb2_stats2 = _eb2.get_stats()
test(
    "EventBus: clear resets all counters",
    _eb2_stats2["total_published"] == 0
    and _eb2_stats2["events_in_buffer"] == 0
    and _eb2_stats2["subscriber_count"] == 0,
    f"stats after clear={_eb2_stats2}",
)

# Test 5: configure caps ring buffer
_eb2.clear()
_eb2.configure(max_events=3)
for _i in range(10):
    _eb2.publish(_eb2.EventType.TOOL_CALLED, {"i": _i}, persist=False)
_eb2_recent = _eb2.get_recent()
test(
    "EventBus: configure caps ring buffer at max_events",
    len(_eb2_recent) == 3,
    f"Expected 3 events, got {len(_eb2_recent)}",
)
_eb2.configure(max_events=1000)  # restore default

# Test 6: broken handler doesn't crash publish (fail-open)
_eb2.clear()
_eb2.subscribe(_eb2.EventType.ERROR_DETECTED, lambda e: (_ for _ in ()).throw(RuntimeError("boom")))
_eb2_evt = _eb2.publish(_eb2.EventType.ERROR_DETECTED, {"err": "test"}, persist=False)
test(
    "EventBus: broken handler doesn't crash publish",
    _eb2_evt is not None and _eb2_evt["type"] == _eb2.EventType.ERROR_DETECTED,
    f"Expected valid event, got {_eb2_evt}",
)

# Test 7: get_recent with limit parameter
_eb2.clear()
for _i in range(20):
    _eb2.publish(_eb2.EventType.GATE_FIRED, {"n": _i}, persist=False)
_eb2_limited = _eb2.get_recent(limit=5)
test(
    "EventBus: get_recent respects limit parameter",
    len(_eb2_limited) == 5 and _eb2_limited[-1]["data"]["n"] == 19,
    f"len={len(_eb2_limited)}, last_n={_eb2_limited[-1]['data'].get('n') if _eb2_limited else 'N/A'}",
)

# Cleanup
_eb2.clear()

# ─────────────────────────────────────────────────
# Circuit Breaker Tests
# ─────────────────────────────────────────────────
print("\n--- Circuit Breaker ---")

from shared.circuit_breaker import (
    record_success, record_failure, is_open, get_state, get_all_states,
    reset, should_skip_gate, record_gate_result, get_gate_circuit_state,
    reset_gate_circuit, STATE_CLOSED, STATE_OPEN, STATE_HALF_OPEN,
    DEFAULT_FAILURE_THRESHOLD, DEFAULT_RECOVERY_TIMEOUT, DEFAULT_SUCCESS_THRESHOLD,
    _load, _save,
)

_CB_TEST_SVC = "__test_cb_fw__"
_CB_TEST_GATE = "__test_gate_fw__"

# Test 1: Fresh service starts CLOSED
reset(_CB_TEST_SVC)
test(
    "CircuitBreaker: fresh service starts CLOSED",
    get_state(_CB_TEST_SVC) == STATE_CLOSED,
    f"Expected CLOSED, got {get_state(_CB_TEST_SVC)}",
)

# Test 2: is_open returns False when CLOSED
test(
    "CircuitBreaker: is_open False when CLOSED",
    is_open(_CB_TEST_SVC) is False,
)

# Test 3: Failures below threshold stay CLOSED
reset(_CB_TEST_SVC)
for _ in range(DEFAULT_FAILURE_THRESHOLD - 1):
    record_failure(_CB_TEST_SVC)
test(
    "CircuitBreaker: stays CLOSED below failure threshold",
    get_state(_CB_TEST_SVC) == STATE_CLOSED,
)

# Test 4: Reaching failure threshold opens circuit
record_failure(_CB_TEST_SVC)  # one more to cross threshold
test(
    "CircuitBreaker: transitions to OPEN at threshold",
    get_state(_CB_TEST_SVC) == STATE_OPEN,
)

# Test 5: is_open returns True when OPEN
test(
    "CircuitBreaker: is_open True when OPEN",
    is_open(_CB_TEST_SVC) is True,
)

# Test 6: Recovery timeout transitions OPEN -> HALF_OPEN
_cb_data = _load()
_cb_data[_CB_TEST_SVC]["opened_at"] = time.time() - DEFAULT_RECOVERY_TIMEOUT - 1
_save(_cb_data)
test(
    "CircuitBreaker: transitions to HALF_OPEN after recovery timeout",
    get_state(_CB_TEST_SVC) == STATE_HALF_OPEN,
)

# Test 7: Success in HALF_OPEN -> CLOSED
for _ in range(DEFAULT_SUCCESS_THRESHOLD):
    record_success(_CB_TEST_SVC)
test(
    "CircuitBreaker: HALF_OPEN closes after success threshold",
    get_state(_CB_TEST_SVC) == STATE_CLOSED,
)

# Test 8: reset() restores CLOSED state
reset(_CB_TEST_SVC)
for _ in range(DEFAULT_FAILURE_THRESHOLD):
    record_failure(_CB_TEST_SVC)
reset(_CB_TEST_SVC)
test(
    "CircuitBreaker: reset() restores CLOSED",
    get_state(_CB_TEST_SVC) == STATE_CLOSED,
)

# Test 9: get_all_states includes tracked service
reset(_CB_TEST_SVC)
record_success(_CB_TEST_SVC)
_cb_all = get_all_states()
test(
    "CircuitBreaker: get_all_states includes test service",
    _CB_TEST_SVC in _cb_all,
)

# Test 10: is_open returns False for unknown service (fail-open)
test(
    "CircuitBreaker: is_open False for unknown service",
    is_open("__unknown_service_xyz__") is False,
)

# Test 11: Gate circuit - should_skip_gate returns False for Tier 1 gates
reset_gate_circuit("gate_01_read_before_edit")
for _ in range(10):
    record_gate_result("gate_01_read_before_edit", success=False)
test(
    "CircuitBreaker: Tier 1 gate never skipped",
    should_skip_gate("gate_01_read_before_edit") is False,
)
reset_gate_circuit("gate_01_read_before_edit")

# Test 12: Gate circuit - non-Tier1 gate opens after crashes
reset_gate_circuit(_CB_TEST_GATE)
for _ in range(5):
    record_gate_result(_CB_TEST_GATE, success=False)
test(
    "CircuitBreaker: non-Tier1 gate circuit opens after crashes",
    get_gate_circuit_state(_CB_TEST_GATE) == STATE_OPEN,
)

# Test 13: Gate circuit - should_skip_gate True when open
test(
    "CircuitBreaker: should_skip_gate True when gate circuit open",
    should_skip_gate(_CB_TEST_GATE) is True,
)

# Test 14: Gate circuit - reset restores CLOSED
reset_gate_circuit(_CB_TEST_GATE)
test(
    "CircuitBreaker: reset_gate_circuit restores CLOSED",
    get_gate_circuit_state(_CB_TEST_GATE) == STATE_CLOSED
    and should_skip_gate(_CB_TEST_GATE) is False,
)

# Cleanup
reset(_CB_TEST_SVC)
reset_gate_circuit(_CB_TEST_GATE)
reset_gate_circuit("gate_01_read_before_edit")

# ─────────────────────────────────────────────────
# Consensus Validator Tests
# ─────────────────────────────────────────────────
print("\n--- Consensus Validator ---")

from shared.consensus_validator import (
    check_memory_consensus,
    check_edit_consensus,
    compute_confidence,
    recommend_action,
)

# Test 1: check_memory_consensus identifies novel content
_cv_result1 = check_memory_consensus(
    "This is a completely new finding about quantum computing",
    ["Old memory about database optimization", "Another about testing"],
)
test(
    "ConsensusValidator: novel content detected",
    _cv_result1["verdict"] == "novel" and _cv_result1["confidence"] > 0.5,
    f"verdict={_cv_result1['verdict']}, confidence={_cv_result1['confidence']}",
)

# Test 2: check_memory_consensus identifies duplicates
_cv_result2 = check_memory_consensus(
    "The gate timing shows latency of 50ms on average",
    ["The gate timing shows latency of 50ms on average for all gates"],
)
test(
    "ConsensusValidator: duplicate content detected",
    _cv_result2["verdict"] == "duplicate" and _cv_result2["top_match"] > 0.8,
    f"verdict={_cv_result2['verdict']}, top_match={_cv_result2['top_match']:.2f}",
)

# Test 3: check_memory_consensus handles empty content
_cv_result3 = check_memory_consensus("", ["some existing memory"])
test(
    "ConsensusValidator: empty content returns novel with 0.5 confidence",
    _cv_result3["verdict"] == "novel" and _cv_result3["confidence"] == 0.5,
    f"verdict={_cv_result3['verdict']}, confidence={_cv_result3['confidence']}",
)

# Test 4: check_memory_consensus handles empty existing memories
_cv_result4 = check_memory_consensus("new content", [])
test(
    "ConsensusValidator: novel when no existing memories",
    _cv_result4["verdict"] == "novel" and _cv_result4["confidence"] >= 0.7,
    f"verdict={_cv_result4['verdict']}, confidence={_cv_result4['confidence']}",
)

# Test 5: check_edit_consensus flags critical file
_cv_edit1 = check_edit_consensus(
    "enforcer.py",
    "def check(): pass",
    "def check(): return True",
)
test(
    "ConsensusValidator: critical file flagged",
    _cv_edit1["is_critical"] is True and len(_cv_edit1["risks"]) > 0,
    f"is_critical={_cv_edit1['is_critical']}, risks={len(_cv_edit1['risks'])}",
)

# Test 6: check_edit_consensus safe for small non-critical changes
_cv_edit2 = check_edit_consensus(
    "my_module.py",
    "def helper(): return 1",
    "def helper(): return 2",
)
test(
    "ConsensusValidator: small non-critical edit is safe",
    _cv_edit2["safe"] is True and _cv_edit2["confidence"] > 0.8,
    f"safe={_cv_edit2['safe']}, confidence={_cv_edit2['confidence']}",
)

# Test 7: check_edit_consensus flags API removal
_cv_edit3 = check_edit_consensus(
    "utils.py",
    "def public_fn(): pass\ndef helper(): pass",
    "def helper(): pass",
)
test(
    "ConsensusValidator: API removal flagged as risk",
    any("removed" in r.lower() for r in _cv_edit3["risks"]),
    f"risks={_cv_edit3['risks']}",
)

# Test 8: compute_confidence returns 0.5 for empty signals
_cv_conf1 = compute_confidence({})
test(
    "ConsensusValidator: compute_confidence returns 0.5 for empty",
    _cv_conf1 == 0.5,
    f"Expected 0.5, got {_cv_conf1}",
)

# Test 9: compute_confidence returns weighted average
_cv_conf2 = compute_confidence({"memory_coverage": 1.0, "test_coverage": 1.0})
test(
    "ConsensusValidator: compute_confidence weighted average",
    0.0 < _cv_conf2 <= 1.0,
    f"Expected value in (0, 1], got {_cv_conf2}",
)

# Test 10: recommend_action thresholds
test(
    "ConsensusValidator: recommend_action thresholds correct",
    recommend_action(0.8) == "allow"
    and recommend_action(0.5) == "ask"
    and recommend_action(0.1) == "block",
    f"0.8={recommend_action(0.8)}, 0.5={recommend_action(0.5)}, 0.1={recommend_action(0.1)}",
)

# Test 11: check_edit_consensus detects hardcoded secrets
_cv_edit4 = check_edit_consensus(
    "config.py",
    "API_URL = 'https://api.example.com'",
    "API_URL = 'https://api.example.com'\npassword = 'supersecret123'",
)
test(
    "ConsensusValidator: detects hardcoded secrets",
    any("secret" in r.lower() or "credential" in r.lower() for r in _cv_edit4["risks"]),
    f"risks={_cv_edit4['risks']}",
)

# Test 12: check_memory_consensus detects conflict via negation
_cv_result5 = check_memory_consensus(
    "The gate is NOT blocking correctly",
    ["The gate is blocking correctly and working well"],
)
test(
    "ConsensusValidator: detects conflict via negation",
    _cv_result5["verdict"] == "conflict",
    f"verdict={_cv_result5['verdict']}, reason={_cv_result5.get('reason', '')}",
)

# ─────────────────────────────────────────────────
# Git Context Tests
# ─────────────────────────────────────────────────
print("\n--- Git Context ---")

try:
    from boot_pkg.context import _extract_git_context
    _gc = _extract_git_context()
    test(
        "GitContext: _extract_git_context returns dict with expected keys",
        isinstance(_gc, dict)
        and "branch" in _gc
        and "uncommitted_count" in _gc
        and "recent_commits" in _gc,
        f"Got {_gc}",
    )
    test(
        "GitContext: branch is a non-empty string",
        isinstance(_gc.get("branch"), str) and len(_gc["branch"]) > 0,
        f"branch={_gc.get('branch')!r}",
    )
    test(
        "GitContext: uncommitted_count is non-negative int",
        isinstance(_gc.get("uncommitted_count"), int) and _gc["uncommitted_count"] >= 0,
        f"uncommitted_count={_gc.get('uncommitted_count')!r}",
    )
    test(
        "GitContext: recent_commits is a list with <=5 entries",
        isinstance(_gc.get("recent_commits"), list) and len(_gc["recent_commits"]) <= 5,
        f"recent_commits len={len(_gc.get('recent_commits', []))}",
    )
except Exception as _gc_e:
    _h.FAIL += 1
    _h.RESULTS.append(f"  FAIL: GitContext tests: {_gc_e}")
    print(f"  FAIL: GitContext tests: {_gc_e}")

# ─────────────────────────────────────────────────
# Gate Trend Tracker Tests
# ─────────────────────────────────────────────────
print("\n--- Gate Trend Tracker ---")

from shared.gate_trend import (
    compute_gate_trend, get_trend_report, _load_snapshots, _save_snapshots,
    _trend_path, TREND_THRESHOLD,
)

# Test 1: compute_gate_trend returns stable for no data
_gt_trend1 = compute_gate_trend("gate_01", [])
test(
    "GateTrend: compute_gate_trend stable for empty snapshots",
    _gt_trend1["direction"] == "stable" and _gt_trend1["data_points"] == 0,
    f"direction={_gt_trend1['direction']}, data_points={_gt_trend1['data_points']}",
)

# Test 2: compute_gate_trend detects rising trend
_gt_snaps2 = [
    {"timestamp": 1, "gates": {"gate_01": {"avg_ms": 10, "p95_ms": 15, "count": 5}}},
    {"timestamp": 2, "gates": {"gate_01": {"avg_ms": 20, "p95_ms": 30, "count": 5}}},
    {"timestamp": 3, "gates": {"gate_01": {"avg_ms": 30, "p95_ms": 45, "count": 5}}},
]
_gt_trend2 = compute_gate_trend("gate_01", _gt_snaps2)
test(
    "GateTrend: compute_gate_trend detects rising trend",
    _gt_trend2["direction"] == "rising" and _gt_trend2["magnitude"] > 0,
    f"direction={_gt_trend2['direction']}, magnitude={_gt_trend2['magnitude']}",
)

# Test 3: compute_gate_trend detects falling trend
_gt_snaps3 = [
    {"timestamp": 1, "gates": {"gate_01": {"avg_ms": 50, "p95_ms": 60, "count": 5}}},
    {"timestamp": 2, "gates": {"gate_01": {"avg_ms": 30, "p95_ms": 40, "count": 5}}},
    {"timestamp": 3, "gates": {"gate_01": {"avg_ms": 10, "p95_ms": 15, "count": 5}}},
]
_gt_trend3 = compute_gate_trend("gate_01", _gt_snaps3)
test(
    "GateTrend: compute_gate_trend detects falling trend",
    _gt_trend3["direction"] == "falling" and _gt_trend3["magnitude"] < 0,
    f"direction={_gt_trend3['direction']}, magnitude={_gt_trend3['magnitude']}",
)

# Test 4: compute_gate_trend stable when values are constant
_gt_snaps4 = [
    {"timestamp": 1, "gates": {"gate_01": {"avg_ms": 10, "p95_ms": 15, "count": 5}}},
    {"timestamp": 2, "gates": {"gate_01": {"avg_ms": 10, "p95_ms": 15, "count": 5}}},
    {"timestamp": 3, "gates": {"gate_01": {"avg_ms": 10, "p95_ms": 15, "count": 5}}},
]
_gt_trend4 = compute_gate_trend("gate_01", _gt_snaps4)
test(
    "GateTrend: compute_gate_trend stable for constant values",
    _gt_trend4["direction"] == "stable",
    f"direction={_gt_trend4['direction']}",
)

# Test 5: get_trend_report returns expected structure
_gt_report = get_trend_report()
test(
    "GateTrend: get_trend_report has required keys",
    all(k in _gt_report for k in ("snapshot_count", "gates", "rising_gates", "falling_gates", "total_gates")),
    f"keys={set(_gt_report.keys())}",
)

# Test 6: compute_gate_trend for unknown gate returns stable
_gt_trend6 = compute_gate_trend("nonexistent_gate_xyz", _gt_snaps2)
test(
    "GateTrend: unknown gate returns stable with 0 data points",
    _gt_trend6["direction"] == "stable" and _gt_trend6["data_points"] == 0,
    f"direction={_gt_trend6['direction']}, data_points={_gt_trend6['data_points']}",
)

# ─────────────────────────────────────────────────
# Gate Dependency Graph Tests
# ─────────────────────────────────────────────────
print("\n--- Gate Dependency Graph ---")

from shared.gate_dependency_graph import (
    generate_mermaid_diagram,
    find_state_conflicts,
    find_parallel_safe_gates,
    get_state_hotspots,
    format_dependency_report,
)

# Test 1: generate_mermaid_diagram returns mermaid-formatted string
_gdg_mermaid = generate_mermaid_diagram()
test(
    "GateDependencyGraph: generate_mermaid_diagram returns mermaid string",
    isinstance(_gdg_mermaid, str) and "```mermaid" in _gdg_mermaid,
    f"starts with: {_gdg_mermaid[:50]!r}",
)

# Test 2: find_state_conflicts returns list
_gdg_conflicts = find_state_conflicts()
test(
    "GateDependencyGraph: find_state_conflicts returns list",
    isinstance(_gdg_conflicts, list),
    f"type={type(_gdg_conflicts).__name__}",
)

# Test 3: each conflict has required keys
_gdg_conflict_ok = True
for _c in _gdg_conflicts[:3]:
    if not (isinstance(_c, dict) and "key" in _c and "type" in _c and "gates" in _c):
        _gdg_conflict_ok = False
        break
test(
    "GateDependencyGraph: conflicts have required keys (key, type, gates)",
    _gdg_conflict_ok or len(_gdg_conflicts) == 0,
    f"sample={_gdg_conflicts[:1]}",
)

# Test 4: find_parallel_safe_gates returns expected structure
_gdg_parallel = find_parallel_safe_gates()
test(
    "GateDependencyGraph: find_parallel_safe_gates has required keys",
    isinstance(_gdg_parallel, dict)
    and "independent_gates" in _gdg_parallel
    and "conflict_pairs" in _gdg_parallel
    and "total_gates" in _gdg_parallel,
    f"keys={set(_gdg_parallel.keys())}",
)

# Test 5: get_state_hotspots returns sorted list of dicts
_gdg_hotspots = get_state_hotspots()
test(
    "GateDependencyGraph: get_state_hotspots returns list of dicts",
    isinstance(_gdg_hotspots, list)
    and (len(_gdg_hotspots) == 0 or (
        isinstance(_gdg_hotspots[0], dict)
        and "key" in _gdg_hotspots[0]
        and "total_gates" in _gdg_hotspots[0]
    )),
    f"sample={_gdg_hotspots[:1]}",
)

# Test 6: format_dependency_report returns string with header
_gdg_report = format_dependency_report()
test(
    "GateDependencyGraph: format_dependency_report returns report string",
    isinstance(_gdg_report, str) and "Gate Dependency Analysis" in _gdg_report,
    f"starts with: {_gdg_report[:50]!r}",
)

# ─── Rate Limiter Tests ──────────────────────────────────────────────
print("\n--- Rate Limiter ---")
from shared.rate_limiter import (
    allow as rl_allow, consume as rl_consume,
    get_remaining as rl_remaining, reset as rl_reset,
    get_all_limits, _config_for,
)

# Test 1: config_for returns correct presets
_rl_tool_cfg = _config_for("tool:Edit")
test("RateLimiter: tool: prefix uses TOOL_RATE (10, 10)",
     _rl_tool_cfg == (10.0, 10), f"got {_rl_tool_cfg}")

_rl_gate_cfg = _config_for("gate:gate_04")
test("RateLimiter: gate: prefix uses GATE_RATE (30, 30)",
     _rl_gate_cfg == (30.0, 30), f"got {_rl_gate_cfg}")

_rl_api_cfg = _config_for("api:memory")
test("RateLimiter: api: prefix uses API_RATE (60, 60)",
     _rl_api_cfg == (60.0, 60), f"got {_rl_api_cfg}")

# Test 2: reset and get_remaining
rl_reset("tool:__test_rl__")
_rl_rem = rl_remaining("tool:__test_rl__")
test("RateLimiter: reset gives full bucket (10 for tool:)",
     _rl_rem == 10, f"got {_rl_rem}")

# Test 3: consume decrements bucket
rl_reset("tool:__test_rl__")
_rl_ok = rl_consume("tool:__test_rl__")
test("RateLimiter: consume returns True when bucket has tokens", _rl_ok is True)
_rl_after = rl_remaining("tool:__test_rl__")
test("RateLimiter: remaining decremented after consume",
     _rl_after == 9, f"got {_rl_after}")

# Test 4: exhaust bucket → consume returns False
rl_reset("tool:__test_rl__")
for _ in range(10):
    rl_consume("tool:__test_rl__")
_rl_denied = rl_consume("tool:__test_rl__")
test("RateLimiter: consume returns False when bucket empty", _rl_denied is False)

# Test 5: allow checks without consuming
rl_reset("tool:__test_rl__")
_rl_check = rl_allow("tool:__test_rl__")
_rl_still = rl_remaining("tool:__test_rl__")
test("RateLimiter: allow does not consume tokens",
     _rl_check is True and _rl_still == 10, f"check={_rl_check}, rem={_rl_still}")

# Test 6: get_all_limits includes tracked keys
_rl_limits = get_all_limits()
test("RateLimiter: get_all_limits returns dict with expected keys",
     isinstance(_rl_limits, dict) and "tool:__test_rl__" in _rl_limits,
     f"keys={list(_rl_limits.keys())[:5]}")

# ─── Retry Strategy Tests ───────────────────────────────────────────
print("\n--- Retry Strategy ---")
from shared.retry_strategy import (
    should_retry as rs_should_retry,
    get_delay as rs_get_delay,
    record_attempt as rs_record_attempt,
    reset as rs_reset,
    get_stats as rs_get_stats,
    RetryConfig, Strategy, Jitter,
)

# Test 1: should_retry respects max_retries
rs_reset("__test_rs__")
_rs_cfg = RetryConfig(max_retries=2)
test("RetryStrategy: should_retry True before max failures",
     rs_should_retry("__test_rs__", config=_rs_cfg) is True)

rs_record_attempt("__test_rs__", success=False, config=_rs_cfg)
rs_record_attempt("__test_rs__", success=False, config=_rs_cfg)
test("RetryStrategy: should_retry False after max failures",
     rs_should_retry("__test_rs__", config=_rs_cfg) is False)

# Test 2: exponential backoff doubles
rs_reset("__test_exp__")
_rs_exp_cfg = RetryConfig(strategy=Strategy.EXPONENTIAL_BACKOFF,
                           base_delay=1.0, multiplier=2.0,
                           max_delay=100.0, jitter=Jitter.NONE)
_rs_delays = []
for _i in range(3):
    _rs_delays.append(rs_get_delay("__test_exp__", config=_rs_exp_cfg))
    rs_record_attempt("__test_exp__", success=False, config=_rs_exp_cfg)
test("RetryStrategy: exponential delays [1.0, 2.0, 4.0]",
     _rs_delays == [1.0, 2.0, 4.0], f"got {_rs_delays}")

# Test 3: constant strategy always returns base_delay
rs_reset("__test_const__")
_rs_const_cfg = RetryConfig(strategy=Strategy.CONSTANT, base_delay=3.0, jitter=Jitter.NONE)
_rs_const_d = rs_get_delay("__test_const__", config=_rs_const_cfg)
test("RetryStrategy: constant delay == base_delay (3.0)",
     abs(_rs_const_d - 3.0) < 1e-9, f"got {_rs_const_d}")

# Test 4: get_stats returns correct counters
rs_reset("__test_stats__")
_rs_s_cfg = RetryConfig(max_retries=10)
rs_record_attempt("__test_stats__", success=True, config=_rs_s_cfg)
rs_record_attempt("__test_stats__", success=False, error="boom", config=_rs_s_cfg)
_rs_stats = rs_get_stats("__test_stats__")
test("RetryStrategy: get_stats has correct attempt/success/failure counts",
     _rs_stats.get("attempts") == 2 and _rs_stats.get("successes") == 1
     and _rs_stats.get("failures") == 1,
     f"got {_rs_stats}")

# Test 5: full jitter within bounds
rs_reset("__test_jitter__")
_rs_jit_cfg = RetryConfig(strategy=Strategy.CONSTANT, base_delay=5.0, jitter=Jitter.FULL)
_rs_jit_vals = [rs_get_delay("__test_jitter__", config=_rs_jit_cfg) for _ in range(20)]
test("RetryStrategy: full jitter delays in [0, 5.0]",
     all(0.0 <= d <= 5.0 + 1e-9 for d in _rs_jit_vals),
     f"range=[{min(_rs_jit_vals):.2f}, {max(_rs_jit_vals):.2f}]")

# Test 6: reset clears state
rs_reset("__test_reset__")
rs_record_attempt("__test_reset__", success=False)
rs_reset("__test_reset__")
_rs_reset_stats = rs_get_stats("__test_reset__")
test("RetryStrategy: reset clears attempts to 0",
     _rs_reset_stats.get("attempts") == 0, f"got {_rs_reset_stats.get('attempts')}")

# ─── Memory Decay Tests ─────────────────────────────────────────────
print("\n--- Memory Decay ---")
from shared.memory_decay import (
    calculate_relevance_score, rank_memories,
    identify_stale_memories, _time_decay_factor,
    _access_boost, _tag_relevance_bonus,
    TIER_BASE, DEFAULT_HALF_LIFE_DAYS,
)
from datetime import datetime, timezone, timedelta

# Test 1: fresh T1 memory scores near 1.0
_md_fresh = {
    "tier": 1,
    "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    "retrieval_count": 0,
    "tags": "",
}
_md_fresh_score = calculate_relevance_score(_md_fresh)
test("MemoryDecay: fresh T1 memory scores >= 0.9",
     _md_fresh_score >= 0.9, f"got {_md_fresh_score:.3f}")

# Test 2: old T3 memory scores low
_md_old = {
    "tier": 3,
    "timestamp": (datetime.now(tz=timezone.utc) - timedelta(days=180)).isoformat(),
    "retrieval_count": 0,
    "tags": "",
}
_md_old_score = calculate_relevance_score(_md_old)
test("MemoryDecay: 180-day old T3 memory scores < 0.15",
     _md_old_score < 0.15, f"got {_md_old_score:.3f}")

# Test 3: time_decay_factor at half-life is ~0.5
_md_decay = _time_decay_factor(DEFAULT_HALF_LIFE_DAYS)
test("MemoryDecay: decay factor at half-life is ~0.5",
     abs(_md_decay - 0.5) < 0.01, f"got {_md_decay:.4f}")

# Test 4: access_boost increases with retrieval count
_md_boost_0 = _access_boost(0)
_md_boost_10 = _access_boost(10)
test("MemoryDecay: access_boost(10) > access_boost(0)",
     _md_boost_10 > _md_boost_0,
     f"boost(0)={_md_boost_0:.3f}, boost(10)={_md_boost_10:.3f}")

# Test 5: rank_memories sorts by relevance descending
_md_entries = [
    {"tier": 3, "timestamp": (datetime.now(tz=timezone.utc) - timedelta(days=100)).isoformat(),
     "retrieval_count": 0, "tags": ""},
    {"tier": 1, "timestamp": datetime.now(tz=timezone.utc).isoformat(),
     "retrieval_count": 5, "tags": ""},
]
_md_ranked = rank_memories(_md_entries)
test("MemoryDecay: rank_memories sorts descending by relevance",
     len(_md_ranked) == 2
     and _md_ranked[0]["_relevance_score"] >= _md_ranked[1]["_relevance_score"],
     f"scores=[{_md_ranked[0]['_relevance_score']:.2f}, {_md_ranked[1]['_relevance_score']:.2f}]")

# Test 6: identify_stale_memories returns low-relevance entries
_md_stale = identify_stale_memories(_md_entries, threshold=0.5)
test("MemoryDecay: identify_stale_memories finds old low-tier entries",
     len(_md_stale) >= 1 and all(s["_relevance_score"] < 0.5 for s in _md_stale),
     f"stale_count={len(_md_stale)}")

# Test 7: tag_relevance_bonus for matching tags
_md_tag_bonus = _tag_relevance_bonus("framework,testing,gate", "framework,testing")
test("MemoryDecay: tag_relevance_bonus > 0 for matching tags",
     _md_tag_bonus > 0, f"got {_md_tag_bonus:.3f}")

# ─── Gate Health Tests ───────────────────────────────────────────────
print("\n--- Gate Health ---")
from shared.gate_health import get_gate_health_report, format_health_dashboard

# Test 1: health report returns expected structure
_gh_report = get_gate_health_report()
test("GateHealth: report has health_score key",
     isinstance(_gh_report, dict) and "health_score" in _gh_report,
     f"keys={set(_gh_report.keys())}")

# Test 2: health_score is 0-100
test("GateHealth: health_score is int in [0, 100]",
     isinstance(_gh_report["health_score"], int)
     and 0 <= _gh_report["health_score"] <= 100,
     f"got {_gh_report['health_score']}")

# Test 3: report has gate_count
test("GateHealth: report has gate_count >= 0",
     "gate_count" in _gh_report and _gh_report["gate_count"] >= 0,
     f"gate_count={_gh_report.get('gate_count')}")

# Test 4: report has slow_gates list
test("GateHealth: slow_gates is a list",
     isinstance(_gh_report.get("slow_gates"), list),
     f"type={type(_gh_report.get('slow_gates')).__name__}")

# Test 5: format_health_dashboard returns string with score
_gh_dashboard = format_health_dashboard()
test("GateHealth: format_health_dashboard returns string with Score",
     isinstance(_gh_dashboard, str) and "Score:" in _gh_dashboard,
     f"starts={_gh_dashboard[:60]!r}")

# ─── Skill Health Tests ──────────────────────────────────────────────
print("\n--- Skill Health ---")
from shared.skill_health import check_all_skills, get_broken_skills, format_health_report as sh_format

# Test 1: check_all_skills returns expected structure
_sh_report = check_all_skills()
test("SkillHealth: check_all_skills has total_skills key",
     isinstance(_sh_report, dict) and "total_skills" in _sh_report,
     f"keys={set(_sh_report.keys())}")

# Test 2: total_skills is positive (we have skills/)
test("SkillHealth: total_skills > 0",
     _sh_report["total_skills"] > 0,
     f"total={_sh_report['total_skills']}")

# Test 3: healthy_skills <= total_skills
test("SkillHealth: healthy_skills <= total_skills",
     _sh_report["healthy_skills"] <= _sh_report["total_skills"],
     f"healthy={_sh_report['healthy_skills']}, total={_sh_report['total_skills']}")

# Test 4: get_broken_skills returns list
_sh_broken = get_broken_skills()
test("SkillHealth: get_broken_skills returns list",
     isinstance(_sh_broken, list), f"type={type(_sh_broken).__name__}")

# Test 5: format_health_report returns string
_sh_formatted = sh_format(_sh_report)
test("SkillHealth: format_health_report returns non-empty string",
     isinstance(_sh_formatted, str) and len(_sh_formatted) > 20,
     f"len={len(_sh_formatted)}")

# ─── Hook Profiler Tests ─────────────────────────────────────────────
print("\n--- Hook Profiler ---")
from shared.hook_profiler import profile, analyze, report as hp_report, _percentile

# Test 1: profile wraps a function and returns result
def _hp_fake_check(tool_name, tool_input, state, event_type="PreToolUse"):
    class _R:
        blocked = False
    return _R()

_hp_wrapped = profile("__test_gate__", _hp_fake_check)
_hp_result = _hp_wrapped("Edit", {}, {})
test("HookProfiler: profile wraps function and returns gate result",
     hasattr(_hp_result, "blocked") and _hp_result.blocked is False)

# Test 2: wrapped function has _profiler_wrapped attribute
test("HookProfiler: wrapped function has _profiler_wrapped=True",
     getattr(_hp_wrapped, "_profiler_wrapped", False) is True)

# Test 3: _percentile handles empty list
_hp_p_empty = _percentile([], 50)
test("HookProfiler: _percentile returns 0.0 for empty list",
     _hp_p_empty == 0.0, f"got {_hp_p_empty}")

# Test 4: _percentile computes correct p50
_hp_p50 = _percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 50)
test("HookProfiler: _percentile p50 of [1..10] is 5",
     _hp_p50 == 5, f"got {_hp_p50}")

# Test 5: analyze returns dict
_hp_stats = analyze()
test("HookProfiler: analyze returns dict",
     isinstance(_hp_stats, dict), f"type={type(_hp_stats).__name__}")

# Test 6: report returns string
_hp_rpt = hp_report()
test("HookProfiler: report returns string",
     isinstance(_hp_rpt, str), f"type={type(_hp_rpt).__name__}")

# ─── Tool Patterns Tests ─────────────────────────────────────────────
print("\n--- Tool Patterns ---")
from shared.tool_patterns import (
    build_markov_chain, predict_next_tool,
    get_workflow_templates, detect_unusual_sequence,
    get_transition_matrix, get_tool_stats, summarize_patterns,
)

# Test 1: build_markov_chain from sequences
_tp_seqs = [["Read", "Edit", "Bash"], ["Read", "Edit", "Read"], ["Bash", "Read", "Edit"]]
_tp_chain = build_markov_chain(_tp_seqs)
test("ToolPatterns: build_markov_chain returns object with transitions",
     hasattr(_tp_chain, "transitions") and isinstance(_tp_chain.transitions, dict),
     f"type={type(_tp_chain).__name__}")

# Test 2: chain has correct vocabulary
test("ToolPatterns: markov chain vocabulary includes Read, Edit, Bash",
     {"Read", "Edit", "Bash"}.issubset(_tp_chain.vocabulary),
     f"vocab={_tp_chain.vocabulary}")

# Test 3: chain tracks sequence count
test("ToolPatterns: markov chain sequence_count == 3",
     _tp_chain.sequence_count == 3, f"got {_tp_chain.sequence_count}")

# Test 4: predict_next_tool returns list of tuples
_tp_preds = predict_next_tool(["Read", "Edit"])
test("ToolPatterns: predict_next_tool returns list",
     isinstance(_tp_preds, list), f"type={type(_tp_preds).__name__}")

# Test 5: get_tool_stats returns dict
_tp_stats = get_tool_stats()
test("ToolPatterns: get_tool_stats returns dict",
     isinstance(_tp_stats, dict), f"type={type(_tp_stats).__name__}")

# Test 6: summarize_patterns returns dict with expected keys
_tp_summary = summarize_patterns()
test("ToolPatterns: summarize_patterns returns dict with vocabulary_size",
     isinstance(_tp_summary, dict) and "vocabulary_size" in _tp_summary,
     f"keys={set(_tp_summary.keys())}")

# ─── Error Pattern Analyzer Tests ────────────────────────────────────
print("\n--- Error Pattern Analyzer ---")
from shared.error_pattern_analyzer import (
    extract_pattern, analyze_errors, top_patterns as ep_top_patterns,
    suggest_prevention, frequency_from_strings, correlate_errors,
)

# Test 1: extract_pattern recognizes ImportError
_ep_import = extract_pattern("ImportError: No module named 'foobar'")
test("ErrorPatternAnalyzer: extract_pattern identifies import error",
     "import" in _ep_import.lower(), f"got {_ep_import!r}")

# Test 2: extract_pattern recognizes gate blocks
_ep_gate = extract_pattern("You must Read 'file.py' before editing it")
test("ErrorPatternAnalyzer: extract_pattern identifies gate1 block",
     _ep_gate == "gate1:read-before-edit",
     f"got {_ep_gate!r}")

# Test 3: suggest_prevention returns string
_ep_sug = suggest_prevention(_ep_import)
test("ErrorPatternAnalyzer: suggest_prevention returns non-empty string",
     isinstance(_ep_sug, str) and len(_ep_sug) > 0, f"got {_ep_sug!r}")

# Test 4: frequency_from_strings counts patterns
_ep_freq = frequency_from_strings([
    "ImportError: no module named x",
    "ImportError: no module named y",
    "SyntaxError: invalid syntax",
])
test("ErrorPatternAnalyzer: frequency_from_strings returns dict with counts",
     isinstance(_ep_freq, dict) and len(_ep_freq) >= 1,
     f"got {_ep_freq}")

# Test 5: analyze_errors returns structured report
_ep_analysis = analyze_errors([])
test("ErrorPatternAnalyzer: analyze_errors({}) returns dict with total_errors",
     isinstance(_ep_analysis, dict) and "total_errors" in _ep_analysis,
     f"keys={set(_ep_analysis.keys())}")

# Test 6: correlate_errors returns list
_ep_corr = correlate_errors([])
test("ErrorPatternAnalyzer: correlate_errors({}) returns list",
     isinstance(_ep_corr, list), f"type={type(_ep_corr).__name__}")

# ─── Gate Correlation Tests ──────────────────────────────────────────
print("\n--- Gate Correlation ---")
from shared.gate_correlation import analyze_correlations, format_correlation_report

# Test 1: analyze_correlations returns expected structure
_gc_data = analyze_correlations(days=1)
test("GateCorrelation: analyze_correlations returns dict with pairs key",
     isinstance(_gc_data, dict) and "pairs" in _gc_data,
     f"keys={set(_gc_data.keys())}")

# Test 2: pairs is a list
test("GateCorrelation: pairs is a list",
     isinstance(_gc_data.get("pairs"), list),
     f"type={type(_gc_data.get('pairs')).__name__}")

# Test 3: gate_block_counts is a dict
test("GateCorrelation: gate_block_counts is a dict",
     isinstance(_gc_data.get("gate_block_counts"), dict),
     f"type={type(_gc_data.get('gate_block_counts')).__name__}")

# Test 4: total_events is an int >= 0
test("GateCorrelation: total_events >= 0",
     isinstance(_gc_data.get("total_events"), int)
     and _gc_data["total_events"] >= 0,
     f"got {_gc_data.get('total_events')}")

# Test 5: format_correlation_report returns string
_gc_report = format_correlation_report(_gc_data)
test("GateCorrelation: format_correlation_report returns string",
     isinstance(_gc_report, str), f"type={type(_gc_report).__name__}")

# ─── Domain Registry Tests ───────────────────────────────────────────
print("\n--- Domain Registry ---")
from shared.domain_registry import (
    list_domains, get_active_domain, load_domain_profile,
    DEFAULT_PROFILE, DOMAINS_DIR,
)

# Test 1: list_domains returns list
_dr_domains = list_domains()
test("DomainRegistry: list_domains returns list",
     isinstance(_dr_domains, list), f"type={type(_dr_domains).__name__}")

# Test 2: each domain has expected keys
_dr_keys_ok = True
for _d in _dr_domains[:3]:
    if not all(k in _d for k in ("name", "active", "graduated", "has_mastery")):
        _dr_keys_ok = False
        break
test("DomainRegistry: domain entries have expected keys",
     _dr_keys_ok or len(_dr_domains) == 0,
     f"sample={_dr_domains[:1]}")

# Test 3: get_active_domain returns str or None
_dr_active = get_active_domain()
test("DomainRegistry: get_active_domain returns str or None",
     _dr_active is None or isinstance(_dr_active, str),
     f"type={type(_dr_active).__name__}")

# Test 4: DEFAULT_PROFILE has expected keys
test("DomainRegistry: DEFAULT_PROFILE has gate_modes key",
     "gate_modes" in DEFAULT_PROFILE and "security_profile" in DEFAULT_PROFILE,
     f"keys={set(DEFAULT_PROFILE.keys())}")

# Test 5: load_domain_profile for non-existent domain returns defaults
_dr_fake = load_domain_profile("__nonexistent_domain__")
test("DomainRegistry: load_domain_profile for missing domain returns dict",
     isinstance(_dr_fake, dict), f"type={type(_dr_fake).__name__}")

# ─── State Migrator Tests ────────────────────────────────────────────
print("\n--- State Migrator ---")
from shared.state_migrator import migrate_state, validate_state, get_schema_diff
from shared.state import default_state, STATE_VERSION

# Test 1: migrate_state adds missing fields
_sm_minimal = {"_version": 1, "files_read": []}
_sm_migrated = migrate_state(_sm_minimal)
test("StateMigrator: migrate_state adds missing fields",
     len(_sm_migrated) > len(_sm_minimal),
     f"minimal={len(_sm_minimal)}, migrated={len(_sm_migrated)}")

# Test 2: migrated state has correct version
test("StateMigrator: migrated state has current STATE_VERSION",
     _sm_migrated["_version"] == STATE_VERSION,
     f"got {_sm_migrated.get('_version')}, expected {STATE_VERSION}")

# Test 3: validate_state for default state — allow known nullable fields
_sm_default = default_state()
_sm_valid, _sm_errors, _sm_warnings = validate_state(_sm_default)
# Some fields may default to None (e.g. mentor_memory_match) — filter those
_sm_real_errors = [e for e in _sm_errors if "NoneType" not in e]
test("StateMigrator: default_state() passes validation (ignoring nullable fields)",
     len(_sm_real_errors) == 0,
     f"errors={_sm_real_errors[:3]}")

# Test 4: validate_state fails for non-dict
_sm_bad_valid, _sm_bad_errors, _ = validate_state("not a dict")
test("StateMigrator: validate_state rejects non-dict",
     _sm_bad_valid is False and len(_sm_bad_errors) > 0)

# Test 5: get_schema_diff detects missing fields
_sm_diff = get_schema_diff({"_version": 1})
test("StateMigrator: get_schema_diff finds missing fields",
     isinstance(_sm_diff, dict) and len(_sm_diff.get("missing_fields", [])) > 0,
     f"missing_count={len(_sm_diff.get('missing_fields', []))}")

# Test 6: migrate_state on non-dict returns default
_sm_non_dict = migrate_state("invalid")
test("StateMigrator: migrate_state on non-dict returns default_state",
     isinstance(_sm_non_dict, dict) and "_version" in _sm_non_dict)

# ─── Plugin Registry Tests ──────────────────────────────────────────
print("\n--- Plugin Registry ---")
from shared.plugin_registry import (
    scan_plugins, get_plugin, is_enabled,
    get_by_category, validate_plugin,
    KNOWN_CATEGORIES, _infer_category,
)

# Test 1: scan_plugins returns list
_pr_plugins = scan_plugins()
test("PluginRegistry: scan_plugins returns list",
     isinstance(_pr_plugins, list), f"type={type(_pr_plugins).__name__}")

# Test 2: plugins have expected keys
_pr_keys_ok = True
for _p in _pr_plugins[:3]:
    if not all(k in _p for k in ("name", "version", "category", "enabled", "path")):
        _pr_keys_ok = False
        break
test("PluginRegistry: plugin entries have expected keys",
     _pr_keys_ok or len(_pr_plugins) == 0,
     f"sample_keys={set(_pr_plugins[0].keys()) if _pr_plugins else 'empty'}")

# Test 3: _infer_category categorizes correctly
_pr_cat = _infer_category("code-review", "automated code review tool")
test("PluginRegistry: _infer_category(code-review) -> quality",
     _pr_cat == "quality", f"got {_pr_cat!r}")

# Test 4: _infer_category for security
_pr_sec_cat = _infer_category("vulnerability-scanner", "finds security vulnerabilities")
test("PluginRegistry: _infer_category(vulnerability-scanner) -> security",
     _pr_sec_cat == "security", f"got {_pr_sec_cat!r}")

# Test 5: KNOWN_CATEGORIES includes quality, security, development
test("PluginRegistry: KNOWN_CATEGORIES has expected entries",
     "quality" in KNOWN_CATEGORIES
     and "security" in KNOWN_CATEGORIES
     and "development" in KNOWN_CATEGORIES,
     f"categories={KNOWN_CATEGORIES}")

# Test 6: get_by_category returns list
_pr_dev = get_by_category("development")
test("PluginRegistry: get_by_category returns list",
     isinstance(_pr_dev, list), f"type={type(_pr_dev).__name__}")

# Test 7: validate_plugin on non-existent path returns (False, errors)
_pr_valid, _pr_errs = validate_plugin("/tmp/__nonexistent_plugin_path__")
test("PluginRegistry: validate_plugin on missing path returns (False, errors)",
     _pr_valid is False and len(_pr_errs) > 0,
     f"valid={_pr_valid}, errors={_pr_errs[:2]}")

# ─── Session Analytics Tests ─────────────────────────────────────────
print("\n--- Session Analytics ---")
from shared.session_analytics import (
    get_session_summary, tool_call_distribution,
    gate_fire_rates, gate_block_rates, error_frequency,
    session_productivity,
)

# Test 1: get_session_summary returns dict
_sa_summary = get_session_summary()
test("SessionAnalytics: get_session_summary returns dict",
     isinstance(_sa_summary, dict), f"type={type(_sa_summary).__name__}")

# Test 2: tool_call_distribution with empty input
_sa_tcd = tool_call_distribution([])
test("SessionAnalytics: tool_call_distribution({}) returns empty dict",
     isinstance(_sa_tcd, dict) and len(_sa_tcd) == 0,
     f"got {_sa_tcd}")

# Test 3: tool_call_distribution with entries
_sa_entries = [{"tool": "Edit"}, {"tool": "Edit"}, {"tool": "Bash"}, {"tool": "Read"}]
_sa_tcd2 = tool_call_distribution(_sa_entries)
test("SessionAnalytics: tool_call_distribution counts correctly",
     _sa_tcd2.get("Edit", 0) == 2 and _sa_tcd2.get("Bash", 0) == 1,
     f"got {_sa_tcd2}")

# Test 4: gate_fire_rates with empty input
_sa_gfr = gate_fire_rates([])
test("SessionAnalytics: gate_fire_rates({}) returns empty dict",
     isinstance(_sa_gfr, dict), f"type={type(_sa_gfr).__name__}")

# Test 5: session_productivity with empty input
_sa_prod = session_productivity([], 60.0)
test("SessionAnalytics: session_productivity returns dict with score",
     isinstance(_sa_prod, dict) and "score" in _sa_prod,
     f"keys={set(_sa_prod.keys())}")

# ─── Session Compressor Tests ────────────────────────────────────────
print("\n--- Session Compressor ---")
from shared.session_compressor import (
    compress_session_context, extract_key_decisions, format_handoff,
)

# Test 1: compress_session_context on empty state
_sc_compressed = compress_session_context({})
test("SessionCompressor: compress_session_context({}) returns string",
     isinstance(_sc_compressed, str), f"type={type(_sc_compressed).__name__}")

# Test 2: compress with a real default state (empty state may compress to empty)
_sc_state = default_state()
_sc_result = compress_session_context(_sc_state, max_tokens=200)
test("SessionCompressor: compress returns string (may be empty for fresh state)",
     isinstance(_sc_result, str),
     f"len={len(_sc_result)}")

# Test 3: extract_key_decisions returns list
_sc_decisions = extract_key_decisions(_sc_state)
test("SessionCompressor: extract_key_decisions returns list",
     isinstance(_sc_decisions, list), f"type={type(_sc_decisions).__name__}")

# Test 4: format_handoff returns string
_sc_handoff = format_handoff(_sc_state, _sc_decisions)
test("SessionCompressor: format_handoff returns string",
     isinstance(_sc_handoff, str), f"type={type(_sc_handoff).__name__}")

# ─── Agent Channel Tests ─────────────────────────────────────────────
print("\n--- Agent Channel ---")
from shared.agent_channel import post_message, read_messages, cleanup

# Test 1: post_message returns bool
_ac_ok = post_message("__test_agent__", "status", "test message")
test("AgentChannel: post_message returns bool",
     isinstance(_ac_ok, bool), f"type={type(_ac_ok).__name__}")

# Test 2: read_messages returns list
import time as _ac_time
_ac_msgs = read_messages(since_ts=_ac_time.time() - 60)
test("AgentChannel: read_messages returns list",
     isinstance(_ac_msgs, list), f"type={type(_ac_msgs).__name__}")

# Test 3: cleanup returns int
_ac_cleaned = cleanup(max_age_hours=0)  # Clean everything
test("AgentChannel: cleanup returns int (count deleted)",
     isinstance(_ac_cleaned, int), f"type={type(_ac_cleaned).__name__}")

# ─── Gate Pruner Tests ───────────────────────────────────────────────
print("\n--- Gate Pruner ---")
from shared.gate_pruner import analyze_gates, get_prune_recommendations, render_pruner_report

# Test 1: analyze_gates returns dict
_gp_analysis = analyze_gates()
test("GatePruner: analyze_gates returns dict",
     isinstance(_gp_analysis, dict), f"type={type(_gp_analysis).__name__}")

# Test 2: each analysis entry has expected fields
_gp_ok = True
for _g, _a in list(_gp_analysis.items())[:3]:
    if not hasattr(_a, "verdict"):
        _gp_ok = False
        break
test("GatePruner: analysis entries have verdict attribute",
     _gp_ok or len(_gp_analysis) == 0,
     f"sample_type={type(list(_gp_analysis.values())[0]).__name__ if _gp_analysis else 'empty'}")

# Test 3: get_prune_recommendations returns list
_gp_recs = get_prune_recommendations()
test("GatePruner: get_prune_recommendations returns list",
     isinstance(_gp_recs, list), f"type={type(_gp_recs).__name__}")

# Test 4: render_pruner_report returns string
_gp_report = render_pruner_report()
test("GatePruner: render_pruner_report returns non-empty string",
     isinstance(_gp_report, str) and len(_gp_report) > 10,
     f"len={len(_gp_report)}")

# ─── Gate Dashboard Tests ────────────────────────────────────────────
print("\n--- Gate Dashboard ---")
from shared.gate_dashboard import (
    get_gate_metrics, rank_gates_by_value,
    render_dashboard as gd_render, get_recommendations,
)

# Test 1: get_gate_metrics returns dict
_gd_metrics = get_gate_metrics()
test("GateDashboard: get_gate_metrics returns dict",
     isinstance(_gd_metrics, dict), f"type={type(_gd_metrics).__name__}")

# Test 2: rank_gates_by_value returns list of tuples
_gd_ranked = rank_gates_by_value()
test("GateDashboard: rank_gates_by_value returns list",
     isinstance(_gd_ranked, list), f"type={type(_gd_ranked).__name__}")

# Test 3: render_dashboard returns string
_gd_dash = gd_render()
test("GateDashboard: render_dashboard returns string",
     isinstance(_gd_dash, str), f"type={type(_gd_dash).__name__}")

# Test 4: get_recommendations returns list of strings
_gd_recs = get_recommendations()
test("GateDashboard: get_recommendations returns list",
     isinstance(_gd_recs, list), f"type={type(_gd_recs).__name__}")

# ─── Metrics Exporter Tests ──────────────────────────────────────────
print("\n--- Metrics Exporter ---")
from shared.metrics_exporter import export_prometheus, export_json

# Test 1: export_json returns dict with metrics key
_me_json = export_json()
test("MetricsExporter: export_json returns dict with metrics key",
     isinstance(_me_json, dict) and "metrics" in _me_json,
     f"keys={set(_me_json.keys())}")

# Test 2: export_prometheus returns non-empty string
_me_prom = export_prometheus()
test("MetricsExporter: export_prometheus returns string",
     isinstance(_me_prom, str), f"type={type(_me_prom).__name__}")

# Test 3: export_json has exported_at timestamp
test("MetricsExporter: export_json has exported_at field",
     "exported_at" in _me_json, f"keys={set(_me_json.keys())}")

# ─── Experience Archive Tests ────────────────────────────────────────
print("\n--- Experience Archive ---")
from shared.experience_archive import (
    record_fix, query_best_strategy, get_success_rate, get_archive_stats,
)

# Test 1: record_fix returns bool
_ea_ok = record_fix("ImportError", "pip_install", "success", file="test.py")
test("ExperienceArchive: record_fix returns bool",
     isinstance(_ea_ok, bool), f"type={type(_ea_ok).__name__}")

# Test 2: get_archive_stats returns dict
_ea_stats = get_archive_stats()
test("ExperienceArchive: get_archive_stats returns dict",
     isinstance(_ea_stats, dict), f"type={type(_ea_stats).__name__}")

# Test 3: get_archive_stats has total_rows key
test("ExperienceArchive: stats has total_rows key",
     "total_rows" in _ea_stats, f"keys={set(_ea_stats.keys())}")

# Test 4: query_best_strategy returns string
_ea_best = query_best_strategy("ImportError")
test("ExperienceArchive: query_best_strategy returns string",
     isinstance(_ea_best, str), f"type={type(_ea_best).__name__}")

# Test 5: get_success_rate returns float in [0, 1]
_ea_rate = get_success_rate("pip_install")
test("ExperienceArchive: get_success_rate returns float in [0,1]",
     isinstance(_ea_rate, float) and 0.0 <= _ea_rate <= 1.0,
     f"got {_ea_rate}")

# ─── Memory Maintenance Tests ────────────────────────────────────────
print("\n--- Memory Maintenance ---")
from shared.memory_maintenance import analyze_memory_health, cleanup_candidates

# Test 1: analyze_memory_health returns dict
_mm_health = analyze_memory_health()
test("MemoryMaintenance: analyze_memory_health returns dict",
     isinstance(_mm_health, dict), f"type={type(_mm_health).__name__}")

# Test 2: health report has summary key
test("MemoryMaintenance: health report has summary key",
     "summary" in _mm_health,
     f"keys={set(_mm_health.keys())}")

# Test 3: cleanup_candidates returns list
_mm_candidates = cleanup_candidates()
test("MemoryMaintenance: cleanup_candidates returns list",
     isinstance(_mm_candidates, list), f"type={type(_mm_candidates).__name__}")

# Test 4: each cleanup candidate is a dict (if any)
_mm_cand_ok = all(isinstance(c, dict) for c in _mm_candidates[:5])
test("MemoryMaintenance: cleanup candidates are dicts",
     _mm_cand_ok or len(_mm_candidates) == 0,
     f"sample_type={type(_mm_candidates[0]).__name__ if _mm_candidates else 'empty'}")

# ─── Rules Validator Tests ───────────────────────────────────────────
print("\n--- Rules Validator ---")
from shared.rules_validator import validate_rules

# Test 1: validate_rules returns dict
_rv_report = validate_rules()
test("RulesValidator: validate_rules returns dict",
     isinstance(_rv_report, dict), f"type={type(_rv_report).__name__}")

# Test 2: report has total and valid keys
test("RulesValidator: report has total and valid keys",
     "total" in _rv_report and "valid" in _rv_report,
     f"keys={set(_rv_report.keys())}")

# Test 3: total is int, valid is list or int
_rv_total = _rv_report.get("total", 0)
_rv_valid = _rv_report.get("valid", [])
_rv_valid_count = len(_rv_valid) if isinstance(_rv_valid, list) else _rv_valid
test("RulesValidator: total >= valid count",
     isinstance(_rv_total, int) and _rv_total >= _rv_valid_count,
     f"total={_rv_total}, valid_count={_rv_valid_count}")

# Test 4: report has issues field (dict or list)
test("RulesValidator: report has issues field",
     "issues" in _rv_report and isinstance(_rv_report["issues"], (list, dict)),
     f"type={type(_rv_report.get('issues')).__name__}")

# ─── Search Cache Tests ──────────────────────────────────────────────
print("\n--- Search Cache ---")
from shared.search_cache import SearchCache

# Test 1: constructor works with defaults
_sc_cache = SearchCache()
test("SearchCache: constructor creates cache with 0 entries",
     len(_sc_cache) == 0, f"len={len(_sc_cache)}")

# Test 2: put and get work
_sc_key = _sc_cache.make_key("test query", n=5)
_sc_cache.put(_sc_key, {"result": "data"})
_sc_got = _sc_cache.get(_sc_key)
test("SearchCache: put then get returns same value",
     _sc_got == {"result": "data"}, f"got {_sc_got!r}")

# Test 3: get on missing key returns None
_sc_miss = _sc_cache.get("nonexistent_key_1234567890")
test("SearchCache: get on missing key returns None",
     _sc_miss is None, f"got {_sc_miss!r}")

# Test 4: stats returns dict with hit_rate
_sc_stats = _sc_cache.stats()
test("SearchCache: stats has hit_rate key",
     isinstance(_sc_stats, dict) and "hit_rate" in _sc_stats,
     f"keys={set(_sc_stats.keys())}")

# Test 5: invalidate clears cache
_sc_cache.invalidate()
test("SearchCache: invalidate clears all entries",
     len(_sc_cache) == 0, f"len={len(_sc_cache)}")

# ─── Config Validator Tests ──────────────────────────────────────────
print("\n--- Config Validator ---")
from shared.config_validator import validate_all, validate_settings, validate_gates

# Test 1: validate_all returns dict with expected keys
_cv_report = validate_all()
test("ConfigValidator: validate_all returns dict",
     isinstance(_cv_report, dict), f"type={type(_cv_report).__name__}")

# Test 2: report has settings key
test("ConfigValidator: report has settings key",
     "settings" in _cv_report, f"keys={set(_cv_report.keys())}")

# Test 3: validate_settings returns list
_cv_settings = validate_settings()
test("ConfigValidator: validate_settings returns list",
     isinstance(_cv_settings, list), f"type={type(_cv_settings).__name__}")

# Test 4: validate_gates returns list
_cv_gates = validate_gates()
test("ConfigValidator: validate_gates returns list",
     isinstance(_cv_gates, list), f"type={type(_cv_gates).__name__}")

# ─── Gate Registry Tests ─────────────────────────────────────────────
print("\n--- Gate Registry ---")
from shared.gate_registry import GATE_MODULES as gr_GATE_MODULES

# Test 1: GATE_MODULES is a non-empty list
test("GateRegistry: GATE_MODULES is non-empty list",
     isinstance(gr_GATE_MODULES, list) and len(gr_GATE_MODULES) > 0,
     f"len={len(gr_GATE_MODULES)}")

# Test 2: all entries are strings starting with "gates."
_gr_ok = all(isinstance(m, str) and m.startswith("gates.") for m in gr_GATE_MODULES)
test("GateRegistry: all modules start with 'gates.'",
     _gr_ok, f"sample={gr_GATE_MODULES[:3]}")

# Test 3: contains gate_01 and gate_02 (Tier 1 safety)
_gr_has_t1 = any("gate_01" in m for m in gr_GATE_MODULES) and any("gate_02" in m for m in gr_GATE_MODULES)
test("GateRegistry: includes Tier 1 safety gates (01, 02)",
     _gr_has_t1, f"modules={gr_GATE_MODULES[:5]}")

# ─── Tool Fingerprint Tests ──────────────────────────────────────────
print("\n--- Tool Fingerprint ---")
from shared.tool_fingerprint import (
    fingerprint_tool, register_tool, check_tool_integrity,
    get_all_fingerprints, get_changed_tools,
)

# Test 1: fingerprint_tool returns hex string
_tf_fp = fingerprint_tool("__test_tool__", "A test tool", {"param1": "str"})
test("ToolFingerprint: fingerprint_tool returns hex string",
     isinstance(_tf_fp, str) and len(_tf_fp) == 64,
     f"len={len(_tf_fp)}, value={_tf_fp[:16]}...")

# Test 2: same input produces same fingerprint
_tf_fp2 = fingerprint_tool("__test_tool__", "A test tool", {"param1": "str"})
test("ToolFingerprint: deterministic fingerprinting",
     _tf_fp == _tf_fp2)

# Test 3: different input produces different fingerprint
_tf_fp3 = fingerprint_tool("__other_tool__", "Different tool", {})
test("ToolFingerprint: different tools get different fingerprints",
     _tf_fp != _tf_fp3)

# Test 4: register_tool returns tuple
_tf_reg = register_tool("__test_reg_tool__", "test", {})
test("ToolFingerprint: register_tool returns 4-tuple",
     isinstance(_tf_reg, tuple) and len(_tf_reg) == 4,
     f"type={type(_tf_reg).__name__}, len={len(_tf_reg)}")

# Test 5: get_all_fingerprints returns dict
_tf_all = get_all_fingerprints()
test("ToolFingerprint: get_all_fingerprints returns dict",
     isinstance(_tf_all, dict), f"type={type(_tf_all).__name__}")

print("\n--- Code Hotspot ---")

try:
    from shared.code_hotspot import (
        extract_file_path, analyze_file_blocks,
        rank_files_by_risk, export_hotspot_report,
    )

    # extract_file_path: Edit tool
    _ch_edit = extract_file_path({"file_path": "/home/user/test.py"}, "Edit")
    test("Hotspot: extract Edit file_path",
         _ch_edit == "/home/user/test.py", f"got '{_ch_edit}'")

    # extract_file_path: Write tool
    _ch_write = extract_file_path({"file_path": "/tmp/output.json"}, "Write")
    test("Hotspot: extract Write file_path",
         _ch_write == "/tmp/output.json", f"got '{_ch_write}'")

    # extract_file_path: Read tool with path key
    _ch_read = extract_file_path({"path": "/home/user/readme.md"}, "Read")
    test("Hotspot: extract Read path",
         _ch_read == "/home/user/readme.md", f"got '{_ch_read}'")

    # extract_file_path: NotebookEdit
    _ch_nb = extract_file_path({"notebook_path": "/tmp/notebook.ipynb"}, "NotebookEdit")
    test("Hotspot: extract notebook_path",
         _ch_nb == "/tmp/notebook.ipynb", f"got '{_ch_nb}'")

    # extract_file_path: empty input
    _ch_empty = extract_file_path({}, "Edit")
    test("Hotspot: empty input → empty string",
         _ch_empty == "", f"got '{_ch_empty}'")

    # extract_file_path: non-dict input
    _ch_bad = extract_file_path("not a dict", "Edit")
    test("Hotspot: non-dict input → empty string",
         _ch_bad == "", f"got '{_ch_bad}'")

    # extract_file_path: Bash with path in command
    _ch_bash = extract_file_path({"command": "python3 /tmp/test_file.py"}, "Bash")
    test("Hotspot: extract Bash command path",
         _ch_bash == "/tmp/test_file.py", f"got '{_ch_bash}'")

    # analyze_file_blocks: returns expected structure
    _ch_analysis = analyze_file_blocks(lookback_days=1)
    test("Hotspot: analyze returns dict",
         isinstance(_ch_analysis, dict), f"type={type(_ch_analysis)}")
    test("Hotspot: analysis has file_blocks",
         "file_blocks" in _ch_analysis, f"keys={set(_ch_analysis.keys())}")
    test("Hotspot: analysis has total_blocks",
         "total_blocks" in _ch_analysis, f"keys={set(_ch_analysis.keys())}")
    test("Hotspot: file_blocks is list",
         isinstance(_ch_analysis["file_blocks"], list),
         f"type={type(_ch_analysis['file_blocks'])}")
    test("Hotspot: total_blocks is int",
         isinstance(_ch_analysis["total_blocks"], int),
         f"type={type(_ch_analysis['total_blocks'])}")

    # rank_files_by_risk: returns list
    _ch_ranked = rank_files_by_risk(lookback_days=1)
    test("Hotspot: rank returns list",
         isinstance(_ch_ranked, list), f"type={type(_ch_ranked)}")

    # Verify structure of ranked entries (if any exist)
    if _ch_ranked:
        _ch_first = _ch_ranked[0]
        test("Hotspot: ranked entry has rank",
             "rank" in _ch_first and _ch_first["rank"] == 1,
             f"keys={set(_ch_first.keys())}")
        test("Hotspot: ranked entry has risk_score",
             "risk_score" in _ch_first and isinstance(_ch_first["risk_score"], (int, float)),
             f"score={_ch_first.get('risk_score')}")
        test("Hotspot: ranked entry has risk_level",
             _ch_first.get("risk_level") in ("critical", "high", "medium", "low"),
             f"level={_ch_first.get('risk_level')}")
        test("Hotspot: ranked entry has churn_factor",
             "churn_factor" in _ch_first, f"keys={set(_ch_first.keys())}")
        test("Hotspot: ranked entry has error_density",
             "error_density" in _ch_first, f"keys={set(_ch_first.keys())}")
    else:
        skip("Hotspot: ranked entry structure", "no blocks in recent audit logs")

    # export_hotspot_report: returns string
    _ch_report = export_hotspot_report(lookback_days=1)
    test("Hotspot: export returns string",
         isinstance(_ch_report, str), f"type={type(_ch_report)}")
    test("Hotspot: report has header",
         "File Hotspot Report" in _ch_report, "missing header")
    test("Hotspot: report has separator lines",
         "=" * 10 in _ch_report, "missing separators")

    # rank_files_by_risk: respects limit
    _ch_limited = rank_files_by_risk(lookback_days=7, limit=2)
    test("Hotspot: limit=2 returns ≤2 files",
         len(_ch_limited) <= 2, f"got {len(_ch_limited)}")

    # rank_files_by_risk: risk_threshold filters
    _ch_high = rank_files_by_risk(lookback_days=7, risk_threshold=999.0)
    test("Hotspot: high threshold filters all",
         len(_ch_high) == 0, f"got {len(_ch_high)}")

except Exception as _ch_exc:
    test("Hotspot: import and basic tests", False, str(_ch_exc))

# ─────────────────────────────────────────────────
# Session Replay
# ─────────────────────────────────────────────────
print("\n--- Session Replay ---")

try:
    from shared.session_replay import (
        build_timeline, export_text, export_mermaid,
        get_timeline_stats, detect_patterns,
    )

    # build_timeline: returns expected structure
    _sr_timeline = build_timeline(lookback_hours=1)
    test("Replay: build_timeline returns dict",
         isinstance(_sr_timeline, dict), f"type={type(_sr_timeline)}")
    test("Replay: timeline has events",
         "events" in _sr_timeline, f"keys={set(_sr_timeline.keys())}")
    test("Replay: timeline has event_count",
         "event_count" in _sr_timeline and isinstance(_sr_timeline["event_count"], int),
         f"count={_sr_timeline.get('event_count')}")
    test("Replay: timeline has duration_seconds",
         "duration_seconds" in _sr_timeline,
         f"keys={set(_sr_timeline.keys())}")
    test("Replay: events is list",
         isinstance(_sr_timeline["events"], list),
         f"type={type(_sr_timeline['events'])}")
    test("Replay: gates_seen is list",
         isinstance(_sr_timeline.get("gates_seen", []), list),
         f"type={type(_sr_timeline.get('gates_seen'))}")
    test("Replay: tools_seen is list",
         isinstance(_sr_timeline.get("tools_seen", []), list),
         f"type={type(_sr_timeline.get('tools_seen'))}")
    test("Replay: event_types is dict",
         isinstance(_sr_timeline.get("event_types", {}), dict),
         f"type={type(_sr_timeline.get('event_types'))}")

    # Verify event structure if events exist
    if _sr_timeline["events"]:
        _sr_ev = _sr_timeline["events"][0]
        test("Replay: event has timestamp",
             "timestamp" in _sr_ev, f"keys={set(_sr_ev.keys())}")
        test("Replay: event has type",
             _sr_ev.get("type") in ("BLOCK", "PASS", "WARN", "EVENT"),
             f"type={_sr_ev.get('type')}")
        test("Replay: event has gate",
             "gate" in _sr_ev, f"keys={set(_sr_ev.keys())}")
        test("Replay: event has tool",
             "tool" in _sr_ev, f"keys={set(_sr_ev.keys())}")
    else:
        skip("Replay: event structure", "no events in last hour")

    # build_timeline: gate_filter works
    _sr_filtered = build_timeline(lookback_hours=1, gate_filter="gate_01")
    test("Replay: gate_filter returns subset",
         _sr_filtered["event_count"] <= _sr_timeline["event_count"],
         f"filtered={_sr_filtered['event_count']}, total={_sr_timeline['event_count']}")

    # export_text: returns string with header
    _sr_text = export_text(lookback_hours=1)
    test("Replay: export_text returns string",
         isinstance(_sr_text, str), f"type={type(_sr_text)}")
    test("Replay: text has Session Timeline header",
         "Session Timeline" in _sr_text, "missing header")
    test("Replay: text has separator",
         "=" * 10 in _sr_text, "missing separator")

    # export_mermaid: returns mermaid markdown
    _sr_mermaid = export_mermaid(lookback_hours=1)
    test("Replay: export_mermaid returns string",
         isinstance(_sr_mermaid, str), f"type={type(_sr_mermaid)}")
    test("Replay: mermaid starts with code fence",
         "```mermaid" in _sr_mermaid, "missing mermaid fence")
    test("Replay: mermaid has sequenceDiagram",
         "sequenceDiagram" in _sr_mermaid, "missing sequenceDiagram")

    # get_timeline_stats: returns expected keys
    _sr_stats = get_timeline_stats(lookback_hours=1)
    test("Replay: stats returns dict",
         isinstance(_sr_stats, dict), f"type={type(_sr_stats)}")
    _sr_stat_keys = {"total_events", "duration_minutes", "block_count",
                     "block_rate", "gate_count"}
    test("Replay: stats has expected keys",
         _sr_stat_keys.issubset(set(_sr_stats.keys())),
         f"missing={_sr_stat_keys - set(_sr_stats.keys())}")
    test("Replay: block_rate in [0,1]",
         0.0 <= _sr_stats.get("block_rate", 0) <= 1.0,
         f"rate={_sr_stats.get('block_rate')}")

    # detect_patterns: returns expected structure
    _sr_patterns = detect_patterns(lookback_hours=1)
    test("Replay: detect_patterns returns dict",
         isinstance(_sr_patterns, dict), f"type={type(_sr_patterns)}")
    test("Replay: patterns has 'patterns' list",
         isinstance(_sr_patterns.get("patterns", []), list),
         f"type={type(_sr_patterns.get('patterns'))}")
    test("Replay: patterns has 'healthy' bool",
         isinstance(_sr_patterns.get("healthy"), bool),
         f"type={type(_sr_patterns.get('healthy'))}")
    test("Replay: patterns has 'summary' string",
         isinstance(_sr_patterns.get("summary", ""), str),
         f"type={type(_sr_patterns.get('summary'))}")

    # Verify pattern structure if any detected
    if _sr_patterns["patterns"]:
        _sr_pat = _sr_patterns["patterns"][0]
        test("Replay: pattern has type",
             _sr_pat.get("type") in ("consecutive_blocks", "rapid_blocks", "gate_dominance"),
             f"type={_sr_pat.get('type')}")
        test("Replay: pattern has severity",
             _sr_pat.get("severity") in ("info", "warn", "error"),
             f"severity={_sr_pat.get('severity')}")
        test("Replay: pattern has description",
             "description" in _sr_pat and isinstance(_sr_pat["description"], str),
             f"keys={set(_sr_pat.keys())}")

except Exception as _sr_exc:
    test("Replay: import and basic tests", False, str(_sr_exc))

# ─── Gate Timing Extended Tests ─────────────────────────────────────
print("\n--- Gate Timing Extended ---")
import tempfile as _gte_tempfile
import shared.gate_timing as _gte_mod

_gte_tmp = _gte_tempfile.NamedTemporaryFile(suffix=".json", delete=False)
_gte_tmp.close()
_gte_tmp_path = _gte_tmp.name
_gte_orig_file = _gte_mod.TIMING_FILE
_gte_mod.TIMING_FILE = _gte_tmp_path
_gte_mod._reset_cache()

try:
    # Test 1: flush_timings persists data to disk
    _gte_mod.record_timing("gate_flush_test", "Edit", 15.0, blocked=False)
    _gte_mod.flush_timings()
    _gte_mod._reset_cache()  # Force reload from disk
    _gte_s1 = _gte_mod.get_gate_stats("gate_flush_test")
    test("GateTimingExt: flush_timings persists data to disk",
         _gte_s1 is not None and _gte_s1["count"] == 1 and abs(_gte_s1["avg_ms"] - 15.0) < 0.01,
         f"After flush+reload got {_gte_s1}")

    # Test 2: flush_timings is no-op when no dirty data
    _gte_mod._reset_cache()
    _gte_mod.flush_timings()  # Should not crash, no-op
    test("GateTimingExt: flush_timings no-op when not dirty",
         True, "No crash on clean flush")

    # Test 3: min_ms tracked correctly across multiple records
    _gte_mod._reset_cache()
    _gte_mod.record_timing("gate_minmax", "Edit", 50.0)
    _gte_mod.record_timing("gate_minmax", "Edit", 10.0)
    _gte_mod.record_timing("gate_minmax", "Edit", 30.0)
    _gte_s3 = _gte_mod.get_gate_stats("gate_minmax")
    test("GateTimingExt: min_ms tracks minimum across records",
         _gte_s3 is not None and abs(_gte_s3["min_ms"] - 10.0) < 0.01,
         f"Expected min=10.0, got {_gte_s3.get('min_ms') if _gte_s3 else None}")

    # Test 4: by_tool breakdown tracks per-tool counts
    _gte_mod.record_timing("gate_bytool", "Edit", 5.0)
    _gte_mod.record_timing("gate_bytool", "Edit", 7.0)
    _gte_mod.record_timing("gate_bytool", "Bash", 3.0)
    _gte_s4 = _gte_mod.get_gate_stats("gate_bytool")
    _gte_bt = _gte_s4["by_tool"] if _gte_s4 else {}
    test("GateTimingExt: by_tool tracks per-tool counts",
         _gte_bt.get("Edit", {}).get("count") == 2
         and _gte_bt.get("Bash", {}).get("count") == 1,
         f"by_tool={_gte_bt}")

    # Test 5: by_tool tracks per-tool total_ms
    test("GateTimingExt: by_tool tracks per-tool total_ms",
         abs(_gte_bt.get("Edit", {}).get("total_ms", 0) - 12.0) < 0.01
         and abs(_gte_bt.get("Bash", {}).get("total_ms", 0) - 3.0) < 0.01,
         f"Edit total_ms={_gte_bt.get('Edit', {}).get('total_ms')}, Bash total_ms={_gte_bt.get('Bash', {}).get('total_ms')}")

    # Test 6: slow_count increments only when > threshold
    _gte_mod.record_timing("gate_slow_cnt", "Edit", 10.0)  # Under threshold (50ms)
    _gte_mod.record_timing("gate_slow_cnt", "Edit", 60.0)  # Over threshold
    _gte_mod.record_timing("gate_slow_cnt", "Edit", 80.0)  # Over threshold
    _gte_s6 = _gte_mod.get_gate_stats("gate_slow_cnt")
    test("GateTimingExt: slow_count increments only for > threshold",
         _gte_s6 is not None and _gte_s6["slow_count"] == 2,
         f"Expected slow_count=2, got {_gte_s6.get('slow_count') if _gte_s6 else None}")

    # Test 7: rolling window trims to 200 samples
    for _i in range(210):
        _gte_mod.record_timing("gate_window", "Edit", float(_i))
    _gte_s7 = _gte_mod.get_gate_stats("gate_window")
    # count should be 210, but samples list should be capped
    test("GateTimingExt: count tracks all records (210)",
         _gte_s7 is not None and _gte_s7["count"] == 210,
         f"Expected count=210, got {_gte_s7.get('count') if _gte_s7 else None}")

    # Test 8: avg_ms computed correctly over multiple records
    _gte_mod.record_timing("gate_avg", "Edit", 10.0)
    _gte_mod.record_timing("gate_avg", "Edit", 20.0)
    _gte_mod.record_timing("gate_avg", "Edit", 30.0)
    _gte_s8 = _gte_mod.get_gate_stats("gate_avg")
    test("GateTimingExt: avg_ms computed correctly (10+20+30)/3=20",
         _gte_s8 is not None and abs(_gte_s8["avg_ms"] - 20.0) < 0.01,
         f"Expected avg=20.0, got {_gte_s8.get('avg_ms') if _gte_s8 else None}")

    # Test 9: _percentile edge cases
    test("GateTimingExt: _percentile empty list returns 0.0",
         _gte_mod._percentile([], 95) == 0.0,
         f"got {_gte_mod._percentile([], 95)}")

    # Test 10: _percentile single element returns that element
    test("GateTimingExt: _percentile single element returns it",
         _gte_mod._percentile([42.0], 50) == 42.0,
         f"got {_gte_mod._percentile([42.0], 50)}")

    # Test 11: _percentile sorted list correct p50
    _gte_p50 = _gte_mod._percentile([10, 20, 30, 40, 50], 50)
    test("GateTimingExt: _percentile p50 of [10,20,30,40,50] = 30",
         abs(_gte_p50 - 30.0) < 0.01,
         f"Expected 30.0, got {_gte_p50}")

    # Test 12: check_gate_sla "warn" status (avg between WARN and DEGRADE)
    for _i in range(15):
        _gte_mod.record_timing("gate_sla_warn_ext", "Edit", 70.0 + _i * 0.5)
    _gte_sla12 = _gte_mod.check_gate_sla("gate_sla_warn_ext")
    test("GateTimingExt: SLA warn status for 50 < avg < 200",
         _gte_sla12["status"] == "warn" and _gte_sla12["skip"] is False,
         f"Expected warn/no-skip, got {_gte_sla12}")

    # Test 13: check_gate_sla for unknown gate
    _gte_sla13 = _gte_mod.check_gate_sla("gate_totally_unknown")
    test("GateTimingExt: SLA unknown for non-existent gate",
         _gte_sla13["status"] == "unknown" and _gte_sla13["avg_ms"] == 0.0,
         f"Expected unknown with avg=0, got {_gte_sla13}")

    # Test 14: get_timing_report with no data returns correct message
    _gte_mod._reset_cache()
    # Write empty JSON to file
    with open(_gte_tmp_path, "w") as _f14:
        _f14.write("{}")
    _gte_mod._reset_cache()
    _gte_r14 = _gte_mod.get_timing_report()
    test("GateTimingExt: empty timing report message",
         "no data recorded" in _gte_r14.lower(),
         f"got: {_gte_r14[:100]}")

    # Test 15: get_slow_gates returns empty dict when no data
    _gte_slow15 = _gte_mod.get_slow_gates()
    test("GateTimingExt: get_slow_gates returns {} with no data",
         isinstance(_gte_slow15, dict) and len(_gte_slow15) == 0,
         f"got {_gte_slow15}")

    # Test 16: get_sla_report returns empty dict when no data
    _gte_sla16 = _gte_mod.get_sla_report()
    test("GateTimingExt: get_sla_report returns {} with no data",
         isinstance(_gte_sla16, dict) and len(_gte_sla16) == 0,
         f"got {_gte_sla16}")

finally:
    _gte_mod.TIMING_FILE = _gte_orig_file
    _gte_mod._reset_cache()
    try:
        os.unlink(_gte_tmp_path)
    except OSError:
        pass

# ─── Gate Trend Extended Tests ──────────────────────────────────────
print("\n--- Gate Trend Extended ---")
from shared.gate_trend import (
    compute_gate_trend, get_trend_report, format_trend_report,
    TREND_THRESHOLD, _load_snapshots, _save_snapshots, _trend_path,
)

try:
    import tempfile as _gtr_tempfile
    import shared.gate_trend as _gtr_mod

    # Save original path functions and override for isolation
    _gtr_orig_trend_path = _gtr_mod._trend_path
    _gtr_tmp = _gtr_tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    _gtr_tmp.close()
    _gtr_tmp_path = _gtr_tmp.name
    _gtr_mod._trend_path = lambda: _gtr_tmp_path

    # Write empty to start clean
    with open(_gtr_tmp_path, "w") as _f:
        _f.write("[]")

    # Test 1: compute_gate_trend with no snapshots returns stable
    _gtr_t1 = compute_gate_trend("test_gate", [])
    test("GateTrend: no snapshots returns stable direction",
         _gtr_t1["direction"] == "stable" and _gtr_t1["data_points"] == 0,
         f"got {_gtr_t1}")

    # Test 2: compute_gate_trend with 1 snapshot returns stable
    _gtr_snaps2 = [{"timestamp": 1000, "gates": {"test_gate": {"avg_ms": 10.0, "p95_ms": 15.0, "count": 5}}}]
    _gtr_t2 = compute_gate_trend("test_gate", _gtr_snaps2)
    test("GateTrend: 1 snapshot returns stable with first/last equal",
         _gtr_t2["direction"] == "stable" and _gtr_t2["data_points"] == 1
         and _gtr_t2["first_avg_ms"] == 10.0 and _gtr_t2["last_avg_ms"] == 10.0,
         f"got {_gtr_t2}")

    # Test 3: compute_gate_trend detects rising trend (>20% increase)
    _gtr_snaps3 = [
        {"timestamp": 1000, "gates": {"g1": {"avg_ms": 10.0, "p95_ms": 12.0, "count": 5}}},
        {"timestamp": 2000, "gates": {"g1": {"avg_ms": 15.0, "p95_ms": 18.0, "count": 10}}},
    ]
    _gtr_t3 = compute_gate_trend("g1", _gtr_snaps3)
    test("GateTrend: detects rising trend (10->15ms, +50%)",
         _gtr_t3["direction"] == "rising" and _gtr_t3["magnitude"] > 0.2,
         f"got {_gtr_t3}")

    # Test 4: compute_gate_trend detects falling trend
    _gtr_snaps4 = [
        {"timestamp": 1000, "gates": {"g2": {"avg_ms": 50.0, "p95_ms": 60.0, "count": 5}}},
        {"timestamp": 2000, "gates": {"g2": {"avg_ms": 30.0, "p95_ms": 35.0, "count": 10}}},
    ]
    _gtr_t4 = compute_gate_trend("g2", _gtr_snaps4)
    test("GateTrend: detects falling trend (50->30ms, -40%)",
         _gtr_t4["direction"] == "falling" and _gtr_t4["magnitude"] < -0.2,
         f"got {_gtr_t4}")

    # Test 5: compute_gate_trend stable when change < threshold
    _gtr_snaps5 = [
        {"timestamp": 1000, "gates": {"g3": {"avg_ms": 10.0, "p95_ms": 12.0, "count": 5}}},
        {"timestamp": 2000, "gates": {"g3": {"avg_ms": 11.0, "p95_ms": 13.0, "count": 10}}},
    ]
    _gtr_t5 = compute_gate_trend("g3", _gtr_snaps5)
    test("GateTrend: stable when change < 20% (10->11ms)",
         _gtr_t5["direction"] == "stable",
         f"got direction={_gtr_t5['direction']}, magnitude={_gtr_t5['magnitude']}")

    # Test 6: compute_gate_trend for missing gate returns stable
    _gtr_t6 = compute_gate_trend("nonexistent_gate", _gtr_snaps3)
    test("GateTrend: missing gate returns stable with 0 data_points",
         _gtr_t6["direction"] == "stable" and _gtr_t6["data_points"] == 0,
         f"got {_gtr_t6}")

    # Test 7: get_trend_report structure with saved snapshots
    _gtr_report_snaps = [
        {"timestamp": 1000, "gates": {
            "gate_fast": {"avg_ms": 10.0, "p95_ms": 12.0, "count": 5},
            "gate_slow": {"avg_ms": 50.0, "p95_ms": 60.0, "count": 5},
        }},
        {"timestamp": 2000, "gates": {
            "gate_fast": {"avg_ms": 5.0, "p95_ms": 7.0, "count": 10},
            "gate_slow": {"avg_ms": 80.0, "p95_ms": 90.0, "count": 10},
        }},
    ]
    _save_snapshots(_gtr_report_snaps)
    _gtr_r7 = get_trend_report()
    test("GateTrend: get_trend_report has expected structure",
         isinstance(_gtr_r7, dict)
         and "snapshot_count" in _gtr_r7
         and "gates" in _gtr_r7
         and "rising_gates" in _gtr_r7
         and "falling_gates" in _gtr_r7
         and "total_gates" in _gtr_r7,
         f"keys={set(_gtr_r7.keys())}")

    # Test 8: rising/falling gates categorized correctly
    test("GateTrend: gate_slow classified as rising",
         "gate_slow" in _gtr_r7.get("rising_gates", []),
         f"rising={_gtr_r7.get('rising_gates')}")

    # Test 9: gate_fast classified as falling
    test("GateTrend: gate_fast classified as falling",
         "gate_fast" in _gtr_r7.get("falling_gates", []),
         f"falling={_gtr_r7.get('falling_gates')}")

    # Test 10: snapshot_count matches saved data
    test("GateTrend: snapshot_count == 2",
         _gtr_r7["snapshot_count"] == 2,
         f"got {_gtr_r7['snapshot_count']}")

    # Test 11: total_gates counts unique gate names
    test("GateTrend: total_gates == 2",
         _gtr_r7["total_gates"] == 2,
         f"got {_gtr_r7['total_gates']}")

    # Test 12: format_trend_report returns readable string
    _gtr_fmt = format_trend_report()
    test("GateTrend: format_trend_report returns string with header",
         isinstance(_gtr_fmt, str) and "Gate Performance Trends" in _gtr_fmt,
         f"got: {_gtr_fmt[:100]}")

    # Test 13: format_trend_report contains RISING section
    test("GateTrend: format_trend_report shows RISING gates",
         "RISING" in _gtr_fmt and "gate_slow" in _gtr_fmt,
         f"missing RISING or gate_slow in report")

    # Test 14: format_trend_report contains FALLING section
    test("GateTrend: format_trend_report shows FALLING gates",
         "FALLING" in _gtr_fmt and "gate_fast" in _gtr_fmt,
         f"missing FALLING or gate_fast in report")

    # Test 15: _load_snapshots returns list from file
    _gtr_loaded = _load_snapshots()
    test("GateTrend: _load_snapshots returns list",
         isinstance(_gtr_loaded, list) and len(_gtr_loaded) == 2,
         f"len={len(_gtr_loaded)}")

    # Test 16: _load_snapshots returns [] for corrupt file
    with open(_gtr_tmp_path, "w") as _f:
        _f.write("{bad json")
    _gtr_bad = _load_snapshots()
    test("GateTrend: _load_snapshots returns [] for corrupt file",
         isinstance(_gtr_bad, list) and len(_gtr_bad) == 0,
         f"got {_gtr_bad}")

    # Test 17: _save_snapshots + _load_snapshots roundtrip
    _gtr_test_data = [{"timestamp": 999, "gates": {"test": {"avg_ms": 1.0, "p95_ms": 1.5, "count": 1}}}]
    _save_snapshots(_gtr_test_data)
    _gtr_rt = _load_snapshots()
    test("GateTrend: save+load roundtrip preserves data",
         len(_gtr_rt) == 1 and _gtr_rt[0]["timestamp"] == 999,
         f"got {_gtr_rt}")

    # Test 18: get_trend_report with empty snapshots
    _save_snapshots([])
    _gtr_empty = get_trend_report()
    test("GateTrend: empty snapshots -> 0 gates and empty rising/falling",
         _gtr_empty["total_gates"] == 0
         and len(_gtr_empty["rising_gates"]) == 0
         and len(_gtr_empty["falling_gates"]) == 0,
         f"got total_gates={_gtr_empty['total_gates']}")

finally:
    _gtr_mod._trend_path = _gtr_orig_trend_path
    try:
        os.unlink(_gtr_tmp_path)
    except OSError:
        pass

# ─── Session Analytics Extended Tests ───────────────────────────────
print("\n--- Session Analytics Extended ---")
from shared.session_analytics import (
    gate_block_rates, error_frequency, compare_sessions,
    compare_sessions_metrics, session_productivity,
    parse_audit_log, analyse_session,
    _stddev, _compute_resolve_score,
)
import tempfile as _sae_tempfile

try:
    # Test 1: gate_block_rates with mixed decisions
    _sae_entries1 = [
        {"gate": "gate_01", "decision": "pass"},
        {"gate": "gate_01", "decision": "pass"},
        {"gate": "gate_01", "decision": "block"},
        {"gate": "gate_02", "decision": "warn"},
        {"gate": "gate_02", "decision": "block"},
    ]
    _sae_gbr = gate_block_rates(_sae_entries1)
    test("SessionAnalyticsExt: gate_block_rates pass/warn/block counts",
         _sae_gbr.get("gate_01", {}).get("pass") == 2
         and _sae_gbr.get("gate_01", {}).get("block") == 1
         and _sae_gbr.get("gate_02", {}).get("warn") == 1,
         f"got {_sae_gbr}")

    # Test 2: gate_block_rates total includes all decisions
    test("SessionAnalyticsExt: gate_block_rates total counts all decisions",
         _sae_gbr.get("gate_01", {}).get("total") == 3
         and _sae_gbr.get("gate_02", {}).get("total") == 2,
         f"gate_01 total={_sae_gbr.get('gate_01', {}).get('total')}")

    # Test 3: gate_block_rates empty input
    _sae_gbr_empty = gate_block_rates([])
    test("SessionAnalyticsExt: gate_block_rates empty -> {}",
         isinstance(_sae_gbr_empty, dict) and len(_sae_gbr_empty) == 0,
         f"got {_sae_gbr_empty}")

    # Test 4: error_frequency categorizes known patterns
    _sae_err_entries = [
        {"decision": "block", "reason": "must Read /tmp/foo.py before editing it"},
        {"decision": "block", "reason": "NO DESTROY: rm -rf blocked by safety gate"},
        {"decision": "warn", "reason": "memory not queried before edit"},
        {"decision": "block", "reason": "deploy without tests is forbidden"},
        {"decision": "pass", "reason": "all good"},  # should be skipped (pass)
    ]
    _sae_ef = error_frequency(_sae_err_entries)
    test("SessionAnalyticsExt: error_frequency categorizes gate1 pattern",
         _sae_ef.get("gate1:read-before-edit") == 1,
         f"got {_sae_ef}")

    # Test 5: error_frequency categorizes gate2 pattern
    test("SessionAnalyticsExt: error_frequency categorizes gate2 pattern",
         _sae_ef.get("gate2:no-destroy") == 1,
         f"got {_sae_ef}")

    # Test 6: error_frequency categorizes gate4 pattern
    test("SessionAnalyticsExt: error_frequency categorizes gate4 memory pattern",
         _sae_ef.get("gate4:memory-first") == 1,
         f"got {_sae_ef}")

    # Test 7: error_frequency skips pass decisions
    test("SessionAnalyticsExt: error_frequency skips pass decisions",
         sum(_sae_ef.values()) == 4,  # 4 block/warn entries categorized
         f"total={sum(_sae_ef.values())}, expected 4")

    # Test 8: _stddev computation
    _sae_sd = _stddev([10, 20, 30, 40, 50])
    test("SessionAnalyticsExt: _stddev([10,20,30,40,50]) ≈ 14.14",
         abs(_sae_sd - 14.1421) < 0.01,
         f"got {_sae_sd}")

    # Test 9: _stddev single value returns 0
    test("SessionAnalyticsExt: _stddev single value returns 0",
         _stddev([42.0]) == 0.0,
         f"got {_stddev([42.0])}")

    # Test 10: _stddev empty list returns 0
    test("SessionAnalyticsExt: _stddev empty list returns 0",
         _stddev([]) == 0.0,
         f"got {_stddev([])}")

    # Test 11: _compute_resolve_score with no blocks returns 1.0
    _sae_rs11 = _compute_resolve_score([{"decision": "pass", "gate": "g1"}])
    test("SessionAnalyticsExt: _compute_resolve_score no blocks -> 1.0",
         abs(_sae_rs11 - 1.0) < 0.001,
         f"got {_sae_rs11}")

    # Test 12: _compute_resolve_score with block then pass = 1.0
    _sae_entries12 = [
        {"decision": "block", "gate": "g1"},
        {"decision": "pass", "gate": "g1"},
    ]
    _sae_rs12 = _compute_resolve_score(_sae_entries12)
    test("SessionAnalyticsExt: block then pass on same gate -> resolve=1.0",
         abs(_sae_rs12 - 1.0) < 0.001,
         f"got {_sae_rs12}")

    # Test 13: _compute_resolve_score with unresolved block = 0.0
    _sae_entries13 = [
        {"decision": "block", "gate": "g1"},
        {"decision": "pass", "gate": "g2"},  # Different gate, doesn't resolve g1
    ]
    _sae_rs13 = _compute_resolve_score(_sae_entries13)
    test("SessionAnalyticsExt: unresolved block -> resolve=0.0",
         abs(_sae_rs13 - 0.0) < 0.001,
         f"got {_sae_rs13}")

    # Test 14: session_productivity with actual entries
    _sae_prod_entries = [
        {"tool": "Edit", "decision": "pass", "gate": "g1"},
        {"tool": "Edit", "decision": "pass", "gate": "g1"},
        {"tool": "Edit", "decision": "block", "gate": "g1"},
        {"tool": "Read", "decision": "pass", "gate": "g1"},
        {"tool": "search_knowledge", "decision": "pass", "gate": "g4"},
        {"tool": "remember_this", "decision": "pass", "gate": "g6"},
    ]
    _sae_prod = session_productivity(_sae_prod_entries, duration_minutes=60.0)
    test("SessionAnalyticsExt: productivity has score, grade, breakdown",
         isinstance(_sae_prod, dict)
         and "score" in _sae_prod
         and "grade" in _sae_prod
         and "breakdown" in _sae_prod,
         f"keys={set(_sae_prod.keys())}")

    # Test 15: productivity score is 0-100
    test("SessionAnalyticsExt: productivity score in range 0-100",
         0.0 <= _sae_prod["score"] <= 100.0,
         f"score={_sae_prod['score']}")

    # Test 16: productivity grade is valid letter
    test("SessionAnalyticsExt: productivity grade is A-F",
         _sae_prod["grade"] in ("A", "B", "C", "D", "F"),
         f"grade={_sae_prod['grade']}")

    # Test 17: productivity breakdown has 4 sub-metrics
    _sae_bd = _sae_prod.get("breakdown", {})
    test("SessionAnalyticsExt: breakdown has 4 sub-metrics",
         all(k in _sae_bd for k in ("edit_velocity", "block_rate", "error_resolve", "memory_contrib")),
         f"breakdown keys={set(_sae_bd.keys())}")

    # Test 18: productivity block_rate reflects actual blocks
    _sae_br = _sae_bd.get("block_rate", {})
    test("SessionAnalyticsExt: block_rate blocked_count=1",
         _sae_br.get("blocked_count") == 1 and _sae_br.get("total_decisions") == 6,
         f"blocked={_sae_br.get('blocked_count')}, total={_sae_br.get('total_decisions')}")

    # Test 19: productivity memory_contrib counts memory tools
    _sae_mc = _sae_bd.get("memory_contrib", {})
    test("SessionAnalyticsExt: memory_contrib counts 2 memory calls",
         _sae_mc.get("memory_calls") == 2,
         f"memory_calls={_sae_mc.get('memory_calls')}")

    # Test 20: compare_sessions_metrics with history
    _sae_current = {"score": 80.0}
    _sae_history = [{"score": 70.0}, {"score": 75.0}, {"score": 65.0}]
    _sae_cmp = compare_sessions_metrics(_sae_current, _sae_history)
    test("SessionAnalyticsExt: compare_sessions_metrics has expected keys",
         isinstance(_sae_cmp, dict)
         and "current_score" in _sae_cmp
         and "rolling_avg" in _sae_cmp
         and "delta" in _sae_cmp
         and "trend" in _sae_cmp,
         f"keys={set(_sae_cmp.keys())}")

    # Test 21: compare_sessions_metrics correct rolling_avg
    _sae_expected_avg = (70.0 + 75.0 + 65.0) / 3.0
    test("SessionAnalyticsExt: rolling_avg = (70+75+65)/3 = 70.0",
         abs(_sae_cmp["rolling_avg"] - _sae_expected_avg) < 0.1,
         f"got {_sae_cmp['rolling_avg']}")

    # Test 22: compare_sessions_metrics positive delta = improving
    test("SessionAnalyticsExt: positive delta -> improving trend",
         _sae_cmp["delta"] > 0 and _sae_cmp["trend"] == "improving",
         f"delta={_sae_cmp['delta']}, trend={_sae_cmp['trend']}")

    # Test 23: compare_sessions_metrics empty history -> insufficient_data
    _sae_cmp23 = compare_sessions_metrics({"score": 80.0}, [])
    test("SessionAnalyticsExt: empty history -> insufficient_data",
         _sae_cmp23["trend"] == "insufficient_data",
         f"trend={_sae_cmp23['trend']}")

    # Test 24: parse_audit_log on non-existent file returns []
    _sae_pal = parse_audit_log("/tmp/nonexistent_audit_test_12345.jsonl")
    test("SessionAnalyticsExt: parse_audit_log missing file returns []",
         isinstance(_sae_pal, list) and len(_sae_pal) == 0,
         f"got len={len(_sae_pal)}")

    # Test 25: parse_audit_log on valid JSONL file
    _sae_tmp25 = _sae_tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w")
    _sae_tmp25.write('{"gate": "g1", "decision": "pass", "tool": "Edit"}\n')
    _sae_tmp25.write('{"gate": "g2", "decision": "block", "tool": "Bash"}\n')
    _sae_tmp25.write('bad json line\n')
    _sae_tmp25.close()
    _sae_pal25 = parse_audit_log(_sae_tmp25.name)
    test("SessionAnalyticsExt: parse_audit_log parses valid lines, skips bad",
         len(_sae_pal25) == 2 and _sae_pal25[0]["gate"] == "g1",
         f"got {len(_sae_pal25)} entries")
    try:
        os.unlink(_sae_tmp25.name)
    except OSError:
        pass

    # Test 26: compare_sessions legacy mode (dict + list)
    _sae_legacy = compare_sessions({"score": 90.0}, [{"score": 80.0}])
    test("SessionAnalyticsExt: compare_sessions legacy mode works",
         isinstance(_sae_legacy, dict) and "current_score" in _sae_legacy,
         f"keys={set(_sae_legacy.keys())}")

    # Test 27: compare_sessions session-ID mode (strings)
    _sae_sid_cmp = compare_sessions("nonexistent_a", "nonexistent_b")
    test("SessionAnalyticsExt: compare_sessions ID mode returns summary",
         isinstance(_sae_sid_cmp, dict) and "summary" in _sae_sid_cmp,
         f"keys={set(_sae_sid_cmp.keys())}")

    # Test 28: compare_sessions handles missing sessions gracefully
    test("SessionAnalyticsExt: compare_sessions missing sessions in summary",
         "not found" in _sae_sid_cmp.get("summary", "").lower()
         or "Neither" in _sae_sid_cmp.get("summary", ""),
         f"summary={_sae_sid_cmp.get('summary')}")

    # Test 29: analyse_session with empty audit dir
    _sae_tmp_dir = _sae_tempfile.mkdtemp()
    _sae_analysis = analyse_session(audit_dir=_sae_tmp_dir, duration_minutes=60.0)
    test("SessionAnalyticsExt: analyse_session with empty dir returns valid structure",
         isinstance(_sae_analysis, dict)
         and "tool_distribution" in _sae_analysis
         and "productivity" in _sae_analysis
         and "entry_count" in _sae_analysis,
         f"keys={set(_sae_analysis.keys())}")
    try:
        os.rmdir(_sae_tmp_dir)
    except OSError:
        pass

    # Test 30: analyse_session entry_count is 0 for empty dir
    test("SessionAnalyticsExt: analyse_session empty dir -> entry_count=0",
         _sae_analysis["entry_count"] == 0,
         f"got {_sae_analysis['entry_count']}")

    # Test 31: session_productivity with 0 duration doesn't crash
    _sae_prod31 = session_productivity([], duration_minutes=0)
    test("SessionAnalyticsExt: productivity with 0 duration doesn't crash",
         isinstance(_sae_prod31, dict) and "score" in _sae_prod31,
         f"keys={set(_sae_prod31.keys())}")

    # Test 32: spike detection in compare_sessions_metrics
    _sae_spike = compare_sessions_metrics(
        {"score": 95.0},
        [{"score": 50.0}, {"score": 52.0}, {"score": 48.0}, {"score": 51.0}],
    )
    test("SessionAnalyticsExt: spike_detected when current far from history",
         _sae_spike.get("spike_detected") is True,
         f"spike_detected={_sae_spike.get('spike_detected')}")

except Exception as _sae_exc:
    test("SessionAnalyticsExt: import and basic tests", False, str(_sae_exc))

# ─── Hook Cache Extended Tests ──────────────────────────────────────
print("\n--- Hook Cache Extended ---")
from shared.hook_cache import (
    get_cached_module, invalidate_module,
    get_cached_state, set_cached_state, invalidate_state,
    get_cached_result, set_cached_result, invalidate_result,
    cache_stats, clear_cache, evict_expired,
)

try:
    clear_cache()

    # Test 1: get_cached_module imports a real module
    _hce_mod = get_cached_module("json")
    test("HookCacheExt: get_cached_module('json') returns module",
         _hce_mod is not None and hasattr(_hce_mod, "loads"),
         f"got {type(_hce_mod)}")

    # Test 2: second call returns same cached object (hit)
    _hce_stats_before = cache_stats()
    _hce_mod2 = get_cached_module("json")
    _hce_stats_after = cache_stats()
    test("HookCacheExt: repeated import is a cache hit",
         _hce_stats_after["module_hits"] > _hce_stats_before["module_hits"],
         f"hits before={_hce_stats_before['module_hits']}, after={_hce_stats_after['module_hits']}")

    # Test 3: invalidate_module removes cached module
    _hce_inv_mod = invalidate_module("json")
    test("HookCacheExt: invalidate_module returns True for cached module",
         _hce_inv_mod is True, f"got {_hce_inv_mod}")

    # Test 4: invalidate_module returns False for uncached module
    _hce_inv_mod2 = invalidate_module("nonexistent_module_xyz")
    test("HookCacheExt: invalidate_module returns False for uncached",
         _hce_inv_mod2 is False, f"got {_hce_inv_mod2}")

    # Test 5: cache_stats tracks module_cached count
    clear_cache()
    get_cached_module("os")
    get_cached_module("sys")
    _hce_s5 = cache_stats()
    test("HookCacheExt: module_cached counts loaded modules",
         _hce_s5["module_cached"] >= 2,
         f"module_cached={_hce_s5['module_cached']}")

    # Test 6: state cache miss returns None
    clear_cache()
    _hce_miss = get_cached_state("__nonexistent_session__")
    test("HookCacheExt: state cache miss returns None",
         _hce_miss is None, f"got {_hce_miss}")

    # Test 7: state cache miss increments counter
    _hce_s7 = cache_stats()
    test("HookCacheExt: state_misses incremented on miss",
         _hce_s7["state_misses"] >= 1,
         f"state_misses={_hce_s7['state_misses']}")

    # Test 8: state cache hit increments counter
    clear_cache()
    set_cached_state("__hce_test__", {"x": 1})
    get_cached_state("__hce_test__", ttl_ms=5000)
    _hce_s8 = cache_stats()
    test("HookCacheExt: state_hits incremented on hit",
         _hce_s8["state_hits"] >= 1,
         f"state_hits={_hce_s8['state_hits']}")

    # Test 9: state_cached count
    test("HookCacheExt: state_cached = 1 after one set",
         _hce_s8["state_cached"] == 1,
         f"state_cached={_hce_s8['state_cached']}")

    # Test 10: result cache set/get roundtrip
    clear_cache()
    from shared.gate_result import GateResult
    _hce_gr = GateResult(blocked=False, message="test", gate_name="test_gate")
    set_cached_result("gate_01", "Edit", "abc123", _hce_gr)
    _hce_r10 = get_cached_result("gate_01", "Edit", "abc123")
    test("HookCacheExt: result cache set/get roundtrip",
         _hce_r10 is not None and _hce_r10.blocked is False,
         f"got {_hce_r10}")

    # Test 11: result cache miss returns None
    _hce_r11 = get_cached_result("gate_01", "Edit", "different_hash")
    test("HookCacheExt: result cache miss for different hash",
         _hce_r11 is None, f"got {_hce_r11}")

    # Test 12: invalidate_result removes entry
    _hce_inv_r = invalidate_result("gate_01", "Edit", "abc123")
    _hce_r12 = get_cached_result("gate_01", "Edit", "abc123")
    test("HookCacheExt: invalidate_result removes entry",
         _hce_inv_r is True and _hce_r12 is None,
         f"inv={_hce_inv_r}, after_get={_hce_r12}")

    # Test 13: invalidate_result returns False for missing entry
    _hce_inv_r2 = invalidate_result("gate_99", "Task", "zzz")
    test("HookCacheExt: invalidate_result False for missing",
         _hce_inv_r2 is False, f"got {_hce_inv_r2}")

    # Test 14: evict_expired returns dict with state/result counts
    clear_cache()
    _hce_ev14 = evict_expired()
    test("HookCacheExt: evict_expired returns {state: 0, result: 0} when empty",
         _hce_ev14 == {"state": 0, "result": 0},
         f"got {_hce_ev14}")

    # Test 15: clear_cache resets all counters to 0
    clear_cache()
    _hce_s15 = cache_stats()
    test("HookCacheExt: clear_cache resets all counters to 0",
         _hce_s15["module_hits"] == 0
         and _hce_s15["state_hits"] == 0
         and _hce_s15["result_hits"] == 0
         and _hce_s15["module_cached"] == 0,
         f"stats={_hce_s15}")

    clear_cache()  # Clean up

except Exception as _hce_exc:
    test("HookCacheExt: import and basic tests", False, str(_hce_exc))

# ─── Metrics Collector Extended Tests ───────────────────────────────
print("\n--- Metrics Collector Extended ---")
from shared.metrics_collector import (
    inc as mc_inc, set_gauge as mc_set_gauge, observe as mc_observe,
    get_metric as mc_get_metric, get_all_metrics as mc_get_all_metrics,
    flush as mc_flush, rollup as mc_rollup,
    record_gate_fire, record_gate_block, record_gate_latency,
    record_hook_duration, record_memory_query, set_memory_total,
    record_tool_call, set_test_pass_rate, export_json as mc_export_json,
    timed as mc_timed, TYPE_COUNTER, TYPE_GAUGE, TYPE_HISTOGRAM,
    _label_key,
)

try:
    # Test 1: counter increments correctly
    mc_inc("__mce_counter__", 5)
    mc_inc("__mce_counter__", 3)
    _mce_c1 = mc_get_metric("__mce_counter__")
    test("MetricsCollectorExt: counter increments to 8",
         _mce_c1.get("value") == 8 and _mce_c1.get("type") == TYPE_COUNTER,
         f"value={_mce_c1.get('value')}")

    # Test 2: counter with labels
    mc_inc("__mce_labeled__", 1, labels={"gate": "gate_01"})
    mc_inc("__mce_labeled__", 1, labels={"gate": "gate_02"})
    _mce_c2a = mc_get_metric("__mce_labeled__", labels={"gate": "gate_01"})
    _mce_c2b = mc_get_metric("__mce_labeled__", labels={"gate": "gate_02"})
    test("MetricsCollectorExt: labeled counters are independent",
         _mce_c2a.get("value") == 1 and _mce_c2b.get("value") == 1,
         f"gate_01={_mce_c2a.get('value')}, gate_02={_mce_c2b.get('value')}")

    # Test 3: gauge set overwrites previous value
    mc_set_gauge("__mce_gauge__", 100.0)
    mc_set_gauge("__mce_gauge__", 42.0)
    _mce_g3 = mc_get_metric("__mce_gauge__")
    test("MetricsCollectorExt: gauge overwrites to 42.0",
         abs(_mce_g3.get("value", 0) - 42.0) < 0.001,
         f"value={_mce_g3.get('value')}")

    # Test 4: histogram tracks count, sum, min, max, avg
    mc_observe("__mce_hist__", 10.0)
    mc_observe("__mce_hist__", 20.0)
    mc_observe("__mce_hist__", 30.0)
    _mce_h4 = mc_get_metric("__mce_hist__")
    test("MetricsCollectorExt: histogram count/sum/min/max",
         _mce_h4.get("count", 0) >= 3
         and _mce_h4.get("type") == TYPE_HISTOGRAM,
         f"count={_mce_h4.get('count')}")

    # Test 5: histogram has computed avg
    test("MetricsCollectorExt: histogram has avg field",
         "avg" in _mce_h4 and _mce_h4["avg"] > 0,
         f"avg={_mce_h4.get('avg')}")

    # Test 6: _label_key encodes labels canonically
    _mce_lk6 = _label_key({"b": "2", "a": "1"})
    test("MetricsCollectorExt: _label_key sorts keys",
         _mce_lk6 == "a=1,b=2",
         f"got '{_mce_lk6}'")

    # Test 7: _label_key returns "" for None/empty
    test("MetricsCollectorExt: _label_key(None) returns ''",
         _label_key(None) == "" and _label_key({}) == "",
         f"None='{_label_key(None)}', empty='{_label_key({})}'")

    # Test 8: get_metric returns {} for nonexistent
    _mce_m8 = mc_get_metric("__totally_fake_metric__")
    test("MetricsCollectorExt: get_metric returns {} for missing",
         _mce_m8 == {}, f"got {_mce_m8}")

    # Test 9: get_all_metrics contains our test metrics
    _mce_all = mc_get_all_metrics()
    test("MetricsCollectorExt: get_all_metrics contains test counter",
         "__mce_counter__" in _mce_all,
         f"keys={list(_mce_all.keys())[:5]}...")

    # Test 10: rollup returns dict with windowed data
    _mce_r10 = mc_rollup(60)
    test("MetricsCollectorExt: rollup(60) returns dict",
         isinstance(_mce_r10, dict),
         f"type={type(_mce_r10).__name__}")

    # Test 11: rollup includes counters as current values
    _mce_has_counter = any("__mce_counter__" in k for k in _mce_r10)
    test("MetricsCollectorExt: rollup includes counter metrics",
         _mce_has_counter,
         f"keys sample={list(_mce_r10.keys())[:5]}")

    # Test 12: convenience helpers - record_gate_fire
    record_gate_fire("__mce_gate_test__")
    _mce_gf = mc_get_metric("gate.fires", labels={"gate": "__mce_gate_test__"})
    test("MetricsCollectorExt: record_gate_fire increments gate.fires",
         _mce_gf.get("value", 0) >= 1,
         f"value={_mce_gf.get('value')}")

    # Test 13: record_gate_block
    record_gate_block("__mce_gate_test__")
    _mce_gb = mc_get_metric("gate.blocks", labels={"gate": "__mce_gate_test__"})
    test("MetricsCollectorExt: record_gate_block increments gate.blocks",
         _mce_gb.get("value", 0) >= 1,
         f"value={_mce_gb.get('value')}")

    # Test 14: record_gate_latency
    record_gate_latency("__mce_gate_test__", 5.5)
    _mce_gl = mc_get_metric("gate.latency_ms", labels={"gate": "__mce_gate_test__"})
    test("MetricsCollectorExt: record_gate_latency records histogram",
         _mce_gl.get("count", 0) >= 1,
         f"count={_mce_gl.get('count')}")

    # Test 15: set_test_pass_rate clamps to [0, 1]
    set_test_pass_rate(1.5)
    _mce_tpr = mc_get_metric("test.pass_rate")
    test("MetricsCollectorExt: set_test_pass_rate clamps 1.5 -> 1.0",
         abs(_mce_tpr.get("value", 0) - 1.0) < 0.001,
         f"value={_mce_tpr.get('value')}")

    # Test 16: export_json returns valid JSON string
    _mce_ej = mc_export_json()
    _mce_parsed = json.loads(_mce_ej) if isinstance(_mce_ej, str) else _mce_ej
    test("MetricsCollectorExt: export_json is valid JSON with expected keys",
         isinstance(_mce_parsed, dict) and "metrics" in _mce_parsed,
         f"type={type(_mce_parsed).__name__}, keys={set(_mce_parsed.keys()) if isinstance(_mce_parsed, dict) else 'N/A'}")

    # Test 17: timed context manager records histogram
    import time as _mce_time
    with mc_timed("__mce_timed__"):
        _mce_time.sleep(0.001)
    _mce_t17 = mc_get_metric("__mce_timed__")
    test("MetricsCollectorExt: timed context manager records observation",
         _mce_t17.get("count", 0) >= 1,
         f"count={_mce_t17.get('count')}")

    # Test 18: flush returns True
    _mce_f18 = mc_flush()
    test("MetricsCollectorExt: flush returns True",
         _mce_f18 is True, f"got {_mce_f18}")

except Exception as _mce_exc:
    test("MetricsCollectorExt: import and basic tests", False, str(_mce_exc))

# ─── Event Replay Extended Tests ────────────────────────────────────
print("\n--- Event Replay Extended ---")
from shared.event_replay import (
    load_events, filter_events, replay_event, diff_results,
    summarise_replay, _extract_tool_input, _parse_context,
    _is_always_allowed, _is_memory_tool, _build_replay_state,
)
import tempfile as _ere_tempfile

try:
    # Test 1: _is_always_allowed for Read
    test("EventReplayExt: Read is always allowed",
         _is_always_allowed("Read") is True, "Expected True")

    # Test 2: _is_always_allowed for Edit
    test("EventReplayExt: Edit is NOT always allowed",
         _is_always_allowed("Edit") is False, "Expected False")

    # Test 3: _is_memory_tool for mcp__memory__ prefix
    test("EventReplayExt: mcp__memory__search_knowledge is memory tool",
         _is_memory_tool("mcp__memory__search_knowledge") is True, "Expected True")

    # Test 4: _is_memory_tool for non-memory tool
    test("EventReplayExt: Edit is not memory tool",
         _is_memory_tool("Edit") is False, "Expected False")

    # Test 5: _parse_context with valid JSON
    _ere_ctx5 = _parse_context('{"file_path": "/tmp/test.py"}')
    test("EventReplayExt: _parse_context parses valid JSON",
         _ere_ctx5.get("file_path") == "/tmp/test.py",
         f"got {_ere_ctx5}")

    # Test 6: _parse_context with non-JSON returns {}
    _ere_ctx6 = _parse_context("just a string")
    test("EventReplayExt: _parse_context non-JSON returns {}",
         _ere_ctx6 == {}, f"got {_ere_ctx6}")

    # Test 7: _parse_context with empty string returns {}
    test("EventReplayExt: _parse_context('') returns {}",
         _parse_context("") == {}, f"got {_parse_context('')}")

    # Test 8: _extract_tool_input for Bash
    _ere_ti8 = _extract_tool_input({"tool_name": "Bash", "context": "ls -la"})
    test("EventReplayExt: _extract_tool_input Bash has command",
         "command" in _ere_ti8,
         f"got {_ere_ti8}")

    # Test 9: _extract_tool_input for Edit
    _ere_ti9 = _extract_tool_input({"tool_name": "Edit", "context": '{"file_path": "/tmp/foo.py"}'})
    test("EventReplayExt: _extract_tool_input Edit has file_path",
         "file_path" in _ere_ti9,
         f"got {_ere_ti9}")

    # Test 10: _extract_tool_input for Task
    _ere_ti10 = _extract_tool_input({"tool_name": "Task", "context": '{"model": "haiku"}'})
    test("EventReplayExt: _extract_tool_input Task has model",
         "model" in _ere_ti10,
         f"got {_ere_ti10}")

    # Test 11: _build_replay_state returns valid state dict
    _ere_state = _build_replay_state("test_replay")
    test("EventReplayExt: _build_replay_state returns state with session_id",
         isinstance(_ere_state, dict) and _ere_state.get("_session_id") == "test_replay",
         f"session_id={_ere_state.get('_session_id')}")

    # Test 12: _build_replay_state has memory_last_queried set
    test("EventReplayExt: replay state has memory_last_queried",
         _ere_state.get("memory_last_queried", 0) > 0,
         f"mlq={_ere_state.get('memory_last_queried')}")

    # Test 13: load_events on non-existent file returns []
    _ere_ev13 = load_events("/tmp/__nonexistent_capture_queue_test__.jsonl")
    test("EventReplayExt: load_events missing file returns []",
         isinstance(_ere_ev13, list) and len(_ere_ev13) == 0,
         f"len={len(_ere_ev13)}")

    # Test 14: load_events on valid JSONL
    _ere_tmp14 = _ere_tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w")
    _ere_tmp14.write('{"document": "test", "metadata": {"tool_name": "Edit", "exit_code": "0", "session_id": "s1"}, "id": "obs_1"}\n')
    _ere_tmp14.write('{"document": "test2", "metadata": {"tool_name": "Bash", "exit_code": "2", "session_id": "s1", "gate": "gate_02"}, "id": "obs_2"}\n')
    _ere_tmp14.close()
    _ere_ev14 = load_events(_ere_tmp14.name)
    test("EventReplayExt: load_events parses 2 valid entries",
         len(_ere_ev14) == 2,
         f"len={len(_ere_ev14)}")

    # Test 15: filter_events with tool_name filter
    _ere_f15 = filter_events(tool_name="Edit", path=_ere_tmp14.name)
    test("EventReplayExt: filter_events tool_name='Edit' returns 1",
         len(_ere_f15) == 1 and _ere_f15[0].get("_replay_meta", {}).get("tool_name") == "Edit",
         f"len={len(_ere_f15)}")

    # Test 16: filter_events blocked=True
    _ere_f16 = filter_events(blocked=True, path=_ere_tmp14.name)
    test("EventReplayExt: filter_events blocked=True returns blocked events",
         len(_ere_f16) == 1 and _ere_f16[0].get("_replay_meta", {}).get("originally_blocked") is True,
         f"len={len(_ere_f16)}")

    # Test 17: filter_events adds _replay_meta
    _ere_f17 = filter_events(path=_ere_tmp14.name)
    _ere_has_meta = all("_replay_meta" in ev for ev in _ere_f17)
    test("EventReplayExt: filter_events adds _replay_meta to all entries",
         _ere_has_meta and len(_ere_f17) == 2,
         f"all_have_meta={_ere_has_meta}")

    # Test 18: replay_event with always-allowed tool returns skipped
    _ere_r18 = replay_event({"metadata": {"tool_name": "Read"}})
    test("EventReplayExt: replay always-allowed tool -> skipped",
         _ere_r18["final_outcome"] == "skipped"
         and _ere_r18["skipped_always_allowed"] is True,
         f"outcome={_ere_r18['final_outcome']}")

    # Test 19: replay_event with empty tool_name -> skipped
    _ere_r19 = replay_event({"metadata": {"tool_name": ""}})
    test("EventReplayExt: replay empty tool_name -> skipped",
         _ere_r19["final_outcome"] == "skipped",
         f"outcome={_ere_r19['final_outcome']}")

    # Test 20: diff_results with no change
    _ere_d20 = diff_results(
        {"originally_blocked": False},
        {"final_outcome": "passed", "per_gate": {}},
    )
    test("EventReplayExt: diff_results no change -> changed=False",
         _ere_d20["changed"] is False,
         f"changed={_ere_d20['changed']}")

    # Test 21: diff_results with change (passed -> blocked)
    _ere_d21 = diff_results(
        {"originally_blocked": False},
        {"final_outcome": "blocked", "per_gate": {}},
    )
    test("EventReplayExt: diff_results passed->blocked -> changed=True",
         _ere_d21["changed"] is True and len(_ere_d21["new_blocks"]) > 0,
         f"changed={_ere_d21['changed']}, new_blocks={_ere_d21['new_blocks']}")

    # Test 22: diff_results per-gate comparison
    _ere_orig22 = {
        "per_gate": {"gate_01": {"blocked": True}, "gate_02": {"blocked": False}},
        "final_outcome": "blocked",
    }
    _ere_rep22 = {
        "per_gate": {"gate_01": {"blocked": False}, "gate_02": {"blocked": False}},
        "final_outcome": "passed",
    }
    _ere_d22 = diff_results(_ere_orig22, _ere_rep22)
    test("EventReplayExt: diff_results per-gate detects gate_01 change",
         _ere_d22["changed"] is True and "gate_01" in _ere_d22.get("new_passes", []),
         f"new_passes={_ere_d22.get('new_passes')}")

    # Test 23: summarise_replay with empty results
    _ere_sum23 = summarise_replay([])
    test("EventReplayExt: summarise_replay empty -> total=0",
         _ere_sum23["total"] == 0 and _ere_sum23["changed"] == 0,
         f"total={_ere_sum23['total']}")

    # Test 24: summarise_replay with mixed results
    _ere_items24 = [
        {"diff": {"changed": False}},
        {"diff": {"changed": True, "new_blocks": ["gate_01"], "new_passes": []},
         "event": {"_replay_meta": {"timestamp": "t1", "tool_name": "Edit"}}},
    ]
    _ere_sum24 = summarise_replay(_ere_items24)
    test("EventReplayExt: summarise_replay counts 1 changed, 1 unchanged",
         _ere_sum24["total"] == 2 and _ere_sum24["changed"] == 1 and _ere_sum24["unchanged"] == 1,
         f"total={_ere_sum24['total']}, changed={_ere_sum24['changed']}")

    try:
        os.unlink(_ere_tmp14.name)
    except OSError:
        pass

except Exception as _ere_exc:
    test("EventReplayExt: import and basic tests", False, str(_ere_exc))

# ─── Gate Helpers Tests ─────────────────────────────────────────────
print("\n--- Gate Helpers ---")
from shared.gate_helpers import (
    extract_file_path as gh_extract_file_path,
    is_test_file as gh_is_test_file,
    stem_normalize as gh_stem_normalize,
    is_related_file as gh_is_related_file,
    safe_tool_input as gh_safe_tool_input,
    extract_command as gh_extract_command,
    is_edit_tool as gh_is_edit_tool,
    file_extension as gh_file_extension,
    elapsed_since as gh_elapsed_since,
    is_stale as gh_is_stale,
)
import time as _gh_time

try:
    # --- extract_file_path ---
    test("GateHelpers: extract_file_path from Edit input",
         gh_extract_file_path({"file_path": "/tmp/foo.py"}) == "/tmp/foo.py",
         f"got {gh_extract_file_path({'file_path': '/tmp/foo.py'})}")

    test("GateHelpers: extract_file_path from NotebookEdit input",
         gh_extract_file_path({"notebook_path": "/tmp/nb.ipynb"}) == "/tmp/nb.ipynb",
         f"got {gh_extract_file_path({'notebook_path': '/tmp/nb.ipynb'})}")

    test("GateHelpers: extract_file_path from Glob path",
         gh_extract_file_path({"path": "/tmp/dir"}) == "/tmp/dir",
         f"got {gh_extract_file_path({'path': '/tmp/dir'})}")

    test("GateHelpers: extract_file_path empty dict returns ''",
         gh_extract_file_path({}) == "", f"got '{gh_extract_file_path({})}'")

    test("GateHelpers: extract_file_path non-dict returns ''",
         gh_extract_file_path("not a dict") == "", "")

    test("GateHelpers: extract_file_path prefers file_path over path",
         gh_extract_file_path({"file_path": "/a.py", "path": "/b"}) == "/a.py", "")

    # --- is_test_file ---
    test("GateHelpers: is_test_file('test_foo.py') = True",
         gh_is_test_file("test_foo.py") is True, "")

    test("GateHelpers: is_test_file('foo_test.py') = True",
         gh_is_test_file("foo_test.py") is True, "")

    test("GateHelpers: is_test_file('foo_spec.py') = True",
         gh_is_test_file("foo_spec.py") is True, "")

    test("GateHelpers: is_test_file('foo.test.js') = True",
         gh_is_test_file("foo.test.js") is True, "")

    test("GateHelpers: is_test_file('foo.py') = False",
         gh_is_test_file("foo.py") is False, "")

    test("GateHelpers: is_test_file('') = False",
         gh_is_test_file("") is False, "")

    # --- stem_normalize ---
    test("GateHelpers: stem_normalize('test_foo.py') = 'foo'",
         gh_stem_normalize("test_foo.py") == "foo",
         f"got '{gh_stem_normalize('test_foo.py')}'")

    test("GateHelpers: stem_normalize('foo_test.py') = 'foo'",
         gh_stem_normalize("foo_test.py") == "foo",
         f"got '{gh_stem_normalize('foo_test.py')}'")

    test("GateHelpers: stem_normalize('foo.py') = 'foo'",
         gh_stem_normalize("foo.py") == "foo",
         f"got '{gh_stem_normalize('foo.py')}'")

    test("GateHelpers: stem_normalize('') = ''",
         gh_stem_normalize("") == "", "")

    test("GateHelpers: stem_normalize preserves non-test stems",
         gh_stem_normalize("enforcer.py") == "enforcer", "")

    # --- is_related_file ---
    test("GateHelpers: foo.py related to test_foo.py",
         gh_is_related_file("foo.py", "test_foo.py") is True, "")

    test("GateHelpers: same basename in different dir is related",
         gh_is_related_file("/a/b/foo.py", "/c/d/foo.py") is True, "")

    test("GateHelpers: unrelated files are not related",
         gh_is_related_file("foo.py", "bar.py") is False, "")

    test("GateHelpers: empty paths are not related",
         gh_is_related_file("", "foo.py") is False, "")

    # --- safe_tool_input ---
    test("GateHelpers: safe_tool_input(dict) returns same dict",
         gh_safe_tool_input({"a": 1}) == {"a": 1}, "")

    test("GateHelpers: safe_tool_input(None) returns {}",
         gh_safe_tool_input(None) == {}, "")

    test("GateHelpers: safe_tool_input('str') returns {}",
         gh_safe_tool_input("str") == {}, "")

    # --- extract_command ---
    test("GateHelpers: extract_command from Bash input",
         gh_extract_command({"command": "ls -la"}) == "ls -la", "")

    test("GateHelpers: extract_command empty dict returns ''",
         gh_extract_command({}) == "", "")

    test("GateHelpers: extract_command non-dict returns ''",
         gh_extract_command(None) == "", "")

    # --- is_edit_tool ---
    test("GateHelpers: is_edit_tool('Edit') = True",
         gh_is_edit_tool("Edit") is True, "")

    test("GateHelpers: is_edit_tool('Write') = True",
         gh_is_edit_tool("Write") is True, "")

    test("GateHelpers: is_edit_tool('Bash') = False",
         gh_is_edit_tool("Bash") is False, "")

    # --- file_extension ---
    test("GateHelpers: file_extension('foo.py') = '.py'",
         gh_file_extension("foo.py") == ".py", "")

    test("GateHelpers: file_extension('FOO.JSON') = '.json'",
         gh_file_extension("FOO.JSON") == ".json", "")

    test("GateHelpers: file_extension('noext') = ''",
         gh_file_extension("noext") == "", "")

    test("GateHelpers: file_extension('') = ''",
         gh_file_extension("") == "", "")

    # --- elapsed_since ---
    _gh_recent = _gh_time.time() - 5.0
    _gh_elapsed = gh_elapsed_since(_gh_recent)
    test("GateHelpers: elapsed_since 5s ago is ~5s",
         4.0 < _gh_elapsed < 10.0,
         f"got {_gh_elapsed}")

    test("GateHelpers: elapsed_since(0) returns 0.0",
         gh_elapsed_since(0) == 0.0, "")

    test("GateHelpers: elapsed_since(None) returns 0.0",
         gh_elapsed_since(None) == 0.0, "")

    # --- is_stale ---
    test("GateHelpers: is_stale(recent, 60) = False",
         gh_is_stale(_gh_time.time() - 5, 60) is False, "")

    test("GateHelpers: is_stale(old, 10) = True",
         gh_is_stale(_gh_time.time() - 30, 10) is True, "")

    test("GateHelpers: is_stale(0, 60) = True (missing timestamp)",
         gh_is_stale(0, 60) is True, "")

except Exception as _gh_exc:
    test("GateHelpers: import and basic tests", False, str(_gh_exc))

# ─── Hot Reload Tests ───────────────────────────────────────────────
print("\n--- Hot Reload ---")
from shared.hot_reload import (
    discover_gate_modules, check_for_changes, seed_mtimes,
    get_reload_history, reload_gate, reset_state as hr_reset_state,
    auto_reload, _module_to_filepath, _get_mtime, _validate_module,
)
import tempfile as _hr_tempfile

try:
    hr_reset_state()

    # Test 1: discover_gate_modules returns list of gate modules
    _hr_gates = discover_gate_modules()
    test("HotReload: discover_gate_modules returns list",
         isinstance(_hr_gates, list) and len(_hr_gates) > 0,
         f"len={len(_hr_gates)}")

    # Test 2: all discovered modules start with "gates."
    _hr_all_prefixed = all(g.startswith("gates.") for g in _hr_gates)
    test("HotReload: all modules start with 'gates.'",
         _hr_all_prefixed, f"first non-prefixed: {[g for g in _hr_gates if not g.startswith('gates.')][:1]}")

    # Test 3: _module_to_filepath converts dotted name to .py path
    _hr_path = _module_to_filepath("gates.gate_01_read_before_edit")
    test("HotReload: _module_to_filepath resolves to .py file",
         _hr_path.endswith("gate_01_read_before_edit.py") and os.path.isfile(_hr_path),
         f"path={_hr_path}")

    # Test 4: _get_mtime returns float for existing file
    _hr_mtime = _get_mtime(_hr_path)
    test("HotReload: _get_mtime returns float for existing file",
         isinstance(_hr_mtime, float) and _hr_mtime > 0,
         f"mtime={_hr_mtime}")

    # Test 5: _get_mtime returns None for missing file
    test("HotReload: _get_mtime returns None for missing file",
         _get_mtime("/tmp/__nonexistent_gate_xyz__.py") is None, "")

    # Test 6: _validate_module succeeds for module with check()
    import types as _hr_types
    _hr_fake_mod = _hr_types.ModuleType("fake_valid")
    _hr_fake_mod.check = lambda *a, **kw: None
    test("HotReload: _validate_module True for module with check()",
         _validate_module(_hr_fake_mod) is True, "")

    # Test 7: _validate_module fails for module without check()
    _hr_fake_nocheck = _hr_types.ModuleType("fake_invalid")
    test("HotReload: _validate_module False for module without check()",
         _validate_module(_hr_fake_nocheck) is False, "")

    # Test 8: seed_mtimes records mtimes
    hr_reset_state()
    seed_mtimes(_hr_gates)
    _hr_hist_seed = get_reload_history()
    test("HotReload: seed_mtimes runs without error",
         isinstance(_hr_hist_seed, list),
         f"history len={len(_hr_hist_seed)}")

    # Test 9: check_for_changes returns {} after seeding
    hr_reset_state()
    seed_mtimes(_hr_gates)
    _hr_changes = check_for_changes(_hr_gates)
    test("HotReload: check_for_changes {} after seeding",
         isinstance(_hr_changes, dict) and len(_hr_changes) == 0,
         f"changes={len(_hr_changes)}")

    # Test 10: check_for_changes reports all as changed when cache empty
    hr_reset_state()
    _hr_changes_all = check_for_changes(_hr_gates)
    test("HotReload: all modules changed when cache empty",
         len(_hr_changes_all) == len(_hr_gates),
         f"changed={len(_hr_changes_all)}, total={len(_hr_gates)}")

    # Test 11: reload_gate succeeds for real gate
    hr_reset_state()
    if _hr_gates:
        _hr_reload_ok = reload_gate(_hr_gates[0])
        test("HotReload: reload_gate returns True for real gate",
             _hr_reload_ok is True,
             f"got {_hr_reload_ok}")
    else:
        skip("HotReload: reload_gate (no gates discovered)", "No gate files found")

    # Test 12: reload_gate returns False for non-existent module
    _hr_bad = reload_gate("gates.__nonexistent_test_gate_xyz__")
    test("HotReload: reload_gate False for missing gate",
         _hr_bad is False, f"got {_hr_bad}")

    # Test 13: get_reload_history returns list
    _hr_hist = get_reload_history()
    test("HotReload: get_reload_history returns list",
         isinstance(_hr_hist, list), f"type={type(_hr_hist).__name__}")

    # Test 14: history entries have expected keys
    if _hr_hist:
        _hr_entry = _hr_hist[0]
        _hr_has_keys = all(k in _hr_entry for k in ("module", "success", "timestamp", "reason"))
        test("HotReload: history entry has expected keys",
             _hr_has_keys,
             f"keys={set(_hr_entry.keys())}")
    else:
        skip("HotReload: history entry keys (no entries)", "Empty history")

    # Test 15: get_reload_history returns a copy
    _hr_hist1 = get_reload_history()
    _hr_hist1.append({"fake": True})
    _hr_hist2 = get_reload_history()
    test("HotReload: get_reload_history returns independent copy",
         {"fake": True} not in _hr_hist2,
         "List mutation leaked through")

    # Test 16: reset_state clears everything
    hr_reset_state()
    _hr_after_reset = get_reload_history()
    test("HotReload: reset_state clears history",
         len(_hr_after_reset) == 0,
         f"len={len(_hr_after_reset)}")

    # Test 17: auto_reload returns [] when nothing changed
    hr_reset_state()
    seed_mtimes(_hr_gates)
    # Force interval to expire
    import shared.hot_reload as _hr_mod
    _hr_mod._last_check_time = 0.0
    _hr_auto = auto_reload(_hr_gates)
    test("HotReload: auto_reload returns [] when nothing changed",
         isinstance(_hr_auto, list) and len(_hr_auto) == 0,
         f"reloaded={_hr_auto}")

    # Test 18: auto_reload returns [] before interval elapses
    _hr_mod._last_check_time = _gh_time.time()
    _hr_auto2 = auto_reload(_hr_gates)
    test("HotReload: auto_reload [] before interval elapses",
         isinstance(_hr_auto2, list) and len(_hr_auto2) == 0,
         f"reloaded={_hr_auto2}")

    # Test 19: discover_gate_modules with custom dir
    _hr_tmpdir = _hr_tempfile.mkdtemp()
    # Write a fake gate file
    with open(os.path.join(_hr_tmpdir, "gate_99_test.py"), "w") as _f:
        _f.write("def check(*a, **kw): pass\n")
    with open(os.path.join(_hr_tmpdir, "utils.py"), "w") as _f:
        _f.write("# not a gate\n")
    _hr_custom = discover_gate_modules(gates_dir=_hr_tmpdir)
    test("HotReload: discover_gate_modules custom dir finds gate_99_test",
         _hr_custom == ["gates.gate_99_test"],
         f"got {_hr_custom}")
    try:
        os.unlink(os.path.join(_hr_tmpdir, "gate_99_test.py"))
        os.unlink(os.path.join(_hr_tmpdir, "utils.py"))
        os.rmdir(_hr_tmpdir)
    except OSError:
        pass

    # Test 20: discover_gate_modules on non-existent dir returns []
    _hr_bad_dir = discover_gate_modules(gates_dir="/tmp/__nonexistent_gates_dir__")
    test("HotReload: discover_gate_modules missing dir returns []",
         _hr_bad_dir == [], f"got {_hr_bad_dir}")

    hr_reset_state()  # Clean up

except Exception as _hr_exc:
    test("HotReload: import and basic tests", False, str(_hr_exc))

# ─────────────────────────────────────────────────
# Gate Dependency Graph Extended (cycle detection, ordering)
# ─────────────────────────────────────────────────
print("\n--- Gate Dependency Graph Extended ---")

try:
    from shared.gate_dependency_graph import (
        generate_mermaid_diagram,
        find_state_conflicts,
        find_parallel_safe_gates,
        get_state_hotspots,
        detect_cycles,
        recommend_gate_ordering,
        format_dependency_report,
    )

    # Test 1: detect_cycles returns expected structure
    _dc = detect_cycles()
    test("DepGraph: detect_cycles returns has_cycles key",
         "has_cycles" in _dc, f"keys={list(_dc.keys())}")

    # Test 2: detect_cycles returns cycles list
    test("DepGraph: detect_cycles returns cycles list",
         isinstance(_dc.get("cycles"), list), f"type={type(_dc.get('cycles'))}")

    # Test 3: detect_cycles returns summary string
    test("DepGraph: detect_cycles returns summary string",
         isinstance(_dc.get("summary"), str) and len(_dc["summary"]) > 0,
         f"summary={_dc.get('summary', '')[:50]}")

    # Test 4: recommend_gate_ordering returns ordering list
    _ro = recommend_gate_ordering()
    test("DepGraph: recommend_ordering returns ordering list",
         isinstance(_ro.get("ordering"), list), f"keys={list(_ro.keys())}")

    # Test 5: recommend_gate_ordering returns tiers
    test("DepGraph: recommend_ordering returns tiers list",
         isinstance(_ro.get("tiers"), list), f"type={type(_ro.get('tiers'))}")

    # Test 6: recommend_gate_ordering has_cycles is bool
    test("DepGraph: recommend_ordering has_cycles is bool",
         isinstance(_ro.get("has_cycles"), bool), f"type={type(_ro.get('has_cycles'))}")

    # Test 7: format_dependency_report includes cycle section
    _fdr = format_dependency_report()
    test("DepGraph: format_report includes Cycle Detection",
         "Cycle Detection" in _fdr, f"report snippet={_fdr[:100]}")

    # Test 8: format_dependency_report includes ordering section
    test("DepGraph: format_report includes Recommended Gate Ordering",
         "Recommended Gate Ordering" in _fdr or "ordering" in _fdr.lower(),
         f"report length={len(_fdr)}")

    # Test 9: detect_cycles with synthetic acyclic graph
    import shared.gate_dependency_graph as _gdg
    _orig_load = _gdg._load_dependencies

    def _mock_acyclic():
        return {
            "gate_a": {"reads": [], "writes": ["key_x"]},
            "gate_b": {"reads": ["key_x"], "writes": ["key_y"]},
            "gate_c": {"reads": ["key_y"], "writes": []},
        }
    _gdg._load_dependencies = _mock_acyclic
    _dc_acyclic = detect_cycles()
    test("DepGraph: acyclic graph has no cycles",
         _dc_acyclic["has_cycles"] is False, f"cycles={_dc_acyclic['cycles']}")

    # Test 10: recommend_ordering on acyclic graph gives valid topo order
    _ro_acyclic = recommend_gate_ordering()
    test("DepGraph: acyclic ordering has all gates",
         set(_ro_acyclic["ordering"]) == {"gate_a", "gate_b", "gate_c"},
         f"ordering={_ro_acyclic['ordering']}")

    # Test 11: ordering respects dependencies (a before b before c)
    _idx_a = _ro_acyclic["ordering"].index("gate_a")
    _idx_b = _ro_acyclic["ordering"].index("gate_b")
    _idx_c = _ro_acyclic["ordering"].index("gate_c")
    test("DepGraph: acyclic ordering respects deps (a < b < c)",
         _idx_a < _idx_b < _idx_c, f"indices a={_idx_a} b={_idx_b} c={_idx_c}")

    # Test 12: tiers on acyclic graph have 3 tiers
    test("DepGraph: acyclic graph has 3 tiers",
         len(_ro_acyclic["tiers"]) == 3,
         f"tiers={_ro_acyclic['tiers']}")

    # Test 13: detect_cycles with synthetic cyclic graph
    def _mock_cyclic():
        return {
            "gate_a": {"reads": ["key_y"], "writes": ["key_x"]},
            "gate_b": {"reads": ["key_x"], "writes": ["key_y"]},
        }
    _gdg._load_dependencies = _mock_cyclic
    _dc_cyclic = detect_cycles()
    test("DepGraph: cyclic graph detects cycle",
         _dc_cyclic["has_cycles"] is True, f"cycles={_dc_cyclic['cycles']}")

    # Test 14: cyclic graph cycle contains both gates
    _cycle_gates = set()
    for c in _dc_cyclic["cycles"]:
        _cycle_gates.update(c)
    test("DepGraph: cyclic graph cycle contains gate_a and gate_b",
         "gate_a" in _cycle_gates and "gate_b" in _cycle_gates,
         f"cycle_gates={_cycle_gates}")

    # Test 15: recommend_ordering on cyclic graph still returns all gates
    _ro_cyclic = recommend_gate_ordering()
    test("DepGraph: cyclic ordering includes all gates",
         set(_ro_cyclic["ordering"]) == {"gate_a", "gate_b"},
         f"ordering={_ro_cyclic['ordering']}")

    # Test 16: cyclic ordering reports has_cycles=True
    test("DepGraph: cyclic ordering reports has_cycles",
         _ro_cyclic["has_cycles"] is True, f"has_cycles={_ro_cyclic['has_cycles']}")

    # Test 17: empty deps returns no cycles
    _gdg._load_dependencies = lambda: {}
    _dc_empty = detect_cycles()
    test("DepGraph: empty deps has no cycles",
         _dc_empty["has_cycles"] is False and _dc_empty["cycles"] == [],
         f"result={_dc_empty}")

    # Test 18: empty deps ordering is empty
    _ro_empty = recommend_gate_ordering()
    test("DepGraph: empty deps ordering is empty list",
         _ro_empty["ordering"] == [] and _ro_empty["tiers"] == [],
         f"result={_ro_empty}")

    # Test 19: independent gates (no shared keys) — no cycles, all in tier 0
    def _mock_independent():
        return {
            "gate_x": {"reads": [], "writes": ["key_a"]},
            "gate_y": {"reads": [], "writes": ["key_b"]},
            "gate_z": {"reads": [], "writes": ["key_c"]},
        }
    _gdg._load_dependencies = _mock_independent
    _dc_indep = detect_cycles()
    test("DepGraph: independent gates have no cycles",
         _dc_indep["has_cycles"] is False, f"cycles={_dc_indep['cycles']}")

    _ro_indep = recommend_gate_ordering()
    test("DepGraph: independent gates all in tier 0",
         len(_ro_indep["tiers"]) == 1 and len(_ro_indep["tiers"][0]) == 3,
         f"tiers={_ro_indep['tiers']}")

    # Restore original
    _gdg._load_dependencies = _orig_load

    # Test 21: find_state_conflicts returns list
    _conflicts = find_state_conflicts()
    test("DepGraph: find_state_conflicts returns list",
         isinstance(_conflicts, list), f"type={type(_conflicts)}")

    # Test 22: find_parallel_safe_gates returns dict with expected keys
    _parallel = find_parallel_safe_gates()
    test("DepGraph: parallel_safe_gates has expected keys",
         all(k in _parallel for k in ("independent_gates", "conflict_pairs", "total_gates")),
         f"keys={list(_parallel.keys())}")

    # Test 23: get_state_hotspots returns list
    _hotspots = get_state_hotspots()
    test("DepGraph: get_state_hotspots returns list",
         isinstance(_hotspots, list), f"type={type(_hotspots)}")

    # Test 24: generate_mermaid_diagram returns string with mermaid
    _mermaid = generate_mermaid_diagram()
    test("DepGraph: mermaid diagram contains mermaid tag",
         "```mermaid" in _mermaid, f"snippet={_mermaid[:50]}")

except Exception as _gdg_exc:
    test("DepGraph Extended: import and basic tests", False, str(_gdg_exc))

# ─────────────────────────────────────────────────
# Gate 05 Refactored (gate_helpers integration)
# ─────────────────────────────────────────────────
print("\n--- MCP Analytics Integration ---")

try:
    # Import analytics_server functions directly (not via MCP protocol)
    sys.path.insert(0, HOOKS_DIR)

    from analytics_server import (
        crash_proof,
        _detect_session_id,
        _resolve_session_id,
    )

    # Test 1: crash_proof decorator catches exceptions
    @crash_proof
    def _failing_tool():
        raise ValueError("test error")

    _cp_result = _failing_tool()
    test("MCP: crash_proof returns error dict on exception",
         isinstance(_cp_result, dict) and "error" in _cp_result,
         f"result={_cp_result}")

    # Test 2: crash_proof passes through normal returns
    @crash_proof
    def _ok_tool():
        return {"status": "ok"}

    _cp_ok = _ok_tool()
    test("MCP: crash_proof passes through normal return",
         _cp_ok == {"status": "ok"}, f"result={_cp_ok}")

    # Test 3: _detect_session_id returns string
    _sid = _detect_session_id()
    test("MCP: _detect_session_id returns string",
         isinstance(_sid, str) and len(_sid) > 0, f"sid={_sid}")

    # Test 4: _resolve_session_id with explicit ID returns it
    _rsid = _resolve_session_id("my-test-session")
    test("MCP: _resolve_session_id explicit returns same",
         _rsid == "my-test-session", f"rsid={_rsid}")

    # Test 5: _resolve_session_id empty auto-detects
    _rsid_auto = _resolve_session_id("")
    test("MCP: _resolve_session_id empty auto-detects",
         isinstance(_rsid_auto, str) and len(_rsid_auto) > 0,
         f"rsid={_rsid_auto}")

    # Test framework_summary (aggregation tool)
    from analytics_server import framework_summary
    _fs = framework_summary()
    test("MCP: framework_summary returns dict",
         isinstance(_fs, dict), f"type={type(_fs)}")
    test("MCP: framework_summary has health_score",
         "health_score" in _fs, f"keys={list(_fs.keys())}")
    test("MCP: framework_summary has skills_total",
         "skills_total" in _fs, f"keys={list(_fs.keys())}")

    # Test circuit_states
    from analytics_server import circuit_states
    _cs = circuit_states()
    test("MCP: circuit_states returns dict",
         isinstance(_cs, dict), f"type={type(_cs)}")
    test("MCP: circuit_states has services key",
         "services" in _cs, f"keys={list(_cs.keys())}")
    test("MCP: circuit_states has gates key",
         "gates" in _cs, f"keys={list(_cs.keys())}")
    test("MCP: circuit_states total_services is int",
         isinstance(_cs.get("total_services"), int), f"val={_cs.get('total_services')}")

    # Test gate_dependencies (with new cycle detection)
    from analytics_server import gate_dependencies
    _gd = gate_dependencies()
    test("MCP: gate_dependencies returns dict",
         isinstance(_gd, dict), f"type={type(_gd)}")
    test("MCP: gate_dependencies has conflicts key",
         "conflicts" in _gd, f"keys={list(_gd.keys())}")
    test("MCP: gate_dependencies has cycles key",
         "cycles" in _gd, f"keys={list(_gd.keys())}")
    test("MCP: gate_dependencies has recommended_ordering key",
         "recommended_ordering" in _gd, f"keys={list(_gd.keys())}")
    test("MCP: gate_dependencies cycles has has_cycles",
         "has_cycles" in _gd.get("cycles", {}),
         f"cycles_keys={list(_gd.get('cycles', {}).keys())}")
    test("MCP: gate_dependencies ordering has ordering list",
         isinstance(_gd.get("recommended_ordering", {}).get("ordering"), list),
         f"type={type(_gd.get('recommended_ordering', {}).get('ordering'))}")

    # Test cache_health
    from analytics_server import cache_health
    _ch = cache_health()
    test("MCP: cache_health returns dict",
         isinstance(_ch, dict), f"type={type(_ch)}")
    test("MCP: cache_health has module_cache",
         "module_cache" in _ch, f"keys={list(_ch.keys())}")
    test("MCP: cache_health has state_cache",
         "state_cache" in _ch, f"keys={list(_ch.keys())}")
    test("MCP: cache_health has result_cache",
         "result_cache" in _ch, f"keys={list(_ch.keys())}")
    test("MCP: cache_health module hit_rate is float",
         isinstance(_ch.get("module_cache", {}).get("hit_rate"), float),
         f"val={_ch.get('module_cache', {}).get('hit_rate')}")

    # Test gate_sla_status
    from analytics_server import gate_sla_status
    _gss = gate_sla_status()
    test("MCP: gate_sla_status returns dict",
         isinstance(_gss, dict), f"type={type(_gss)}")
    test("MCP: gate_sla_status has total_gates",
         "total_gates" in _gss, f"keys={list(_gss.keys())}")
    test("MCP: gate_sla_status has ok count",
         "ok" in _gss, f"keys={list(_gss.keys())}")

    # Test gate_sla_status with custom threshold
    _gss_custom = gate_sla_status(threshold_ms=10)
    test("MCP: gate_sla_status custom threshold returns dict",
         isinstance(_gss_custom, dict) and "total_gates" in _gss_custom,
         f"keys={list(_gss_custom.keys())}")

    # Test event_stats
    from analytics_server import event_stats
    _es = event_stats()
    test("MCP: event_stats returns dict",
         isinstance(_es, dict), f"type={type(_es)}")
    test("MCP: event_stats has stats key",
         "stats" in _es, f"keys={list(_es.keys())}")
    test("MCP: event_stats has recent_events",
         "recent_events" in _es, f"keys={list(_es.keys())}")

    # Test event_stats with filter
    _es_filtered = event_stats(event_type="GATE_BLOCKED", limit=5)
    test("MCP: event_stats filtered returns dict",
         isinstance(_es_filtered, dict), f"type={type(_es_filtered)}")
    test("MCP: event_stats filtered has filter field",
         _es_filtered.get("filter") == "GATE_BLOCKED",
         f"filter={_es_filtered.get('filter')}")

    # Test gate_trends
    from analytics_server import gate_trends
    _gt = gate_trends()
    test("MCP: gate_trends returns dict",
         isinstance(_gt, dict), f"type={type(_gt)}")
    test("MCP: gate_trends has snapshot_count",
         "snapshot_count" in _gt, f"keys={list(_gt.keys())}")

    # Test all_metrics
    from analytics_server import all_metrics
    _am = all_metrics()
    test("MCP: all_metrics returns dict",
         isinstance(_am, dict), f"type={type(_am)}")
    test("MCP: all_metrics has current key",
         "current" in _am, f"keys={list(_am.keys())}")
    test("MCP: all_metrics has rollup_1m",
         "rollup_1m" in _am, f"keys={list(_am.keys())}")
    test("MCP: all_metrics has rollup_5m",
         "rollup_5m" in _am, f"keys={list(_am.keys())}")

    # Test preview_gates (dry-run simulator)
    from analytics_server import preview_gates
    _pg = preview_gates("Read")
    test("MCP: preview_gates Read returns dict",
         isinstance(_pg, dict), f"type={type(_pg)}")
    test("MCP: preview_gates has tool_name",
         _pg.get("tool_name") == "Read", f"tool_name={_pg.get('tool_name')}")
    test("MCP: preview_gates has would_block",
         "would_block" in _pg, f"keys={list(_pg.keys())}")
    test("MCP: preview_gates has gates_checked",
         isinstance(_pg.get("gates_checked"), int), f"val={_pg.get('gates_checked')}")

    # Test preview_gates with Edit tool (more gates apply)
    _pg_edit = preview_gates("Edit", '{"file_path": "/tmp/test.py"}')
    test("MCP: preview_gates Edit checks more gates",
         _pg_edit.get("gates_checked", 0) > _pg.get("gates_checked", 0),
         f"edit={_pg_edit.get('gates_checked')} > read={_pg.get('gates_checked')}")

    # Test preview_gates with invalid JSON input
    _pg_bad = preview_gates("Bash", "not valid json")
    test("MCP: preview_gates handles invalid JSON gracefully",
         isinstance(_pg_bad, dict) and "would_block" in _pg_bad,
         f"result keys={list(_pg_bad.keys())}")

    # Test skill_health
    from analytics_server import skill_health
    _sh = skill_health()
    test("MCP: skill_health returns dict",
         isinstance(_sh, dict), f"type={type(_sh)}")
    test("MCP: skill_health has total_skills key",
         "total_skills" in _sh, f"keys={list(_sh.keys())}")

    # Test gate_dashboard
    from analytics_server import gate_dashboard
    _gdb = gate_dashboard()
    test("MCP: gate_dashboard returns dict",
         isinstance(_gdb, dict), f"type={type(_gdb)}")
    test("MCP: gate_dashboard has dashboard text",
         "dashboard" in _gdb, f"keys={list(_gdb.keys())}")
    test("MCP: gate_dashboard has ranked_gates",
         "ranked_gates" in _gdb, f"keys={list(_gdb.keys())}")

    # Test memory_health
    from analytics_server import memory_health
    _mh = memory_health()
    test("MCP: memory_health returns dict",
         isinstance(_mh, dict), f"type={type(_mh)}")
    test("MCP: memory_health has lance_exists",
         "lance_exists" in _mh, f"keys={list(_mh.keys())}")
    test("MCP: memory_health has tables key",
         "tables" in _mh, f"keys={list(_mh.keys())}")

    # Test session_replay
    from analytics_server import session_replay
    _sr = session_replay(lookback_hours=1)
    test("MCP: session_replay returns dict",
         isinstance(_sr, dict), f"type={type(_sr)}")
    test("MCP: session_replay has event_count",
         "event_count" in _sr, f"keys={list(_sr.keys())}")

    # Test session_replay mermaid format
    _sr_m = session_replay(format="mermaid")
    test("MCP: session_replay mermaid returns dict with mermaid key",
         "mermaid" in _sr_m, f"keys={list(_sr_m.keys())}")

    # Test session_replay stats format
    _sr_s = session_replay(format="stats")
    test("MCP: session_replay stats returns dict",
         isinstance(_sr_s, dict) and "total_events" in _sr_s,
         f"keys={list(_sr_s.keys())}")

    # Test session_replay patterns format
    _sr_p = session_replay(format="patterns")
    test("MCP: session_replay patterns returns dict with healthy key",
         "healthy" in _sr_p, f"keys={list(_sr_p.keys())}")

    # Test framework_pulse
    from analytics_server import framework_pulse
    _fp = framework_pulse(lookback_hours=1)
    test("MCP: framework_pulse returns dict",
         isinstance(_fp, dict), f"type={type(_fp)}")
    test("MCP: framework_pulse has health_score",
         "health_score" in _fp, f"keys={list(_fp.keys())}")
    test("MCP: framework_pulse health_score 0-100",
         0 <= _fp.get("health_score", -1) <= 100,
         f"score={_fp.get('health_score')}")
    test("MCP: framework_pulse has hotspots",
         "hotspots" in _fp, f"keys={list(_fp.keys())}")
    test("MCP: framework_pulse has gate_trends",
         "gate_trends" in _fp, f"keys={list(_fp.keys())}")
    test("MCP: framework_pulse has circuits",
         "circuits" in _fp, f"keys={list(_fp.keys())}")

except Exception as _mcp_exc:
    import traceback as _mcp_tb
    test("MCP Analytics Integration: import and tests", False,
         f"{_mcp_exc}\n{_mcp_tb.format_exc()}")

# ─────────────────────────────────────────────────
# New MCP Tools: fix_effectiveness, query_observations, inspect_domain
# ─────────────────────────────────────────────────
print("\n--- New MCP Tools ---")

try:
    # Test fix_effectiveness
    from analytics_server import fix_effectiveness

    # Test 1: fix_effectiveness no filter
    _fe = fix_effectiveness()
    test("MCP fix_effectiveness: returns dict",
         isinstance(_fe, dict), f"type={type(_fe)}")
    test("MCP fix_effectiveness: has total_fix_attempts",
         "total_fix_attempts" in _fe, f"keys={list(_fe.keys())}")
    test("MCP fix_effectiveness: has unique_errors",
         "unique_errors" in _fe, f"keys={list(_fe.keys())}")
    test("MCP fix_effectiveness: has overall_success_rate",
         "overall_success_rate" in _fe, f"keys={list(_fe.keys())}")
    test("MCP fix_effectiveness: overall_success_rate is float",
         isinstance(_fe.get("overall_success_rate"), (int, float)),
         f"val={_fe.get('overall_success_rate')}")

    # Test 2: fix_effectiveness with filter
    _fe_import = fix_effectiveness(error_type="ImportError")
    test("MCP fix_effectiveness: filtered has error_type",
         _fe_import.get("error_type") == "ImportError",
         f"error_type={_fe_import.get('error_type')}")
    test("MCP fix_effectiveness: filtered has strategies list",
         isinstance(_fe_import.get("strategies"), list),
         f"type={type(_fe_import.get('strategies'))}")
    test("MCP fix_effectiveness: filtered has best_strategy",
         "best_strategy" in _fe_import,
         f"keys={list(_fe_import.keys())}")

    # Test 3: fix_effectiveness with unknown error type
    _fe_unknown = fix_effectiveness(error_type="ZZZNonexistentErrorZZZ")
    test("MCP fix_effectiveness: unknown error has empty strategies",
         _fe_unknown.get("strategies") == [] or _fe_unknown.get("best_strategy") == "",
         f"strategies={_fe_unknown.get('strategies', 'missing')}")

    # Test query_observations
    from analytics_server import query_observations

    # Test 4: query_observations basic call
    _qo = query_observations()
    test("MCP query_observations: returns dict",
         isinstance(_qo, dict), f"type={type(_qo)}")
    test("MCP query_observations: has total key",
         "total" in _qo, f"keys={list(_qo.keys())}")
    test("MCP query_observations: has observations list",
         isinstance(_qo.get("observations"), list),
         f"type={type(_qo.get('observations'))}")

    # Test 5: query_observations with filters
    _qo_err = query_observations(error_only=True, limit=5)
    test("MCP query_observations: error_only returns dict",
         isinstance(_qo_err, dict) and "total" in _qo_err,
         f"keys={list(_qo_err.keys())}")
    test("MCP query_observations: filters_applied correct",
         _qo_err.get("filters_applied", {}).get("error_only") is True,
         f"filters={_qo_err.get('filters_applied')}")

    # Test 6: query_observations with tool_name filter
    _qo_tool = query_observations(tool_name="Bash", limit=5)
    test("MCP query_observations: tool_name filter applied",
         _qo_tool.get("filters_applied", {}).get("tool_name") == "Bash",
         f"filters={_qo_tool.get('filters_applied')}")

    # Test 7: query_observations with priority filter
    _qo_pri = query_observations(priority="high", limit=5)
    test("MCP query_observations: priority filter applied",
         _qo_pri.get("filters_applied", {}).get("priority") == "high",
         f"filters={_qo_pri.get('filters_applied')}")

    # Test 8: query_observations has sentiment_breakdown
    test("MCP query_observations: has sentiment_breakdown",
         "sentiment_breakdown" in _qo,
         f"keys={list(_qo.keys())}")

    # Test inspect_domain
    from analytics_server import inspect_domain

    # Test 9: inspect_domain basic call
    _id = inspect_domain()
    test("MCP inspect_domain: returns dict",
         isinstance(_id, dict), f"type={type(_id)}")
    test("MCP inspect_domain: has active_domain key",
         "active_domain" in _id, f"keys={list(_id.keys())}")
    test("MCP inspect_domain: has total_domains",
         "total_domains" in _id, f"keys={list(_id.keys())}")
    test("MCP inspect_domain: has domains list",
         isinstance(_id.get("domains"), list),
         f"type={type(_id.get('domains'))}")
    test("MCP inspect_domain: total_domains matches list length",
         _id.get("total_domains") == len(_id.get("domains", [])),
         f"total={_id.get('total_domains')}, list_len={len(_id.get('domains', []))}")

    # Test 10: If there's an active domain, check detail
    if _id.get("active_domain"):
        _detail = _id.get("active_detail", {})
        test("MCP inspect_domain: active_detail has mastery",
             "mastery" in _detail, f"detail_keys={list(_detail.keys())}")
        test("MCP inspect_domain: active_detail has behavior",
             "behavior" in _detail, f"detail_keys={list(_detail.keys())}")
        test("MCP inspect_domain: active_detail has gate_overrides",
             "gate_overrides" in _detail, f"detail_keys={list(_detail.keys())}")
        test("MCP inspect_domain: active_detail has token_budget",
             "token_budget" in _detail, f"detail_keys={list(_detail.keys())}")
        test("MCP inspect_domain: active_detail has over_budget bool",
             isinstance(_detail.get("over_budget"), bool),
             f"type={type(_detail.get('over_budget'))}")
        test("MCP inspect_domain: active_detail has graduation",
             "graduation" in _detail, f"detail_keys={list(_detail.keys())}")
    else:
        test("MCP inspect_domain: no active domain → no active_detail",
             "active_detail" not in _id, f"keys={list(_id.keys())}")

except Exception as _new_mcp_exc:
    import traceback as _new_mcp_tb
    test("New MCP Tools: import and tests", False,
         f"{_new_mcp_exc}\n{_new_mcp_tb.format_exc()}")

# ─────────────────────────────────────────────────
# Experience Archive Integration
# ─────────────────────────────────────────────────
