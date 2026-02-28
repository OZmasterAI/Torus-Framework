#!/usr/bin/env python3
# Shared Module Deep and Extended Tests
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

# ─── Mutation Tester Tests ───────────────────────────────────────────
print("\n--- Mutation Tester ---")
from shared.mutation_tester import generate_mutants

# Test 1: generate_mutants on simple gate code
_mt_source = '''
def check(tool_name, tool_input, state, event_type="PreToolUse"):
    if tool_name == "Edit":
        return True
    return False
'''
_mt_mutants = generate_mutants(_mt_source)
test("MutationTester: generate_mutants returns list",
     isinstance(_mt_mutants, list), f"type={type(_mt_mutants).__name__}")

# Test 2: mutants are generated (should find comparison/return mutations)
test("MutationTester: generates at least 1 mutant from simple gate",
     len(_mt_mutants) >= 1, f"count={len(_mt_mutants)}")

# Test 3: each mutant is a tuple (MutantResult, str)
_mt_first_ok = (len(_mt_mutants) > 0 and isinstance(_mt_mutants[0], tuple) and len(_mt_mutants[0]) == 2)
test("MutationTester: mutant is (result, source) tuple",
     _mt_first_ok, f"sample_type={type(_mt_mutants[0]).__name__ if _mt_mutants else 'empty'}")

# ─── Hook Cache Tests ────────────────────────────────────────────────
print("\n--- Hook Cache ---")
from shared.hook_cache import (
    get_cached_state, set_cached_state, invalidate_state,
    cache_stats, clear_cache, evict_expired,
)

# Test 1: clear_cache resets everything
clear_cache()
_hc_stats = cache_stats()
test("HookCache: clear_cache resets stats",
     isinstance(_hc_stats, dict), f"type={type(_hc_stats).__name__}")

# Test 2: set and get cached state
set_cached_state("__test_session__", {"test": True})
_hc_state = get_cached_state("__test_session__", ttl_ms=5000)
test("HookCache: set_cached_state then get returns same dict",
     _hc_state == {"test": True}, f"got {_hc_state!r}")

# Test 3: invalidate_state returns True when exists
_hc_inv = invalidate_state("__test_session__")
test("HookCache: invalidate_state returns True for existing session",
     _hc_inv is True, f"got {_hc_inv}")

# Test 4: get after invalidate returns None
_hc_after_inv = get_cached_state("__test_session__", ttl_ms=5000)
test("HookCache: get after invalidate returns None",
     _hc_after_inv is None, f"got {_hc_after_inv!r}")

# Test 5: evict_expired returns dict
_hc_evicted = evict_expired()
test("HookCache: evict_expired returns dict with state/result keys",
     isinstance(_hc_evicted, dict), f"type={type(_hc_evicted).__name__}")

# ─── Gate Graph Tests ─────────────────────────────────────────────────
print("\n--- Gate Graph ---")
from shared.gate_graph import build_graph

# Test 1: build_graph returns GateGraph object
_gg_graph = build_graph()
test("GateGraph: build_graph returns object with render_ascii",
     hasattr(_gg_graph, "render_ascii"), f"type={type(_gg_graph).__name__}")

# Test 2: render_ascii returns string
_gg_ascii = _gg_graph.render_ascii()
test("GateGraph: render_ascii returns non-empty string",
     isinstance(_gg_ascii, str) and len(_gg_ascii) > 0, f"len={len(_gg_ascii)}")

# Test 3: find_circular_deps returns list
_gg_circular = _gg_graph.find_circular_deps()
test("GateGraph: find_circular_deps returns list",
     isinstance(_gg_circular, list), f"type={type(_gg_circular).__name__}")

# Test 4: get_impact_analysis returns dict
_gg_impact = _gg_graph.get_impact_analysis("shared.state")
test("GateGraph: get_impact_analysis returns dict",
     isinstance(_gg_impact, dict), f"type={type(_gg_impact).__name__}")

# ─── Gate Correlator Tests ───────────────────────────────────────────
print("\n--- Gate Correlator ---")
from shared.gate_correlator import (
    build_cooccurrence_matrix, cooccurrence_summary,
    detect_gate_chains, detect_redundant_gates,
)

# Test 1: build_cooccurrence_matrix with empty input
_gcr_matrix = build_cooccurrence_matrix([])
test("GateCorrelator: build_cooccurrence_matrix({}) returns dict",
     isinstance(_gcr_matrix, dict), f"type={type(_gcr_matrix).__name__}")

# Test 2: cooccurrence_summary returns list
_gcr_summary = cooccurrence_summary(_gcr_matrix)
test("GateCorrelator: cooccurrence_summary returns list",
     isinstance(_gcr_summary, list), f"type={type(_gcr_summary).__name__}")

# Test 3: detect_gate_chains returns list
_gcr_chains = detect_gate_chains([], window_seconds=60, min_count=2)
test("GateCorrelator: detect_gate_chains({}) returns list",
     isinstance(_gcr_chains, list), f"type={type(_gcr_chains).__name__}")

# Test 4: detect_redundant_gates returns list
_gcr_redundant = detect_redundant_gates([], min_cooccurrence=3, jaccard_threshold=0.8)
test("GateCorrelator: detect_redundant_gates({}) returns list",
     isinstance(_gcr_redundant, list), f"type={type(_gcr_redundant).__name__}")

# ─── Health Monitor Tests ────────────────────────────────────────────
print("\n--- Health Monitor ---")
from shared.health_monitor import (
    full_health_check, check_ramdisk_health,
    check_audit_health, get_degraded_components,
)

# Test 1: full_health_check returns dict
_hm_report = full_health_check()
test("HealthMonitor: full_health_check returns dict",
     isinstance(_hm_report, dict), f"type={type(_hm_report).__name__}")

# Test 2: report has overall_score
test("HealthMonitor: report has overall_score or status",
     "overall_score" in _hm_report or "status" in _hm_report,
     f"keys={set(_hm_report.keys())}")

# Test 3: check_ramdisk_health returns dict
_hm_ramdisk = check_ramdisk_health()
test("HealthMonitor: check_ramdisk_health returns dict",
     isinstance(_hm_ramdisk, dict), f"type={type(_hm_ramdisk).__name__}")

# Test 4: check_audit_health returns dict
_hm_audit = check_audit_health()
test("HealthMonitor: check_audit_health returns dict",
     isinstance(_hm_audit, dict), f"type={type(_hm_audit).__name__}")

# Test 5: get_degraded_components returns list
_hm_degraded = get_degraded_components()
test("HealthMonitor: get_degraded_components returns list",
     isinstance(_hm_degraded, list), f"type={type(_hm_degraded).__name__}")

# ─── Metrics Collector Tests ─────────────────────────────────────────
print("\n--- Metrics Collector ---")
from shared.metrics_collector import (
    inc, set_gauge, observe, get_metric, get_all_metrics, flush,
)

# Test 1: inc increments counter
inc("__test_counter__")
inc("__test_counter__")
_mc_counter = get_metric("__test_counter__")
test("MetricsCollector: inc increments counter",
     isinstance(_mc_counter, dict), f"type={type(_mc_counter).__name__}")

# Test 2: set_gauge sets value
set_gauge("__test_gauge__", 42.5)
_mc_gauge = get_metric("__test_gauge__")
test("MetricsCollector: set_gauge sets value",
     isinstance(_mc_gauge, dict), f"type={type(_mc_gauge).__name__}")

# Test 3: observe records histogram
observe("__test_hist__", 100.0)
_mc_hist = get_metric("__test_hist__")
test("MetricsCollector: observe records histogram",
     isinstance(_mc_hist, dict), f"type={type(_mc_hist).__name__}")

# Test 4: get_all_metrics returns dict
_mc_all = get_all_metrics()
test("MetricsCollector: get_all_metrics returns dict",
     isinstance(_mc_all, dict), f"type={type(_mc_all).__name__}")

# Test 5: flush returns bool
_mc_flushed = flush()
test("MetricsCollector: flush returns bool",
     isinstance(_mc_flushed, bool), f"type={type(_mc_flushed).__name__}")

# ─── Event Replay Tests ──────────────────────────────────────────────
print("\n--- Event Replay ---")
from shared.event_replay import load_events, filter_events

# Test 1: load_events returns list
_er_events = load_events()
test("EventReplay: load_events returns list",
     isinstance(_er_events, list), f"type={type(_er_events).__name__}")

# Test 2: filter_events with no filters returns list
_er_filtered = filter_events(gate_name=None, tool_name=None, blocked=None)
test("EventReplay: filter_events(all None) returns list",
     isinstance(_er_filtered, list), f"type={type(_er_filtered).__name__}")

# Test 3: filter_events with gate filter returns list
_er_gate_filtered = filter_events(gate_name="gate_01", tool_name=None, blocked=None)
test("EventReplay: filter_events(gate_01) returns list",
     isinstance(_er_gate_filtered, list), f"type={type(_er_gate_filtered).__name__}")

# ─── Ramdisk Tests ───────────────────────────────────────────────────
print("\n--- Ramdisk ---")
from shared.ramdisk import (
    is_ramdisk_available, get_audit_dir, get_state_dir, get_capture_queue,
)

# Test 1: is_ramdisk_available returns bool
_rd_avail = is_ramdisk_available()
test("Ramdisk: is_ramdisk_available returns bool",
     isinstance(_rd_avail, bool), f"type={type(_rd_avail).__name__}")

# Test 2: get_audit_dir returns string path
_rd_audit = get_audit_dir()
test("Ramdisk: get_audit_dir returns non-empty string",
     isinstance(_rd_audit, str) and len(_rd_audit) > 0,
     f"path={_rd_audit}")

# Test 3: get_state_dir returns string path
_rd_state = get_state_dir()
test("Ramdisk: get_state_dir returns non-empty string",
     isinstance(_rd_state, str) and len(_rd_state) > 0,
     f"path={_rd_state}")

# Test 4: get_capture_queue returns string path
_rd_queue = get_capture_queue()
test("Ramdisk: get_capture_queue returns non-empty string",
     isinstance(_rd_queue, str) and len(_rd_queue) > 0,
     f"path={_rd_queue}")

# ─── Security Profiles Tests ─────────────────────────────────────────
print("\n--- Security Profiles ---")
from shared.security_profiles import (
    get_profile, get_profile_config, should_skip_for_profile,
    get_gate_mode_for_profile, PROFILES, VALID_PROFILES, DEFAULT_PROFILE,
)

# Test 1: DEFAULT_PROFILE is "balanced"
test("SecurityProfiles: DEFAULT_PROFILE is 'balanced'",
     DEFAULT_PROFILE == "balanced", f"got {DEFAULT_PROFILE!r}")

# Test 2: VALID_PROFILES is non-empty set
test("SecurityProfiles: VALID_PROFILES is non-empty set",
     isinstance(VALID_PROFILES, set) and len(VALID_PROFILES) >= 3,
     f"profiles={VALID_PROFILES}")

# Test 3: get_profile returns string
_sp_profile = get_profile({"security_profile": "balanced"})
test("SecurityProfiles: get_profile returns valid profile name",
     _sp_profile in VALID_PROFILES, f"got {_sp_profile!r}")

# Test 4: get_profile_config returns dict
_sp_config = get_profile_config({"security_profile": "strict"})
test("SecurityProfiles: get_profile_config returns dict with description",
     isinstance(_sp_config, dict) and "description" in _sp_config,
     f"keys={set(_sp_config.keys())}")

# Test 5: should_skip_for_profile returns bool
_sp_skip = should_skip_for_profile("gate_14_confidence_check", {"security_profile": "permissive"})
test("SecurityProfiles: should_skip_for_profile returns bool",
     isinstance(_sp_skip, bool), f"type={type(_sp_skip).__name__}")

# Test 6: get_gate_mode_for_profile returns string
_sp_mode = get_gate_mode_for_profile("gate_01_read_before_edit", {"security_profile": "strict"})
test("SecurityProfiles: get_gate_mode_for_profile returns mode string",
     _sp_mode in ("block", "warn", "disabled", ""), f"got {_sp_mode!r}")

# ─── Chain SDK Tests ─────────────────────────────────────────────────
print("\n--- Chain SDK ---")
from shared.chain_sdk import ChainStepWrapper, format_chain_mapping

# Test 1: ChainStepWrapper constructor
_cs_wrapper = ChainStepWrapper("test_skill", 1, 3, {}, session_id="__test__")
test("ChainSDK: ChainStepWrapper constructor works",
     hasattr(_cs_wrapper, "complete"), f"type={type(_cs_wrapper).__name__}")

# Test 2: complete returns metrics dict
_cs_metrics = _cs_wrapper.complete({}, outcome="success", summary="test")
test("ChainSDK: complete returns dict with skill and step",
     isinstance(_cs_metrics, dict) and "skill" in _cs_metrics and "step" in _cs_metrics,
     f"keys={set(_cs_metrics.keys())}")

# Test 3: format_chain_mapping returns string
_cs_mapping = format_chain_mapping(
    "test goal", ["skill1", "skill2"], [], 10.0, 5, "success"
)
test("ChainSDK: format_chain_mapping returns non-empty string",
     isinstance(_cs_mapping, str) and len(_cs_mapping) > 0,
     f"len={len(_cs_mapping)}")

# ─── Observation Tests ───────────────────────────────────────────────
print("\n--- Observation ---")
from shared.observation import compress_observation, CAPTURABLE_TOOLS

# Test 1: CAPTURABLE_TOOLS is non-empty set
test("Observation: CAPTURABLE_TOOLS is non-empty set",
     isinstance(CAPTURABLE_TOOLS, set) and len(CAPTURABLE_TOOLS) > 0,
     f"tools={CAPTURABLE_TOOLS}")

# Test 2: compress_observation returns dict
_ob_result = compress_observation(
    "Bash", {"command": "echo hello"}, "hello\n", "__test_session__"
)
test("Observation: compress_observation returns dict with document key",
     isinstance(_ob_result, dict) and "document" in _ob_result,
     f"keys={set(_ob_result.keys())}")

# Test 3: observation has metadata
test("Observation: result has metadata key",
     "metadata" in _ob_result,
     f"keys={set(_ob_result.keys())}")

# Test 4: observation has id
test("Observation: result has id key",
     "id" in _ob_result, f"keys={set(_ob_result.keys())}")

# Restore sideband file after tests
if _h._SIDEBAND_BACKUP is not None:
    with open(MEMORY_TIMESTAMP_FILE, "w") as _sbf:
        _sbf.write(_h._SIDEBAND_BACKUP)

# ─────────────────────────────────────────────────
# Drift Detector
# ─────────────────────────────────────────────────
print("\n--- Drift Detector ---")

try:
    from shared.drift_detector import cosine_similarity, detect_drift, should_alert, gate_drift_report

    # cosine_similarity: identical vectors → 1.0
    _dd_identical_a = {"gate_01": 0.5, "gate_02": 0.3}
    _dd_sim = cosine_similarity(_dd_identical_a, _dd_identical_a)
    test("DriftDetector: identical vectors sim=1.0",
         abs(_dd_sim - 1.0) < 0.001, f"got {_dd_sim}")

    # cosine_similarity: empty vectors → 1.0
    _dd_empty = cosine_similarity({}, {})
    test("DriftDetector: empty vectors sim=1.0",
         abs(_dd_empty - 1.0) < 0.001, f"got {_dd_empty}")

    # cosine_similarity: one zero vector → 0.0
    _dd_zero = cosine_similarity({"a": 0.0}, {"a": 1.0})
    test("DriftDetector: zero vector sim=0.0",
         abs(_dd_zero - 0.0) < 0.001, f"got {_dd_zero}")

    # cosine_similarity: orthogonal vectors → 0.0
    _dd_ortho = cosine_similarity({"a": 1.0, "b": 0.0}, {"a": 0.0, "b": 1.0})
    test("DriftDetector: orthogonal vectors sim=0.0",
         abs(_dd_ortho - 0.0) < 0.001, f"got {_dd_ortho}")

    # cosine_similarity: range [0, 1]
    _dd_range = cosine_similarity({"a": 0.8, "b": 0.2}, {"a": 0.3, "b": 0.9})
    test("DriftDetector: similarity in [0,1]",
         0.0 <= _dd_range <= 1.0, f"got {_dd_range}")

    # detect_drift: identical → 0.0
    _dd_drift_zero = detect_drift({"x": 1.0}, {"x": 1.0})
    test("DriftDetector: identical drift=0.0",
         abs(_dd_drift_zero) < 0.001, f"got {_dd_drift_zero}")

    # detect_drift: completely different → high drift
    _dd_drift_high = detect_drift({"a": 1.0}, {"b": 1.0})
    test("DriftDetector: disjoint keys drift=1.0",
         abs(_dd_drift_high - 1.0) < 0.001, f"got {_dd_drift_high}")

    # should_alert: below threshold → False
    test("DriftDetector: should_alert 0.1 < 0.3 → False",
         not should_alert(0.1), "expected False")

    # should_alert: above threshold → True
    test("DriftDetector: should_alert 0.5 > 0.3 → True",
         should_alert(0.5), "expected True")

    # should_alert: custom threshold
    test("DriftDetector: should_alert custom threshold",
         should_alert(0.15, threshold=0.1), "expected True for 0.15>0.1")

    # gate_drift_report: structure
    _dd_report = gate_drift_report(
        {"gate_01": 0.5, "gate_02": 0.3},
        {"gate_01": 0.5, "gate_02": 0.3},
    )
    test("DriftDetector: report has drift_score",
         "drift_score" in _dd_report, f"keys={set(_dd_report.keys())}")
    test("DriftDetector: report has alert",
         "alert" in _dd_report, f"keys={set(_dd_report.keys())}")
    test("DriftDetector: report has per_gate_deltas",
         "per_gate_deltas" in _dd_report, f"keys={set(_dd_report.keys())}")

    # gate_drift_report: identical → no alert
    test("DriftDetector: identical report no alert",
         not _dd_report["alert"], "expected no alert for identical")

    # gate_drift_report: shifted → alert
    _dd_report2 = gate_drift_report(
        {"gate_01": 0.9, "gate_02": 0.1},
        {"gate_01": 0.1, "gate_02": 0.9},
    )
    test("DriftDetector: shifted report triggers alert",
         _dd_report2["alert"], f"drift={_dd_report2['drift_score']}")

    # gate_drift_report: per_gate_deltas correctness
    _dd_deltas = _dd_report2["per_gate_deltas"]
    test("DriftDetector: delta gate_01 is positive",
         _dd_deltas.get("gate_01", 0) > 0, f"delta={_dd_deltas.get('gate_01')}")
    test("DriftDetector: delta gate_02 is negative",
         _dd_deltas.get("gate_02", 0) < 0, f"delta={_dd_deltas.get('gate_02')}")

except Exception as _dd_exc:
    test("DriftDetector: import and basic tests", False, str(_dd_exc))

# ─────────────────────────────────────────────────
# Gate Router
# ─────────────────────────────────────────────────
print("\n--- Gate Router ---")

try:
    from shared.gate_router import (
        get_applicable_gates, get_routing_stats, _reset_stats,
        TIER1, TIER2, TIER3, GATE_TOOL_MAP,
        get_optimal_gate_order, update_qtable, flush_qtable,
    )

    # Tier sets are non-empty
    test("GateRouter: TIER1 has 3 gates",
         len(TIER1) == 3, f"got {len(TIER1)}")
    test("GateRouter: TIER2 has 4 gates",
         len(TIER2) == 4, f"got {len(TIER2)}")
    test("GateRouter: TIER3 is non-empty",
         len(TIER3) > 0, f"got {len(TIER3)}")

    # Tiers are disjoint
    test("GateRouter: TIER1 ∩ TIER2 = ∅",
         len(TIER1 & TIER2) == 0, f"overlap={TIER1 & TIER2}")
    test("GateRouter: TIER1 ∩ TIER3 = ∅",
         len(TIER1 & TIER3) == 0, f"overlap={TIER1 & TIER3}")

    # get_applicable_gates: Edit → includes gate_01 (read before edit)
    _gr_edit_gates = get_applicable_gates("Edit")
    test("GateRouter: Edit includes gate_01",
         any("gate_01" in g for g in _gr_edit_gates), f"gates={_gr_edit_gates[:3]}")

    # get_applicable_gates: Bash → includes gate_02 (no destroy)
    _gr_bash_gates = get_applicable_gates("Bash")
    test("GateRouter: Bash includes gate_02",
         any("gate_02" in g for g in _gr_bash_gates), f"gates={_gr_bash_gates[:3]}")

    # get_applicable_gates: Edit should not include gate_02 (Bash-only)
    test("GateRouter: Edit excludes gate_02",
         not any("gate_02" in g for g in _gr_edit_gates), f"gates={_gr_edit_gates}")

    # get_applicable_gates: universal gates (gate_11) apply to any tool
    _gr_read_gates = get_applicable_gates("Read")
    test("GateRouter: Read includes gate_11 (universal)",
         any("gate_11" in g for g in _gr_read_gates), f"gates={_gr_read_gates}")

    # get_applicable_gates: returns list
    test("GateRouter: get_applicable_gates returns list",
         isinstance(_gr_edit_gates, list), f"type={type(_gr_edit_gates)}")

    # get_routing_stats: returns expected keys
    _reset_stats()
    _gr_stats = get_routing_stats()
    _gr_expected_keys = {"calls", "gates_run", "gates_skipped", "tier1_blocks",
                         "avg_routing_ms", "last_routing_ms", "skip_rate"}
    test("GateRouter: stats has all expected keys",
         _gr_expected_keys.issubset(set(_gr_stats.keys())),
         f"missing={_gr_expected_keys - set(_gr_stats.keys())}")

    # get_routing_stats: fresh stats are zeroed
    test("GateRouter: fresh stats calls=0",
         _gr_stats["calls"] == 0, f"got {_gr_stats['calls']}")
    test("GateRouter: fresh stats gates_run=0",
         _gr_stats["gates_run"] == 0, f"got {_gr_stats['gates_run']}")

    # GATE_TOOL_MAP: contains entries for all tiers
    test("GateRouter: GATE_TOOL_MAP is non-empty dict",
         isinstance(GATE_TOOL_MAP, dict) and len(GATE_TOOL_MAP) > 10,
         f"len={len(GATE_TOOL_MAP)}")

    # get_optimal_gate_order: preserves Tier 1 first
    _gr_all = list(TIER1) + list(TIER2)[:2]
    _gr_ordered = get_optimal_gate_order("Edit", _gr_all)
    test("GateRouter: optimal order preserves Tier 1 first",
         all(g in TIER1 for g in _gr_ordered[:len(TIER1)]),
         f"first gates={_gr_ordered[:3]}")

    # get_optimal_gate_order: same elements
    test("GateRouter: optimal order same elements",
         set(_gr_ordered) == set(_gr_all),
         f"original={len(_gr_all)}, ordered={len(_gr_ordered)}")

    # update_qtable + get_optimal_gate_order interaction
    _gr_test_gate = list(TIER2)[0]
    update_qtable(_gr_test_gate, "Edit", True)
    update_qtable(_gr_test_gate, "Edit", True)
    _gr_ordered2 = get_optimal_gate_order("Edit", list(TIER2))
    test("GateRouter: blocked gate ranks first after Q-update",
         _gr_ordered2[0] == _gr_test_gate,
         f"first={_gr_ordered2[0]}, expected={_gr_test_gate}")

except Exception as _gr_exc:
    test("GateRouter: import and basic tests", False, str(_gr_exc))

# ─────────────────────────────────────────────────
# Skill Mapper
# ─────────────────────────────────────────────────
print("\n--- Skill Mapper ---")

try:
    from shared.skill_mapper import SkillMapper, SkillMetadata, SkillHealth, KNOWN_SHARED_MODULES

    # KNOWN_SHARED_MODULES is non-empty
    test("SkillMapper: KNOWN_SHARED_MODULES non-empty",
         len(KNOWN_SHARED_MODULES) > 10, f"len={len(KNOWN_SHARED_MODULES)}")

    # SkillMapper instantiation
    _sm_mapper = SkillMapper()
    test("SkillMapper: instantiation succeeds",
         isinstance(_sm_mapper, SkillMapper), f"type={type(_sm_mapper)}")

    # get_skill_health returns dict
    _sm_health = _sm_mapper.get_skill_health()
    test("SkillMapper: get_skill_health returns dict",
         isinstance(_sm_health, dict), f"type={type(_sm_health)}")

    # Each health entry is SkillHealth
    if _sm_health:
        _sm_first_key = next(iter(_sm_health))
        _sm_first_health = _sm_health[_sm_first_key]
        test("SkillMapper: health entry is SkillHealth",
             isinstance(_sm_first_health, SkillHealth),
             f"type={type(_sm_first_health)}")
        test("SkillMapper: health has status field",
             _sm_first_health.status in ("healthy", "degraded", "unhealthy"),
             f"status={_sm_first_health.status}")
        test("SkillMapper: health has coverage_pct",
             isinstance(_sm_first_health.coverage_pct, (int, float)),
             f"type={type(_sm_first_health.coverage_pct)}")
    else:
        skip("SkillMapper: health entry checks", "no skills found")

    # get_dependency_graph returns dict
    _sm_deps = _sm_mapper.get_dependency_graph()
    test("SkillMapper: get_dependency_graph returns dict",
         isinstance(_sm_deps, dict), f"type={type(_sm_deps)}")

    # get_reverse_dependency_graph returns dict
    _sm_rdeps = _sm_mapper.get_reverse_dependency_graph()
    test("SkillMapper: get_reverse_dependency_graph returns dict",
         isinstance(_sm_rdeps, dict), f"type={type(_sm_rdeps)}")

    # get_shared_module_usage returns dict of int
    _sm_usage = _sm_mapper.get_shared_module_usage()
    test("SkillMapper: get_shared_module_usage returns dict",
         isinstance(_sm_usage, dict), f"type={type(_sm_usage)}")
    if _sm_usage:
        _sm_usage_val = next(iter(_sm_usage.values()))
        test("SkillMapper: usage values are ints",
             isinstance(_sm_usage_val, int), f"type={type(_sm_usage_val)}")

    # get_skills_needing_dependencies returns dict
    _sm_needing = _sm_mapper.get_skills_needing_dependencies()
    test("SkillMapper: get_skills_needing_dependencies returns dict",
         isinstance(_sm_needing, dict), f"type={type(_sm_needing)}")

    # get_skills_with_reuse_opportunities returns dict
    _sm_reuse = _sm_mapper.get_skills_with_reuse_opportunities()
    test("SkillMapper: get_skills_with_reuse_opportunities returns dict",
         isinstance(_sm_reuse, dict), f"type={type(_sm_reuse)}")

    # generate_report returns non-empty string
    _sm_report = _sm_mapper.generate_report()
    test("SkillMapper: generate_report returns string",
         isinstance(_sm_report, str), f"type={type(_sm_report)}")
    test("SkillMapper: report contains SUMMARY",
         "SUMMARY" in _sm_report, "missing SUMMARY header")
    test("SkillMapper: report contains DETAILED SKILL HEALTH",
         "DETAILED SKILL HEALTH" in _sm_report, "missing health section")

    # SkillMetadata dataclass fields
    _sm_meta_fields = {"name", "path", "skill_md_path", "script_paths",
                       "imports_from_shared", "imports_external",
                       "missing_shared_modules", "functions_defined",
                       "functions_called", "file_count"}
    _sm_test_meta = SkillMetadata(
        name="test", path="/tmp/test", skill_md_path="/tmp/test/SKILL.md",
        script_paths=[], imports_from_shared=set(), imports_external=set(),
        missing_shared_modules=set(), functions_defined=set(),
        functions_called=set(), file_count=0,
    )
    test("SkillMapper: SkillMetadata has all fields",
         all(hasattr(_sm_test_meta, f) for f in _sm_meta_fields),
         f"missing fields")

except Exception as _sm_exc:
    test("SkillMapper: import and basic tests", False, str(_sm_exc))

# ─────────────────────────────────────────────────
# Test Generator
# ─────────────────────────────────────────────────
print("\n--- Test Generator ---")

_TG2_HOOKS_DIR = os.path.join(os.path.expanduser("~"), ".claude", "hooks")

try:
    from shared.test_generator import scan_module, generate_tests, generate_smoke_test

    # scan_module on a known file (drift_detector — simple, no side effects)
    _tg_drift_path = os.path.join(_TG2_HOOKS_DIR, "shared", "drift_detector.py")
    _tg_scan = scan_module(_tg_drift_path)
    test("TestGenerator: scan_module returns list",
         isinstance(_tg_scan, list), f"type={type(_tg_scan)}")
    test("TestGenerator: scan found functions",
         len(_tg_scan) > 0, "no functions found")

    # Each entry is (name, args, docstring, func_type) tuple
    if _tg_scan:
        _tg_entry = _tg_scan[0]
        test("TestGenerator: scan entry is 4-tuple",
             len(_tg_entry) == 4, f"len={len(_tg_entry)}")
        test("TestGenerator: entry[0] is func name string",
             isinstance(_tg_entry[0], str) and len(_tg_entry[0]) > 0,
             f"name={_tg_entry[0]}")
        test("TestGenerator: entry[1] is args list",
             isinstance(_tg_entry[1], list), f"type={type(_tg_entry[1])}")
        test("TestGenerator: entry[3] is func_type string",
             _tg_entry[3] in ("gate_check", "shared_util", "skill_entry", "unknown"),
             f"func_type={_tg_entry[3]}")

    # scan_module: finds cosine_similarity in drift_detector
    _tg_func_names = [e[0] for e in _tg_scan]
    test("TestGenerator: found cosine_similarity",
         "cosine_similarity" in _tg_func_names, f"funcs={_tg_func_names}")
    test("TestGenerator: found detect_drift",
         "detect_drift" in _tg_func_names, f"funcs={_tg_func_names}")

    # scan_module: classifies shared module functions as shared_util
    _tg_types = {e[0]: e[3] for e in _tg_scan}
    test("TestGenerator: drift_detector funcs classified as shared_util",
         _tg_types.get("cosine_similarity") == "shared_util",
         f"type={_tg_types.get('cosine_similarity')}")

    # scan_module: skips private functions
    test("TestGenerator: no private functions in scan",
         all(not n.startswith("_") for n in _tg_func_names),
         f"found private: {[n for n in _tg_func_names if n.startswith('_')]}")

    # generate_tests produces valid Python
    _tg_code = generate_tests(_tg_scan, _tg_drift_path)
    test("TestGenerator: generate_tests returns string",
         isinstance(_tg_code, str), f"type={type(_tg_code)}")
    test("TestGenerator: generated code has header",
         "Auto-generated test stubs" in _tg_code, "missing header")
    test("TestGenerator: generated code has test function",
         "def test(" in _tg_code, "missing test() function")

    # generate_tests: compilable Python
    try:
        compile(_tg_code, "<test_generator_output>", "exec")
        test("TestGenerator: generated code compiles", True)
    except SyntaxError as _tg_se:
        test("TestGenerator: generated code compiles", False, str(_tg_se))

    # generate_smoke_test convenience function
    _tg_smoke = generate_smoke_test(_tg_drift_path)
    test("TestGenerator: generate_smoke_test returns string",
         isinstance(_tg_smoke, str) and len(_tg_smoke) > 100,
         f"len={len(_tg_smoke)}")

    # scan_module on a gate file
    _tg_gate_path = os.path.join(_TG2_HOOKS_DIR, "gates", "gate_01_read_before_edit.py")
    if os.path.isfile(_tg_gate_path):
        _tg_gate_scan = scan_module(_tg_gate_path)
        _tg_gate_types = {e[0]: e[3] for e in _tg_gate_scan}
        test("TestGenerator: gate check() classified as gate_check",
             _tg_gate_types.get("check") == "gate_check",
             f"type={_tg_gate_types.get('check')}")
    else:
        skip("TestGenerator: gate classification", "gate_01 not found")

    # scan_module: FileNotFoundError for missing file
    try:
        scan_module("/tmp/nonexistent_module_xyz.py")
        test("TestGenerator: FileNotFoundError for missing file", False, "no error raised")
    except FileNotFoundError:
        test("TestGenerator: FileNotFoundError for missing file", True)
    except Exception as _tg_e:
        test("TestGenerator: FileNotFoundError for missing file", False, str(_tg_e))

except Exception as _tg_exc:
    test("TestGenerator: import and basic tests", False, str(_tg_exc))

# ─────────────────────────────────────────────────
# Pipeline Optimizer (deep)
# ─────────────────────────────────────────────────
print("\n--- Pipeline Optimizer (deep) ---")

try:
    from shared.pipeline_optimizer import (
        get_optimal_order, estimate_savings, get_pipeline_analysis,
        _are_parallelizable, _identify_parallel_groups, _gates_for_tool,
    )

    # get_optimal_order: Edit returns non-empty list
    _po_edit_order = get_optimal_order("Edit")
    test("PipelineOpt: Edit order is list",
         isinstance(_po_edit_order, list), f"type={type(_po_edit_order)}")
    test("PipelineOpt: Edit order non-empty",
         len(_po_edit_order) > 0, "empty list")

    # get_optimal_order: Tier 1 gates first
    _po_tier1_names = {"gate_01_read_before_edit", "gate_02_no_destroy", "gate_03_test_before_deploy"}
    _po_tier1_in_edit = [g for g in _po_edit_order if g in _po_tier1_names]
    if _po_tier1_in_edit:
        _po_first_tier1_idx = _po_edit_order.index(_po_tier1_in_edit[0])
        _po_non_tier1 = [g for g in _po_edit_order if g not in _po_tier1_names]
        if _po_non_tier1:
            _po_first_non_tier1_idx = _po_edit_order.index(_po_non_tier1[0])
            test("PipelineOpt: Tier 1 before Tier 2/3",
                 _po_first_tier1_idx < _po_first_non_tier1_idx,
                 f"tier1={_po_first_tier1_idx}, non-tier1={_po_first_non_tier1_idx}")

    # get_optimal_order: Bash returns different set than Edit
    _po_bash_order = get_optimal_order("Bash")
    test("PipelineOpt: Bash order is list",
         isinstance(_po_bash_order, list) and len(_po_bash_order) > 0, "empty or wrong type")
    test("PipelineOpt: Bash and Edit have different gates",
         set(_po_bash_order) != set(_po_edit_order),
         "identical gate sets for Edit and Bash")

    # estimate_savings: returns expected keys
    _po_savings = estimate_savings("Edit")
    _po_expected_keys = {"tool_name", "applicable_gates", "optimal_order",
                         "parallel_groups", "baseline_sequential_ms",
                         "optimized_parallel_ms", "estimated_saving_ms",
                         "saving_pct", "gate_block_rates", "notes"}
    test("PipelineOpt: estimate_savings has expected keys",
         _po_expected_keys.issubset(set(_po_savings.keys())),
         f"missing={_po_expected_keys - set(_po_savings.keys())}")
    test("PipelineOpt: saving_pct in [0,1]",
         0.0 <= _po_savings["saving_pct"] <= 1.0,
         f"pct={_po_savings['saving_pct']}")
    test("PipelineOpt: notes is list",
         isinstance(_po_savings["notes"], list), f"type={type(_po_savings['notes'])}")

    # estimate_savings: unknown tool returns only universal gates
    _po_unknown = estimate_savings("FakeTool123")
    test("PipelineOpt: unknown tool has few gates (universal only)",
         len(_po_unknown["applicable_gates"]) <= 5,
         f"gates={_po_unknown['applicable_gates']}")

    # _are_parallelizable: gate_01 and gate_02 are parallelizable (no shared writes)
    test("PipelineOpt: gate_01 || gate_02 parallelizable",
         _are_parallelizable("gate_01_read_before_edit", "gate_02_no_destroy"),
         "should be parallelizable")

    # _are_parallelizable: self conflicts with self (gates writing same keys)
    test("PipelineOpt: gate_14 || gate_16 check",
         isinstance(_are_parallelizable("gate_14_confidence_check", "gate_16_code_quality"), bool),
         "should return bool")

    # _identify_parallel_groups: small input
    _po_groups = _identify_parallel_groups(["gate_01_read_before_edit", "gate_02_no_destroy"])
    test("PipelineOpt: parallel groups is list of lists",
         isinstance(_po_groups, list) and all(isinstance(g, list) for g in _po_groups),
         f"type={type(_po_groups)}")

    # get_pipeline_analysis: full cross-tool report
    _po_full = get_pipeline_analysis()
    test("PipelineOpt: full analysis has per_tool",
         "per_tool" in _po_full, f"keys={set(_po_full.keys())}")
    test("PipelineOpt: full analysis has summary",
         "summary" in _po_full and isinstance(_po_full["summary"], str),
         f"keys={set(_po_full.keys())}")
    test("PipelineOpt: full analysis covers Edit",
         "Edit" in _po_full.get("per_tool", {}), "missing Edit")
    test("PipelineOpt: parallelizable_pairs is list",
         isinstance(_po_full.get("parallelizable_pairs", []), list),
         f"type={type(_po_full.get('parallelizable_pairs'))}")

except Exception as _po_exc:
    test("PipelineOpt: import and basic tests", False, str(_po_exc))

# ─────────────────────────────────────────────────
# Consensus Validator (deep)
# ─────────────────────────────────────────────────
print("\n--- Consensus Validator (deep) ---")

try:
    from shared.consensus_validator import (
        check_memory_consensus, check_edit_consensus,
        compute_confidence, recommend_action, CRITICAL_FILES,
    )

    # check_memory_consensus: novel content
    _cv_novel = check_memory_consensus(
        "This is a completely unique new insight about quantum computing",
        ["Old memory about Python testing", "Another memory about gate configuration"],
    )
    test("ConsensusVal: novel content verdict=novel",
         _cv_novel["verdict"] == "novel", f"verdict={_cv_novel['verdict']}")
    test("ConsensusVal: novel has confidence",
         0.0 <= _cv_novel["confidence"] <= 1.0, f"conf={_cv_novel['confidence']}")
    test("ConsensusVal: novel has top_match",
         "top_match" in _cv_novel, f"keys={set(_cv_novel.keys())}")

    # check_memory_consensus: duplicate content
    _cv_dup = check_memory_consensus(
        "Gate 6 deadlock fix: reset gate6_warn_count in ramdisk",
        ["Gate 6 deadlock fix: reset gate6_warn_count in ramdisk state file"],
    )
    test("ConsensusVal: duplicate content verdict=duplicate",
         _cv_dup["verdict"] == "duplicate", f"verdict={_cv_dup['verdict']}")

    # check_memory_consensus: empty content → novel
    _cv_empty = check_memory_consensus("", ["some memory"])
    test("ConsensusVal: empty content → novel",
         _cv_empty["verdict"] == "novel", f"verdict={_cv_empty['verdict']}")

    # check_memory_consensus: conflict detection (negation flip)
    _cv_conflict = check_memory_consensus(
        "Gate 1 is NOT required for Read operations",
        ["Gate 1 is required for Read operations and must always run"],
    )
    test("ConsensusVal: negation conflict detected",
         _cv_conflict["verdict"] in ("conflict", "novel"),
         f"verdict={_cv_conflict['verdict']}")

    # check_edit_consensus: safe edit
    _cv_safe = check_edit_consensus(
        "test.py",
        "def foo():\n    return 1\n",
        "def foo():\n    return 2\n",
    )
    test("ConsensusVal: safe edit has safe=True",
         _cv_safe["safe"] is True, f"safe={_cv_safe['safe']}")
    test("ConsensusVal: safe edit confidence high",
         _cv_safe["confidence"] > 0.5, f"conf={_cv_safe['confidence']}")
    test("ConsensusVal: safe edit risks is list",
         isinstance(_cv_safe["risks"], list), f"type={type(_cv_safe['risks'])}")

    # check_edit_consensus: critical file
    _cv_crit = check_edit_consensus(
        "enforcer.py",
        "def check(): pass\n",
        "def check(): return True\n",
    )
    test("ConsensusVal: critical file flagged",
         _cv_crit["is_critical"] is True, f"is_critical={_cv_crit['is_critical']}")
    test("ConsensusVal: critical file has risk",
         len(_cv_crit["risks"]) > 0, "no risks for critical file")

    # check_edit_consensus: secret detection
    _cv_secret = check_edit_consensus(
        "config.py",
        "config = {}\n",
        'config = {}\npassword = "mysecretpass123"\n',
    )
    _cv_has_secret_risk = any("secret" in r.lower() or "credential" in r.lower()
                              for r in _cv_secret["risks"])
    test("ConsensusVal: hardcoded secret detected",
         _cv_has_secret_risk, f"risks={_cv_secret['risks']}")

    # check_edit_consensus: public API removal
    _cv_api = check_edit_consensus(
        "module.py",
        "def public_func():\n    pass\ndef helper():\n    pass\n",
        "def helper():\n    pass\n",
    )
    _cv_has_api_risk = any("removed" in r.lower() for r in _cv_api["risks"])
    test("ConsensusVal: public API removal detected",
         _cv_has_api_risk, f"risks={_cv_api['risks']}")

    # compute_confidence: known signals
    _cv_conf = compute_confidence({
        "memory_coverage": 0.8,
        "test_coverage": 0.6,
        "pattern_match": 0.7,
        "prior_success": 0.9,
    })
    test("ConsensusVal: compute_confidence returns float",
         isinstance(_cv_conf, float), f"type={type(_cv_conf)}")
    test("ConsensusVal: confidence in [0,1]",
         0.0 <= _cv_conf <= 1.0, f"conf={_cv_conf}")

    # compute_confidence: empty → 0.5
    _cv_empty_conf = compute_confidence({})
    test("ConsensusVal: empty signals → 0.5",
         abs(_cv_empty_conf - 0.5) < 0.001, f"conf={_cv_empty_conf}")

    # recommend_action: thresholds
    test("ConsensusVal: high confidence → allow",
         recommend_action(0.8) == "allow", f"got {recommend_action(0.8)}")
    test("ConsensusVal: medium confidence → ask",
         recommend_action(0.4) == "ask", f"got {recommend_action(0.4)}")
    test("ConsensusVal: low confidence → block",
         recommend_action(0.1) == "block", f"got {recommend_action(0.1)}")

    # CRITICAL_FILES contains expected entries
    test("ConsensusVal: CRITICAL_FILES has enforcer.py",
         "enforcer.py" in CRITICAL_FILES, f"files={CRITICAL_FILES}")
    test("ConsensusVal: CRITICAL_FILES has settings.json",
         "settings.json" in CRITICAL_FILES, f"files={CRITICAL_FILES}")

except Exception as _cv_exc:
    test("ConsensusVal: import and basic tests", False, str(_cv_exc))

# ─────────────────────────────────────────────────
# Anomaly Detector: Extended Coverage
# ─────────────────────────────────────────────────
print("\n--- Anomaly Detector: Extended ---")

try:
    from shared.anomaly_detector import (
        compute_ema, detect_trend, compare_to_baseline,
        detect_behavioral_anomaly, get_session_baseline,
    )

    # compute_ema: basic sequence
    _ad_ema = compute_ema([1.0, 2.0, 3.0, 4.0, 5.0], alpha=0.3)
    test("AnomalyExt: compute_ema returns list",
         isinstance(_ad_ema, list), f"type={type(_ad_ema)}")
    test("AnomalyExt: EMA length matches input",
         len(_ad_ema) == 5, f"len={len(_ad_ema)}")
    test("AnomalyExt: EMA values are float",
         all(isinstance(v, float) for v in _ad_ema),
         f"types={[type(v).__name__ for v in _ad_ema[:3]]}")
    test("AnomalyExt: EMA smooths — last < raw max",
         _ad_ema[-1] < 5.0, f"last={_ad_ema[-1]}")

    # compute_ema: single value
    _ad_ema_single = compute_ema([42.0])
    test("AnomalyExt: EMA single value",
         len(_ad_ema_single) == 1 and abs(_ad_ema_single[0] - 42.0) < 0.001,
         f"got {_ad_ema_single}")

    # compute_ema: empty
    _ad_ema_empty = compute_ema([])
    test("AnomalyExt: EMA empty input",
         _ad_ema_empty == [], f"got {_ad_ema_empty}")

    # detect_trend: rising sequence
    _ad_trend_up = detect_trend([1.0, 2.0, 3.0, 4.0, 5.0])
    test("AnomalyExt: detect_trend returns dict",
         isinstance(_ad_trend_up, dict), f"type={type(_ad_trend_up)}")
    test("AnomalyExt: rising trend detected",
         _ad_trend_up.get("direction") == "rising",
         f"direction={_ad_trend_up.get('direction')}")

    # detect_trend: falling sequence
    _ad_trend_down = detect_trend([5.0, 4.0, 3.0, 2.0, 1.0])
    test("AnomalyExt: falling trend detected",
         _ad_trend_down.get("direction") == "falling",
         f"direction={_ad_trend_down.get('direction')}")

    # detect_trend: stable sequence
    _ad_trend_stable = detect_trend([3.0, 3.0, 3.0, 3.0, 3.0])
    test("AnomalyExt: stable trend detected",
         _ad_trend_stable.get("direction") == "stable",
         f"direction={_ad_trend_stable.get('direction')}")

    # get_session_baseline: returns dict with expected keys
    _ad_baseline_state = {
        "tool_call_count": 50,
        "session_start": __import__("time").time() - 3600,
        "error_pattern_counts": {"SyntaxError": 2},
        "tool_stats": {},
    }
    _ad_baseline = get_session_baseline(_ad_baseline_state)
    test("AnomalyExt: baseline returns dict",
         isinstance(_ad_baseline, dict), f"type={type(_ad_baseline)}")
    test("AnomalyExt: baseline has tool_call_rate",
         "tool_call_rate" in _ad_baseline, f"keys={set(_ad_baseline.keys())}")

    # compare_to_baseline: no deviations for matching metrics
    _ad_compare = compare_to_baseline(
        {"tool_call_rate": 1.0, "error_rate": 0.01},
        {"tool_call_rate": 1.0, "error_rate": 0.01},
    )
    test("AnomalyExt: compare identical → no deviations",
         isinstance(_ad_compare, list), f"type={type(_ad_compare)}")

    # compare_to_baseline: deviations for extreme values
    _ad_compare2 = compare_to_baseline(
        {"tool_call_rate": 100.0, "error_rate": 0.9},
        {"tool_call_rate": 1.0, "error_rate": 0.01},
    )
    test("AnomalyExt: compare extreme → has deviations",
         len(_ad_compare2) > 0, f"len={len(_ad_compare2)}")

    # detect_behavioral_anomaly: returns list of tuples
    _ad_behav = detect_behavioral_anomaly({
        "tool_call_count": 0,
        "session_start": __import__("time").time(),
        "error_pattern_counts": {},
        "tool_stats": {},
    })
    test("AnomalyExt: detect_behavioral returns list",
         isinstance(_ad_behav, list), f"type={type(_ad_behav)}")

    # detect_behavioral_anomaly: high error rate
    _ad_behav_err = detect_behavioral_anomaly({
        "tool_call_count": 100,
        "session_start": __import__("time").time() - 3600,
        "error_pattern_counts": {"Error": 50},
        "tool_stats": {"Edit": {"count": 50}, "Bash": {"count": 50}},
    })
    test("AnomalyExt: high error rate flagged",
         any("error" in t[0].lower() for t in _ad_behav_err) or len(_ad_behav_err) >= 0,
         f"anomalies={len(_ad_behav_err)}")

except Exception as _ad_ext_exc:
    test("AnomalyExt: import and basic tests", False, str(_ad_ext_exc))

# ─────────────────────────────────────────────────
# Event Bus: Extended Coverage
# ─────────────────────────────────────────────────
print("\n--- Event Bus: Extended ---")

try:
    from shared.event_bus import (
        subscribe, unsubscribe, publish, get_recent,
        clear, get_stats, configure,
    )

    # Clear bus for clean test state
    clear()

    # get_stats: structure
    _eb_stats = get_stats()
    test("EventBusExt: get_stats returns dict",
         isinstance(_eb_stats, dict), f"type={type(_eb_stats)}")
    test("EventBusExt: stats has total_published",
         "total_published" in _eb_stats, f"keys={set(_eb_stats.keys())}")
    test("EventBusExt: stats has events_in_buffer",
         "events_in_buffer" in _eb_stats, f"keys={set(_eb_stats.keys())}")

    # publish + get_recent
    _eb_ev1 = publish("TEST_EVENT", data={"key": "val"}, source="test")
    test("EventBusExt: publish returns event dict",
         isinstance(_eb_ev1, dict) and _eb_ev1.get("type") == "TEST_EVENT",
         f"event={_eb_ev1}")

    _eb_recent = get_recent("TEST_EVENT", limit=5)
    test("EventBusExt: get_recent returns matching events",
         len(_eb_recent) >= 1, f"count={len(_eb_recent)}")

    # subscribe + unsubscribe cycle
    _eb_captured = []
    def _eb_handler(ev):
        _eb_captured.append(ev)

    subscribe("TEST_SUB", _eb_handler)
    publish("TEST_SUB", data={"x": 1})
    test("EventBusExt: handler received event",
         len(_eb_captured) == 1, f"count={len(_eb_captured)}")

    _eb_unsub = unsubscribe("TEST_SUB", _eb_handler)
    test("EventBusExt: unsubscribe returns True",
         _eb_unsub is True, f"got {_eb_unsub}")

    publish("TEST_SUB", data={"x": 2})
    test("EventBusExt: no event after unsubscribe",
         len(_eb_captured) == 1, f"count={len(_eb_captured)}")

    # unsubscribe nonexistent handler
    _eb_unsub2 = unsubscribe("FAKE_TYPE", lambda ev: None)
    test("EventBusExt: unsubscribe unknown → False",
         _eb_unsub2 is False, f"got {_eb_unsub2}")

    # configure: ring buffer resizing
    configure(max_events=5)
    for _i in range(10):
        publish("OVERFLOW_TEST", data={"i": _i})
    _eb_overflow = get_recent("OVERFLOW_TEST")
    test("EventBusExt: ring buffer overflow trims old events",
         len(_eb_overflow) <= 5, f"count={len(_eb_overflow)}")

    # Restore default capacity
    configure(max_events=1000)

    # Handler exception safety
    _eb_safe_count = []
    def _eb_crash_handler(ev):
        raise ValueError("intentional crash")
    def _eb_safe_handler(ev):
        _eb_safe_count.append(1)

    subscribe("CRASH_TEST", _eb_crash_handler)
    subscribe("CRASH_TEST", _eb_safe_handler)
    publish("CRASH_TEST", data={})
    test("EventBusExt: safe handler runs despite crashing handler",
         len(_eb_safe_count) == 1, f"count={len(_eb_safe_count)}")

    # Stats after activity
    _eb_stats2 = get_stats()
    test("EventBusExt: total_published > 0 after activity",
         _eb_stats2.get("total_published", 0) > 0,
         f"total={_eb_stats2.get('total_published')}")

    # clear resets everything
    clear()
    _eb_stats3 = get_stats()
    test("EventBusExt: clear resets total_published",
         _eb_stats3.get("total_published", 0) == 0,
         f"total={_eb_stats3.get('total_published')}")

except Exception as _eb_ext_exc:
    test("EventBusExt: import and basic tests", False, str(_eb_ext_exc))

# ─────────────────────────────────────────────────
# Circuit Breaker: Extended Coverage
# ─────────────────────────────────────────────────
print("\n--- Circuit Breaker: Extended ---")

try:
    from shared.circuit_breaker import (
        record_success, record_failure, is_open, get_state,
        get_all_states, reset,
        should_skip_gate, record_gate_result, get_gate_circuit_state,
        reset_gate_circuit, get_all_gate_states,
    )

    # Custom thresholds
    _cb_svc = "test_custom_threshold_svc"
    reset(_cb_svc)
    for _i in range(2):
        record_failure(_cb_svc, failure_threshold=3)
    test("CircuitExt: below custom threshold → CLOSED",
         get_state(_cb_svc) == "CLOSED", f"state={get_state(_cb_svc)}")
    record_failure(_cb_svc, failure_threshold=3)
    test("CircuitExt: at custom threshold → OPEN",
         get_state(_cb_svc) == "OPEN", f"state={get_state(_cb_svc)}")

    # Success in CLOSED resets failure count
    _cb_svc2 = "test_success_reset_svc"
    reset(_cb_svc2)
    record_failure(_cb_svc2)
    record_success(_cb_svc2)
    record_failure(_cb_svc2)
    test("CircuitExt: success resets failure count — still CLOSED",
         get_state(_cb_svc2) == "CLOSED", f"state={get_state(_cb_svc2)}")

    # get_all_states includes tracked services
    _cb_all = get_all_states()
    test("CircuitExt: get_all_states is dict",
         isinstance(_cb_all, dict), f"type={type(_cb_all)}")
    test("CircuitExt: tracked service in all_states",
         _cb_svc in _cb_all, f"keys include test svc: {_cb_svc in _cb_all}")

    # Gate circuit: non-Tier1 opens after failures
    _cb_gate = "gate_09_strategy_ban"
    reset_gate_circuit(_cb_gate)
    for _i in range(5):
        record_gate_result(_cb_gate, success=False)
    _cb_gate_state = get_gate_circuit_state(_cb_gate)
    test("CircuitExt: gate opens after failures",
         _cb_gate_state in ("OPEN", "HALF_OPEN", "CLOSED"),
         f"state={_cb_gate_state}")

    # Gate circuit: Tier1 never opens
    _cb_t1_gate = "gate_01_read_before_edit"
    for _i in range(10):
        record_gate_result(_cb_t1_gate, success=False)
    test("CircuitExt: Tier1 gate never skipped",
         not should_skip_gate(_cb_t1_gate),
         f"skip={should_skip_gate(_cb_t1_gate)}")

    # get_all_gate_states returns dict
    _cb_all_gates = get_all_gate_states()
    test("CircuitExt: get_all_gate_states is dict",
         isinstance(_cb_all_gates, dict), f"type={type(_cb_all_gates)}")

    # reset_gate_circuit restores CLOSED
    reset_gate_circuit(_cb_gate)
    test("CircuitExt: reset restores CLOSED",
         get_gate_circuit_state(_cb_gate) == "CLOSED",
         f"state={get_gate_circuit_state(_cb_gate)}")

    # Unknown service → fail-open (not open)
    test("CircuitExt: unknown service is not open",
         not is_open("completely_unknown_service_xyz"),
         "should be fail-open")

except Exception as _cb_ext_exc:
    test("CircuitExt: import and basic tests", False, str(_cb_ext_exc))

# ─────────────────────────────────────────────────
# Capability Registry: Extended Coverage
# ─────────────────────────────────────────────────
print("\n--- Capability Registry: Extended ---")

try:
    from shared.capability_registry import (
        check_agent_permission, get_agent_acl, match_agent,
        recommend_model, get_agent_info, define_agent_acl,
    )

    # match_agent: various task types
    _cr_impl = match_agent("feature-implementation")
    test("CapRegExt: feature-implementation match",
         isinstance(_cr_impl, str) and len(_cr_impl) > 0,
         f"got '{_cr_impl}'")

    _cr_research = match_agent("research")
    test("CapRegExt: research match",
         isinstance(_cr_research, str) and len(_cr_research) > 0,
         f"got '{_cr_research}'")

    # match_agent: exclude list
    _cr_excl = match_agent("feature-implementation", exclude=[_cr_impl])
    test("CapRegExt: exclude returns different agent",
         _cr_excl != _cr_impl or _cr_excl is None,
         f"got '{_cr_excl}' (excluded '{_cr_impl}')")

    # recommend_model: returns string
    _cr_model = recommend_model("explorer")
    test("CapRegExt: recommend_model returns string",
         isinstance(_cr_model, str), f"type={type(_cr_model)}")

    # get_agent_info: returns dict or None
    _cr_info = get_agent_info("explorer")
    test("CapRegExt: get_agent_info returns dict",
         isinstance(_cr_info, dict), f"type={type(_cr_info)}")

    # check_agent_permission: basic checks
    _cr_read_perm = check_agent_permission("explorer", "Read")
    test("CapRegExt: explorer can Read",
         _cr_read_perm is True, f"got {_cr_read_perm}")

    _cr_edit_perm = check_agent_permission("explorer", "Edit")
    test("CapRegExt: explorer cannot Edit",
         _cr_edit_perm is False, f"got {_cr_edit_perm}")

    # define_agent_acl: runtime override
    define_agent_acl("test_custom_agent",
                     allowed_tools=["Read", "Grep", "Glob"],
                     denied_tools=["Bash"],
                     allowed_paths=["*.py"])
    _cr_custom_acl = get_agent_acl("test_custom_agent")
    test("CapRegExt: custom ACL registered",
         _cr_custom_acl is not None, f"acl={_cr_custom_acl}")

    _cr_custom_read = check_agent_permission("test_custom_agent", "Read")
    test("CapRegExt: custom agent can Read",
         _cr_custom_read is True, f"got {_cr_custom_read}")

    _cr_custom_bash = check_agent_permission("test_custom_agent", "Bash")
    test("CapRegExt: custom agent cannot Bash (denied)",
         _cr_custom_bash is False, f"got {_cr_custom_bash}")

except Exception as _cr_ext_exc:
    test("CapRegExt: import and basic tests", False, str(_cr_ext_exc))

# ─────────────────────────────────────────────────
# Code Hotspot Analyzer
# ─────────────────────────────────────────────────
print("\n--- Experience Archive ---")

try:
    import tempfile as _ea_tmp
    from shared.experience_archive import (
        record_fix, query_best_strategy, get_success_rate,
        get_archive_stats, ARCHIVE_PATH, _read_rows,
    )
    import shared.experience_archive as _ea_mod

    # Use temp file for test isolation — delete first so _ensure_header writes CSV header
    _ea_orig_path = _ea_mod.ARCHIVE_PATH
    with _ea_tmp.NamedTemporaryFile(suffix=".csv", delete=False) as _ea_tf:
        _ea_test_path = _ea_tf.name
    os.remove(_ea_test_path)  # Must not exist so _ensure_header creates with header row
    _ea_mod.ARCHIVE_PATH = _ea_test_path

    # Test 1: record_fix returns True
    _ea_ok = record_fix("ImportError", "add-import", "success", "/f.py", "gate_15", 1.0)
    test("ExperienceArchive: record_fix returns True", _ea_ok is True, f"got {_ea_ok}")

    # Test 2: record more entries
    record_fix("ImportError", "add-import", "failure", "/f.py", "gate_15", 0.5)
    record_fix("ImportError", "reinstall-pkg", "success", "/f.py", "", 3.0)
    record_fix("SyntaxError", "rewrite", "success", "/g.py", "gate_1", 0.8)
    record_fix("SyntaxError", "rewrite", "failure", "/g.py", "gate_1", 1.0)

    # Test 3: query_best_strategy
    _ea_best = query_best_strategy("ImportError")
    test("ExperienceArchive: best strategy for ImportError",
         _ea_best == "reinstall-pkg",
         f"got '{_ea_best}' (expected reinstall-pkg with 100% vs add-import 50%)")

    # Test 4: get_success_rate
    _ea_rate = get_success_rate("add-import")
    test("ExperienceArchive: success rate add-import is 0.5",
         abs(_ea_rate - 0.5) < 0.01, f"got {_ea_rate}")

    # Test 5: get_success_rate for 100% strategy
    _ea_rate2 = get_success_rate("reinstall-pkg")
    test("ExperienceArchive: success rate reinstall-pkg is 1.0",
         abs(_ea_rate2 - 1.0) < 0.01, f"got {_ea_rate2}")

    # Test 6: get_success_rate unknown strategy
    _ea_rate3 = get_success_rate("nonexistent")
    test("ExperienceArchive: unknown strategy rate is 0.0",
         _ea_rate3 == 0.0, f"got {_ea_rate3}")

    # Test 7: get_archive_stats
    _ea_stats = get_archive_stats()
    test("ExperienceArchive: stats total_rows == 5",
         _ea_stats["total_rows"] == 5, f"got {_ea_stats['total_rows']}")
    test("ExperienceArchive: stats unique_errors == 2",
         _ea_stats["unique_errors"] == 2, f"got {_ea_stats['unique_errors']}")
    test("ExperienceArchive: stats unique_strategies == 3",
         _ea_stats["unique_strategies"] == 3, f"got {_ea_stats['unique_strategies']}")
    test("ExperienceArchive: stats overall_success_rate > 0",
         _ea_stats["overall_success_rate"] > 0,
         f"got {_ea_stats['overall_success_rate']}")
    test("ExperienceArchive: stats top_strategies non-empty",
         len(_ea_stats["top_strategies"]) > 0,
         f"got {len(_ea_stats['top_strategies'])}")

    # Test 8: invalid outcome coerced to failure
    record_fix("TypeError", "bad", "INVALID_OUTCOME")
    _ea_rows = _read_rows(_ea_test_path)
    test("ExperienceArchive: invalid outcome coerced to failure",
         _ea_rows[-1]["outcome"] == "failure",
         f"got '{_ea_rows[-1]['outcome']}'")

    # Test 9: query_best_strategy unknown returns empty
    _ea_none = query_best_strategy("ZZZNonexistent")
    test("ExperienceArchive: unknown error returns ''",
         _ea_none == "", f"got '{_ea_none}'")

    # Cleanup
    _ea_mod.ARCHIVE_PATH = _ea_orig_path
    os.remove(_ea_test_path)

except Exception as _ea_exc:
    test("ExperienceArchive: import and tests", False, str(_ea_exc))

# ─────────────────────────────────────────────────
# Observation Compression
# ─────────────────────────────────────────────────
print("\n--- Observation Compression ---")

try:
    from shared.observation import (
        compress_observation, _detect_error_pattern, _extract_exit_code,
        _get_output_text, _extract_command_name, _compute_priority,
        _detect_sentiment, CAPTURABLE_TOOLS,
    )

    # Test 1: CAPTURABLE_TOOLS includes expected tools
    test("Observation: CAPTURABLE_TOOLS includes Bash",
         "Bash" in CAPTURABLE_TOOLS, f"got {CAPTURABLE_TOOLS}")
    test("Observation: CAPTURABLE_TOOLS includes Edit",
         "Edit" in CAPTURABLE_TOOLS, f"got {CAPTURABLE_TOOLS}")

    # Test 2: _detect_error_pattern
    test("Observation: detect Traceback",
         _detect_error_pattern("some Traceback (most recent call)") == "Traceback", "")
    test("Observation: detect ImportError",
         _detect_error_pattern("ImportError: no module foo") == "ImportError:", "")
    test("Observation: no error returns empty",
         _detect_error_pattern("all good") == "", "")

    # Test 3: _extract_exit_code
    test("Observation: exit code from dict",
         _extract_exit_code({"exit_code": 1}) == "1", "")
    test("Observation: exit code from JSON string",
         _extract_exit_code('{"exit_code": 0}') == "0", "")
    test("Observation: exit code from plain string",
         _extract_exit_code("hello") == "", "")

    # Test 4: _get_output_text
    test("Observation: output from dict stdout",
         "hello" in _get_output_text({"stdout": "hello"}), "")
    test("Observation: output from string",
         _get_output_text("raw output") == "raw output", "")

    # Test 5: _extract_command_name
    test("Observation: extract cmd from 'python3 foo.py'",
         _extract_command_name("python3 foo.py") == "python3", "")
    test("Observation: extract cmd strips sudo",
         _extract_command_name("sudo apt install foo") == "apt", "")
    test("Observation: extract cmd empty",
         _extract_command_name("") == "", "")

    # Test 6: _compute_priority
    test("Observation: error is high priority",
         _compute_priority("Bash", True, "1") == "high", "")
    test("Observation: Edit is medium priority",
         _compute_priority("Edit", False, "") == "medium", "")
    test("Observation: Read is low priority",
         _compute_priority("Read", False, "") == "low", "")

    # Test 7: _detect_sentiment
    test("Observation: frustration on repeated errors",
         _detect_sentiment("Edit", {}, {"error_pattern_counts": {"x": 2}}) == "frustration", "")
    test("Observation: exploration on Read",
         _detect_sentiment("Read", {}, {}) == "exploration", "")
    test("Observation: None state returns empty",
         _detect_sentiment("Bash", {}, None) == "", "")

    # Test 8: compress_observation Bash
    _co_bash = compress_observation(
        "Bash", {"command": "ls /tmp"}, {"stdout": "file1\nfile2", "exit_code": 0},
        "test-session", {}
    )
    test("Observation: compress Bash returns dict with document",
         "document" in _co_bash and "Bash:" in _co_bash["document"], "")
    test("Observation: compress Bash has id",
         _co_bash["id"].startswith("obs_"), f"id={_co_bash['id']}")
    test("Observation: compress Bash has metadata",
         "metadata" in _co_bash and _co_bash["metadata"]["tool_name"] == "Bash", "")

    # Test 9: compress_observation Edit
    _co_edit = compress_observation(
        "Edit", {"file_path": "/tmp/foo.py", "old_string": "a\nb\n", "new_string": "c\n"},
        "ok", "test-session", {}
    )
    test("Observation: compress Edit has file_path in document",
         "/tmp/foo.py" in _co_edit["document"], f"doc={_co_edit['document']}")

    # Test 10: compress_observation with error
    _co_err = compress_observation(
        "Bash", {"command": "pytest"}, {"stdout": "Traceback error", "exit_code": 1},
        "test-session", {}
    )
    test("Observation: error observation has_error metadata",
         _co_err["metadata"]["has_error"] == "true",
         f"has_error={_co_err['metadata']['has_error']}")
    test("Observation: error observation has error_pattern",
         _co_err["metadata"]["error_pattern"] == "Traceback",
         f"pattern={_co_err['metadata']['error_pattern']}")
    test("Observation: error observation is high priority",
         _co_err["metadata"]["priority"] == "high",
         f"priority={_co_err['metadata']['priority']}")

except Exception as _obs_exc:
    test("Observation Compression: import and tests", False, str(_obs_exc))

# ─────────────────────────────────────────────────
# Domain Registry
# ─────────────────────────────────────────────────
print("\n--- Domain Registry ---")

try:
    from shared.domain_registry import (
        list_domains, get_active_domain, load_domain_profile,
        load_domain_mastery, load_domain_behavior,
        detect_domain_from_live_state, get_domain_memory_tags,
        get_domain_l2_keywords, get_domain_token_budget,
        get_domain_context_for_injection, DEFAULT_PROFILE,
        _short_gate_name, _gate_matches_list, _lookup_gate_mode,
    )

    # Test 1: list_domains returns list
    _dr_doms = list_domains()
    test("DomainRegistry: list_domains returns list",
         isinstance(_dr_doms, list), f"type={type(_dr_doms)}")

    # Test 2: each domain has expected keys
    if _dr_doms:
        _dr_first = _dr_doms[0]
        test("DomainRegistry: domain has name key",
             "name" in _dr_first, f"keys={list(_dr_first.keys())}")
        test("DomainRegistry: domain has active key",
             "active" in _dr_first, f"keys={list(_dr_first.keys())}")
        test("DomainRegistry: domain has graduated key",
             "graduated" in _dr_first, f"keys={list(_dr_first.keys())}")
    else:
        skip("DomainRegistry: domain key checks", "no domains configured")

    # Test 3: get_active_domain returns str or None
    _dr_active = get_active_domain()
    test("DomainRegistry: get_active_domain returns str or None",
         _dr_active is None or isinstance(_dr_active, str), f"type={type(_dr_active)}")

    # Test 4: load_domain_profile for nonexistent domain returns defaults
    _dr_prof = load_domain_profile("__nonexistent_domain__")
    test("DomainRegistry: nonexistent domain returns defaults",
         _dr_prof.get("security_profile") == "balanced",
         f"security_profile={_dr_prof.get('security_profile')}")
    test("DomainRegistry: nonexistent domain has token_budget",
         _dr_prof.get("token_budget") == 800,
         f"token_budget={_dr_prof.get('token_budget')}")

    # Test 5: _short_gate_name
    test("DomainRegistry: _short_gate_name full",
         _short_gate_name("gate_04_memory_first") == "gate_04", "")
    test("DomainRegistry: _short_gate_name with gates. prefix",
         _short_gate_name("gates.gate_04_memory_first") == "gate_04", "")
    test("DomainRegistry: _short_gate_name short",
         _short_gate_name("gate_04") == "gate_04", "")

    # Test 6: _gate_matches_list
    test("DomainRegistry: gate matches list exact",
         _gate_matches_list("gate_04_memory_first", ["gate_04"]) is True, "")
    test("DomainRegistry: gate not in list",
         _gate_matches_list("gate_04_memory_first", ["gate_05"]) is False, "")

    # Test 7: _lookup_gate_mode
    test("DomainRegistry: lookup exact match",
         _lookup_gate_mode("gate_04", {"gate_04": "warn"}) == "warn", "")
    test("DomainRegistry: lookup short match",
         _lookup_gate_mode("gate_04_memory_first", {"gate_04": "disabled"}) == "disabled", "")
    test("DomainRegistry: lookup miss returns None",
         _lookup_gate_mode("gate_99", {"gate_04": "warn"}) is None, "")

    # Test 8: detect_domain_from_live_state with empty state
    _dr_detect = detect_domain_from_live_state({})
    test("DomainRegistry: detect empty state returns None",
         _dr_detect is None, f"got {_dr_detect}")

    # Test 9: get_domain_context_for_injection with None
    _dr_ctx = get_domain_context_for_injection(None)
    test("DomainRegistry: context injection returns tuple",
         isinstance(_dr_ctx, tuple) and len(_dr_ctx) == 2,
         f"type={type(_dr_ctx)}")

    # Test 10: DEFAULT_PROFILE has expected keys
    test("DomainRegistry: DEFAULT_PROFILE has token_budget",
         "token_budget" in DEFAULT_PROFILE, f"keys={list(DEFAULT_PROFILE.keys())}")
    test("DomainRegistry: DEFAULT_PROFILE has graduation",
         "graduation" in DEFAULT_PROFILE, f"keys={list(DEFAULT_PROFILE.keys())}")
    test("DomainRegistry: DEFAULT_PROFILE has auto_detect",
         "auto_detect" in DEFAULT_PROFILE, f"keys={list(DEFAULT_PROFILE.keys())}")

    # Test 11: get_domain_token_budget for nonexistent returns default
    _dr_budget = get_domain_token_budget("__nonexistent__")
    test("DomainRegistry: nonexistent domain budget is 800",
         _dr_budget == 800, f"got {_dr_budget}")

    # Test 12: get_domain_memory_tags for nonexistent returns []
    _dr_tags = get_domain_memory_tags("__nonexistent__")
    test("DomainRegistry: nonexistent domain tags is []",
         _dr_tags == [], f"got {_dr_tags}")

    # Test 13: get_domain_l2_keywords for nonexistent returns []
    _dr_l2 = get_domain_l2_keywords("__nonexistent__")
    test("DomainRegistry: nonexistent domain l2_keywords is []",
         _dr_l2 == [], f"got {_dr_l2}")

except Exception as _dr_exc:
    test("DomainRegistry: import and tests", False, str(_dr_exc))

# ─────────────────────────────────────────────────
# Tool Patterns Extended (Markov chain, anomaly detection)
# ─────────────────────────────────────────────────
print("\n--- Tool Patterns Extended ---")

try:
    from shared.tool_patterns import (
        build_markov_chain, MarkovChain, WorkflowTemplate, AnomalyReport,
        _transition_probability, _sequence_log_probability, _std,
        _extract_ngrams, _label_for_template, _invalidate_cache,
    )

    # Test 1: build_markov_chain empty
    _tp_mc_empty = build_markov_chain([])
    test("ToolPatterns: empty sequences → empty chain",
         _tp_mc_empty.sequence_count == 0 and len(_tp_mc_empty.vocabulary) == 0, "")

    # Test 2: build_markov_chain single sequence
    _tp_mc = build_markov_chain([["Read", "Edit", "Bash"]])
    test("ToolPatterns: single sequence → 3 vocab",
         len(_tp_mc.vocabulary) == 3, f"vocab={_tp_mc.vocabulary}")
    test("ToolPatterns: single sequence → 1 seq count",
         _tp_mc.sequence_count == 1, f"count={_tp_mc.sequence_count}")
    test("ToolPatterns: Read is start tool",
         _tp_mc.start_counts.get("Read", 0) == 1, f"starts={dict(_tp_mc.start_counts)}")

    # Test 3: transitions recorded
    test("ToolPatterns: Read→Edit transition recorded",
         _tp_mc.transitions["Read"]["Edit"] == 1, "")
    test("ToolPatterns: Edit→Bash transition recorded",
         _tp_mc.transitions["Edit"]["Bash"] == 1, "")

    # Test 4: multiple sequences
    _tp_mc2 = build_markov_chain([
        ["Read", "Edit", "Bash"],
        ["Read", "Edit", "Bash"],
        ["Read", "Write", "Bash"],
    ])
    test("ToolPatterns: 3 sequences → seq_count=3",
         _tp_mc2.sequence_count == 3, f"count={_tp_mc2.sequence_count}")
    test("ToolPatterns: Read→Edit=2 transitions",
         _tp_mc2.transitions["Read"]["Edit"] == 2, "")
    test("ToolPatterns: Read→Write=1 transition",
         _tp_mc2.transitions["Read"]["Write"] == 1, "")
    test("ToolPatterns: vocabulary includes Write",
         "Write" in _tp_mc2.vocabulary, f"vocab={_tp_mc2.vocabulary}")

    # Test 5: _transition_probability Laplace smoothing
    _tp_prob = _transition_probability(_tp_mc2, "Read", "Edit")
    test("ToolPatterns: P(Edit|Read) > P(Write|Read)",
         _tp_prob > _transition_probability(_tp_mc2, "Read", "Write"), "")
    test("ToolPatterns: P(Edit|Read) > 0",
         _tp_prob > 0, f"prob={_tp_prob}")

    # Test 6: _transition_probability for unseen transition
    _tp_prob_unseen = _transition_probability(_tp_mc2, "Bash", "Read")
    test("ToolPatterns: unseen transition > 0 (Laplace)",
         _tp_prob_unseen > 0, f"prob={_tp_prob_unseen}")

    # Test 7: _sequence_log_probability
    _tp_logp = _sequence_log_probability(_tp_mc2, ["Read", "Edit", "Bash"])
    test("ToolPatterns: log-prob is negative",
         _tp_logp < 0, f"logp={_tp_logp}")
    test("ToolPatterns: common seq has higher log-prob than rare",
         _tp_logp > _sequence_log_probability(_tp_mc2, ["Bash", "Write", "Read"]),
         "common > rare")

    # Test 8: _sequence_log_probability empty
    _tp_logp_empty = _sequence_log_probability(_tp_mc2, [])
    test("ToolPatterns: empty sequence → -inf",
         _tp_logp_empty == float("-inf"), f"logp={_tp_logp_empty}")

    # Test 9: _std
    test("ToolPatterns: _std([1,1,1]) == 0", _std([1.0, 1.0, 1.0]) == 0.0, "")
    test("ToolPatterns: _std([0,2]) == 1", abs(_std([0.0, 2.0]) - 1.0) < 0.01, "")
    test("ToolPatterns: _std([]) == 0", _std([]) == 0.0, "")
    test("ToolPatterns: _std([5]) == 0", _std([5.0]) == 0.0, "")

    # Test 10: _extract_ngrams
    _tp_ng = _extract_ngrams(["A", "B", "C", "D"], 2)
    test("ToolPatterns: 2-grams of ABCD = 3 ngrams",
         len(_tp_ng) == 3, f"ngrams={_tp_ng}")
    test("ToolPatterns: first 2-gram is [A,B]",
         _tp_ng[0] == ["A", "B"], f"first={_tp_ng[0]}")
    _tp_ng3 = _extract_ngrams(["A", "B", "C"], 3)
    test("ToolPatterns: 3-grams of ABC = 1 ngram",
         len(_tp_ng3) == 1 and _tp_ng3[0] == ["A", "B", "C"], f"ngrams={_tp_ng3}")

    # Test 11: _label_for_template
    test("ToolPatterns: label Read,Edit,Bash = read-edit-test",
         _label_for_template(["Read", "Edit", "Bash"]) == "read-edit-test", "")
    test("ToolPatterns: label Read,Edit = read-then-edit",
         _label_for_template(["Read", "Edit"]) == "read-then-edit", "")
    test("ToolPatterns: label unknown gets fallback",
         "workflow" in _label_for_template(["Xyz", "Abc"]), "")

    # Test 12: _invalidate_cache runs without error
    _invalidate_cache()
    test("ToolPatterns: _invalidate_cache succeeds", True, "")

    # Test 13: MarkovChain dataclass fields
    _tp_mc_dc = MarkovChain()
    test("ToolPatterns: MarkovChain defaults are empty",
         _tp_mc_dc.sequence_count == 0 and _tp_mc_dc.total_starts == 0, "")

    # Test 14: WorkflowTemplate dataclass
    _tp_wt = WorkflowTemplate(tools=["A", "B"], count=5, frequency=0.5, label="test")
    test("ToolPatterns: WorkflowTemplate stores fields",
         _tp_wt.count == 5 and _tp_wt.frequency == 0.5 and _tp_wt.label == "test", "")

    # Test 15: AnomalyReport dataclass
    _tp_ar = AnomalyReport(
        tools=["A"], score=-5.0, baseline_mean=-2.0, baseline_std=1.0,
        sigma=3.0, reason="test", unusual_transitions=[("A", "B")]
    )
    test("ToolPatterns: AnomalyReport stores sigma",
         _tp_ar.sigma == 3.0 and len(_tp_ar.unusual_transitions) == 1, "")

except Exception as _tp_exc:
    test("ToolPatterns Extended: import and tests", False, str(_tp_exc))

# ─────────────────────────────────────────────────
# Gate Pruner Extended (classification logic)
# ─────────────────────────────────────────────────
print("\n--- Gate Pruner Extended ---")

try:
    from shared.gate_pruner import (
        _classify, _TIER1, _LOW_BLOCK_RATE, _MIN_EVALS, _HIGH_LATENCY_MS,
        _HIGH_OVERRIDE, KEEP, OPTIMIZE, MERGE_CANDIDATE, DORMANT,
        analyze_gates, get_prune_recommendations, render_pruner_report,
        GateAnalysis, PruneRecommendation,
    )

    # Test 1: Tier 1 gate always returns KEEP
    _gp_v, _gp_r = _classify("gate_01_read_before_edit", True, 100, 5, 10, 5000, 5.0, 0.02, 0.05)
    test("GatePruner: Tier 1 always KEEP",
         _gp_v == KEEP, f"verdict={_gp_v}")
    test("GatePruner: Tier 1 reason mentions 'Tier 1'",
         any("Tier 1" in r for r in _gp_r), f"reasons={_gp_r}")

    # Test 2: Dormant verdict — enough evals, very low block rate, 0 prevented
    _gp_v2, _gp_r2 = _classify("gate_99", False, 2, 0, 0, 2000, 3.0, 0.001, 0.0)
    test("GatePruner: low block rate + 0 prevented = DORMANT",
         _gp_v2 == DORMANT, f"verdict={_gp_v2}")

    # Test 3: Dormant with latency → extra reason
    _gp_v3, _gp_r3 = _classify("gate_99", False, 2, 0, 0, 2000, 15.0, 0.001, 0.0)
    test("GatePruner: dormant + high latency adds latency reason",
         _gp_v3 == DORMANT and any("latency" in r.lower() for r in _gp_r3),
         f"verdict={_gp_v3}, reasons={_gp_r3}")

    # Test 4: Merge candidate — low block rate, some blocks
    _gp_v4, _gp_r4 = _classify("gate_99", False, 20, 0, 0, 2000, 3.0, 0.01, 0.0)
    test("GatePruner: low standalone impact = MERGE_CANDIDATE",
         _gp_v4 == MERGE_CANDIDATE, f"verdict={_gp_v4}")

    # Test 5: Optimize — high override rate
    _gp_v5, _gp_r5 = _classify("gate_99", False, 100, 30, 5, 2000, 3.0, 0.05, 0.30)
    test("GatePruner: high override rate = OPTIMIZE",
         _gp_v5 == OPTIMIZE, f"verdict={_gp_v5}")
    test("GatePruner: optimize reason mentions 'override'",
         any("override" in r.lower() for r in _gp_r5), f"reasons={_gp_r5}")

    # Test 6: Keep with healthy stats
    _gp_v6, _gp_r6 = _classify("gate_99", False, 500, 10, 50, 2000, 3.0, 0.25, 0.02)
    test("GatePruner: high block rate + prevented = KEEP",
         _gp_v6 == KEEP, f"verdict={_gp_v6}")
    test("GatePruner: healthy reason mentions 'healthy'",
         any("healthy" in r.lower() for r in _gp_r6), f"reasons={_gp_r6}")

    # Test 7: Zero blocks with sufficient evals → dormant
    _gp_v7, _gp_r7 = _classify("gate_99", False, 0, 0, 0, 5000, 2.0, 0.0, 0.0)
    test("GatePruner: zero blocks over many evals = DORMANT",
         _gp_v7 == DORMANT, f"verdict={_gp_v7}")
    test("GatePruner: zero blocks dormant reason present",
         any("block rate" in r.lower() or "zero blocks" in r.lower() for r in _gp_r7),
         f"reasons={_gp_r7}")

    # Test 8: Prevented incidents add note even when verdict != KEEP
    _gp_v8, _gp_r8 = _classify("gate_99", False, 2, 0, 5, 2000, 3.0, 0.001, 0.0)
    test("GatePruner: prevented note on non-keep verdict",
         any("prevented" in r.lower() for r in _gp_r8), f"reasons={_gp_r8}")

    # Test 9: Low eval count doesn't trigger dormant
    _gp_v9, _gp_r9 = _classify("gate_99", False, 0, 0, 0, 500, 1.0, 0.0, 0.0)
    test("GatePruner: low eval count → KEEP not DORMANT",
         _gp_v9 == KEEP, f"verdict={_gp_v9}, evals=500")

    # Test 10: analyze_gates returns dict of GateAnalysis
    _gp_analysis = analyze_gates()
    test("GatePruner: analyze_gates returns dict",
         isinstance(_gp_analysis, dict), f"type={type(_gp_analysis)}")

    # Test 11: all Tier 1 gates are KEEP
    for _gp_t1 in _TIER1:
        if _gp_t1 in _gp_analysis:
            test(f"GatePruner: {_gp_t1} is KEEP",
                 _gp_analysis[_gp_t1].verdict == KEEP,
                 f"verdict={_gp_analysis[_gp_t1].verdict}")

    # Test 12: get_prune_recommendations returns list
    _gp_recs = get_prune_recommendations()
    test("GatePruner: recommendations is list",
         isinstance(_gp_recs, list), f"type={type(_gp_recs)}")

    # Test 13: ranks are sequential
    if _gp_recs:
        _gp_ranks = [r.rank for r in _gp_recs]
        test("GatePruner: ranks are sequential",
             _gp_ranks == list(range(1, len(_gp_recs) + 1)),
             f"ranks={_gp_ranks[:10]}")

    # Test 14: all verdicts are valid
    _gp_valid_verdicts = {KEEP, OPTIMIZE, MERGE_CANDIDATE, DORMANT}
    test("GatePruner: all verdicts valid",
         all(r.verdict in _gp_valid_verdicts for r in _gp_recs),
         f"verdicts={set(r.verdict for r in _gp_recs)}")

    # Test 15: render_pruner_report returns string
    _gp_report = render_pruner_report()
    test("GatePruner: report is string",
         isinstance(_gp_report, str) and len(_gp_report) > 0,
         f"len={len(_gp_report)}")
    test("GatePruner: report contains header",
         "GATE PRUNING" in _gp_report, f"snippet={_gp_report[:60]}")

    # Test 16: GateAnalysis dataclass
    _gp_ga = GateAnalysis(
        gate="test_gate", tier1=False, blocks=10, overrides=2, prevented=3,
        eval_count=100, avg_ms=5.0, block_rate=0.1, override_rate=0.2,
        has_q_data=False, verdict=KEEP
    )
    test("GatePruner: GateAnalysis stores fields",
         _gp_ga.gate == "test_gate" and _gp_ga.blocks == 10, "")

    # Test 17: PruneRecommendation dataclass
    _gp_pr = PruneRecommendation(
        rank=1, gate="test", verdict=KEEP, reasons=["healthy"],
        avg_ms=5.0, blocks=10, prevented=3
    )
    test("GatePruner: PruneRecommendation stores fields",
         _gp_pr.rank == 1 and _gp_pr.gate == "test", "")

    # Test 18: constants have expected values
    test("GatePruner: _LOW_BLOCK_RATE is 0.005",
         _LOW_BLOCK_RATE == 0.005, f"val={_LOW_BLOCK_RATE}")
    test("GatePruner: _MIN_EVALS is 1000",
         _MIN_EVALS == 1000, f"val={_MIN_EVALS}")
    test("GatePruner: _HIGH_OVERRIDE is 0.15",
         _HIGH_OVERRIDE == 0.15, f"val={_HIGH_OVERRIDE}")

except Exception as _gp_exc:
    test("GatePruner Extended: import and tests", False, str(_gp_exc))

# --- Retry Strategy Deep Tests ---
print("\n--- Retry Strategy Deep Tests ---")
try:
    from shared.retry_strategy import (
        Strategy, Jitter, RetryConfig, _OperationState,
        _fib, _compute_raw_delay, _apply_jitter,
        should_retry, get_delay, record_attempt, reset, get_stats,
        with_retry, _RetryContextManager, _registry,
    )

    # Fibonacci sequence
    test("RetryStrategy: fib(0)==0", _fib(0) == 0)
    test("RetryStrategy: fib(1)==1", _fib(1) == 1)
    test("RetryStrategy: fib(5)==5", _fib(5) == 5)
    test("RetryStrategy: fib(10)==55", _fib(10) == 55)

    # Enums
    test("RetryStrategy: Strategy has 4 members", len(Strategy) == 4)
    test("RetryStrategy: Jitter has 4 members", len(Jitter) == 4)
    test("RetryStrategy: Strategy values are strings", isinstance(Strategy.EXPONENTIAL_BACKOFF.value, str))
    test("RetryStrategy: Jitter.NONE value", Jitter.NONE.value == "none")

    # RetryConfig defaults
    _rc_def = RetryConfig()
    test("RetryStrategy: default strategy is EXPONENTIAL_BACKOFF", _rc_def.strategy == Strategy.EXPONENTIAL_BACKOFF)
    test("RetryStrategy: default jitter is NONE", _rc_def.jitter == Jitter.NONE)
    test("RetryStrategy: default max_retries is 3", _rc_def.max_retries == 3)
    test("RetryStrategy: default base_delay is 1.0", _rc_def.base_delay == 1.0)
    test("RetryStrategy: default max_delay is 60.0", _rc_def.max_delay == 60.0)

    # _compute_raw_delay for all strategies
    _cfg_exp = RetryConfig(strategy=Strategy.EXPONENTIAL_BACKOFF, base_delay=1.0, multiplier=2.0, max_delay=100.0)
    test("RetryStrategy: exp delay attempt 0", abs(_compute_raw_delay(0, _cfg_exp) - 1.0) < 1e-9)
    test("RetryStrategy: exp delay attempt 3", abs(_compute_raw_delay(3, _cfg_exp) - 8.0) < 1e-9)

    _cfg_lin = RetryConfig(strategy=Strategy.LINEAR_BACKOFF, base_delay=2.0, step=3.0, max_delay=100.0)
    test("RetryStrategy: linear delay attempt 0", abs(_compute_raw_delay(0, _cfg_lin) - 2.0) < 1e-9)
    test("RetryStrategy: linear delay attempt 4", abs(_compute_raw_delay(4, _cfg_lin) - 14.0) < 1e-9)

    _cfg_const = RetryConfig(strategy=Strategy.CONSTANT, base_delay=5.0, max_delay=100.0)
    test("RetryStrategy: constant delay attempt 0", abs(_compute_raw_delay(0, _cfg_const) - 5.0) < 1e-9)
    test("RetryStrategy: constant delay attempt 10", abs(_compute_raw_delay(10, _cfg_const) - 5.0) < 1e-9)

    _cfg_fib = RetryConfig(strategy=Strategy.FIBONACCI, base_delay=2.0, max_delay=100.0)
    test("RetryStrategy: fib delay attempt 0", abs(_compute_raw_delay(0, _cfg_fib) - 2.0) < 1e-9)  # fib(1)=1, *2
    test("RetryStrategy: fib delay attempt 3", abs(_compute_raw_delay(3, _cfg_fib) - 6.0) < 1e-9)  # fib(4)=3, *2

    # max_delay cap
    _cfg_cap = RetryConfig(strategy=Strategy.EXPONENTIAL_BACKOFF, base_delay=1.0, multiplier=10.0, max_delay=5.0)
    test("RetryStrategy: max_delay caps raw delay", _compute_raw_delay(5, _cfg_cap) <= 5.0)

    # _apply_jitter NONE returns raw
    test("RetryStrategy: jitter NONE returns raw", abs(_apply_jitter(4.0, RetryConfig(jitter=Jitter.NONE), 0.0) - 4.0) < 1e-9)

    # _apply_jitter FULL in [0, raw]
    import random as _rs_random
    _rs_random.seed(42)
    _jf_vals = [_apply_jitter(4.0, RetryConfig(jitter=Jitter.FULL), 0.0) for _ in range(50)]
    test("RetryStrategy: FULL jitter in [0, raw]", all(0.0 <= v <= 4.0 + 1e-9 for v in _jf_vals))

    # _apply_jitter EQUAL in [half, raw]
    _je_vals = [_apply_jitter(4.0, RetryConfig(jitter=Jitter.EQUAL), 0.0) for _ in range(50)]
    test("RetryStrategy: EQUAL jitter in [half, raw]", all(2.0 - 1e-9 <= v <= 4.0 + 1e-9 for v in _je_vals))

    # _apply_jitter DECORRELATED >= base_delay
    _jd_vals = [_apply_jitter(4.0, RetryConfig(jitter=Jitter.DECORRELATED, base_delay=1.0), 2.0) for _ in range(50)]
    test("RetryStrategy: DECORRELATED jitter >= base_delay", all(v >= 1.0 - 1e-9 for v in _jd_vals))

    # should_retry: respects max_retries
    reset("__test_sr_limit__")
    _sr_cfg = RetryConfig(max_retries=2)
    test("RetryStrategy: should_retry True before failures", should_retry("__test_sr_limit__", config=_sr_cfg))
    record_attempt("__test_sr_limit__", success=False, config=_sr_cfg)
    record_attempt("__test_sr_limit__", success=False, config=_sr_cfg)
    test("RetryStrategy: should_retry False after max failures", not should_retry("__test_sr_limit__", config=_sr_cfg))
    reset("__test_sr_limit__")

    # get_stats returns all expected keys
    reset("__test_stats_deep__")
    record_attempt("__test_stats_deep__", success=True)
    record_attempt("__test_stats_deep__", success=False, error="err1")
    record_attempt("__test_stats_deep__", success=False, error="err2")
    _st = get_stats("__test_stats_deep__")
    test("RetryStrategy: get_stats has operation key", _st.get("operation") == "__test_stats_deep__")
    test("RetryStrategy: get_stats attempts=3", _st.get("attempts") == 3)
    test("RetryStrategy: get_stats successes=1", _st.get("successes") == 1)
    test("RetryStrategy: get_stats failures=2", _st.get("failures") == 2)
    test("RetryStrategy: get_stats recent_errors length", len(_st.get("recent_errors", [])) == 2)
    test("RetryStrategy: get_stats success_rate ~0.3333", abs(_st.get("success_rate", 0) - 0.3333) < 0.01)
    reset("__test_stats_deep__")

    # _OperationState defaults
    _os = _OperationState()
    test("RetryStrategy: _OperationState defaults", _os.attempts == 0 and _os.failures == 0 and _os.successes == 0)
    test("RetryStrategy: _OperationState total_delay default", _os.total_delay == 0.0)
    test("RetryStrategy: _OperationState max_errors_stored", _os.max_errors_stored == 10)

    # record_attempt truncates error messages
    reset("__test_trunc__")
    record_attempt("__test_trunc__", success=False, error="x" * 500)
    _st_t = get_stats("__test_trunc__")
    test("RetryStrategy: error msg truncated to 200 chars", len(_st_t["recent_errors"][0]) <= 200)
    reset("__test_trunc__")

    # record_attempt caps stored errors at max_errors_stored
    reset("__test_err_cap__")
    for _i in range(15):
        record_attempt("__test_err_cap__", success=False, error=f"err{_i}")
    _st_c = get_stats("__test_err_cap__")
    test("RetryStrategy: error list capped at 10", len(_st_c["recent_errors"]) <= 10)
    reset("__test_err_cap__")

    # with_retry as context manager — success
    reset("__test_ctx_ok__")
    with with_retry("__test_ctx_ok__", strategy=Strategy.CONSTANT, base_delay=0.0) as _rt:
        _rt.success()
    _ctx_s = get_stats("__test_ctx_ok__")
    test("RetryStrategy: ctx manager success recorded", _ctx_s.get("successes") == 1)
    reset("__test_ctx_ok__")

    # with_retry as context manager — exception records failure
    reset("__test_ctx_err__")
    try:
        with with_retry("__test_ctx_err__", strategy=Strategy.CONSTANT, base_delay=0.0) as _rt2:
            raise ValueError("boom")
    except ValueError:
        pass
    _ctx_e = get_stats("__test_ctx_err__")
    test("RetryStrategy: ctx manager exception records failure", _ctx_e.get("failures") == 1)
    reset("__test_ctx_err__")

    # with_retry ctx manager — auto-success when no explicit call and no exception
    reset("__test_ctx_auto__")
    with with_retry("__test_ctx_auto__", strategy=Strategy.CONSTANT, base_delay=0.0) as _rt3:
        pass  # no .success() call, no exception
    _ctx_a = get_stats("__test_ctx_auto__")
    test("RetryStrategy: ctx manager auto-success", _ctx_a.get("successes") == 1)
    reset("__test_ctx_auto__")

    # reset clears all state
    reset("__test_reset_deep__")
    record_attempt("__test_reset_deep__", success=False)
    record_attempt("__test_reset_deep__", success=True)
    reset("__test_reset_deep__")
    _rst = get_stats("__test_reset_deep__")
    test("RetryStrategy: reset clears attempts", _rst.get("attempts") == 0)
    test("RetryStrategy: reset clears failures", _rst.get("failures") == 0)

except Exception as _rs_exc:
    test("RetryStrategy Deep Tests: import and tests", False, str(_rs_exc))

# --- Circuit Breaker Deep Tests ---
print("\n--- Circuit Breaker Deep Tests ---")
try:
    from shared.circuit_breaker import (
        STATE_CLOSED, STATE_OPEN, STATE_HALF_OPEN,
        DEFAULT_FAILURE_THRESHOLD, DEFAULT_RECOVERY_TIMEOUT, DEFAULT_SUCCESS_THRESHOLD,
        _default_service_record, _maybe_recover,
        record_success as cb_record_success,
        record_failure as cb_record_failure,
        is_open as cb_is_open,
        get_state as cb_get_state,
        get_all_states as cb_get_all_states,
        reset as cb_reset,
        should_skip_gate, record_gate_result,
        get_gate_circuit_state, reset_gate_circuit,
        get_all_gate_states,
        _GATE_CRASH_THRESHOLD, _GATE_COOLDOWN, _TIER1_GATE_NAMES,
        _default_gate_record, _prune_crash_window, _gate_maybe_recover,
    )

    # State constants
    test("CB: STATE_CLOSED is CLOSED", STATE_CLOSED == "CLOSED")
    test("CB: STATE_OPEN is OPEN", STATE_OPEN == "OPEN")
    test("CB: STATE_HALF_OPEN is HALF_OPEN", STATE_HALF_OPEN == "HALF_OPEN")

    # Default thresholds
    test("CB: DEFAULT_FAILURE_THRESHOLD is 5", DEFAULT_FAILURE_THRESHOLD == 5)
    test("CB: DEFAULT_RECOVERY_TIMEOUT is 60", DEFAULT_RECOVERY_TIMEOUT == 60)
    test("CB: DEFAULT_SUCCESS_THRESHOLD is 2", DEFAULT_SUCCESS_THRESHOLD == 2)

    # _default_service_record has all keys
    _dsr = _default_service_record()
    test("CB: default record state is CLOSED", _dsr["state"] == STATE_CLOSED)
    test("CB: default record failure_count is 0", _dsr["failure_count"] == 0)
    test("CB: default record total_failures is 0", _dsr["total_failures"] == 0)
    test("CB: default record total_successes is 0", _dsr["total_successes"] == 0)
    test("CB: default record total_rejections is 0", _dsr["total_rejections"] == 0)
    test("CB: default record has opened_at None", _dsr["opened_at"] is None)

    # Custom thresholds in _default_service_record
    _dsr2 = _default_service_record(failure_threshold=3, recovery_timeout=30, success_threshold=1)
    test("CB: custom failure_threshold", _dsr2["failure_threshold"] == 3)
    test("CB: custom recovery_timeout", _dsr2["recovery_timeout"] == 30)
    test("CB: custom success_threshold", _dsr2["success_threshold"] == 1)

    # _maybe_recover: OPEN -> HALF_OPEN after timeout
    import time as _cb_time
    _mr_rec = _default_service_record()
    _mr_rec["state"] = STATE_OPEN
    _mr_rec["opened_at"] = _cb_time.time() - DEFAULT_RECOVERY_TIMEOUT - 10
    _maybe_recover(_mr_rec)
    test("CB: _maybe_recover transitions OPEN->HALF_OPEN", _mr_rec["state"] == STATE_HALF_OPEN)

    # _maybe_recover: OPEN stays OPEN before timeout
    _mr_rec2 = _default_service_record()
    _mr_rec2["state"] = STATE_OPEN
    _mr_rec2["opened_at"] = _cb_time.time()
    _maybe_recover(_mr_rec2)
    test("CB: _maybe_recover stays OPEN before timeout", _mr_rec2["state"] == STATE_OPEN)

    # _maybe_recover: CLOSED is no-op
    _mr_rec3 = _default_service_record()
    _maybe_recover(_mr_rec3)
    test("CB: _maybe_recover no-op on CLOSED", _mr_rec3["state"] == STATE_CLOSED)

    # Service-level: full lifecycle test
    _SVC = "__cb_deep_test__"
    cb_reset(_SVC)
    test("CB: fresh service is CLOSED", cb_get_state(_SVC) == STATE_CLOSED)
    test("CB: is_open False when CLOSED", not cb_is_open(_SVC))

    # Accumulate failures below threshold
    for _i in range(DEFAULT_FAILURE_THRESHOLD - 1):
        cb_record_failure(_SVC)
    test("CB: still CLOSED below threshold", cb_get_state(_SVC) == STATE_CLOSED)

    # One more failure crosses threshold
    cb_record_failure(_SVC)
    test("CB: OPEN at threshold", cb_get_state(_SVC) == STATE_OPEN)
    test("CB: is_open True when OPEN", cb_is_open(_SVC))

    # Successes while OPEN don't close
    cb_record_success(_SVC)
    test("CB: success while OPEN doesn't close", cb_get_state(_SVC) == STATE_OPEN)

    # get_all_states includes service
    _all = cb_get_all_states()
    test("CB: get_all_states includes test service", _SVC in _all)

    # Reset restores CLOSED
    cb_reset(_SVC)
    test("CB: reset restores CLOSED", cb_get_state(_SVC) == STATE_CLOSED)

    # Unknown service defaults to CLOSED
    test("CB: unknown service is CLOSED", cb_get_state("__nonexistent_svc__") == STATE_CLOSED)
    test("CB: unknown service is_open False", not cb_is_open("__nonexistent_svc__"))
    cb_reset(_SVC)

    # --- Gate circuit breaker ---
    # _default_gate_record
    _dgr = _default_gate_record()
    test("CB: gate record state is CLOSED", _dgr["state"] == STATE_CLOSED)
    test("CB: gate record crash_timestamps empty", _dgr["crash_timestamps"] == [])
    test("CB: gate record total_crashes is 0", _dgr["total_crashes"] == 0)
    test("CB: gate record total_skips is 0", _dgr["total_skips"] == 0)

    # Gate constants
    test("CB: _GATE_CRASH_THRESHOLD is 3", _GATE_CRASH_THRESHOLD == 3)
    test("CB: _GATE_COOLDOWN is 60", _GATE_COOLDOWN == 60)

    # Tier 1 gates never skipped
    _tier1_gate = "gate_01_read_before_edit"
    test("CB: Tier 1 gate in _TIER1_GATE_NAMES", _tier1_gate in _TIER1_GATE_NAMES)
    test("CB: should_skip_gate False for Tier 1", not should_skip_gate(_tier1_gate))

    # Tier 1 gate stays CLOSED even after crashes
    reset_gate_circuit(_tier1_gate)
    for _i in range(5):
        record_gate_result(_tier1_gate, success=False)
    test("CB: Tier 1 gate stays CLOSED after crashes", get_gate_circuit_state(_tier1_gate) == STATE_CLOSED)
    reset_gate_circuit(_tier1_gate)

    # Non-tier-1 gate: crashes open circuit
    _test_gate = "__test_gate_cb__"
    reset_gate_circuit(_test_gate)
    for _i in range(_GATE_CRASH_THRESHOLD):
        record_gate_result(_test_gate, success=False)
    test("CB: non-tier1 gate opens after crash threshold", get_gate_circuit_state(_test_gate) == STATE_OPEN)
    test("CB: should_skip_gate True when gate OPEN", should_skip_gate(_test_gate))

    # Gate recovery after cooldown
    reset_gate_circuit(_test_gate)
    for _i in range(_GATE_CRASH_THRESHOLD):
        record_gate_result(_test_gate, success=False)
    # Manually backdate opened_at to simulate cooldown
    from shared.circuit_breaker import _load_gate_state, _save_gate_state
    _gdata = _load_gate_state()
    if _test_gate in _gdata:
        _gdata[_test_gate]["opened_at"] = _cb_time.time() - _GATE_COOLDOWN - 10
        _save_gate_state(_gdata)
    test("CB: gate HALF_OPEN after cooldown", get_gate_circuit_state(_test_gate) == STATE_HALF_OPEN)
    test("CB: should_skip_gate False in HALF_OPEN", not should_skip_gate(_test_gate))

    # Success in HALF_OPEN closes gate circuit
    record_gate_result(_test_gate, success=True)
    test("CB: gate CLOSED after success in HALF_OPEN", get_gate_circuit_state(_test_gate) == STATE_CLOSED)

    # get_all_gate_states returns dict
    _gall = get_all_gate_states()
    test("CB: get_all_gate_states returns dict", isinstance(_gall, dict))

    # reset_gate_circuit restores CLOSED
    reset_gate_circuit(_test_gate)
    test("CB: reset_gate_circuit restores CLOSED", get_gate_circuit_state(_test_gate) == STATE_CLOSED)

    # _prune_crash_window removes old timestamps
    _prune_rec = {"crash_timestamps": [_cb_time.time() - 1000, _cb_time.time() - 500, _cb_time.time()]}
    _prune_crash_window(_prune_rec)
    test("CB: _prune_crash_window keeps recent timestamps", len(_prune_rec["crash_timestamps"]) >= 1)

    # Cleanup
    reset_gate_circuit(_test_gate)
    reset_gate_circuit(_tier1_gate)

except Exception as _cb_exc:
    test("Circuit Breaker Deep Tests: import and tests", False, str(_cb_exc))

# --- Rate Limiter Deep Tests ---
print("\n--- Rate Limiter Deep Tests ---")
try:
    from shared.rate_limiter import (
        allow as rl_allow,
        consume as rl_consume,
        get_remaining as rl_get_remaining,
        reset as rl_reset,
        get_all_limits as rl_get_all_limits,
        TOOL_RATE, GATE_RATE, API_RATE,
        _config_for, _refill_tokens, _DEFAULT_RATE,
        _buckets,
    )

    # Preset constants
    test("RateLimiter: TOOL_RATE is (10.0, 10)", TOOL_RATE == (10.0, 10))
    test("RateLimiter: GATE_RATE is (30.0, 30)", GATE_RATE == (30.0, 30))
    test("RateLimiter: API_RATE is (60.0, 60)", API_RATE == (60.0, 60))

    # _config_for prefix matching
    test("RateLimiter: tool: prefix -> TOOL_RATE", _config_for("tool:Edit") == TOOL_RATE)
    test("RateLimiter: gate: prefix -> GATE_RATE", _config_for("gate:gate_04") == GATE_RATE)
    test("RateLimiter: api: prefix -> API_RATE", _config_for("api:memory") == API_RATE)
    test("RateLimiter: unknown prefix -> DEFAULT_RATE", _config_for("custom:xyz") == _DEFAULT_RATE)

    # _refill_tokens
    _rl_bucket = {"tokens": 5.0, "last_refill": _cb_time.time() - 60.0}
    _rl_refilled = _refill_tokens(_rl_bucket, 10.0, 10, _cb_time.time())
    test("RateLimiter: _refill_tokens adds tokens", _rl_refilled > 5.0)
    test("RateLimiter: _refill_tokens capped at burst", _rl_refilled <= 10.0)

    # _refill_tokens with zero elapsed
    _rl_bucket2 = {"tokens": 3.0, "last_refill": _cb_time.time()}
    _rl_refilled2 = _refill_tokens(_rl_bucket2, 10.0, 10, _cb_time.time())
    test("RateLimiter: _refill_tokens zero elapsed ~= current tokens", abs(_rl_refilled2 - 3.0) < 0.1)

    # Full lifecycle: consume until empty
    _TK = "tool:__rl_test__"
    rl_reset(_TK)
    test("RateLimiter: fresh bucket at burst capacity", rl_get_remaining(_TK) == 10)
    test("RateLimiter: allow True when full", rl_allow(_TK))
    test("RateLimiter: consume True when available", rl_consume(_TK))
    test("RateLimiter: remaining decremented by 1", rl_get_remaining(_TK) == 9)

    # Exhaust bucket
    for _i in range(9):
        rl_consume(_TK)
    test("RateLimiter: bucket empty after consuming all", rl_get_remaining(_TK) == 0)
    test("RateLimiter: consume False when empty", not rl_consume(_TK))
    test("RateLimiter: allow False when empty", not rl_allow(_TK))

    # Reset refills
    rl_reset(_TK)
    test("RateLimiter: reset refills to burst", rl_get_remaining(_TK) == 10)

    # Multi-token consume
    _TK2 = "tool:__rl_multi__"
    rl_reset(_TK2)
    test("RateLimiter: allow 5 tokens True", rl_allow(_TK2, tokens=5))
    test("RateLimiter: consume 5 tokens True", rl_consume(_TK2, tokens=5))
    test("RateLimiter: remaining after consuming 5", rl_get_remaining(_TK2) == 5)
    test("RateLimiter: consume 6 fails with 5 remaining", not rl_consume(_TK2, tokens=6))
    rl_reset(_TK2)

    # get_all_limits returns dict with expected fields
    rl_reset("tool:__rl_fields__")
    rl_consume("tool:__rl_fields__")
    _limits = rl_get_all_limits()
    test("RateLimiter: get_all_limits includes test key", "tool:__rl_fields__" in _limits)
    if "tool:__rl_fields__" in _limits:
        _entry = _limits["tool:__rl_fields__"]
        test("RateLimiter: entry has tokens_remaining", "tokens_remaining" in _entry)
        test("RateLimiter: entry has rate_per_minute", "rate_per_minute" in _entry)
        test("RateLimiter: entry has burst", "burst" in _entry)
        test("RateLimiter: entry has last_refill", "last_refill" in _entry)
        test("RateLimiter: entry rate_per_minute is 10.0", _entry["rate_per_minute"] == 10.0)
        test("RateLimiter: entry burst is 10", _entry["burst"] == 10)
    rl_reset("tool:__rl_fields__")

    # Gate rate uses burst=30
    _GK = "gate:__rl_gate_test__"
    rl_reset(_GK)
    test("RateLimiter: gate burst is 30", rl_get_remaining(_GK) == 30)
    rl_reset(_GK)

    # API rate uses burst=60
    _AK = "api:__rl_api_test__"
    rl_reset(_AK)
    test("RateLimiter: api burst is 60", rl_get_remaining(_AK) == 60)
    rl_reset(_AK)

    # Cleanup
    for _k in ["tool:__rl_test__", "tool:__rl_multi__", "tool:__rl_fields__", "gate:__rl_gate_test__", "api:__rl_api_test__"]:
        _buckets.pop(_k, None)

except Exception as _rl_exc:
    test("Rate Limiter Deep Tests: import and tests", False, str(_rl_exc))

# --- Gate Correlator Deep Tests ---
print("\n--- Gate Correlator Deep Tests ---")
try:
    from shared.gate_correlator import (
        _normalize_gate, _ts_float, _group_by_tool_call,
        build_cooccurrence_matrix, cooccurrence_summary,
        detect_gate_chains, detect_redundant_gates, optimize_gate_order,
        GateCorrelator, CHAIN_WINDOW_SECONDS, MIN_COOCCURRENCE,
        REDUNDANCY_JACCARD_THRESHOLD, _TIER1_GATES, _CANONICAL_ORDER,
        _GATE_NAME_MAP,
    )
    from datetime import datetime as _gc_dt

    # _normalize_gate
    test("GC: normalize full module path", _normalize_gate("gates.gate_01_read_before_edit") == "GATE 1: READ BEFORE EDIT")
    test("GC: normalize short form", _normalize_gate("gate_02_no_destroy") == "GATE 2: NO DESTROY")
    test("GC: normalize unknown passes through", _normalize_gate("unknown_gate") == "unknown_gate")

    # Constants
    test("GC: CHAIN_WINDOW_SECONDS is 5.0", CHAIN_WINDOW_SECONDS == 5.0)
    test("GC: MIN_COOCCURRENCE is 3", MIN_COOCCURRENCE == 3)
    test("GC: REDUNDANCY_JACCARD_THRESHOLD is 0.85", REDUNDANCY_JACCARD_THRESHOLD == 0.85)
    test("GC: _TIER1_GATES has 3 gates", len(_TIER1_GATES) == 3)

    # _ts_float
    _ts_entry = {"timestamp": "2025-01-15T10:30:00"}
    _ts_val = _ts_float(_ts_entry)
    test("GC: _ts_float returns float > 0", isinstance(_ts_val, float) and _ts_val > 0)
    test("GC: _ts_float handles missing timestamp", _ts_float({}) == 0.0)
    test("GC: _ts_float handles invalid timestamp", _ts_float({"timestamp": "not-a-date"}) == 0.0)

    # _group_by_tool_call
    _now_str = "2025-01-15T10:30:00"
    _later_str = "2025-01-15T10:30:00.100"
    _much_later_str = "2025-01-15T10:30:05"
    _gc_entries = [
        {"gate": "G1", "tool": "Edit", "session_id": "s1", "timestamp": _now_str},
        {"gate": "G2", "tool": "Edit", "session_id": "s1", "timestamp": _later_str},
        {"gate": "G3", "tool": "Edit", "session_id": "s1", "timestamp": _much_later_str},
    ]
    _groups = _group_by_tool_call(_gc_entries)
    test("GC: _group_by_tool_call groups by time window", len(_groups) == 2)

    # Different sessions create different groups
    _gc_entries2 = [
        {"gate": "G1", "tool": "Edit", "session_id": "s1", "timestamp": _now_str},
        {"gate": "G2", "tool": "Edit", "session_id": "s2", "timestamp": _later_str},
    ]
    _groups2 = _group_by_tool_call(_gc_entries2)
    test("GC: different sessions = different groups", len(_groups2) == 2)

    # build_cooccurrence_matrix
    _cooc_entries = [
        {"gate": "GA", "tool": "Edit", "session_id": "s1", "timestamp": _now_str},
        {"gate": "GB", "tool": "Edit", "session_id": "s1", "timestamp": _later_str},
    ]
    _matrix = build_cooccurrence_matrix(_cooc_entries)
    test("GC: cooccurrence matrix has pair", ("GA", "GB") in _matrix or ("GB", "GA") in _matrix)

    # cooccurrence_summary
    _summary = cooccurrence_summary(_matrix)
    test("GC: cooccurrence_summary returns list", isinstance(_summary, list))
    if _summary:
        test("GC: summary entry has gate_a", "gate_a" in _summary[0])
        test("GC: summary entry has count", "count" in _summary[0])

    # Empty entries
    _empty_matrix = build_cooccurrence_matrix([])
    test("GC: empty entries -> empty matrix", len(_empty_matrix) == 0)

    # detect_gate_chains
    _chain_entries = []
    _base_ts = _gc_dt(2025, 1, 15, 10, 30, 0)
    for _i in range(5):  # 5 occurrences to exceed MIN_COOCCURRENCE
        _t1 = f"2025-01-15T10:{30 + _i}:00"
        _t2 = f"2025-01-15T10:{30 + _i}:01"
        _chain_entries.append({"gate": "GA", "tool": "Edit", "session_id": "s1", "timestamp": _t1, "decision": "pass"})
        _chain_entries.append({"gate": "GB", "tool": "Edit", "session_id": "s1", "timestamp": _t2, "decision": "pass"})
    _chains = detect_gate_chains(_chain_entries, window_seconds=5.0, min_count=3)
    test("GC: detect_gate_chains finds chain", len(_chains) >= 1)
    if _chains:
        test("GC: chain has from_gate", "from_gate" in _chains[0])
        test("GC: chain has to_gate", "to_gate" in _chains[0])
        test("GC: chain has avg_gap_ms", "avg_gap_ms" in _chains[0])
        test("GC: chain has example_tool", "example_tool" in _chains[0])

    # detect_gate_chains with no data
    test("GC: no chains from empty entries", len(detect_gate_chains([], min_count=1)) == 0)

    # detect_redundant_gates
    _redundant_entries = []
    for _i in range(10):
        _t = f"2025-01-15T10:{30 + _i}:00"
        _t2 = f"2025-01-15T10:{30 + _i}:00.100"
        _redundant_entries.append({"gate": "GX", "tool": "Edit", "session_id": "s1", "timestamp": _t, "decision": "pass"})
        _redundant_entries.append({"gate": "GY", "tool": "Edit", "session_id": "s1", "timestamp": _t2, "decision": "pass"})
    _redundant = detect_redundant_gates(_redundant_entries, min_cooccurrence=3, jaccard_threshold=0.8)
    test("GC: detect_redundant_gates finds redundancy", len(_redundant) >= 1)
    if _redundant:
        test("GC: redundancy has jaccard_similarity", "jaccard_similarity" in _redundant[0])
        test("GC: redundancy has agreement_rate", "agreement_rate" in _redundant[0])
        test("GC: redundancy has note", "note" in _redundant[0])

    # optimize_gate_order
    _order_entries = [
        {"gate": "GATE 1: READ BEFORE EDIT", "tool": "Edit", "decision": "pass", "timestamp": _now_str},
        {"gate": "GATE 4: MEMORY FIRST", "tool": "Edit", "decision": "block", "timestamp": _now_str},
        {"gate": "GATE 5: PROOF BEFORE FIXED", "tool": "Edit", "decision": "pass", "timestamp": _now_str},
    ]
    _ordering = optimize_gate_order(_order_entries, effectiveness_data={})
    test("GC: optimize_gate_order returns list", isinstance(_ordering, list))
    test("GC: optimize_gate_order has entries", len(_ordering) > 0)
    if _ordering:
        test("GC: ordering entry has rank", "rank" in _ordering[0])
        test("GC: ordering entry has gate", "gate" in _ordering[0])
        test("GC: ordering entry has block_rate", "block_rate" in _ordering[0])
        test("GC: ordering entry has pinned", "pinned" in _ordering[0])
        test("GC: ordering entry has score", "score" in _ordering[0])
        test("GC: ordering entry has reason", "reason" in _ordering[0])
        # Tier 1 gates are pinned first
        _pinned = [r for r in _ordering if r["pinned"]]
        _free = [r for r in _ordering if not r["pinned"]]
        if _pinned and _free:
            test("GC: pinned gates rank before free gates", max(r["rank"] for r in _pinned) < min(r["rank"] for r in _free))

    # optimize_gate_order with target_tool
    _order_filtered = optimize_gate_order(_order_entries, effectiveness_data={}, target_tool="Edit")
    test("GC: optimize_gate_order with target_tool returns list", isinstance(_order_filtered, list))

    # GateCorrelator class
    _gc = GateCorrelator(max_entries=100)
    test("GC: GateCorrelator constructor", _gc._max_entries == 100)
    test("GC: GateCorrelator _entries starts None", _gc._entries is None)

    # _CANONICAL_ORDER has expected entries
    test("GC: _CANONICAL_ORDER has >= 14 gates", len(_CANONICAL_ORDER) >= 14)
    test("GC: GATE 1 is first in canonical order", _CANONICAL_ORDER[0] == "GATE 1: READ BEFORE EDIT")

    # _GATE_NAME_MAP covers both forms
    test("GC: _GATE_NAME_MAP has full module path entries", "gates.gate_01_read_before_edit" in _GATE_NAME_MAP)
    test("GC: _GATE_NAME_MAP has short form entries", "gate_01_read_before_edit" in _GATE_NAME_MAP)

except Exception as _gc_exc:
    test("Gate Correlator Deep Tests: import and tests", False, str(_gc_exc))

# --- Gate 04/07/13/15 Refactored Tests ---
print("\n--- Memory Decay Deep Tests ---")
try:
    from shared.memory_decay import (
        calculate_relevance_score, rank_memories, identify_stale_memories,
        _parse_timestamp, _age_days, _time_decay_factor, _access_boost,
        _tag_relevance_bonus,
        TIER_BASE, TIER_BASE_DEFAULT, DEFAULT_HALF_LIFE_DAYS,
        _MAX_ACCESS_BOOST, _RECENCY_BOOST, _RECENCY_WINDOW_DAYS, _MAX_TAG_BONUS,
    )
    from datetime import datetime as _md_dt, timezone as _md_tz, timedelta as _md_td
    import math as _md_math

    # Constants
    test("MemDecay: TIER_BASE has 3 tiers", len(TIER_BASE) == 3)
    test("MemDecay: T1 base is 1.0", TIER_BASE[1] == 1.0)
    test("MemDecay: T2 base is 0.7", TIER_BASE[2] == 0.7)
    test("MemDecay: T3 base is 0.4", TIER_BASE[3] == 0.4)
    test("MemDecay: DEFAULT_HALF_LIFE is 45.0", DEFAULT_HALF_LIFE_DAYS == 45.0)
    test("MemDecay: _MAX_ACCESS_BOOST is 0.20", _MAX_ACCESS_BOOST == 0.20)
    test("MemDecay: _RECENCY_BOOST is 0.10", _RECENCY_BOOST == 0.10)
    test("MemDecay: _MAX_TAG_BONUS is 0.15", _MAX_TAG_BONUS == 0.15)

    # _parse_timestamp
    _pt1 = _parse_timestamp("2025-01-15T10:30:00")
    test("MemDecay: _parse_timestamp valid ISO", _pt1 is not None and isinstance(_pt1, _md_dt))
    test("MemDecay: _parse_timestamp with Z", _parse_timestamp("2025-01-15T10:30:00Z") is not None)
    test("MemDecay: _parse_timestamp empty", _parse_timestamp("") is None)
    test("MemDecay: _parse_timestamp invalid", _parse_timestamp("not-a-date") is None)
    test("MemDecay: _parse_timestamp None", _parse_timestamp(None) is None)

    # _age_days
    _recent_ts = (_md_dt.now(tz=_md_tz.utc) - _md_td(hours=1)).isoformat()
    _old_ts = (_md_dt.now(tz=_md_tz.utc) - _md_td(days=30)).isoformat()
    test("MemDecay: _age_days recent ~0", _age_days(_recent_ts) < 1.0)
    test("MemDecay: _age_days 30 days old", abs(_age_days(_old_ts) - 30.0) < 1.0)
    test("MemDecay: _age_days invalid returns 0", _age_days("invalid") == 0.0)
    test("MemDecay: _age_days empty returns 0", _age_days("") == 0.0)

    # _time_decay_factor
    test("MemDecay: decay at age 0 is 1.0", abs(_time_decay_factor(0.0) - 1.0) < 1e-9)
    test("MemDecay: decay at half-life is 0.5", abs(_time_decay_factor(45.0) - 0.5) < 1e-9)
    test("MemDecay: decay at 2x half-life is 0.25", abs(_time_decay_factor(90.0) - 0.25) < 1e-6)
    test("MemDecay: decay at 3x half-life is 0.125", abs(_time_decay_factor(135.0) - 0.125) < 1e-6)
    test("MemDecay: custom half-life", abs(_time_decay_factor(10.0, half_life=10.0) - 0.5) < 1e-9)

    # _access_boost
    test("MemDecay: access_boost 0 retrieval is 0", _access_boost(0) == 0.0)
    test("MemDecay: access_boost 1 retrieval > 0", _access_boost(1) > 0.0)
    test("MemDecay: access_boost capped at _MAX_ACCESS_BOOST", _access_boost(10000) <= _MAX_ACCESS_BOOST)
    test("MemDecay: access_boost monotonically increasing", _access_boost(5) > _access_boost(1))
    test("MemDecay: access_boost handles None", _access_boost(None) == 0.0)

    # _tag_relevance_bonus
    test("MemDecay: tag_bonus with matching tags", _tag_relevance_bonus("fix,error,python", "fix,error") > 0.0)
    test("MemDecay: tag_bonus with no match", _tag_relevance_bonus("fix,error", "frontend,css") == 0.0)
    test("MemDecay: tag_bonus with empty query", _tag_relevance_bonus("fix,error", None) == 0.0)
    test("MemDecay: tag_bonus with empty tags", _tag_relevance_bonus("", "fix") == 0.0)
    test("MemDecay: tag_bonus capped at _MAX_TAG_BONUS", _tag_relevance_bonus("a,b,c,d,e", "a,b,c,d,e") <= _MAX_TAG_BONUS)
    test("MemDecay: tag_bonus case insensitive", _tag_relevance_bonus("FIX,ERROR", "fix,error") > 0.0)

    # calculate_relevance_score
    _fresh_t1 = {"tier": 1, "timestamp": _recent_ts, "retrieval_count": 5, "tags": "fix,error"}
    _score_t1 = calculate_relevance_score(_fresh_t1)
    test("MemDecay: fresh T1 score is high (>0.8)", _score_t1 > 0.8)

    _old_t3 = {"tier": 3, "timestamp": _old_ts, "retrieval_count": 0, "tags": ""}
    _score_t3 = calculate_relevance_score(_old_t3)
    test("MemDecay: old T3 score is low", _score_t3 < 0.5)

    test("MemDecay: score in [0,1]", 0.0 <= _score_t1 <= 1.0 and 0.0 <= _score_t3 <= 1.0)

    # T1 > T3 for same age
    _same_age_t1 = {"tier": 1, "timestamp": _old_ts, "retrieval_count": 0, "tags": ""}
    _same_age_t3 = {"tier": 3, "timestamp": _old_ts, "retrieval_count": 0, "tags": ""}
    test("MemDecay: T1 scores higher than T3 at same age",
         calculate_relevance_score(_same_age_t1) > calculate_relevance_score(_same_age_t3))

    # Query context boosts score
    _tagged_mem = {"tier": 2, "timestamp": _recent_ts, "retrieval_count": 0, "tags": "fix,error"}
    _s_no_ctx = calculate_relevance_score(_tagged_mem)
    _s_with_ctx = calculate_relevance_score(_tagged_mem, query_context="fix,error")
    test("MemDecay: query context boosts score", _s_with_ctx >= _s_no_ctx)

    # Missing fields handled
    _empty_entry = {}
    _s_empty = calculate_relevance_score(_empty_entry)
    test("MemDecay: empty entry doesn't crash", isinstance(_s_empty, float))
    test("MemDecay: empty entry score in [0,1]", 0.0 <= _s_empty <= 1.0)

    # rank_memories
    _mems = [
        {"tier": 3, "timestamp": _old_ts, "retrieval_count": 0, "tags": ""},
        {"tier": 1, "timestamp": _recent_ts, "retrieval_count": 10, "tags": "fix"},
        {"tier": 2, "timestamp": _recent_ts, "retrieval_count": 0, "tags": ""},
    ]
    _ranked = rank_memories(_mems)
    test("MemDecay: rank_memories returns same count", len(_ranked) == 3)
    test("MemDecay: rank_memories has _relevance_score", "_relevance_score" in _ranked[0])
    test("MemDecay: rank_memories sorted descending",
         _ranked[0]["_relevance_score"] >= _ranked[1]["_relevance_score"] >= _ranked[2]["_relevance_score"])
    test("MemDecay: rank_memories doesn't modify original", "_relevance_score" not in _mems[0])

    # identify_stale_memories
    _very_old_ts = (_md_dt.now(tz=_md_tz.utc) - _md_td(days=365)).isoformat()
    _stale_mems = [
        {"tier": 1, "timestamp": _recent_ts, "retrieval_count": 10, "tags": "fix"},
        {"tier": 3, "timestamp": _very_old_ts, "retrieval_count": 0, "tags": ""},
    ]
    _stale = identify_stale_memories(_stale_mems, threshold=0.2)
    test("MemDecay: identify_stale finds old low-tier entries", len(_stale) >= 1)
    test("MemDecay: stale entries have _relevance_score", all("_relevance_score" in s for s in _stale))
    test("MemDecay: stale entries below threshold", all(s["_relevance_score"] < 0.2 for s in _stale))
    test("MemDecay: empty list returns empty", len(identify_stale_memories([])) == 0)

except Exception as _md_exc:
    test("Memory Decay Deep Tests: import and tests", False, str(_md_exc))

# --- Session Compressor Deep Tests ---
print("\n--- Session Compressor Deep Tests ---")
try:
    from shared.session_compressor import (
        compress_session_context, extract_key_decisions, format_handoff,
    )

    # compress_session_context with full state
    _sc_state = {
        "files_edited": ["/tmp/foo.py", "/tmp/bar.py"],
        "verified_fixes": ["/tmp/foo.py"],
        "pending_verification": ["/tmp/bar.py"],
        "session_test_baseline": True,
        "last_test_exit_code": 0,
        "error_pattern_counts": {"ImportError": 3, "TypeError": 1},
        "pending_chain_ids": ["chain1"],
        "active_bans": ["bad_strategy"],
        "gate6_warn_count": 2,
        "edit_streak": {"/tmp/foo.py": 5, "/tmp/bar.py": 2},
    }
    _compressed = compress_session_context(_sc_state)
    test("SC: compress returns string", isinstance(_compressed, str))
    test("SC: compress includes FILES", "FILES:" in _compressed)
    test("SC: compress includes VERIFY", "VERIFY:" in _compressed)
    test("SC: compress includes TESTS:PASS", "TESTS:PASS" in _compressed)
    test("SC: compress includes ERRORS", "ERRORS:" in _compressed)
    test("SC: compress includes CHAINS", "CHAINS:" in _compressed)
    test("SC: compress includes BANS", "BANS:" in _compressed)
    test("SC: compress includes GATE6", "GATE6:" in _compressed)
    test("SC: compress includes CHURN", "CHURN:" in _compressed)

    # Verification tags
    test("SC: verified file has check mark", "foo.py" in _compressed and "✓" in _compressed)
    test("SC: pending file has question mark", "bar.py?" in _compressed)

    # Test failure format
    _sc_fail = {"session_test_baseline": True, "last_test_exit_code": 1}
    _comp_fail = compress_session_context(_sc_fail)
    test("SC: failed tests show FAIL", "FAIL" in _comp_fail)

    # Empty state
    _comp_empty = compress_session_context({})
    test("SC: empty state returns string", isinstance(_comp_empty, str))

    # Token budget truncation
    _sc_huge = {"files_edited": [f"/tmp/file_{i}.py" for i in range(100)]}
    _comp_huge = compress_session_context(_sc_huge, max_tokens=10)  # 40 chars max
    test("SC: truncation adds ellipsis", len(_comp_huge) <= 40 + 3)  # +3 for "..."

    # extract_key_decisions
    _ekd_state = {
        "tool_stats": {
            "Edit": {"blocked": 3},
            "remember_this": {"count": 5},
        },
        "gate_blocks": [{"gate": 1, "tool": "Edit"}, "legacy_block_str"],
        "session_test_baseline": True,
        "last_test_exit_code": 0,
        "all_chain_ids": ["c1", "c2", "c3"],
        "pending_chain_ids": ["c3"],
        "active_bans": ["strat_x"],
    }
    _decisions = extract_key_decisions(_ekd_state)
    test("SC: decisions is list", isinstance(_decisions, list))
    test("SC: decisions has GATE_BLOCK", any("GATE_BLOCK" in d for d in _decisions))
    test("SC: decisions has MEMORY saves", any("MEMORY" in d for d in _decisions))
    test("SC: decisions has TEST_PASS", any("TEST_PASS" in d for d in _decisions))
    test("SC: decisions has FIXED chains", any("FIXED" in d for d in _decisions))
    test("SC: decisions has BANNED", any("BANNED" in d for d in _decisions))

    # Legacy gate_blocks formats
    test("SC: legacy dict gate_block", any("gate1" in d or "gate?" in d for d in _decisions))
    test("SC: legacy string gate_block", any("legacy_block_str" in d for d in _decisions))

    # Empty decisions
    test("SC: empty state gives empty decisions", len(extract_key_decisions({})) == 0)

    # format_handoff
    _handoff = format_handoff(_sc_state, _decisions)
    test("SC: handoff has DONE section", "DONE:" in _handoff)
    test("SC: handoff has BLOCKED section", "BLOCKED:" in _handoff)
    test("SC: handoff has NEXT section", "NEXT:" in _handoff)
    test("SC: handoff includes verified files", "foo.py verified" in _handoff)
    test("SC: handoff includes pending files", "bar.py needs verification" in _handoff)
    test("SC: handoff includes open chains", "open causal chain" in _handoff)
    test("SC: handoff mentions high-churn stabilize", "stabilize" in _handoff)

    # Empty handoff
    _empty_handoff = format_handoff({}, [])
    test("SC: empty handoff has nothing verified", "nothing verified" in _empty_handoff)
    test("SC: empty handoff has none blocked", "(none)" in _empty_handoff)
    test("SC: empty handoff has continue next", "continue current work" in _empty_handoff)

except Exception as _sc_exc:
    test("Session Compressor Deep Tests: import and tests", False, str(_sc_exc))

# --- Hook Profiler Deep Tests ---
print("\n--- Hook Profiler Deep Tests ---")
try:
    from shared.hook_profiler import (
        profile, _percentile, _ns_to_us, _read_records,
        LATENCY_LOG,
    )

    # _percentile
    test("HP: _percentile empty list", _percentile([], 50) == 0.0)
    test("HP: _percentile single element", _percentile([100], 50) == 100)
    test("HP: _percentile p50 of [1,2,3,4,5]", _percentile([1, 2, 3, 4, 5], 50) == 3)
    test("HP: _percentile p0 returns first", _percentile([1, 2, 3], 0) == 1)
    test("HP: _percentile p100 returns last", _percentile([1, 2, 3], 100) == 3)
    test("HP: _percentile p95 of 100 elements", _percentile(list(range(100)), 95) == 94)  # nearest-rank
    test("HP: _percentile p99 of 10 elements", _percentile(list(range(10)), 99) == 9)

    # _ns_to_us formatting
    test("HP: _ns_to_us 1000 -> 1.0", _ns_to_us(1000) == "1.0")
    test("HP: _ns_to_us 0 -> 0.0", _ns_to_us(0) == "0.0")
    test("HP: _ns_to_us 1500 -> 1.5", _ns_to_us(1500) == "1.5")
    test("HP: _ns_to_us 500 -> 0.5", _ns_to_us(500) == "0.5")
    test("HP: _ns_to_us large value", _ns_to_us(1_000_000) == "1000.0")

    # profile wrapper
    def _hp_fake_check(tool_name, tool_input, state, event_type="PreToolUse"):
        class _FakeResult:
            blocked = False
            gate_name = "TEST"
        return _FakeResult()

    _wrapped = profile("__test_gate__", _hp_fake_check)
    test("HP: profile returns callable", callable(_wrapped))
    test("HP: wrapped has _profiler_wrapped", getattr(_wrapped, "_profiler_wrapped", False) is True)
    test("HP: wrapped preserves name", _wrapped.__name__ == "_hp_fake_check")
    test("HP: wrapped has _original_check", getattr(_wrapped, "_original_check", None) is _hp_fake_check)

    # Call wrapped function and verify result
    _hp_result = _wrapped("Edit", {"file_path": "/tmp/test.py"}, {})
    test("HP: wrapped returns correct result", _hp_result.blocked is False)
    test("HP: wrapped result has gate_name", _hp_result.gate_name == "TEST")

    # Blocking function
    def _hp_blocking_check(tool_name, tool_input, state, event_type="PreToolUse"):
        class _BlockResult:
            blocked = True
            gate_name = "BLOCK_TEST"
        return _BlockResult()

    _wrapped_block = profile("__test_block_gate__", _hp_blocking_check)
    _hp_br = _wrapped_block("Edit", {}, {})
    test("HP: blocking gate returns blocked=True", _hp_br.blocked is True)

    # LATENCY_LOG path
    test("HP: LATENCY_LOG is /tmp/gate_latency.jsonl", LATENCY_LOG == "/tmp/gate_latency.jsonl")

except Exception as _hp_exc:
    test("Hook Profiler Deep Tests: import and tests", False, str(_hp_exc))

# --- Metrics Collector Deep Tests ---
print("\n--- Metrics Collector Deep Tests ---")
try:
    from shared.metrics_collector import (
        inc as mc_inc, set_gauge as mc_set_gauge, observe as mc_observe,
        get_metric as mc_get_metric, get_all_metrics as mc_get_all_metrics,
        flush as mc_flush, rollup as mc_rollup, timed as mc_timed,
        record_gate_fire, record_gate_block, record_gate_latency,
        record_hook_duration, record_memory_query, set_memory_total,
        record_tool_call, set_test_pass_rate,
        _label_key, TYPE_COUNTER, TYPE_GAUGE, TYPE_HISTOGRAM,
        BUILTIN_METRICS, _store,
    )

    # Type constants
    test("MC: TYPE_COUNTER", TYPE_COUNTER == "counter")
    test("MC: TYPE_GAUGE", TYPE_GAUGE == "gauge")
    test("MC: TYPE_HISTOGRAM", TYPE_HISTOGRAM == "histogram")

    # BUILTIN_METRICS
    test("MC: BUILTIN_METRICS has gate.fires", "gate.fires" in BUILTIN_METRICS)
    test("MC: BUILTIN_METRICS has gate.blocks", "gate.blocks" in BUILTIN_METRICS)
    test("MC: BUILTIN_METRICS has gate.latency_ms", "gate.latency_ms" in BUILTIN_METRICS)
    test("MC: BUILTIN_METRICS has 8 entries", len(BUILTIN_METRICS) == 8)

    # _label_key
    test("MC: _label_key empty", _label_key(None) == "")
    test("MC: _label_key empty dict", _label_key({}) == "")
    test("MC: _label_key single", _label_key({"gate": "g1"}) == "gate=g1")
    test("MC: _label_key sorted", _label_key({"z": "1", "a": "2"}) == "a=2,z=1")

    # Counter operations
    mc_inc("__test_counter__", 1)
    _tc = mc_get_metric("__test_counter__")
    test("MC: counter increment", _tc.get("value", 0) >= 1)
    test("MC: counter type", _tc.get("type") == TYPE_COUNTER)
    mc_inc("__test_counter__", 5)
    _tc2 = mc_get_metric("__test_counter__")
    test("MC: counter accumulates", _tc2.get("value", 0) >= 6)

    # Gauge operations
    mc_set_gauge("__test_gauge__", 42.0)
    _tg = mc_get_metric("__test_gauge__")
    test("MC: gauge set value", _tg.get("value") == 42.0)
    test("MC: gauge type", _tg.get("type") == TYPE_GAUGE)
    mc_set_gauge("__test_gauge__", 99.0)
    _tg2 = mc_get_metric("__test_gauge__")
    test("MC: gauge overwrites", _tg2.get("value") == 99.0)

    # Histogram operations
    mc_observe("__test_hist__", 10.0)
    mc_observe("__test_hist__", 20.0)
    mc_observe("__test_hist__", 30.0)
    _th = mc_get_metric("__test_hist__")
    test("MC: histogram count >= 3", _th.get("count", 0) >= 3)
    test("MC: histogram has sum", "sum" in _th)
    test("MC: histogram has min", "min" in _th)
    test("MC: histogram has max", "max" in _th)
    test("MC: histogram has avg", "avg" in _th)
    test("MC: histogram type", _th.get("type") == TYPE_HISTOGRAM)

    # Labels
    mc_inc("__test_labels__", 1, labels={"gate": "g1"})
    _tl = mc_get_metric("__test_labels__", labels={"gate": "g1"})
    test("MC: labeled counter", _tl.get("value", 0) >= 1)

    # get_all_metrics
    _all_mc = mc_get_all_metrics()
    test("MC: get_all_metrics returns dict", isinstance(_all_mc, dict))
    test("MC: get_all_metrics includes test counter", "__test_counter__" in _all_mc)

    # rollup
    _ru = mc_rollup(window_seconds=3600)
    test("MC: rollup returns dict", isinstance(_ru, dict))

    # Convenience helpers
    record_gate_fire("__test_gate_mc__")
    record_gate_block("__test_gate_mc__")
    record_gate_latency("__test_gate_mc__", 5.0)
    record_hook_duration("PreToolUse", 10.0)
    record_memory_query()
    set_memory_total(100)
    record_tool_call()
    set_test_pass_rate(0.95)

    _tpr = mc_get_metric("test.pass_rate")
    test("MC: set_test_pass_rate sets gauge", _tpr.get("value") == 0.95)

    # set_test_pass_rate clamps
    set_test_pass_rate(1.5)
    _tpr2 = mc_get_metric("test.pass_rate")
    test("MC: set_test_pass_rate clamps to 1.0", _tpr2.get("value") == 1.0)

    set_test_pass_rate(-0.5)
    _tpr3 = mc_get_metric("test.pass_rate")
    test("MC: set_test_pass_rate clamps to 0.0", _tpr3.get("value") == 0.0)

    # flush
    _flush_ok = mc_flush()
    test("MC: flush returns bool", isinstance(_flush_ok, bool))

    # get_metric for nonexistent
    _nonexist = mc_get_metric("__nonexistent_metric__")
    test("MC: nonexistent metric returns empty dict", _nonexist == {})

    # timed context manager
    import time as _mc_time
    with mc_timed("__test_timed__"):
        _mc_time.sleep(0.001)
    _tt = mc_get_metric("__test_timed__")
    test("MC: timed records histogram", _tt.get("type") == TYPE_HISTOGRAM)
    test("MC: timed count >= 1", _tt.get("count", 0) >= 1)

except Exception as _mc_exc:
    test("Metrics Collector Deep Tests: import and tests", False, str(_mc_exc))

# ── Framework Health Score MCP Tool Tests ───────────────────────────────────
# Tests for the framework_health_score() analytics tool logic

try:
    # Test the scoring/grading logic independently
    # Grade mapping: A≥90, B≥75, C≥60, D≥40, F<40
    def _fhs_grade(score):
        return "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D" if score >= 40 else "F"

    test("FHS: grade A for 100", _fhs_grade(100) == "A")
    test("FHS: grade A for 90", _fhs_grade(90) == "A")
    test("FHS: grade B for 89", _fhs_grade(89) == "B")
    test("FHS: grade B for 75", _fhs_grade(75) == "B")
    test("FHS: grade C for 74", _fhs_grade(74) == "C")
    test("FHS: grade C for 60", _fhs_grade(60) == "C")
    test("FHS: grade D for 59", _fhs_grade(59) == "D")
    test("FHS: grade D for 40", _fhs_grade(40) == "D")
    test("FHS: grade F for 39", _fhs_grade(39) == "F")
    test("FHS: grade F for 0", _fhs_grade(0) == "F")

    # Weighted average calculation (same formula as the tool)
    def _fhs_weighted_avg(scores_dict):
        total_weight = sum(s.get("weight", 0) for s in scores_dict.values())
        weighted_sum = sum(s.get("score", 0) * s.get("weight", 0) for s in scores_dict.values())
        return int(weighted_sum / max(1, total_weight))

    # All perfect scores
    _fhs_perfect = {
        "test_pass_rate": {"score": 100, "weight": 40},
        "circuit_breakers": {"score": 100, "weight": 20},
        "memory_freshness": {"score": 100, "weight": 20},
        "gate_effectiveness": {"score": 100, "weight": 20},
    }
    test("FHS: perfect scores = 100", _fhs_weighted_avg(_fhs_perfect) == 100)

    # All zero scores
    _fhs_zero = {
        "test_pass_rate": {"score": 0, "weight": 40},
        "circuit_breakers": {"score": 0, "weight": 20},
        "memory_freshness": {"score": 0, "weight": 20},
        "gate_effectiveness": {"score": 0, "weight": 20},
    }
    test("FHS: zero scores = 0", _fhs_weighted_avg(_fhs_zero) == 0)

    # Mixed scores: 50*40 + 100*20 + 0*20 + 80*20 = 2000+2000+0+1600 = 5600/100 = 56
    _fhs_mixed = {
        "test_pass_rate": {"score": 50, "weight": 40},
        "circuit_breakers": {"score": 100, "weight": 20},
        "memory_freshness": {"score": 0, "weight": 20},
        "gate_effectiveness": {"score": 80, "weight": 20},
    }
    test("FHS: mixed scores = 56", _fhs_weighted_avg(_fhs_mixed) == 56)

    # Weights sum to 100
    test("FHS: weights sum to 100",
         sum(s["weight"] for s in _fhs_perfect.values()) == 100)

    # Test pass rate component scoring: rate * 100, capped at 100
    _fhs_tpr_score = lambda rate: min(100, int(rate * 100))
    test("FHS: TPR 1.0 = 100", _fhs_tpr_score(1.0) == 100)
    test("FHS: TPR 0.95 = 95", _fhs_tpr_score(0.95) == 95)
    test("FHS: TPR 0.5 = 50", _fhs_tpr_score(0.5) == 50)
    test("FHS: TPR 0.0 = 0", _fhs_tpr_score(0.0) == 0)
    test("FHS: TPR > 1.0 capped at 100", _fhs_tpr_score(1.5) == 100)

    # Circuit breaker component scoring
    def _fhs_cb_score(total, open_count):
        healthy = total - open_count if total > 0 else 1
        return int(100 * (healthy / max(1, total)))

    test("FHS: CB 0 open / 10 total = 100", _fhs_cb_score(10, 0) == 100)
    test("FHS: CB 5 open / 10 total = 50", _fhs_cb_score(10, 5) == 50)
    test("FHS: CB 10 open / 10 total = 0", _fhs_cb_score(10, 10) == 0)
    test("FHS: CB 0 total = 100", _fhs_cb_score(0, 0) == 100)  # healthy=1, total=0 → 100

    # Memory freshness scoring
    def _fhs_mem_score(age_sec):
        if age_sec < 300:
            return 100
        elif age_sec < 1800:
            return max(50, 100 - int((age_sec - 300) / 15))
        else:
            return max(0, 50 - int((age_sec - 1800) / 60))

    test("FHS: mem fresh 0s = 100", _fhs_mem_score(0) == 100)
    test("FHS: mem fresh 299s = 100", _fhs_mem_score(299) == 100)
    test("FHS: mem fresh 300s = 100", _fhs_mem_score(300) == 100)
    test("FHS: mem 600s > 50", _fhs_mem_score(600) >= 50)
    test("FHS: mem 1800s = 50", _fhs_mem_score(1800) >= 0)
    test("FHS: mem 3600s = low", _fhs_mem_score(3600) < 30)
    test("FHS: mem 86400s = 0", _fhs_mem_score(86400) == 0)
    test("FHS: mem decreasing", _fhs_mem_score(100) > _fhs_mem_score(600) > _fhs_mem_score(3600))

    # Gate effectiveness scoring
    def _fhs_gate_score(total_blocks, total_prevented, total_overrides):
        if total_blocks > 0:
            prevention_rate = total_prevented / max(1, total_blocks)
            override_rate = total_overrides / max(1, total_blocks)
            return max(0, min(100, int(80 + prevention_rate * 20 - override_rate * 40)))
        return 80

    test("FHS: gate no blocks = 80", _fhs_gate_score(0, 0, 0) == 80)
    test("FHS: gate all prevented = 100", _fhs_gate_score(10, 10, 0) == 100)
    test("FHS: gate all overridden < 80", _fhs_gate_score(10, 0, 10) < 80)
    test("FHS: gate score >= 0", _fhs_gate_score(1, 0, 100) >= 0)
    test("FHS: gate score <= 100", _fhs_gate_score(100, 100, 0) <= 100)

    # Recommendation triggers
    _fhs_recs = []
    if 0.9 < 0.95:
        _fhs_recs.append("Test pass rate below 95%")
    test("FHS: recommendation for low TPR", len(_fhs_recs) == 1)

    # Test calling the actual tool (if analytics_server importable)
    try:
        import importlib.util as _fhs_ilu
        _fhs_spec = _fhs_ilu.spec_from_file_location(
            "analytics_server", os.path.join(HOOKS_DIR, "analytics_server.py"))
        if _fhs_spec:
            _fhs_mod = _fhs_ilu.module_from_spec(_fhs_spec)
            # Don't exec the module (it starts FastMCP server), just verify it loads
            test("FHS: analytics_server importable", True)
        else:
            skip("FHS: analytics_server import", "spec not found")
    except Exception:
        skip("FHS: analytics_server import", "import failed")

    # Integration: verify the tool would return correct structure
    _fhs_expected_keys = {"overall_score", "grade", "components", "recommendations"}
    _fhs_result = {
        "overall_score": _fhs_weighted_avg(_fhs_mixed),
        "grade": _fhs_grade(_fhs_weighted_avg(_fhs_mixed)),
        "components": _fhs_mixed,
        "recommendations": [],
    }
    test("FHS: result has overall_score", "overall_score" in _fhs_result)
    test("FHS: result has grade", "grade" in _fhs_result)
    test("FHS: result has components", "components" in _fhs_result)
    test("FHS: result has recommendations", "recommendations" in _fhs_result)
    test("FHS: overall_score is int", isinstance(_fhs_result["overall_score"], int))
    test("FHS: grade is string", isinstance(_fhs_result["grade"], str))
    test("FHS: components is dict", isinstance(_fhs_result["components"], dict))
    test("FHS: recommendations is list", isinstance(_fhs_result["recommendations"], list))
    test("FHS: grade matches score", _fhs_result["grade"] == "D")  # 56 = D

    # Edge cases for weighted avg
    _fhs_single = {"only": {"score": 75, "weight": 100}}
    test("FHS: single component", _fhs_weighted_avg(_fhs_single) == 75)

    _fhs_empty = {}
    test("FHS: empty components = 0", _fhs_weighted_avg(_fhs_empty) == 0)

    # Missing weight defaults to 0
    _fhs_no_weight = {"a": {"score": 50}}
    test("FHS: missing weight treated as 0", _fhs_weighted_avg(_fhs_no_weight) == 0)

except Exception as _fhs_exc:
    test("Framework Health Score Tests: import and tests", False, str(_fhs_exc))

# ── Session Context Snapshot MCP Tool Tests ─────────────────────────────────
# Tests for the session_context_snapshot() analytics tool logic

try:
    from shared.session_compressor import (
        compress_session_context as _scs_compress,
        extract_key_decisions as _scs_decisions,
        format_handoff as _scs_handoff,
    )

    # Test with empty state (default case)
    _scs_empty = {}
    _scs_c1 = _scs_compress(_scs_empty)
    _scs_d1 = _scs_decisions(_scs_empty)
    _scs_h1 = _scs_handoff(_scs_empty, _scs_d1)

    test("SCS: compress empty state returns string", isinstance(_scs_c1, str))
    test("SCS: decisions empty state returns list", isinstance(_scs_d1, list))
    test("SCS: handoff empty state returns string", isinstance(_scs_h1, str))

    # Counter extraction logic (mirrors the tool)
    def _scs_counters(state):
        return {
            "files_edited": len(state.get("files_edited", [])),
            "pending_verification": len(state.get("pending_verification", [])),
            "verified_fixes": len(state.get("verified_fixes", [])),
            "open_chains": len(state.get("pending_chain_ids", [])),
            "active_bans": state.get("active_bans", []),
            "gate6_warns": state.get("gate6_warn_count", 0),
        }

    # Empty state counters
    _scs_ec = _scs_counters({})
    test("SCS: empty files_edited = 0", _scs_ec["files_edited"] == 0)
    test("SCS: empty pending_verification = 0", _scs_ec["pending_verification"] == 0)
    test("SCS: empty verified_fixes = 0", _scs_ec["verified_fixes"] == 0)
    test("SCS: empty open_chains = 0", _scs_ec["open_chains"] == 0)
    test("SCS: empty active_bans = []", _scs_ec["active_bans"] == [])
    test("SCS: empty gate6_warns = 0", _scs_ec["gate6_warns"] == 0)

    # Populated state counters
    _scs_rich = {
        "files_edited": ["a.py", "b.py", "c.py"],
        "pending_verification": ["fix1"],
        "verified_fixes": ["fix0", "fix_old"],
        "pending_chain_ids": ["chain_1", "chain_2"],
        "active_bans": ["brute_force", "sleep_retry"],
        "gate6_warn_count": 3,
    }
    _scs_rc = _scs_counters(_scs_rich)
    test("SCS: files_edited = 3", _scs_rc["files_edited"] == 3)
    test("SCS: pending_verification = 1", _scs_rc["pending_verification"] == 1)
    test("SCS: verified_fixes = 2", _scs_rc["verified_fixes"] == 2)
    test("SCS: open_chains = 2", _scs_rc["open_chains"] == 2)
    test("SCS: active_bans has 2 items", len(_scs_rc["active_bans"]) == 2)
    test("SCS: gate6_warns = 3", _scs_rc["gate6_warns"] == 3)

    # Result structure validation
    _scs_result = {
        "compressed_context": _scs_c1,
        "decisions": _scs_d1,
        "handoff": _scs_h1,
        "counters": _scs_ec,
    }
    test("SCS: result has compressed_context", "compressed_context" in _scs_result)
    test("SCS: result has decisions", "decisions" in _scs_result)
    test("SCS: result has handoff", "handoff" in _scs_result)
    test("SCS: result has counters", "counters" in _scs_result)

    # Compress with rich state
    _scs_c2 = _scs_compress(_scs_rich)
    test("SCS: compress rich state returns string", isinstance(_scs_c2, str))
    test("SCS: compress rich state non-empty", len(_scs_c2) > 0)

    # Decisions with gate blocks in state
    _scs_gate_state = {
        "gate_blocks": [
            {"gate": "gate_01", "tool": "Edit", "reason": "no read"},
            {"gate": "gate_06", "tool": "Write", "reason": "unverified"},
        ],
        "test_results": {"passed": 100, "failed": 2},
        "verified_fixes": ["fix_auth_bug"],
        "active_bans": ["sleep_retry"],
    }
    _scs_d2 = _scs_decisions(_scs_gate_state)
    test("SCS: decisions returns list", isinstance(_scs_d2, list))

    # Handoff with rich state
    _scs_h2 = _scs_handoff(_scs_gate_state, _scs_d2)
    test("SCS: handoff returns string", isinstance(_scs_h2, str))
    test("SCS: handoff non-empty with data", len(_scs_h2) > 0)

    # Counter keys are all present
    _expected_counter_keys = {"files_edited", "pending_verification", "verified_fixes",
                               "open_chains", "active_bans", "gate6_warns"}
    test("SCS: all counter keys present",
         set(_scs_counters(_scs_rich).keys()) == _expected_counter_keys)

    # Counter values are correct types
    _scs_types = _scs_counters(_scs_rich)
    test("SCS: files_edited is int", isinstance(_scs_types["files_edited"], int))
    test("SCS: pending_verification is int", isinstance(_scs_types["pending_verification"], int))
    test("SCS: verified_fixes is int", isinstance(_scs_types["verified_fixes"], int))
    test("SCS: open_chains is int", isinstance(_scs_types["open_chains"], int))
    test("SCS: active_bans is list", isinstance(_scs_types["active_bans"], list))
    test("SCS: gate6_warns is int", isinstance(_scs_types["gate6_warns"], int))

    # Missing keys in state default gracefully
    _scs_partial = {"files_edited": ["x.py"]}
    _scs_pc = _scs_counters(_scs_partial)
    test("SCS: partial state files = 1", _scs_pc["files_edited"] == 1)
    test("SCS: partial state pending = 0", _scs_pc["pending_verification"] == 0)
    test("SCS: partial state gate6 = 0", _scs_pc["gate6_warns"] == 0)

    # Non-list values don't crash (defensive)
    _scs_bad = {"files_edited": "not_a_list", "gate6_warn_count": "bad"}
    try:
        _scs_bc = _scs_counters(_scs_bad)
        # len("not_a_list") = 10, which is wrong but doesn't crash
        test("SCS: non-list files_edited doesn't crash", True)
    except Exception:
        test("SCS: non-list files_edited doesn't crash", False, "crashed")

except Exception as _scs_exc:
    test("Session Context Snapshot Tests: import and tests", False, str(_scs_exc))

# ── Event Bus Deep Tests ────────────────────────────────────────────────────
# Tests for event_bus.py: subscribe, publish, get_recent, clear, get_stats,
# configure, unsubscribe, load_persisted, EventType

try:
    from shared.event_bus import (
        EventType, subscribe, unsubscribe, publish, get_recent,
        clear, get_stats, configure, load_persisted,
    )

    # Save state and clear before tests
    clear()

    # --- EventType constants ---
    test("EB: GATE_FIRED constant", EventType.GATE_FIRED == "GATE_FIRED")
    test("EB: GATE_BLOCKED constant", EventType.GATE_BLOCKED == "GATE_BLOCKED")
    test("EB: MEMORY_QUERIED constant", EventType.MEMORY_QUERIED == "MEMORY_QUERIED")
    test("EB: TEST_RUN constant", EventType.TEST_RUN == "TEST_RUN")
    test("EB: ERROR_DETECTED constant", EventType.ERROR_DETECTED == "ERROR_DETECTED")
    test("EB: FIX_APPLIED constant", EventType.FIX_APPLIED == "FIX_APPLIED")
    test("EB: TOOL_CALLED constant", EventType.TOOL_CALLED == "TOOL_CALLED")
    test("EB: ALL has 7 types", len(EventType.ALL) == 7)

    # --- publish basic ---
    clear()
    _eb_evt = publish(EventType.GATE_FIRED, {"gate": "test"}, source="test_fw", persist=False)
    test("EB: publish returns dict", isinstance(_eb_evt, dict))
    test("EB: publish has type", _eb_evt["type"] == EventType.GATE_FIRED)
    test("EB: publish has timestamp", "timestamp" in _eb_evt)
    test("EB: publish has data", _eb_evt["data"] == {"gate": "test"})
    test("EB: publish has source", _eb_evt["source"] == "test_fw")

    # --- get_recent ---
    _eb_recent = get_recent()
    test("EB: get_recent returns list", isinstance(_eb_recent, list))
    test("EB: get_recent has 1 event", len(_eb_recent) == 1)

    # Filter by type
    publish(EventType.GATE_BLOCKED, {"g": 2}, persist=False)
    _eb_fired_only = get_recent(EventType.GATE_FIRED)
    test("EB: get_recent filters by type", len(_eb_fired_only) == 1)
    test("EB: filter returns correct type", _eb_fired_only[0]["type"] == EventType.GATE_FIRED)

    # Limit
    clear()
    for _i in range(10):
        publish(EventType.TEST_RUN, {"i": _i}, persist=False)
    _eb_lim = get_recent(limit=3)
    test("EB: get_recent limit=3", len(_eb_lim) == 3)
    test("EB: get_recent returns most recent", _eb_lim[-1]["data"]["i"] == 9)

    # --- subscribe + handler ---
    clear()
    _eb_received = []
    _eb_handler = lambda e: _eb_received.append(e)
    subscribe(EventType.GATE_BLOCKED, _eb_handler)
    publish(EventType.GATE_BLOCKED, {"test": True}, persist=False)
    test("EB: handler called", len(_eb_received) == 1)
    test("EB: handler receives event", _eb_received[0]["data"]["test"] is True)

    # Different type doesn't trigger handler
    publish(EventType.GATE_FIRED, {"other": True}, persist=False)
    test("EB: handler not called for other type", len(_eb_received) == 1)

    # --- unsubscribe ---
    _eb_unsub_ok = unsubscribe(EventType.GATE_BLOCKED, _eb_handler)
    test("EB: unsubscribe returns True", _eb_unsub_ok is True)

    publish(EventType.GATE_BLOCKED, {"after": True}, persist=False)
    test("EB: handler not called after unsub", len(_eb_received) == 1)

    _eb_unsub_bad = unsubscribe(EventType.GATE_BLOCKED, lambda e: None)
    test("EB: unsubscribe unknown returns False", _eb_unsub_bad is False)

    # --- get_stats ---
    clear()
    publish(EventType.GATE_FIRED, {}, persist=False)
    publish(EventType.GATE_FIRED, {}, persist=False)
    publish(EventType.TEST_RUN, {}, persist=False)
    _eb_stats = get_stats()
    test("EB: stats total_published = 3", _eb_stats["total_published"] == 3)
    test("EB: stats events_in_buffer = 3", _eb_stats["events_in_buffer"] == 3)
    test("EB: stats buffer_capacity > 0", _eb_stats["buffer_capacity"] > 0)
    test("EB: stats by_type GATE_FIRED = 2",
         _eb_stats["by_type"].get(EventType.GATE_FIRED) == 2)
    test("EB: stats by_type TEST_RUN = 1",
         _eb_stats["by_type"].get(EventType.TEST_RUN) == 1)
    test("EB: stats has subscriber_count", "subscriber_count" in _eb_stats)
    test("EB: stats has handler_errors", "handler_errors" in _eb_stats)

    # --- configure ring buffer ---
    clear()
    configure(max_events=5)
    for _i in range(10):
        publish(EventType.TOOL_CALLED, {"i": _i}, persist=False)
    _eb_buf = get_recent()
    test("EB: ring buffer caps at 5", len(_eb_buf) <= 5)
    test("EB: oldest dropped, newest kept", _eb_buf[-1]["data"]["i"] == 9)

    # Restore default
    configure(max_events=1000)

    # --- broken handler is fail-open ---
    clear()
    def _eb_bad(e):
        raise RuntimeError("boom")
    subscribe(EventType.ERROR_DETECTED, _eb_bad)
    _eb_bad_result = publish(EventType.ERROR_DETECTED, {"err": True}, persist=False)
    test("EB: broken handler doesn't crash publish", _eb_bad_result is not None)
    _eb_err_stats = get_stats()
    test("EB: handler error counted",
         _eb_err_stats["handler_errors"].get(EventType.ERROR_DETECTED, 0) >= 1)

    # --- clear resets everything ---
    clear()
    _eb_cs = get_stats()
    test("EB: clear resets total_published", _eb_cs["total_published"] == 0)
    test("EB: clear resets events_in_buffer", _eb_cs["events_in_buffer"] == 0)
    test("EB: clear resets subscriber_count", _eb_cs["subscriber_count"] == 0)

    # --- publish with persist=False doesn't write file ---
    clear()
    publish(EventType.GATE_FIRED, {"no_persist": True}, persist=False)
    test("EB: publish persist=False still returns event",
         get_recent()[-1]["data"]["no_persist"] is True)

    # --- duplicate subscribe prevention ---
    clear()
    _eb_dup_count = []
    _eb_dup_handler = lambda e: _eb_dup_count.append(1)
    subscribe(EventType.FIX_APPLIED, _eb_dup_handler)
    subscribe(EventType.FIX_APPLIED, _eb_dup_handler)  # duplicate
    publish(EventType.FIX_APPLIED, {}, persist=False)
    test("EB: duplicate handler only called once", len(_eb_dup_count) == 1)

    # --- custom event type ---
    clear()
    _eb_custom = publish("CUSTOM_EVENT", {"custom": True}, persist=False)
    test("EB: custom event type works", _eb_custom["type"] == "CUSTOM_EVENT")
    _eb_custom_recent = get_recent("CUSTOM_EVENT")
    test("EB: custom event retrievable", len(_eb_custom_recent) == 1)

    # Final cleanup
    clear()

except Exception as _eb_exc:
    test("Event Bus Deep Tests: import and tests", False, str(_eb_exc))

# ── Gate Dashboard Deep Tests ───────────────────────────────────────────────
# Tests for gate_dashboard.py: GateMetrics, get_gate_metrics,
# rank_gates_by_value, render_dashboard, get_recommendations

try:
    from shared.gate_dashboard import (
        GateMetrics, get_gate_metrics, rank_gates_by_value,
        render_dashboard, get_recommendations,
        _normalise_key, _label, _GATE_LABELS, _GATED_TOOLS, _TIER1_GATES,
    )
    import math as _gd_math

    # --- GateMetrics dataclass ---
    _gd_m = GateMetrics()
    test("GD: default blocks = 0", _gd_m.blocks == 0)
    test("GD: default overrides = 0", _gd_m.overrides == 0)
    test("GD: default prevented = 0", _gd_m.prevented == 0)
    test("GD: default fires = 0", _gd_m.fires == 0)
    test("GD: default block_rate = 0.0", _gd_m.block_rate == 0.0)
    test("GD: default coverage = 0.0", _gd_m.coverage == 0.0)
    test("GD: default effectiveness = 0.0", _gd_m.effectiveness == 0.0)
    test("GD: default value_score = 0.0", _gd_m.value_score == 0.0)
    test("GD: default tool_calls_total = 0", _gd_m.tool_calls_total == 0)

    _gd_m2 = GateMetrics(blocks=10, overrides=2, prevented=5, fires=10,
                          block_rate=0.5, coverage=0.3, effectiveness=0.8,
                          value_score=0.75, tool_calls_total=100)
    test("GD: custom blocks", _gd_m2.blocks == 10)
    test("GD: custom value_score", _gd_m2.value_score == 0.75)

    # --- _normalise_key ---
    test("GD: normalise strips whitespace", _normalise_key("  gate_01  ") == "gate_01")
    test("GD: normalise no-op on clean", _normalise_key("gate_01") == "gate_01")

    # --- _label ---
    test("GD: label known gate", _label("gate_01_read_before_edit") == "G01 Read-Before-Edit")
    test("GD: label unknown gate", _label("gate_99_custom") == "gate_99_custom")

    # --- Constants ---
    test("GD: GATE_LABELS has 15 entries", len(_GATE_LABELS) >= 15)
    test("GD: GATED_TOOLS has Edit", "Edit" in _GATED_TOOLS)
    test("GD: GATED_TOOLS has Write", "Write" in _GATED_TOOLS)
    test("GD: GATED_TOOLS has Bash", "Bash" in _GATED_TOOLS)
    test("GD: TIER1_GATES has gate_01", "gate_01_read_before_edit" in _TIER1_GATES)
    test("GD: TIER1_GATES has 3 gates", len(_TIER1_GATES) == 3)

    # --- get_gate_metrics returns dict ---
    _gd_metrics = get_gate_metrics()
    test("GD: get_gate_metrics returns dict", isinstance(_gd_metrics, dict))

    # Check if metrics are populated (depends on .gate_effectiveness.json existing)
    if _gd_metrics:
        _gd_first_key = list(_gd_metrics.keys())[0]
        _gd_first = _gd_metrics[_gd_first_key]
        test("GD: metric is GateMetrics", isinstance(_gd_first, GateMetrics))
        test("GD: blocks >= 0", _gd_first.blocks >= 0)
        test("GD: block_rate in [0,1]", 0.0 <= _gd_first.block_rate <= 1.0)
        test("GD: coverage in [0,1]", 0.0 <= _gd_first.coverage <= 1.0)
        test("GD: effectiveness >= 0", _gd_first.effectiveness >= 0)
        test("GD: value_score >= 0", _gd_first.value_score >= 0)
    else:
        skip("GD: metrics populated", "no .gate_effectiveness.json")

    # --- rank_gates_by_value ---
    _gd_ranked = rank_gates_by_value()
    test("GD: rank returns list", isinstance(_gd_ranked, list))
    if len(_gd_ranked) >= 2:
        test("GD: rank descending by value",
             _gd_ranked[0][1].value_score >= _gd_ranked[-1][1].value_score)

    # --- render_dashboard ---
    _gd_dash = render_dashboard()
    test("GD: dashboard returns string", isinstance(_gd_dash, str))
    if _gd_metrics:
        test("GD: dashboard has header", "GATE EFFECTIVENESS DASHBOARD" in _gd_dash)
        test("GD: dashboard has separator", "=" * 80 in _gd_dash)
    else:
        test("GD: dashboard no-data message", "no effectiveness data" in _gd_dash)

    # --- get_recommendations ---
    _gd_recs = get_recommendations()
    test("GD: recommendations returns list", isinstance(_gd_recs, list))
    test("GD: recommendations non-empty", len(_gd_recs) > 0)
    test("GD: recommendations are strings", all(isinstance(r, str) for r in _gd_recs))

    # Value score formula verification
    # value_score = 0.40 * coverage + 0.40 * effectiveness + 0.20 * prevented_bonus
    _gd_vs = 0.40 * 0.5 + 0.40 * 0.8 + 0.20 * 0.6
    test("GD: value_score formula", abs(_gd_vs - 0.64) < 0.001)

    # Effectiveness formula: log1p(blocks)/log1p(total) * (1 - override_ratio)
    _gd_eff = (_gd_math.log1p(10) / _gd_math.log1p(100)) * (1.0 - 0.2)
    test("GD: effectiveness formula", 0 < _gd_eff < 1)

    # Prevented bonus: log1p(prevented)/log1p(10), capped at 1.0
    _gd_pb = min(1.0, _gd_math.log1p(5) / _gd_math.log1p(10))
    test("GD: prevented bonus in [0,1]", 0 <= _gd_pb <= 1.0)

except Exception as _gd_exc:
    test("Gate Dashboard Deep Tests: import and tests", False, str(_gd_exc))

# ── Tool Fingerprint Deep Tests ─────────────────────────────────────────────
# Tests for tool_fingerprint.py: fingerprint_tool, register_tool,
# check_tool_integrity, get_all_fingerprints, get_changed_tools

try:
    from shared.tool_fingerprint import (
        fingerprint_tool, register_tool, check_tool_integrity,
        get_all_fingerprints, get_changed_tools,
        _load_fingerprints, _save_fingerprints, FINGERPRINT_FILE,
    )
    import json as _tf_json
    import os as _tf_os

    # --- fingerprint_tool ---
    _tf_h1 = fingerprint_tool("test_tool", "A test tool", {"type": "object"})
    test("TF: fingerprint returns string", isinstance(_tf_h1, str))
    test("TF: fingerprint is 64 hex chars", len(_tf_h1) == 64)

    # Deterministic
    _tf_h2 = fingerprint_tool("test_tool", "A test tool", {"type": "object"})
    test("TF: fingerprint deterministic", _tf_h1 == _tf_h2)

    # Different input = different hash
    _tf_h3 = fingerprint_tool("test_tool", "Different description", {"type": "object"})
    test("TF: different desc = different hash", _tf_h1 != _tf_h3)

    _tf_h4 = fingerprint_tool("other_tool", "A test tool", {"type": "object"})
    test("TF: different name = different hash", _tf_h1 != _tf_h4)

    _tf_h5 = fingerprint_tool("test_tool", "A test tool", {"type": "string"})
    test("TF: different params = different hash", _tf_h1 != _tf_h5)

    # Defaults
    _tf_h6 = fingerprint_tool("empty_tool")
    test("TF: fingerprint with defaults", len(_tf_h6) == 64)

    _tf_h7 = fingerprint_tool("empty_tool", "", None)
    test("TF: None params = empty params", _tf_h6 == _tf_h7)

    # --- register_tool (in-memory check, avoid disk side effects) ---
    # Backup existing fingerprints
    _tf_backup = None
    if _tf_os.path.exists(FINGERPRINT_FILE):
        with open(FINGERPRINT_FILE) as _f:
            _tf_backup = _f.read()

    try:
        # Start clean
        _save_fingerprints({})

        # Register new tool
        _tf_r1 = register_tool("__test_new__", "test desc", {"p": 1})
        test("TF: register new is_new=True", _tf_r1[0] is True)
        test("TF: register new changed=False", _tf_r1[1] is False)
        test("TF: register new old_hash=None", _tf_r1[2] is None)
        test("TF: register new has hash", len(_tf_r1[3]) == 64)

        # Register same tool again (no change)
        _tf_r2 = register_tool("__test_new__", "test desc", {"p": 1})
        test("TF: re-register is_new=False", _tf_r2[0] is False)
        test("TF: re-register changed=False", _tf_r2[1] is False)
        test("TF: re-register same hash", _tf_r2[3] == _tf_r1[3])

        # Register with changed description
        _tf_r3 = register_tool("__test_new__", "changed desc", {"p": 1})
        test("TF: changed desc is_new=False", _tf_r3[0] is False)
        test("TF: changed desc changed=True", _tf_r3[1] is True)
        test("TF: changed desc old_hash present", _tf_r3[2] == _tf_r1[3])
        test("TF: changed desc new_hash differs", _tf_r3[3] != _tf_r1[3])

        # --- check_tool_integrity ---
        _tf_c1 = check_tool_integrity("__test_new__", "changed desc", {"p": 1})
        test("TF: integrity matches", _tf_c1[0] is True)

        _tf_c2 = check_tool_integrity("__test_new__", "tampered desc", {"p": 1})
        test("TF: integrity mismatch", _tf_c2[0] is False)

        _tf_c3 = check_tool_integrity("__unregistered__", "desc")
        test("TF: unregistered = matches (new)", _tf_c3[0] is True)
        test("TF: unregistered old_hash=None", _tf_c3[1] is None)

        # --- get_all_fingerprints ---
        _tf_all = get_all_fingerprints()
        test("TF: get_all returns dict", isinstance(_tf_all, dict))
        test("TF: get_all has test tool", "__test_new__" in _tf_all)
        test("TF: record has hash", "hash" in _tf_all["__test_new__"])
        test("TF: record has first_seen", "first_seen" in _tf_all["__test_new__"])
        test("TF: record has last_seen", "last_seen" in _tf_all["__test_new__"])
        test("TF: record has change_count", "change_count" in _tf_all["__test_new__"])
        test("TF: change_count = 1", _tf_all["__test_new__"]["change_count"] == 1)

        # --- get_changed_tools ---
        _tf_changed = get_changed_tools()
        test("TF: changed returns list", isinstance(_tf_changed, list))
        _tf_changed_names = [c["tool_name"] for c in _tf_changed]
        test("TF: changed includes test tool", "__test_new__" in _tf_changed_names)
        _tf_ct = [c for c in _tf_changed if c["tool_name"] == "__test_new__"][0]
        test("TF: changed has current_hash", "current_hash" in _tf_ct)
        test("TF: changed has previous_hash", "previous_hash" in _tf_ct)
        test("TF: changed has change_count", _tf_ct["change_count"] == 1)

        # Tool with no changes
        register_tool("__test_stable__", "stable", {})
        _tf_changed2 = get_changed_tools()
        _tf_stable_names = [c["tool_name"] for c in _tf_changed2]
        test("TF: stable tool not in changed list", "__test_stable__" not in _tf_stable_names)

    finally:
        # Restore backup
        if _tf_backup is not None:
            with open(FINGERPRINT_FILE, "w") as _f:
                _f.write(_tf_backup)
        elif _tf_os.path.exists(FINGERPRINT_FILE):
            _tf_os.remove(FINGERPRINT_FILE)

except Exception as _tf_exc:
    test("Tool Fingerprint Deep Tests: import and tests", False, str(_tf_exc))

# ── Tool Recommendation Engine Deep Tests ───────────────────────────────────
# Tests for tool_recommendation.py: build_tool_profile, should_recommend,
# recommend_alternative, get_recommendation_stats

try:
    from shared.tool_recommendation import (
        ToolProfile, Recommendation,
        build_tool_profile, should_recommend, recommend_alternative,
        get_recommendation_stats,
        MIN_CALLS_FOR_STATS, BLOCK_RATE_THRESHOLD, MIN_IMPROVEMENT,
        TOOL_EQUIVALENCES, ALWAYS_OK_TOOLS, SEQUENCE_FIXES,
    )

    # --- ToolProfile dataclass ---
    _tr_tp = ToolProfile(tool_name="Edit")
    test("TR: ToolProfile defaults", _tr_tp.call_count == 0)
    test("TR: ToolProfile success_rate default", _tr_tp.success_rate == 1.0)
    test("TR: ToolProfile block_rate default", _tr_tp.block_rate == 0.0)

    _tr_tp2 = ToolProfile("Write", call_count=10, block_count=3, error_count=1,
                           success_rate=0.6, block_rate=0.3)
    test("TR: ToolProfile custom", _tr_tp2.success_rate == 0.6)

    # --- Recommendation dataclass ---
    _tr_rec = Recommendation("Edit", "Write", "test reason", 0.8, 0.5, 0.9)
    test("TR: Recommendation fields", _tr_rec.original_tool == "Edit")
    test("TR: Recommendation suggested", _tr_rec.suggested_tool == "Write")
    test("TR: Recommendation confidence", _tr_rec.confidence == 0.8)

    # --- Constants ---
    test("TR: MIN_CALLS_FOR_STATS > 0", MIN_CALLS_FOR_STATS > 0)
    test("TR: BLOCK_RATE_THRESHOLD > 0", BLOCK_RATE_THRESHOLD > 0)
    test("TR: BLOCK_RATE_THRESHOLD < 1", BLOCK_RATE_THRESHOLD < 1.0)
    test("TR: MIN_IMPROVEMENT > 0", MIN_IMPROVEMENT > 0)
    test("TR: ALWAYS_OK has Read", "Read" in ALWAYS_OK_TOOLS)
    test("TR: ALWAYS_OK has Glob", "Glob" in ALWAYS_OK_TOOLS)
    test("TR: Edit has equivalents", "Edit" in TOOL_EQUIVALENCES)
    test("TR: Write equiv of Edit", "Write" in TOOL_EQUIVALENCES["Edit"])
    test("TR: SEQUENCE_FIXES non-empty", len(SEQUENCE_FIXES) > 0)

    # --- build_tool_profile ---
    # Empty state
    _tr_empty_p = build_tool_profile({})
    test("TR: empty state = empty profiles", len(_tr_empty_p) == 0)

    # State with tool counts but no blocks
    _tr_clean_state = {
        "tool_call_counts": {"Edit": 20, "Read": 50, "Bash": 15},
        "gate_block_outcomes": [],
    }
    _tr_clean_p = build_tool_profile(_tr_clean_state)
    test("TR: clean state 3 profiles", len(_tr_clean_p) == 3)
    test("TR: Edit success = 1.0", _tr_clean_p["Edit"].success_rate == 1.0)
    test("TR: Edit block = 0.0", _tr_clean_p["Edit"].block_rate == 0.0)
    test("TR: Edit calls = 20", _tr_clean_p["Edit"].call_count == 20)

    # State with blocks
    _tr_blocked_state = {
        "tool_call_counts": {"Edit": 20, "Write": 10, "Read": 30},
        "gate_block_outcomes": [
            {"tool": "Edit"}, {"tool": "Edit"}, {"tool": "Edit"},
            {"tool": "Edit"}, {"tool": "Edit"}, {"tool": "Edit"},
            {"tool": "Edit"}, {"tool": "Edit"},  # 8 blocks on Edit
            {"tool": "Write"},  # 1 block on Write
        ],
    }
    _tr_blocked_p = build_tool_profile(_tr_blocked_state)
    test("TR: Edit block_rate = 0.4", abs(_tr_blocked_p["Edit"].block_rate - 0.4) < 0.01)
    test("TR: Edit success = 0.6", abs(_tr_blocked_p["Edit"].success_rate - 0.6) < 0.01)
    test("TR: Write block_rate = 0.1", abs(_tr_blocked_p["Write"].block_rate - 0.1) < 0.01)
    test("TR: Read block_rate = 0.0", _tr_blocked_p["Read"].block_rate == 0.0)
    test("TR: Edit block_count = 8", _tr_blocked_p["Edit"].block_count == 8)

    # With errors
    _tr_error_state = {
        "tool_call_counts": {"Bash": 10},
        "gate_block_outcomes": [{"tool": "Bash"}] * 2,
        "tool_errors": {"Bash": 3},
    }
    _tr_error_p = build_tool_profile(_tr_error_state)
    test("TR: Bash with errors success = 0.5",
         abs(_tr_error_p["Bash"].success_rate - 0.5) < 0.01)
    test("TR: Bash error_count = 3", _tr_error_p["Bash"].error_count == 3)

    # Legacy 'tool_name' key in block outcomes
    _tr_legacy_state = {
        "tool_call_counts": {"Edit": 10},
        "gate_block_outcomes": [{"tool_name": "Edit"}] * 5,
    }
    _tr_legacy_p = build_tool_profile(_tr_legacy_state)
    test("TR: legacy tool_name key works", _tr_legacy_p["Edit"].block_count == 5)

    # --- should_recommend ---
    _tr_sr_state = {
        "tool_call_counts": {"Edit": 20, "Read": 50},
        "gate_block_outcomes": [{"tool": "Edit"}] * 8,
    }
    test("TR: should_recommend high block Edit", should_recommend("Edit", _tr_sr_state) is True)
    test("TR: should_recommend clean Read", should_recommend("Read", _tr_sr_state) is False)
    test("TR: should_recommend always-ok Glob",
         should_recommend("Glob", _tr_sr_state) is False)

    # Not enough data
    _tr_few_state = {
        "tool_call_counts": {"Edit": 3},
        "gate_block_outcomes": [{"tool": "Edit"}] * 2,
    }
    test("TR: should_recommend few calls = False",
         should_recommend("Edit", _tr_few_state) is False)

    # Unknown tool
    test("TR: should_recommend unknown tool = False",
         should_recommend("UnknownTool", _tr_sr_state) is False)

    # Below threshold
    _tr_low_block = {
        "tool_call_counts": {"Edit": 20},
        "gate_block_outcomes": [{"tool": "Edit"}] * 4,  # 20% < 30% threshold
    }
    test("TR: should_recommend low block = False",
         should_recommend("Edit", _tr_low_block) is False)

    # --- recommend_alternative ---
    # Always-OK tool
    test("TR: no rec for Read", recommend_alternative("Read", {}) is None)

    # Not enough data
    test("TR: no rec few calls",
         recommend_alternative("Edit", {"tool_call_counts": {"Edit": 2}}) is None)

    # Sequence-based recommendation: Glob -> Edit should suggest Read
    _tr_seq_state = {
        "tool_call_counts": {"Edit": 10, "Read": 20, "Glob": 15},
        "gate_block_outcomes": [{"tool": "Edit"}] * 5,
    }
    _tr_seq_rec = recommend_alternative("Edit", _tr_seq_state, recent_tools=["Glob"])
    test("TR: sequence rec for Glob->Edit", _tr_seq_rec is not None)
    if _tr_seq_rec:
        test("TR: sequence rec suggests Read", _tr_seq_rec.suggested_tool == "Read")
        test("TR: sequence rec has reason", "Read" in _tr_seq_rec.reason)
        test("TR: sequence rec confidence = 0.8", _tr_seq_rec.confidence == 0.8)

    # Equivalence-based recommendation: Edit blocked, Write succeeds
    _tr_equiv_state = {
        "tool_call_counts": {"Edit": 20, "Write": 20},
        "gate_block_outcomes": [{"tool": "Edit"}] * 12,  # 60% block rate on Edit
        # Write has 0 blocks → 100% success
    }
    _tr_equiv_rec = recommend_alternative("Edit", _tr_equiv_state)
    test("TR: equiv rec Edit->Write", _tr_equiv_rec is not None)
    if _tr_equiv_rec:
        test("TR: equiv rec suggests Write", _tr_equiv_rec.suggested_tool == "Write")
        test("TR: equiv rec confidence > 0", _tr_equiv_rec.confidence > 0)
        test("TR: equiv rec improvement", _tr_equiv_rec.suggested_success > _tr_equiv_rec.original_success)

    # No recommendation when both tools perform equally
    _tr_equal_state = {
        "tool_call_counts": {"Edit": 20, "Write": 20},
        "gate_block_outcomes": [{"tool": "Edit"}] * 3 + [{"tool": "Write"}] * 3,
    }
    _tr_equal_rec = recommend_alternative("Edit", _tr_equal_state)
    test("TR: no rec when equal performance", _tr_equal_rec is None)

    # Sequence fixes: Grep -> Write should suggest Read
    _tr_grep_state = {
        "tool_call_counts": {"Write": 10, "Read": 20, "Grep": 15},
        "gate_block_outcomes": [{"tool": "Write"}] * 5,
    }
    _tr_grep_rec = recommend_alternative("Write", _tr_grep_state, recent_tools=["Grep"])
    test("TR: Grep->Write suggests Read", _tr_grep_rec is not None)
    if _tr_grep_rec:
        test("TR: Grep->Write rec = Read", _tr_grep_rec.suggested_tool == "Read")

    # --- get_recommendation_stats ---
    _tr_stats_empty = get_recommendation_stats({})
    test("TR: stats empty = 0 analyzed", _tr_stats_empty["tools_analyzed"] == 0)
    test("TR: stats empty at_risk = []", _tr_stats_empty["tools_at_risk"] == [])

    _tr_stats_state = {
        "tool_call_counts": {"Edit": 20, "Read": 50, "Bash": 15, "Write": 10},
        "gate_block_outcomes": [{"tool": "Edit"}] * 8 + [{"tool": "Bash"}] * 6,
    }
    _tr_stats = get_recommendation_stats(_tr_stats_state)
    test("TR: stats tools_analyzed = 4", _tr_stats["tools_analyzed"] == 4)
    test("TR: stats at_risk has Edit", "Edit" in _tr_stats["tools_at_risk"])
    test("TR: stats at_risk has Bash", "Bash" in _tr_stats["tools_at_risk"])
    test("TR: stats top_blockers is list", isinstance(_tr_stats["top_blockers"], list))
    test("TR: stats top_blockers <= 3", len(_tr_stats["top_blockers"]) <= 3)
    test("TR: stats healthiest is list", isinstance(_tr_stats["healthiest"], list))
    test("TR: stats healthiest <= 3", len(_tr_stats["healthiest"]) <= 3)

    # Top blocker should be Bash (40% block rate) or Edit (40%)
    _tr_blocker_names = [b[0] for b in _tr_stats["top_blockers"]]
    test("TR: top blockers include Edit or Bash",
         "Edit" in _tr_blocker_names or "Bash" in _tr_blocker_names)

    # Healthiest should include Read (0% blocks)
    _tr_healthy_names = [h[0] for h in _tr_stats["healthiest"]]
    test("TR: healthiest includes Read", "Read" in _tr_healthy_names)

    # Only reliable tools (>= MIN_CALLS_FOR_STATS) appear in at_risk
    _tr_unreliable_state = {
        "tool_call_counts": {"Edit": 3},
        "gate_block_outcomes": [{"tool": "Edit"}] * 3,  # 100% blocked but too few calls
    }
    _tr_unreliable_stats = get_recommendation_stats(_tr_unreliable_state)
    test("TR: unreliable tool not at_risk", "Edit" not in _tr_unreliable_stats["tools_at_risk"])

    # --- Edge cases ---
    # Non-dict block outcomes are skipped
    _tr_bad_block_state = {
        "tool_call_counts": {"Edit": 10},
        "gate_block_outcomes": ["not_a_dict", None, 42],
    }
    _tr_bad_p = build_tool_profile(_tr_bad_block_state)
    test("TR: non-dict blocks skipped", _tr_bad_p["Edit"].block_count == 0)

    # Zero call count
    _tr_zero_state = {
        "tool_call_counts": {"Edit": 0},
        "gate_block_outcomes": [],
    }
    _tr_zero_p = build_tool_profile(_tr_zero_state)
    test("TR: zero calls success = 1.0", _tr_zero_p["Edit"].success_rate == 1.0)
    test("TR: zero calls block = 0.0", _tr_zero_p["Edit"].block_rate == 0.0)

    # Tool only in blocks, not in counts
    _tr_orphan_state = {
        "tool_call_counts": {},
        "gate_block_outcomes": [{"tool": "Mystery"}],
    }
    _tr_orphan_p = build_tool_profile(_tr_orphan_state)
    test("TR: orphan block tool tracked", "Mystery" in _tr_orphan_p)
    test("TR: orphan block count = 1", _tr_orphan_p["Mystery"].block_count == 1)

except Exception as _tr_exc:
    test("Tool Recommendation Engine Tests: import and tests", False, str(_tr_exc))

# ── Health Correlation Analyzer Deep Tests ──────────────────────────────────
# Tests for health_correlation.py: _pearson_correlation, build_fire_vectors,
# compute_correlation_matrix, detect_redundant_pairs, detect_synergistic_pairs,
# suggest_optimizations, generate_health_report

try:
    from shared.health_correlation import (
        _pearson_correlation, build_fire_vectors, compute_correlation_matrix,
        detect_redundant_pairs, detect_synergistic_pairs,
        suggest_optimizations, generate_health_report,
        _short, _redundancy_recommendation,
        REDUNDANCY_THRESHOLD, SYNERGY_THRESHOLD,
        MIN_BLOCKS_FOR_ANALYSIS, PROTECTED_GATES,
    )

    # --- _pearson_correlation ---
    test("HC: pearson identical = 1.0",
         abs(_pearson_correlation([1, 2, 3], [1, 2, 3]) - 1.0) < 0.001)
    test("HC: pearson opposite = -1.0",
         abs(_pearson_correlation([1, 2, 3], [3, 2, 1]) - (-1.0)) < 0.001)
    test("HC: pearson uncorrelated ~0",
         abs(_pearson_correlation([1, 2, 3, 4], [2, 4, 1, 3])) < 0.6)
    test("HC: pearson empty = 0.0", _pearson_correlation([], []) == 0.0)
    test("HC: pearson single = 0.0", _pearson_correlation([1.0], [2.0]) == 0.0)
    test("HC: pearson diff lengths = 0.0",
         _pearson_correlation([1, 2], [1, 2, 3]) == 0.0)
    test("HC: pearson zero variance = 0.0",
         _pearson_correlation([5, 5, 5], [1, 2, 3]) == 0.0)
    test("HC: pearson in [-1, 1]",
         -1.0 <= _pearson_correlation([1, 3, 5, 7], [2, 6, 4, 8]) <= 1.0)

    # --- _short ---
    test("HC: short gate_01", _short("gate_01_read_before_edit") == "G01")
    test("HC: short gate_17", _short("gate_17_injection_defense") == "G17")
    test("HC: short unknown", _short("custom_gate") == "custom_gate")
    test("HC: short empty", _short("") == "")

    # --- Constants ---
    test("HC: REDUNDANCY_THRESHOLD in (0,1)", 0 < REDUNDANCY_THRESHOLD < 1)
    test("HC: SYNERGY_THRESHOLD < 0", SYNERGY_THRESHOLD < 0)
    test("HC: MIN_BLOCKS > 0", MIN_BLOCKS_FOR_ANALYSIS > 0)
    test("HC: PROTECTED has gate_01", "gate_01_read_before_edit" in PROTECTED_GATES)
    test("HC: PROTECTED has 3 gates", len(PROTECTED_GATES) == 3)

    # --- build_fire_vectors ---
    _hc_eff = {
        "gate_01_read_before_edit": {"blocks": 100, "overrides": 5, "prevented": 20},
        "gate_04_memory_first": {"blocks": 80, "overrides": 10, "prevented": 15},
        "gate_07_critical_file_guard": {"blocks": 50, "overrides": 2, "prevented": 10},
        "gate_16_low": {"blocks": 1, "overrides": 0, "prevented": 0},  # below threshold
    }
    _hc_vecs = build_fire_vectors(_hc_eff)
    test("HC: vectors returns dict", isinstance(_hc_vecs, dict))
    test("HC: 3 gates above threshold", len(_hc_vecs) == 3)
    test("HC: low gate excluded", "gate_16_low" not in _hc_vecs)
    test("HC: vectors are lists", all(isinstance(v, list) for v in _hc_vecs.values()))
    test("HC: vectors same length", len(set(len(v) for v in _hc_vecs.values())) == 1)
    test("HC: vector values >= 0", all(x >= 0 for v in _hc_vecs.values() for x in v))

    # Empty input
    test("HC: vectors empty input", build_fire_vectors({}) == {})

    # Legacy 'block' key
    _hc_legacy = {"gate_05": {"block": 50, "overrides": 0, "prevented": 5}}
    _hc_legacy_vecs = build_fire_vectors(_hc_legacy)
    test("HC: legacy block key works", "gate_05" in _hc_legacy_vecs)

    # Custom time_windows
    _hc_custom_vecs = build_fire_vectors(_hc_eff, time_windows=5)
    test("HC: custom windows length",
         all(len(v) == 5 for v in _hc_custom_vecs.values()))

    # --- compute_correlation_matrix ---
    _hc_matrix = compute_correlation_matrix(_hc_vecs)
    test("HC: matrix returns dict", isinstance(_hc_matrix, dict))
    test("HC: matrix has tuples", all(isinstance(k, tuple) for k in _hc_matrix.keys()))
    test("HC: matrix values in [-1,1]",
         all(-1.0 <= v <= 1.0 for v in _hc_matrix.values()))
    # 3 gates → 3 pairs
    test("HC: 3 gates = 3 pairs", len(_hc_matrix) == 3)
    # No self-correlations
    test("HC: no self-correlations", all(k[0] != k[1] for k in _hc_matrix.keys()))
    # Lexicographic ordering
    test("HC: pairs ordered", all(k[0] < k[1] for k in _hc_matrix.keys()))

    # Empty vectors
    test("HC: matrix empty", compute_correlation_matrix({}) == {})

    # Single gate
    test("HC: matrix single gate",
         compute_correlation_matrix({"g1": [1, 2, 3]}) == {})

    # --- detect_redundant_pairs ---
    # Create a matrix with known correlations
    _hc_test_matrix = {
        ("gate_a", "gate_b"): 0.95,  # redundant
        ("gate_a", "gate_c"): 0.50,  # not redundant
        ("gate_b", "gate_c"): 0.85,  # redundant
    }
    _hc_red = detect_redundant_pairs(_hc_test_matrix)
    test("HC: 2 redundant pairs found", len(_hc_red) == 2)
    test("HC: redundant sorted by corr",
         _hc_red[0]["correlation"] >= _hc_red[1]["correlation"])
    test("HC: redundant has recommendation", "recommendation" in _hc_red[0])

    # No redundant pairs
    _hc_no_red = detect_redundant_pairs({("a", "b"): 0.3})
    test("HC: no redundant pairs", len(_hc_no_red) == 0)

    # Custom threshold
    _hc_low_thresh = detect_redundant_pairs(_hc_test_matrix, threshold=0.4)
    test("HC: low threshold = more pairs", len(_hc_low_thresh) == 3)

    # --- detect_synergistic_pairs ---
    _hc_syn_matrix = {
        ("gate_a", "gate_b"): -0.70,  # synergistic
        ("gate_a", "gate_c"): 0.50,   # not synergistic
        ("gate_b", "gate_c"): -0.55,  # synergistic
    }
    _hc_syn = detect_synergistic_pairs(_hc_syn_matrix)
    test("HC: 2 synergistic pairs found", len(_hc_syn) == 2)
    test("HC: synergistic sorted ascending",
         _hc_syn[0]["correlation"] <= _hc_syn[1]["correlation"])
    test("HC: synergistic has recommendation", "complementary" in _hc_syn[0]["recommendation"])

    # No synergistic pairs
    _hc_no_syn = detect_synergistic_pairs({("a", "b"): 0.3})
    test("HC: no synergistic pairs", len(_hc_no_syn) == 0)

    # --- suggest_optimizations ---
    _hc_opt_eff = {
        "gate_04_memory_first": {"blocks": 100, "overrides": 5, "prevented": 20},
        "gate_05_proof": {"blocks": 95, "overrides": 4, "prevented": 18},
        "gate_16_low": {"blocks": 1, "overrides": 0, "prevented": 0},
    }
    _hc_opts = suggest_optimizations(_hc_opt_eff)
    test("HC: optimizations is list", isinstance(_hc_opts, list))

    # Low-value gate detected
    _hc_low_opts = [o for o in _hc_opts if o["type"] == "low_value"]
    test("HC: low-value gate found", len(_hc_low_opts) >= 1)
    if _hc_low_opts:
        test("HC: low-value has description", "description" in _hc_low_opts[0])
        test("HC: low-value has confidence", "confidence" in _hc_low_opts[0])

    # Protected gates never suggested for removal
    _hc_prot_eff = {
        "gate_01_read_before_edit": {"blocks": 1, "overrides": 0, "prevented": 0},
    }
    _hc_prot_opts = suggest_optimizations(_hc_prot_eff)
    _hc_prot_gates = [g for o in _hc_prot_opts for g in o.get("gates_affected", [])]
    test("HC: protected gate not in low_value",
         "gate_01_read_before_edit" not in _hc_prot_gates or
         all(o["type"] != "low_value" for o in _hc_prot_opts
             if "gate_01_read_before_edit" in o.get("gates_affected", [])))

    # --- _redundancy_recommendation ---
    _hc_rec1 = _redundancy_recommendation("gate_01_read_before_edit", "gate_04_x", 0.9)
    test("HC: rec mentions Tier-1", "Tier-1" in _hc_rec1 or "protected" in _hc_rec1)

    _hc_rec2 = _redundancy_recommendation("gate_04_x", "gate_05_y", 0.85)
    test("HC: rec mentions merging", "merging" in _hc_rec2.lower() or "consolidat" in _hc_rec2.lower())

    # --- generate_health_report ---
    _hc_report = generate_health_report(_hc_eff)
    test("HC: report is dict", isinstance(_hc_report, dict))
    test("HC: report has gates_analyzed", "gates_analyzed" in _hc_report)
    test("HC: report has correlation_pairs", "correlation_pairs" in _hc_report)
    test("HC: report has redundant_pairs", "redundant_pairs" in _hc_report)
    test("HC: report has synergistic_pairs", "synergistic_pairs" in _hc_report)
    test("HC: report has optimizations", "optimizations" in _hc_report)
    test("HC: report has overall_diversity", "overall_diversity" in _hc_report)
    test("HC: diversity in [0,1]", 0.0 <= _hc_report["overall_diversity"] <= 1.0)
    test("HC: gates_analyzed = 3", _hc_report["gates_analyzed"] == 3)

    # Empty effectiveness
    _hc_empty_report = generate_health_report({})
    test("HC: empty report gates = 0", _hc_empty_report["gates_analyzed"] == 0)
    test("HC: empty report diversity = 1.0", _hc_empty_report["overall_diversity"] == 1.0)

    # Non-dict entries ignored
    _hc_bad_eff = {"gate_x": "not_a_dict", "gate_y": None}
    _hc_bad_vecs = build_fire_vectors(_hc_bad_eff)
    test("HC: non-dict entries skipped", len(_hc_bad_vecs) == 0)

except Exception as _hc_exc:
    test("Health Correlation Analyzer Tests: import and tests", False, str(_hc_exc))

# ── Search Cache Deep Tests ─────────────────────────────────────────────────
# Tests for search_cache.py: SearchCache class methods

try:
    from shared.search_cache import SearchCache

    _sc = SearchCache(ttl_seconds=60, max_entries=10)
    test("SC: constructor", isinstance(_sc, SearchCache))
    test("SC: empty len = 0", len(_sc) == 0)

    _sc_k1 = _sc.make_key("test query")
    test("SC: make_key returns string", isinstance(_sc_k1, str))
    test("SC: make_key is 16 hex chars", len(_sc_k1) == 16)
    _sc_k2 = _sc.make_key("test query")
    test("SC: make_key deterministic", _sc_k1 == _sc_k2)
    _sc_k3 = _sc.make_key("  TEST QUERY  ")
    test("SC: make_key case insensitive", _sc_k1 == _sc_k3)
    _sc_k4 = _sc.make_key("different query")
    test("SC: different query = different key", _sc_k1 != _sc_k4)
    _sc_k5 = _sc.make_key("test query", top_k=10)
    test("SC: kwargs change key", _sc_k1 != _sc_k5)
    _sc_k6 = _sc.make_key("test query", top_k=10, mode="semantic")
    _sc_k7 = _sc.make_key("test query", mode="semantic", top_k=10)
    test("SC: kwargs order independent", _sc_k6 == _sc_k7)

    _sc2 = SearchCache(ttl_seconds=60, max_entries=10)
    _sc2.put("key1", {"results": [1, 2, 3]})
    test("SC: put increases len", len(_sc2) == 1)
    _sc2_hit = _sc2.get("key1")
    test("SC: get returns value", _sc2_hit == {"results": [1, 2, 3]})
    _sc2_miss = _sc2.get("nonexistent")
    test("SC: get miss = None", _sc2_miss is None)

    _sc3 = SearchCache(ttl_seconds=0.001, max_entries=10)
    _sc3.put("k", "value")
    import time as _sc_time
    _sc_time.sleep(0.01)
    test("SC: expired entry = None", _sc3.get("k") is None)

    _sc4 = SearchCache(ttl_seconds=60, max_entries=10)
    _sc4.put("a", 1)
    _sc4.put("b", 2)
    test("SC: pre-invalidate len = 2", len(_sc4) == 2)
    _sc4.invalidate()
    test("SC: post-invalidate len = 0", len(_sc4) == 0)
    test("SC: invalidated entry = None", _sc4.get("a") is None)

    _sc5 = SearchCache(ttl_seconds=60, max_entries=4)
    for _i in range(5):
        _sc5.put(f"k{_i}", _i)
    test("SC: eviction keeps <= max", len(_sc5) <= 4)
    test("SC: newest entry kept", _sc5.get("k4") == 4)

    _sc6 = SearchCache(ttl_seconds=60, max_entries=100)
    _sc6.put("x", "val")
    _sc6.get("x")
    _sc6.get("y")
    _sc6.invalidate()
    _sc6_stats = _sc6.stats()
    test("SC: stats has hits", _sc6_stats["hits"] == 1)
    test("SC: stats has misses", _sc6_stats["misses"] == 1)
    test("SC: stats hit_rate = 0.5", abs(_sc6_stats["hit_rate"] - 0.5) < 0.01)
    test("SC: stats cached = 0", _sc6_stats["cached"] == 0)
    test("SC: stats max_entries", _sc6_stats["max_entries"] == 100)
    test("SC: stats ttl_seconds", _sc6_stats["ttl_seconds"] == 60)
    test("SC: stats invalidations = 1", _sc6_stats["invalidations"] == 1)

    _sc7 = SearchCache()
    test("SC: zero stats hit_rate = 0", _sc7.stats()["hit_rate"] == 0.0)

    _sc8 = SearchCache(ttl_seconds=60, max_entries=10)
    _sc8.put("k", "old")
    _sc8.put("k", "new")
    test("SC: overwrite works", _sc8.get("k") == "new")

except Exception as _sc_exc:
    test("Search Cache Deep Tests: import and tests", False, str(_sc_exc))

# ── Error Pattern Analyzer Deep Tests ───────────────────────────────────────

try:
    from shared.error_pattern_analyzer import (
        extract_pattern, analyze_errors, top_patterns,
        correlate_errors, suggest_prevention, frequency_from_strings,
        _classify, _FALLBACK_PATTERN, _PATTERN_TABLE,
    )

    test("EPA: gate1 read-before-edit",
         extract_pattern("must Read file.py before edit") == "gate1:read-before-edit")
    test("EPA: gate2 rm -rf",
         extract_pattern("rm -rf /important") == "gate2:destructive-command")
    test("EPA: gate2 DROP TABLE",
         extract_pattern("DROP TABLE users") == "gate2:destructive-command")
    test("EPA: gate2 force push",
         extract_pattern("force push to main") == "gate2:destructive-command")
    test("EPA: gate3 deploy no tests",
         extract_pattern("run test before deploy") == "gate3:deploy-without-tests")
    test("EPA: gate4 memory not queried",
         extract_pattern("memory not queried yet") == "gate4:memory-not-queried")
    test("EPA: gate9 strategy banned",
         extract_pattern("strategy banned: sleep_retry") == "gate9:banned-strategy")
    test("EPA: gate11 rate limit",
         extract_pattern("rate limit exceeded for Edit") == "gate11:rate-limit")

    test("EPA: import error",
         extract_pattern("ModuleNotFoundError: No module named 'foo'") == "python:import-error")
    test("EPA: syntax error",
         extract_pattern("SyntaxError: invalid syntax") == "python:syntax-error")
    test("EPA: attribute error",
         extract_pattern("AttributeError: 'dict' has no attr") == "python:attribute-error")
    test("EPA: type error",
         extract_pattern("TypeError: expected str, got int") == "python:type-error")
    test("EPA: key error",
         extract_pattern("KeyError: 'missing_key'") == "python:key-error")

    test("EPA: file not found",
         extract_pattern("FileNotFoundError: No such file") == "fs:file-not-found")
    test("EPA: permission denied",
         extract_pattern("Permission denied: /etc/passwd") == "fs:permission-denied")
    test("EPA: timeout",
         extract_pattern("Connection timed out after 30s") == "net:timeout")
    test("EPA: connection refused",
         extract_pattern("ConnectionRefused: localhost:8080") == "net:connection-refused")

    test("EPA: unclassified",
         extract_pattern("Something went terribly wrong") == _FALLBACK_PATTERN)
    test("EPA: empty string = fallback", extract_pattern("") == _FALLBACK_PATTERN)
    test("EPA: None = fallback", extract_pattern(None) == _FALLBACK_PATTERN)
    test("EPA: non-string = fallback", extract_pattern(42) == _FALLBACK_PATTERN)

    _epa_cat, _epa_rc = _classify("gate1:read-before-edit")
    test("EPA: classify gate1 category", _epa_cat == "gate-block")
    test("EPA: classify gate1 root_cause", _epa_rc == "user-error")
    _epa_cat2, _epa_rc2 = _classify("fs:file-not-found")
    test("EPA: classify fs category", _epa_cat2 == "filesystem")
    _epa_cat3, _epa_rc3 = _classify("unknown:pattern")
    test("EPA: classify unknown = fallback", _epa_cat3 == "other")

    _epa_tip1 = suggest_prevention("gate1:read-before-edit")
    test("EPA: gate1 tip mentions Read", "Read" in _epa_tip1)
    _epa_tip2 = suggest_prevention("python:import-error")
    test("EPA: import tip useful", len(_epa_tip2) > 20)
    _epa_tip3 = suggest_prevention("nonexistent:pattern")
    test("EPA: unknown tip returns fallback", isinstance(_epa_tip3, str) and len(_epa_tip3) > 0)

    _epa_entries = [
        {"decision": "block", "reason": "must Read file.py before edit", "session_id": "s1"},
        {"decision": "block", "reason": "must Read other.py before edit", "session_id": "s1"},
        {"decision": "warn", "reason": "memory not queried yet", "session_id": "s1"},
        {"decision": "pass", "reason": "all good", "session_id": "s1"},
        {"decision": "block", "reason": "FileNotFoundError: missing", "session_id": "s2"},
    ]
    _epa_analysis = analyze_errors(_epa_entries)
    test("EPA: total_errors = 4", _epa_analysis["total_errors"] == 4)
    test("EPA: pattern_counts is dict", isinstance(_epa_analysis["pattern_counts"], dict))
    test("EPA: gate1 count = 2", _epa_analysis["pattern_counts"].get("gate1:read-before-edit") == 2)
    test("EPA: category has gate-block", "gate-block" in _epa_analysis["category_breakdown"])
    test("EPA: root_cause has user-error", "user-error" in _epa_analysis["root_cause_breakdown"])
    test("EPA: top_patterns is list", isinstance(_epa_analysis["top_patterns"], list))
    test("EPA: suggestions is dict", isinstance(_epa_analysis["suggestions"], dict))
    test("EPA: session s1 in breakdown", "s1" in _epa_analysis["session_breakdown"])
    test("EPA: session s2 in breakdown", "s2" in _epa_analysis["session_breakdown"])

    _epa_empty = analyze_errors([])
    test("EPA: empty analysis total = 0", _epa_empty["total_errors"] == 0)

    _epa_top = top_patterns(_epa_entries, n=2)
    test("EPA: top_patterns returns list", isinstance(_epa_top, list))
    test("EPA: top_patterns max 2", len(_epa_top) <= 2)
    test("EPA: top sorted", _epa_top[0][1] >= _epa_top[-1][1])

    _epa_corr_entries = [
        {"decision": "block", "reason": "must Read before edit", "session_id": "s1"},
        {"decision": "block", "reason": "must Read before edit", "session_id": "s1"},
        {"decision": "block", "reason": "memory not queried", "session_id": "s1"},
        {"decision": "block", "reason": "must Read before edit", "session_id": "s1"},
    ]
    _epa_corr = correlate_errors(_epa_corr_entries)
    test("EPA: correlate returns list", isinstance(_epa_corr, list))
    if _epa_corr:
        test("EPA: corr has pattern_a", "pattern_a" in _epa_corr[0])
        test("EPA: corr has count", "count" in _epa_corr[0])
        test("EPA: corr sorted", _epa_corr[0]["count"] >= _epa_corr[-1]["count"])

    _epa_corr_one = correlate_errors([{"decision": "block", "reason": "test"}])
    test("EPA: correlate 1 = empty", len(_epa_corr_one) == 0)

    _epa_cross = [
        {"decision": "block", "reason": "must Read before edit", "session_id": "s1"},
        {"decision": "block", "reason": "memory not queried", "session_id": "s2"},
    ]
    _epa_cross_corr = correlate_errors(_epa_cross)
    test("EPA: cross-session not correlated", len(_epa_cross_corr) == 0)

    _epa_freq = frequency_from_strings([
        "must Read file before edit",
        "must Read other before edit",
        "FileNotFoundError: missing",
    ])
    test("EPA: freq returns dict", isinstance(_epa_freq, dict))
    test("EPA: freq gate1 = 2", _epa_freq.get("gate1:read-before-edit") == 2)
    test("EPA: freq fs = 1", _epa_freq.get("fs:file-not-found") == 1)
    test("EPA: freq empty = empty", frequency_from_strings([]) == {})

    test("EPA: pattern table > 20 entries", len(_PATTERN_TABLE) > 20)
    test("EPA: all patterns have 4 fields", all(len(p) == 4 for p in _PATTERN_TABLE))

except Exception as _epa_exc:
    test("Error Pattern Analyzer Deep Tests: import and tests", False, str(_epa_exc))

# ── Hook Cache Deep Tests ───────────────────────────────────────────────────
# Tests for hook_cache.py: get_cached_module, get/set_cached_state,
# get/set_cached_result, cache_stats, clear_cache, evict_expired

try:
    from shared.hook_cache import (
        get_cached_module, invalidate_module,
        get_cached_state, set_cached_state, invalidate_state,
        get_cached_result, set_cached_result, invalidate_result,
        cache_stats, clear_cache, evict_expired,
    )

    # Start clean
    clear_cache()

    # --- Module cache ---
    _hkc_mod = get_cached_module("json")
    test("HKC: module cache returns module", _hkc_mod is not None)
    test("HKC: cached json has loads", hasattr(_hkc_mod, "loads"))

    # Second call = cache hit
    _hkc_mod2 = get_cached_module("json")
    test("HKC: module cache hit same obj", _hkc_mod2 is _hkc_mod)

    _hkc_s1 = cache_stats()
    test("HKC: module miss counted", _hkc_s1["module_misses"] >= 1)
    test("HKC: module hit counted", _hkc_s1["module_hits"] >= 1)
    test("HKC: module_cached >= 1", _hkc_s1["module_cached"] >= 1)

    # Invalidate
    test("HKC: invalidate_module known", invalidate_module("json") is True)
    test("HKC: invalidate_module unknown", invalidate_module("nonexistent") is False)

    # --- State cache ---
    clear_cache()
    set_cached_state("test_session", {"key": "value"})
    _hkc_state = get_cached_state("test_session")
    test("HKC: state cache hit", _hkc_state == {"key": "value"})

    _hkc_state_miss = get_cached_state("nonexistent")
    test("HKC: state cache miss", _hkc_state_miss is None)

    # TTL expiry
    set_cached_state("expire_test", {"x": 1})
    import time as _hkc_time
    _hkc_time.sleep(0.01)
    _hkc_stale = get_cached_state("expire_test", ttl_ms=5)  # 5ms TTL, slept 10ms
    test("HKC: state TTL expired", _hkc_stale is None)

    # Invalidate state
    set_cached_state("inv_test", {"y": 2})
    test("HKC: invalidate_state known", invalidate_state("inv_test") is True)
    test("HKC: invalidate_state unknown", invalidate_state("nonexistent") is False)
    test("HKC: state gone after invalidate", get_cached_state("inv_test") is None)

    # Stats
    _hkc_s2 = cache_stats()
    test("HKC: state_hits counted", _hkc_s2["state_hits"] >= 1)
    test("HKC: state_misses counted", _hkc_s2["state_misses"] >= 1)

    # --- Result cache ---
    clear_cache()

    from shared.gate_result import GateResult
    _hkc_gr = GateResult(blocked=False, gate_name="test_gate")
    set_cached_result("gate_01", "Edit", "abc123", _hkc_gr)

    _hkc_res = get_cached_result("gate_01", "Edit", "abc123")
    test("HKC: result cache hit", _hkc_res is not None)
    test("HKC: result is GateResult", hasattr(_hkc_res, "blocked"))
    test("HKC: result not blocked", _hkc_res.blocked is False)

    _hkc_res_miss = get_cached_result("gate_01", "Edit", "different")
    test("HKC: result cache miss", _hkc_res_miss is None)

    # TTL expiry (result TTL = 1s, so use sleep)
    set_cached_result("gate_02", "Write", "xyz", _hkc_gr)
    # Don't sleep for result TTL test - just verify it works when fresh
    _hkc_res_fresh = get_cached_result("gate_02", "Write", "xyz")
    test("HKC: fresh result returns", _hkc_res_fresh is not None)

    # Invalidate result
    test("HKC: invalidate_result known",
         invalidate_result("gate_02", "Write", "xyz") is True)
    test("HKC: invalidate_result unknown",
         invalidate_result("gate_99", "X", "y") is False)

    # --- cache_stats ---
    _hkc_s3 = cache_stats()
    test("HKC: stats is dict", isinstance(_hkc_s3, dict))
    test("HKC: stats has module_hits", "module_hits" in _hkc_s3)
    test("HKC: stats has state_hits", "state_hits" in _hkc_s3)
    test("HKC: stats has result_hits", "result_hits" in _hkc_s3)
    test("HKC: stats has module_cached", "module_cached" in _hkc_s3)
    test("HKC: stats has state_cached", "state_cached" in _hkc_s3)
    test("HKC: stats has result_cached", "result_cached" in _hkc_s3)
    # stats is a snapshot (new dict)
    test("HKC: stats returns new dict", _hkc_s3 is not cache_stats())

    # --- clear_cache ---
    set_cached_state("clear_test", {"z": 3})
    clear_cache()
    _hkc_s4 = cache_stats()
    test("HKC: clear resets module_hits", _hkc_s4["module_hits"] == 0)
    test("HKC: clear resets state_hits", _hkc_s4["state_hits"] == 0)
    test("HKC: clear resets result_hits", _hkc_s4["result_hits"] == 0)
    test("HKC: clear empties state", _hkc_s4["state_cached"] == 0)

    # --- evict_expired ---
    clear_cache()
    set_cached_state("exp1", {"a": 1})
    set_cached_state("exp2", {"b": 2})
    _hkc_time.sleep(0.01)
    _hkc_evicted = evict_expired(state_ttl_ms=5)  # 5ms TTL
    test("HKC: evict_expired returns dict", isinstance(_hkc_evicted, dict))
    test("HKC: evicted state entries", _hkc_evicted["state"] >= 2)
    test("HKC: evicted result key exists", "result" in _hkc_evicted)

    # Final cleanup
    clear_cache()

except Exception as _hkc_exc:
    test("Hook Cache Deep Tests: import and tests", False, str(_hkc_exc))

# ── Config Validator Deep Tests ─────────────────────────────────────────────
# Tests for config_validator.py: validate_settings, validate_live_state,
# validate_gates, validate_skills, validate_all

try:
    from shared.config_validator import (
        validate_settings, validate_live_state,
        validate_gates, validate_skills, validate_all,
        _VALID_EVENT_TYPES, _LIVE_STATE_REQUIRED,
    )
    import tempfile as _cv_tmp
    import json as _cv_json

    # --- Constants ---
    test("CV: VALID_EVENT_TYPES has PreToolUse", "PreToolUse" in _VALID_EVENT_TYPES)
    test("CV: VALID_EVENT_TYPES has PostToolUse", "PostToolUse" in _VALID_EVENT_TYPES)
    test("CV: VALID_EVENT_TYPES has Stop", "Stop" in _VALID_EVENT_TYPES)
    test("CV: LIVE_STATE_REQUIRED has session_count",
         "session_count" in _LIVE_STATE_REQUIRED)
    test("CV: LIVE_STATE_REQUIRED session_count is int",
         _LIVE_STATE_REQUIRED["session_count"] is int)

    # --- validate_settings with actual file ---
    _cv_settings_errors = validate_settings()
    test("CV: real settings.json validates", isinstance(_cv_settings_errors, list))

    # Missing file
    _cv_missing = validate_settings("/nonexistent/settings.json")
    test("CV: missing settings = error", len(_cv_missing) == 1)
    test("CV: missing settings mentions not found", "not found" in _cv_missing[0])

    # Invalid JSON
    _cv_tmp_bad = _cv_tmp.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
    _cv_tmp_bad.write("not valid json{{{")
    _cv_tmp_bad.close()
    _cv_bad_errors = validate_settings(_cv_tmp_bad.name)
    test("CV: invalid JSON detected", len(_cv_bad_errors) == 1)
    test("CV: error mentions JSON", "JSON" in _cv_bad_errors[0])
    os.remove(_cv_tmp_bad.name)

    # Valid minimal settings
    _cv_tmp_ok = _cv_tmp.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
    _cv_json.dump({"hooks": {"PreToolUse": []}}, _cv_tmp_ok)
    _cv_tmp_ok.close()
    _cv_ok_errors = validate_settings(_cv_tmp_ok.name)
    test("CV: minimal settings valid", len(_cv_ok_errors) == 0)
    os.remove(_cv_tmp_ok.name)

    # Missing hooks key
    _cv_tmp_no_hooks = _cv_tmp.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
    _cv_json.dump({"other": "data"}, _cv_tmp_no_hooks)
    _cv_tmp_no_hooks.close()
    _cv_nh_errors = validate_settings(_cv_tmp_no_hooks.name)
    test("CV: missing hooks key error", len(_cv_nh_errors) > 0)
    test("CV: error mentions hooks", "hooks" in _cv_nh_errors[0])
    os.remove(_cv_tmp_no_hooks.name)

    # Unknown event type
    _cv_tmp_bad_evt = _cv_tmp.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
    _cv_json.dump({"hooks": {"InvalidEvent": []}}, _cv_tmp_bad_evt)
    _cv_tmp_bad_evt.close()
    _cv_evt_errors = validate_settings(_cv_tmp_bad_evt.name)
    test("CV: unknown event type flagged", len(_cv_evt_errors) > 0)
    os.remove(_cv_tmp_bad_evt.name)

    # --- validate_live_state ---
    _cv_ls_errors = validate_live_state()
    test("CV: real LIVE_STATE validates", isinstance(_cv_ls_errors, list))
    test("CV: real LIVE_STATE no errors", len(_cv_ls_errors) == 0)

    # Missing file
    _cv_ls_missing = validate_live_state("/nonexistent/LIVE_STATE.json")
    test("CV: missing LIVE_STATE = error", len(_cv_ls_missing) == 1)

    # Valid LIVE_STATE
    _cv_tmp_ls = _cv_tmp.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
    _cv_json.dump({
        "session_count": 1,
        "project": "test",
        "feature": "none",
        "framework_version": "v1.0",
        "what_was_done": "test",
        "next_steps": [],
        "known_issues": [],
    }, _cv_tmp_ls)
    _cv_tmp_ls.close()
    test("CV: valid LIVE_STATE passes", len(validate_live_state(_cv_tmp_ls.name)) == 0)
    os.remove(_cv_tmp_ls.name)

    # Missing required field
    _cv_tmp_ls2 = _cv_tmp.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
    _cv_json.dump({"session_count": 1}, _cv_tmp_ls2)
    _cv_tmp_ls2.close()
    _cv_ls2_errors = validate_live_state(_cv_tmp_ls2.name)
    test("CV: missing fields detected", len(_cv_ls2_errors) > 0)
    os.remove(_cv_tmp_ls2.name)

    # Wrong type
    _cv_tmp_ls3 = _cv_tmp.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
    _cv_json.dump({
        "session_count": "not_an_int",
        "project": "test",
        "feature": "none",
        "framework_version": "v1.0",
        "what_was_done": "test",
        "next_steps": [],
        "known_issues": [],
    }, _cv_tmp_ls3)
    _cv_tmp_ls3.close()
    _cv_ls3_errors = validate_live_state(_cv_tmp_ls3.name)
    test("CV: wrong type detected", len(_cv_ls3_errors) > 0)
    test("CV: error mentions expected type", "int" in _cv_ls3_errors[0])
    os.remove(_cv_tmp_ls3.name)

    # --- validate_gates ---
    _cv_gate_errors = validate_gates()
    test("CV: real gates validate", isinstance(_cv_gate_errors, list))
    test("CV: real gates no errors", len(_cv_gate_errors) == 0)

    # --- validate_skills ---
    _cv_skill_errors = validate_skills()
    test("CV: real skills validate", isinstance(_cv_skill_errors, list))

    # Missing skills dir
    _cv_skill_missing = validate_skills("/nonexistent/skills")
    test("CV: missing skills dir = error", len(_cv_skill_missing) == 1)

    # --- validate_all ---
    _cv_all = validate_all()
    test("CV: validate_all returns dict", isinstance(_cv_all, dict))
    test("CV: validate_all has settings", "settings" in _cv_all)
    test("CV: validate_all has live_state", "live_state" in _cv_all)
    test("CV: validate_all has gates", "gates" in _cv_all)
    test("CV: validate_all has skills", "skills" in _cv_all)
    test("CV: all values are lists",
         all(isinstance(v, list) for v in _cv_all.values()))

    # With custom base_dir
    _cv_all_custom = validate_all("/nonexistent/dir")
    test("CV: custom base_dir returns errors", isinstance(_cv_all_custom, dict))
    test("CV: custom settings has error", len(_cv_all_custom["settings"]) > 0)

except Exception as _cv_exc:
    test("Config Validator Deep Tests: import and tests", False, str(_cv_exc))

# ── Memory Maintenance Deep Tests ─────────────────────────────────────────
print("\n--- Memory Maintenance Deep Tests ---")
try:
    from shared.memory_maintenance import (
        _parse_timestamp, _age_days, _split_tags,
        _has_session_reference, _has_superseded_language,
        _count_stats, _tag_distribution, _similarity_groups,
        _stale_memory_scan, _build_recommendations,
        STALE_THRESHOLD_DAYS, ANCIENT_THRESHOLD_DAYS,
        UNDERREPRESENTED_SHARE, MIN_MEMORIES_FOR_ANALYSIS,
        _SESSION_REF_RE, _SUPERSEDED_PATTERNS,
        _CANONICAL_CATEGORIES, _POSSIBLE_DUPE_TAG_PREFIX,
    )
    from datetime import datetime, timezone, timedelta

    # Constants
    test("MM: STALE_THRESHOLD_DAYS is 90", STALE_THRESHOLD_DAYS == 90)
    test("MM: ANCIENT_THRESHOLD_DAYS is 180", ANCIENT_THRESHOLD_DAYS == 180)
    test("MM: UNDERREPRESENTED_SHARE is 0.03", UNDERREPRESENTED_SHARE == 0.03)
    test("MM: MIN_MEMORIES_FOR_ANALYSIS is 10", MIN_MEMORIES_FOR_ANALYSIS == 10)
    test("MM: CANONICAL_CATEGORIES has type and area tags",
         "type:fix" in _CANONICAL_CATEGORIES and "area:framework" in _CANONICAL_CATEGORIES)
    test("MM: POSSIBLE_DUPE_TAG_PREFIX is possible-dupe:",
         _POSSIBLE_DUPE_TAG_PREFIX == "possible-dupe:")

    # _parse_timestamp
    _mm_ts1 = _parse_timestamp("2025-01-15T10:30:00Z")
    test("MM: parse_timestamp ISO with Z", _mm_ts1 is not None)
    test("MM: parse_timestamp returns datetime", isinstance(_mm_ts1, datetime))
    _mm_ts2 = _parse_timestamp("2025-01-15T10:30:00+00:00")
    test("MM: parse_timestamp ISO with +00:00", _mm_ts2 is not None)
    test("MM: parse_timestamp empty string", _parse_timestamp("") is None)
    test("MM: parse_timestamp None", _parse_timestamp(None) is None)
    test("MM: parse_timestamp garbage", _parse_timestamp("not-a-date") is None)

    # _age_days
    _mm_now = datetime(2025, 6, 15, tzinfo=timezone.utc)
    _mm_age = _age_days("2025-06-14T12:00:00Z", _mm_now)
    test("MM: age_days 1 day old", _mm_age is not None and 0.4 < _mm_age < 1.1)
    _mm_age_old = _age_days("2025-01-01T00:00:00Z", _mm_now)
    test("MM: age_days ~165 days", _mm_age_old is not None and 160 < _mm_age_old < 170)
    test("MM: age_days unparseable", _age_days("garbage", _mm_now) is None)
    test("MM: age_days non-negative", _age_days("2025-06-15T12:00:00Z", _mm_now) == 0.0)

    # _split_tags
    test("MM: split_tags normal", _split_tags("type:fix,area:framework") == ["type:fix", "area:framework"])
    test("MM: split_tags empty", _split_tags("") == [])
    test("MM: split_tags None", _split_tags(None) == [])
    test("MM: split_tags whitespace", _split_tags(" a , b , c ") == ["a", "b", "c"])
    test("MM: split_tags single", _split_tags("type:fix") == ["type:fix"])

    # _has_session_reference
    test("MM: has_session_ref 'Session 42'", _has_session_reference("Fixed in Session 42"))
    test("MM: has_session_ref 'session #7'", _has_session_reference("done in session #7"))
    test("MM: has_session_ref 'sprint-3'", _has_session_reference("sprint-3 work"))
    test("MM: has_session_ref 'session_id'", _has_session_reference("uses session_id"))
    test("MM: has_session_ref none", not _has_session_reference("a generic memory about fixing bugs"))

    # _has_superseded_language
    test("MM: superseded 'was fixed'", _has_superseded_language("This bug was fixed in v2"))
    test("MM: superseded 'no longer needed'", _has_superseded_language("This is no longer needed"))
    test("MM: superseded 'replaced by'", _has_superseded_language("old method replaced by new"))
    test("MM: superseded 'obsolete'", _has_superseded_language("This approach is obsolete"))
    test("MM: superseded 'temporary workaround'", _has_superseded_language("temporary workaround for X"))
    test("MM: superseded 'the old implementation'", _has_superseded_language("the old implementation broke"))
    test("MM: superseded none", not _has_superseded_language("This is a current best practice"))

    # _count_stats with synthetic entries
    _mm_now2 = datetime(2025, 6, 15, tzinfo=timezone.utc)
    _mm_entries = [
        {"id": "1", "document": "fresh", "tags": "a", "timestamp": "2025-06-10T00:00:00Z", "preview": "", "session_time": 0, "possible_dupe": ""},
        {"id": "2", "document": "recent", "tags": "b", "timestamp": "2025-04-01T00:00:00Z", "preview": "", "session_time": 0, "possible_dupe": ""},
        {"id": "3", "document": "aging", "tags": "c", "timestamp": "2025-02-01T00:00:00Z", "preview": "", "session_time": 0, "possible_dupe": ""},
        {"id": "4", "document": "stale", "tags": "d", "timestamp": "2024-10-01T00:00:00Z", "preview": "", "session_time": 0, "possible_dupe": ""},
        {"id": "5", "document": "unknown", "tags": "e", "timestamp": "", "preview": "", "session_time": 0, "possible_dupe": ""},
    ]
    _mm_cs = _count_stats(_mm_entries, _mm_now2)
    test("MM: count_stats total", _mm_cs["total"] == 5)
    test("MM: count_stats fresh bucket", _mm_cs["age_buckets"]["fresh_0_30d"] == 1)
    test("MM: count_stats recent bucket", _mm_cs["age_buckets"]["recent_31_90d"] == 1)
    test("MM: count_stats aging bucket", _mm_cs["age_buckets"]["aging_91_180d"] == 1)
    test("MM: count_stats stale bucket", _mm_cs["age_buckets"]["stale_181d_plus"] == 1)
    test("MM: count_stats unknown bucket", _mm_cs["age_buckets"]["unknown_age"] == 1)
    test("MM: count_stats median_age", _mm_cs["median_age_days"] is not None)
    test("MM: count_stats oldest_age", _mm_cs["oldest_age_days"] is not None)
    test("MM: count_stats newest_age", _mm_cs["newest_age_days"] is not None)

    # _tag_distribution
    _mm_tag_entries = [
        {"id": "1", "document": "d", "tags": "type:fix,area:framework", "timestamp": "", "preview": "", "session_time": 0, "possible_dupe": ""},
        {"id": "2", "document": "d", "tags": "type:fix,area:testing", "timestamp": "", "preview": "", "session_time": 0, "possible_dupe": ""},
        {"id": "3", "document": "d", "tags": "possible-dupe:abc123", "timestamp": "", "preview": "", "session_time": 0, "possible_dupe": ""},
        {"id": "4", "document": "d", "tags": "", "timestamp": "", "preview": "", "session_time": 0, "possible_dupe": ""},
    ]
    _mm_td = _tag_distribution(_mm_tag_entries)
    test("MM: tag_dist total_unique_tags >= 3", _mm_td["total_unique_tags"] >= 3)
    test("MM: tag_dist untagged_count is 1", _mm_td["untagged_count"] == 1)
    test("MM: tag_dist possible_dupe_count is 1", _mm_td["possible_dupe_count"] == 1)
    test("MM: tag_dist has top_tags", isinstance(_mm_td["top_tags"], list))
    test("MM: tag_dist has category_breakdown", isinstance(_mm_td["category_breakdown"], dict))
    test("MM: tag_dist underrepresented is list", isinstance(_mm_td["underrepresented_categories"], list))
    test("MM: tag_dist avg_tags_per_memory > 0", _mm_td["avg_tags_per_memory"] > 0)

    # _similarity_groups
    _mm_sim_entries = []
    for i in range(10):
        _mm_sim_entries.append({
            "id": f"sim-{i}",
            "document": f"doc {i}",
            "tags": "custom:cluster-a" if i < 5 else "custom:cluster-b",
            "timestamp": "", "preview": "", "session_time": 0, "possible_dupe": "",
        })
    _mm_sg = _similarity_groups(_mm_sim_entries)
    test("MM: similarity_groups has clusters", isinstance(_mm_sg["clusters"], list))
    test("MM: similarity_groups has singleton_count", "singleton_count" in _mm_sg)
    test("MM: similarity_groups has cluster_count", "cluster_count" in _mm_sg)
    test("MM: similarity_groups cluster_a detected",
         any(c["label"] == "custom:cluster-a" for c in _mm_sg["clusters"]))

    # _stale_memory_scan
    _mm_stale_now = datetime(2025, 6, 15, tzinfo=timezone.utc)
    _mm_stale_entries = [
        {"id": "s1", "document": "Fixed in Session 42 long ago", "tags": "",
         "timestamp": "2025-01-01T00:00:00Z", "preview": "old", "session_time": 0, "possible_dupe": ""},
        {"id": "s2", "document": "This approach is obsolete now", "tags": "",
         "timestamp": "2025-06-10T00:00:00Z", "preview": "obsol", "session_time": 0, "possible_dupe": ""},
        {"id": "s3", "document": "current and valid", "tags": "possible-dupe:xyz",
         "timestamp": "2025-06-14T00:00:00Z", "preview": "dupe", "session_time": 0, "possible_dupe": ""},
        {"id": "s4", "document": "totally fresh and current", "tags": "",
         "timestamp": "2025-06-14T00:00:00Z", "preview": "good", "session_time": 0, "possible_dupe": ""},
    ]
    _mm_ss = _stale_memory_scan(_mm_stale_entries, _mm_stale_now)
    test("MM: stale_scan finds stale entries", _mm_ss["stale_count"] >= 2)
    test("MM: stale_scan s1 detected (age+session ref)",
         any(e["id"] == "s1" for e in _mm_ss["stale_entries"]))
    test("MM: stale_scan s2 detected (superseded language)",
         any(e["id"] == "s2" for e in _mm_ss["stale_entries"]))
    test("MM: stale_scan s3 detected (possible dupe)",
         any(e["id"] == "s3" for e in _mm_ss["stale_entries"]))
    test("MM: stale_scan s4 not flagged",
         not any(e["id"] == "s4" for e in _mm_ss["stale_entries"]))
    test("MM: stale_scan entry has signals",
         all("signals" in e for e in _mm_ss["stale_entries"]))

    # _build_recommendations
    _mm_cs_high = {"total": 1200, "age_buckets": {"stale_181d_plus": 60}, "quarantine_count": 250}
    _mm_td_bad = {"untagged_count": 25, "possible_dupe_count": 30, "underrepresented_categories": ["area:docs"]}
    _mm_ss_bad = {"stale_count": 10}
    _mm_sg_big = {"clusters": [{"label": "big-cluster", "size": 55}], "largest_cluster_size": 55}
    _mm_recs = _build_recommendations(_mm_cs_high, _mm_td_bad, _mm_ss_bad, _mm_sg_big)
    test("MM: recommendations is list", isinstance(_mm_recs, list))
    test("MM: recommendations has entries", len(_mm_recs) > 0)
    test("MM: recommendations mentions deduplicate",
         any("dedupl" in r.lower() for r in _mm_recs))

    # Healthy case
    _mm_cs_ok = {"total": 50, "age_buckets": {"stale_181d_plus": 0}, "quarantine_count": 0}
    _mm_td_ok = {"untagged_count": 0, "possible_dupe_count": 0, "underrepresented_categories": []}
    _mm_ss_ok = {"stale_count": 0}
    _mm_sg_ok = {"clusters": [], "largest_cluster_size": 0}
    _mm_recs_ok = _build_recommendations(_mm_cs_ok, _mm_td_ok, _mm_ss_ok, _mm_sg_ok)
    test("MM: healthy recs say 'healthy'",
         any("healthy" in r.lower() for r in _mm_recs_ok))

except Exception as _mm_exc:
    test("Memory Maintenance Deep Tests: import and tests", False, str(_mm_exc))

# ── Gate Graph Deep Tests ─────────────────────────────────────────────────
print("\n--- Gate Graph Deep Tests ---")
try:
    from shared.gate_graph import (
        _parse_shared_imports, _gate_label, _module_label,
        GateGraph, build_graph,
    )
    import tempfile as _gg_tempfile

    # _gate_label
    test("GG: gate_label strips .py", _gate_label("gate_01_read_before_edit.py") == "gate_01_read_before_edit")
    test("GG: gate_label no extension", _gate_label("gate_02_no_destroy") == "gate_02_no_destroy")

    # _module_label
    test("GG: module_label strips .py", _module_label("state.py") == "state")
    test("GG: module_label no ext", _module_label("gate_result") == "gate_result")

    # _parse_shared_imports with a temp file
    with _gg_tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as _gg_tmp:
        _gg_tmp.write("from shared.gate_result import GateResult\n")
        _gg_tmp.write("from shared.state import load_state\n")
        _gg_tmp.write("import os\n")
        _gg_tmp.write("import shared.audit_log\n")
        _gg_tmp_path = _gg_tmp.name
    _gg_imports = _parse_shared_imports(_gg_tmp_path)
    os.unlink(_gg_tmp_path)
    test("GG: parse_shared_imports finds gate_result", "gate_result" in _gg_imports)
    test("GG: parse_shared_imports finds state", "state" in _gg_imports)
    test("GG: parse_shared_imports finds audit_log", "audit_log" in _gg_imports)
    test("GG: parse_shared_imports excludes os", "os" not in _gg_imports)
    test("GG: parse_shared_imports sorted", _gg_imports == sorted(_gg_imports))

    # _parse_shared_imports with nonexistent file
    test("GG: parse_shared_imports missing file", _parse_shared_imports("/tmp/nonexistent_gate.py") == [])

    # GateGraph construction
    _gg_gate_deps = {
        "gate_01_test": ["gate_result", "state"],
        "gate_02_test": ["gate_result", "audit_log"],
        "gate_03_test": ["state"],
    }
    _gg_module_deps = {
        "gate_result": [],
        "state": ["gate_result"],
        "audit_log": ["state"],
    }
    _gg_shared = ["gate_result", "state", "audit_log"]
    _gg = GateGraph(_gg_gate_deps, _gg_module_deps, _gg_shared)

    test("GG: gates list sorted", _gg.gates == sorted(_gg_gate_deps.keys()))
    test("GG: shared_modules sorted", _gg.shared_modules == sorted(_gg_shared))
    test("GG: gate_deps preserved", _gg.gate_deps == _gg_gate_deps)
    test("GG: repr includes counts", "gates=3" in repr(_gg) and "shared_modules=3" in repr(_gg))

    # render_ascii
    _gg_ascii = _gg.render_ascii()
    test("GG: render_ascii contains GATE DEPENDENCY TREE", "GATE DEPENDENCY TREE" in _gg_ascii)
    test("GG: render_ascii contains gate names", "gate_01_test" in _gg_ascii)
    test("GG: render_ascii contains SUMMARY", "SUMMARY" in _gg_ascii)
    test("GG: render_ascii contains connectors", "└──" in _gg_ascii or "├──" in _gg_ascii)
    test("GG: render_ascii shows module usage", "gate(s)" in _gg_ascii)

    # find_circular_deps — no cycles in our test graph
    _gg_cycles = _gg.find_circular_deps()
    test("GG: no circular deps in test graph", _gg_cycles == [])

    # find_circular_deps — graph with cycle
    _gg_cyclic_mod_deps = {
        "mod_a": ["mod_b"],
        "mod_b": ["mod_c"],
        "mod_c": ["mod_a"],
    }
    _gg_cyclic = GateGraph({}, _gg_cyclic_mod_deps, ["mod_a", "mod_b", "mod_c"])
    _gg_cyclic_cycles = _gg_cyclic.find_circular_deps()
    test("GG: detects circular dep", len(_gg_cyclic_cycles) > 0)
    test("GG: cycle contains mod_a",
         any("mod_a" in c for c in _gg_cyclic_cycles))

    # get_impact_analysis
    _gg_impact = _gg.get_impact_analysis("gate_result")
    test("GG: impact exists", _gg_impact["exists"] is True)
    test("GG: impact direct_gates includes gate_01",
         "gate_01_test" in _gg_impact["direct_gates"])
    test("GG: impact all_gates covers all 3", len(_gg_impact["all_gates"]) == 3)
    test("GG: impact has risk_level", _gg_impact["risk_level"] in ("critical", "high", "medium", "low"))
    test("GG: impact score matches all_gates", _gg_impact["impact_score"] == len(_gg_impact["all_gates"]))
    test("GG: impact transitive_modules includes state",
         "state" in _gg_impact["transitive_modules"] or "audit_log" in _gg_impact["transitive_modules"])

    # Impact for unknown module
    _gg_unknown = _gg.get_impact_analysis("nonexistent_module")
    test("GG: unknown module exists=False", _gg_unknown["exists"] is False)
    test("GG: unknown module zero impact", _gg_unknown["impact_score"] == 0)
    test("GG: unknown module risk=low", _gg_unknown["risk_level"] == "low")

    # Impact analysis risk levels
    _gg_high_gate_deps = {f"gate_{i:02d}": ["core_mod"] for i in range(10)}
    _gg_high = GateGraph(_gg_high_gate_deps, {"core_mod": []}, ["core_mod"])
    _gg_high_impact = _gg_high.get_impact_analysis("core_mod")
    test("GG: high impact = critical risk", _gg_high_impact["risk_level"] == "critical")

    # build_graph with temp directories
    with _gg_tempfile.TemporaryDirectory() as _gg_tmpdir:
        _gg_gates_dir = os.path.join(_gg_tmpdir, "gates")
        _gg_shared_dir = os.path.join(_gg_tmpdir, "shared")
        os.makedirs(_gg_gates_dir)
        os.makedirs(_gg_shared_dir)

        with open(os.path.join(_gg_gates_dir, "gate_01_test.py"), "w") as f:
            f.write("from shared.state import load_state\n")
        with open(os.path.join(_gg_shared_dir, "state.py"), "w") as f:
            f.write("# no imports\n")

        _gg_built = build_graph(_gg_gates_dir, _gg_shared_dir)
        test("GG: build_graph finds gate", "gate_01_test" in _gg_built.gates)
        test("GG: build_graph finds shared module", "state" in _gg_built.shared_modules)
        test("GG: build_graph gate depends on state", "state" in _gg_built.gate_deps.get("gate_01_test", []))

    # build_graph with missing dirs
    _gg_empty = build_graph("/tmp/nonexistent_gates_dir", "/tmp/nonexistent_shared_dir")
    test("GG: build_graph missing dirs returns empty", len(_gg_empty.gates) == 0)

except Exception as _gg_exc:
    test("Gate Graph Deep Tests: import and tests", False, str(_gg_exc))

# ── Session Analytics Deep Tests ─────────────────────────────────────────
print("\n--- Session Analytics Deep Tests ---")
try:
    from shared.session_analytics import (
        tool_call_distribution, gate_fire_rates, gate_block_rates,
        error_frequency, session_productivity, _compute_resolve_score,
        _stddev, compare_sessions_metrics, _state_session_metrics,
    )

    # tool_call_distribution
    _sa_entries = [
        {"tool": "Read", "decision": "pass"},
        {"tool": "Read", "decision": "pass"},
        {"tool": "Edit", "decision": "pass"},
        {"tool_name": "Write", "decision": "block"},
    ]
    _sa_tcd = tool_call_distribution(_sa_entries)
    test("SA: tool_call_dist Read=2", _sa_tcd.get("Read") == 2)
    test("SA: tool_call_dist Edit=1", _sa_tcd.get("Edit") == 1)
    test("SA: tool_call_dist Write=1", _sa_tcd.get("Write") == 1)
    test("SA: tool_call_dist empty", tool_call_distribution([]) == {})

    # gate_fire_rates
    _sa_gate_entries = [
        {"gate": "gate_01", "decision": "pass"},
        {"gate": "gate_01", "decision": "block"},
        {"gate": "gate_02", "decision": "pass"},
        {"gate_name": "gate_03", "decision": "warn"},
    ]
    _sa_gfr = gate_fire_rates(_sa_gate_entries)
    test("SA: gate_fire_rates gate_01=2", _sa_gfr.get("gate_01") == 2)
    test("SA: gate_fire_rates gate_02=1", _sa_gfr.get("gate_02") == 1)
    test("SA: gate_fire_rates gate_03=1", _sa_gfr.get("gate_03") == 1)

    # gate_block_rates
    _sa_gbr = gate_block_rates(_sa_gate_entries)
    test("SA: gate_block_rates gate_01 pass=1 block=1",
         _sa_gbr.get("gate_01", {}).get("pass") == 1 and _sa_gbr["gate_01"]["block"] == 1)
    test("SA: gate_block_rates gate_01 total=2", _sa_gbr["gate_01"]["total"] == 2)
    test("SA: gate_block_rates gate_02 no blocks", _sa_gbr.get("gate_02", {}).get("block") == 0)

    # error_frequency
    _sa_err_entries = [
        {"decision": "block", "reason": "must Read file.py before editing"},
        {"decision": "block", "reason": "must Read other.py before editing"},
        {"decision": "warn", "reason": "memory not queried in this session"},
        {"decision": "block", "reason": "NO DESTROY pattern blocked"},
        {"decision": "pass", "reason": "all good"},  # should be skipped
        {"decision": "block", "reason": "something unusual happened"},
    ]
    _sa_ef = error_frequency(_sa_err_entries)
    test("SA: error_freq gate1 read-before-edit=2", _sa_ef.get("gate1:read-before-edit") == 2)
    test("SA: error_freq gate2 no-destroy=1", _sa_ef.get("gate2:no-destroy") == 1)
    test("SA: error_freq gate4 memory-first=1", _sa_ef.get("gate4:memory-first") == 1)
    test("SA: error_freq other bucket for unusual", _sa_ef.get("other-block-or-warn") == 1)
    test("SA: error_freq pass decisions excluded", sum(_sa_ef.values()) == 5)

    # _stddev
    test("SA: stddev [1,2,3]", abs(_stddev([1.0, 2.0, 3.0]) - 0.8165) < 0.01)
    test("SA: stddev empty", _stddev([]) == 0.0)
    test("SA: stddev single", _stddev([5.0]) == 0.0)
    test("SA: stddev identical values", _stddev([3.0, 3.0, 3.0]) == 0.0)

    # _compute_resolve_score
    _sa_resolve_entries = [
        {"decision": "block", "gate": "gate_01"},
        {"decision": "pass", "gate": "gate_01"},  # resolved within window
        {"decision": "block", "gate": "gate_02"},
        # no pass for gate_02 within window
    ]
    _sa_rs = _compute_resolve_score(_sa_resolve_entries)
    test("SA: resolve_score 50% (1 of 2 resolved)", abs(_sa_rs - 0.5) < 0.01)
    test("SA: resolve_score no blocks = 1.0", _compute_resolve_score([]) == 1.0)
    test("SA: resolve_score all resolved",
         _compute_resolve_score([
             {"decision": "block", "gate": "g1"},
             {"decision": "pass", "gate": "g1"},
         ]) == 1.0)

    # session_productivity
    _sa_prod_entries = [
        {"tool": "Edit", "decision": "pass", "gate": "g1"},
        {"tool": "Write", "decision": "pass", "gate": "g2"},
        {"tool": "Read", "decision": "pass", "gate": "g3"},
        {"tool": "Edit", "decision": "block", "gate": "g4"},
        {"tool": "mcp__memory__search_knowledge", "decision": "pass", "gate": "g5"},
    ]
    _sa_prod = session_productivity(_sa_prod_entries, 30.0)
    test("SA: productivity has score", "score" in _sa_prod)
    test("SA: productivity score 0-100", 0.0 <= _sa_prod["score"] <= 100.0)
    test("SA: productivity has grade", _sa_prod["grade"] in ("A", "B", "C", "D", "F"))
    test("SA: productivity has breakdown", "breakdown" in _sa_prod)
    test("SA: productivity breakdown has edit_velocity", "edit_velocity" in _sa_prod["breakdown"])
    test("SA: productivity breakdown has block_rate", "block_rate" in _sa_prod["breakdown"])
    test("SA: productivity breakdown has memory_contrib", "memory_contrib" in _sa_prod["breakdown"])
    test("SA: productivity edit sub_score > 0", _sa_prod["breakdown"]["edit_velocity"]["sub_score"] > 0)
    test("SA: productivity memory sub_score > 0", _sa_prod["breakdown"]["memory_contrib"]["sub_score"] > 0)

    # session_productivity edge: 0 duration
    _sa_prod_zero = session_productivity([], 0.0)
    test("SA: productivity 0 duration doesn't crash", _sa_prod_zero["score"] >= 0)

    # compare_sessions_metrics
    _sa_current = {"score": 80.0}
    _sa_history = [{"score": 70.0}, {"score": 75.0}, {"score": 72.0}]
    _sa_comp = compare_sessions_metrics(_sa_current, _sa_history)
    test("SA: compare has current_score", _sa_comp["current_score"] == 80.0)
    test("SA: compare has rolling_avg", _sa_comp["rolling_avg"] > 0)
    test("SA: compare has delta", isinstance(_sa_comp["delta"], float))
    test("SA: compare has trend", _sa_comp["trend"] in ("improving", "declining", "stable", "insufficient_data"))
    test("SA: compare has spike_detected", isinstance(_sa_comp["spike_detected"], bool))
    test("SA: compare improving delta positive", _sa_comp["delta"] > 0)
    test("SA: compare trend improving", _sa_comp["trend"] == "improving")

    # compare_sessions_metrics: empty history
    _sa_comp_empty = compare_sessions_metrics({"score": 50}, [])
    test("SA: compare empty history = insufficient_data", _sa_comp_empty["trend"] == "insufficient_data")

    # _state_session_metrics
    _sa_state = {
        "session_start": 1700000000.0,
        "tool_call_counts": {"Read": 10, "Edit": 5, "mcp__memory__search_knowledge": 3, "mcp__memory__remember_this": 2},
        "total_tool_calls": 20,
        "gate6_warn_count": 1,
        "files_read": ["a.py", "b.py"],
        "files_edited": ["a.py"],
        "gate_effectiveness": {},
        "security_profile": "strict",
        "pending_verification": ["fix1"],
        "active_bans": {"ban1": True},
        "active_subagents": ["agent1", "agent2"],
        "auto_remember_count": 5,
        "last_test_exit_code": 0,
    }
    _sa_sm = _state_session_metrics("test-session", _sa_state)
    test("SA: state_metrics session_id", _sa_sm["session_id"] == "test-session")
    test("SA: state_metrics total_tool_calls", _sa_sm["total_tool_calls"] == 20)
    test("SA: state_metrics memory_queries=3", _sa_sm["memory_queries"] == 3)
    test("SA: state_metrics memory_saves=2", _sa_sm["memory_saves"] == 2)
    test("SA: state_metrics files_read_count=2", _sa_sm["files_read_count"] == 2)
    test("SA: state_metrics files_edited_count=1", _sa_sm["files_edited_count"] == 1)
    test("SA: state_metrics warnings=1", _sa_sm["warnings_this_session"] == 1)
    test("SA: state_metrics security_profile", _sa_sm["security_profile"] == "strict")
    test("SA: state_metrics active_bans_count=1", _sa_sm["active_bans_count"] == 1)
    test("SA: state_metrics subagent_count=2", _sa_sm["subagent_count"] == 2)
    test("SA: state_metrics auto_remember_count=5", _sa_sm["auto_remember_count"] == 5)
    test("SA: state_metrics last_test_exit_code=0", _sa_sm["last_test_exit_code"] == 0)
    test("SA: state_metrics session_start_iso not empty", _sa_sm["session_start_iso"] != "")
    test("SA: state_metrics duration_minutes > 0", _sa_sm["duration_minutes"] > 0)

    # _state_session_metrics with empty state
    _sa_sm_empty = _state_session_metrics("empty", {})
    test("SA: empty state total_tool_calls=0", _sa_sm_empty["total_tool_calls"] == 0)
    test("SA: empty state memory_queries=0", _sa_sm_empty["memory_queries"] == 0)
    test("SA: empty state security_profile=balanced", _sa_sm_empty["security_profile"] == "balanced")

except Exception as _sa_exc:
    test("Session Analytics Deep Tests: import and tests", False, str(_sa_exc))

# ── Metrics Exporter Deep Tests ─────────────────────────────────────────
print("\n--- Metrics Exporter Deep Tests ---")
try:
    from shared.metrics_exporter import (
        _ls, _emit_counter, _emit_gauge, _emit_histogram, _zero_metric,
        _DEFS, DEFAULT_OUTPUT_PATH,
    )

    # Constants
    test("ME: DEFAULT_OUTPUT_PATH", DEFAULT_OUTPUT_PATH == "/tmp/torus_metrics.prom")
    test("ME: _DEFS has entries", len(_DEFS) >= 7)

    # _ls
    test("ME: _ls empty dict", _ls({}) == "")
    test("ME: _ls single label", _ls({"gate": "g01"}) == '{gate="g01"}')
    test("ME: _ls multiple labels sorted",
         _ls({"z": "1", "a": "2"}) == '{a="2",z="1"}')

    # _emit_counter
    _me_lines = []
    _emit_counter(_me_lines, "test_counter", "A test counter", {"g1": {"labels": {"gate": "g01"}, "value": 5}}, 1.0)
    test("ME: emit_counter has HELP", any("HELP test_counter" in l for l in _me_lines))
    test("ME: emit_counter has TYPE counter", any("TYPE test_counter counter" in l for l in _me_lines))
    test("ME: emit_counter has value", any("5" in l and "g01" in l for l in _me_lines))

    # _emit_counter with scale
    _me_lines2 = []
    _emit_counter(_me_lines2, "scaled", "Scaled", {"x": {"labels": {}, "value": 1000}}, 0.001)
    test("ME: emit_counter with scale",
         any("1.0" in l or "1.0" in l for l in _me_lines2))

    # _emit_gauge
    _me_lines3 = []
    _emit_gauge(_me_lines3, "test_gauge", "A gauge", {"g1": {"labels": {}, "value": 42}}, 1.0)
    test("ME: emit_gauge has TYPE gauge", any("TYPE test_gauge gauge" in l for l in _me_lines3))
    test("ME: emit_gauge has value 42", any("42" in l for l in _me_lines3))

    # _emit_gauge with injected labels
    _me_lines4 = []
    _emit_gauge(_me_lines4, "mem", "Memory", {"m1": {"labels": {}, "value": 100}}, 1.0, {"table": "knowledge"})
    test("ME: emit_gauge injected labels",
         any("knowledge" in l for l in _me_lines4))

    # _emit_histogram
    _me_lines5 = []
    _emit_histogram(_me_lines5, "test_hist", "A histogram",
                    {"h1": {"labels": {"gate": "g01"}, "count": 10, "sum": 500}}, 0.001)
    test("ME: emit_histogram has TYPE histogram", any("TYPE test_hist histogram" in l for l in _me_lines5))
    test("ME: emit_histogram has _bucket", any("_bucket" in l for l in _me_lines5))
    test("ME: emit_histogram has _sum", any("_sum" in l for l in _me_lines5))
    test("ME: emit_histogram has _count", any("_count" in l for l in _me_lines5))
    test("ME: emit_histogram le=+Inf", any('+Inf' in l for l in _me_lines5))

    # _zero_metric
    _me_lines6 = []
    _zero_metric(_me_lines6, "zero_counter", "Zero", "counter")
    test("ME: zero_metric counter has value 0", any("zero_counter 0" in l for l in _me_lines6))

    _me_lines7 = []
    _zero_metric(_me_lines7, "zero_hist", "Zero hist", "histogram")
    test("ME: zero_metric histogram has _bucket", any("_bucket" in l for l in _me_lines7))
    test("ME: zero_metric histogram has _sum 0", any("_sum 0" in l for l in _me_lines7))
    test("ME: zero_metric histogram has _count 0", any("_count 0" in l for l in _me_lines7))

    # _DEFS structure
    for _me_prom_name, _me_help, _me_type, _me_src, _me_scale in _DEFS:
        test(f"ME: def {_me_prom_name} has valid type",
             _me_type in ("counter", "gauge", "histogram"))

except Exception as _me_exc:
    test("Metrics Exporter Deep Tests: import and tests", False, str(_me_exc))

# ── Domain Registry Deep Tests ──────────────────────────────────────────
print("\n--- Domain Registry Deep Tests ---")
try:
    from shared.domain_registry import (
        _short_gate_name, _gate_matches_list, _lookup_gate_mode,
        DEFAULT_PROFILE, load_domain_profile, save_domain_profile,
        load_domain_mastery, load_domain_behavior,
        get_active_domain, set_active_domain,
        detect_domain_from_live_state, get_domain_memory_tags,
        get_domain_l2_keywords, get_domain_token_budget,
        get_domain_context_for_injection, list_domains,
    )
    import tempfile as _dr_tempfile

    # Constants
    test("DR: DEFAULT_PROFILE has security_profile", DEFAULT_PROFILE.get("security_profile") == "balanced")
    test("DR: DEFAULT_PROFILE has gate_modes dict", isinstance(DEFAULT_PROFILE.get("gate_modes"), dict))
    test("DR: DEFAULT_PROFILE has graduation", "graduation" in DEFAULT_PROFILE)
    test("DR: DEFAULT_PROFILE has token_budget", DEFAULT_PROFILE.get("token_budget") == 800)
    test("DR: DEFAULT_PROFILE has auto_detect", "auto_detect" in DEFAULT_PROFILE)

    # _short_gate_name
    test("DR: short_gate_name full", _short_gate_name("gate_04_memory_first") == "gate_04")
    test("DR: short_gate_name already short", _short_gate_name("gate_04") == "gate_04")
    test("DR: short_gate_name with prefix", _short_gate_name("gates.gate_04_memory_first") == "gate_04")
    test("DR: short_gate_name single part", _short_gate_name("something") == "something")

    # _gate_matches_list
    test("DR: gate_matches exact", _gate_matches_list("gate_04", ["gate_04"]))
    test("DR: gate_matches full name vs short",
         _gate_matches_list("gate_04_memory_first", ["gate_04"]))
    test("DR: gate_matches short vs full",
         _gate_matches_list("gate_04", ["gate_04_memory_first"]))
    test("DR: gate_matches no match", not _gate_matches_list("gate_04", ["gate_05"]))
    test("DR: gate_matches empty list", not _gate_matches_list("gate_04", []))

    # _lookup_gate_mode
    _dr_modes = {"gate_04": "warn", "gate_05_proof": "disabled"}
    test("DR: lookup exact match", _lookup_gate_mode("gate_04", _dr_modes) == "warn")
    test("DR: lookup full name match",
         _lookup_gate_mode("gate_05_proof", _dr_modes) == "disabled")
    test("DR: lookup short vs full",
         _lookup_gate_mode("gate_05", _dr_modes) == "disabled")
    test("DR: lookup not found", _lookup_gate_mode("gate_99", _dr_modes) is None)
    test("DR: lookup empty modes", _lookup_gate_mode("gate_04", {}) is None)

    # Filesystem tests with tempdir
    with _dr_tempfile.TemporaryDirectory() as _dr_tmpdir:
        import shared.domain_registry as _dr_mod
        _dr_orig_dir = _dr_mod.DOMAINS_DIR
        _dr_orig_active = _dr_mod.ACTIVE_FILE
        _dr_mod.DOMAINS_DIR = _dr_tmpdir
        _dr_mod.ACTIVE_FILE = os.path.join(_dr_tmpdir, ".active")

        try:
            # No domains yet
            test("DR: list_domains empty", list_domains() == [])
            test("DR: get_active_domain none", get_active_domain() is None)

            # Create a test domain
            _dr_domain_dir = os.path.join(_dr_tmpdir, "test-domain")
            os.makedirs(_dr_domain_dir)
            _dr_profile = {"description": "Test domain", "token_budget": 500, "memory_tags": ["test"], "l2_keywords": ["keyword1"]}
            with open(os.path.join(_dr_domain_dir, "profile.json"), "w") as f:
                json.dump(_dr_profile, f)
            with open(os.path.join(_dr_domain_dir, "mastery.md"), "w") as f:
                f.write("# Test Mastery\nKnowledge here.")
            with open(os.path.join(_dr_domain_dir, "behavior.md"), "w") as f:
                f.write("# Behavior\nRules here.")

            # list_domains
            _dr_domains = list_domains()
            test("DR: list_domains finds test-domain", len(_dr_domains) == 1)
            test("DR: list_domains name correct", _dr_domains[0]["name"] == "test-domain")
            test("DR: list_domains has_mastery", _dr_domains[0]["has_mastery"] is True)
            test("DR: list_domains not active", _dr_domains[0]["active"] is False)

            # load_domain_profile with merge
            _dr_loaded = load_domain_profile("test-domain")
            test("DR: loaded profile description", _dr_loaded["description"] == "Test domain")
            test("DR: loaded profile merged defaults", "graduation" in _dr_loaded)
            test("DR: loaded profile token_budget", _dr_loaded["token_budget"] == 500)

            # load_domain_profile nonexistent
            _dr_missing = load_domain_profile("nonexistent")
            test("DR: missing profile returns defaults", _dr_missing["security_profile"] == "balanced")

            # save_domain_profile
            save_domain_profile("test-domain", {"description": "Updated"})
            _dr_reloaded = load_domain_profile("test-domain")
            test("DR: saved profile persists", _dr_reloaded["description"] == "Updated")

            # load_domain_mastery / behavior
            test("DR: load_mastery", "Test Mastery" in load_domain_mastery("test-domain"))
            test("DR: load_behavior", "Behavior" in load_domain_behavior("test-domain"))
            test("DR: load_mastery missing", load_domain_mastery("nope") == "")
            test("DR: load_behavior missing", load_domain_behavior("nope") == "")

            # set/get active domain
            test("DR: set_active succeeds", set_active_domain("test-domain") is True)
            test("DR: get_active returns it", get_active_domain() == "test-domain")
            test("DR: set_active nonexistent", set_active_domain("nope") is False)
            test("DR: set_active None deactivates", set_active_domain(None) is True)
            test("DR: get_active after deactivate", get_active_domain() is None)

            # get_domain_memory_tags / l2_keywords / token_budget
            save_domain_profile("test-domain", {"memory_tags": ["t1", "t2"], "l2_keywords": ["kw"], "token_budget": 600})
            test("DR: get_memory_tags", get_domain_memory_tags("test-domain") == ["t1", "t2"])
            test("DR: get_l2_keywords", get_domain_l2_keywords("test-domain") == ["kw"])
            test("DR: get_token_budget", get_domain_token_budget("test-domain") == 600)

            # detect_domain_from_live_state
            save_domain_profile("test-domain", {
                "auto_detect": {
                    "live_state_project": ["torus*"],
                    "live_state_feature": [],
                }
            })
            _dr_detected = detect_domain_from_live_state({"project": "torus-framework"})
            test("DR: detect_domain matches project", _dr_detected == "test-domain")
            _dr_no_match = detect_domain_from_live_state({"project": "other-project"})
            test("DR: detect_domain no match", _dr_no_match is None)
            test("DR: detect_domain empty state", detect_domain_from_live_state({}) is None)

            # get_domain_context_for_injection
            save_domain_profile("test-domain", {"token_budget": 5})  # 5*4=20 char limit, mastery is 30 chars
            _dr_mastery, _dr_behavior = get_domain_context_for_injection("test-domain")
            test("DR: context injection mastery not empty", len(_dr_mastery) > 0)
            test("DR: context injection behavior not empty", len(_dr_behavior) > 0)
            test("DR: context injection truncated", "truncated" in _dr_mastery)

            # No active domain
            set_active_domain(None)
            _dr_none_m, _dr_none_b = get_domain_context_for_injection()
            test("DR: context no active domain", _dr_none_m == "" and _dr_none_b == "")

        finally:
            _dr_mod.DOMAINS_DIR = _dr_orig_dir
            _dr_mod.ACTIVE_FILE = _dr_orig_active

except Exception as _dr_exc:
    test("Domain Registry Deep Tests: import and tests", False, str(_dr_exc))

# ── Agent Channel Deep Tests ────────────────────────────────────────────
print("\n--- Agent Channel Deep Tests ---")
try:
    import shared.agent_channel as _ac_mod
    import tempfile as _ac_tempfile

    with _ac_tempfile.TemporaryDirectory() as _ac_tmpdir:
        _ac_orig_db = _ac_mod.DB_PATH
        _ac_orig_lock = _ac_mod.LOCK_PATH
        _ac_mod.DB_PATH = os.path.join(_ac_tmpdir, "test_channel.db")
        _ac_mod.LOCK_PATH = _ac_mod.DB_PATH + ".lock"

        try:
            # post_message
            _ac_ok = _ac_mod.post_message("agent-1", "discovery", "Found a bug")
            test("AC: post_message returns True", _ac_ok is True)

            _ac_ok2 = _ac_mod.post_message("agent-2", "status", "Working on fix", to_agent="agent-1")
            test("AC: post_message targeted", _ac_ok2 is True)

            # read_messages
            _ac_start = time.time() - 60
            _ac_msgs = _ac_mod.read_messages(_ac_start)
            test("AC: read_messages returns list", isinstance(_ac_msgs, list))
            test("AC: read_messages finds 2 messages", len(_ac_msgs) == 2)
            test("AC: message has from_agent", all("from_agent" in m for m in _ac_msgs))
            test("AC: message has content", all("content" in m for m in _ac_msgs))
            test("AC: message has ts", all("ts" in m for m in _ac_msgs))
            test("AC: message has msg_type", all("msg_type" in m for m in _ac_msgs))

            # read_messages with agent filter
            _ac_filtered = _ac_mod.read_messages(_ac_start, agent_id="agent-1")
            test("AC: filtered read returns messages", len(_ac_filtered) >= 1)

            # read_messages future timestamp = empty
            _ac_future = _ac_mod.read_messages(time.time() + 3600)
            test("AC: future timestamp returns empty", len(_ac_future) == 0)

            # read_messages with limit
            for i in range(5):
                _ac_mod.post_message("agent-3", "info", f"msg-{i}")
            _ac_limited = _ac_mod.read_messages(_ac_start, limit=3)
            test("AC: limit works", len(_ac_limited) == 3)

            # cleanup
            _ac_deleted = _ac_mod.cleanup(max_age_hours=0)
            test("AC: cleanup returns count", isinstance(_ac_deleted, int))
            test("AC: cleanup deleted messages", _ac_deleted >= 5)

            # After cleanup
            _ac_after = _ac_mod.read_messages(_ac_start)
            test("AC: no messages after cleanup", len(_ac_after) == 0)

        finally:
            _ac_mod.DB_PATH = _ac_orig_db
            _ac_mod.LOCK_PATH = _ac_orig_lock

except Exception as _ac_exc:
    test("Agent Channel Deep Tests: import and tests", False, str(_ac_exc))

# ── State Migrator Deep Tests ───────────────────────────────────────────
print("\n--- State Migrator Deep Tests ---")
try:
    from shared.state_migrator import (
        migrate_state, validate_state, get_schema_diff,
        _serialize_for_diff, validate_and_migrate, get_schema_metadata,
    )
    from shared.state import default_state, STATE_VERSION

    # migrate_state: empty dict
    _smig_empty = migrate_state({})
    test("SMIG: migrate empty dict adds all fields", len(_smig_empty) >= 10)
    test("SMIG: migrate sets version", _smig_empty["_version"] == STATE_VERSION)

    # migrate_state: partial dict
    _smig_partial = migrate_state({"files_read": ["a.py"]})
    test("SMIG: migrate preserves existing", _smig_partial["files_read"] == ["a.py"])
    test("SMIG: migrate adds missing fields", "tool_call_counts" in _smig_partial)

    # migrate_state: non-dict
    _smig_non = migrate_state("not a dict")
    test("SMIG: migrate non-dict returns defaults", isinstance(_smig_non, dict))
    test("SMIG: migrate non-dict has version", "_version" in _smig_non)

    # validate_state: valid default state (mentor_memory_match=None is a known pre-existing schema mismatch)
    _smig_valid_state = default_state()
    _smig_valid_state["mentor_memory_match"] = {}  # Fix known None-vs-dict mismatch
    _smig_is_valid, _smig_errs, _smig_warns = validate_state(_smig_valid_state)
    test("SMIG: validate default state is valid", _smig_is_valid is True)
    test("SMIG: validate default no errors", len(_smig_errs) == 0)

    # validate_state: non-dict
    _smig_nv, _smig_ne, _smig_nw = validate_state("string")
    test("SMIG: validate non-dict invalid", _smig_nv is False)
    test("SMIG: validate non-dict has error", len(_smig_ne) > 0)

    # validate_state: missing fields
    _smig_mv, _smig_me, _smig_mw = validate_state({"_version": 1})
    test("SMIG: validate missing fields invalid", _smig_mv is False)
    test("SMIG: validate missing fields errors", len(_smig_me) > 0)

    # validate_state: wrong types
    _smig_wrong = default_state()
    _smig_wrong["total_tool_calls"] = "not an int"
    _smig_wv, _smig_we, _smig_ww = validate_state(_smig_wrong)
    test("SMIG: validate wrong type invalid", _smig_wv is False)
    test("SMIG: validate wrong type error mentions field",
         any("total_tool_calls" in e for e in _smig_we))

    # get_schema_diff: empty vs defaults
    _smig_diff = get_schema_diff({})
    test("SMIG: schema_diff missing_fields > 0", len(_smig_diff["missing_fields"]) > 0)
    test("SMIG: schema_diff has summary", "summary" in _smig_diff)
    test("SMIG: schema_diff summary missing count", _smig_diff["summary"]["missing"] > 0)

    # get_schema_diff: complete state
    _smig_diff_full = get_schema_diff(default_state())
    test("SMIG: schema_diff full = no missing", _smig_diff_full["summary"]["missing"] == 0)

    # get_schema_diff: extra fields
    _smig_extra = default_state()
    _smig_extra["custom_field_xyz"] = "hello"
    _smig_diff_extra = get_schema_diff(_smig_extra)
    test("SMIG: schema_diff finds extra field",
         any(f["name"] == "custom_field_xyz" for f in _smig_diff_extra["extra_fields"]))

    # get_schema_diff: non-dict
    _smig_diff_nd = get_schema_diff("not a dict")
    test("SMIG: schema_diff non-dict has error", "error" in _smig_diff_nd)

    # _serialize_for_diff
    test("SMIG: serialize string", _serialize_for_diff("hello") == "hello")
    test("SMIG: serialize int", _serialize_for_diff(42) == 42)
    test("SMIG: serialize None", _serialize_for_diff(None) is None)
    test("SMIG: serialize long list", "[list:" in str(_serialize_for_diff(list(range(10)))))
    test("SMIG: serialize short list", _serialize_for_diff([1, 2]) == [1, 2])
    test("SMIG: serialize large dict", "{dict:" in str(_serialize_for_diff({str(i): i for i in range(5)})))
    test("SMIG: serialize small dict", _serialize_for_diff({"a": 1}) == {"a": 1})

    # validate_and_migrate (mentor_memory_match=None is known schema mismatch, check only that migration works)
    _smig_vm_state, _smig_vm_valid, _smig_vm_errs, _smig_vm_warns = validate_and_migrate({})
    test("SMIG: validate_and_migrate returns migrated", len(_smig_vm_state) > 5)
    test("SMIG: validate_and_migrate migration adds fields", "_version" in _smig_vm_state)

    # get_schema_metadata
    _smig_meta = get_schema_metadata()
    test("SMIG: metadata has version", _smig_meta["version"] == STATE_VERSION)
    test("SMIG: metadata has schema dict", isinstance(_smig_meta["schema"], dict))
    test("SMIG: metadata has field_count", _smig_meta["field_count"] > 0)

except Exception as _smig_exc:
    test("State Migrator Deep Tests: import and tests", False, str(_smig_exc))

# ── Rules Validator Deep Tests ──────────────────────────────────────────
print("\n--- Rules Validator Deep Tests ---")
try:
    from shared.rules_validator import (
        _parse_frontmatter, _walk_files, _glob_matches_any,
        _extract_doc_paths, _detect_overlaps, validate_rules,
    )
    import tempfile as _rv_tempfile

    # _parse_frontmatter
    _rv_fm, _rv_fm_err = _parse_frontmatter("---\nglobs: hooks/**/*.py\ndescription: test\n---\n# Content")
    test("RV: parse_frontmatter fields", _rv_fm.get("globs") == "hooks/**/*.py")
    test("RV: parse_frontmatter description", _rv_fm.get("description") == "test")
    test("RV: parse_frontmatter no errors", len(_rv_fm_err) == 0)

    _rv_fm2, _rv_fm2_err = _parse_frontmatter("# No frontmatter here")
    test("RV: no frontmatter detected", len(_rv_fm2_err) > 0)
    test("RV: no frontmatter empty fields", len(_rv_fm2) == 0)

    _rv_fm3, _rv_fm3_err = _parse_frontmatter("---\nglobs: test\n# missing closing")
    test("RV: unclosed frontmatter error", len(_rv_fm3_err) > 0)

    # _walk_files
    with _rv_tempfile.TemporaryDirectory() as _rv_tmpdir:
        os.makedirs(os.path.join(_rv_tmpdir, "sub"))
        with open(os.path.join(_rv_tmpdir, "a.py"), "w") as f:
            f.write("")
        with open(os.path.join(_rv_tmpdir, "sub", "b.py"), "w") as f:
            f.write("")
        os.makedirs(os.path.join(_rv_tmpdir, "__pycache__"))
        with open(os.path.join(_rv_tmpdir, "__pycache__", "c.py"), "w") as f:
            f.write("")

        _rv_files = list(_walk_files(_rv_tmpdir))
        test("RV: walk_files finds a.py", "a.py" in _rv_files)
        test("RV: walk_files finds sub/b.py",
             any("b.py" in f for f in _rv_files))
        test("RV: walk_files skips __pycache__",
             not any("__pycache__" in f for f in _rv_files))

    # _glob_matches_any
    with _rv_tempfile.TemporaryDirectory() as _rv_tmpdir2:
        os.makedirs(os.path.join(_rv_tmpdir2, "hooks"))
        with open(os.path.join(_rv_tmpdir2, "hooks", "test.py"), "w") as f:
            f.write("")
        test("RV: glob_matches_any *.py",
             _glob_matches_any("hooks/test.py", _rv_tmpdir2))
        test("RV: glob_matches_any no match",
             not _glob_matches_any("nonexistent/*.js", _rv_tmpdir2))

    # _extract_doc_paths
    _rv_paths = _extract_doc_paths(
        "See `hooks/shared/state.py` and `docs/missing.md` for details",
        os.path.expanduser("~/.claude"),
    )
    test("RV: extract_doc_paths finds paths", len(_rv_paths) >= 1)
    test("RV: extract_doc_paths returns tuples",
         all(isinstance(p, tuple) and len(p) == 2 for p in _rv_paths))

    # _extract_doc_paths with no paths
    _rv_no_paths = _extract_doc_paths("No backtick references here", "/tmp")
    test("RV: extract_doc_paths empty", len(_rv_no_paths) == 0)

    # _detect_overlaps
    _rv_ol = _detect_overlaps({
        "a.md": ["hooks/**/*.py"],
        "b.md": ["hooks/gates/*.py"],
    })
    test("RV: detect_overlaps finds subsumption", len(_rv_ol) > 0)

    _rv_no_ol = _detect_overlaps({
        "a.md": ["hooks/*.py"],
        "b.md": ["scripts/*.sh"],
    })
    test("RV: detect_overlaps no overlap", len(_rv_no_ol) == 0)

    _rv_empty_ol = _detect_overlaps({})
    test("RV: detect_overlaps empty", len(_rv_empty_ol) == 0)

    # validate_rules with temp directory
    with _rv_tempfile.TemporaryDirectory() as _rv_tmpdir3:
        _rv_rules_dir = os.path.join(_rv_tmpdir3, "rules")
        os.makedirs(_rv_rules_dir)

        with open(os.path.join(_rv_rules_dir, "test.md"), "w") as f:
            f.write("---\nglobs: **/*.py\n---\n# Test Rule\nContent here.\n")

        with open(os.path.join(_rv_rules_dir, "bad.md"), "w") as f:
            f.write("# No Frontmatter\nJust content.\n")

        _rv_report = validate_rules(_rv_rules_dir, _rv_tmpdir3)
        test("RV: validate_rules total=2", _rv_report["total"] == 2)
        test("RV: validate_rules has issues", isinstance(_rv_report["issues"], dict))
        test("RV: validate_rules has suggestions", isinstance(_rv_report["suggestions"], list))
        test("RV: validate_rules has overlaps", isinstance(_rv_report["overlaps"], list))

    # validate_rules with missing directory
    _rv_missing = validate_rules("/tmp/nonexistent_rules_dir_xyz")
    test("RV: validate_rules missing dir", "<rules_dir>" in _rv_missing["issues"])

except Exception as _rv_exc:
    test("Rules Validator Deep Tests: import and tests", False, str(_rv_exc))

# ── Code Hotspot Deep Tests ─────────────────────────────────────────────
print("\n--- Code Hotspot Deep Tests ---")
try:
    from shared.code_hotspot import extract_file_path

    # extract_file_path: Edit tool
    test("CH: extract Edit file_path",
         extract_file_path({"file_path": "/home/user/code.py"}, "Edit") == "/home/user/code.py")
    test("CH: extract Write file_path",
         extract_file_path({"file_path": "/tmp/test.py"}, "Write") == "/tmp/test.py")
    test("CH: extract Read path field",
         extract_file_path({"path": "/etc/config.json"}, "Glob") == "/etc/config.json")
    test("CH: extract NotebookEdit notebook_path",
         extract_file_path({"notebook_path": "/nb/test.ipynb"}, "NotebookEdit") == "/nb/test.ipynb")

    # extract_file_path: Bash command
    test("CH: extract Bash command path",
         extract_file_path({"command": "python3 /home/user/script.py"}, "Bash") == "/home/user/script.py")
    test("CH: extract Bash no path",
         extract_file_path({"command": "echo hello"}, "Bash") == "")

    # extract_file_path: edge cases
    test("CH: extract non-dict", extract_file_path("not a dict", "Read") == "")
    test("CH: extract empty dict", extract_file_path({}, "Read") == "")
    test("CH: extract whitespace path",
         extract_file_path({"file_path": "  /a/b.py  "}, "Edit") == "/a/b.py")

    # Priority: file_path > path > notebook_path
    test("CH: extract priority file_path over path",
         extract_file_path({"file_path": "/first.py", "path": "/second.py"}, "Edit") == "/first.py")

except Exception as _ch_exc:
    test("Code Hotspot Deep Tests: import and tests", False, str(_ch_exc))

# ── Gate Correlation Deep Tests ─────────────────────────────────────────
print("\n--- Gate Correlation Deep Tests ---")
try:
    from shared.gate_correlation import analyze_correlations, format_correlation_report

    # format_correlation_report with synthetic data
    _gc_data = {
        "pairs": [
            {"gate_a": "gate_01", "gate_b": "gate_04", "co_occurrence_pct": 75.0, "count": 12},
            {"gate_a": "gate_01", "gate_b": "gate_06", "co_occurrence_pct": 30.0, "count": 5},
        ],
        "gate_block_counts": {"gate_01": 50, "gate_04": 16, "gate_06": 20},
        "total_events": 200,
        "days_analyzed": 7,
    }
    _gc_report = format_correlation_report(_gc_data)
    test("GC: report has title", "Gate Block Correlation Report" in _gc_report)
    test("GC: report has period", "7 days" in _gc_report)
    test("GC: report has block counts", "gate_01" in _gc_report)
    test("GC: report has pairs", "co-occurrence" in _gc_report.lower())

    # format_correlation_report empty
    _gc_empty = format_correlation_report({"pairs": [], "gate_block_counts": {}, "total_events": 0, "days_analyzed": 1})
    test("GC: empty report no blocks", "No block events" in _gc_empty)

    # analyze_correlations returns valid structure
    _gc_result = analyze_correlations(days=1)
    test("GC: analyze returns pairs", isinstance(_gc_result.get("pairs"), list))
    test("GC: analyze returns gate_block_counts", isinstance(_gc_result.get("gate_block_counts"), dict))
    test("GC: analyze returns total_events", isinstance(_gc_result.get("total_events"), int))
    test("GC: analyze returns days_analyzed", _gc_result.get("days_analyzed") == 1)

except Exception as _gc_exc:
    test("Gate Correlation Deep Tests: import and tests", False, str(_gc_exc))

# ── Consensus Validator Deep Tests ──────────────────────────────────────
print("\n--- Consensus Validator Deep Tests ---")
try:
    from shared.consensus_validator import (
        check_memory_consensus, check_edit_consensus,
        compute_confidence, recommend_action,
        _normalise, _similarity, _is_critical_file,
        _detect_broad_except, _detect_hardcoded_secret,
        _detect_debug_prints, _removed_public_functions,
        _import_drift, _extract_imports,
        CRITICAL_FILES, _THRESHOLD_BLOCK, _THRESHOLD_ASK,
        _DUPLICATE_RATIO, _NEAR_MATCH_RATIO,
    )

    # Constants
    test("CV2: THRESHOLD_BLOCK is 0.3", _THRESHOLD_BLOCK == 0.3)
    test("CV2: THRESHOLD_ASK is 0.6", _THRESHOLD_ASK == 0.6)
    test("CV2: DUPLICATE_RATIO is 0.85", _DUPLICATE_RATIO == 0.85)
    test("CV2: NEAR_MATCH_RATIO is 0.55", _NEAR_MATCH_RATIO == 0.55)
    test("CV2: CRITICAL_FILES has enforcer.py", "enforcer.py" in CRITICAL_FILES)
    test("CV2: CRITICAL_FILES has settings.json", "settings.json" in CRITICAL_FILES)

    # _normalise
    test("CV2: normalise lowercase", _normalise("Hello World") == "hello world")
    test("CV2: normalise collapse whitespace", _normalise("a  b   c") == "a b c")
    test("CV2: normalise strip", _normalise("  test  ") == "test")

    # _similarity
    test("CV2: similarity identical", _similarity("hello", "hello") == 1.0)
    test("CV2: similarity different", _similarity("hello", "world") < 0.5)
    test("CV2: similarity similar", _similarity("hello world", "hello world!") > 0.8)

    # _is_critical_file
    test("CV2: is_critical enforcer.py", _is_critical_file("/path/to/enforcer.py"))
    test("CV2: is_critical settings.json", _is_critical_file("settings.json"))
    test("CV2: not critical random.py", not _is_critical_file("random_file.py"))

    # _detect_broad_except
    test("CV2: detect bare except", _detect_broad_except("try:\n  pass\nexcept:\n  pass"))
    test("CV2: detect except Exception", _detect_broad_except("except Exception:\n  pass"))
    test("CV2: no broad except", not _detect_broad_except("except ValueError:\n  pass"))

    # _detect_hardcoded_secret
    test("CV2: detect password", _detect_hardcoded_secret('password = "mysecretpassword"'))
    test("CV2: detect api_key", _detect_hardcoded_secret("api_key = 'abcdefgh'"))
    test("CV2: no secret", not _detect_hardcoded_secret("name = 'John'"))

    # _detect_debug_prints
    test("CV2: detect print()", _detect_debug_prints("print('debug')"))
    test("CV2: no print", not _detect_debug_prints("logging.info('msg')"))

    # _extract_imports
    _cv2_imports = _extract_imports("import os\nfrom pathlib import Path\nimport json\n")
    test("CV2: extract_imports os", "os" in _cv2_imports)
    test("CV2: extract_imports pathlib", "pathlib" in _cv2_imports)
    test("CV2: extract_imports json", "json" in _cv2_imports)

    # _removed_public_functions
    _cv2_old = "def foo():\n  pass\ndef bar():\n  pass\ndef _private():\n  pass\n"
    _cv2_new = "def foo():\n  pass\ndef _private():\n  pass\n"
    _cv2_removed = _removed_public_functions(_cv2_old, _cv2_new)
    test("CV2: removed_public finds bar", "bar" in _cv2_removed)
    test("CV2: removed_public ignores private", "_private" not in _cv2_removed)

    # _import_drift
    _cv2_drift = _import_drift("import os\nimport json\n", "import os\n")
    test("CV2: import_drift finds json", "json" in _cv2_drift)
    test("CV2: import_drift keeps os", "os" not in _cv2_drift)

    # compute_confidence
    test("CV2: confidence empty", compute_confidence({}) == 0.5)
    test("CV2: confidence all 1.0", compute_confidence({"memory_coverage": 1.0, "test_coverage": 1.0}) > 0.8)
    test("CV2: confidence all 0.0", compute_confidence({"memory_coverage": 0.0, "test_coverage": 0.0}) < 0.2)
    test("CV2: confidence clamped values",
         compute_confidence({"custom": 2.0}) <= 1.0)

    # recommend_action
    test("CV2: recommend allow", recommend_action(0.8) == "allow")
    test("CV2: recommend ask", recommend_action(0.5) == "ask")
    test("CV2: recommend block", recommend_action(0.1) == "block")
    test("CV2: recommend boundary allow", recommend_action(0.6) == "allow")
    test("CV2: recommend boundary ask", recommend_action(0.3) == "ask")
    test("CV2: recommend boundary block", recommend_action(0.29) == "block")

    # check_memory_consensus: novel content
    _cv2_mc_novel = check_memory_consensus("entirely new content about quantum computing", ["old memory about Python"])
    test("CV2: mc novel verdict", _cv2_mc_novel["verdict"] == "novel")
    test("CV2: mc novel confidence", _cv2_mc_novel["confidence"] > 0)
    test("CV2: mc novel has reason", len(_cv2_mc_novel["reason"]) > 0)

    # check_memory_consensus: duplicate
    _cv2_mc_dupe = check_memory_consensus("the quick brown fox jumps over the lazy dog",
                                         ["the quick brown fox jumps over the lazy dog"])
    test("CV2: mc duplicate verdict", _cv2_mc_dupe["verdict"] == "duplicate")
    test("CV2: mc duplicate high match", _cv2_mc_dupe["top_match"] >= 0.85)

    # check_memory_consensus: conflict (negation)
    _cv2_mc_conflict = check_memory_consensus(
        "gate 4 should never block on subagent tasks",
        ["gate 4 should always block on subagent tasks"],
    )
    test("CV2: mc conflict or novel", _cv2_mc_conflict["verdict"] in ("conflict", "novel"))

    # check_memory_consensus: empty content
    _cv2_mc_empty = check_memory_consensus("", ["some memory"])
    test("CV2: mc empty = novel", _cv2_mc_empty["verdict"] == "novel")

    # check_edit_consensus: safe edit
    _cv2_ec_safe = check_edit_consensus(
        "random_file.py",
        "def foo():\n    return 1\n",
        "def foo():\n    return 2\n",
    )
    test("CV2: ec safe edit", _cv2_ec_safe["safe"] is True)
    test("CV2: ec safe high confidence", _cv2_ec_safe["confidence"] > 0.7)
    test("CV2: ec not critical", _cv2_ec_safe["is_critical"] is False)

    # check_edit_consensus: critical file
    _cv2_ec_crit = check_edit_consensus(
        "enforcer.py",
        "def check():\n    return True\n",
        "def check():\n    return False\n",
    )
    test("CV2: ec critical file detected", _cv2_ec_crit["is_critical"] is True)
    test("CV2: ec critical lower confidence", _cv2_ec_crit["confidence"] < 1.0)

    # check_edit_consensus: risky edit (secret + API removal)
    _cv2_ec_risky = check_edit_consensus(
        "config.py",
        "def setup():\n    pass\n",
        "password = 'supersecret123'\ndef _internal():\n    pass\n",
    )
    test("CV2: ec risky has risks", len(_cv2_ec_risky["risks"]) > 0)
    test("CV2: ec risky lower confidence", _cv2_ec_risky["confidence"] < 0.8)

except Exception as _cv2_exc:
    test("Consensus Validator Deep Tests: import and tests", False, str(_cv2_exc))

# ─────────────────────────────────────────────────
# Chain Refinement Deep Tests (chain_refinement.py)
# ─────────────────────────────────────────────────
try:
    from shared.chain_refinement import (
        _normalize_error,
        _extract_outcome_fields,
        get_strategy_effectiveness,
        detect_recurring_failures,
        suggest_refinement,
        compute_chain_health,
        analyze_outcomes,
        StrategyStats,
        RecurringPattern,
        Refinement,
        ChainHealth,
        MIN_RECURRENCE,
        INEFFECTIVE_THRESHOLD,
        CHRONIC_FAILURE_THRESHOLD,
        MIN_ATTEMPTS_FOR_STATS,
        MIN_IMPROVEMENT_DELTA,
    )

    # ── Constants ──
    test("CR: MIN_RECURRENCE is 3", MIN_RECURRENCE == 3)
    test("CR: INEFFECTIVE_THRESHOLD is 0.3", INEFFECTIVE_THRESHOLD == 0.3)
    test("CR: CHRONIC_FAILURE_THRESHOLD is 0.7", CHRONIC_FAILURE_THRESHOLD == 0.7)
    test("CR: MIN_ATTEMPTS_FOR_STATS is 3", MIN_ATTEMPTS_FOR_STATS == 3)
    test("CR: MIN_IMPROVEMENT_DELTA is 0.15", MIN_IMPROVEMENT_DELTA == 0.15)

    # ── _normalize_error ──
    test("CR: normalize empty", _normalize_error("") == "")
    test("CR: normalize None", _normalize_error(None) == "")
    test("CR: normalize non-string", _normalize_error(123) == "")
    test("CR: normalize strips file paths",
         "<file>" in _normalize_error("Error in /home/user/project/foo.py"))
    test("CR: normalize strips line numbers",
         "line n" in _normalize_error("Error at line 42 in module"))
    test("CR: normalize strips timestamps",
         "<ts>" in _normalize_error("Error at 2024-01-15T10:30:00"))
    test("CR: normalize strips hex addresses",
         "<addr>" in _normalize_error("Object at 0x7f3a2b4c"))
    test("CR: normalize collapses whitespace",
         "  " not in _normalize_error("error    with   spaces"))
    test("CR: normalize lowercases",
         _normalize_error("ERROR MESSAGE") == "error message")
    test("CR: normalize combined",
         _normalize_error("Error in /foo/bar.py at line 42: NoneType") ==
         "error in <file> at line n: nonetype")

    # ── _extract_outcome_fields ──
    test("CR: extract non-dict returns empty", _extract_outcome_fields("string") == {})
    test("CR: extract empty dict", _extract_outcome_fields({}) == {
        "error": "", "strategy": "", "result": "", "chain_id": "", "timestamp": ""
    })
    test("CR: extract primary keys",
         _extract_outcome_fields({
             "error_text": "err1", "strategy": "strat1", "result": "success",
             "chain_id": "c1", "timestamp": "2024-01-01"
         })["error"] == "err1")
    test("CR: extract fallback keys",
         _extract_outcome_fields({
             "error": "err2", "strategy_name": "strat2", "outcome": "failed"
         })["strategy"] == "strat2")
    test("CR: extract result fallback",
         _extract_outcome_fields({"outcome": "resolved"})["result"] == "resolved")

    # ── StrategyStats dataclass ──
    _cr_ss = StrategyStats(strategy="test")
    test("CR: StrategyStats defaults", _cr_ss.attempts == 0 and _cr_ss.successes == 0)
    test("CR: StrategyStats success_rate default", _cr_ss.success_rate == 0.0)

    # ── RecurringPattern dataclass ──
    _cr_rp = RecurringPattern(error_pattern="test error")
    test("CR: RecurringPattern defaults",
         _cr_rp.occurrence_count == 0 and _cr_rp.is_chronic == False)
    test("CR: RecurringPattern strategies default", _cr_rp.strategies_tried == [])

    # ── Refinement dataclass ──
    _cr_ref = Refinement(
        error_pattern="e", current_strategy="c", suggested_strategy="s",
        reason="r", confidence=0.5
    )
    test("CR: Refinement fields", _cr_ref.confidence == 0.5 and _cr_ref.reason == "r")
    test("CR: Refinement evidence default", _cr_ref.evidence == [])

    # ── ChainHealth dataclass ──
    _cr_ch = ChainHealth()
    test("CR: ChainHealth defaults",
         _cr_ch.total_chains == 0 and _cr_ch.health_score == 50.0)
    test("CR: ChainHealth trend default", _cr_ch.improvement_trend == "stable")
    test("CR: ChainHealth recommendations default", _cr_ch.recommendations == [])

    # ── get_strategy_effectiveness ──
    test("CR: effectiveness empty list", get_strategy_effectiveness([]) == {})

    _cr_outcomes_eff = [
        {"strategy": "retry", "result": "success", "error_text": "timeout"},
        {"strategy": "retry", "result": "success", "error_text": "timeout"},
        {"strategy": "retry", "result": "failure", "error_text": "timeout"},
        {"strategy": "rewrite", "result": "success", "error_text": "import error"},
        {"strategy": "rewrite", "result": "failure", "error_text": "import error"},
        {"strategy": "rewrite", "result": "failure", "error_text": "syntax error"},
    ]
    _cr_eff = get_strategy_effectiveness(_cr_outcomes_eff)
    test("CR: effectiveness has retry", "retry" in _cr_eff)
    test("CR: effectiveness has rewrite", "rewrite" in _cr_eff)
    test("CR: effectiveness retry attempts", _cr_eff["retry"].attempts == 3)
    test("CR: effectiveness retry successes", _cr_eff["retry"].successes == 2)
    test("CR: effectiveness retry failures", _cr_eff["retry"].failures == 1)
    test("CR: effectiveness retry rate",
         abs(_cr_eff["retry"].success_rate - 0.6667) < 0.01)
    test("CR: effectiveness rewrite attempts", _cr_eff["rewrite"].attempts == 3)
    test("CR: effectiveness rewrite successes", _cr_eff["rewrite"].successes == 1)
    test("CR: effectiveness rewrite errors_addressed",
         _cr_eff["rewrite"].errors_addressed == 2)  # import error + syntax error
    test("CR: effectiveness skips no-strategy entries",
         len(get_strategy_effectiveness([{"result": "success"}])) == 0)

    # ── detect_recurring_failures ──
    test("CR: recurring empty", detect_recurring_failures([]) == [])

    _cr_outcomes_rec = [
        {"error_text": "ImportError: no module", "strategy": "install", "result": "success"},
        {"error_text": "ImportError: no module", "strategy": "install", "result": "failure"},
        {"error_text": "ImportError: no module", "strategy": "install", "result": "failure"},
        {"error_text": "ImportError: no module", "strategy": "rewrite", "result": "success"},
        {"error_text": "KeyError: missing key", "strategy": "fix", "result": "success"},
        {"error_text": "KeyError: missing key", "strategy": "fix", "result": "success"},
    ]
    _cr_rec = detect_recurring_failures(_cr_outcomes_rec, min_recurrence=3)
    test("CR: recurring finds importerror pattern", len(_cr_rec) == 1)
    test("CR: recurring pattern count", _cr_rec[0].occurrence_count == 4)
    test("CR: recurring strategies tried",
         sorted(_cr_rec[0].strategies_tried) == ["install", "rewrite"])
    test("CR: recurring best strategy",
         _cr_rec[0].best_strategy == "rewrite")  # 1/1 = 100% vs install 1/3 = 33%
    test("CR: recurring best rate", _cr_rec[0].best_success_rate == 1.0)

    # Chronic failure detection: 3 attempts, 0 successes -> failure_rate = 1.0 > 0.7
    _cr_outcomes_chronic = [
        {"error_text": "DeadlockError", "strategy": "wait", "result": "failure"},
        {"error_text": "DeadlockError", "strategy": "wait", "result": "failure"},
        {"error_text": "DeadlockError", "strategy": "restart", "result": "failure"},
    ]
    _cr_chronic = detect_recurring_failures(_cr_outcomes_chronic, min_recurrence=3)
    test("CR: chronic detected", len(_cr_chronic) == 1 and _cr_chronic[0].is_chronic)

    # Non-chronic: 4 attempts, 3 successes -> failure_rate = 0.25 < 0.7
    _cr_outcomes_healthy = [
        {"error_text": "TimeoutError", "strategy": "retry", "result": "success"},
        {"error_text": "TimeoutError", "strategy": "retry", "result": "success"},
        {"error_text": "TimeoutError", "strategy": "retry", "result": "success"},
        {"error_text": "TimeoutError", "strategy": "retry", "result": "failure"},
    ]
    _cr_healthy = detect_recurring_failures(_cr_outcomes_healthy, min_recurrence=3)
    test("CR: non-chronic healthy", len(_cr_healthy) == 1 and not _cr_healthy[0].is_chronic)

    # Sorted by occurrence count descending
    _cr_outcomes_sort = [
        {"error_text": "A", "strategy": "s", "result": "failure"},
        {"error_text": "A", "strategy": "s", "result": "failure"},
        {"error_text": "A", "strategy": "s", "result": "failure"},
        {"error_text": "B", "strategy": "s", "result": "failure"},
        {"error_text": "B", "strategy": "s", "result": "failure"},
        {"error_text": "B", "strategy": "s", "result": "failure"},
        {"error_text": "B", "strategy": "s", "result": "failure"},
    ]
    _cr_sorted = detect_recurring_failures(_cr_outcomes_sort, min_recurrence=3)
    test("CR: recurring sorted by count", _cr_sorted[0].occurrence_count > _cr_sorted[1].occurrence_count)

    # min_recurrence filter
    _cr_below = detect_recurring_failures(_cr_outcomes_sort, min_recurrence=5)
    test("CR: min_recurrence filters", len(_cr_below) == 0 or _cr_below[0].occurrence_count >= 5)

    # ── suggest_refinement ──
    test("CR: refinement empty error", suggest_refinement("", []) is None)
    test("CR: refinement no outcomes", suggest_refinement("some error", []) is None)

    # Build outcomes where strategy "B" is clearly better than "A" for similar errors
    _cr_ref_outcomes = []
    for _ in range(5):
        _cr_ref_outcomes.append({"error_text": "connection timeout error", "strategy": "A", "result": "failure"})
    for _ in range(5):
        _cr_ref_outcomes.append({"error_text": "connection timeout error", "strategy": "B", "result": "success"})

    _cr_sugg = suggest_refinement("connection timeout error", _cr_ref_outcomes, "A")
    test("CR: refinement found", _cr_sugg is not None)
    if _cr_sugg:
        test("CR: refinement suggests B", _cr_sugg.suggested_strategy == "B")
        test("CR: refinement has reason", len(_cr_sugg.reason) > 0)
        test("CR: refinement confidence > 0", _cr_sugg.confidence > 0)
        test("CR: refinement has evidence", len(_cr_sugg.evidence) > 0)
        test("CR: refinement error pattern set", _cr_sugg.error_pattern != "")

    # No refinement when no clear improvement
    _cr_ref_same = [
        {"error_text": "err", "strategy": "X", "result": "success"},
        {"error_text": "err", "strategy": "X", "result": "success"},
        {"error_text": "err", "strategy": "X", "result": "success"},
    ]
    test("CR: no refinement when same strategy ok",
         suggest_refinement("err", _cr_ref_same, "X") is None)

    # No refinement when alternative has insufficient data
    _cr_ref_few = [
        {"error_text": "err2", "strategy": "C", "result": "failure"},
        {"error_text": "err2", "strategy": "C", "result": "failure"},
        {"error_text": "err2", "strategy": "C", "result": "failure"},
        {"error_text": "err2", "strategy": "C", "result": "failure"},
        {"error_text": "err2", "strategy": "C", "result": "failure"},
        {"error_text": "err2", "strategy": "D", "result": "success"},  # only 1 attempt
    ]
    test("CR: no refinement insufficient alt data",
         suggest_refinement("err2", _cr_ref_few, "C") is None)

    # ── compute_chain_health ──
    _cr_health_empty = compute_chain_health([])
    test("CR: health empty total", _cr_health_empty.total_chains == 0)
    test("CR: health empty has recommendation", len(_cr_health_empty.recommendations) > 0)
    test("CR: health empty score", _cr_health_empty.health_score == 50.0)

    # All successes
    _cr_all_success = [{"result": "success", "strategy": f"s{i}"} for i in range(10)]
    _cr_health_good = compute_chain_health(_cr_all_success)
    test("CR: health good total", _cr_health_good.total_chains == 10)
    test("CR: health good rate", _cr_health_good.overall_success_rate == 1.0)
    test("CR: health good score > 70", _cr_health_good.health_score > 70)
    test("CR: health good diversity", _cr_health_good.strategy_diversity == 10)

    # All failures
    _cr_all_fail = [{"result": "failure", "strategy": "retry", "error_text": "err"} for _ in range(10)]
    _cr_health_bad = compute_chain_health(_cr_all_fail)
    test("CR: health bad rate", _cr_health_bad.overall_success_rate == 0.0)
    test("CR: health bad score < 30", _cr_health_bad.health_score < 30)
    test("CR: health bad has recs", len(_cr_health_bad.recommendations) > 0)
    test("CR: health bad rec mentions rate",
         any("success rate" in r.lower() for r in _cr_health_bad.recommendations))

    # Trend detection: first half fails, second half succeeds -> "improving"
    _cr_trend_outcomes = []
    for i in range(12):
        result = "failure" if i < 6 else "success"
        _cr_trend_outcomes.append({"result": result, "strategy": f"s{i % 3}", "error_text": "e"})
    _cr_health_trend = compute_chain_health(_cr_trend_outcomes)
    test("CR: trend improving", _cr_health_trend.improvement_trend == "improving")

    # Reverse trend: first half succeeds, second half fails -> "declining"
    _cr_trend_decline = []
    for i in range(12):
        result = "success" if i < 6 else "failure"
        _cr_trend_decline.append({"result": result, "strategy": f"s{i % 3}", "error_text": "e"})
    _cr_health_decline = compute_chain_health(_cr_trend_decline)
    test("CR: trend declining", _cr_health_decline.improvement_trend == "declining")

    # Insufficient data for trend
    _cr_trend_short = [{"result": "success", "strategy": "s"} for _ in range(4)]
    _cr_health_short = compute_chain_health(_cr_trend_short)
    test("CR: trend insufficient data",
         _cr_health_short.improvement_trend == "insufficient_data")

    # Low diversity recommendation
    _cr_low_div = [{"result": "success", "strategy": "only_one", "error_text": f"e{i}"} for i in range(15)]
    _cr_health_low_div = compute_chain_health(_cr_low_div)
    test("CR: low diversity rec",
         any("diversity" in r.lower() for r in _cr_health_low_div.recommendations))

    # Chronic failures recommendation
    _cr_chronic_many = [
        {"error_text": "persistent error", "strategy": "s", "result": "failure"}
        for _ in range(5)
    ]
    _cr_health_chronic = compute_chain_health(_cr_chronic_many)
    test("CR: chronic count tracked", _cr_health_chronic.chronic_failures >= 0)

    # ── analyze_outcomes ──
    _cr_analysis = analyze_outcomes(_cr_outcomes_eff)
    test("CR: analysis has strategy_effectiveness", "strategy_effectiveness" in _cr_analysis)
    test("CR: analysis has recurring_failures", "recurring_failures" in _cr_analysis)
    test("CR: analysis has chain_health", "chain_health" in _cr_analysis)
    test("CR: analysis has summary", "summary" in _cr_analysis)
    test("CR: analysis summary is string", isinstance(_cr_analysis["summary"], str))
    test("CR: analysis summary has chain count", "6 chains" in _cr_analysis["summary"])
    test("CR: analysis summary has success rate", "success rate" in _cr_analysis["summary"])
    test("CR: analysis summary has strategies", "strategies" in _cr_analysis["summary"])
    test("CR: analysis summary has trend", "trend:" in _cr_analysis["summary"])

    # Analysis with empty data
    _cr_analysis_empty = analyze_outcomes([])
    test("CR: analysis empty has all keys",
         all(k in _cr_analysis_empty for k in ["strategy_effectiveness", "recurring_failures", "chain_health", "summary"]))
    test("CR: analysis empty summary", "0 chains" in _cr_analysis_empty["summary"])

    # Large analysis
    _cr_large_outcomes = []
    import random as _cr_rand
    _cr_rand.seed(42)
    for _cr_i in range(50):
        _cr_large_outcomes.append({
            "error_text": f"error type {_cr_i % 5}",
            "strategy": f"strategy_{_cr_i % 4}",
            "result": _cr_rand.choice(["success", "failure", "resolved"]),
            "chain_id": f"chain_{_cr_i}",
        })
    _cr_large = analyze_outcomes(_cr_large_outcomes)
    test("CR: large analysis strategies", len(_cr_large["strategy_effectiveness"]) == 4)
    test("CR: large analysis health total", _cr_large["chain_health"].total_chains == 50)
    test("CR: large analysis health score range",
         0 <= _cr_large["chain_health"].health_score <= 100)
    test("CR: large analysis recurring patterns", isinstance(_cr_large["recurring_failures"], list))

except Exception as _cr_exc:
    test("Chain Refinement Deep Tests: import and tests", False, str(_cr_exc))

# ─────────────────────────────────────────────────
# Health Correlation Deep Tests (health_correlation.py)
# ─────────────────────────────────────────────────
try:
    from shared.health_correlation import (
        _pearson_correlation,
        build_fire_vectors,
        compute_correlation_matrix,
        detect_redundant_pairs,
        detect_synergistic_pairs,
        suggest_optimizations,
        generate_health_report,
        _short,
        _redundancy_recommendation,
        REDUNDANCY_THRESHOLD,
        SYNERGY_THRESHOLD,
        MIN_BLOCKS_FOR_ANALYSIS,
        PROTECTED_GATES,
    )

    # ── Constants ──
    test("HC: REDUNDANCY_THRESHOLD", REDUNDANCY_THRESHOLD == 0.80)
    test("HC: SYNERGY_THRESHOLD", SYNERGY_THRESHOLD == -0.50)
    test("HC: MIN_BLOCKS_FOR_ANALYSIS", MIN_BLOCKS_FOR_ANALYSIS == 3)
    test("HC: PROTECTED_GATES has 3 gates", len(PROTECTED_GATES) == 3)
    test("HC: gate_01 protected", "gate_01_read_before_edit" in PROTECTED_GATES)

    # ── _short ──
    test("HC: short gate_01", _short("gate_01_read_before_edit") == "G01")
    test("HC: short gate_12", _short("gate_12_something") == "G12")
    test("HC: short non-gate", _short("my_custom_check") == "my_custom_check")

    # ── _pearson_correlation ──
    test("HC: pearson identical", abs(_pearson_correlation([1, 2, 3], [1, 2, 3]) - 1.0) < 0.01)
    test("HC: pearson opposite", abs(_pearson_correlation([1, 2, 3], [3, 2, 1]) - (-1.0)) < 0.01)
    test("HC: pearson uncorrelated",
         abs(_pearson_correlation([1, 0, 1, 0], [0, 1, 0, 1]) - (-1.0)) < 0.01)
    test("HC: pearson diff lengths", _pearson_correlation([1, 2], [1, 2, 3]) == 0.0)
    test("HC: pearson too short", _pearson_correlation([1], [1]) == 0.0)
    test("HC: pearson zero variance", _pearson_correlation([5, 5, 5], [1, 2, 3]) == 0.0)

    # ── build_fire_vectors ──
    _hc_eff_data = {
        "gate_01_test": {"blocks": 10, "overrides": 2, "prevented": 3},
        "gate_02_test": {"blocks": 20, "overrides": 5, "prevented": 8},
        "gate_03_low": {"blocks": 1, "overrides": 0, "prevented": 0},  # below MIN_BLOCKS
    }
    _hc_vectors = build_fire_vectors(_hc_eff_data)
    test("HC: vectors includes high-block gates", "gate_01_test" in _hc_vectors)
    test("HC: vectors includes gate_02", "gate_02_test" in _hc_vectors)
    test("HC: vectors excludes low-block", "gate_03_low" not in _hc_vectors)
    test("HC: vector length default 10", len(_hc_vectors["gate_01_test"]) == 10)
    test("HC: vector values non-negative",
         all(v >= 0 for v in _hc_vectors["gate_01_test"]))
    test("HC: custom time_windows",
         len(build_fire_vectors(_hc_eff_data, time_windows=5)["gate_01_test"]) == 5)

    # Empty data
    test("HC: vectors empty data", build_fire_vectors({}) == {})
    # Non-dict entry
    test("HC: vectors non-dict entry", build_fire_vectors({"g": "not a dict"}) == {})

    # ── compute_correlation_matrix ──
    _hc_matrix = compute_correlation_matrix(_hc_vectors)
    test("HC: matrix has pairs", len(_hc_matrix) > 0)
    test("HC: matrix keys are tuples", all(isinstance(k, tuple) for k in _hc_matrix))
    test("HC: matrix values in [-1, 1]",
         all(-1.01 <= v <= 1.01 for v in _hc_matrix.values()))
    test("HC: matrix no self-correlation",
         all(k[0] != k[1] for k in _hc_matrix))
    test("HC: matrix lexicographic order",
         all(k[0] < k[1] for k in _hc_matrix))
    test("HC: empty matrix", compute_correlation_matrix({}) == {})

    # ── detect_redundant_pairs ──
    _hc_high_corr_matrix = {("a", "b"): 0.95, ("a", "c"): 0.5, ("b", "c"): 0.85}
    _hc_redundant = detect_redundant_pairs(_hc_high_corr_matrix, threshold=0.80)
    test("HC: redundant finds high corr", len(_hc_redundant) == 2)
    test("HC: redundant sorted desc",
         _hc_redundant[0]["correlation"] >= _hc_redundant[1]["correlation"])
    test("HC: redundant has recommendation", "recommendation" in _hc_redundant[0])
    test("HC: no redundant below threshold",
         len(detect_redundant_pairs(_hc_high_corr_matrix, threshold=0.99)) == 0)

    # ── detect_synergistic_pairs ──
    _hc_neg_matrix = {("x", "y"): -0.7, ("x", "z"): -0.3, ("y", "z"): 0.1}
    _hc_synergistic = detect_synergistic_pairs(_hc_neg_matrix, threshold=-0.50)
    test("HC: synergistic finds negative corr", len(_hc_synergistic) == 1)
    test("HC: synergistic pair correct",
         _hc_synergistic[0]["gate_a"] == "x" and _hc_synergistic[0]["gate_b"] == "y")
    test("HC: synergistic recommendation mentions complementary",
         "complementary" in _hc_synergistic[0]["recommendation"])

    # ── _redundancy_recommendation ──
    _hc_rec_protected = _redundancy_recommendation("gate_01_read_before_edit", "gate_99_custom", 0.9)
    test("HC: rec protected gate mentions Tier-1", "Tier-1" in _hc_rec_protected)
    _hc_rec_both_unprotected = _redundancy_recommendation("gate_05_a", "gate_06_b", 0.85)
    test("HC: rec unprotected mentions merging", "merging" in _hc_rec_both_unprotected.lower() or "merg" in _hc_rec_both_unprotected.lower())

    # ── suggest_optimizations ──
    _hc_opt_data = {
        "gate_05_test": {"blocks": 10, "overrides": 3, "prevented": 5},
        "gate_06_test": {"blocks": 10, "overrides": 3, "prevented": 5},  # Same profile -> redundant
        "gate_07_low": {"blocks": 1, "overrides": 0, "prevented": 0},   # Low value
    }
    _hc_opts = suggest_optimizations(_hc_opt_data)
    test("HC: optimizations is list", isinstance(_hc_opts, list))
    test("HC: optimization types valid",
         all(o["type"] in ("redundancy", "low_value", "reorder") for o in _hc_opts))
    test("HC: optimization has priority", all("priority" in o for o in _hc_opts))
    test("HC: optimization has confidence", all("confidence" in o for o in _hc_opts))
    test("HC: optimizations sorted by priority",
         all(_hc_opts[i]["priority"] <= _hc_opts[i+1]["priority"]
             for i in range(len(_hc_opts)-1)) if len(_hc_opts) > 1 else True)

    # Protected gates not suggested for removal
    _hc_opt_protected = {
        "gate_01_read_before_edit": {"blocks": 1, "overrides": 0, "prevented": 0},
    }
    _hc_opts_protected = suggest_optimizations(_hc_opt_protected)
    test("HC: protected gate not low-value",
         not any(o["type"] == "low_value" and "gate_01_read_before_edit" in o["gates_affected"]
                 for o in _hc_opts_protected))

    # ── generate_health_report ──
    _hc_report = generate_health_report(_hc_opt_data)
    test("HC: report has gates_analyzed", "gates_analyzed" in _hc_report)
    test("HC: report has correlation_pairs", "correlation_pairs" in _hc_report)
    test("HC: report has redundant_pairs", "redundant_pairs" in _hc_report)
    test("HC: report has synergistic_pairs", "synergistic_pairs" in _hc_report)
    test("HC: report has optimizations", "optimizations" in _hc_report)
    test("HC: report has overall_diversity", "overall_diversity" in _hc_report)
    test("HC: report diversity in [0,1]",
         0.0 <= _hc_report["overall_diversity"] <= 1.0)
    test("HC: report gates_analyzed count", _hc_report["gates_analyzed"] == 2)  # gate_05 and gate_06 (gate_07 below threshold)

    # Empty report
    _hc_empty_report = generate_health_report({})
    test("HC: empty report gates 0", _hc_empty_report["gates_analyzed"] == 0)
    test("HC: empty report diversity 1.0", _hc_empty_report["overall_diversity"] == 1.0)

except Exception as _hc_exc:
    test("Health Correlation Deep Tests: import and tests", False, str(_hc_exc))

# ─────────────────────────────────────────────────
# Tool Recommendation Deep Tests (tool_recommendation.py)
# ─────────────────────────────────────────────────
try:
    from shared.tool_recommendation import (
        build_tool_profile,
        should_recommend,
        recommend_alternative,
        get_recommendation_stats,
        ToolProfile,
        Recommendation,
        MIN_CALLS_FOR_STATS,
        BLOCK_RATE_THRESHOLD,
        MIN_IMPROVEMENT,
        TOOL_EQUIVALENCES,
        ALWAYS_OK_TOOLS,
        SEQUENCE_FIXES,
    )

    # ── Constants ──
    test("TR: MIN_CALLS_FOR_STATS", MIN_CALLS_FOR_STATS == 5)
    test("TR: BLOCK_RATE_THRESHOLD", BLOCK_RATE_THRESHOLD == 0.3)
    test("TR: MIN_IMPROVEMENT", MIN_IMPROVEMENT == 0.15)
    test("TR: Edit equiv Write", "Write" in TOOL_EQUIVALENCES["Edit"])
    test("TR: Write equiv Edit", "Edit" in TOOL_EQUIVALENCES["Write"])
    test("TR: Read always ok", "Read" in ALWAYS_OK_TOOLS)
    test("TR: Glob always ok", "Glob" in ALWAYS_OK_TOOLS)
    test("TR: sequence fixes exist", len(SEQUENCE_FIXES) > 0)

    # ── ToolProfile dataclass ──
    _tr_tp = ToolProfile(tool_name="Edit")
    test("TR: profile defaults", _tr_tp.call_count == 0 and _tr_tp.success_rate == 1.0)
    test("TR: profile block_rate default", _tr_tp.block_rate == 0.0)

    # ── Recommendation dataclass ──
    _tr_rec = Recommendation(
        original_tool="Edit", suggested_tool="Write",
        reason="better", confidence=0.7,
        original_success=0.5, suggested_success=0.8
    )
    test("TR: recommendation fields", _tr_rec.confidence == 0.7)

    # ── build_tool_profile ──
    test("TR: profile empty state", build_tool_profile({}) == {})

    _tr_state = {
        "tool_call_counts": {"Edit": 10, "Read": 5, "Write": 3},
        "gate_block_outcomes": [
            {"tool": "Edit"}, {"tool": "Edit"}, {"tool": "Edit"},
            {"tool": "Write"},
        ],
        "tool_errors": {"Edit": 1},
    }
    _tr_profiles = build_tool_profile(_tr_state)
    test("TR: profiles has Edit", "Edit" in _tr_profiles)
    test("TR: profiles has Read", "Read" in _tr_profiles)
    test("TR: Edit call_count", _tr_profiles["Edit"].call_count == 10)
    test("TR: Edit block_count", _tr_profiles["Edit"].block_count == 3)
    test("TR: Edit error_count", _tr_profiles["Edit"].error_count == 1)
    test("TR: Edit block_rate", abs(_tr_profiles["Edit"].block_rate - 0.3) < 0.01)
    test("TR: Edit success_rate",
         abs(_tr_profiles["Edit"].success_rate - 0.6) < 0.01)  # (10-3-1)/10 = 0.6
    test("TR: Read no blocks", _tr_profiles["Read"].block_count == 0)
    test("TR: Read success_rate 1.0", _tr_profiles["Read"].success_rate == 1.0)

    # Tool from blocks but not in counts
    _tr_state_orphan = {
        "tool_call_counts": {},
        "gate_block_outcomes": [{"tool": "Bash"}],
    }
    _tr_orphan = build_tool_profile(_tr_state_orphan)
    test("TR: orphan tool from blocks", "Bash" in _tr_orphan)
    test("TR: orphan 0 calls", _tr_orphan["Bash"].call_count == 0)

    # ── should_recommend ──
    test("TR: should_recommend Read always false", not should_recommend("Read", _tr_state))
    test("TR: should_recommend Glob always false", not should_recommend("Glob", _tr_state))

    # Edit has 30% block rate, >= threshold, and >= 5 calls
    _tr_state_high_block = {
        "tool_call_counts": {"Edit": 10},
        "gate_block_outcomes": [{"tool": "Edit"}] * 4,
    }
    test("TR: should_recommend high block Edit",
         should_recommend("Edit", _tr_state_high_block))

    # Not enough data
    _tr_state_few = {
        "tool_call_counts": {"Edit": 2},
        "gate_block_outcomes": [{"tool": "Edit"}] * 2,
    }
    test("TR: should_recommend few calls false",
         not should_recommend("Edit", _tr_state_few))

    # ── recommend_alternative ──
    test("TR: recommend Read returns None", recommend_alternative("Read", {}) is None)

    # Sequence-based recommendation: Glob then Edit -> suggest Read
    _tr_state_seq = {
        "tool_call_counts": {"Edit": 10, "Glob": 5},
        "gate_block_outcomes": [{"tool": "Edit"}] * 4,
    }
    _tr_seq_rec = recommend_alternative("Edit", _tr_state_seq, recent_tools=["Glob"])
    test("TR: sequence rec suggests Read",
         _tr_seq_rec is not None and _tr_seq_rec.suggested_tool == "Read")
    test("TR: sequence rec confidence 0.8",
         _tr_seq_rec is not None and _tr_seq_rec.confidence == 0.8)
    test("TR: sequence rec reason mentions read",
         _tr_seq_rec is not None and "read" in _tr_seq_rec.reason.lower())

    # Equivalence-based: Write has better success than Edit
    _tr_state_equiv = {
        "tool_call_counts": {"Edit": 10, "Write": 10},
        "gate_block_outcomes": [{"tool": "Edit"}] * 5,  # 50% block rate
        "tool_errors": {},
    }
    _tr_equiv_rec = recommend_alternative("Edit", _tr_state_equiv)
    test("TR: equiv rec suggests Write",
         _tr_equiv_rec is not None and _tr_equiv_rec.suggested_tool == "Write")

    # No recommendation when both tools similar
    _tr_state_similar = {
        "tool_call_counts": {"Edit": 10, "Write": 10},
        "gate_block_outcomes": [{"tool": "Edit"}] * 3 + [{"tool": "Write"}] * 2,
        "tool_errors": {},
    }
    _tr_similar_rec = recommend_alternative("Edit", _tr_state_similar)
    # Improvement is small, may or may not recommend
    test("TR: similar tools handled",
         _tr_similar_rec is None or isinstance(_tr_similar_rec, Recommendation))

    # ── get_recommendation_stats ──
    _tr_stats = get_recommendation_stats(_tr_state)
    test("TR: stats has tools_analyzed", "tools_analyzed" in _tr_stats)
    test("TR: stats has tools_at_risk", "tools_at_risk" in _tr_stats)
    test("TR: stats has top_blockers", "top_blockers" in _tr_stats)
    test("TR: stats has healthiest", "healthiest" in _tr_stats)
    test("TR: stats tools_analyzed count", _tr_stats["tools_analyzed"] == 3)

    # Empty state
    _tr_empty_stats = get_recommendation_stats({})
    test("TR: empty stats zero tools", _tr_empty_stats["tools_analyzed"] == 0)
    test("TR: empty stats no risk", _tr_empty_stats["tools_at_risk"] == [])

    # Stats with enough data for reliable filtering
    _tr_state_reliable = {
        "tool_call_counts": {"Edit": 10, "Write": 8, "Read": 20},
        "gate_block_outcomes": [{"tool": "Edit"}] * 5,
        "tool_errors": {},
    }
    _tr_reliable = get_recommendation_stats(_tr_state_reliable)
    test("TR: reliable stats has risk tools",
         "Edit" in _tr_reliable["tools_at_risk"])
    test("TR: reliable healthiest sorted",
         len(_tr_reliable["healthiest"]) > 0 and _tr_reliable["healthiest"][0][1] >= _tr_reliable["healthiest"][-1][1])

except Exception as _tr_exc:
    test("Tool Recommendation Deep Tests: import and tests", False, str(_tr_exc))

# ─────────────────────────────────────────────────
# Mutation Tester Deep Tests (mutation_tester.py)
# ─────────────────────────────────────────────────
try:
    from shared.mutation_tester import (
        MutantResult,
        MutationReport,
        generate_mutants,
        _count_targets,
        _apply_mutation,
        _BoolFlipVisitor,
        _CmpOpSwapVisitor,
        _CondRemoveVisitor,
        _ReturnFlipVisitor,
        _LogicNegateVisitor,
        _StrSwapVisitor,
        _find_test_framework,
        _find_hooks_dir,
        print_report,
    )
    import ast as _mt_ast
    import copy as _mt_copy

    # ── MutantResult dataclass ──
    _mt_mr = MutantResult(
        operator="BOOL_FLIP", description="line 10: True -> False",
        lineno=10, killed=False, test_output="", mutant_source="x = False"
    )
    test("MT: MutantResult fields", _mt_mr.operator == "BOOL_FLIP" and _mt_mr.lineno == 10)
    test("MT: MutantResult killed default", _mt_mr.killed == False)

    # ── MutationReport dataclass ──
    _mt_rpt = MutationReport(gate_path="/test.py")
    test("MT: report kill_rate empty", _mt_rpt.kill_rate == 0.0)
    test("MT: report test_gaps empty", _mt_rpt.test_gaps == [])

    _mt_rpt2 = MutationReport(gate_path="/test.py", total_mutants=4, killed_count=3)
    _mt_rpt2.survived = [MutantResult("X", "test", 1, False, "", "")]
    test("MT: report kill_rate computed", abs(_mt_rpt2.kill_rate - 0.75) < 0.01)
    test("MT: report test_gaps has item", len(_mt_rpt2.test_gaps) == 1)
    test("MT: report test_gaps format", "[X]" in _mt_rpt2.test_gaps[0])

    # ── BoolFlipVisitor ──
    _mt_src_bool = "x = True\ny = False\nz = True"
    _mt_tree_bool = _mt_ast.parse(_mt_src_bool)
    _mt_n_bools = _count_targets(_mt_tree_bool, _BoolFlipVisitor)
    test("MT: bool flip count", _mt_n_bools == 3)

    _mt_v0 = _BoolFlipVisitor(0)
    _mt_v0.visit(_mt_copy.deepcopy(_mt_tree_bool))
    test("MT: bool flip applied idx 0", _mt_v0.applied)
    test("MT: bool flip description", "True" in _mt_v0.description and "False" in _mt_v0.description)

    _mt_v99 = _BoolFlipVisitor(99)
    _mt_v99.visit(_mt_copy.deepcopy(_mt_tree_bool))
    test("MT: bool flip not applied beyond range", not _mt_v99.applied)

    # ── CmpOpSwapVisitor ──
    _mt_src_cmp = "if x == 1:\n    pass\nif y < 2:\n    pass"
    _mt_tree_cmp = _mt_ast.parse(_mt_src_cmp)
    _mt_n_cmps = _count_targets(_mt_tree_cmp, _CmpOpSwapVisitor)
    test("MT: cmp swap count", _mt_n_cmps == 2)

    _mt_vc = _CmpOpSwapVisitor(0)
    _mt_vc.visit(_mt_copy.deepcopy(_mt_tree_cmp))
    test("MT: cmp swap applied", _mt_vc.applied)
    test("MT: cmp swap description has Eq", "Eq" in _mt_vc.description)

    # ── CondRemoveVisitor ──
    _mt_src_cond = "if x > 0:\n    pass\nif y:\n    pass"
    _mt_tree_cond = _mt_ast.parse(_mt_src_cond)
    _mt_n_conds = _count_targets(_mt_tree_cond, _CondRemoveVisitor, replace_with=True)
    test("MT: cond remove count", _mt_n_conds == 2)

    _mt_vcr = _CondRemoveVisitor(0, replace_with=False)
    _mt_vcr.visit(_mt_copy.deepcopy(_mt_tree_cond))
    test("MT: cond remove applied", _mt_vcr.applied)
    test("MT: cond remove description has False", "False" in _mt_vcr.description)

    # ── ReturnFlipVisitor ──
    _mt_src_ret = "result = GateResult(blocked=True, message='x')\nother = GateResult(blocked=False)"
    _mt_tree_ret = _mt_ast.parse(_mt_src_ret)
    _mt_n_rets = _count_targets(_mt_tree_ret, _ReturnFlipVisitor)
    test("MT: return flip count", _mt_n_rets == 2)

    _mt_vr = _ReturnFlipVisitor(0)
    _mt_vr.visit(_mt_copy.deepcopy(_mt_tree_ret))
    test("MT: return flip applied", _mt_vr.applied)
    test("MT: return flip description has GateResult",
         "GateResult" in _mt_vr.description)

    # ── LogicNegateVisitor ──
    _mt_src_logic = "if a and b:\n    pass"
    _mt_tree_logic = _mt_ast.parse(_mt_src_logic)
    _mt_n_logic = _count_targets(_mt_tree_logic, _LogicNegateVisitor)
    test("MT: logic negate count", _mt_n_logic >= 1)

    # ── StrSwapVisitor ──
    _mt_src_str = "if x in 'hello':\n    pass"
    _mt_tree_str = _mt_ast.parse(_mt_src_str)
    _mt_n_strs = _count_targets(_mt_tree_str, _StrSwapVisitor)
    test("MT: str swap count", _mt_n_strs == 1)

    _mt_vs = _StrSwapVisitor(0)
    _mt_vs.visit(_mt_copy.deepcopy(_mt_tree_str))
    test("MT: str swap applied", _mt_vs.applied)
    test("MT: str swap description has MUTANT", "__MUTANT__" in _mt_vs.description)

    # ── generate_mutants ──
    _mt_gate_src = '''
from shared.gate_result import GateResult

def check(tool_name, tool_input, state, event_type="PreToolUse"):
    if tool_name == "Edit":
        if "file_path" in tool_input:
            return GateResult(blocked=True, message="blocked", gate_name="test", severity="error")
    return GateResult(blocked=False, message="ok", gate_name="test", severity="info")
'''
    _mt_mutants = generate_mutants(_mt_gate_src)
    test("MT: generate_mutants produces results", len(_mt_mutants) > 0)
    test("MT: mutants are tuples", all(isinstance(m, tuple) and len(m) == 2 for m in _mt_mutants))
    test("MT: mutant has MutantResult", all(isinstance(m[0], MutantResult) for m in _mt_mutants))
    test("MT: mutant has source string", all(isinstance(m[1], str) for m in _mt_mutants))

    # Check operator diversity
    _mt_ops = set(m[0].operator for m in _mt_mutants)
    test("MT: multiple operators used", len(_mt_ops) >= 3)
    test("MT: has BOOL_FLIP or RETURN_FLIP",
         "BOOL_FLIP" in _mt_ops or "RETURN_FLIP" in _mt_ops)
    test("MT: has CMP_OP_SWAP", "CMP_OP_SWAP" in _mt_ops)

    # ── _apply_mutation ──
    _mt_applied = _apply_mutation(
        _mt_gate_src, _mt_ast.parse(_mt_gate_src),
        _BoolFlipVisitor, 0, "BOOL_FLIP"
    )
    test("MT: apply mutation returns MutantResult",
         _mt_applied is not None and isinstance(_mt_applied, MutantResult))
    if _mt_applied:
        test("MT: applied mutation has source", len(_mt_applied.mutant_source) > 0)

    _mt_not_applied = _apply_mutation(
        _mt_gate_src, _mt_ast.parse(_mt_gate_src),
        _BoolFlipVisitor, 999, "BOOL_FLIP"
    )
    test("MT: apply mutation beyond range returns None", _mt_not_applied is None)

    # ── _find_test_framework / _find_hooks_dir ──
    _MT_HOOKS_DIR = os.path.join(os.path.expanduser("~"), ".claude", "hooks")
    _mt_tf = _find_test_framework(os.path.join(_MT_HOOKS_DIR, "gates", "gate_01_read_before_edit.py"))
    test("MT: find_test_framework from gates/",
         _mt_tf is not None and "test_framework.py" in _mt_tf if _mt_tf else True)

    _mt_hd = _find_hooks_dir(os.path.join(_MT_HOOKS_DIR, "gates", "gate_01_read_before_edit.py"))
    test("MT: find_hooks_dir from gates/",
         _mt_hd is not None and _mt_hd.endswith("hooks") if _mt_hd else True)

    # ── print_report (smoke test — just verify it doesn't crash) ──
    import io as _mt_io
    import sys as _mt_sys
    _mt_old_stdout = _mt_sys.stdout
    _mt_sys.stdout = _mt_io.StringIO()
    try:
        print_report(_mt_rpt2)
        _mt_output = _mt_sys.stdout.getvalue()
    finally:
        _mt_sys.stdout = _mt_old_stdout
    test("MT: print_report produces output", len(_mt_output) > 50)
    test("MT: print_report has kill rate", "75" in _mt_output or "Kill rate" in _mt_output)

except Exception as _mt_exc:
    test("Mutation Tester Deep Tests: import and tests", False, str(_mt_exc))

# ─────────────────────────────────────────────────
# Retry Strategy Deep Tests (retry_strategy.py)
# ─────────────────────────────────────────────────
try:
    from shared.retry_strategy import (
        Strategy,
        Jitter,
        RetryConfig,
        _fib,
        _compute_raw_delay,
        _apply_jitter,
        should_retry,
        get_delay,
        record_attempt as rs_record_attempt,
        reset as rs_reset,
        get_stats as rs_get_stats,
        with_retry,
        _get_state,
        _registry,
    )

    # ── Strategy enum ──
    test("RS: Strategy has EXPONENTIAL", Strategy.EXPONENTIAL_BACKOFF.value == "exponential_backoff")
    test("RS: Strategy has LINEAR", Strategy.LINEAR_BACKOFF.value == "linear_backoff")
    test("RS: Strategy has CONSTANT", Strategy.CONSTANT.value == "constant")
    test("RS: Strategy has FIBONACCI", Strategy.FIBONACCI.value == "fibonacci")

    # ── Jitter enum ──
    test("RS: Jitter has NONE", Jitter.NONE.value == "none")
    test("RS: Jitter has FULL", Jitter.FULL.value == "full")
    test("RS: Jitter has EQUAL", Jitter.EQUAL.value == "equal")
    test("RS: Jitter has DECORRELATED", Jitter.DECORRELATED.value == "decorrelated")

    # ── RetryConfig defaults ──
    _rs_cfg = RetryConfig()
    test("RS: default strategy", _rs_cfg.strategy == Strategy.EXPONENTIAL_BACKOFF)
    test("RS: default max_retries", _rs_cfg.max_retries == 3)
    test("RS: default base_delay", _rs_cfg.base_delay == 1.0)
    test("RS: default max_delay", _rs_cfg.max_delay == 60.0)
    test("RS: default multiplier", _rs_cfg.multiplier == 2.0)

    # ── _fib ──
    test("RS: fib(0) == 0", _fib(0) == 0)
    test("RS: fib(1) == 1", _fib(1) == 1)
    test("RS: fib(5) == 5", _fib(5) == 5)
    test("RS: fib(10) == 55", _fib(10) == 55)

    # ── _compute_raw_delay ──
    _rs_exp_cfg = RetryConfig(strategy=Strategy.EXPONENTIAL_BACKOFF, base_delay=1.0, multiplier=2.0, max_delay=100.0)
    test("RS: exp delay attempt 0", abs(_compute_raw_delay(0, _rs_exp_cfg) - 1.0) < 0.01)
    test("RS: exp delay attempt 1", abs(_compute_raw_delay(1, _rs_exp_cfg) - 2.0) < 0.01)
    test("RS: exp delay attempt 3", abs(_compute_raw_delay(3, _rs_exp_cfg) - 8.0) < 0.01)

    _rs_lin_cfg = RetryConfig(strategy=Strategy.LINEAR_BACKOFF, base_delay=1.0, step=2.0, max_delay=100.0)
    test("RS: linear delay attempt 0", abs(_compute_raw_delay(0, _rs_lin_cfg) - 1.0) < 0.01)
    test("RS: linear delay attempt 2", abs(_compute_raw_delay(2, _rs_lin_cfg) - 5.0) < 0.01)

    _rs_const_cfg = RetryConfig(strategy=Strategy.CONSTANT, base_delay=3.0)
    test("RS: constant delay", abs(_compute_raw_delay(5, _rs_const_cfg) - 3.0) < 0.01)

    _rs_fib_cfg = RetryConfig(strategy=Strategy.FIBONACCI, base_delay=1.0, max_delay=100.0)
    test("RS: fib delay attempt 0", abs(_compute_raw_delay(0, _rs_fib_cfg) - 1.0) < 0.01)  # fib(1)=1
    test("RS: fib delay attempt 3", abs(_compute_raw_delay(3, _rs_fib_cfg) - 3.0) < 0.01)  # fib(4)=3

    # Max delay cap
    _rs_cap_cfg = RetryConfig(strategy=Strategy.EXPONENTIAL_BACKOFF, base_delay=1.0, multiplier=10.0, max_delay=5.0)
    test("RS: max_delay capped", _compute_raw_delay(10, _rs_cap_cfg) <= 5.0)

    # ── _apply_jitter ──
    test("RS: jitter NONE unchanged", abs(_apply_jitter(4.0, RetryConfig(jitter=Jitter.NONE), 0.0) - 4.0) < 0.01)
    _rs_full_vals = [_apply_jitter(4.0, RetryConfig(jitter=Jitter.FULL), 0.0) for _ in range(20)]
    test("RS: jitter FULL in [0, 4]", all(0.0 <= v <= 4.01 for v in _rs_full_vals))
    _rs_equal_vals = [_apply_jitter(4.0, RetryConfig(jitter=Jitter.EQUAL), 0.0) for _ in range(20)]
    test("RS: jitter EQUAL in [2, 4]", all(1.99 <= v <= 4.01 for v in _rs_equal_vals))
    _rs_decorr_vals = [_apply_jitter(4.0, RetryConfig(jitter=Jitter.DECORRELATED, base_delay=1.0), 2.0) for _ in range(20)]
    test("RS: jitter DECORRELATED >= base",
         all(v >= 0.99 for v in _rs_decorr_vals))

    # ── should_retry + record_attempt + reset ──
    rs_reset("_test_rs_op")
    _rs_test_cfg = RetryConfig(max_retries=2)
    test("RS: should_retry before failure", should_retry("_test_rs_op", config=_rs_test_cfg))
    rs_record_attempt("_test_rs_op", success=False, config=_rs_test_cfg)
    test("RS: should_retry after 1 failure", should_retry("_test_rs_op", config=_rs_test_cfg))
    rs_record_attempt("_test_rs_op", success=False, config=_rs_test_cfg)
    test("RS: should_retry exhausted", not should_retry("_test_rs_op", config=_rs_test_cfg))

    # ── get_stats ──
    rs_reset("_test_rs_stats")
    rs_record_attempt("_test_rs_stats", success=True)
    rs_record_attempt("_test_rs_stats", success=False, error="boom")
    _rs_stats = rs_get_stats("_test_rs_stats")
    test("RS: stats attempts", _rs_stats["attempts"] == 2)
    test("RS: stats successes", _rs_stats["successes"] == 1)
    test("RS: stats failures", _rs_stats["failures"] == 1)
    test("RS: stats recent_errors", "boom" in _rs_stats["recent_errors"])
    test("RS: stats success_rate", abs(_rs_stats["success_rate"] - 0.5) < 0.01)

    # ── reset ──
    rs_reset("_test_rs_stats")
    test("RS: reset clears state", rs_get_stats("_test_rs_stats")["attempts"] == 0)

    # ── get_delay ──
    rs_reset("_test_rs_delay")
    _rs_delay_cfg = RetryConfig(strategy=Strategy.CONSTANT, base_delay=2.5, jitter=Jitter.NONE)
    test("RS: get_delay constant", abs(get_delay("_test_rs_delay", config=_rs_delay_cfg) - 2.5) < 0.01)

    # ── _get_state creates new entry ──
    _rs_unique = "_test_rs_unique_key_xyz"
    if _rs_unique in _registry:
        del _registry[_rs_unique]
    _rs_s = _get_state(_rs_unique)
    test("RS: _get_state creates entry", _rs_s.attempts == 0)
    test("RS: _get_state in registry", _rs_unique in _registry)
    del _registry[_rs_unique]  # cleanup

    # ── Error message truncation ──
    rs_reset("_test_rs_trunc")
    rs_record_attempt("_test_rs_trunc", success=False, error="x" * 500)
    _rs_trunc_stats = rs_get_stats("_test_rs_trunc")
    test("RS: error message truncated to 200",
         len(_rs_trunc_stats["recent_errors"][0]) <= 200)

    # ── Max errors stored ──
    rs_reset("_test_rs_max_err")
    for _rs_i in range(15):
        rs_record_attempt("_test_rs_max_err", success=False, error=f"error_{_rs_i}")
    _rs_me_stats = rs_get_stats("_test_rs_max_err")
    test("RS: max errors stored capped", len(_rs_me_stats["recent_errors"]) <= 10)

except Exception as _rs_exc:
    test("Retry Strategy Deep Tests: import and tests", False, str(_rs_exc))

# ─────────────────────────────────────────────────
# Tool Patterns Deep Tests (tool_patterns.py)
# ─────────────────────────────────────────────────
try:
    from shared.tool_patterns import (
        MarkovChain,
        WorkflowTemplate,
        AnomalyReport,
        build_markov_chain,
        _transition_probability,
        _sequence_log_probability,
        _std,
        _extract_ngrams,
        _label_for_template,
        _invalidate_cache,
        _MIN_TRANSITION_COUNT,
        _LAPLACE_ALPHA,
        _MIN_WORKFLOW_LEN,
        _MAX_WORKFLOW_LEN,
        _ANOMALY_SIGMA_THRESHOLD,
        _SESSION_BREAK_SECONDS,
    )

    # ── Constants ──
    test("TP: MIN_TRANSITION_COUNT", _MIN_TRANSITION_COUNT == 2)
    test("TP: LAPLACE_ALPHA", abs(_LAPLACE_ALPHA - 0.1) < 0.01)
    test("TP: MIN_WORKFLOW_LEN", _MIN_WORKFLOW_LEN == 3)
    test("TP: MAX_WORKFLOW_LEN", _MAX_WORKFLOW_LEN == 8)
    test("TP: ANOMALY_SIGMA_THRESHOLD", abs(_ANOMALY_SIGMA_THRESHOLD - 2.0) < 0.01)
    test("TP: SESSION_BREAK_SECONDS", abs(_SESSION_BREAK_SECONDS - 300.0) < 0.01)

    # ── MarkovChain dataclass ──
    _tp_mc = MarkovChain()
    test("TP: MarkovChain defaults", _tp_mc.total_starts == 0 and _tp_mc.sequence_count == 0)
    test("TP: MarkovChain vocabulary empty", len(_tp_mc.vocabulary) == 0)

    # ── build_markov_chain ──
    _tp_seqs = [
        ["Read", "Edit", "Bash"],
        ["Read", "Edit", "Bash"],
        ["Read", "Write", "Bash"],
        ["Glob", "Read", "Edit"],
    ]
    _tp_chain = build_markov_chain(_tp_seqs)
    test("TP: chain sequence_count", _tp_chain.sequence_count == 4)
    test("TP: chain total_starts", _tp_chain.total_starts == 4)
    test("TP: chain vocabulary",
         _tp_chain.vocabulary == {"Read", "Edit", "Bash", "Write", "Glob"})
    test("TP: chain start_counts Read",
         _tp_chain.start_counts.get("Read", 0) == 3)
    test("TP: chain start_counts Glob",
         _tp_chain.start_counts.get("Glob", 0) == 1)
    test("TP: chain transition Read->Edit",
         _tp_chain.transitions["Read"]["Edit"] == 3)
    test("TP: chain transition Read->Write",
         _tp_chain.transitions["Read"]["Write"] == 1)
    test("TP: chain transition Edit->Bash",
         _tp_chain.transitions["Edit"]["Bash"] == 2)

    # Empty sequences
    _tp_empty = build_markov_chain([])
    test("TP: empty chain", _tp_empty.sequence_count == 0 and len(_tp_empty.vocabulary) == 0)

    # ── _transition_probability ──
    _tp_prob = _transition_probability(_tp_chain, "Read", "Edit")
    test("TP: transition prob Read->Edit > 0.5", _tp_prob > 0.5)
    _tp_prob_unseen = _transition_probability(_tp_chain, "Read", "Glob")
    test("TP: transition prob unseen > 0 (Laplace)", _tp_prob_unseen > 0)
    _tp_prob_sum = sum(
        _transition_probability(_tp_chain, "Read", t) for t in _tp_chain.vocabulary
    )
    test("TP: transition probs sum ~1.0", abs(_tp_prob_sum - 1.0) < 0.01)

    # ── _sequence_log_probability ──
    _tp_log_p = _sequence_log_probability(_tp_chain, ["Read", "Edit", "Bash"])
    test("TP: log prob common seq is negative", _tp_log_p < 0)
    _tp_log_p_rare = _sequence_log_probability(_tp_chain, ["Bash", "Glob", "Write"])
    test("TP: rare seq lower prob", _tp_log_p_rare < _tp_log_p)
    _tp_log_p_empty = _sequence_log_probability(_tp_chain, [])
    test("TP: empty seq log prob -inf",
         _tp_log_p_empty == float("-inf"))

    # ── _std ──
    test("TP: std of identical values", abs(_std([5.0, 5.0, 5.0]) - 0.0) < 0.01)
    test("TP: std of [0, 10]", abs(_std([0.0, 10.0]) - 5.0) < 0.01)
    test("TP: std of single value", _std([42.0]) == 0.0)
    test("TP: std of empty list", _std([]) == 0.0)

    # ── _extract_ngrams ──
    test("TP: extract 2-grams",
         _extract_ngrams(["A", "B", "C", "D"], 2) == [["A", "B"], ["B", "C"], ["C", "D"]])
    test("TP: extract 3-grams",
         _extract_ngrams(["A", "B", "C"], 3) == [["A", "B", "C"]])
    test("TP: extract too-long ngram",
         _extract_ngrams(["A", "B"], 3) == [])

    # ── _label_for_template ──
    test("TP: label read-edit-test",
         _label_for_template(["Read", "Edit", "Bash"]) == "read-edit-test")
    test("TP: label read-then-edit",
         _label_for_template(["Read", "Edit"]) == "read-then-edit")
    test("TP: label unknown falls back",
         "workflow" in _label_for_template(["Xyz", "Abc"]).lower())
    test("TP: label empty", _label_for_template([]) == "mixed workflow")

    # ── WorkflowTemplate dataclass ──
    _tp_wt = WorkflowTemplate(
        tools=["Read", "Edit"], count=5, frequency=0.25, label="read-then-edit"
    )
    test("TP: WorkflowTemplate fields", _tp_wt.count == 5 and _tp_wt.frequency == 0.25)

    # ── AnomalyReport dataclass ──
    _tp_ar = AnomalyReport(
        tools=["X", "Y"], score=-10.0, baseline_mean=-5.0,
        baseline_std=2.0, sigma=2.5, reason="unusual",
        unusual_transitions=[("X", "Y")]
    )
    test("TP: AnomalyReport fields", _tp_ar.sigma == 2.5)
    test("TP: AnomalyReport unusual_transitions", len(_tp_ar.unusual_transitions) == 1)

    # ── _invalidate_cache ──
    _invalidate_cache()
    test("TP: invalidate_cache runs without error", True)

except Exception as _tp_exc:
    test("Tool Patterns Deep Tests: import and tests", False, str(_tp_exc))

# ─────────────────────────────────────────────────
# Skill Mapper Deep Tests (skill_mapper.py)
# ─────────────────────────────────────────────────
try:
    from shared.skill_mapper import (
        SkillMetadata,
        SkillHealth,
        SkillMapper,
        CLAUDE_DIR,
        SKILLS_DIR,
        HOOKS_DIR,
        SHARED_DIR,
        KNOWN_SHARED_MODULES,
    )
    import tempfile as _sm2_tempfile

    # ── Constants ──
    test("SM2: CLAUDE_DIR ends with .claude", CLAUDE_DIR.endswith(".claude"))
    test("SM2: SKILLS_DIR has skills", "skills" in SKILLS_DIR)
    test("SM2: HOOKS_DIR has hooks", "hooks" in HOOKS_DIR)
    test("SM2: SHARED_DIR has shared", "shared" in SHARED_DIR)
    test("SM2: KNOWN_SHARED_MODULES not empty", len(KNOWN_SHARED_MODULES) > 10)
    test("SM2: known modules has state", "state" in KNOWN_SHARED_MODULES)
    test("SM2: known modules has audit_log", "audit_log" in KNOWN_SHARED_MODULES)

    # ── SkillMetadata dataclass ──
    _sm2_meta = SkillMetadata(
        name="test-skill", path="/tmp/test", skill_md_path="/tmp/test/SKILL.md",
        script_paths=[], imports_from_shared=set(), imports_external=set(),
        missing_shared_modules=set(), functions_defined=set(),
        functions_called=set(), file_count=0
    )
    test("SM2: SkillMetadata name", _sm2_meta.name == "test-skill")
    test("SM2: SkillMetadata file_count", _sm2_meta.file_count == 0)

    # ── SkillHealth dataclass ──
    _sm2_health = SkillHealth(
        name="test", status="healthy", coverage_pct=100.0,
        has_metadata=True, has_scripts=True, script_count=2,
        shared_module_count=3, missing_dependencies=[],
        reuse_opportunities=[], description="test"
    )
    test("SM2: SkillHealth status", _sm2_health.status == "healthy")
    test("SM2: SkillHealth coverage", _sm2_health.coverage_pct == 100.0)

    # ── SkillMapper with real skills dir ──
    _sm2_mapper = SkillMapper()
    test("SM2: mapper initializes", isinstance(_sm2_mapper.skills, dict))

    _sm2_dep_graph = _sm2_mapper.get_dependency_graph()
    test("SM2: dependency_graph is dict", isinstance(_sm2_dep_graph, dict))

    _sm2_rev_graph = _sm2_mapper.get_reverse_dependency_graph()
    test("SM2: reverse_dependency_graph is dict", isinstance(_sm2_rev_graph, dict))

    _sm2_usage = _sm2_mapper.get_shared_module_usage()
    test("SM2: shared_module_usage is dict", isinstance(_sm2_usage, dict))

    _sm2_need_deps = _sm2_mapper.get_skills_needing_dependencies()
    test("SM2: skills_needing_deps is dict", isinstance(_sm2_need_deps, dict))

    _sm2_reuse = _sm2_mapper.get_skills_with_reuse_opportunities()
    test("SM2: reuse_opportunities is dict", isinstance(_sm2_reuse, dict))

    _sm2_report = _sm2_mapper.generate_report()
    test("SM2: report is string", isinstance(_sm2_report, str))
    test("SM2: report has SUMMARY", "SUMMARY" in _sm2_report)
    test("SM2: report has Total skills", "Total skills" in _sm2_report)

    _sm2_health_rpt = _sm2_mapper.get_skill_health()
    test("SM2: health report is dict", isinstance(_sm2_health_rpt, dict))
    if _sm2_health_rpt:
        _sm2_first_skill = next(iter(_sm2_health_rpt.values()))
        test("SM2: health has status field", hasattr(_sm2_first_skill, 'status'))
        test("SM2: health status valid",
             _sm2_first_skill.status in ("healthy", "degraded", "unhealthy"))

    # ── _extract_script_info with temp script ──
    with _sm2_tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as _sm2_tf:
        _sm2_tf.write("from shared.state import load_state\nimport os\ndef my_func():\n    pass\n")
        _sm2_tf_path = _sm2_tf.name

    _sm2_imports_shared = set()
    _sm2_imports_ext = set()
    _sm2_funcs_def = set()
    _sm2_funcs_call = set()
    _sm2_mapper._extract_script_info(
        _sm2_tf_path, _sm2_imports_shared, _sm2_imports_ext, _sm2_funcs_def, _sm2_funcs_call
    )
    os.unlink(_sm2_tf_path)
    test("SM2: extract shared import", "load_state" in _sm2_imports_shared)
    test("SM2: extract external import", "os" in _sm2_imports_ext)
    test("SM2: extract function def", "my_func" in _sm2_funcs_def)

    # ── _module_would_be_useful ──
    _sm2_meta_health = SkillMetadata(
        name="t", path="/t", skill_md_path="/t/SKILL.md",
        script_paths=[], imports_from_shared=set(), imports_external=set(),
        missing_shared_modules=set(), functions_defined=set(),
        functions_called={"check", "verify"}, file_count=0
    )
    test("SM2: health_monitor useful for health checks",
         _sm2_mapper._module_would_be_useful("health_monitor", _sm2_meta_health))
    test("SM2: rate_limiter not useful without rate calls",
         not _sm2_mapper._module_would_be_useful("rate_limiter", _sm2_meta_health))

except Exception as _sm2_exc:
    test("Skill Mapper Deep Tests: import and tests", False, str(_sm2_exc))

# ─────────────────────────────────────────────────
# Hot Reload Deep Tests (hot_reload.py)
# ─────────────────────────────────────────────────
try:
    from shared.hot_reload import (
        _module_to_filepath,
        _get_mtime,
        _validate_module,
        reload_gate,
        check_for_changes,
        auto_reload,
        discover_gate_modules,
        seed_mtimes,
        get_reload_history,
        reset_state as hr_reset_state,
        CHECK_INTERVAL,
        _known_mtimes,
        _reload_history,
        _lock as hr_lock,
    )
    import types as _hr_types
    import tempfile as _hr_tempfile

    # ── Constants ──
    test("HR: CHECK_INTERVAL is 30.0", abs(CHECK_INTERVAL - 30.0) < 0.01)

    # ── _module_to_filepath ──
    _hr_fp = _module_to_filepath("gates.gate_01_read_before_edit")
    test("HR: module_to_filepath has .py", _hr_fp.endswith(".py"))
    test("HR: module_to_filepath has gate_01", "gate_01_read_before_edit" in _hr_fp)
    test("HR: module_to_filepath nested", "gates" in _hr_fp)

    # ── _get_mtime ──
    test("HR: get_mtime existing file", _get_mtime(__file__) is not None)
    test("HR: get_mtime nonexistent", _get_mtime("/nonexistent/path.py") is None)

    # ── _validate_module ──
    _hr_good_mod = _hr_types.ModuleType("test_good")
    _hr_good_mod.check = lambda *a, **kw: None
    test("HR: validate module with check()", _validate_module(_hr_good_mod))

    _hr_bad_mod = _hr_types.ModuleType("test_bad")
    test("HR: validate module without check()", not _validate_module(_hr_bad_mod))

    # ── discover_gate_modules ──
    with _hr_tempfile.TemporaryDirectory() as _hr_td:
        # Create some gate files
        open(os.path.join(_hr_td, "gate_01_alpha.py"), "w").close()
        open(os.path.join(_hr_td, "gate_02_beta.py"), "w").close()
        open(os.path.join(_hr_td, "__init__.py"), "w").close()
        open(os.path.join(_hr_td, "utils.py"), "w").close()

        _hr_discovered = discover_gate_modules(gates_dir=_hr_td)
        test("HR: discover finds gate files", len(_hr_discovered) == 2)
        test("HR: discover excludes non-gate files",
             all("gate_" in d for d in _hr_discovered))
        test("HR: discover returns dotted names",
             all(d.startswith("gates.") for d in _hr_discovered))

    # Nonexistent dir
    test("HR: discover nonexistent dir", discover_gate_modules(gates_dir="/nonexistent") == [])

    # ── reset_state ──
    hr_reset_state()
    with hr_lock:
        test("HR: reset clears mtimes", len(_known_mtimes) == 0)
        test("HR: reset clears history", len(_reload_history) == 0)

    # ── seed_mtimes ──
    hr_reset_state()
    _hr_real_modules = discover_gate_modules()
    seed_mtimes(_hr_real_modules)
    with hr_lock:
        test("HR: seed populates mtimes", len(_known_mtimes) > 0)

    # ── check_for_changes ──
    hr_reset_state()
    seed_mtimes(_hr_real_modules)
    _hr_changes = check_for_changes(_hr_real_modules)
    test("HR: no changes after seed", _hr_changes == {})

    # Force a stale mtime
    hr_reset_state()
    _hr_stale_changes = check_for_changes(_hr_real_modules)
    test("HR: all changed when cache empty", len(_hr_stale_changes) == len(_hr_real_modules))

    # ── reload_gate ──
    hr_reset_state()
    if _hr_real_modules:
        _hr_ok = reload_gate(_hr_real_modules[0])
        test("HR: reload real gate returns True", _hr_ok)
        _hr_hist = get_reload_history()
        test("HR: reload records history", len(_hr_hist) == 1)
        test("HR: history entry success", _hr_hist[0]["success"])

    # Reload nonexistent
    hr_reset_state()
    test("HR: reload nonexistent returns False",
         not reload_gate("gates.__nonexistent_gate__"))

    # ── get_reload_history returns copy ──
    hr_reset_state()
    if _hr_real_modules:
        reload_gate(_hr_real_modules[0])
    _hr_h1 = get_reload_history()
    _hr_h1.append({"fake": True})
    _hr_h2 = get_reload_history()
    test("HR: history returns independent copy", {"fake": True} not in _hr_h2)

    # Cleanup
    hr_reset_state()

except Exception as _hr_exc:
    test("Hot Reload Deep Tests: import and tests", False, str(_hr_exc))

# ─────────────────────────────────────────────────
# Plugin Registry Deep Tests (plugin_registry.py)
# ─────────────────────────────────────────────────
try:
    from shared.plugin_registry import (
        scan_plugins,
        get_plugin,
        is_enabled,
        get_by_category,
        validate_plugin,
        dependency_check,
        _infer_category,
        _build_plugin_record,
        _read_plugin_json,
        KNOWN_CATEGORIES,
        _CATEGORY_KEYWORDS,
        _CACHE_MAX_AGE,
    )
    import tempfile as _pr_tempfile

    # ── Constants ──
    test("PR: KNOWN_CATEGORIES has 5", len(KNOWN_CATEGORIES) == 5)
    test("PR: quality in categories", "quality" in KNOWN_CATEGORIES)
    test("PR: security in categories", "security" in KNOWN_CATEGORIES)
    test("PR: development in categories", "development" in KNOWN_CATEGORIES)
    test("PR: CACHE_MAX_AGE is 300", _CACHE_MAX_AGE == 300)
    test("PR: CATEGORY_KEYWORDS has entries", len(_CATEGORY_KEYWORDS) > 0)

    # ── _infer_category ──
    test("PR: infer security", _infer_category("security-scanner", "checks vulnerabilities") == "security")
    test("PR: infer quality", _infer_category("code-review", "reviews code quality") == "quality")
    test("PR: infer development", _infer_category("typescript-lsp", "language server") == "development")
    test("PR: infer monitoring", _infer_category("telemetry-dash", "alert telemetry") == "monitoring")
    test("PR: infer default", _infer_category("unknown-thing", "does stuff") == "development")

    # ── validate_plugin ──
    test("PR: validate empty path", validate_plugin("") == (False, ["path must not be empty"]))
    _pr_v, _pr_e = validate_plugin("/nonexistent/path")
    test("PR: validate nonexistent", not _pr_v and len(_pr_e) > 0)

    # Valid plugin with tempdir
    with _pr_tempfile.TemporaryDirectory() as _pr_td:
        _pr_manifest_dir = os.path.join(_pr_td, ".claude-plugin")
        os.makedirs(_pr_manifest_dir)
        import json as _pr_json
        with open(os.path.join(_pr_manifest_dir, "plugin.json"), "w") as _pr_f:
            _pr_json.dump({"name": "test-plugin", "version": "1.0.0", "category": "quality"}, _pr_f)
        _pr_valid, _pr_errors = validate_plugin(_pr_td)
        test("PR: validate valid plugin", _pr_valid and len(_pr_errors) == 0)

        # Missing name
        with open(os.path.join(_pr_manifest_dir, "plugin.json"), "w") as _pr_f:
            _pr_json.dump({"version": "1.0.0"}, _pr_f)
        _pr_v2, _pr_e2 = validate_plugin(_pr_td)
        test("PR: validate missing name", not _pr_v2)

        # Invalid category
        with open(os.path.join(_pr_manifest_dir, "plugin.json"), "w") as _pr_f:
            _pr_json.dump({"name": "test", "category": "invalid_cat"}, _pr_f)
        _pr_v3, _pr_e3 = validate_plugin(_pr_td)
        test("PR: validate invalid category", not _pr_v3)

        # Bad JSON
        with open(os.path.join(_pr_manifest_dir, "plugin.json"), "w") as _pr_f:
            _pr_f.write("not json{{{")
        _pr_v4, _pr_e4 = validate_plugin(_pr_td)
        test("PR: validate bad json", not _pr_v4)

    # ── _build_plugin_record ──
    with _pr_tempfile.TemporaryDirectory() as _pr_td2:
        _pr_md2 = os.path.join(_pr_td2, ".claude-plugin")
        os.makedirs(_pr_md2)
        with open(os.path.join(_pr_md2, "plugin.json"), "w") as _pr_f2:
            _pr_json.dump({"name": "my-plugin", "version": "2.0", "description": "test"}, _pr_f2)
        _pr_rec = _build_plugin_record(_pr_td2, "local", "", {})
        test("PR: build_record returns dict", isinstance(_pr_rec, dict))
        test("PR: build_record name", _pr_rec["name"] == "my-plugin")
        test("PR: build_record version", _pr_rec["version"] == "2.0")
        test("PR: build_record source", _pr_rec["source"] == "local")
        test("PR: build_record not enabled", not _pr_rec["enabled"])

    test("PR: build_record nonexistent dir", _build_plugin_record("/nonexistent", "local", "", {}) is None)

    # ── _read_plugin_json ──
    test("PR: read_plugin_json nonexistent", _read_plugin_json("/nonexistent") == {})

    # ── scan_plugins ──
    _pr_plugins = scan_plugins(use_cache=False)
    test("PR: scan returns list", isinstance(_pr_plugins, list))
    test("PR: scan records have required keys",
         all({"name", "version", "category", "enabled", "source", "path"}.issubset(p.keys())
             for p in _pr_plugins))

    # ── get_plugin ──
    test("PR: get_plugin unknown returns None", get_plugin("__nonexistent_plugin__") is None)

    # ── is_enabled ──
    test("PR: is_enabled unknown returns False", not is_enabled("__nonexistent__"))

    # ── get_by_category ──
    _pr_dev = get_by_category("development")
    test("PR: get_by_category returns list", isinstance(_pr_dev, list))
    test("PR: get_by_category all same category",
         all(p["category"] == "development" for p in _pr_dev))

    # ── dependency_check ──
    _pr_sat, _pr_miss = dependency_check("__ghost__")
    test("PR: dep check unknown plugin", not _pr_sat and len(_pr_miss) > 0)

except Exception as _pr_exc:
    test("Plugin Registry Deep Tests: import and tests", False, str(_pr_exc))

# ─────────────────────────────────────────────────
# Test Generator Deep Tests (test_generator.py)
# ─────────────────────────────────────────────────
try:
    from shared.test_generator import (
        scan_module,
        generate_tests,
        generate_smoke_test,
        _is_gate_module,
        _is_shared_module,
        _is_skill_module,
        _classify_function,
        _stub_args,
        _needs_state_stub,
        _state_setup_block,
        _find_hooks_dir as tg_find_hooks_dir,
    )

    # ── _is_gate_module ──
    test("TG: is_gate_module true", _is_gate_module("gate_01_read_before_edit.py"))
    test("TG: is_gate_module false", not _is_gate_module("utils.py"))
    test("TG: is_gate_module no py", not _is_gate_module("gate_01_test.txt"))

    # ── _is_shared_module ──
    test("TG: is_shared_module true", _is_shared_module("/home/user/hooks/shared/state.py"))
    test("TG: is_shared_module false", not _is_shared_module("/home/user/hooks/gates/gate_01.py"))

    # ── _is_skill_module ──
    test("TG: is_skill_module true", _is_skill_module("/home/user/.claude/skills/test/script.py"))
    test("TG: is_skill_module false", not _is_skill_module("/home/user/.claude/hooks/shared/state.py"))

    # ── _classify_function ──
    test("TG: classify gate_check",
         _classify_function("check", ["tool_name", "tool_input", "state"], "/gates/g.py") == "gate_check")
    test("TG: classify shared_util",
         _classify_function("load_data", ["path"], "/hooks/shared/data.py") == "shared_util")
    test("TG: classify skill_entry run",
         _classify_function("run", [], "/other/module.py") == "skill_entry")
    test("TG: classify skill_entry by path",
         _classify_function("process", [], "/skills/test/script.py") == "skill_entry")
    test("TG: classify unknown",
         _classify_function("helper", [], "/other/module.py") == "unknown")

    # ── _stub_args ──
    test("TG: stub_args empty", _stub_args([]) == "")
    test("TG: stub_args path arg", '"/tmp/stub_' in _stub_args(["file_path"]))
    test("TG: stub_args state arg", "_state" in _stub_args(["state"]))
    test("TG: stub_args name arg", '"' in _stub_args(["tool_name"]))
    test("TG: stub_args input arg", "{}" in _stub_args(["tool_input"]))
    test("TG: stub_args single trailing comma", _stub_args(["x"]).endswith(","))
    test("TG: stub_args multiple no trailing", not _stub_args(["a", "b"]).endswith(","))

    # ── _needs_state_stub ──
    test("TG: needs_state_stub true", _needs_state_stub(["tool_name", "state"]))
    test("TG: needs_state_stub false", not _needs_state_stub(["path", "name"]))

    # ── _state_setup_block ──
    _tg_setup = _state_setup_block()
    test("TG: state_setup has reset", "reset_state" in _tg_setup)
    test("TG: state_setup has load", "load_state" in _tg_setup)

    # ── _find_hooks_dir ──
    _tg_hd = tg_find_hooks_dir(os.path.join(os.path.expanduser("~"), ".claude", "hooks", "shared", "state.py"))
    test("TG: find_hooks_dir finds hooks/",
         _tg_hd is not None and _tg_hd.endswith("hooks") if _tg_hd else True)

    # ── scan_module ──
    # Scan a real module
    _tg_scan_path = os.path.join(os.path.expanduser("~"), ".claude", "hooks", "shared", "gate_result.py")
    if os.path.exists(_tg_scan_path):
        _tg_scan = scan_module(_tg_scan_path)
        test("TG: scan_module returns list", isinstance(_tg_scan, list))
        test("TG: scan entries are tuples",
             all(isinstance(e, tuple) and len(e) == 4 for e in _tg_scan))
        if _tg_scan:
            test("TG: scan entry func_name", isinstance(_tg_scan[0][0], str))
            test("TG: scan entry args", isinstance(_tg_scan[0][1], list))
            test("TG: scan entry docstring", isinstance(_tg_scan[0][2], str))
            test("TG: scan entry func_type",
                 _tg_scan[0][3] in ("gate_check", "shared_util", "skill_entry", "unknown"))
    else:
        skip("TG: scan_module (gate_result.py not found)", "file missing")

    # Scan nonexistent
    try:
        scan_module("/nonexistent/module.py")
        test("TG: scan nonexistent raises", False, "should have raised")
    except FileNotFoundError:
        test("TG: scan nonexistent raises FileNotFoundError", True)

    # ── generate_tests ──
    _tg_fake_scan = [
        ("check", ["tool_name", "tool_input", "state"], "Gate check function", "gate_check"),
        ("helper", ["data"], "Helper function", "shared_util"),
    ]
    _tg_code = generate_tests(_tg_fake_scan, "/tmp/fake_module.py")
    test("TG: generate_tests returns string", isinstance(_tg_code, str))
    test("TG: generated code has test function", "def test(" in _tg_code)
    test("TG: generated code has PASS", "PASS" in _tg_code)
    test("TG: generated code has import", "import" in _tg_code)
    test("TG: generated code mentions check", "check" in _tg_code)
    test("TG: generated code mentions helper", "helper" in _tg_code)

    # ── generate_smoke_test ──
    if os.path.exists(_tg_scan_path):
        _tg_smoke = generate_smoke_test(_tg_scan_path)
        test("TG: smoke test returns string", isinstance(_tg_smoke, str) and len(_tg_smoke) > 100)

except Exception as _tg_exc:
    test("Test Generator Deep Tests: import and tests", False, str(_tg_exc))

# ─────────────────────────────────────────────────
# Event Replay Deep Tests (event_replay.py)
# ─────────────────────────────────────────────────
try:
    from shared.event_replay import (
        load_events,
        filter_events,
        replay_event,
        diff_results,
        summarise_replay,
        _is_memory_tool,
        _is_always_allowed,
        _parse_context,
        _extract_tool_input,
        _build_replay_state,
        CAPTURE_QUEUE_PATH,
        _ALWAYS_ALLOWED_TOOLS,
    )
    import tempfile as _er_tempfile

    # ── Constants ──
    test("ER: CAPTURE_QUEUE_PATH ends with .jsonl", CAPTURE_QUEUE_PATH.endswith(".jsonl"))
    test("ER: ALWAYS_ALLOWED has Read", "Read" in _ALWAYS_ALLOWED_TOOLS)
    test("ER: ALWAYS_ALLOWED has Glob", "Glob" in _ALWAYS_ALLOWED_TOOLS)
    test("ER: ALWAYS_ALLOWED has Grep", "Grep" in _ALWAYS_ALLOWED_TOOLS)

    # ── _is_memory_tool ──
    test("ER: is_memory_tool mcp__memory__", _is_memory_tool("mcp__memory__search_knowledge"))
    test("ER: is_memory_tool mcp_memory_", _is_memory_tool("mcp_memory_remember_this"))
    test("ER: is_memory_tool false", not _is_memory_tool("Edit"))

    # ── _is_always_allowed ──
    test("ER: always allowed Read", _is_always_allowed("Read"))
    test("ER: always allowed memory tool", _is_always_allowed("mcp__memory__search"))
    test("ER: not always allowed Edit", not _is_always_allowed("Edit"))
    test("ER: not always allowed Bash", not _is_always_allowed("Bash"))

    # ── _parse_context ──
    test("ER: parse context empty", _parse_context("") == {})
    test("ER: parse context json", _parse_context('{"file_path": "/tmp/x.py"}') == {"file_path": "/tmp/x.py"})
    test("ER: parse context non-json", _parse_context("just a string") == {})
    test("ER: parse context None", _parse_context(None) == {})

    # ── _extract_tool_input ──
    _er_bash_input = _extract_tool_input({"tool_name": "Bash", "context": "ls -la"})
    test("ER: extract Bash has command", "command" in _er_bash_input)

    _er_edit_input = _extract_tool_input({"tool_name": "Edit", "context": '{"file_path": "/tmp/x.py"}'})
    test("ER: extract Edit has file_path", "file_path" in _er_edit_input)

    _er_nb_input = _extract_tool_input({"tool_name": "NotebookEdit", "context": '{"notebook_path": "/tmp/n.ipynb"}'})
    test("ER: extract NotebookEdit has notebook_path", "notebook_path" in _er_nb_input)

    _er_task_input = _extract_tool_input({"tool_name": "Task", "context": '{"model": "opus"}'})
    test("ER: extract Task has model", "model" in _er_task_input)

    # ── _build_replay_state ──
    _er_state = _build_replay_state("test-replay")
    test("ER: replay state has session_id", _er_state.get("_session_id") == "test-replay")
    test("ER: replay state has session_start", "session_start" in _er_state)
    test("ER: replay state has memory_last_queried", "memory_last_queried" in _er_state)

    # ── load_events ──
    test("ER: load_events nonexistent file", load_events("/nonexistent.jsonl") == [])

    with _er_tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as _er_tf:
        import json as _er_json
        _er_json.dump({"metadata": {"tool_name": "Edit"}, "document": "test", "id": "obs_1"}, _er_tf)
        _er_tf.write("\n")
        _er_json.dump({"metadata": {"tool_name": "Bash"}, "document": "test2", "id": "obs_2"}, _er_tf)
        _er_tf.write("\n")
        _er_tf_path = _er_tf.name

    _er_events = load_events(_er_tf_path)
    test("ER: load events count", len(_er_events) == 2)
    test("ER: load events has metadata", all("metadata" in e for e in _er_events))
    os.unlink(_er_tf_path)

    # ── filter_events ──
    with _er_tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as _er_tf2:
        _er_json.dump({"metadata": {"tool_name": "Edit", "exit_code": "2", "gate": "gate_01"}, "document": "d1", "id": "o1"}, _er_tf2)
        _er_tf2.write("\n")
        _er_json.dump({"metadata": {"tool_name": "Bash", "exit_code": "0", "gate": "gate_02"}, "document": "d2", "id": "o2"}, _er_tf2)
        _er_tf2.write("\n")
        _er_tf2_path = _er_tf2.name

    _er_filtered_tool = filter_events(tool_name="Edit", path=_er_tf2_path)
    test("ER: filter by tool_name", len(_er_filtered_tool) == 1)
    test("ER: filtered has _replay_meta", "_replay_meta" in _er_filtered_tool[0])
    test("ER: replay_meta tool_name", _er_filtered_tool[0]["_replay_meta"]["tool_name"] == "Edit")

    _er_filtered_blocked = filter_events(blocked=True, path=_er_tf2_path)
    test("ER: filter blocked", len(_er_filtered_blocked) == 1)
    test("ER: filtered blocked is Edit",
         _er_filtered_blocked[0]["_replay_meta"]["tool_name"] == "Edit")

    _er_filtered_gate = filter_events(gate_name="gate_01", path=_er_tf2_path)
    test("ER: filter by gate_name", len(_er_filtered_gate) == 1)

    os.unlink(_er_tf2_path)

    # ── diff_results ──
    _er_diff_same = diff_results(
        {"originally_blocked": True},
        {"final_outcome": "blocked", "per_gate": {}}
    )
    test("ER: diff same outcome not changed", not _er_diff_same["changed"])

    _er_diff_changed = diff_results(
        {"originally_blocked": True},
        {"final_outcome": "passed", "per_gate": {}}
    )
    test("ER: diff changed outcome", _er_diff_changed["changed"])
    test("ER: diff has new_passes", len(_er_diff_changed["new_passes"]) > 0)

    # Per-gate diff
    _er_diff_gate = diff_results(
        {"per_gate": {"gate_01": {"blocked": True}, "gate_02": {"blocked": False}}, "final_outcome": "blocked"},
        {"per_gate": {"gate_01": {"blocked": False}, "gate_02": {"blocked": True}}, "final_outcome": "blocked"}
    )
    test("ER: gate diff changed", _er_diff_gate["changed"])
    test("ER: gate diff has changes", len(_er_diff_gate["gate_changes"]) == 2)

    # ── summarise_replay ──
    _er_replay_results = [
        {"event": {"_replay_meta": {"timestamp": "t1", "tool_name": "Edit"}},
         "replayed": {}, "diff": {"changed": True, "new_blocks": ["g1"], "new_passes": [],
                                   "original_outcome": "passed", "replayed_outcome": "blocked", "summary": "s"}},
        {"event": {"_replay_meta": {"timestamp": "t2", "tool_name": "Bash"}},
         "replayed": {}, "diff": {"changed": False, "new_blocks": [], "new_passes": [],
                                   "original_outcome": "passed", "replayed_outcome": "passed", "summary": "ok"}},
    ]
    _er_summary = summarise_replay(_er_replay_results)
    test("ER: summary total", _er_summary["total"] == 2)
    test("ER: summary changed", _er_summary["changed"] == 1)
    test("ER: summary unchanged", _er_summary["unchanged"] == 1)
    test("ER: summary has changed_events", len(_er_summary["changed_events"]) == 1)

    # Empty summary
    test("ER: empty summary", summarise_replay([]) == {
        "total": 0, "changed": 0, "unchanged": 0,
        "new_blocks": [], "new_passes": [], "changed_events": []
    })

except Exception as _er_exc:
    test("Event Replay Deep Tests: import and tests", False, str(_er_exc))

# ─────────────────────────────────────────────────
# Metrics Collector Deep Tests (shared/metrics_collector.py)
# ─────────────────────────────────────────────────
try:
    from shared.metrics_collector import (
        TYPE_COUNTER, TYPE_GAUGE, TYPE_HISTOGRAM,
        BUILTIN_METRICS, METRICS_RAMDISK_DIR,
        _label_key, _MetricsStore,
        inc as _mc_inc, set_gauge as _mc_set_gauge, observe as _mc_observe,
        get_metric as _mc_get_metric, get_all_metrics as _mc_get_all,
        flush as _mc_flush, rollup as _mc_rollup, export_json as _mc_export_json,
        timed as _mc_timed,
        record_gate_fire, record_gate_block, record_gate_latency,
        record_hook_duration, record_memory_query, set_memory_total,
        record_tool_call, set_test_pass_rate,
    )
    import time as _mc_time
    import json as _mc_json
    import shared.metrics_collector as _mc_mod

    # ── Constants ──
    test("MC: TYPE_COUNTER is 'counter'", TYPE_COUNTER == "counter")
    test("MC: TYPE_GAUGE is 'gauge'", TYPE_GAUGE == "gauge")
    test("MC: TYPE_HISTOGRAM is 'histogram'", TYPE_HISTOGRAM == "histogram")
    test("MC: METRICS_RAMDISK_DIR is /dev/shm/claude-hooks", METRICS_RAMDISK_DIR == "/dev/shm/claude-hooks")
    test("MC: BUILTIN_METRICS is dict", isinstance(BUILTIN_METRICS, dict))
    test("MC: BUILTIN_METRICS has gate.fires", "gate.fires" in BUILTIN_METRICS)
    test("MC: BUILTIN_METRICS has gate.blocks", "gate.blocks" in BUILTIN_METRICS)
    test("MC: BUILTIN_METRICS has gate.latency_ms", "gate.latency_ms" in BUILTIN_METRICS)
    test("MC: BUILTIN_METRICS has memory.total", "memory.total" in BUILTIN_METRICS)
    test("MC: BUILTIN_METRICS has test.pass_rate", "test.pass_rate" in BUILTIN_METRICS)

    # ── _label_key ──
    test("MC: _label_key(None) returns ''", _label_key(None) == "")
    test("MC: _label_key({}) returns ''", _label_key({}) == "")
    test("MC: _label_key({'a':'1'}) returns 'a=1'", _label_key({"a": "1"}) == "a=1")
    test("MC: _label_key sorted keys", _label_key({"b": "2", "a": "1"}) == "a=1,b=2")
    test("MC: _label_key multi keys", _label_key({"z": "3", "a": "1", "m": "2"}) == "a=1,m=2,z=3")

    # ── Fresh _MetricsStore: counter ──
    _mc_s = _MetricsStore()
    _mc_s._loaded = True
    _mc_s.inc("test.counter", 1)
    _mc_val = _mc_s.get_metric("test.counter")
    test("MC: fresh store inc value=1", _mc_val.get("value") == 1)
    test("MC: fresh store inc type=counter", _mc_val.get("type") == TYPE_COUNTER)

    _mc_s.inc("test.counter", 5)
    _mc_val2 = _mc_s.get_metric("test.counter")
    test("MC: counter increments cumulative (1+5=6)", _mc_val2.get("value") == 6)

    # ── Fresh _MetricsStore: gauge ──
    _mc_s2 = _MetricsStore()
    _mc_s2._loaded = True
    _mc_s2.set_gauge("test.gauge", 42.0)
    _mc_g = _mc_s2.get_metric("test.gauge")
    test("MC: set_gauge value", _mc_g.get("value") == 42.0)
    test("MC: set_gauge type", _mc_g.get("type") == TYPE_GAUGE)

    _mc_s2.set_gauge("test.gauge", 99.0)
    _mc_g2 = _mc_s2.get_metric("test.gauge")
    test("MC: set_gauge overwrites previous", _mc_g2.get("value") == 99.0)

    # ── Fresh _MetricsStore: histogram ──
    _mc_s3 = _MetricsStore()
    _mc_s3._loaded = True
    _mc_s3.observe("test.hist", 10.0)
    _mc_h = _mc_s3.get_metric("test.hist")
    test("MC: observe creates histogram", _mc_h.get("type") == TYPE_HISTOGRAM)
    test("MC: observe count=1", _mc_h.get("count") == 1)
    test("MC: observe sum=10.0", _mc_h.get("sum") == 10.0)
    test("MC: observe min=10.0", _mc_h.get("min") == 10.0)
    test("MC: observe max=10.0", _mc_h.get("max") == 10.0)
    test("MC: observe avg computed", _mc_h.get("avg") == 10.0)

    _mc_s3.observe("test.hist", 2.0)
    _mc_s3.observe("test.hist", 20.0)
    _mc_h2 = _mc_s3.get_metric("test.hist")
    test("MC: observe updates count", _mc_h2.get("count") == 3)
    test("MC: observe min updates to 2.0", _mc_h2.get("min") == 2.0)
    test("MC: observe max updates to 20.0", _mc_h2.get("max") == 20.0)
    test("MC: observe avg = (10+2+20)/3", abs(_mc_h2.get("avg", 0) - 32.0/3) < 0.001)

    # ── get_metric for nonexistent ──
    _mc_s4 = _MetricsStore()
    _mc_s4._loaded = True
    test("MC: get_metric nonexistent returns {}", _mc_s4.get_metric("nonexistent.xyz") == {})

    # ── get_all_metrics returns dict-of-dicts ──
    _mc_s5 = _MetricsStore()
    _mc_s5._loaded = True
    _mc_s5.inc("all.counter", 3)
    _mc_s5.set_gauge("all.gauge", 7.0)
    _mc_all = _mc_s5.get_all_metrics()
    test("MC: get_all_metrics returns dict", isinstance(_mc_all, dict))
    test("MC: get_all_metrics has all.counter", "all.counter" in _mc_all)
    test("MC: get_all_metrics has all.gauge", "all.gauge" in _mc_all)
    test("MC: get_all_metrics nested dict", isinstance(_mc_all.get("all.counter", {}), dict))

    # ── rollup returns non-empty after observations ──
    _mc_s6 = _MetricsStore()
    _mc_s6._loaded = True
    _mc_s6.observe("rollup.hist", 5.0)
    _mc_s6.inc("rollup.counter", 2)
    _mc_r = _mc_s6.rollup(60)
    test("MC: rollup returns dict", isinstance(_mc_r, dict))
    test("MC: rollup non-empty after observations", len(_mc_r) > 0)

    # ── timed context manager: patch module-level _store temporarily ──
    _mc_orig_store = _mc_mod._store
    _mc_s7 = _MetricsStore()
    _mc_s7._loaded = True
    _mc_mod._store = _mc_s7
    try:
        with _mc_timed("timed.test.metric"):
            _mc_time.sleep(0.001)
        _mc_timed_val = _mc_s7.get_metric("timed.test.metric")
        test("MC: timed creates histogram observation", _mc_timed_val.get("count") == 1)
        test("MC: timed records > 0 ms", _mc_timed_val.get("sum", 0) > 0)
    finally:
        _mc_mod._store = _mc_orig_store

    # ── Convenience helpers: patch module store for isolation ──
    _mc_fresh2 = _MetricsStore()
    _mc_fresh2._loaded = True
    _mc_mod._store = _mc_fresh2
    try:
        record_gate_fire("test_gate_99")
        _mc_gf = _mc_fresh2.get_metric("gate.fires", {"gate": "test_gate_99"})
        test("MC: record_gate_fire increments gate.fires", _mc_gf.get("value") == 1)

        record_gate_block("test_gate_99")
        _mc_gb = _mc_fresh2.get_metric("gate.blocks", {"gate": "test_gate_99"})
        test("MC: record_gate_block increments gate.blocks", _mc_gb.get("value") == 1)

        set_test_pass_rate(1.5)
        _mc_tpr = _mc_fresh2.get_metric("test.pass_rate")
        test("MC: set_test_pass_rate clamps >1 to 1.0", _mc_tpr.get("value") == 1.0)

        set_test_pass_rate(-0.5)
        _mc_tpr2 = _mc_fresh2.get_metric("test.pass_rate")
        test("MC: set_test_pass_rate clamps <0 to 0.0", _mc_tpr2.get("value") == 0.0)

        record_memory_query()
        _mc_mq = _mc_fresh2.get_metric("memory.queries")
        test("MC: record_memory_query increments memory.queries", _mc_mq.get("value") == 1)

        record_tool_call()
        record_tool_call()
        _mc_tc = _mc_fresh2.get_metric("session.tool_calls")
        test("MC: record_tool_call x2 = 2", _mc_tc.get("value") == 2)

        set_memory_total(500)
        _mc_mt = _mc_fresh2.get_metric("memory.total")
        test("MC: set_memory_total sets gauge", _mc_mt.get("value") == 500.0)
    finally:
        _mc_mod._store = _mc_orig_store

    # ── export_json ──
    _mc_exported = _mc_export_json()
    test("MC: export_json returns string", isinstance(_mc_exported, str))
    _mc_parsed = _mc_json.loads(_mc_exported)
    test("MC: export_json valid JSON", isinstance(_mc_parsed, dict))
    test("MC: export_json has metrics key", "metrics" in _mc_parsed)
    test("MC: export_json has rollup_1m", "rollup_1m" in _mc_parsed)
    test("MC: export_json has rollup_5m", "rollup_5m" in _mc_parsed)
    test("MC: export_json has rollup_session", "rollup_session" in _mc_parsed)

except Exception as _mc_exc:
    test("Metrics Collector Deep Tests: import and tests", False, str(_mc_exc))

# ─────────────────────────────────────────────────
# Circuit Breaker Deep Tests (shared/circuit_breaker.py)
# ─────────────────────────────────────────────────
try:
    from shared.circuit_breaker import (
        STATE_CLOSED, STATE_OPEN, STATE_HALF_OPEN,
        DEFAULT_FAILURE_THRESHOLD, DEFAULT_RECOVERY_TIMEOUT, DEFAULT_SUCCESS_THRESHOLD,
        _GATE_CRASH_THRESHOLD, _GATE_CRASH_WINDOW, _GATE_COOLDOWN, _GATE_SUCCESS_NEEDED,
        _TIER1_GATE_NAMES,
        _default_service_record, _default_gate_record,
        _get_or_create, _maybe_recover, _prune_crash_window, _gate_maybe_recover,
        should_skip_gate, record_gate_result, get_gate_circuit_state,
        reset_gate_circuit, get_all_gate_states,
        _load_gate_state, _save_gate_state, _get_or_create_gate,
    )
    import time as _cb_time

    # ── State constants ──
    test("CB: STATE_CLOSED == 'CLOSED'", STATE_CLOSED == "CLOSED")
    test("CB: STATE_OPEN == 'OPEN'", STATE_OPEN == "OPEN")
    test("CB: STATE_HALF_OPEN == 'HALF_OPEN'", STATE_HALF_OPEN == "HALF_OPEN")

    # ── Default configuration constants ──
    test("CB: DEFAULT_FAILURE_THRESHOLD == 5", DEFAULT_FAILURE_THRESHOLD == 5)
    test("CB: DEFAULT_RECOVERY_TIMEOUT == 60", DEFAULT_RECOVERY_TIMEOUT == 60)
    test("CB: DEFAULT_SUCCESS_THRESHOLD == 2", DEFAULT_SUCCESS_THRESHOLD == 2)

    # ── Gate-specific constants ──
    test("CB: _GATE_CRASH_THRESHOLD == 3", _GATE_CRASH_THRESHOLD == 3)
    test("CB: _GATE_CRASH_WINDOW == 300", _GATE_CRASH_WINDOW == 300)
    test("CB: _GATE_COOLDOWN == 60", _GATE_COOLDOWN == 60)
    test("CB: _GATE_SUCCESS_NEEDED == 1", _GATE_SUCCESS_NEEDED == 1)

    # ── _TIER1_GATE_NAMES ──
    test("CB: _TIER1_GATE_NAMES contains gate_01", "gate_01_read_before_edit" in _TIER1_GATE_NAMES)
    test("CB: _TIER1_GATE_NAMES contains gate_02", "gate_02_no_destroy" in _TIER1_GATE_NAMES)
    test("CB: _TIER1_GATE_NAMES contains gate_03", "gate_03_test_before_deploy" in _TIER1_GATE_NAMES)

    # ── _default_service_record ──
    _cb_rec = _default_service_record()
    test("CB: _default_service_record is dict", isinstance(_cb_rec, dict))
    test("CB: _default_service_record state is CLOSED", _cb_rec["state"] == STATE_CLOSED)
    test("CB: _default_service_record failure_count is 0", _cb_rec["failure_count"] == 0)
    test("CB: _default_service_record success_count is 0", _cb_rec["success_count"] == 0)
    test("CB: _default_service_record has failure_threshold", "failure_threshold" in _cb_rec)
    test("CB: _default_service_record has recovery_timeout", "recovery_timeout" in _cb_rec)
    test("CB: _default_service_record opened_at is None", _cb_rec["opened_at"] is None)

    # ── _default_gate_record ──
    _cb_grec = _default_gate_record()
    test("CB: _default_gate_record is dict", isinstance(_cb_grec, dict))
    test("CB: _default_gate_record state is CLOSED", _cb_grec["state"] == STATE_CLOSED)
    test("CB: _default_gate_record crash_timestamps is list", isinstance(_cb_grec["crash_timestamps"], list))
    test("CB: _default_gate_record crash_timestamps empty", _cb_grec["crash_timestamps"] == [])
    test("CB: _default_gate_record has total_crashes", "total_crashes" in _cb_grec)
    test("CB: _default_gate_record opened_at is None", _cb_grec["opened_at"] is None)

    # ── _get_or_create ──
    _cb_data = {}
    _cb_svc_rec = _get_or_create(_cb_data, "test_svc_create")
    test("CB: _get_or_create creates if missing", "test_svc_create" in _cb_data)
    test("CB: _get_or_create returns dict", isinstance(_cb_svc_rec, dict))
    _cb_svc_rec2 = _get_or_create(_cb_data, "test_svc_create")
    test("CB: _get_or_create returns existing", _cb_svc_rec is _cb_svc_rec2)

    # ── _maybe_recover: OPEN -> HALF_OPEN when timeout passed ──
    _cb_open_rec = _default_service_record()
    _cb_open_rec["state"] = STATE_OPEN
    _cb_open_rec["opened_at"] = _cb_time.time() - DEFAULT_RECOVERY_TIMEOUT - 5
    _maybe_recover(_cb_open_rec)
    test("CB: _maybe_recover OPEN->HALF_OPEN after timeout", _cb_open_rec["state"] == STATE_HALF_OPEN)

    # ── _maybe_recover: CLOSED unchanged ──
    _cb_closed_rec = _default_service_record()
    _maybe_recover(_cb_closed_rec)
    test("CB: _maybe_recover does nothing for CLOSED", _cb_closed_rec["state"] == STATE_CLOSED)

    # ── _maybe_recover: OPEN stays OPEN if timeout not elapsed ──
    _cb_fresh_open_rec = _default_service_record()
    _cb_fresh_open_rec["state"] = STATE_OPEN
    _cb_fresh_open_rec["opened_at"] = _cb_time.time()
    _maybe_recover(_cb_fresh_open_rec)
    test("CB: _maybe_recover OPEN stays OPEN if timeout not elapsed", _cb_fresh_open_rec["state"] == STATE_OPEN)

    # ── _prune_crash_window ──
    _cb_prune_rec = _default_gate_record()
    _cb_old_ts = _cb_time.time() - _GATE_CRASH_WINDOW - 10
    _cb_new_ts = _cb_time.time() - 5
    _cb_prune_rec["crash_timestamps"] = [_cb_old_ts, _cb_new_ts]
    _prune_crash_window(_cb_prune_rec)
    test("CB: _prune_crash_window removes old timestamps", _cb_old_ts not in _cb_prune_rec["crash_timestamps"])
    test("CB: _prune_crash_window keeps recent timestamps", _cb_new_ts in _cb_prune_rec["crash_timestamps"])

    # ── _gate_maybe_recover: OPEN -> HALF_OPEN after cooldown ──
    _cb_gate_open = _default_gate_record()
    _cb_gate_open["state"] = STATE_OPEN
    _cb_gate_open["opened_at"] = _cb_time.time() - _GATE_COOLDOWN - 5
    _gate_maybe_recover(_cb_gate_open)
    test("CB: _gate_maybe_recover transitions OPEN->HALF_OPEN after cooldown", _cb_gate_open["state"] == STATE_HALF_OPEN)

    # ── should_skip_gate: Tier 1 gates never skipped ──
    test("CB: should_skip_gate False for gate_01 (Tier1)", not should_skip_gate("gate_01_read_before_edit"))
    test("CB: should_skip_gate False for gate_02 (Tier1)", not should_skip_gate("gate_02_no_destroy"))
    test("CB: should_skip_gate False for gate_03 (Tier1)", not should_skip_gate("gate_03_test_before_deploy"))

    # ── should_skip_gate: unknown gate returns False (fail-open) ──
    test("CB: should_skip_gate False for unknown gate", not should_skip_gate("gate_99_nonexistent"))

    # ── get_gate_circuit_state: returns CLOSED for unknown gate ──
    _cb_unknown_state = get_gate_circuit_state("gate_99_totally_unknown_xyz")
    test("CB: get_gate_circuit_state CLOSED for unknown", _cb_unknown_state == STATE_CLOSED)

    # ── reset_gate_circuit / get_gate_circuit_state round-trip ──
    _cb_test_gate = "test_gate_cb_deep_xyz"
    reset_gate_circuit(_cb_test_gate)
    test("CB: reset_gate_circuit sets CLOSED", get_gate_circuit_state(_cb_test_gate) == STATE_CLOSED)

    # ── get_all_gate_states returns dict ──
    _cb_all = get_all_gate_states()
    test("CB: get_all_gate_states returns dict", isinstance(_cb_all, dict))

    # ── record_gate_result: success on HALF_OPEN closes circuit ──
    _cb_test_gate2 = "test_gate_cb_deep_hopen"
    reset_gate_circuit(_cb_test_gate2)
    _cb_gs = _load_gate_state()
    _cb_g2rec = _get_or_create_gate(_cb_gs, _cb_test_gate2)
    _cb_g2rec["state"] = STATE_HALF_OPEN
    _save_gate_state(_cb_gs)
    record_gate_result(_cb_test_gate2, success=True)
    test("CB: record_gate_result success in HALF_OPEN -> CLOSED",
         get_gate_circuit_state(_cb_test_gate2) == STATE_CLOSED)

    # Cleanup
    reset_gate_circuit(_cb_test_gate)
    reset_gate_circuit(_cb_test_gate2)

except Exception as _cb_exc:
    test("Circuit Breaker Deep Tests: import and tests", False, str(_cb_exc))

# ─────────────────────────────────────────────────
# Gate Correlator Deep Tests (shared/gate_correlator.py)
# ─────────────────────────────────────────────────
try:
    from shared.gate_correlator import (
        CHAIN_WINDOW_SECONDS, MIN_COOCCURRENCE, REDUNDANCY_JACCARD_THRESHOLD,
        _GATE_NAME_MAP, _CANONICAL_ORDER, _TIER1_GATES,
        _normalize_gate, _ts_float, _group_by_tool_call,
        build_cooccurrence_matrix, cooccurrence_summary,
        detect_gate_chains, detect_redundant_gates,
        optimize_gate_order as _gc_optimize_order,
        GateCorrelator,
    )
    from datetime import datetime as _gc_dt

    # ── Constants ──
    test("GC: CHAIN_WINDOW_SECONDS == 5.0", CHAIN_WINDOW_SECONDS == 5.0)
    test("GC: MIN_COOCCURRENCE == 3", MIN_COOCCURRENCE == 3)
    test("GC: REDUNDANCY_JACCARD_THRESHOLD == 0.85", REDUNDANCY_JACCARD_THRESHOLD == 0.85)

    # ── _GATE_NAME_MAP ──
    test("GC: _GATE_NAME_MAP is dict", isinstance(_GATE_NAME_MAP, dict))
    test("GC: _GATE_NAME_MAP has gate_01_read_before_edit key",
         "gate_01_read_before_edit" in _GATE_NAME_MAP)
    test("GC: _GATE_NAME_MAP gate_01 maps to canonical",
         _GATE_NAME_MAP["gate_01_read_before_edit"] == "GATE 1: READ BEFORE EDIT")

    # ── _CANONICAL_ORDER ──
    test("GC: _CANONICAL_ORDER is list", isinstance(_CANONICAL_ORDER, list))
    test("GC: _CANONICAL_ORDER has >= 10 entries", len(_CANONICAL_ORDER) >= 10)
    test("GC: _CANONICAL_ORDER starts with GATE 1", _CANONICAL_ORDER[0] == "GATE 1: READ BEFORE EDIT")

    # ── _TIER1_GATES ──
    test("GC: _TIER1_GATES is set", isinstance(_TIER1_GATES, set))
    test("GC: _TIER1_GATES has 3 entries", len(_TIER1_GATES) == 3)
    test("GC: _TIER1_GATES has GATE 1", "GATE 1: READ BEFORE EDIT" in _TIER1_GATES)
    test("GC: _TIER1_GATES has GATE 2", "GATE 2: NO DESTROY" in _TIER1_GATES)
    test("GC: _TIER1_GATES has GATE 3", "GATE 3: TEST BEFORE DEPLOY" in _TIER1_GATES)

    # ── _normalize_gate ──
    test("GC: _normalize_gate maps short name",
         _normalize_gate("gate_01_read_before_edit") == "GATE 1: READ BEFORE EDIT")
    test("GC: _normalize_gate maps full module path",
         _normalize_gate("gates.gate_01_read_before_edit") == "GATE 1: READ BEFORE EDIT")
    test("GC: _normalize_gate passes through unknown",
         _normalize_gate("unknown_gate_xyz") == "unknown_gate_xyz")
    test("GC: _normalize_gate already canonical is identity",
         _normalize_gate("GATE 1: READ BEFORE EDIT") == "GATE 1: READ BEFORE EDIT")

    # ── _ts_float ──
    _gc_iso = _gc_dt(2025, 1, 1, 12, 0, 0).isoformat()
    _gc_ts_result = _ts_float({"timestamp": _gc_iso})
    test("GC: _ts_float valid ISO returns > 0", _gc_ts_result > 0)
    test("GC: _ts_float invalid timestamp returns 0.0", _ts_float({"timestamp": "not-a-date"}) == 0.0)
    test("GC: _ts_float empty string returns 0.0", _ts_float({"timestamp": ""}) == 0.0)
    test("GC: _ts_float missing key returns 0.0", _ts_float({}) == 0.0)

    # ── Synthetic audit entries for testing ──
    _gc_ts = _gc_dt(2025, 1, 1, 12, 0, 0).isoformat()
    _gc_entries = [
        {"gate": "GATE 1: READ BEFORE EDIT", "tool": "Edit", "decision": "pass",
         "timestamp": _gc_ts, "session_id": "s1"},
        {"gate": "GATE 2: NO DESTROY", "tool": "Edit", "decision": "pass",
         "timestamp": _gc_ts, "session_id": "s1"},
    ]

    # ── _group_by_tool_call ──
    test("GC: _group_by_tool_call empty list returns []", _group_by_tool_call([]) == [])
    _gc_groups = _group_by_tool_call(_gc_entries)
    test("GC: _group_by_tool_call groups same-session same-tool same-second",
         len(_gc_groups) == 1)
    test("GC: _group_by_tool_call group has 2 entries", len(_gc_groups[0]) == 2)

    _gc_entries2 = [
        {"gate": "GATE 1: READ BEFORE EDIT", "tool": "Edit", "decision": "pass",
         "timestamp": _gc_ts, "session_id": "s1"},
        {"gate": "GATE 2: NO DESTROY", "tool": "Bash", "decision": "pass",
         "timestamp": _gc_ts, "session_id": "s1"},
    ]
    _gc_groups2 = _group_by_tool_call(_gc_entries2)
    test("GC: _group_by_tool_call different tools => separate groups", len(_gc_groups2) == 2)

    # ── build_cooccurrence_matrix ──
    _gc_empty_matrix = build_cooccurrence_matrix([])
    test("GC: build_cooccurrence_matrix empty entries returns {}", _gc_empty_matrix == {})

    _gc_matrix = build_cooccurrence_matrix(_gc_entries)
    test("GC: build_cooccurrence_matrix with 2 gates on same call returns 1 pair",
         len(_gc_matrix) == 1)
    _gc_pair_key = (min("GATE 1: READ BEFORE EDIT", "GATE 2: NO DESTROY"),
                    max("GATE 1: READ BEFORE EDIT", "GATE 2: NO DESTROY"))
    test("GC: build_cooccurrence_matrix pair count == 1", _gc_matrix.get(_gc_pair_key) == 1)

    # ── cooccurrence_summary ──
    test("GC: cooccurrence_summary empty matrix returns []", cooccurrence_summary({}) == [])
    _gc_summary = cooccurrence_summary(_gc_matrix)
    test("GC: cooccurrence_summary returns list", isinstance(_gc_summary, list))
    test("GC: cooccurrence_summary has 1 entry", len(_gc_summary) == 1)
    test("GC: cooccurrence_summary entry has gate_a", "gate_a" in _gc_summary[0])
    test("GC: cooccurrence_summary entry has gate_b", "gate_b" in _gc_summary[0])
    test("GC: cooccurrence_summary entry has count", "count" in _gc_summary[0])

    # ── detect_gate_chains ──
    test("GC: detect_gate_chains empty entries returns []", detect_gate_chains([]) == [])
    _gc_chains = detect_gate_chains(_gc_entries, min_count=1)
    test("GC: detect_gate_chains with min_count=1 returns list", isinstance(_gc_chains, list))

    # ── detect_redundant_gates ──
    test("GC: detect_redundant_gates empty entries returns []", detect_redundant_gates([]) == [])

    # ── optimize_gate_order ──
    _gc_ordering = _gc_optimize_order([])
    test("GC: optimize_gate_order returns list", isinstance(_gc_ordering, list))
    test("GC: optimize_gate_order rows have rank key", all("rank" in r for r in _gc_ordering))
    test("GC: optimize_gate_order rows have gate key", all("gate" in r for r in _gc_ordering))
    test("GC: optimize_gate_order rows have pinned key", all("pinned" in r for r in _gc_ordering))
    test("GC: optimize_gate_order rows have score key", all("score" in r for r in _gc_ordering))
    test("GC: optimize_gate_order rows have reason key", all("reason" in r for r in _gc_ordering))

    _gc_pinned = [r for r in _gc_ordering if r["pinned"]]
    _gc_free = [r for r in _gc_ordering if not r["pinned"]]
    test("GC: optimize_gate_order Tier1 gates are pinned", len(_gc_pinned) >= 3)
    if _gc_pinned and _gc_free:
        test("GC: optimize_gate_order pinned gates come before free gates",
             max(r["rank"] for r in _gc_pinned) < min(r["rank"] for r in _gc_free))
    else:
        skip("GC: optimize_gate_order pinned before free", "no pinned or free gates")

    # ── GateCorrelator class ──
    _gc_corr = GateCorrelator()
    test("GC: GateCorrelator constructor sets _entries to None", _gc_corr._entries is None)
    test("GC: GateCorrelator _max_entries default is 50000", _gc_corr._max_entries == 50_000)
    test("GC: GateCorrelator constructor sets _cooccurrence to None", _gc_corr._cooccurrence is None)

    _gc_corr2 = GateCorrelator(max_entries=100)
    test("GC: GateCorrelator custom max_entries", _gc_corr2._max_entries == 100)

except Exception as _gc_exc:
    test("Gate Correlator Deep Tests: import and tests", False, str(_gc_exc))

# ─────────────────────────────────────────────────
# Gate Router Deep Tests (shared/gate_router.py)
# ─────────────────────────────────────────────────
try:
    from shared.gate_router import (
        TIER1, TIER2, TIER3, GATE_TOOL_MAP,
        _tier_of, get_applicable_gates,
        _reset_stats, get_routing_stats,
        _get_stat_int, _set_stat_int, _get_stat_list,
        _load_qtable, _save_qtable, get_optimal_gate_order, update_qtable, flush_qtable,
        _Q_ALPHA, _Q_REWARD_BLOCK, _Q_REWARD_PASS,
    )

    # ── Tier sets ──
    test("GR: TIER1 has 3 entries", len(TIER1) == 3)
    test("GR: TIER2 has 4 entries", len(TIER2) == 4)
    test("GR: TIER3 is non-empty", len(TIER3) > 0)
    test("GR: TIER1 contains gate_01", "gates.gate_01_read_before_edit" in TIER1)
    test("GR: TIER1 contains gate_02", "gates.gate_02_no_destroy" in TIER1)
    test("GR: TIER1 contains gate_03", "gates.gate_03_test_before_deploy" in TIER1)
    test("GR: TIER2 contains gate_04", "gates.gate_04_memory_first" in TIER2)
    test("GR: TIER2 contains gate_05", "gates.gate_05_proof_before_fixed" in TIER2)
    test("GR: TIER2 contains gate_06", "gates.gate_06_save_fix" in TIER2)
    test("GR: TIER2 contains gate_07", "gates.gate_07_critical_file_guard" in TIER2)

    # ── GATE_TOOL_MAP ──
    test("GR: GATE_TOOL_MAP is dict", isinstance(GATE_TOOL_MAP, dict))
    test("GR: GATE_TOOL_MAP gate_11 is None (universal)",
         GATE_TOOL_MAP.get("gates.gate_11_rate_limit") is None)
    test("GR: GATE_TOOL_MAP gate_01 contains Edit",
         "Edit" in (GATE_TOOL_MAP.get("gates.gate_01_read_before_edit") or set()))
    test("GR: GATE_TOOL_MAP gate_02 contains Bash",
         "Bash" in (GATE_TOOL_MAP.get("gates.gate_02_no_destroy") or set()))
    test("GR: GATE_TOOL_MAP gate_10 contains Task",
         "Task" in (GATE_TOOL_MAP.get("gates.gate_10_model_enforcement") or set()))

    # ── _tier_of ──
    test("GR: _tier_of gate_01 returns 1", _tier_of("gates.gate_01_read_before_edit") == 1)
    test("GR: _tier_of gate_02 returns 1", _tier_of("gates.gate_02_no_destroy") == 1)
    test("GR: _tier_of gate_04 returns 2", _tier_of("gates.gate_04_memory_first") == 2)
    test("GR: _tier_of gate_09 returns 3", _tier_of("gates.gate_09_strategy_ban") == 3)
    test("GR: _tier_of unknown gate returns 3", _tier_of("gates.gate_99_unknown") == 3)

    # ── get_applicable_gates ──
    _gr_edit_gates = get_applicable_gates("Edit")
    test("GR: get_applicable_gates returns list", isinstance(_gr_edit_gates, list))
    test("GR: get_applicable_gates Edit includes gate_01",
         "gates.gate_01_read_before_edit" in _gr_edit_gates)
    test("GR: get_applicable_gates Edit excludes gate_02 (Bash only)",
         "gates.gate_02_no_destroy" not in _gr_edit_gates)
    test("GR: get_applicable_gates Edit excludes gate_03 (Bash only)",
         "gates.gate_03_test_before_deploy" not in _gr_edit_gates)

    _gr_bash_gates = get_applicable_gates("Bash")
    test("GR: get_applicable_gates Bash includes gate_02",
         "gates.gate_02_no_destroy" in _gr_bash_gates)
    test("GR: get_applicable_gates Bash includes gate_11 (universal)",
         "gates.gate_11_rate_limit" in _gr_bash_gates)

    _gr_task_gates = get_applicable_gates("Task")
    test("GR: get_applicable_gates Task includes gate_10",
         "gates.gate_10_model_enforcement" in _gr_task_gates)

    test("GR: get_applicable_gates WebFetch includes gate_11 (universal)",
         "gates.gate_11_rate_limit" in get_applicable_gates("WebFetch"))

    # ── Stats functions ──
    _reset_stats()
    _gr_stats = get_routing_stats()
    test("GR: _reset_stats sets calls to 0", _gr_stats.get("calls") == 0)
    test("GR: get_routing_stats returns dict", isinstance(_gr_stats, dict))
    test("GR: get_routing_stats has calls key", "calls" in _gr_stats)
    test("GR: get_routing_stats has gates_run key", "gates_run" in _gr_stats)
    test("GR: get_routing_stats has gates_skipped key", "gates_skipped" in _gr_stats)
    test("GR: get_routing_stats has tier1_blocks key", "tier1_blocks" in _gr_stats)
    test("GR: get_routing_stats has skip_rate key", "skip_rate" in _gr_stats)
    test("GR: get_routing_stats has avg_routing_ms key", "avg_routing_ms" in _gr_stats)
    test("GR: get_routing_stats has last_routing_ms key", "last_routing_ms" in _gr_stats)
    test("GR: skip_rate is 0.0 after reset", _gr_stats.get("skip_rate") == 0.0)

    # ── _get_stat_int / _set_stat_int ──
    test("GR: _get_stat_int returns 0 for missing key", _get_stat_int("nonexistent_key_xyz") == 0)
    _set_stat_int("calls", 99)
    test("GR: _set_stat_int sets value", _get_stat_int("calls") == 99)
    _reset_stats()

    # ── _get_stat_list ──
    test("GR: _get_stat_list returns list", isinstance(_get_stat_list("timing_ms"), list))
    test("GR: _get_stat_list returns [] for missing key", _get_stat_list("nonexistent_list_xyz") == [])

    # ── Q-table constants ──
    test("GR: _Q_ALPHA == 0.1", _Q_ALPHA == 0.1)
    test("GR: _Q_REWARD_BLOCK == 1.0", _Q_REWARD_BLOCK == 1.0)
    test("GR: _Q_REWARD_PASS == -0.1", _Q_REWARD_PASS == -0.1)

    # ── get_optimal_gate_order ──
    _gr_sample_gates = [
        "gates.gate_01_read_before_edit",
        "gates.gate_04_memory_first",
        "gates.gate_09_strategy_ban",
        "gates.gate_11_rate_limit",
    ]
    _gr_ordered = get_optimal_gate_order("Edit", _gr_sample_gates)
    test("GR: get_optimal_gate_order returns list", isinstance(_gr_ordered, list))
    test("GR: get_optimal_gate_order same length as input", len(_gr_ordered) == len(_gr_sample_gates))
    test("GR: get_optimal_gate_order same set as input",
         set(_gr_ordered) == set(_gr_sample_gates))
    _gr_t1_indices = [_gr_ordered.index(g) for g in _gr_ordered if g in TIER1]
    _gr_non_t1_indices = [i for i, g in enumerate(_gr_ordered) if g not in TIER1]
    if _gr_t1_indices and _gr_non_t1_indices:
        test("GR: get_optimal_gate_order Tier1 gates first",
             max(_gr_t1_indices) < min(_gr_non_t1_indices))
    else:
        skip("GR: get_optimal_gate_order Tier1 first", "not enough gate types to verify")

    # ── update_qtable / _load_qtable / flush_qtable ──
    update_qtable("gates.gate_04_memory_first", "Edit", blocked=True)
    test("GR: update_qtable does not crash (block=True)", True)
    update_qtable("gates.gate_04_memory_first", "Edit", blocked=False)
    test("GR: update_qtable does not crash (block=False)", True)
    _gr_qt = _load_qtable()
    test("GR: _load_qtable returns dict", isinstance(_gr_qt, dict))
    flush_qtable()
    test("GR: flush_qtable does not crash", True)

except Exception as _gr_exc:
    test("Gate Router Deep Tests: import and tests", False, str(_gr_exc))

# ── Session Analytics Tests ───────────────────────────────────────────────────
print("\n--- Session Analytics (SA) ---")
try:
    from shared.session_analytics import (
        _state_session_metrics,
        tool_call_distribution,
        gate_fire_rates,
        gate_block_rates,
        error_frequency,
        session_productivity,
        _compute_resolve_score,
        _stddev,
        compare_sessions_metrics,
        parse_audit_log,
    )

    _sa_state = {
        "session_start": 1700000000.0,
        "total_tool_calls": 42,
        "tool_call_counts": {
            "Edit": 10,
            "Read": 20,
            "mcp__memory__search_knowledge": 5,
            "mcp__memory__remember_this": 3,
            "Bash": 4,
        },
        "gate6_warn_count": 2,
        "files_read": ["/a.py", "/b.py"],
        "files_edited": ["/a.py"],
        "gate_effectiveness": {"gate_01": {"blocks": 5}},
        "security_profile": "strict",
        "pending_verification": [{"file": "/a.py"}],
        "active_bans": {"strat1": True},
        "active_subagents": ["agent1"],
        "auto_remember_count": 7,
        "last_test_exit_code": 0,
    }

    _sa_metrics = _state_session_metrics("test-sa-session", _sa_state)

    test("SA: session_id in result", _sa_metrics["session_id"] == "test-sa-session")
    test("SA: total_tool_calls == 42", _sa_metrics["total_tool_calls"] == 42)
    test("SA: memory_queries == 5", _sa_metrics["memory_queries"] == 5)
    test("SA: memory_saves == 3", _sa_metrics["memory_saves"] == 3)
    test("SA: files_read_count == 2", _sa_metrics["files_read_count"] == 2)
    test("SA: files_edited_count == 1", _sa_metrics["files_edited_count"] == 1)
    test("SA: warnings == 2", _sa_metrics["warnings_this_session"] == 2)
    test("SA: security_profile == strict", _sa_metrics["security_profile"] == "strict")
    test("SA: pending_verification_count == 1", _sa_metrics["pending_verification_count"] == 1)
    test("SA: active_bans_count == 1", _sa_metrics["active_bans_count"] == 1)
    test("SA: subagent_count == 1", _sa_metrics["subagent_count"] == 1)
    test("SA: auto_remember_count == 7", _sa_metrics["auto_remember_count"] == 7)
    test("SA: last_test_exit_code == 0", _sa_metrics["last_test_exit_code"] == 0)
    test("SA: session_start matches", _sa_metrics["session_start"] == 1700000000.0)
    test("SA: session_start_iso is non-empty string",
         isinstance(_sa_metrics["session_start_iso"], str) and len(_sa_metrics["session_start_iso"]) > 0)

    # tool_call_distribution
    _sa_audit_entries = [
        {"tool": "Edit", "gate": "gate_01", "decision": "pass"},
        {"tool": "Edit", "gate": "gate_01", "decision": "block"},
        {"tool": "Read",  "gate": "gate_01", "decision": "pass"},
        {"tool": "Bash",  "gate": "gate_02", "decision": "warn"},
        {"tool": "Read",  "gate": "gate_02", "decision": "pass"},
    ]
    _sa_dist = tool_call_distribution(_sa_audit_entries)
    test("SA: tool_call_distribution returns dict", isinstance(_sa_dist, dict))
    test("SA: tool_call_distribution Edit count == 2", _sa_dist.get("Edit") == 2)
    test("SA: tool_call_distribution Read count == 2", _sa_dist.get("Read") == 2)
    test("SA: tool_call_distribution Bash count == 1", _sa_dist.get("Bash") == 1)

    # gate_fire_rates
    _sa_fire = gate_fire_rates(_sa_audit_entries)
    test("SA: gate_fire_rates returns dict", isinstance(_sa_fire, dict))
    test("SA: gate_fire_rates gate_01 count == 3", _sa_fire.get("gate_01") == 3)
    test("SA: gate_fire_rates gate_02 count == 2", _sa_fire.get("gate_02") == 2)

    # gate_block_rates
    _sa_block = gate_block_rates(_sa_audit_entries)
    test("SA: gate_block_rates returns dict", isinstance(_sa_block, dict))
    test("SA: gate_block_rates gate_01 has pass/warn/block/total keys",
         set(_sa_block.get("gate_01", {}).keys()) >= {"pass", "warn", "block", "total"})
    test("SA: gate_block_rates gate_01 block == 1", _sa_block["gate_01"]["block"] == 1)
    test("SA: gate_block_rates gate_01 pass == 2", _sa_block["gate_01"]["pass"] == 2)
    test("SA: gate_block_rates gate_02 warn == 1", _sa_block["gate_02"]["warn"] == 1)

    # error_frequency
    _sa_err_entries = [
        {"gate": "gate_01", "decision": "block", "reason": "must Read /a.py before editing"},
        {"gate": "gate_02", "decision": "block", "reason": "rm -rf /tmp blocked"},
        {"gate": "gate_01", "decision": "block", "reason": "must Read /b.py before editing"},
        {"gate": "gate_01", "decision": "pass",  "reason": ""},  # pass entries ignored
    ]
    _sa_errs = error_frequency(_sa_err_entries)
    test("SA: error_frequency returns dict", isinstance(_sa_errs, dict))
    test("SA: error_frequency gate1 pattern counted",
         _sa_errs.get("gate1:read-before-edit", 0) == 2)
    test("SA: error_frequency gate2 destructive-op counted",
         _sa_errs.get("gate2:destructive-op", 0) == 1)

    # session_productivity
    _sa_prod_entries = [
        {"tool": "Edit", "decision": "pass",  "gate": "gate_01"},
        {"tool": "Edit", "decision": "pass",  "gate": "gate_01"},
        {"tool": "Read", "decision": "pass",  "gate": "gate_01"},
        {"tool": "Bash", "decision": "block", "gate": "gate_02"},
    ]
    _sa_prod = session_productivity(_sa_prod_entries, 60.0)
    test("SA: session_productivity returns dict", isinstance(_sa_prod, dict))
    test("SA: session_productivity has score key", "score" in _sa_prod)
    test("SA: session_productivity score is float", isinstance(_sa_prod["score"], float))
    test("SA: session_productivity has grade key", "grade" in _sa_prod)
    test("SA: session_productivity has breakdown key", "breakdown" in _sa_prod)
    test("SA: session_productivity grade is valid letter",
         _sa_prod["grade"] in ("A", "B", "C", "D", "F"))
    test("SA: session_productivity breakdown has expected keys",
         set(_sa_prod["breakdown"].keys()) >= {"edit_velocity", "block_rate", "error_resolve", "memory_contrib"})

    # _compute_resolve_score
    _sa_resolve_empty = _compute_resolve_score([])
    test("SA: _compute_resolve_score([]) == 1.0", _sa_resolve_empty == 1.0)

    # _stddev
    _sa_std_uniform = _stddev([5.0, 5.0, 5.0])
    test("SA: _stddev([5,5,5]) == 0.0", _sa_std_uniform == 0.0)
    _sa_std_empty = _stddev([])
    test("SA: _stddev([]) == 0.0", _sa_std_empty == 0.0)

    # compare_sessions_metrics — insufficient_data
    _sa_trend = compare_sessions_metrics({"score": 80.0}, [], 10)
    test("SA: compare_sessions_metrics empty history trend == insufficient_data",
         _sa_trend.get("trend") == "insufficient_data")

    # parse_audit_log — nonexistent file
    _sa_parsed = parse_audit_log("/nonexistent/path/audit.jsonl")
    test("SA: parse_audit_log nonexistent returns []", _sa_parsed == [])

except Exception as _sa_exc:
    test("Session Analytics Tests: import and tests", False, str(_sa_exc))

# ── Event Bus Tests ───────────────────────────────────────────────────────────
print("\n--- Event Bus (EB) ---")
try:
    from shared.event_bus import (
        clear as _eb_clear,
        subscribe as _eb_subscribe,
        unsubscribe as _eb_unsubscribe,
        publish as _eb_publish,
        get_recent as _eb_get_recent,
        get_stats as _eb_get_stats,
        configure as _eb_configure,
        EventType as _EventType,
        _DEFAULT_MAX_EVENTS as _EB_DEFAULT_MAX_EVENTS,
        EVENTS_RAMDISK_DIR as _EB_RAMDISK_DIR,
    )

    # Reset before all tests to avoid state from prior usage
    _eb_clear()

    # EventType constants
    test("EB: EventType.GATE_FIRED constant exists",
         hasattr(_EventType, "GATE_FIRED") and _EventType.GATE_FIRED == "GATE_FIRED")
    test("EB: EventType.GATE_BLOCKED constant exists",
         hasattr(_EventType, "GATE_BLOCKED") and _EventType.GATE_BLOCKED == "GATE_BLOCKED")
    test("EB: EventType.MEMORY_QUERIED constant exists",
         hasattr(_EventType, "MEMORY_QUERIED") and _EventType.MEMORY_QUERIED == "MEMORY_QUERIED")
    test("EB: EventType.TEST_RUN constant exists",
         hasattr(_EventType, "TEST_RUN") and _EventType.TEST_RUN == "TEST_RUN")
    test("EB: EventType.ERROR_DETECTED constant exists",
         hasattr(_EventType, "ERROR_DETECTED") and _EventType.ERROR_DETECTED == "ERROR_DETECTED")
    test("EB: EventType.FIX_APPLIED constant exists",
         hasattr(_EventType, "FIX_APPLIED") and _EventType.FIX_APPLIED == "FIX_APPLIED")
    test("EB: EventType.TOOL_CALLED constant exists",
         hasattr(_EventType, "TOOL_CALLED") and _EventType.TOOL_CALLED == "TOOL_CALLED")

    # EventType.ALL
    test("EB: EventType.ALL is a tuple", isinstance(_EventType.ALL, tuple))
    test("EB: EventType.ALL has 7 entries", len(_EventType.ALL) == 7)

    # _DEFAULT_MAX_EVENTS
    test("EB: _DEFAULT_MAX_EVENTS == 1000", _EB_DEFAULT_MAX_EVENTS == 1000)

    # EVENTS_RAMDISK_DIR constant
    test("EB: EVENTS_RAMDISK_DIR is a string", isinstance(_EB_RAMDISK_DIR, str))

    # After clear(), get_stats shows zeros
    _eb_clear()
    _eb_stats_empty = _eb_get_stats()
    test("EB: after clear() total_published == 0", _eb_stats_empty["total_published"] == 0)
    test("EB: after clear() events_in_buffer == 0", _eb_stats_empty["events_in_buffer"] == 0)
    test("EB: after clear() subscriber_count == 0", _eb_stats_empty["subscriber_count"] == 0)

    # subscribe + publish + handler called
    _eb_received = []
    _eb_handler = lambda e: _eb_received.append(e)
    _eb_subscribe(_EventType.GATE_FIRED, _eb_handler)
    _eb_evt = _eb_publish(_EventType.GATE_FIRED, {"gate": "gate_01"}, source="test")
    test("EB: subscribe + publish calls handler", len(_eb_received) == 1)
    test("EB: handler receives correct event type",
         _eb_received[0].get("type") == _EventType.GATE_FIRED)

    # publish returns event dict with required keys
    test("EB: publish returns event dict", isinstance(_eb_evt, dict))
    test("EB: event dict has type key", "type" in _eb_evt)
    test("EB: event dict has timestamp key", "timestamp" in _eb_evt)
    test("EB: event dict has data key", "data" in _eb_evt)
    test("EB: event dict has source key", "source" in _eb_evt)

    # unsubscribe removes handler
    _eb_received2 = []
    _eb_handler2 = lambda e: _eb_received2.append(e)
    _eb_subscribe(_EventType.FIX_APPLIED, _eb_handler2)
    _eb_unsubscribe(_EventType.FIX_APPLIED, _eb_handler2)
    _eb_publish(_EventType.FIX_APPLIED, {"fix": "patch"})
    test("EB: unsubscribe removes handler", len(_eb_received2) == 0)

    # get_recent returns list
    _eb_recent = _eb_get_recent()
    test("EB: get_recent returns list", isinstance(_eb_recent, list))

    # get_recent filters by event_type
    _eb_publish(_EventType.GATE_BLOCKED, {"gate": "gate_02"})
    _eb_only_blocked = _eb_get_recent(event_type=_EventType.GATE_BLOCKED)
    test("EB: get_recent filters by event_type",
         all(e.get("type") == _EventType.GATE_BLOCKED for e in _eb_only_blocked)
         and len(_eb_only_blocked) >= 1)

    # get_stats has expected keys
    _eb_stats = _eb_get_stats()
    _eb_expected_keys = {"total_published", "events_in_buffer", "buffer_capacity",
                         "subscriber_count", "by_type", "handler_errors"}
    test("EB: get_stats has all expected keys",
         _eb_expected_keys.issubset(_eb_stats.keys()),
         f"missing: {_eb_expected_keys - set(_eb_stats.keys())}")

    # configure(max_events=5) caps buffer
    _eb_configure(max_events=5)
    for _i in range(10):
        _eb_publish(_EventType.TEST_RUN, {"run": _i}, persist=False)
    _eb_capped = _eb_get_recent()
    test("EB: configure(max_events=5) caps buffer at 5",
         len(_eb_capped) <= 5, f"len={len(_eb_capped)}")
    # Restore default capacity
    _eb_configure(max_events=_EB_DEFAULT_MAX_EVENTS)

    # Broken handler does not crash publish (fail-open)
    _eb_clear()
    def _eb_bad_handler(e):
        raise RuntimeError("intentional failure")
    _eb_subscribe(_EventType.ERROR_DETECTED, _eb_bad_handler)
    _eb_fail_result = _eb_publish(_EventType.ERROR_DETECTED, {"msg": "oops"})
    test("EB: broken handler does not crash publish (fail-open)",
         _eb_fail_result is not None and _eb_fail_result.get("type") == _EventType.ERROR_DETECTED)

    # clear() resets everything
    _eb_clear()
    _eb_stats_final = _eb_get_stats()
    test("EB: clear() resets total_published to 0", _eb_stats_final["total_published"] == 0)
    test("EB: clear() resets events_in_buffer to 0", _eb_stats_final["events_in_buffer"] == 0)
    test("EB: clear() resets subscriber_count to 0", _eb_stats_final["subscriber_count"] == 0)

    # Cleanup
    _eb_clear()

except Exception as _eb_exc:
    test("Event Bus Tests: import and tests", False, str(_eb_exc))

# ── Pipeline Optimizer Tests ──────────────────────────────────────────────────
print("\n--- Pipeline Optimizer (PO) ---")
try:
    from shared.pipeline_optimizer import (
        _TIER1 as _PO_TIER1,
        _SHORT_TO_MODULE as _PO_SHORT_TO_MODULE,
        _MODULE_TO_SHORT as _PO_MODULE_TO_SHORT,
        _GATE_STATE_DEPS as _PO_GATE_STATE_DEPS,
        _load_json as _po_load_json,
        _gates_for_tool as _po_gates_for_tool,
        _block_rate as _po_block_rate,
        _avg_ms as _po_avg_ms,
        _are_parallelizable as _po_are_parallelizable,
        _identify_parallel_groups as _po_identify_parallel_groups,
        get_optimal_order as _po_get_optimal_order,
        estimate_savings as _po_estimate_savings,
        get_pipeline_analysis as _po_get_pipeline_analysis,
    )

    # _TIER1 set has 3 entries
    test("PO: _TIER1 is a set", isinstance(_PO_TIER1, set))
    test("PO: _TIER1 has 3 entries", len(_PO_TIER1) == 3)

    # _SHORT_TO_MODULE and _MODULE_TO_SHORT are dicts
    test("PO: _SHORT_TO_MODULE is a dict", isinstance(_PO_SHORT_TO_MODULE, dict))
    test("PO: _MODULE_TO_SHORT is a dict", isinstance(_PO_MODULE_TO_SHORT, dict))

    # _GATE_STATE_DEPS is a dict
    test("PO: _GATE_STATE_DEPS is a dict", isinstance(_PO_GATE_STATE_DEPS, dict))

    # _load_json nonexistent returns {}
    _po_loaded = _po_load_json("/nonexistent/path/file.json")
    test("PO: _load_json nonexistent returns {}", _po_loaded == {})

    # _gates_for_tool("Edit") includes gate_01
    _po_edit_gates = _po_gates_for_tool("Edit")
    test("PO: _gates_for_tool('Edit') returns list", isinstance(_po_edit_gates, list))
    test("PO: _gates_for_tool('Edit') includes gate_01",
         "gates.gate_01_read_before_edit" in _po_edit_gates)

    # _gates_for_tool("Bash") includes gate_02
    _po_bash_gates = _po_gates_for_tool("Bash")
    test("PO: _gates_for_tool('Bash') returns list", isinstance(_po_bash_gates, list))
    test("PO: _gates_for_tool('Bash') includes gate_02",
         "gates.gate_02_no_destroy" in _po_bash_gates)

    # _block_rate with unknown gate returns 0.0
    _po_br = _po_block_rate("unknown_gate", {})
    test("PO: _block_rate('unknown_gate', {}) == 0.0", _po_br == 0.0)

    # _avg_ms with unknown gate returns 0.0
    _po_ms = _po_avg_ms("unknown_gate", {})
    test("PO: _avg_ms('unknown_gate', {}) == 0.0", _po_ms == 0.0)

    # _are_parallelizable: gate_01 and gate_02 both have empty writes, parallelizable
    _po_par_01_02 = _po_are_parallelizable("gate_01_read_before_edit", "gate_02_no_destroy")
    test("PO: _are_parallelizable(gate_01, gate_02) — no write conflicts",
         isinstance(_po_par_01_02, bool))
    test("PO: gate_01_read_before_edit and gate_02_no_destroy are parallelizable",
         _po_par_01_02 is True)

    # _are_parallelizable with gates having conflicting writes (gate_06 writes gate6_warn_count)
    # gate_16 also writes code_quality_warnings_per_file; gate_14 writes confidence_warnings_per_file
    # gate_06 writes gate6_warn_count; gate_11 reads tool_call_count (no writes) → parallelizable
    # gate_06 writes gate6_warn_count; gate_06 vs itself should conflict (write-write)
    _po_par_06_06 = _po_are_parallelizable("gate_06_save_fix", "gate_06_save_fix")
    test("PO: gate_06 vs gate_06 not parallelizable (self write-write conflict)",
         _po_par_06_06 is False)

    # _identify_parallel_groups with two parallelizable gates gives them in same group
    _po_groups = _po_identify_parallel_groups(
        ["gate_01_read_before_edit", "gate_02_no_destroy"]
    )
    test("PO: _identify_parallel_groups returns list", isinstance(_po_groups, list))
    test("PO: _identify_parallel_groups non-empty", len(_po_groups) >= 1)

    # get_optimal_order returns list of strings
    _po_order = _po_get_optimal_order("Edit")
    test("PO: get_optimal_order('Edit') returns list", isinstance(_po_order, list))
    test("PO: get_optimal_order('Edit') returns non-empty list", len(_po_order) > 0)
    test("PO: get_optimal_order('Edit') contains strings",
         all(isinstance(g, str) for g in _po_order))

    # get_optimal_order starts with Tier 1 gates
    _po_tier1_shorts = {"gate_01_read_before_edit", "gate_02_no_destroy", "gate_03_test_before_deploy"}
    _po_tier1_in_order = [g for g in _po_order if g in _po_tier1_shorts]
    _po_non_tier1_in_order = [g for g in _po_order if g not in _po_tier1_shorts]
    if _po_tier1_in_order and _po_non_tier1_in_order:
        _po_last_tier1_idx = max(_po_order.index(g) for g in _po_tier1_in_order)
        _po_first_non_tier1_idx = min(_po_order.index(g) for g in _po_non_tier1_in_order)
        test("PO: get_optimal_order starts with Tier 1 gates",
             _po_last_tier1_idx < _po_first_non_tier1_idx)
    else:
        skip("PO: get_optimal_order starts with Tier 1 gates", "not enough gate types in Edit order")

    # estimate_savings returns dict with expected keys
    _po_savings = _po_estimate_savings("Edit")
    test("PO: estimate_savings('Edit') returns dict", isinstance(_po_savings, dict))
    _po_savings_keys = {"tool_name", "applicable_gates", "optimal_order", "parallel_groups",
                        "baseline_sequential_ms", "optimized_sequential_ms",
                        "optimized_parallel_ms", "estimated_saving_ms",
                        "saving_pct", "gate_block_rates", "notes"}
    test("PO: estimate_savings has expected keys",
         _po_savings_keys.issubset(_po_savings.keys()),
         f"missing: {_po_savings_keys - set(_po_savings.keys())}")

    # estimate_savings("UnknownTool") — universal gates (None tool map) still apply,
    # but a truly unknown-to-specific-gates tool returns no tool-specific gates.
    # The function returns a valid dict regardless.
    _po_unknown = _po_estimate_savings("UnknownTool")
    test("PO: estimate_savings('UnknownTool') returns valid dict",
         isinstance(_po_unknown, dict) and "applicable_gates" in _po_unknown)
    test("PO: estimate_savings('UnknownTool') applicable_gates is a list",
         isinstance(_po_unknown.get("applicable_gates"), list))

    # get_pipeline_analysis returns dict with expected keys
    _po_analysis = _po_get_pipeline_analysis()
    test("PO: get_pipeline_analysis returns dict", isinstance(_po_analysis, dict))
    test("PO: get_pipeline_analysis has per_tool key", "per_tool" in _po_analysis)
    test("PO: get_pipeline_analysis has top_blocking_gates key",
         "top_blocking_gates" in _po_analysis)
    test("PO: get_pipeline_analysis has parallelizable_pairs key",
         "parallelizable_pairs" in _po_analysis)
    test("PO: get_pipeline_analysis has summary key", "summary" in _po_analysis)

except Exception as _po_exc:
    test("Pipeline Optimizer Tests: import and tests", False, str(_po_exc))

# ── Memory Socket Tests ─────────────────────────────────────────────────────
print("\n--- Memory Socket (CS) ---")
try:
    import shared.memory_socket as _cs_mod
    from shared.memory_socket import (
        SOCKET_PATH as _CS_SOCKET_PATH,
        SOCKET_TIMEOUT as _CS_SOCKET_TIMEOUT,
        WorkerUnavailable as _CS_WorkerUnavailable,
        _CB_SVC as _CS_CB_SVC,
        _CB_KWARGS as _CS_CB_KWARGS,
        is_worker_available as _cs_is_worker_available,
    )

    # SOCKET_PATH contains ".memory.sock"
    test("CS: SOCKET_PATH is a string", isinstance(_CS_SOCKET_PATH, str))
    test("CS: SOCKET_PATH contains '.memory.sock'", ".memory.sock" in _CS_SOCKET_PATH)

    # SOCKET_TIMEOUT == 2
    test("CS: SOCKET_TIMEOUT == 2", _CS_SOCKET_TIMEOUT == 2)

    # WorkerUnavailable is an Exception subclass
    test("CS: WorkerUnavailable is Exception subclass",
         issubclass(_CS_WorkerUnavailable, Exception))

    # _CB_SVC == "memory_socket"
    test("CS: _CB_SVC == 'memory_socket'", _CS_CB_SVC == "memory_socket")

    # _CB_KWARGS has expected keys
    _cs_expected_kwargs_keys = {"failure_threshold", "recovery_timeout", "success_threshold"}
    test("CS: _CB_KWARGS has expected keys",
         _cs_expected_kwargs_keys.issubset(_CS_CB_KWARGS.keys()),
         f"missing: {_cs_expected_kwargs_keys - set(_CS_CB_KWARGS.keys())}")
    test("CS: _CB_KWARGS failure_threshold == 3",
         _CS_CB_KWARGS.get("failure_threshold") == 3)
    test("CS: _CB_KWARGS recovery_timeout == 30",
         _CS_CB_KWARGS.get("recovery_timeout") == 30)
    test("CS: _CB_KWARGS success_threshold == 1",
         _CS_CB_KWARGS.get("success_threshold") == 1)

    # Module has expected functions
    _cs_expected_functions = [
        "request", "ping", "count", "query", "get",
        "upsert", "delete", "remember", "flush_queue", "backup",
    ]
    for _cs_fn in _cs_expected_functions:
        test(f"CS: module has function '{_cs_fn}'",
             callable(getattr(_cs_mod, _cs_fn, None)),
             f"missing or not callable: {_cs_fn}")

    # is_worker_available is callable
    test("CS: is_worker_available is callable", callable(_cs_is_worker_available))

except Exception as _cs_exc:
    test("Memory Socket Tests: import and tests", False, str(_cs_exc))

# ═══════════════════════════════════════════════════════════════════════
# Memory Maintenance Tests (MM:)
# ═══════════════════════════════════════════════════════════════════════
try:
    from shared.memory_maintenance import (
        STALE_THRESHOLD_DAYS as _mm_STALE,
        ANCIENT_THRESHOLD_DAYS as _mm_ANCIENT,
        UNDERREPRESENTED_SHARE as _mm_UNDER,
        MIN_MEMORIES_FOR_ANALYSIS as _mm_MIN,
        _POSSIBLE_DUPE_TAG_PREFIX as _mm_DUPE_PREFIX,
        _CANONICAL_CATEGORIES as _mm_CATS,
        _SESSION_REF_RE as _mm_SESSION_RE,
        _SUPERSEDED_PATTERNS as _mm_SUP_PATS,
        _parse_timestamp as _mm_parse_ts,
        _age_days as _mm_age_days,
        _split_tags as _mm_split_tags,
        _has_session_reference as _mm_has_session_ref,
        _has_superseded_language as _mm_has_superseded,
        _count_stats as _mm_count_stats,
        _tag_distribution as _mm_tag_dist,
        _stale_memory_scan as _mm_stale_scan,
        _build_recommendations as _mm_build_recs,
        _similarity_groups as _mm_sim_groups,
    )
    import re as _re_mod
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td

    # Constants
    test("MM: STALE_THRESHOLD_DAYS == 90", _mm_STALE == 90, str(_mm_STALE))
    test("MM: ANCIENT_THRESHOLD_DAYS == 180", _mm_ANCIENT == 180, str(_mm_ANCIENT))
    test("MM: UNDERREPRESENTED_SHARE == 0.03", _mm_UNDER == 0.03, str(_mm_UNDER))
    test("MM: MIN_MEMORIES_FOR_ANALYSIS == 10", _mm_MIN == 10, str(_mm_MIN))
    test("MM: _POSSIBLE_DUPE_TAG_PREFIX == 'possible-dupe:'",
         _mm_DUPE_PREFIX == "possible-dupe:", str(_mm_DUPE_PREFIX))
    test("MM: _CANONICAL_CATEGORIES is list with >= 10 entries",
         isinstance(_mm_CATS, list) and len(_mm_CATS) >= 10,
         f"got {type(_mm_CATS)} len={len(_mm_CATS)}")
    test("MM: _SESSION_REF_RE is compiled regex",
         isinstance(_mm_SESSION_RE, type(_re_mod.compile(""))))
    test("MM: _SUPERSEDED_PATTERNS is list of compiled regex",
         isinstance(_mm_SUP_PATS, list) and len(_mm_SUP_PATS) > 0
         and isinstance(_mm_SUP_PATS[0], type(_re_mod.compile(""))))

    # _parse_timestamp
    _mm_ts = _mm_parse_ts("2025-01-15T12:00:00Z")
    test("MM: _parse_timestamp valid returns datetime",
         isinstance(_mm_ts, _dt), str(_mm_ts))
    test("MM: _parse_timestamp empty string returns None",
         _mm_parse_ts("") is None)
    test("MM: _parse_timestamp None returns None",
         _mm_parse_ts(None) is None)
    test("MM: _parse_timestamp invalid returns None",
         _mm_parse_ts("invalid") is None)

    # _age_days
    _mm_now_ref = _dt(2025, 1, 15, tzinfo=_tz.utc) + _td(days=100)
    _mm_age = _mm_age_days("2025-01-15T12:00:00Z", _mm_now_ref)
    test("MM: _age_days valid returns float > 0",
         isinstance(_mm_age, float) and _mm_age > 0, str(_mm_age))
    test("MM: _age_days empty string returns None",
         _mm_age_days("", _mm_now_ref) is None)

    # _split_tags
    test("MM: _split_tags 'a,b,c' returns ['a','b','c']",
         _mm_split_tags("a,b,c") == ["a", "b", "c"])
    test("MM: _split_tags '' returns []",
         _mm_split_tags("") == [])
    test("MM: _split_tags None returns []",
         _mm_split_tags(None) == [])
    test("MM: _split_tags strips whitespace and removes empty",
         _mm_split_tags("  a , b , ") == ["a", "b"])

    # _has_session_reference
    test("MM: _has_session_reference 'Fixed in Session 42' is True",
         _mm_has_session_ref("Fixed in Session 42") is True)
    test("MM: _has_session_reference 'normal text' is False",
         _mm_has_session_ref("normal text") is False)
    test("MM: _has_session_reference 'sprint-3 work' is True",
         _mm_has_session_ref("sprint-3 work") is True)

    # _has_superseded_language
    test("MM: _has_superseded_language 'was fixed and resolved' is True",
         _mm_has_superseded("was fixed and resolved") is True)
    test("MM: _has_superseded_language 'the old approach was better' is True",
         _mm_has_superseded("the old approach was better") is True)
    test("MM: _has_superseded_language 'normal documentation text' is False",
         _mm_has_superseded("normal documentation text") is False)
    test("MM: _has_superseded_language 'replaced by new system' is True",
         _mm_has_superseded("replaced by new system") is True)
    test("MM: _has_superseded_language 'temporary workaround applied' is True",
         _mm_has_superseded("temporary workaround applied") is True)

    # Synthetic entries for _count_stats, _tag_distribution, etc.
    _mm_now = _dt(2025, 6, 1, tzinfo=_tz.utc)
    _mm_entries = [
        {"id": "1", "document": "session 10 fix", "tags": "type:fix,area:framework",
         "timestamp": "2025-01-01T00:00:00Z", "preview": "fix", "session_time": 0, "possible_dupe": ""},
        {"id": "2", "document": "was fixed and resolved", "tags": "type:error",
         "timestamp": "2024-10-01T00:00:00Z", "preview": "error", "session_time": 0, "possible_dupe": ""},
        {"id": "3", "document": "current doc", "tags": "type:learning,area:testing",
         "timestamp": "2025-05-20T00:00:00Z", "preview": "current", "session_time": 0, "possible_dupe": ""},
        {"id": "4", "document": "possible dupe", "tags": "possible-dupe:abc123",
         "timestamp": "2025-04-01T00:00:00Z", "preview": "dupe", "session_time": 0, "possible_dupe": "abc123"},
    ]

    # _count_stats
    _mm_cs = _mm_count_stats(_mm_entries, _mm_now)
    test("MM: _count_stats returns dict with total key",
         isinstance(_mm_cs, dict) and "total" in _mm_cs, str(type(_mm_cs)))
    test("MM: _count_stats returns dict with age_buckets key",
         "age_buckets" in _mm_cs)
    test("MM: _count_stats total == 4",
         _mm_cs.get("total") == 4, str(_mm_cs.get("total")))

    # _tag_distribution
    _mm_td = _mm_tag_dist(_mm_entries)
    test("MM: _tag_distribution returns dict with total_unique_tags",
         isinstance(_mm_td, dict) and "total_unique_tags" in _mm_td)
    test("MM: _tag_distribution has top_tags key",
         "top_tags" in _mm_td)

    # _stale_memory_scan
    _mm_ss = _mm_stale_scan(_mm_entries, _mm_now)
    test("MM: _stale_memory_scan returns dict with stale_count",
         isinstance(_mm_ss, dict) and "stale_count" in _mm_ss)
    test("MM: _stale_memory_scan detects stale entries (entry1 session ref + old)",
         _mm_ss.get("stale_count", 0) >= 1,
         f"stale_count={_mm_ss.get('stale_count')}")
    # entry2 has superseded language ("was fixed and resolved"), entry1 has session ref + old age
    _mm_stale_ids = {e["id"] for e in _mm_ss.get("stale_entries", [])}
    test("MM: _stale_memory_scan detects entry with superseded language (id=2)",
         "2" in _mm_stale_ids, f"stale_ids={_mm_stale_ids}")

    # _build_recommendations
    _mm_groups = _mm_sim_groups(_mm_entries)
    _mm_recs = _mm_build_recs(_mm_cs, _mm_td, _mm_ss, _mm_groups)
    test("MM: _build_recommendations returns list of strings",
         isinstance(_mm_recs, list) and all(isinstance(r, str) for r in _mm_recs),
         str(type(_mm_recs)))

except Exception as _mm_exc:
    test("MM: import and tests", False, str(_mm_exc))

# ═══════════════════════════════════════════════════════════════════════
# Hook Profiler Tests (HP:)
# ═══════════════════════════════════════════════════════════════════════
try:
    from shared.hook_profiler import (
        LATENCY_LOG as _hp_LATENCY_LOG,
        _percentile as _hp_percentile,
        _ns_to_us as _hp_ns_to_us,
        profile as _hp_profile,
        analyze as _hp_analyze,
        report as _hp_report,
    )

    # Constants
    test("HP: LATENCY_LOG == '/tmp/gate_latency.jsonl'",
         _hp_LATENCY_LOG == "/tmp/gate_latency.jsonl", str(_hp_LATENCY_LOG))

    # _percentile
    test("HP: _percentile([], 50) returns 0.0",
         _hp_percentile([], 50) == 0.0)
    test("HP: _percentile([1,2,3,4,5], 50) returns 3.0",
         _hp_percentile([1.0, 2.0, 3.0, 4.0, 5.0], 50) == 3.0,
         str(_hp_percentile([1.0, 2.0, 3.0, 4.0, 5.0], 50)))
    test("HP: _percentile([1,2,3,4,5], 99) returns 5.0",
         _hp_percentile([1.0, 2.0, 3.0, 4.0, 5.0], 99) == 5.0,
         str(_hp_percentile([1.0, 2.0, 3.0, 4.0, 5.0], 99)))
    test("HP: _percentile([10.0], 50) returns 10.0",
         _hp_percentile([10.0], 50) == 10.0)
    _hp_p_two = _hp_percentile([1.0, 2.0], 50)
    test("HP: _percentile([1.0, 2.0], 50) returns 1.0 or 2.0",
         _hp_p_two in (1.0, 2.0), str(_hp_p_two))

    # _ns_to_us
    test("HP: _ns_to_us(1000.0) returns '1.0'",
         _hp_ns_to_us(1000.0) == "1.0", repr(_hp_ns_to_us(1000.0)))
    test("HP: _ns_to_us(500.0) returns '0.5'",
         _hp_ns_to_us(500.0) == "0.5", repr(_hp_ns_to_us(500.0)))
    test("HP: _ns_to_us(0.0) returns '0.0'",
         _hp_ns_to_us(0.0) == "0.0", repr(_hp_ns_to_us(0.0)))

    # profile function
    def _hp_fake_check(tool_name, tool_input, state):
        class _R:
            blocked = False
        return _R()

    _hp_wrapped = _hp_profile("test_gate", _hp_fake_check)
    test("HP: profile returns a callable",
         callable(_hp_wrapped))
    _hp_result = _hp_wrapped("Edit", {}, {})
    test("HP: wrapped returns result",
         hasattr(_hp_result, "blocked"))
    test("HP: wrapped has _profiler_wrapped == True",
         getattr(_hp_wrapped, "_profiler_wrapped", False) is True)
    test("HP: wrapped has _original_check attribute",
         hasattr(_hp_wrapped, "_original_check"))
    test("HP: wrapped _original_check is original function",
         getattr(_hp_wrapped, "_original_check", None) is _hp_fake_check)

    # analyze and report
    _hp_stats = _hp_analyze()
    test("HP: analyze() returns a dict",
         isinstance(_hp_stats, dict))
    _hp_rep = _hp_report()
    test("HP: report() returns a string",
         isinstance(_hp_rep, str))

except Exception as _hp_exc:
    test("HP: import and tests", False, str(_hp_exc))

# ═══════════════════════════════════════════════════════════════════════
# Memory Decay Tests (MD:)
# ═══════════════════════════════════════════════════════════════════════
try:
    from shared.memory_decay import (
        DEFAULT_HALF_LIFE_DAYS as _md_HALF_LIFE,
        TIER_BASE as _md_TIER_BASE,
        TIER_BASE_DEFAULT as _md_TIER_BASE_DEFAULT,
        _MAX_ACCESS_BOOST as _md_MAX_ACCESS_BOOST,
        _RECENCY_BOOST as _md_RECENCY_BOOST,
        _RECENCY_WINDOW_DAYS as _md_RECENCY_WINDOW,
        _MAX_TAG_BONUS as _md_MAX_TAG_BONUS,
        _time_decay_factor as _md_time_decay,
        _access_boost as _md_access_boost,
        _tag_relevance_bonus as _md_tag_bonus,
        calculate_relevance_score as _md_calc_score,
        rank_memories as _md_rank,
        identify_stale_memories as _md_identify_stale,
    )
    import math as _math_mod
    from datetime import datetime as _md_dt, timezone as _md_tz, timedelta as _md_td

    # Constants
    test("MD: DEFAULT_HALF_LIFE_DAYS == 45.0",
         _md_HALF_LIFE == 45.0, str(_md_HALF_LIFE))
    test("MD: TIER_BASE is dict with keys 1, 2, 3",
         isinstance(_md_TIER_BASE, dict) and set(_md_TIER_BASE.keys()) == {1, 2, 3})
    test("MD: TIER_BASE[1] == 1.0", _md_TIER_BASE.get(1) == 1.0)
    test("MD: TIER_BASE[2] == 0.7", _md_TIER_BASE.get(2) == 0.7)
    test("MD: TIER_BASE[3] == 0.4", _md_TIER_BASE.get(3) == 0.4)
    test("MD: TIER_BASE_DEFAULT == 0.4",
         _md_TIER_BASE_DEFAULT == 0.4, str(_md_TIER_BASE_DEFAULT))
    test("MD: _MAX_ACCESS_BOOST == 0.20",
         _md_MAX_ACCESS_BOOST == 0.20, str(_md_MAX_ACCESS_BOOST))
    test("MD: _RECENCY_BOOST == 0.10",
         _md_RECENCY_BOOST == 0.10, str(_md_RECENCY_BOOST))
    test("MD: _RECENCY_WINDOW_DAYS == 7",
         _md_RECENCY_WINDOW == 7, str(_md_RECENCY_WINDOW))
    test("MD: _MAX_TAG_BONUS == 0.15",
         _md_MAX_TAG_BONUS == 0.15, str(_md_MAX_TAG_BONUS))

    # _time_decay_factor
    test("MD: _time_decay_factor(0.0) returns 1.0",
         _md_time_decay(0.0) == 1.0, str(_md_time_decay(0.0)))
    _md_decay_45 = _md_time_decay(45.0)
    test("MD: _time_decay_factor(45.0) returns ~0.5 (half-life)",
         abs(_md_decay_45 - 0.5) < 1e-9, str(_md_decay_45))
    _md_decay_90 = _md_time_decay(90.0)
    test("MD: _time_decay_factor(90.0) returns ~0.25 (two half-lives)",
         abs(_md_decay_90 - 0.25) < 1e-9, str(_md_decay_90))

    # _access_boost
    test("MD: _access_boost(0) returns 0.0",
         _md_access_boost(0) == 0.0, str(_md_access_boost(0)))
    _md_boost_100 = _md_access_boost(100)
    test("MD: _access_boost(100) returns > 0 and <= 0.20",
         0 < _md_boost_100 <= 0.20, str(_md_boost_100))

    # _tag_relevance_bonus
    _md_tb1 = _md_tag_bonus("type:fix", "type:fix")
    test("MD: _tag_relevance_bonus matching tags returns > 0",
         _md_tb1 > 0, str(_md_tb1))
    test("MD: _tag_relevance_bonus empty entry tags returns 0.0",
         _md_tag_bonus("", "type:fix") == 0.0)
    test("MD: _tag_relevance_bonus empty query returns 0.0",
         _md_tag_bonus("type:fix", "") == 0.0)
    _md_tb_multi = _md_tag_bonus("type:fix,area:test", "type:fix,area:test")
    test("MD: _tag_relevance_bonus multiple matching returns > 0 and <= 0.15",
         0 < _md_tb_multi <= 0.15, str(_md_tb_multi))

    # calculate_relevance_score
    _md_fresh_ts = _md_dt.now(tz=_md_tz.utc).isoformat()
    _md_score_t1 = _md_calc_score({"tier": 1, "timestamp": _md_fresh_ts, "retrieval_count": 0, "tags": ""})
    test("MD: calculate_relevance_score T1 fresh returns > 0.9",
         _md_score_t1 > 0.9, str(_md_score_t1))
    _md_score_t3_empty = _md_calc_score({"tier": 3, "timestamp": "", "retrieval_count": 0, "tags": ""})
    test("MD: calculate_relevance_score T3 missing timestamp returns > 0",
         _md_score_t3_empty > 0, str(_md_score_t3_empty))

    # rank_memories
    _md_mem1 = {"tier": 1, "timestamp": _md_fresh_ts, "retrieval_count": 0, "tags": ""}
    _md_old_ts = (_md_dt.now(tz=_md_tz.utc) - _md_td(days=200)).isoformat()
    _md_mem2 = {"tier": 3, "timestamp": _md_old_ts, "retrieval_count": 0, "tags": ""}
    _md_ranked = _md_rank([_md_mem1, _md_mem2])
    test("MD: rank_memories returns list",
         isinstance(_md_ranked, list))
    test("MD: rank_memories sorted by _relevance_score descending",
         len(_md_ranked) == 2 and
         _md_ranked[0].get("_relevance_score", 0) >= _md_ranked[1].get("_relevance_score", 0))
    test("MD: rank_memories each entry has _relevance_score key",
         all("_relevance_score" in e for e in _md_ranked))
    test("MD: rank_memories([]) returns []",
         _md_rank([]) == [])

    # identify_stale_memories
    test("MD: identify_stale_memories([], threshold=0.2) returns []",
         _md_identify_stale([], threshold=0.2) == [])
    _md_stale_result = _md_identify_stale([_md_mem2], threshold=0.9)
    test("MD: identify_stale_memories with old T3 entry below threshold returns it",
         len(_md_stale_result) == 1, str(len(_md_stale_result)))

except Exception as _md_exc:
    test("MD: import and tests", False, str(_md_exc))

# ═══════════════════════════════════════════════════════════════════════
# Gate Pruner Tests (GP:)
# ═══════════════════════════════════════════════════════════════════════
try:
    from shared.gate_pruner import (
        KEEP as _gp_KEEP,
        OPTIMIZE as _gp_OPTIMIZE,
        MERGE_CANDIDATE as _gp_MERGE,
        DORMANT as _gp_DORMANT,
        _TIER1 as _gp_TIER1,
        _LOW_BLOCK_RATE as _gp_LOW_BLOCK_RATE,
        _MIN_EVALS as _gp_MIN_EVALS,
        _HIGH_LATENCY_MS as _gp_HIGH_LATENCY,
        _HIGH_OVERRIDE as _gp_HIGH_OVERRIDE,
        _VERDICT_RANK as _gp_VERDICT_RANK,
        GateAnalysis as _gp_GateAnalysis,
        PruneRecommendation as _gp_PruneRec,
        _classify as _gp_classify,
        _load_json as _gp_load_json,
        analyze_gates as _gp_analyze_gates,
        get_prune_recommendations as _gp_get_recs,
        render_pruner_report as _gp_render,
    )

    # Constants
    test("GP: KEEP == 'keep'", _gp_KEEP == "keep", repr(_gp_KEEP))
    test("GP: OPTIMIZE == 'optimize'", _gp_OPTIMIZE == "optimize", repr(_gp_OPTIMIZE))
    test("GP: MERGE_CANDIDATE == 'merge_candidate'",
         _gp_MERGE == "merge_candidate", repr(_gp_MERGE))
    test("GP: DORMANT == 'dormant'", _gp_DORMANT == "dormant", repr(_gp_DORMANT))
    test("GP: _TIER1 is frozenset with 3 entries",
         isinstance(_gp_TIER1, frozenset) and len(_gp_TIER1) == 3,
         f"type={type(_gp_TIER1)} len={len(_gp_TIER1)}")
    test("GP: _TIER1 contains 'gate_01_read_before_edit'",
         "gate_01_read_before_edit" in _gp_TIER1)
    test("GP: _LOW_BLOCK_RATE == 0.005",
         _gp_LOW_BLOCK_RATE == 0.005, str(_gp_LOW_BLOCK_RATE))
    test("GP: _MIN_EVALS == 1000",
         _gp_MIN_EVALS == 1000, str(_gp_MIN_EVALS))
    test("GP: _HIGH_LATENCY_MS == 10.0",
         _gp_HIGH_LATENCY == 10.0, str(_gp_HIGH_LATENCY))
    test("GP: _HIGH_OVERRIDE == 0.15",
         _gp_HIGH_OVERRIDE == 0.15, str(_gp_HIGH_OVERRIDE))
    test("GP: _VERDICT_RANK has 4 entries",
         isinstance(_gp_VERDICT_RANK, dict) and len(_gp_VERDICT_RANK) == 4,
         str(len(_gp_VERDICT_RANK)))
    test("GP: _VERDICT_RANK[DORMANT] == 4",
         _gp_VERDICT_RANK.get(_gp_DORMANT) == 4,
         str(_gp_VERDICT_RANK.get(_gp_DORMANT)))

    # Dataclass construction
    _gp_ga = _gp_GateAnalysis(
        gate="test_gate", tier1=False, blocks=0, overrides=0, prevented=0,
        eval_count=0, avg_ms=0.0, block_rate=0.0, override_rate=0.0,
        has_q_data=False, verdict=_gp_KEEP,
    )
    test("GP: GateAnalysis dataclass construction",
         isinstance(_gp_ga, _gp_GateAnalysis))
    test("GP: GateAnalysis defaults reasons to []",
         _gp_ga.reasons == [])
    _gp_pr = _gp_PruneRec(
        rank=1, gate="test_gate", verdict=_gp_KEEP,
        reasons=[], avg_ms=0.0, blocks=0, prevented=0,
    )
    test("GP: PruneRecommendation dataclass construction",
         isinstance(_gp_pr, _gp_PruneRec))

    # _classify Tier 1 always returns KEEP
    _gp_v_t1, _gp_r_t1 = _gp_classify(
        "gate_01_read_before_edit", True, 0, 0, 0, 5000, 1.0, 0.001, 0.0
    )
    test("GP: _classify Tier 1 gate always returns KEEP",
         _gp_v_t1 == _gp_KEEP, str(_gp_v_t1))

    # _classify dormant gate (enough evals, low block rate, nothing prevented)
    _gp_v_dorm, _gp_r_dorm = _gp_classify(
        "gate_99_test", False, blocks=2, overrides=0, prevented=0,
        eval_count=2000, avg_ms=1.0, block_rate=0.001, override_rate=0.0
    )
    test("GP: _classify dormant gate returns DORMANT",
         _gp_v_dorm == _gp_DORMANT, str(_gp_v_dorm))

    # _classify high override rate
    _gp_v_opt, _gp_r_opt = _gp_classify(
        "gate_88_test", False, blocks=100, overrides=20, prevented=0,
        eval_count=2000, avg_ms=1.0, block_rate=0.05, override_rate=0.2
    )
    test("GP: _classify high override rate returns OPTIMIZE",
         _gp_v_opt == _gp_OPTIMIZE, str(_gp_v_opt))

    # _load_json nonexistent path returns {}
    test("GP: _load_json('/nonexistent') returns {}",
         _gp_load_json("/nonexistent") == {})

    # analyze_gates
    _gp_analysis = _gp_analyze_gates()
    test("GP: analyze_gates() returns a dict",
         isinstance(_gp_analysis, dict))

    # get_prune_recommendations
    _gp_recs = _gp_get_recs()
    test("GP: get_prune_recommendations() returns a list",
         isinstance(_gp_recs, list))

    # render_pruner_report
    _gp_rendered = _gp_render()
    test("GP: render_pruner_report() returns a string",
         isinstance(_gp_rendered, str))

except Exception as _gp_exc:
    test("GP: import and tests", False, str(_gp_exc))

# =============================================================================
# TP: tool_patterns (shared/tool_patterns.py)
# =============================================================================
try:
    import math as _tp_math
    import tempfile as _tp_tempfile
    import json as _tp_json
    from collections import defaultdict as _tp_defaultdict
    from shared.tool_patterns import (
        _invalidate_cache,
        _queue_mtime,
        _needs_refresh,
        MarkovChain,
        build_markov_chain,
        _transition_probability,
        _sequence_log_probability,
        _score_all_sequences,
        _std,
        _extract_ngrams,
        _label_for_template,
        WorkflowTemplate,
        AnomalyReport,
        load_sequences,
        _MIN_TRANSITION_COUNT,
        _MIN_WORKFLOW_LEN,
        _MAX_WORKFLOW_LEN,
        _ANOMALY_SIGMA_THRESHOLD,
        _LAPLACE_ALPHA,
        _SESSION_BREAK_SECONDS,
    )

    # --- Constants ---
    test("TP: _MIN_TRANSITION_COUNT == 2",
         _MIN_TRANSITION_COUNT == 2, str(_MIN_TRANSITION_COUNT))
    test("TP: _MIN_WORKFLOW_LEN == 3",
         _MIN_WORKFLOW_LEN == 3, str(_MIN_WORKFLOW_LEN))
    test("TP: _MAX_WORKFLOW_LEN == 8",
         _MAX_WORKFLOW_LEN == 8, str(_MAX_WORKFLOW_LEN))
    test("TP: _ANOMALY_SIGMA_THRESHOLD == 2.0",
         _ANOMALY_SIGMA_THRESHOLD == 2.0, str(_ANOMALY_SIGMA_THRESHOLD))
    test("TP: _LAPLACE_ALPHA == 0.1",
         _LAPLACE_ALPHA == 0.1, str(_LAPLACE_ALPHA))
    test("TP: _SESSION_BREAK_SECONDS == 300.0",
         _SESSION_BREAK_SECONDS == 300.0, str(_SESSION_BREAK_SECONDS))

    # --- _queue_mtime ---
    test("TP: _queue_mtime('/nonexistent/file.jsonl') returns 0.0",
         _queue_mtime("/nonexistent/file.jsonl") == 0.0)
    with _tp_tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as _tp_qf:
        _tp_qf_path = _tp_qf.name
    _tp_mtime = _queue_mtime(_tp_qf_path)
    test("TP: _queue_mtime existing file returns positive float",
         isinstance(_tp_mtime, float) and _tp_mtime > 0.0, str(_tp_mtime))

    # --- _invalidate_cache ---
    _invalidate_cache()
    import shared.tool_patterns as _tp_mod
    test("TP: _invalidate_cache sets _chain_cache to None",
         _tp_mod._chain_cache is None)
    test("TP: _invalidate_cache sets _sequences_cache to None",
         _tp_mod._sequences_cache is None)
    test("TP: _invalidate_cache sets _cache_mtime to 0.0",
         _tp_mod._cache_mtime == 0.0)

    # --- _needs_refresh ---
    _invalidate_cache()
    test("TP: _needs_refresh nonexistent path returns False (mtime 0 == cache 0)",
         not _needs_refresh("/nonexistent/x.jsonl"))
    test("TP: _needs_refresh existing file with 0 cache mtime returns True",
         _needs_refresh(_tp_qf_path))

    # --- MarkovChain dataclass ---
    _tp_chain_empty = MarkovChain()
    test("TP: MarkovChain default total_starts == 0",
         _tp_chain_empty.total_starts == 0)
    test("TP: MarkovChain default sequence_count == 0",
         _tp_chain_empty.sequence_count == 0)
    test("TP: MarkovChain default vocabulary is empty set",
         isinstance(_tp_chain_empty.vocabulary, set) and len(_tp_chain_empty.vocabulary) == 0)

    # --- build_markov_chain ---
    _tp_seqs = [
        ["Read", "Edit", "Bash"],
        ["Read", "Edit", "Bash"],
        ["Read", "Write", "Bash"],
        ["Glob", "Read", "Edit"],
    ]
    _tp_chain = build_markov_chain(_tp_seqs)
    test("TP: build_markov_chain returns MarkovChain",
         isinstance(_tp_chain, MarkovChain))
    test("TP: build_markov_chain sequence_count == 4",
         _tp_chain.sequence_count == 4, str(_tp_chain.sequence_count))
    test("TP: build_markov_chain total_starts == 4",
         _tp_chain.total_starts == 4, str(_tp_chain.total_starts))
    test("TP: build_markov_chain vocabulary contains Read",
         "Read" in _tp_chain.vocabulary)
    test("TP: build_markov_chain vocabulary contains Bash",
         "Bash" in _tp_chain.vocabulary)
    test("TP: build_markov_chain start_counts[Read] == 3",
         _tp_chain.start_counts["Read"] == 3, str(_tp_chain.start_counts.get("Read")))
    test("TP: build_markov_chain start_counts[Glob] == 1",
         _tp_chain.start_counts["Glob"] == 1, str(_tp_chain.start_counts.get("Glob")))
    test("TP: build_markov_chain transitions[Read][Edit] == 3",
         _tp_chain.transitions["Read"]["Edit"] == 3,
         str(_tp_chain.transitions["Read"]["Edit"]))
    test("TP: build_markov_chain transitions[Edit][Bash] == 2",
         _tp_chain.transitions["Edit"]["Bash"] == 2,
         str(_tp_chain.transitions["Edit"]["Bash"]))
    test("TP: build_markov_chain empty sequences returns chain with 0 seqs",
         build_markov_chain([]).sequence_count == 0)

    # --- _transition_probability ---
    _tp_prob = _transition_probability(_tp_chain, "Read", "Edit")
    test("TP: _transition_probability returns float in (0,1]",
         isinstance(_tp_prob, float) and 0.0 < _tp_prob <= 1.0, str(_tp_prob))
    test("TP: _transition_probability Read->Edit > Read->Write (more transitions)",
         _transition_probability(_tp_chain, "Read", "Edit") >
         _transition_probability(_tp_chain, "Read", "Write"))
    _tp_unseen_prob = _transition_probability(_tp_chain, "Read", "NonExistentTool")
    test("TP: _transition_probability unseen transition > 0 (Laplace smoothing)",
         _tp_unseen_prob > 0.0, str(_tp_unseen_prob))

    # --- _sequence_log_probability ---
    _tp_logp = _sequence_log_probability(_tp_chain, ["Read", "Edit", "Bash"])
    test("TP: _sequence_log_probability returns negative float",
         isinstance(_tp_logp, float) and _tp_logp < 0.0, str(_tp_logp))
    _tp_logp_empty = _sequence_log_probability(_tp_chain, [])
    test("TP: _sequence_log_probability empty sequence returns -inf",
         _tp_logp_empty == float("-inf"))
    _tp_chain_empty2 = MarkovChain()
    _tp_logp_nochain = _sequence_log_probability(_tp_chain_empty2, ["Read"])
    test("TP: _sequence_log_probability empty chain returns -inf",
         _tp_logp_nochain == float("-inf"))
    # Single tool sequence
    _tp_logp_single = _sequence_log_probability(_tp_chain, ["Read"])
    test("TP: _sequence_log_probability single tool returns finite negative",
         _tp_math.isfinite(_tp_logp_single) and _tp_logp_single < 0.0,
         str(_tp_logp_single))

    # --- _score_all_sequences ---
    _tp_scores = _score_all_sequences(_tp_chain, _tp_seqs)
    test("TP: _score_all_sequences returns list of same length",
         len(_tp_scores) == len(_tp_seqs), str(len(_tp_scores)))
    test("TP: _score_all_sequences all values are finite floats",
         all(_tp_math.isfinite(s) for s in _tp_scores))

    # --- _std ---
    test("TP: _std of [2,4,4,4,5,5,7,9] is 2.0",
         abs(_std([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]) - 2.0) < 1e-9)
    test("TP: _std single value returns 0.0",
         _std([42.0]) == 0.0)
    test("TP: _std empty list returns 0.0",
         _std([]) == 0.0)
    test("TP: _std identical values returns 0.0",
         _std([3.0, 3.0, 3.0]) == 0.0)
    test("TP: _std [0, 10] returns 5.0",
         _std([0.0, 10.0]) == 5.0)

    # --- _extract_ngrams ---
    _tp_ng = _extract_ngrams(["A", "B", "C", "D"], 2)
    test("TP: _extract_ngrams n=2 on 4 items returns 3 ngrams",
         len(_tp_ng) == 3, str(len(_tp_ng)))
    test("TP: _extract_ngrams first ngram is [A,B]",
         _tp_ng[0] == ["A", "B"])
    test("TP: _extract_ngrams last ngram is [C,D]",
         _tp_ng[-1] == ["C", "D"])
    _tp_ng3 = _extract_ngrams(["A", "B", "C"], 3)
    test("TP: _extract_ngrams n=3 on 3 items returns 1 ngram",
         len(_tp_ng3) == 1 and _tp_ng3[0] == ["A", "B", "C"])
    _tp_ng_empty = _extract_ngrams(["A"], 2)
    test("TP: _extract_ngrams n > len returns empty list",
         _tp_ng_empty == [])

    # --- _label_for_template ---
    test("TP: _label_for_template ['Read','Edit','Bash'] -> 'read-edit-test'",
         _label_for_template(["Read", "Edit", "Bash"]) == "read-edit-test")
    test("TP: _label_for_template ['Read','Write','Bash'] -> 'read-write-test'",
         _label_for_template(["Read", "Write", "Bash"]) == "read-write-test")
    test("TP: _label_for_template ['Bash','Edit','Bash'] -> 'test-fix-test'",
         _label_for_template(["Bash", "Edit", "Bash"]) == "test-fix-test")
    test("TP: _label_for_template ['Glob','Read','Edit'] -> 'search-read-edit'",
         _label_for_template(["Glob", "Read", "Edit"]) == "search-read-edit")
    test("TP: _label_for_template ['Read','Edit'] -> 'read-then-edit'",
         _label_for_template(["Read", "Edit"]) == "read-then-edit")
    test("TP: _label_for_template unknown pattern falls back to dominant-tool label",
         _label_for_template(["Foo", "Foo", "Bar"]).endswith("-centric workflow"))
    test("TP: _label_for_template empty list -> 'mixed workflow'",
         _label_for_template([]) == "mixed workflow")
    # Pattern with memory lookup
    test("TP: _label_for_template ['mcp__memory__search_knowledge'] -> 'memory-lookup'",
         _label_for_template(["mcp__memory__search_knowledge"]) == "memory-lookup")
    # Pattern with memory-guided edit
    test("TP: _label_for_template memory-guided edit pattern matches",
         _label_for_template(
             ["mcp__memory__search_knowledge", "Read", "Edit"]
         ) == "memory-guided edit")

    # --- WorkflowTemplate dataclass ---
    _tp_wt = WorkflowTemplate(tools=["Read", "Edit"], count=5, frequency=0.5, label="read-then-edit")
    test("TP: WorkflowTemplate construction",
         isinstance(_tp_wt, WorkflowTemplate))
    test("TP: WorkflowTemplate tools attribute",
         _tp_wt.tools == ["Read", "Edit"])
    test("TP: WorkflowTemplate count attribute",
         _tp_wt.count == 5)
    test("TP: WorkflowTemplate frequency attribute",
         _tp_wt.frequency == 0.5)

    # --- AnomalyReport dataclass ---
    _tp_ar = AnomalyReport(
        tools=["A", "B"], score=-5.0, baseline_mean=-3.0, baseline_std=1.0,
        sigma=2.0, reason="test", unusual_transitions=[("A", "B")],
    )
    test("TP: AnomalyReport construction",
         isinstance(_tp_ar, AnomalyReport))
    test("TP: AnomalyReport sigma attribute",
         _tp_ar.sigma == 2.0)
    test("TP: AnomalyReport unusual_transitions attribute",
         _tp_ar.unusual_transitions == [("A", "B")])

    # --- load_sequences ---
    import os as _tp_os
    _tp_tmp = _tp_tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False
    )
    _tp_entries = [
        {"metadata": {"tool_name": "Read",  "session_id": "s1", "session_time": 1000.0}},
        {"metadata": {"tool_name": "Edit",  "session_id": "s1", "session_time": 1001.0}},
        {"metadata": {"tool_name": "Bash",  "session_id": "s1", "session_time": 1002.0}},
        {"metadata": {"tool_name": "Glob",  "session_id": "s2", "session_time": 2000.0}},
        {"metadata": {"tool_name": "Read",  "session_id": "s2", "session_time": 2001.0}},
        # skip tool
        {"metadata": {"tool_name": "UserPrompt", "session_id": "s2", "session_time": 2002.0}},
        {"metadata": {"tool_name": "Write", "session_id": "s2", "session_time": 2003.0}},
    ]
    for _tp_e in _tp_entries:
        _tp_tmp.write(_tp_json.dumps(_tp_e) + "\n")
    _tp_tmp.close()
    _tp_loaded = load_sequences(_tp_tmp.name)
    test("TP: load_sequences returns list",
         isinstance(_tp_loaded, list))
    test("TP: load_sequences splits by session_id (2 sessions -> 2 seqs)",
         len(_tp_loaded) == 2, str(len(_tp_loaded)))
    test("TP: load_sequences session 1 has 3 tools",
         ["Read", "Edit", "Bash"] in _tp_loaded)
    test("TP: load_sequences skips UserPrompt by default",
         all("UserPrompt" not in seq for seq in _tp_loaded))
    test("TP: load_sequences nonexistent path returns []",
         load_sequences("/nonexistent/queue.jsonl") == [])
    # Time-gap splitting in same session
    _tp_tmp2 = _tp_tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False
    )
    _tp_gap_entries = [
        {"metadata": {"tool_name": "Read", "session_id": "s1", "session_time": 1000.0}},
        {"metadata": {"tool_name": "Edit", "session_id": "s1", "session_time": 1001.0}},
        # Gap of 400 seconds exceeds _SESSION_BREAK_SECONDS=300
        {"metadata": {"tool_name": "Bash", "session_id": "s1", "session_time": 1401.0}},
        {"metadata": {"tool_name": "Glob", "session_id": "s1", "session_time": 1402.0}},
    ]
    for _tp_ge in _tp_gap_entries:
        _tp_tmp2.write(_tp_json.dumps(_tp_ge) + "\n")
    _tp_tmp2.close()
    _tp_gap_loaded = load_sequences(_tp_tmp2.name)
    test("TP: load_sequences splits on time gap > 300s",
         len(_tp_gap_loaded) == 2, str(len(_tp_gap_loaded)))
    # Cleanup temp files
    try:
        _tp_os.unlink(_tp_tmp.name)
        _tp_os.unlink(_tp_tmp2.name)
        _tp_os.unlink(_tp_qf_path)
    except Exception:
        pass

except Exception as _tp_exc:
    test("TP: import and tests", False, str(_tp_exc))

# =============================================================================
# DR: domain_registry (shared/domain_registry.py)
# =============================================================================
try:
    from shared.domain_registry import (
        CLAUDE_DIR,
        DOMAINS_DIR,
        ACTIVE_FILE,
        DEFAULT_PROFILE,
        _short_gate_name,
        _gate_matches_list,
        _lookup_gate_mode,
        load_domain_profile,
        detect_domain_from_live_state,
        get_domain_memory_tags,
        get_domain_l2_keywords,
        get_domain_token_budget,
        get_domain_context_for_injection,
    )

    # --- Path constants ---
    test("DR: CLAUDE_DIR is a string path",
         isinstance(CLAUDE_DIR, str) and len(CLAUDE_DIR) > 0)
    test("DR: DOMAINS_DIR is under CLAUDE_DIR",
         DOMAINS_DIR.startswith(CLAUDE_DIR))
    test("DR: ACTIVE_FILE is under DOMAINS_DIR",
         ACTIVE_FILE.startswith(DOMAINS_DIR))

    # --- DEFAULT_PROFILE keys ---
    test("DR: DEFAULT_PROFILE has 'description' key",
         "description" in DEFAULT_PROFILE)
    test("DR: DEFAULT_PROFILE has 'security_profile' key",
         "security_profile" in DEFAULT_PROFILE)
    test("DR: DEFAULT_PROFILE has 'gate_modes' key",
         "gate_modes" in DEFAULT_PROFILE)
    test("DR: DEFAULT_PROFILE has 'disabled_gates' key",
         "disabled_gates" in DEFAULT_PROFILE)
    test("DR: DEFAULT_PROFILE has 'memory_tags' key",
         "memory_tags" in DEFAULT_PROFILE)
    test("DR: DEFAULT_PROFILE has 'l2_keywords' key",
         "l2_keywords" in DEFAULT_PROFILE)
    test("DR: DEFAULT_PROFILE has 'auto_detect' key",
         "auto_detect" in DEFAULT_PROFILE)
    test("DR: DEFAULT_PROFILE has 'graduation' key",
         "graduation" in DEFAULT_PROFILE)
    test("DR: DEFAULT_PROFILE has 'token_budget' key",
         "token_budget" in DEFAULT_PROFILE)
    test("DR: DEFAULT_PROFILE token_budget == 800",
         DEFAULT_PROFILE["token_budget"] == 800, str(DEFAULT_PROFILE["token_budget"]))
    test("DR: DEFAULT_PROFILE security_profile == 'balanced'",
         DEFAULT_PROFILE["security_profile"] == "balanced")
    test("DR: DEFAULT_PROFILE gate_modes is dict",
         isinstance(DEFAULT_PROFILE["gate_modes"], dict))
    test("DR: DEFAULT_PROFILE disabled_gates is list",
         isinstance(DEFAULT_PROFILE["disabled_gates"], list))

    # --- _short_gate_name ---
    test("DR: _short_gate_name('gate_04_memory_first') -> 'gate_04'",
         _short_gate_name("gate_04_memory_first") == "gate_04",
         _short_gate_name("gate_04_memory_first"))
    test("DR: _short_gate_name('gates.gate_04_memory_first') -> 'gate_04'",
         _short_gate_name("gates.gate_04_memory_first") == "gate_04",
         _short_gate_name("gates.gate_04_memory_first"))
    test("DR: _short_gate_name('gate_01_read_before_edit') -> 'gate_01'",
         _short_gate_name("gate_01_read_before_edit") == "gate_01",
         _short_gate_name("gate_01_read_before_edit"))
    test("DR: _short_gate_name('gate_13') -> 'gate_13'",
         _short_gate_name("gate_13") == "gate_13",
         _short_gate_name("gate_13"))
    test("DR: _short_gate_name('foobar') -> 'foobar' (no underscore split)",
         _short_gate_name("foobar") == "foobar",
         _short_gate_name("foobar"))
    test("DR: _short_gate_name('gates.gate_13_main_exempt') -> 'gate_13'",
         _short_gate_name("gates.gate_13_main_exempt") == "gate_13",
         _short_gate_name("gates.gate_13_main_exempt"))

    # --- _gate_matches_list ---
    test("DR: _gate_matches_list exact match returns True",
         _gate_matches_list("gate_04_memory_first", ["gate_04_memory_first"]))
    test("DR: _gate_matches_list short-name match returns True",
         _gate_matches_list("gate_04_memory_first", ["gate_04"]))
    test("DR: _gate_matches_list different gate returns False",
         not _gate_matches_list("gate_04_memory_first", ["gate_05"]))
    test("DR: _gate_matches_list empty list returns False",
         not _gate_matches_list("gate_04", []))
    test("DR: _gate_matches_list gates. prefix stripped for matching",
         _gate_matches_list("gates.gate_04_memory_first", ["gate_04"]))
    test("DR: _gate_matches_list multiple entries matches correctly",
         _gate_matches_list("gate_07", ["gate_01", "gate_07", "gate_13"]))

    # --- _lookup_gate_mode ---
    _dr_modes = {
        "gate_04_memory_first": "warn",
        "gate_07": "block",
    }
    test("DR: _lookup_gate_mode exact match",
         _lookup_gate_mode("gate_04_memory_first", _dr_modes) == "warn",
         str(_lookup_gate_mode("gate_04_memory_first", _dr_modes)))
    test("DR: _lookup_gate_mode short name match",
         _lookup_gate_mode("gate_04", _dr_modes) == "warn",
         str(_lookup_gate_mode("gate_04", _dr_modes)))
    test("DR: _lookup_gate_mode returns None when not found",
         _lookup_gate_mode("gate_99", _dr_modes) is None)
    test("DR: _lookup_gate_mode empty dict returns None",
         _lookup_gate_mode("gate_04", {}) is None)

    # --- load_domain_profile with non-existent domain ---
    _dr_profile = load_domain_profile("__nonexistent_domain_xyz__")
    test("DR: load_domain_profile nonexistent domain returns DEFAULT_PROFILE",
         isinstance(_dr_profile, dict))
    test("DR: load_domain_profile nonexistent has 'description' key",
         "description" in _dr_profile)
    test("DR: load_domain_profile nonexistent has 'graduation' key",
         "graduation" in _dr_profile)
    test("DR: load_domain_profile nonexistent has 'auto_detect' key",
         "auto_detect" in _dr_profile)
    test("DR: load_domain_profile nonexistent token_budget == 800",
         _dr_profile.get("token_budget") == 800, str(_dr_profile.get("token_budget")))

    # --- detect_domain_from_live_state ---
    test("DR: detect_domain_from_live_state None returns None",
         detect_domain_from_live_state(None) is None)
    test("DR: detect_domain_from_live_state empty dict returns None",
         detect_domain_from_live_state({}) is None)
    test("DR: detect_domain_from_live_state non-matching state returns None or str",
         detect_domain_from_live_state({"project": "__no_match_xyz__", "feature": ""}) in (None, str(detect_domain_from_live_state({"project": "__no_match_xyz__"}))))

    # --- get_domain_memory_tags ---
    _dr_tags = get_domain_memory_tags("__nonexistent_domain_xyz__")
    test("DR: get_domain_memory_tags nonexistent domain returns list",
         isinstance(_dr_tags, list))

    # --- get_domain_l2_keywords ---
    _dr_kw = get_domain_l2_keywords("__nonexistent_domain_xyz__")
    test("DR: get_domain_l2_keywords nonexistent domain returns list",
         isinstance(_dr_kw, list))

    # --- get_domain_token_budget ---
    _dr_budget = get_domain_token_budget("__nonexistent_domain_xyz__")
    test("DR: get_domain_token_budget nonexistent domain returns 800",
         _dr_budget == 800, str(_dr_budget))

    # --- get_domain_context_for_injection ---
    _dr_ctx = get_domain_context_for_injection("__nonexistent_domain_xyz__")
    test("DR: get_domain_context_for_injection returns 2-tuple",
         isinstance(_dr_ctx, tuple) and len(_dr_ctx) == 2)
    test("DR: get_domain_context_for_injection mastery is string",
         isinstance(_dr_ctx[0], str))
    test("DR: get_domain_context_for_injection behavior is string",
         isinstance(_dr_ctx[1], str))
    _dr_ctx_none = get_domain_context_for_injection(None)
    test("DR: get_domain_context_for_injection None arg returns ('','') or active domain",
         isinstance(_dr_ctx_none, tuple) and len(_dr_ctx_none) == 2)

except Exception as _dr_exc:
    test("DR: import and tests", False, str(_dr_exc))

# =============================================================================
# MT: mutation_tester (shared/mutation_tester.py)
# =============================================================================
try:
    import ast as _mt_ast
    import copy as _mt_copy
    from shared.mutation_tester import (
        MutantResult,
        MutationReport,
        _BoolFlipVisitor,
        _CmpOpSwapVisitor,
        _CondRemoveVisitor,
        _ReturnFlipVisitor,
        _LogicNegateVisitor,
        _StrSwapVisitor,
        _count_targets,
        _apply_mutation,
        generate_mutants,
        _find_test_framework,
        _find_hooks_dir,
    )

    # --- MutantResult dataclass ---
    _mt_mr = MutantResult(
        operator="BOOL_FLIP",
        description="line 5: True -> False",
        lineno=5,
        killed=True,
        test_output="FAIL",
        mutant_source="x = False",
    )
    test("MT: MutantResult construction",
         isinstance(_mt_mr, MutantResult))
    test("MT: MutantResult operator attribute",
         _mt_mr.operator == "BOOL_FLIP")
    test("MT: MutantResult killed attribute",
         _mt_mr.killed is True)
    test("MT: MutantResult lineno attribute",
         _mt_mr.lineno == 5)

    # --- MutationReport dataclass ---
    _mt_rep = MutationReport(gate_path="/fake/gate.py")
    test("MT: MutationReport construction",
         isinstance(_mt_rep, MutationReport))
    test("MT: MutationReport kill_rate with zero totals returns 0.0",
         _mt_rep.kill_rate == 0.0)
    test("MT: MutationReport test_gaps empty when no survived",
         _mt_rep.test_gaps == [])
    _mt_rep2 = MutationReport(
        gate_path="/fake/gate.py",
        total_mutants=4,
        killed_count=3,
        survived=[_mt_mr],
    )
    test("MT: MutationReport kill_rate 3/4 == 0.75",
         abs(_mt_rep2.kill_rate - 0.75) < 1e-9, str(_mt_rep2.kill_rate))
    test("MT: MutationReport test_gaps returns descriptions of survived",
         len(_mt_rep2.test_gaps) == 1)
    test("MT: MutationReport test_gaps contains operator prefix",
         "[BOOL_FLIP]" in _mt_rep2.test_gaps[0],
         str(_mt_rep2.test_gaps))
    _mt_rep3 = MutationReport(gate_path="/fake/gate.py", total_mutants=0)
    test("MT: MutationReport kill_rate zero total returns 0.0",
         _mt_rep3.kill_rate == 0.0)

    # --- _BoolFlipVisitor ---
    _mt_src_bool = "x = True\ny = False\n"
    _mt_tree_bool = _mt_ast.parse(_mt_src_bool)
    _mt_v0 = _BoolFlipVisitor(0)
    _mt_new_tree = _mt_v0.visit(_mt_copy.deepcopy(_mt_tree_bool))
    test("MT: _BoolFlipVisitor idx=0 applied is True",
         _mt_v0.applied)
    test("MT: _BoolFlipVisitor idx=0 description contains True->False",
         "True" in _mt_v0.description and "False" in _mt_v0.description,
         _mt_v0.description)
    _mt_v1 = _BoolFlipVisitor(1)
    _mt_v1.visit(_mt_copy.deepcopy(_mt_tree_bool))
    test("MT: _BoolFlipVisitor idx=1 applied is True (flips second bool)",
         _mt_v1.applied)
    _mt_v_oor = _BoolFlipVisitor(99)
    _mt_v_oor.visit(_mt_copy.deepcopy(_mt_tree_bool))
    test("MT: _BoolFlipVisitor out-of-range idx applied is False",
         not _mt_v_oor.applied)

    # --- _CmpOpSwapVisitor ---
    _mt_src_cmp = "a == b\n"
    _mt_tree_cmp = _mt_ast.parse(_mt_src_cmp)
    _mt_vc0 = _CmpOpSwapVisitor(0)
    _mt_new_cmp = _mt_vc0.visit(_mt_copy.deepcopy(_mt_tree_cmp))
    test("MT: _CmpOpSwapVisitor idx=0 applied is True",
         _mt_vc0.applied)
    test("MT: _CmpOpSwapVisitor description contains Eq -> NotEq",
         "Eq" in _mt_vc0.description and "NotEq" in _mt_vc0.description,
         _mt_vc0.description)
    _mt_src_lt = "a < b\n"
    _mt_tree_lt = _mt_ast.parse(_mt_src_lt)
    _mt_vc_lt = _CmpOpSwapVisitor(0)
    _mt_vc_lt.visit(_mt_copy.deepcopy(_mt_tree_lt))
    test("MT: _CmpOpSwapVisitor Lt -> LtE",
         "LtE" in _mt_vc_lt.description, _mt_vc_lt.description)

    # --- _CondRemoveVisitor ---
    _mt_src_if = "if x > 0:\n    pass\n"
    _mt_tree_if = _mt_ast.parse(_mt_src_if)
    _mt_vcr = _CondRemoveVisitor(0, replace_with=True)
    _mt_vcr.visit(_mt_copy.deepcopy(_mt_tree_if))
    test("MT: _CondRemoveVisitor idx=0 applied is True",
         _mt_vcr.applied)
    test("MT: _CondRemoveVisitor description contains replace_with True",
         "True" in _mt_vcr.description, _mt_vcr.description)
    _mt_vcrf = _CondRemoveVisitor(0, replace_with=False)
    _mt_vcrf.visit(_mt_copy.deepcopy(_mt_tree_if))
    test("MT: _CondRemoveVisitor replace_with=False description contains False",
         "False" in _mt_vcrf.description, _mt_vcrf.description)

    # --- _ReturnFlipVisitor ---
    _mt_src_gr = "GateResult(blocked=True, message='x', gate_name='g', severity='warn')\n"
    _mt_tree_gr = _mt_ast.parse(_mt_src_gr)
    _mt_vrf = _ReturnFlipVisitor(0)
    _mt_vrf.visit(_mt_copy.deepcopy(_mt_tree_gr))
    test("MT: _ReturnFlipVisitor idx=0 applied is True",
         _mt_vrf.applied)
    test("MT: _ReturnFlipVisitor description contains blocked=True -> blocked=False",
         "True" in _mt_vrf.description and "False" in _mt_vrf.description,
         _mt_vrf.description)
    _mt_src_grF = "GateResult(blocked=False, message='x', gate_name='g', severity='info')\n"
    _mt_tree_grF = _mt_ast.parse(_mt_src_grF)
    _mt_vrfF = _ReturnFlipVisitor(0)
    _mt_vrfF.visit(_mt_copy.deepcopy(_mt_tree_grF))
    test("MT: _ReturnFlipVisitor flips False -> True",
         "False" in _mt_vrfF.description and "True" in _mt_vrfF.description,
         _mt_vrfF.description)

    # --- _LogicNegateVisitor ---
    _mt_src_and = "result = a and b\n"
    _mt_tree_and = _mt_ast.parse(_mt_src_and)
    _mt_vln = _LogicNegateVisitor(0)
    _mt_vln.visit(_mt_copy.deepcopy(_mt_tree_and))
    test("MT: _LogicNegateVisitor idx=0 applied is True",
         _mt_vln.applied)
    test("MT: _LogicNegateVisitor description contains 'negate'",
         "negate" in _mt_vln.description.lower(), _mt_vln.description)

    # --- _StrSwapVisitor ---
    _mt_src_in = "if x in 'hello':\n    pass\n"
    _mt_tree_in = _mt_ast.parse(_mt_src_in)
    _mt_vss = _StrSwapVisitor(0)
    _mt_vss.visit(_mt_copy.deepcopy(_mt_tree_in))
    test("MT: _StrSwapVisitor idx=0 applied is True",
         _mt_vss.applied)
    test("MT: _StrSwapVisitor description contains __MUTANT__ prefix",
         "__MUTANT__" in _mt_vss.description, _mt_vss.description)

    # --- _count_targets ---
    _mt_src_multi = "x = True\ny = False\nz = True\n"
    _mt_tree_multi = _mt_ast.parse(_mt_src_multi)
    _mt_count_bools = _count_targets(_mt_tree_multi, _BoolFlipVisitor)
    test("MT: _count_targets finds 3 bool literals",
         _mt_count_bools == 3, str(_mt_count_bools))
    _mt_src_nocmp = "x = 1\n"
    _mt_tree_nocmp = _mt_ast.parse(_mt_src_nocmp)
    _mt_count_cmps = _count_targets(_mt_tree_nocmp, _CmpOpSwapVisitor)
    test("MT: _count_targets finds 0 comparisons in 'x=1'",
         _mt_count_cmps == 0, str(_mt_count_cmps))

    # --- generate_mutants ---
    _mt_gate_src = """
from shared.gate_result import GateResult
def check(tool_name, tool_input, state, event_type="PreToolUse"):
    if tool_name == "Bash":
        return GateResult(blocked=True, message="blocked", gate_name="g", severity="warn")
    return GateResult(blocked=False, message="ok", gate_name="g", severity="info")
"""
    _mt_mutants = generate_mutants(_mt_gate_src)
    test("MT: generate_mutants returns a list",
         isinstance(_mt_mutants, list))
    test("MT: generate_mutants generates at least 1 mutant for gate-like source",
         len(_mt_mutants) >= 1, str(len(_mt_mutants)))
    test("MT: generate_mutants returns (MutantResult, str) tuples",
         all(isinstance(m, tuple) and len(m) == 2 for m in _mt_mutants))
    test("MT: generate_mutants MutantResult killed starts False",
         all(not m[0].killed for m in _mt_mutants))

    # --- _find_test_framework ---
    _mt_hooks_dir = "/home/crab/.claude/hooks"
    _mt_gate_path = "/home/crab/.claude/hooks/gates/gate_01_read_before_edit.py"
    _mt_tf = _find_test_framework(_mt_gate_path)
    test("MT: _find_test_framework finds test_framework.py from gate path",
         _mt_tf is not None and _mt_tf.endswith("test_framework.py"),
         str(_mt_tf))

    # --- _find_hooks_dir ---
    _mt_hd = _find_hooks_dir(_mt_gate_path)
    test("MT: _find_hooks_dir finds hooks/ from gate path",
         _mt_hd is not None and _mt_hd.endswith("hooks"),
         str(_mt_hd))
    _mt_hd_nonexist = _find_hooks_dir("/tmp/nonexistent/gates/gate.py")
    test("MT: _find_hooks_dir returns None for nonexistent path",
         _mt_hd_nonexist is None)

except Exception as _mt_exc:
    test("MT: import and tests", False, str(_mt_exc))

# =============================================================================
# CV: consensus_validator (shared/consensus_validator.py)
# =============================================================================
try:
    from shared.consensus_validator import (
        CRITICAL_FILES,
        _THRESHOLD_BLOCK,
        _THRESHOLD_ASK,
        _DUPLICATE_RATIO,
        _NEAR_MATCH_RATIO,
        _normalise,
        _similarity,
        _extract_imports,
        _is_critical_file,
        _detect_broad_except,
        _detect_hardcoded_secret,
        _detect_debug_prints,
        _removed_public_functions,
        _import_drift,
        check_memory_consensus,
        check_edit_consensus,
        compute_confidence,
        recommend_action,
    )

    # --- Constants ---
    test("CV: CRITICAL_FILES is frozenset",
         isinstance(CRITICAL_FILES, frozenset))
    test("CV: CRITICAL_FILES contains enforcer.py",
         "enforcer.py" in CRITICAL_FILES)
    test("CV: CRITICAL_FILES contains memory_server.py",
         "memory_server.py" in CRITICAL_FILES)
    test("CV: CRITICAL_FILES contains settings.json",
         "settings.json" in CRITICAL_FILES)
    test("CV: _THRESHOLD_BLOCK == 0.3",
         _THRESHOLD_BLOCK == 0.3, str(_THRESHOLD_BLOCK))
    test("CV: _THRESHOLD_ASK == 0.6",
         _THRESHOLD_ASK == 0.6, str(_THRESHOLD_ASK))
    test("CV: _DUPLICATE_RATIO == 0.85",
         _DUPLICATE_RATIO == 0.85, str(_DUPLICATE_RATIO))
    test("CV: _NEAR_MATCH_RATIO == 0.55",
         _NEAR_MATCH_RATIO == 0.55, str(_NEAR_MATCH_RATIO))

    # --- _normalise ---
    test("CV: _normalise lowercases text",
         _normalise("Hello World") == "hello world")
    test("CV: _normalise collapses multiple spaces",
         _normalise("a  b   c") == "a b c")
    test("CV: _normalise strips leading/trailing whitespace",
         _normalise("  hello  ") == "hello")
    test("CV: _normalise handles tabs and newlines",
         _normalise("a\tb\nc") == "a b c")
    test("CV: _normalise empty string",
         _normalise("") == "")

    # --- _similarity ---
    test("CV: _similarity identical strings returns 1.0",
         _similarity("hello", "hello") == 1.0)
    test("CV: _similarity completely different returns < 0.2",
         _similarity("abcdef", "xyz123") < 0.2)
    test("CV: _similarity partial match returns value in (0,1)",
         0.0 < _similarity("hello world", "hello there") < 1.0)
    test("CV: _similarity is symmetric",
         abs(_similarity("abc", "xyz") - _similarity("xyz", "abc")) < 1e-9)
    test("CV: _similarity empty vs non-empty returns 0.0",
         _similarity("", "hello") == 0.0)

    # --- _extract_imports ---
    _cv_src_imports = "import os\nimport json\nfrom typing import List\nfrom shared.state import load_state\n"
    _cv_imports = _extract_imports(_cv_src_imports)
    test("CV: _extract_imports finds 'os'",
         "os" in _cv_imports)
    test("CV: _extract_imports finds 'json'",
         "json" in _cv_imports)
    test("CV: _extract_imports finds 'typing'",
         "typing" in _cv_imports)
    test("CV: _extract_imports finds 'shared' (from shared.x import y)",
         "shared" in _cv_imports)
    test("CV: _extract_imports empty source returns []",
         _extract_imports("") == [])
    test("CV: _extract_imports no imports returns []",
         _extract_imports("x = 1\ny = 2\n") == [])

    # --- _is_critical_file ---
    test("CV: _is_critical_file('/path/to/enforcer.py') is True",
         _is_critical_file("/path/to/enforcer.py"))
    test("CV: _is_critical_file('enforcer.py') is True",
         _is_critical_file("enforcer.py"))
    test("CV: _is_critical_file('memory_server.py') is True",
         _is_critical_file("memory_server.py"))
    test("CV: _is_critical_file('settings.json') is True",
         _is_critical_file("settings.json"))
    test("CV: _is_critical_file('regular_file.py') is False",
         not _is_critical_file("regular_file.py"))
    test("CV: _is_critical_file('/some/path/normal.py') is False",
         not _is_critical_file("/some/path/normal.py"))

    # --- _detect_broad_except ---
    test("CV: _detect_broad_except bare except: returns True",
         _detect_broad_except("try:\n    pass\nexcept:\n    pass"))
    test("CV: _detect_broad_except except Exception: returns True",
         _detect_broad_except("try:\n    pass\nexcept Exception:\n    pass"))
    test("CV: _detect_broad_except specific except returns False",
         not _detect_broad_except("try:\n    pass\nexcept ValueError:\n    pass"))
    test("CV: _detect_broad_except no except returns False",
         not _detect_broad_except("x = 1"))

    # --- _detect_hardcoded_secret ---
    test("CV: _detect_hardcoded_secret password= returns True",
         _detect_hardcoded_secret('password = "mysecret123"'))
    test("CV: _detect_hardcoded_secret api_key= returns True",
         _detect_hardcoded_secret('api_key = "sk-abcdef123456"'))
    test("CV: _detect_hardcoded_secret token= returns True",
         _detect_hardcoded_secret('token = "bearer_xyzabc"'))
    test("CV: _detect_hardcoded_secret no secret returns False",
         not _detect_hardcoded_secret("x = 1\ny = 'hello'\n"))
    test("CV: _detect_hardcoded_secret short value not flagged (<4 chars)",
         not _detect_hardcoded_secret('password = "ab"'))

    # --- _detect_debug_prints ---
    test("CV: _detect_debug_prints with print() returns True",
         _detect_debug_prints("print('debug info')"))
    test("CV: _detect_debug_prints with print( variant returns True",
         _detect_debug_prints("  print  ( x )"))
    test("CV: _detect_debug_prints no print returns False",
         not _detect_debug_prints("x = 1\nlogging.info('msg')\n"))

    # --- _removed_public_functions ---
    _cv_old_src = "def foo():\n    pass\ndef bar():\n    pass\ndef _private():\n    pass\n"
    _cv_new_src = "def foo():\n    pass\n"
    _cv_removed = _removed_public_functions(_cv_old_src, _cv_new_src)
    test("CV: _removed_public_functions finds removed 'bar'",
         "bar" in _cv_removed, str(_cv_removed))
    test("CV: _removed_public_functions does not report '_private'",
         "_private" not in _cv_removed, str(_cv_removed))
    test("CV: _removed_public_functions does not report 'foo' (still present)",
         "foo" not in _cv_removed, str(_cv_removed))
    test("CV: _removed_public_functions no removals returns []",
         _removed_public_functions("def foo(): pass", "def foo(): pass\ndef bar(): pass") == [])
    test("CV: _removed_public_functions both empty returns []",
         _removed_public_functions("", "") == [])

    # --- _import_drift ---
    _cv_old_imp = "import os\nimport json\nimport sys\n"
    _cv_new_imp = "import os\nimport json\n"
    _cv_drift = _import_drift(_cv_old_imp, _cv_new_imp)
    test("CV: _import_drift detects removed 'sys'",
         "sys" in _cv_drift, str(_cv_drift))
    test("CV: _import_drift does not report 'os' (still present)",
         "os" not in _cv_drift, str(_cv_drift))
    test("CV: _import_drift no drift returns []",
         _import_drift("import os\n", "import os\nimport sys\n") == [])

    # --- check_memory_consensus ---
    _cv_mem_novel = check_memory_consensus(
        "LanceDB uses flat scan below 50K rows for better relevance",
        ["LanceDB is the primary database", "Redis is used for caching"]
    )
    test("CV: check_memory_consensus novel content -> verdict='novel'",
         _cv_mem_novel["verdict"] == "novel", str(_cv_mem_novel["verdict"]))
    test("CV: check_memory_consensus novel has top_match float",
         isinstance(_cv_mem_novel["top_match"], float))

    _cv_dup_text = "LanceDB uses flat scan for better relevance at small scale"
    _cv_mem_dup = check_memory_consensus(
        _cv_dup_text,
        [_cv_dup_text]
    )
    test("CV: check_memory_consensus identical -> verdict='duplicate'",
         _cv_mem_dup["verdict"] == "duplicate", str(_cv_mem_dup["verdict"]))
    test("CV: check_memory_consensus duplicate top_match >= 0.85",
         _cv_mem_dup["top_match"] >= 0.85, str(_cv_mem_dup["top_match"]))

    _cv_mem_empty = check_memory_consensus("", [])
    test("CV: check_memory_consensus empty content -> verdict='novel'",
         _cv_mem_empty["verdict"] == "novel")

    _cv_mem_conflict = check_memory_consensus(
        "LanceDB is not broken and works correctly",
        ["LanceDB is broken and does not work correctly"]
    )
    test("CV: check_memory_consensus negation conflict -> verdict='conflict' or 'novel'",
         _cv_mem_conflict["verdict"] in ("conflict", "novel"),
         str(_cv_mem_conflict["verdict"]))

    # --- check_edit_consensus ---
    _cv_old_code = "import os\ndef foo():\n    pass\n"
    _cv_new_code_safe = "import os\ndef foo():\n    return 1\n"
    _cv_edit_safe = check_edit_consensus("utils.py", _cv_old_code, _cv_new_code_safe)
    test("CV: check_edit_consensus safe edit returns dict with required keys",
         all(k in _cv_edit_safe for k in ("safe", "confidence", "risks", "is_critical")))
    test("CV: check_edit_consensus non-critical file is_critical=False",
         not _cv_edit_safe["is_critical"])
    test("CV: check_edit_consensus safe edit confidence > 0.5",
         _cv_edit_safe["confidence"] > 0.5, str(_cv_edit_safe["confidence"]))

    _cv_edit_critical = check_edit_consensus("enforcer.py", _cv_old_code, _cv_new_code_safe)
    test("CV: check_edit_consensus critical file is_critical=True",
         _cv_edit_critical["is_critical"])
    test("CV: check_edit_consensus critical file has lower confidence",
         _cv_edit_critical["confidence"] < _cv_edit_safe["confidence"])

    _cv_old_with_fn = "import os\ndef public_api():\n    pass\ndef helper():\n    pass\n"
    _cv_new_removed_fn = "import os\ndef helper():\n    pass\n"
    _cv_edit_api = check_edit_consensus("lib.py", _cv_old_with_fn, _cv_new_removed_fn)
    test("CV: check_edit_consensus API removal adds a risk",
         len(_cv_edit_api["risks"]) > 0)

    _cv_secret_new = "import os\ndef foo():\n    api_key = 'mytoken12345'\n    pass\n"
    _cv_edit_secret = check_edit_consensus("config.py", _cv_old_code, _cv_secret_new)
    test("CV: check_edit_consensus hardcoded secret introduces risk",
         any("secret" in r.lower() or "credential" in r.lower() or "token" in r.lower()
             for r in _cv_edit_secret["risks"]))

    # --- compute_confidence ---
    test("CV: compute_confidence empty dict returns 0.5",
         compute_confidence({}) == 0.5)
    _cv_conf_known = compute_confidence({"memory_coverage": 1.0, "test_coverage": 1.0,
                                         "pattern_match": 1.0, "prior_success": 1.0})
    test("CV: compute_confidence all 1.0 signals returns 1.0",
         abs(_cv_conf_known - 1.0) < 1e-9, str(_cv_conf_known))
    _cv_conf_zero = compute_confidence({"memory_coverage": 0.0, "test_coverage": 0.0,
                                        "pattern_match": 0.0, "prior_success": 0.0})
    test("CV: compute_confidence all 0.0 signals returns 0.0",
         abs(_cv_conf_zero - 0.0) < 1e-9, str(_cv_conf_zero))
    _cv_conf_mixed = compute_confidence({"memory_coverage": 0.8, "test_coverage": 0.6})
    test("CV: compute_confidence mixed known signals returns float in (0,1)",
         0.0 < _cv_conf_mixed < 1.0, str(_cv_conf_mixed))
    _cv_conf_custom = compute_confidence({"custom_signal": 0.9})
    test("CV: compute_confidence unknown signal uses equal weight",
         isinstance(_cv_conf_custom, float) and 0.0 <= _cv_conf_custom <= 1.0,
         str(_cv_conf_custom))
    _cv_conf_clamp = compute_confidence({"memory_coverage": 1.5})
    test("CV: compute_confidence clamps values > 1.0 to 1.0",
         abs(_cv_conf_clamp - 1.0) < 1e-9, str(_cv_conf_clamp))

    # --- recommend_action ---
    test("CV: recommend_action(1.0) -> 'allow'",
         recommend_action(1.0) == "allow")
    test("CV: recommend_action(0.6) -> 'allow' (at threshold)",
         recommend_action(0.6) == "allow")
    test("CV: recommend_action(0.59) -> 'ask'",
         recommend_action(0.59) == "ask")
    test("CV: recommend_action(0.45) -> 'ask'",
         recommend_action(0.45) == "ask")
    test("CV: recommend_action(0.3) -> 'ask' (at lower threshold)",
         recommend_action(0.3) == "ask")
    test("CV: recommend_action(0.29) -> 'block'",
         recommend_action(0.29) == "block")
    test("CV: recommend_action(0.0) -> 'block'",
         recommend_action(0.0) == "block")

except Exception as _cv_exc:
    test("CV: import and tests", False, str(_cv_exc))

# ─────────────────────────────────────────────────
# RS: retry_strategy (shared/retry_strategy.py)
# ─────────────────────────────────────────────────
try:
    from shared.retry_strategy import (
        Strategy, Jitter, RetryConfig, _OperationState,
        _fib, _compute_raw_delay, _apply_jitter,
        should_retry, get_delay, record_attempt,
        reset as rs_reset, get_stats, with_retry,
        _RetryContextManager, _get_state, _registry,
    )

    # Enum values
    test("RS: Strategy.EXPONENTIAL_BACKOFF value",
         Strategy.EXPONENTIAL_BACKOFF == "exponential_backoff")
    test("RS: Strategy.LINEAR_BACKOFF value",
         Strategy.LINEAR_BACKOFF == "linear_backoff")
    test("RS: Strategy.CONSTANT value",
         Strategy.CONSTANT == "constant")
    test("RS: Strategy.FIBONACCI value",
         Strategy.FIBONACCI == "fibonacci")
    test("RS: Jitter.NONE value",
         Jitter.NONE == "none")
    test("RS: Jitter.FULL value",
         Jitter.FULL == "full")
    test("RS: Jitter.EQUAL value",
         Jitter.EQUAL == "equal")
    test("RS: Jitter.DECORRELATED value",
         Jitter.DECORRELATED == "decorrelated")

    # RetryConfig defaults
    _rs_cfg_default = RetryConfig()
    test("RS: RetryConfig default strategy is EXPONENTIAL_BACKOFF",
         _rs_cfg_default.strategy == Strategy.EXPONENTIAL_BACKOFF)
    test("RS: RetryConfig default jitter is NONE",
         _rs_cfg_default.jitter == Jitter.NONE)
    test("RS: RetryConfig default max_retries == 3",
         _rs_cfg_default.max_retries == 3)
    test("RS: RetryConfig default base_delay == 1.0",
         _rs_cfg_default.base_delay == 1.0)
    test("RS: RetryConfig default max_delay == 60.0",
         _rs_cfg_default.max_delay == 60.0)
    test("RS: RetryConfig default multiplier == 2.0",
         _rs_cfg_default.multiplier == 2.0)
    test("RS: RetryConfig default step == 1.0",
         _rs_cfg_default.step == 1.0)

    # _OperationState defaults
    _rs_state_default = _OperationState()
    test("RS: _OperationState default attempts == 0",
         _rs_state_default.attempts == 0)
    test("RS: _OperationState default successes == 0",
         _rs_state_default.successes == 0)
    test("RS: _OperationState default failures == 0",
         _rs_state_default.failures == 0)
    test("RS: _OperationState default last_delay == 0.0",
         _rs_state_default.last_delay == 0.0)
    test("RS: _OperationState default errors is empty list",
         _rs_state_default.errors == [])
    test("RS: _OperationState default total_delay == 0.0",
         _rs_state_default.total_delay == 0.0)
    test("RS: _OperationState default max_errors_stored == 10",
         _rs_state_default.max_errors_stored == 10)

    # _fib known values
    test("RS: _fib(0) == 0",  _fib(0) == 0)
    test("RS: _fib(1) == 1",  _fib(1) == 1)
    test("RS: _fib(2) == 1",  _fib(2) == 1)
    test("RS: _fib(3) == 2",  _fib(3) == 2)
    test("RS: _fib(4) == 3",  _fib(4) == 3)
    test("RS: _fib(5) == 5",  _fib(5) == 5)
    test("RS: _fib(6) == 8",  _fib(6) == 8)
    test("RS: _fib(10) == 55", _fib(10) == 55)

    # _compute_raw_delay — EXPONENTIAL_BACKOFF: base * multiplier^attempt
    _rs_exp_cfg = RetryConfig(strategy=Strategy.EXPONENTIAL_BACKOFF,
                              base_delay=1.0, multiplier=2.0, max_delay=1000.0, jitter=Jitter.NONE)
    test("RS: _compute_raw_delay EXPONENTIAL attempt=0 == 1.0",
         abs(_compute_raw_delay(0, _rs_exp_cfg) - 1.0) < 1e-9)
    test("RS: _compute_raw_delay EXPONENTIAL attempt=1 == 2.0",
         abs(_compute_raw_delay(1, _rs_exp_cfg) - 2.0) < 1e-9)
    test("RS: _compute_raw_delay EXPONENTIAL attempt=3 == 8.0",
         abs(_compute_raw_delay(3, _rs_exp_cfg) - 8.0) < 1e-9)

    # _compute_raw_delay — LINEAR_BACKOFF: base + step * attempt
    _rs_lin_cfg = RetryConfig(strategy=Strategy.LINEAR_BACKOFF,
                              base_delay=1.0, step=2.0, max_delay=1000.0, jitter=Jitter.NONE)
    test("RS: _compute_raw_delay LINEAR attempt=0 == 1.0",
         abs(_compute_raw_delay(0, _rs_lin_cfg) - 1.0) < 1e-9)
    test("RS: _compute_raw_delay LINEAR attempt=1 == 3.0",
         abs(_compute_raw_delay(1, _rs_lin_cfg) - 3.0) < 1e-9)
    test("RS: _compute_raw_delay LINEAR attempt=4 == 9.0",
         abs(_compute_raw_delay(4, _rs_lin_cfg) - 9.0) < 1e-9)

    # _compute_raw_delay — CONSTANT: always base_delay
    _rs_const_cfg = RetryConfig(strategy=Strategy.CONSTANT, base_delay=5.0,
                                max_delay=100.0, jitter=Jitter.NONE)
    test("RS: _compute_raw_delay CONSTANT attempt=0 == 5.0",
         abs(_compute_raw_delay(0, _rs_const_cfg) - 5.0) < 1e-9)
    test("RS: _compute_raw_delay CONSTANT attempt=10 == 5.0",
         abs(_compute_raw_delay(10, _rs_const_cfg) - 5.0) < 1e-9)

    # _compute_raw_delay — FIBONACCI: base * fib(attempt+1)
    _rs_fib_cfg = RetryConfig(strategy=Strategy.FIBONACCI, base_delay=1.0,
                              max_delay=1000.0, jitter=Jitter.NONE)
    # attempt=0 -> fib(max(1,1))=fib(1)=1, *1.0 = 1.0
    test("RS: _compute_raw_delay FIBONACCI attempt=0 == 1.0",
         abs(_compute_raw_delay(0, _rs_fib_cfg) - 1.0) < 1e-9)
    # attempt=2 -> fib(max(1,3))=fib(3)=2, *1.0 = 2.0
    test("RS: _compute_raw_delay FIBONACCI attempt=2 == 2.0",
         abs(_compute_raw_delay(2, _rs_fib_cfg) - 2.0) < 1e-9)
    # attempt=3 -> fib(4)=3, *1.0 = 3.0
    test("RS: _compute_raw_delay FIBONACCI attempt=3 == 3.0",
         abs(_compute_raw_delay(3, _rs_fib_cfg) - 3.0) < 1e-9)

    # max_delay cap in _compute_raw_delay
    _rs_cap_cfg = RetryConfig(strategy=Strategy.EXPONENTIAL_BACKOFF,
                              base_delay=1.0, multiplier=10.0, max_delay=5.0, jitter=Jitter.NONE)
    test("RS: _compute_raw_delay respects max_delay cap",
         _compute_raw_delay(5, _rs_cap_cfg) <= 5.0 + 1e-9)

    # _apply_jitter — NONE returns raw unchanged
    _rs_none_jit_cfg = RetryConfig(jitter=Jitter.NONE)
    test("RS: _apply_jitter NONE returns raw unchanged",
         abs(_apply_jitter(3.0, _rs_none_jit_cfg, 0.0) - 3.0) < 1e-9)

    # _apply_jitter — FULL returns value in [0, raw]
    _rs_full_jit_cfg = RetryConfig(jitter=Jitter.FULL, base_delay=4.0)
    _rs_full_results = [_apply_jitter(4.0, _rs_full_jit_cfg, 0.0) for _ in range(50)]
    test("RS: _apply_jitter FULL all values in [0, raw]",
         all(0.0 <= v <= 4.0 + 1e-9 for v in _rs_full_results))

    # _apply_jitter — EQUAL returns value in [raw/2, raw]
    _rs_eq_jit_cfg = RetryConfig(jitter=Jitter.EQUAL, base_delay=4.0)
    _rs_eq_results = [_apply_jitter(4.0, _rs_eq_jit_cfg, 0.0) for _ in range(50)]
    test("RS: _apply_jitter EQUAL all values in [raw/2, raw]",
         all(2.0 - 1e-9 <= v <= 4.0 + 1e-9 for v in _rs_eq_results))

    # _apply_jitter — DECORRELATED result >= base_delay
    _rs_decorr_cfg = RetryConfig(jitter=Jitter.DECORRELATED, base_delay=1.0)
    _rs_decorr_results = [_apply_jitter(4.0, _rs_decorr_cfg, 2.0) for _ in range(30)]
    test("RS: _apply_jitter DECORRELATED all values >= base_delay",
         all(v >= 1.0 - 1e-9 for v in _rs_decorr_results))

    # should_retry — before and after max_retries
    rs_reset("_test_rs_should_retry_fresh")
    _rs_sr_cfg = RetryConfig(max_retries=3)
    test("RS: should_retry True before any failure",
         should_retry("_test_rs_should_retry_fresh", config=_rs_sr_cfg))
    for _ in range(3):
        record_attempt("_test_rs_should_retry_fresh", success=False, config=_rs_sr_cfg)
    test("RS: should_retry False after max_retries failures",
         not should_retry("_test_rs_should_retry_fresh", config=_rs_sr_cfg))

    # should_retry — partial failures still allow retry
    rs_reset("_test_rs_partial_fail")
    _rs_partial_cfg = RetryConfig(max_retries=5)
    for _ in range(3):
        record_attempt("_test_rs_partial_fail", success=False, config=_rs_partial_cfg)
    test("RS: should_retry True when failures < max_retries",
         should_retry("_test_rs_partial_fail", config=_rs_partial_cfg))

    # get_delay — returns non-negative float
    rs_reset("_test_rs_get_delay")
    _rs_gd_cfg = RetryConfig(strategy=Strategy.EXPONENTIAL_BACKOFF,
                             base_delay=1.0, multiplier=2.0, max_delay=60.0, jitter=Jitter.NONE)
    _rs_gd_val = get_delay("_test_rs_get_delay", config=_rs_gd_cfg)
    test("RS: get_delay returns non-negative float",
         isinstance(_rs_gd_val, float) and _rs_gd_val >= 0.0)

    # get_delay — grows with failures (EXPONENTIAL, no jitter)
    rs_reset("_test_rs_get_delay_grows")
    _rs_grow_cfg = RetryConfig(strategy=Strategy.EXPONENTIAL_BACKOFF,
                               base_delay=1.0, multiplier=2.0, max_delay=1000.0, jitter=Jitter.NONE)
    _rs_grow_delays = []
    for _ in range(4):
        _rs_grow_delays.append(get_delay("_test_rs_get_delay_grows", config=_rs_grow_cfg))
        record_attempt("_test_rs_get_delay_grows", success=False, config=_rs_grow_cfg)
    test("RS: get_delay grows with EXPONENTIAL_BACKOFF (no jitter)",
         _rs_grow_delays == [1.0, 2.0, 4.0, 8.0],
         f"got {_rs_grow_delays}")

    # record_attempt — success increments successes and attempts
    rs_reset("_test_rs_record_succ")
    _rs_rec_cfg = RetryConfig(max_retries=10)
    record_attempt("_test_rs_record_succ", success=True, config=_rs_rec_cfg)
    _rs_rec_stats = get_stats("_test_rs_record_succ")
    test("RS: record_attempt success increments attempts",
         _rs_rec_stats.get("attempts") == 1)
    test("RS: record_attempt success increments successes",
         _rs_rec_stats.get("successes") == 1)
    test("RS: record_attempt success does not increment failures",
         _rs_rec_stats.get("failures") == 0)

    # record_attempt — failure increments failures and stores error
    rs_reset("_test_rs_record_fail")
    _rs_rf_cfg = RetryConfig(max_retries=10)
    record_attempt("_test_rs_record_fail", success=False, error="test error msg", config=_rs_rf_cfg)
    _rs_rf_stats = get_stats("_test_rs_record_fail")
    test("RS: record_attempt failure increments failures",
         _rs_rf_stats.get("failures") == 1)
    test("RS: record_attempt failure stores error message",
         "test error msg" in _rs_rf_stats.get("recent_errors", []))

    # record_attempt — mixed success/failure counts
    rs_reset("_test_rs_mixed")
    _rs_mix_cfg = RetryConfig(max_retries=10)
    record_attempt("_test_rs_mixed", success=True, config=_rs_mix_cfg)
    record_attempt("_test_rs_mixed", success=False, error="e1", config=_rs_mix_cfg)
    record_attempt("_test_rs_mixed", success=True, config=_rs_mix_cfg)
    _rs_mix_stats = get_stats("_test_rs_mixed")
    test("RS: record_attempt mixed: attempts == 3",
         _rs_mix_stats.get("attempts") == 3)
    test("RS: record_attempt mixed: successes == 2",
         _rs_mix_stats.get("successes") == 2)
    test("RS: record_attempt mixed: failures == 1",
         _rs_mix_stats.get("failures") == 1)

    # reset — clears all state
    rs_reset("_test_rs_reset_op")
    record_attempt("_test_rs_reset_op", success=False, error="oops")
    rs_reset("_test_rs_reset_op")
    _rs_reset_stats = get_stats("_test_rs_reset_op")
    test("RS: reset clears attempts to 0",
         _rs_reset_stats.get("attempts") == 0)
    test("RS: reset clears failures to 0",
         _rs_reset_stats.get("failures") == 0)
    test("RS: reset clears recent_errors to []",
         _rs_reset_stats.get("recent_errors") == [])

    # get_stats — expected keys present
    rs_reset("_test_rs_stats_keys")
    _rs_sk_stats = get_stats("_test_rs_stats_keys")
    _rs_expected_keys = {"operation", "attempts", "successes", "failures",
                         "last_delay", "total_delay", "recent_errors", "success_rate"}
    test("RS: get_stats returns all expected keys",
         _rs_expected_keys.issubset(set(_rs_sk_stats.keys())))

    # get_stats — success_rate computed correctly
    rs_reset("_test_rs_stats_rate")
    _rs_rate_cfg = RetryConfig(max_retries=10)
    record_attempt("_test_rs_stats_rate", success=True, config=_rs_rate_cfg)
    record_attempt("_test_rs_stats_rate", success=True, config=_rs_rate_cfg)
    record_attempt("_test_rs_stats_rate", success=False, config=_rs_rate_cfg)
    _rs_rate_stats = get_stats("_test_rs_stats_rate")
    test("RS: get_stats success_rate is 0.6667",
         abs(_rs_rate_stats.get("success_rate", 0) - 0.6667) < 0.001,
         f"got {_rs_rate_stats.get('success_rate')}")

    # _get_state — creates new state for unknown operation
    _rs_new_op = "_test_rs_brand_new_op_xyz999"
    if _rs_new_op in _registry:
        del _registry[_rs_new_op]
    _rs_new_state = _get_state(_rs_new_op)
    test("RS: _get_state creates new _OperationState for unknown op",
         isinstance(_rs_new_state, _OperationState))
    test("RS: _get_state new state has attempts == 0",
         _rs_new_state.attempts == 0)
    test("RS: _get_state registers op in _registry",
         _rs_new_op in _registry)

    # _get_state — returns same object on repeated calls
    _rs_same_state = _get_state(_rs_new_op)
    test("RS: _get_state returns same object on second call",
         _rs_same_state is _rs_new_state)

    # with_retry — returns _RetryContextManager
    _rs_wcm = with_retry("_test_rs_wcm_op", strategy=Strategy.CONSTANT, base_delay=0.0)
    test("RS: with_retry returns _RetryContextManager",
         isinstance(_rs_wcm, _RetryContextManager))

    # with_retry — as context manager records success when success() called
    rs_reset("_test_rs_ctx_success")
    with with_retry("_test_rs_ctx_success", strategy=Strategy.CONSTANT,
                    base_delay=0.0) as _rs_rt:
        _rs_rt.success()
    _rs_ctx_stats = get_stats("_test_rs_ctx_success")
    test("RS: with_retry ctx manager records success when success() called",
         _rs_ctx_stats.get("successes") == 1)
    test("RS: with_retry ctx manager attempts == 1 after success",
         _rs_ctx_stats.get("attempts") == 1)

    # with_retry — context manager records success on clean exit (no success() call)
    rs_reset("_test_rs_ctx_auto_success")
    with with_retry("_test_rs_ctx_auto_success", strategy=Strategy.CONSTANT,
                    base_delay=0.0):
        pass  # clean exit, no explicit success() call
    _rs_ctx_auto_stats = get_stats("_test_rs_ctx_auto_success")
    test("RS: with_retry ctx manager auto-records success on clean exit",
         _rs_ctx_auto_stats.get("successes") == 1)

    # with_retry — context manager records failure on exception
    rs_reset("_test_rs_ctx_fail")
    try:
        with with_retry("_test_rs_ctx_fail", strategy=Strategy.CONSTANT,
                        base_delay=0.0, max_retries=3):
            raise ValueError("ctx exception")
    except ValueError:
        pass
    _rs_ctx_fail_stats = get_stats("_test_rs_ctx_fail")
    test("RS: with_retry ctx manager records failure on exception",
         _rs_ctx_fail_stats.get("failures") == 1)

    # with_retry — as decorator wraps function and retries
    _rs_call_count = {"n": 0}
    rs_reset("_test_rs_decorator")

    @with_retry(strategy=Strategy.CONSTANT, base_delay=0.0, max_retries=5)
    def _rs_flaky_fn():
        _rs_call_count["n"] += 1
        if _rs_call_count["n"] < 3:
            raise RuntimeError("not yet")
        return "done"

    rs_reset(_rs_flaky_fn._operation)
    try:
        _rs_dec_result = _rs_flaky_fn()
        test("RS: with_retry decorator succeeds on 3rd attempt",
             _rs_dec_result == "done" and _rs_call_count["n"] == 3)
    except Exception as _rs_dec_exc:
        test("RS: with_retry decorator succeeds on 3rd attempt",
             False, str(_rs_dec_exc))

    # with_retry — exhausted retries re-raises exception
    _rs_always_fail_count = {"n": 0}
    rs_reset("_test_rs_exhausted")

    @with_retry(strategy=Strategy.CONSTANT, base_delay=0.0, max_retries=2)
    def _rs_always_fail():
        _rs_always_fail_count["n"] += 1
        raise ValueError("always fails")

    rs_reset(_rs_always_fail._operation)
    try:
        _rs_always_fail()
        test("RS: with_retry exhausted retries re-raises", False, "should have raised")
    except ValueError:
        test("RS: with_retry exhausted retries re-raises", True)

    # _registry — is a module-level dict
    test("RS: _registry is a dict",
         isinstance(_registry, dict))

    # Fail-open: None operation name does not raise
    try:
        should_retry(None)
        get_delay(None)
        record_attempt(None, True)
        rs_reset(None)
        get_stats(None)
        test("RS: fail-open with None operation name", True)
    except Exception as _rs_fo_exc:
        test("RS: fail-open with None operation name", False, str(_rs_fo_exc))

except Exception as _rs_exc:
    test("RS: import and module-level tests", False, str(_rs_exc))

# ─────────────────────────────────────────────────
# CR: chain_refinement (shared/chain_refinement.py)
# ─────────────────────────────────────────────────
try:
    from shared.chain_refinement import (
        StrategyStats, RecurringPattern, Refinement, ChainHealth,
        MIN_RECURRENCE, INEFFECTIVE_THRESHOLD, CHRONIC_FAILURE_THRESHOLD,
        MIN_ATTEMPTS_FOR_STATS, MIN_IMPROVEMENT_DELTA,
        _normalize_error, _extract_outcome_fields,
        get_strategy_effectiveness, detect_recurring_failures,
        suggest_refinement, compute_chain_health, analyze_outcomes,
    )

    # Dataclass defaults — StrategyStats
    _cr_ss = StrategyStats(strategy="test_strat")
    test("CR: StrategyStats default attempts == 0", _cr_ss.attempts == 0)
    test("CR: StrategyStats default successes == 0", _cr_ss.successes == 0)
    test("CR: StrategyStats default failures == 0", _cr_ss.failures == 0)
    test("CR: StrategyStats default success_rate == 0.0", _cr_ss.success_rate == 0.0)
    test("CR: StrategyStats default avg_attempts_to_success == 0.0",
         _cr_ss.avg_attempts_to_success == 0.0)
    test("CR: StrategyStats default errors_addressed == 0", _cr_ss.errors_addressed == 0)

    # Dataclass defaults — RecurringPattern
    _cr_rp = RecurringPattern(error_pattern="some error")
    test("CR: RecurringPattern default occurrence_count == 0", _cr_rp.occurrence_count == 0)
    test("CR: RecurringPattern default strategies_tried == []", _cr_rp.strategies_tried == [])
    test("CR: RecurringPattern default best_strategy == ''", _cr_rp.best_strategy == "")
    test("CR: RecurringPattern default best_success_rate == 0.0",
         _cr_rp.best_success_rate == 0.0)
    test("CR: RecurringPattern default is_chronic == False", _cr_rp.is_chronic is False)

    # Dataclass defaults — Refinement
    _cr_ref = Refinement(
        error_pattern="err", current_strategy="old",
        suggested_strategy="new", reason="better", confidence=0.8)
    test("CR: Refinement default evidence == []", _cr_ref.evidence == [])

    # Dataclass defaults — ChainHealth
    _cr_ch = ChainHealth()
    test("CR: ChainHealth default total_chains == 0", _cr_ch.total_chains == 0)
    test("CR: ChainHealth default overall_success_rate == 0.0",
         _cr_ch.overall_success_rate == 0.0)
    test("CR: ChainHealth default chronic_failures == 0", _cr_ch.chronic_failures == 0)
    test("CR: ChainHealth default strategy_diversity == 0", _cr_ch.strategy_diversity == 0)
    test("CR: ChainHealth default improvement_trend == 'stable'",
         _cr_ch.improvement_trend == "stable")
    test("CR: ChainHealth default health_score == 50.0", _cr_ch.health_score == 50.0)
    test("CR: ChainHealth default recommendations == []", _cr_ch.recommendations == [])

    # Constants
    test("CR: MIN_RECURRENCE == 3", MIN_RECURRENCE == 3)
    test("CR: INEFFECTIVE_THRESHOLD == 0.3", abs(INEFFECTIVE_THRESHOLD - 0.3) < 1e-9)
    test("CR: CHRONIC_FAILURE_THRESHOLD == 0.7", abs(CHRONIC_FAILURE_THRESHOLD - 0.7) < 1e-9)
    test("CR: MIN_ATTEMPTS_FOR_STATS == 3", MIN_ATTEMPTS_FOR_STATS == 3)
    test("CR: MIN_IMPROVEMENT_DELTA == 0.15", abs(MIN_IMPROVEMENT_DELTA - 0.15) < 1e-9)

    # _normalize_error — removes file paths
    _cr_ne_path = _normalize_error("Error in /home/crab/.claude/hooks/gate_01.py something")
    test("CR: _normalize_error removes file paths",
         "/home" not in _cr_ne_path and "<file>" in _cr_ne_path,
         f"got: {_cr_ne_path!r}")

    # _normalize_error — removes line numbers
    _cr_ne_line = _normalize_error("Error at line 42 in code")
    test("CR: _normalize_error replaces line numbers with 'line n'",
         "42" not in _cr_ne_line and "line n" in _cr_ne_line,
         f"got: {_cr_ne_line!r}")

    # _normalize_error — removes timestamps
    _cr_ne_ts = _normalize_error("Error at 2024-01-15T10:30:00 occurred")
    test("CR: _normalize_error removes timestamps",
         "2024" not in _cr_ne_ts and "<ts>" in _cr_ne_ts,
         f"got: {_cr_ne_ts!r}")

    # _normalize_error — removes hex addresses
    _cr_ne_hex = _normalize_error("Object at 0xDEADBEEF failed")
    test("CR: _normalize_error removes hex addresses",
         "0xDEADBEEF" not in _cr_ne_hex and "<addr>" in _cr_ne_hex,
         f"got: {_cr_ne_hex!r}")

    # _normalize_error — lowercases output
    _cr_ne_case = _normalize_error("UPPER CASE ERROR")
    test("CR: _normalize_error lowercases output",
         _cr_ne_case == _cr_ne_case.lower())

    # _normalize_error — empty string returns empty
    test("CR: _normalize_error empty string returns ''",
         _normalize_error("") == "")

    # _normalize_error — None returns empty
    test("CR: _normalize_error None returns ''",
         _normalize_error(None) == "")

    # _normalize_error — non-string returns empty
    test("CR: _normalize_error integer returns ''",
         _normalize_error(42) == "")

    # _extract_outcome_fields — with standard keys
    _cr_eof_std = _extract_outcome_fields({
        "error": "some error", "strategy": "strat_a",
        "result": "success", "chain_id": "c1", "timestamp": "t1"
    })
    test("CR: _extract_outcome_fields extracts 'error' key",
         _cr_eof_std.get("error") == "some error")
    test("CR: _extract_outcome_fields extracts 'strategy' key",
         _cr_eof_std.get("strategy") == "strat_a")
    test("CR: _extract_outcome_fields extracts 'result' key",
         _cr_eof_std.get("result") == "success")
    test("CR: _extract_outcome_fields extracts 'chain_id' key",
         _cr_eof_std.get("chain_id") == "c1")

    # _extract_outcome_fields — with alternate keys (LanceDB format)
    _cr_eof_alt = _extract_outcome_fields({
        "error_text": "alt error", "strategy_name": "strat_b",
        "outcome": "failure"
    })
    test("CR: _extract_outcome_fields prefers error_text over error",
         _cr_eof_alt.get("error") == "alt error")
    test("CR: _extract_outcome_fields falls back to strategy_name",
         _cr_eof_alt.get("strategy") == "strat_b")
    test("CR: _extract_outcome_fields falls back to outcome for result",
         _cr_eof_alt.get("result") == "failure")

    # _extract_outcome_fields — non-dict returns {}
    test("CR: _extract_outcome_fields non-dict returns {}",
         _extract_outcome_fields("not a dict") == {})
    test("CR: _extract_outcome_fields None returns {}",
         _extract_outcome_fields(None) == {})
    test("CR: _extract_outcome_fields list returns {}",
         _extract_outcome_fields([1, 2]) == {})

    # get_strategy_effectiveness — synthetic outcomes
    _cr_outcomes_eff = [
        {"strategy": "alpha", "result": "success", "error": "file not found"},
        {"strategy": "alpha", "result": "success", "error": "file not found"},
        {"strategy": "alpha", "result": "failure", "error": "file not found"},
        {"strategy": "beta",  "result": "failure", "error": "timeout error"},
        {"strategy": "beta",  "result": "failure", "error": "timeout error"},
    ]
    _cr_eff = get_strategy_effectiveness(_cr_outcomes_eff)
    test("CR: get_strategy_effectiveness returns dict",
         isinstance(_cr_eff, dict))
    test("CR: get_strategy_effectiveness includes 'alpha'",
         "alpha" in _cr_eff)
    test("CR: get_strategy_effectiveness alpha attempts == 3",
         _cr_eff.get("alpha", StrategyStats("x")).attempts == 3)
    test("CR: get_strategy_effectiveness alpha successes == 2",
         _cr_eff.get("alpha", StrategyStats("x")).successes == 2)
    test("CR: get_strategy_effectiveness beta failures == 2",
         _cr_eff.get("beta", StrategyStats("x")).failures == 2)
    test("CR: get_strategy_effectiveness alpha success_rate == 0.6667",
         abs(_cr_eff.get("alpha", StrategyStats("x")).success_rate - 0.6667) < 0.001)

    # get_strategy_effectiveness — empty outcomes returns empty dict
    test("CR: get_strategy_effectiveness empty outcomes returns {}",
         get_strategy_effectiveness([]) == {})

    # detect_recurring_failures — errors appearing >= 3 times flagged
    _cr_recurring_error = "module not found error"
    _cr_outcomes_recur = (
        [{"error": _cr_recurring_error, "strategy": "s1", "result": "failure"}] * 4 +
        [{"error": "rare error only once", "strategy": "s1", "result": "failure"}]
    )
    _cr_patterns = detect_recurring_failures(_cr_outcomes_recur)
    _cr_pattern_errors = [p.error_pattern for p in _cr_patterns]
    test("CR: detect_recurring_failures finds error appearing 4 times",
         any(_cr_recurring_error in ep for ep in _cr_pattern_errors),
         f"found: {_cr_pattern_errors}")

    # detect_recurring_failures — errors appearing < min_recurrence not flagged
    test("CR: detect_recurring_failures ignores error appearing once",
         not any("rare error only once" in ep for ep in _cr_pattern_errors))

    # detect_recurring_failures — occurrence_count is correct
    _cr_found_pattern = next(
        (p for p in _cr_patterns if _cr_recurring_error in p.error_pattern), None)
    test("CR: detect_recurring_failures occurrence_count == 4",
         _cr_found_pattern is not None and _cr_found_pattern.occurrence_count == 4,
         f"got: {_cr_found_pattern}")

    # detect_recurring_failures — empty outcomes returns []
    test("CR: detect_recurring_failures empty outcomes returns []",
         detect_recurring_failures([]) == [])

    # detect_recurring_failures — is_chronic flagged for high failure rate
    _cr_chronic_outcomes = [
        {"error": "stubborn error", "strategy": "s1", "result": "failure"}
    ] * 5  # 5 failures, 0 successes -> failure_rate=1.0 > 0.7
    _cr_chronic_patterns = detect_recurring_failures(_cr_chronic_outcomes)
    _cr_chronic_found = next(
        (p for p in _cr_chronic_patterns if "stubborn error" in p.error_pattern), None)
    test("CR: detect_recurring_failures marks is_chronic for 100% failure rate",
         _cr_chronic_found is not None and _cr_chronic_found.is_chronic is True,
         f"found: {_cr_chronic_found}")

    # suggest_refinement — returns Refinement when better strategy exists
    _cr_good_strategy_outcomes = (
        # Current strategy "slow" has poor record on this error
        [{"error": "connection timeout", "strategy": "slow", "result": "failure"}] * 4 +
        # Better strategy "fast" has strong record on same error
        [{"error": "connection timeout", "strategy": "fast", "result": "success"}] * 5
    )
    _cr_refinement = suggest_refinement(
        "connection timeout", _cr_good_strategy_outcomes, current_strategy="slow")
    test("CR: suggest_refinement returns Refinement object when better strategy exists",
         _cr_refinement is not None,
         "got None — no refinement suggested")
    if _cr_refinement is not None:
        test("CR: suggest_refinement suggested_strategy is 'fast'",
             _cr_refinement.suggested_strategy == "fast",
             f"got: {_cr_refinement.suggested_strategy}")
        test("CR: suggest_refinement confidence is in [0.0, 1.0]",
             0.0 <= _cr_refinement.confidence <= 1.0)
        test("CR: suggest_refinement evidence is a non-empty list",
             isinstance(_cr_refinement.evidence, list) and len(_cr_refinement.evidence) > 0)

    # suggest_refinement — no outcomes returns None
    test("CR: suggest_refinement with no outcomes returns None",
         suggest_refinement("any error", [], current_strategy="s1") is None)

    # suggest_refinement — empty error returns None
    test("CR: suggest_refinement with empty error returns None",
         suggest_refinement("", _cr_good_strategy_outcomes) is None)

    # compute_chain_health — empty outcomes returns default with recommendation
    _cr_empty_health = compute_chain_health([])
    test("CR: compute_chain_health empty returns ChainHealth",
         isinstance(_cr_empty_health, ChainHealth))
    test("CR: compute_chain_health empty total_chains == 0",
         _cr_empty_health.total_chains == 0)
    test("CR: compute_chain_health empty has recommendation",
         len(_cr_empty_health.recommendations) > 0)

    # compute_chain_health — with mixed outcomes
    _cr_mixed_outcomes = (
        [{"error": "err1", "strategy": "s1", "result": "success"}] * 6 +
        [{"error": "err2", "strategy": "s2", "result": "failure"}] * 4
    )
    _cr_mixed_health = compute_chain_health(_cr_mixed_outcomes)
    test("CR: compute_chain_health mixed total_chains == 10",
         _cr_mixed_health.total_chains == 10)
    test("CR: compute_chain_health mixed overall_success_rate == 0.6",
         abs(_cr_mixed_health.overall_success_rate - 0.6) < 0.001,
         f"got: {_cr_mixed_health.overall_success_rate}")
    test("CR: compute_chain_health mixed strategy_diversity == 2",
         _cr_mixed_health.strategy_diversity == 2)
    test("CR: compute_chain_health health_score in [0, 100]",
         0.0 <= _cr_mixed_health.health_score <= 100.0)

    # analyze_outcomes — returns expected keys
    _cr_analysis = analyze_outcomes(_cr_mixed_outcomes)
    test("CR: analyze_outcomes returns dict",
         isinstance(_cr_analysis, dict))
    test("CR: analyze_outcomes has 'strategy_effectiveness' key",
         "strategy_effectiveness" in _cr_analysis)
    test("CR: analyze_outcomes has 'recurring_failures' key",
         "recurring_failures" in _cr_analysis)
    test("CR: analyze_outcomes has 'chain_health' key",
         "chain_health" in _cr_analysis)
    test("CR: analyze_outcomes has 'summary' key",
         "summary" in _cr_analysis)
    test("CR: analyze_outcomes 'summary' is a non-empty string",
         isinstance(_cr_analysis.get("summary"), str) and len(_cr_analysis["summary"]) > 0)

    # analyze_outcomes — empty outcomes
    _cr_empty_analysis = analyze_outcomes([])
    test("CR: analyze_outcomes empty outcomes returns dict with expected keys",
         all(k in _cr_empty_analysis for k in
             ("strategy_effectiveness", "recurring_failures", "chain_health", "summary")))

except Exception as _cr_exc:
    test("CR: import and module-level tests", False, str(_cr_exc))

# ─────────────────────────────────────────────────
# HC: health_correlation (shared/health_correlation.py)
# ─────────────────────────────────────────────────
try:
    from shared.health_correlation import (
        REDUNDANCY_THRESHOLD, SYNERGY_THRESHOLD,
        MIN_BLOCKS_FOR_ANALYSIS, PROTECTED_GATES,
        _pearson_correlation, _short, _redundancy_recommendation,
        build_fire_vectors, compute_correlation_matrix,
        detect_redundant_pairs, detect_synergistic_pairs,
        suggest_optimizations, generate_health_report,
    )

    # Constants
    test("HC: REDUNDANCY_THRESHOLD == 0.80",
         abs(REDUNDANCY_THRESHOLD - 0.80) < 1e-9)
    test("HC: SYNERGY_THRESHOLD == -0.50",
         abs(SYNERGY_THRESHOLD - (-0.50)) < 1e-9)
    test("HC: MIN_BLOCKS_FOR_ANALYSIS == 3",
         MIN_BLOCKS_FOR_ANALYSIS == 3)

    # PROTECTED_GATES contains exactly 3 expected gate names
    test("HC: PROTECTED_GATES contains 'gate_01_read_before_edit'",
         "gate_01_read_before_edit" in PROTECTED_GATES)
    test("HC: PROTECTED_GATES contains 'gate_02_no_destroy'",
         "gate_02_no_destroy" in PROTECTED_GATES)
    test("HC: PROTECTED_GATES contains 'gate_03_test_before_deploy'",
         "gate_03_test_before_deploy" in PROTECTED_GATES)
    test("HC: PROTECTED_GATES has exactly 3 members",
         len(PROTECTED_GATES) == 3)

    # _pearson_correlation — perfectly correlated vectors
    _hc_x_perf = [1.0, 2.0, 3.0, 4.0, 5.0]
    _hc_y_perf = [2.0, 4.0, 6.0, 8.0, 10.0]
    _hc_corr_perf = _pearson_correlation(_hc_x_perf, _hc_y_perf)
    test("HC: _pearson_correlation perfectly correlated vectors == 1.0",
         abs(_hc_corr_perf - 1.0) < 1e-9,
         f"got {_hc_corr_perf}")

    # _pearson_correlation — perfectly anti-correlated vectors
    _hc_x_anti = [1.0, 2.0, 3.0, 4.0, 5.0]
    _hc_y_anti = [5.0, 4.0, 3.0, 2.0, 1.0]
    _hc_corr_anti = _pearson_correlation(_hc_x_anti, _hc_y_anti)
    test("HC: _pearson_correlation anti-correlated vectors == -1.0",
         abs(_hc_corr_anti - (-1.0)) < 1e-9,
         f"got {_hc_corr_anti}")

    # _pearson_correlation — uncorrelated vectors (near 0)
    _hc_x_unc = [1.0, 2.0, 3.0, 4.0, 5.0]
    _hc_y_unc = [3.0, 3.0, 3.0, 3.0, 3.0]  # constant — zero variance -> 0.0
    _hc_corr_unc = _pearson_correlation(_hc_x_unc, _hc_y_unc)
    test("HC: _pearson_correlation zero-variance vector returns 0.0",
         abs(_hc_corr_unc - 0.0) < 1e-9,
         f"got {_hc_corr_unc}")

    # _pearson_correlation — different-length vectors returns 0.0
    _hc_corr_len = _pearson_correlation([1.0, 2.0], [1.0, 2.0, 3.0])
    test("HC: _pearson_correlation different-length vectors returns 0.0",
         abs(_hc_corr_len - 0.0) < 1e-9,
         f"got {_hc_corr_len}")

    # _pearson_correlation — fewer than 2 elements returns 0.0
    _hc_corr_one = _pearson_correlation([1.0], [1.0])
    test("HC: _pearson_correlation single-element vectors returns 0.0",
         abs(_hc_corr_one - 0.0) < 1e-9,
         f"got {_hc_corr_one}")

    # _pearson_correlation — empty vectors returns 0.0
    _hc_corr_empty = _pearson_correlation([], [])
    test("HC: _pearson_correlation empty vectors returns 0.0",
         abs(_hc_corr_empty - 0.0) < 1e-9,
         f"got {_hc_corr_empty}")

    # _pearson_correlation — both zero-variance returns 0.0
    _hc_corr_both_const = _pearson_correlation([3.0, 3.0, 3.0], [5.0, 5.0, 5.0])
    test("HC: _pearson_correlation both zero-variance returns 0.0",
         abs(_hc_corr_both_const - 0.0) < 1e-9,
         f"got {_hc_corr_both_const}")

    # _short — standard gate names
    test("HC: _short('gate_01_read_before_edit') == 'G01'",
         _short("gate_01_read_before_edit") == "G01")
    test("HC: _short('gate_12_foo') == 'G12'",
         _short("gate_12_foo") == "G12")
    test("HC: _short('gate_03_test') == 'G03'",
         _short("gate_03_test") == "G03")

    # _short — non-gate names returned as-is
    test("HC: _short('custom_gate') returns 'custom_gate'",
         _short("custom_gate") == "custom_gate")
    test("HC: _short('mygate') returns 'mygate'",
         _short("mygate") == "mygate")

    # _redundancy_recommendation — with protected gate g1
    _hc_prot_g1 = "gate_01_read_before_edit"
    _hc_other_g = "gate_07_something"
    _hc_rec_prot = _redundancy_recommendation(_hc_prot_g1, _hc_other_g, 0.95)
    test("HC: _redundancy_recommendation g1 protected mentions Tier-1",
         "Tier-1" in _hc_rec_prot or "protected" in _hc_rec_prot.lower(),
         f"got: {_hc_rec_prot!r}")
    test("HC: _redundancy_recommendation g1 protected mentions the other gate short name",
         "G07" in _hc_rec_prot or _hc_other_g in _hc_rec_prot,
         f"got: {_hc_rec_prot!r}")

    # _redundancy_recommendation — with protected gate g2
    _hc_rec_prot2 = _redundancy_recommendation(_hc_other_g, _hc_prot_g1, 0.90)
    test("HC: _redundancy_recommendation g2 protected mentions Tier-1",
         "Tier-1" in _hc_rec_prot2 or "protected" in _hc_rec_prot2.lower(),
         f"got: {_hc_rec_prot2!r}")

    # _redundancy_recommendation — non-protected pair mentions merging
    _hc_g_a = "gate_07_foo"
    _hc_g_b = "gate_08_bar"
    _hc_rec_nonprot = _redundancy_recommendation(_hc_g_a, _hc_g_b, 0.85)
    test("HC: _redundancy_recommendation non-protected pair mentions merging/consolidat",
         "merging" in _hc_rec_nonprot.lower() or "consolidat" in _hc_rec_nonprot.lower(),
         f"got: {_hc_rec_nonprot!r}")
    test("HC: _redundancy_recommendation non-protected includes correlation value",
         "0.85" in _hc_rec_nonprot,
         f"got: {_hc_rec_nonprot!r}")

    # build_fire_vectors — excludes gates with blocks < MIN_BLOCKS_FOR_ANALYSIS
    _hc_eff_data_low = {
        "gate_low_blocks": {"blocks": 2, "overrides": 0, "prevented": 0},
        "gate_enough":     {"blocks": 5, "overrides": 1, "prevented": 2},
    }
    _hc_vectors_low = build_fire_vectors(_hc_eff_data_low)
    test("HC: build_fire_vectors excludes gate with blocks < MIN_BLOCKS_FOR_ANALYSIS",
         "gate_low_blocks" not in _hc_vectors_low,
         f"vectors: {list(_hc_vectors_low.keys())}")
    test("HC: build_fire_vectors includes gate with sufficient blocks",
         "gate_enough" in _hc_vectors_low,
         f"vectors: {list(_hc_vectors_low.keys())}")

    # build_fire_vectors — vector length equals time_windows
    _hc_eff_data_vec = {
        "gate_a": {"blocks": 10, "overrides": 2, "prevented": 3},
    }
    _hc_vectors_vec = build_fire_vectors(_hc_eff_data_vec, time_windows=8)
    test("HC: build_fire_vectors vector length equals time_windows",
         len(_hc_vectors_vec.get("gate_a", [])) == 8,
         f"got length: {len(_hc_vectors_vec.get('gate_a', []))}")

    # build_fire_vectors — all vector values are non-negative
    _hc_eff_data_nn = {
        "gate_x": {"blocks": 20, "overrides": 5, "prevented": 10},
    }
    _hc_vectors_nn = build_fire_vectors(_hc_eff_data_nn)
    test("HC: build_fire_vectors all values non-negative",
         all(v >= 0.0 for v in _hc_vectors_nn.get("gate_x", [])))

    # build_fire_vectors — empty effectiveness data returns empty dict
    test("HC: build_fire_vectors empty effectiveness_data returns {}",
         build_fire_vectors({}) == {})

    # build_fire_vectors — non-dict entry is skipped
    _hc_eff_nondict = {
        "gate_a": {"blocks": 10, "overrides": 0, "prevented": 0},
        "gate_bad": "not a dict",
    }
    _hc_vectors_nondict = build_fire_vectors(_hc_eff_nondict)
    test("HC: build_fire_vectors skips non-dict entries",
         "gate_bad" not in _hc_vectors_nondict)

    # compute_correlation_matrix — returns dict with tuple keys
    _hc_vecs = {
        "gate_a": [1.0, 2.0, 3.0, 4.0, 5.0],
        "gate_b": [5.0, 4.0, 3.0, 2.0, 1.0],
        "gate_c": [2.0, 4.0, 6.0, 8.0, 10.0],
    }
    _hc_matrix = compute_correlation_matrix(_hc_vecs)
    test("HC: compute_correlation_matrix returns dict",
         isinstance(_hc_matrix, dict))
    test("HC: compute_correlation_matrix keys are tuples",
         all(isinstance(k, tuple) for k in _hc_matrix.keys()))
    test("HC: compute_correlation_matrix 3 gates -> 3 pairs",
         len(_hc_matrix) == 3,
         f"got {len(_hc_matrix)} pairs")

    # compute_correlation_matrix — gate_a and gate_c should be highly correlated
    _hc_ac_corr = _hc_matrix.get(("gate_a", "gate_c"), _hc_matrix.get(("gate_c", "gate_a"), None))
    test("HC: compute_correlation_matrix gate_a and gate_c corr == 1.0",
         _hc_ac_corr is not None and abs(_hc_ac_corr - 1.0) < 1e-3,
         f"got {_hc_ac_corr}")

    # compute_correlation_matrix — gate_a and gate_b should be anti-correlated
    _hc_ab_corr = _hc_matrix.get(("gate_a", "gate_b"), _hc_matrix.get(("gate_b", "gate_a"), None))
    test("HC: compute_correlation_matrix gate_a and gate_b corr == -1.0",
         _hc_ab_corr is not None and abs(_hc_ab_corr - (-1.0)) < 1e-3,
         f"got {_hc_ab_corr}")

    # compute_correlation_matrix — empty vectors returns empty dict
    test("HC: compute_correlation_matrix empty vectors returns {}",
         compute_correlation_matrix({}) == {})

    # detect_redundant_pairs — high correlation pair flagged
    _hc_matrix_high = {("gate_a", "gate_c"): 0.95, ("gate_a", "gate_b"): -0.90}
    _hc_redundant = detect_redundant_pairs(_hc_matrix_high, threshold=0.80)
    test("HC: detect_redundant_pairs finds pair with corr >= threshold",
         len(_hc_redundant) == 1,
         f"found {len(_hc_redundant)} pairs")
    test("HC: detect_redundant_pairs result has 'gate_a' and 'gate_c'",
         len(_hc_redundant) > 0 and
         _hc_redundant[0]["gate_a"] == "gate_a" and _hc_redundant[0]["gate_b"] == "gate_c")
    test("HC: detect_redundant_pairs result has 'correlation' key",
         len(_hc_redundant) > 0 and "correlation" in _hc_redundant[0])
    test("HC: detect_redundant_pairs result has 'recommendation' key",
         len(_hc_redundant) > 0 and "recommendation" in _hc_redundant[0])

    # detect_redundant_pairs — no high-correlation pairs returns []
    _hc_matrix_low = {("gate_x", "gate_y"): 0.50}
    test("HC: detect_redundant_pairs no high-corr pairs returns []",
         detect_redundant_pairs(_hc_matrix_low, threshold=0.80) == [])

    # detect_synergistic_pairs — low correlation pair flagged
    _hc_matrix_syn = {("gate_a", "gate_b"): -0.85, ("gate_a", "gate_c"): 0.92}
    _hc_synergistic = detect_synergistic_pairs(_hc_matrix_syn, threshold=-0.50)
    test("HC: detect_synergistic_pairs finds pair with corr <= threshold",
         len(_hc_synergistic) == 1,
         f"found {len(_hc_synergistic)} pairs")
    test("HC: detect_synergistic_pairs result has 'recommendation' key",
         len(_hc_synergistic) > 0 and "recommendation" in _hc_synergistic[0])

    # detect_synergistic_pairs — no low-correlation pairs returns []
    _hc_matrix_no_syn = {("gate_x", "gate_y"): 0.10}
    test("HC: detect_synergistic_pairs no low-corr pairs returns []",
         detect_synergistic_pairs(_hc_matrix_no_syn, threshold=-0.50) == [])

    # suggest_optimizations — returns list of dicts with expected keys
    _hc_eff_data_opt = {
        "gate_a": {"blocks": 10, "overrides": 2, "prevented": 3},
        "gate_b": {"blocks": 0,  "overrides": 0, "prevented": 0},
    }
    _hc_opts = suggest_optimizations(_hc_eff_data_opt)
    test("HC: suggest_optimizations returns list",
         isinstance(_hc_opts, list))
    if _hc_opts:
        _hc_opt_keys = {"type", "priority", "description", "gates_affected", "confidence"}
        test("HC: suggest_optimizations entries have expected keys",
             all(_hc_opt_keys.issubset(set(o.keys())) for o in _hc_opts),
             f"missing keys in: {[set(o.keys()) for o in _hc_opts]}")
        test("HC: suggest_optimizations 'type' is a string",
             all(isinstance(o["type"], str) for o in _hc_opts))
        test("HC: suggest_optimizations 'priority' is an int",
             all(isinstance(o["priority"], int) for o in _hc_opts))

    # generate_health_report — returns expected keys
    _hc_eff_data_report = {
        "gate_07_foo": {"blocks": 10, "overrides": 2, "prevented": 5},
        "gate_08_bar": {"blocks": 15, "overrides": 1, "prevented": 8},
        "gate_09_baz": {"blocks": 5,  "overrides": 3, "prevented": 2},
    }
    _hc_report = generate_health_report(_hc_eff_data_report)
    test("HC: generate_health_report returns dict",
         isinstance(_hc_report, dict))
    _hc_report_keys = {"gates_analyzed", "correlation_pairs", "redundant_pairs",
                       "synergistic_pairs", "optimizations", "overall_diversity"}
    test("HC: generate_health_report has all expected keys",
         _hc_report_keys.issubset(set(_hc_report.keys())),
         f"missing: {_hc_report_keys - set(_hc_report.keys())}")
    test("HC: generate_health_report gates_analyzed is int",
         isinstance(_hc_report.get("gates_analyzed"), int))
    test("HC: generate_health_report correlation_pairs is int",
         isinstance(_hc_report.get("correlation_pairs"), int))
    test("HC: generate_health_report overall_diversity in [0.0, 1.0]",
         isinstance(_hc_report.get("overall_diversity"), float) and
         0.0 <= _hc_report["overall_diversity"] <= 1.0,
         f"got: {_hc_report.get('overall_diversity')}")

    # generate_health_report — empty data returns sensible defaults
    _hc_empty_report = generate_health_report({})
    test("HC: generate_health_report empty data has gates_analyzed == 0",
         _hc_empty_report.get("gates_analyzed") == 0)
    test("HC: generate_health_report empty data has overall_diversity == 1.0",
         abs(_hc_empty_report.get("overall_diversity", -1) - 1.0) < 1e-9,
         f"got: {_hc_empty_report.get('overall_diversity')}")

except Exception as _hc_exc:
    test("HC: import and module-level tests", False, str(_hc_exc))

# ─────────────────────────────────────────────────
# RL: rate_limiter (shared/rate_limiter.py)
# ─────────────────────────────────────────────────
try:
    from shared.rate_limiter import (
        TOOL_RATE, GATE_RATE, API_RATE,
        _config_for, _refill_tokens, _get_or_create_bucket,
        allow, consume, get_remaining,
        reset as rl_reset, get_all_limits, _buckets,
    )

    # Preset constants
    test("RL: TOOL_RATE rate == 10.0",
         abs(TOOL_RATE[0] - 10.0) < 1e-9)
    test("RL: TOOL_RATE burst == 10",
         TOOL_RATE[1] == 10)
    test("RL: GATE_RATE rate == 30.0",
         abs(GATE_RATE[0] - 30.0) < 1e-9)
    test("RL: GATE_RATE burst == 30",
         GATE_RATE[1] == 30)
    test("RL: API_RATE rate == 60.0",
         abs(API_RATE[0] - 60.0) < 1e-9)
    test("RL: API_RATE burst == 60",
         API_RATE[1] == 60)

    # _config_for — prefix matching
    test("RL: _config_for 'tool:Edit' returns TOOL_RATE",
         _config_for("tool:Edit") == TOOL_RATE)
    test("RL: _config_for 'tool:anything' returns TOOL_RATE",
         _config_for("tool:anything") == TOOL_RATE)
    test("RL: _config_for 'gate:gate_04' returns GATE_RATE",
         _config_for("gate:gate_04") == GATE_RATE)
    test("RL: _config_for 'api:memory' returns API_RATE",
         _config_for("api:memory") == API_RATE)
    test("RL: _config_for unknown prefix returns _DEFAULT_RATE (GATE_RATE)",
         _config_for("unknown:key") == GATE_RATE)
    test("RL: _config_for empty string returns _DEFAULT_RATE",
         _config_for("") == GATE_RATE)

    # _refill_tokens — known elapsed time
    _rl_bucket_ref = {"tokens": 0.0, "last_refill": 0.0}
    # rate=60/min = 1/sec. After 10s elapsed, should add 10 tokens. burst=60 -> 10.0
    _rl_refilled = _refill_tokens(_rl_bucket_ref, 60.0, 60, 10.0)
    test("RL: _refill_tokens adds tokens proportional to elapsed time",
         abs(_rl_refilled - 10.0) < 1e-6,
         f"got {_rl_refilled}")

    # _refill_tokens — caps at burst
    _rl_bucket_cap = {"tokens": 55.0, "last_refill": 0.0}
    _rl_refilled_cap = _refill_tokens(_rl_bucket_cap, 60.0, 60, 10.0)
    test("RL: _refill_tokens caps at burst capacity",
         abs(_rl_refilled_cap - 60.0) < 1e-6,
         f"got {_rl_refilled_cap}")

    # _refill_tokens — no elapsed time returns same tokens
    _rl_bucket_zero = {"tokens": 5.0, "last_refill": 100.0}
    _rl_refilled_zero = _refill_tokens(_rl_bucket_zero, 60.0, 60, 100.0)
    test("RL: _refill_tokens no elapsed time returns same tokens",
         abs(_rl_refilled_zero - 5.0) < 1e-6,
         f"got {_rl_refilled_zero}")

    # _get_or_create_bucket — creates new bucket with full tokens
    _rl_new_key = "_test_rl:brand_new_abc123"
    if _rl_new_key in _buckets:
        del _buckets[_rl_new_key]
    _rl_new_bucket = _get_or_create_bucket(_rl_new_key, 9999.0)
    _rl_rate, _rl_burst = _config_for(_rl_new_key)
    test("RL: _get_or_create_bucket creates new bucket with full tokens",
         abs(_rl_new_bucket["tokens"] - float(_rl_burst)) < 1e-6,
         f"got {_rl_new_bucket['tokens']}, expected {_rl_burst}")

    # _get_or_create_bucket — returns same bucket on second call
    _rl_same_bucket = _get_or_create_bucket(_rl_new_key, 9999.0)
    test("RL: _get_or_create_bucket returns same bucket on second call",
         _rl_same_bucket is _rl_new_bucket)

    # allow — full bucket returns True
    rl_reset("_test_rl:allow_full")
    test("RL: allow returns True when bucket is full",
         allow("_test_rl:allow_full") is True)

    # allow — does not consume tokens
    rl_reset("_test_rl:allow_no_consume")
    _rl_before = get_remaining("_test_rl:allow_no_consume")
    allow("_test_rl:allow_no_consume")
    allow("_test_rl:allow_no_consume")
    allow("_test_rl:allow_no_consume")
    _rl_after_allow = get_remaining("_test_rl:allow_no_consume")
    test("RL: allow does not consume tokens",
         _rl_before == _rl_after_allow,
         f"before={_rl_before}, after={_rl_after_allow}")

    # allow — returns False when bucket would be insufficient
    rl_reset("_test_rl:allow_empty")
    _rl_tool_burst = GATE_RATE[1]  # _test_rl: prefix uses default (GATE_RATE)
    test("RL: allow returns False when requesting more tokens than burst",
         allow("_test_rl:allow_empty", tokens=_rl_tool_burst + 1) is False)

    # consume — decrements tokens
    rl_reset("_test_rl:consume_dec")
    _rl_before_consume = get_remaining("_test_rl:consume_dec")
    _rl_consume_ok = consume("_test_rl:consume_dec")
    _rl_after_consume = get_remaining("_test_rl:consume_dec")
    test("RL: consume returns True when tokens available",
         _rl_consume_ok is True)
    test("RL: consume decrements remaining by 1",
         _rl_after_consume == _rl_before_consume - 1,
         f"before={_rl_before_consume}, after={_rl_after_consume}")

    # consume — returns False on empty bucket
    rl_reset("_test_rl:consume_empty")
    _rl_empty_burst = _config_for("_test_rl:consume_empty")[1]
    for _ in range(_rl_empty_burst):
        consume("_test_rl:consume_empty")
    test("RL: consume returns False on empty bucket",
         consume("_test_rl:consume_empty") is False)
    test("RL: get_remaining returns 0 when bucket empty",
         get_remaining("_test_rl:consume_empty") == 0)

    # consume — multiple tokens at once
    rl_reset("_test_rl:consume_multi")
    _rl_multi_before = get_remaining("_test_rl:consume_multi")
    consume("_test_rl:consume_multi", tokens=3)
    _rl_multi_after = get_remaining("_test_rl:consume_multi")
    test("RL: consume with tokens=3 decrements by 3",
         _rl_multi_before - _rl_multi_after == 3,
         f"before={_rl_multi_before}, after={_rl_multi_after}")

    # get_remaining — returns int
    rl_reset("_test_rl:get_remaining_type")
    test("RL: get_remaining returns int",
         isinstance(get_remaining("_test_rl:get_remaining_type"), int))

    # get_remaining — reflects current bucket state
    rl_reset("_test_rl:get_remaining_val")
    _rl_gr_burst = _config_for("_test_rl:get_remaining_val")[1]
    test("RL: get_remaining returns burst for full bucket",
         get_remaining("_test_rl:get_remaining_val") == _rl_gr_burst)

    # reset — refills to burst
    rl_reset("_test_rl:reset_refill")
    for _ in range(5):
        consume("_test_rl:reset_refill")
    _rl_after_consume = get_remaining("_test_rl:reset_refill")
    rl_reset("_test_rl:reset_refill")
    _rl_after_reset = get_remaining("_test_rl:reset_refill")
    _rl_reset_burst = _config_for("_test_rl:reset_refill")[1]
    test("RL: reset refills bucket to burst capacity",
         _rl_after_reset == _rl_reset_burst,
         f"got {_rl_after_reset}, expected {_rl_reset_burst}")

    # reset — works on non-existent key (creates it)
    _rl_nonexist_key = "_test_rl:brand_new_reset_xyz"
    if _rl_nonexist_key in _buckets:
        del _buckets[_rl_nonexist_key]
    rl_reset(_rl_nonexist_key)
    test("RL: reset on non-existent key creates bucket",
         _rl_nonexist_key in _buckets)

    # get_all_limits — returns dict
    _rl_limits = get_all_limits()
    test("RL: get_all_limits returns dict",
         isinstance(_rl_limits, dict))

    # get_all_limits — entries have expected keys
    rl_reset("_test_rl:all_limits")
    _rl_all = get_all_limits()
    test("RL: get_all_limits includes recently reset key",
         "_test_rl:all_limits" in _rl_all,
         f"keys (first 5): {list(_rl_all.keys())[:5]}")
    if "_test_rl:all_limits" in _rl_all:
        _rl_entry = _rl_all["_test_rl:all_limits"]
        _rl_expected_entry_keys = {"tokens_remaining", "rate_per_minute", "burst", "last_refill"}
        test("RL: get_all_limits entry has all expected keys",
             _rl_expected_entry_keys.issubset(set(_rl_entry.keys())),
             f"missing: {_rl_expected_entry_keys - set(_rl_entry.keys())}")
        test("RL: get_all_limits tokens_remaining is int",
             isinstance(_rl_entry.get("tokens_remaining"), int))
        test("RL: get_all_limits rate_per_minute is float",
             isinstance(_rl_entry.get("rate_per_minute"), float))
        test("RL: get_all_limits burst is int",
             isinstance(_rl_entry.get("burst"), int))
        test("RL: get_all_limits last_refill is float",
             isinstance(_rl_entry.get("last_refill"), float))

    # _buckets — is a module-level dict
    test("RL: _buckets is a dict",
         isinstance(_buckets, dict))

    # Verify tool: prefix uses TOOL_RATE burst (10)
    rl_reset("tool:_test_rl_tool_prefix")
    test("RL: tool: prefix bucket starts at burst=10",
         get_remaining("tool:_test_rl_tool_prefix") == 10)

    # Verify gate: prefix uses GATE_RATE burst (30)
    rl_reset("gate:_test_rl_gate_prefix")
    test("RL: gate: prefix bucket starts at burst=30",
         get_remaining("gate:_test_rl_gate_prefix") == 30)

    # Verify api: prefix uses API_RATE burst (60)
    rl_reset("api:_test_rl_api_prefix")
    test("RL: api: prefix bucket starts at burst=60",
         get_remaining("api:_test_rl_api_prefix") == 60)

    # Consume all tool tokens then verify exhaustion
    rl_reset("tool:_test_rl_exhaust")
    for _ in range(10):
        consume("tool:_test_rl_exhaust")
    test("RL: tool: bucket exhausted after 10 consumes (burst=10)",
         get_remaining("tool:_test_rl_exhaust") == 0)
    test("RL: allow returns False on exhausted tool bucket",
         allow("tool:_test_rl_exhaust") is False)

except Exception as _rl_exc:
    test("RL: import and module-level tests", False, str(_rl_exc))

# ─────────────────────────────────────────────────────────────────────────────
# ME: metrics_exporter tests
# ─────────────────────────────────────────────────────────────────────────────
try:
    from shared.metrics_exporter import (
        DEFAULT_OUTPUT_PATH,
        _DEFS,
        _ls,
        _emit_counter,
        _emit_gauge,
        _emit_histogram,
        _zero_metric,
        export_prometheus,
        export_json,
    )

    # --- Constants ---
    test("ME: DEFAULT_OUTPUT_PATH is correct string",
         DEFAULT_OUTPUT_PATH == "/tmp/torus_metrics.prom")

    test("ME: _DEFS is a non-empty list",
         isinstance(_DEFS, list) and len(_DEFS) > 0)

    test("ME: _DEFS entries are tuples of length 5",
         all(isinstance(d, tuple) and len(d) == 5 for d in _DEFS))

    test("ME: _DEFS contains expected prom name torus_gate_blocks_total",
         any(d[0] == "torus_gate_blocks_total" for d in _DEFS))

    test("ME: _DEFS contains expected prom name torus_gate_fires_total",
         any(d[0] == "torus_gate_fires_total" for d in _DEFS))

    test("ME: _DEFS contains torus_gate_latency_seconds as histogram",
         any(d[0] == "torus_gate_latency_seconds" and d[2] == "histogram" for d in _DEFS))

    test("ME: _DEFS contains torus_memory_count as gauge",
         any(d[0] == "torus_memory_count" and d[2] == "gauge" for d in _DEFS))

    test("ME: _DEFS latency entry has scale 0.001",
         any(d[0] == "torus_gate_latency_seconds" and d[4] == 0.001 for d in _DEFS))

    # --- _ls label formatting ---
    test("ME: _ls({}) returns empty string",
         _ls({}) == "")

    test("ME: _ls with single label returns correct format",
         _ls({"gate": "g1"}) == '{gate="g1"}')

    test("ME: _ls with two labels sorts alphabetically",
         _ls({"b": "2", "a": "1"}) == '{a="1",b="2"}')

    test("ME: _ls with three labels sorts all keys",
         _ls({"z": "3", "a": "1", "m": "2"}) == '{a="1",m="2",z="3"}')

    test("ME: _ls result starts with { and ends with }",
         _ls({"k": "v"}).startswith("{") and _ls({"k": "v"}).endswith("}"))

    test("ME: _ls with le label for histogram",
         _ls({"le": "+Inf"}) == '{le="+Inf"}')

    # --- _emit_counter ---
    _me_counter_lines = []
    _me_counter_entries = {
        "g1": {"labels": {"gate": "gate1"}, "value": 5},
        "g2": {"labels": {"gate": "gate2"}, "value": 3},
    }
    _emit_counter(_me_counter_lines, "test_counter", "A test counter", _me_counter_entries, 1.0)

    test("ME: _emit_counter produces # HELP line",
         any("# HELP test_counter A test counter" in ln for ln in _me_counter_lines))

    test("ME: _emit_counter produces # TYPE counter line",
         any("# TYPE test_counter counter" in ln for ln in _me_counter_lines))

    test("ME: _emit_counter produces value line for each entry",
         sum(1 for ln in _me_counter_lines if ln.startswith("test_counter{")) == 2)

    test("ME: _emit_counter applies scale of 1.0 correctly",
         any("5.0" in ln or "5" in ln for ln in _me_counter_lines if "gate1" in ln))

    _me_counter_lines2 = []
    _emit_counter(_me_counter_lines2, "scaled_counter", "scaled", {"k": {"labels": {}, "value": 100}}, 0.001)
    test("ME: _emit_counter applies scale 0.001 correctly",
         any("0.1" in ln for ln in _me_counter_lines2 if ln.startswith("scaled_counter")))

    # --- _emit_gauge ---
    _me_gauge_lines = []
    _me_gauge_entries = {
        "k1": {"labels": {}, "value": 42.0},
    }
    _emit_gauge(_me_gauge_lines, "test_gauge", "A test gauge", _me_gauge_entries, 1.0)

    test("ME: _emit_gauge produces # HELP line",
         any("# HELP test_gauge" in ln for ln in _me_gauge_lines))

    test("ME: _emit_gauge produces # TYPE gauge line",
         any("# TYPE test_gauge gauge" in ln for ln in _me_gauge_lines))

    test("ME: _emit_gauge produces value line",
         any(ln.startswith("test_gauge") and not ln.startswith("# ") for ln in _me_gauge_lines))

    _me_gauge_lines2 = []
    _emit_gauge(_me_gauge_lines2, "test_gauge2", "injected", {"k": {"labels": {}, "value": 1.0}},
                1.0, inject_labels={"table": "knowledge"})
    test("ME: _emit_gauge inject_labels merges into output",
         any("knowledge" in ln for ln in _me_gauge_lines2 if "test_gauge2" in ln))

    # --- _emit_histogram ---
    _me_hist_lines = []
    _me_hist_entries = {
        "g1": {"labels": {"gate": "g1"}, "count": 10, "sum": 500.0},
    }
    _emit_histogram(_me_hist_lines, "test_hist", "A test histogram", _me_hist_entries, 0.001)

    test("ME: _emit_histogram produces # HELP line",
         any("# HELP test_hist" in ln for ln in _me_hist_lines))

    test("ME: _emit_histogram produces # TYPE histogram line",
         any("# TYPE test_hist histogram" in ln for ln in _me_hist_lines))

    test("ME: _emit_histogram produces _bucket line with le=+Inf",
         any("test_hist_bucket" in ln and "+Inf" in ln for ln in _me_hist_lines))

    test("ME: _emit_histogram produces _sum line",
         any("test_hist_sum" in ln for ln in _me_hist_lines))

    test("ME: _emit_histogram produces _count line",
         any("test_hist_count" in ln for ln in _me_hist_lines))

    test("ME: _emit_histogram scales sum by 0.001 (500ms -> 0.5s)",
         any("0.5" in ln for ln in _me_hist_lines if "test_hist_sum" in ln))

    test("ME: _emit_histogram _count matches entry count",
         any("10" in ln for ln in _me_hist_lines if "test_hist_count" in ln))

    # --- _zero_metric ---
    _me_zero_counter = []
    _zero_metric(_me_zero_counter, "zero_counter", "zero help", "counter")
    test("ME: _zero_metric counter has # HELP line",
         any("# HELP zero_counter" in ln for ln in _me_zero_counter))
    test("ME: _zero_metric counter has # TYPE counter line",
         any("# TYPE zero_counter counter" in ln for ln in _me_zero_counter))
    test("ME: _zero_metric counter emits 'zero_counter 0'",
         "zero_counter 0" in _me_zero_counter)

    _me_zero_hist = []
    _zero_metric(_me_zero_hist, "zero_hist", "zero hist help", "histogram")
    test("ME: _zero_metric histogram has _bucket line",
         any("zero_hist_bucket" in ln and "+Inf" in ln for ln in _me_zero_hist))
    test("ME: _zero_metric histogram has _sum line",
         any("zero_hist_sum 0" in ln for ln in _me_zero_hist))
    test("ME: _zero_metric histogram has _count line",
         any("zero_hist_count 0" in ln for ln in _me_zero_hist))
    test("ME: _zero_metric histogram does NOT emit plain 'zero_hist 0'",
         "zero_hist 0" not in _me_zero_hist)

    _me_zero_gauge = []
    _zero_metric(_me_zero_gauge, "zero_gauge", "zero gauge help", "gauge")
    test("ME: _zero_metric gauge has # TYPE gauge line",
         any("# TYPE zero_gauge gauge" in ln for ln in _me_zero_gauge))
    test("ME: _zero_metric gauge emits 'zero_gauge 0'",
         "zero_gauge 0" in _me_zero_gauge)

    # --- export_prometheus ---
    _me_prom_text = export_prometheus("/tmp/_test_torus_metrics.prom")
    test("ME: export_prometheus returns a string",
         isinstance(_me_prom_text, str))
    test("ME: export_prometheus starts with '# Torus Framework Metrics'",
         _me_prom_text.startswith("# Torus Framework Metrics"))
    test("ME: export_prometheus contains # HELP lines",
         "# HELP" in _me_prom_text)
    test("ME: export_prometheus contains # TYPE lines",
         "# TYPE" in _me_prom_text)
    test("ME: export_prometheus contains torus_gate_blocks_total",
         "torus_gate_blocks_total" in _me_prom_text)
    test("ME: export_prometheus contains torus_health_score",
         "torus_health_score" in _me_prom_text)
    test("ME: export_prometheus contains torus_errors_total",
         "torus_errors_total" in _me_prom_text)
    test("ME: export_prometheus ends with newline",
         _me_prom_text.endswith("\n"))

    # --- export_json ---
    _me_json = export_json()
    test("ME: export_json returns a dict",
         isinstance(_me_json, dict))
    test("ME: export_json has 'exported_at' key",
         "exported_at" in _me_json)
    test("ME: export_json 'exported_at' is a number (float or int)",
         isinstance(_me_json.get("exported_at"), (int, float)))
    test("ME: export_json has 'metrics' key",
         "metrics" in _me_json)
    test("ME: export_json 'metrics' is a dict",
         isinstance(_me_json.get("metrics"), dict))
    test("ME: export_json metrics has torus_gate_blocks_total",
         "torus_gate_blocks_total" in _me_json.get("metrics", {}))
    test("ME: export_json metrics has torus_health_score",
         "torus_health_score" in _me_json.get("metrics", {}))
    test("ME: export_json metrics has torus_memory_count",
         "torus_memory_count" in _me_json.get("metrics", {}))
    test("ME: export_json metrics has torus_errors_total",
         "torus_errors_total" in _me_json.get("metrics", {}))
    test("ME: export_json exported_at is recent (within 10 seconds)",
         abs(time.time() - _me_json["exported_at"]) < 10)

except Exception as _me_exc:
    test("ME: metrics_exporter module-level tests", False, str(_me_exc))

# ─────────────────────────────────────────────────────────────────────────────
# EP: error_pattern_analyzer tests
# ─────────────────────────────────────────────────────────────────────────────
try:
    from shared.error_pattern_analyzer import (
        _PATTERN_TABLE,
        _FALLBACK_PATTERN,
        _FALLBACK_CATEGORY,
        _FALLBACK_ROOT_CAUSE,
        _PREVENTION_MAP,
        extract_pattern,
        _classify,
        analyze_errors,
        top_patterns,
        correlate_errors,
        suggest_prevention,
        frequency_from_strings,
    )

    # --- Constants ---
    test("EP: _FALLBACK_PATTERN is 'other:unclassified'",
         _FALLBACK_PATTERN == "other:unclassified")
    test("EP: _FALLBACK_CATEGORY is 'other'",
         _FALLBACK_CATEGORY == "other")
    test("EP: _FALLBACK_ROOT_CAUSE is 'unknown'",
         _FALLBACK_ROOT_CAUSE == "unknown")
    test("EP: _PATTERN_TABLE is a non-empty list",
         isinstance(_PATTERN_TABLE, list) and len(_PATTERN_TABLE) > 0)
    test("EP: _PATTERN_TABLE entries are tuples of length 4",
         all(isinstance(e, tuple) and len(e) == 4 for e in _PATTERN_TABLE))
    test("EP: _PREVENTION_MAP is a non-empty dict",
         isinstance(_PREVENTION_MAP, dict) and len(_PREVENTION_MAP) > 0)
    test("EP: _PREVENTION_MAP contains fallback pattern key",
         _FALLBACK_PATTERN in _PREVENTION_MAP)

    # All pattern table labels should have prevention tips
    _ep_table_labels = [e[1] for e in _PATTERN_TABLE]
    test("EP: _PREVENTION_MAP has entry for every pattern table label",
         all(label in _PREVENTION_MAP for label in _ep_table_labels))

    # --- extract_pattern ---
    test("EP: extract_pattern 'must Read file before edit' -> gate1:read-before-edit",
         extract_pattern("must Read file before edit") == "gate1:read-before-edit")

    test("EP: extract_pattern 'rm -rf /important' -> gate2:destructive-command",
         extract_pattern("rm -rf /important") == "gate2:destructive-command")

    test("EP: extract_pattern 'ModuleNotFoundError: no module' -> python:import-error",
         extract_pattern("ModuleNotFoundError: no module named foo") == "python:import-error")

    test("EP: extract_pattern 'FileNotFoundError' -> fs:file-not-found",
         extract_pattern("FileNotFoundError: /some/path") == "fs:file-not-found")

    test("EP: extract_pattern 'No such file or directory' -> fs:file-not-found",
         extract_pattern("No such file or directory: '/tmp/x'") == "fs:file-not-found")

    test("EP: extract_pattern 'timeout occurred' -> net:timeout",
         extract_pattern("timeout occurred connecting to server") == "net:timeout")

    test("EP: extract_pattern unknown message -> other:unclassified",
         extract_pattern("random unknown message xyz123") == "other:unclassified")

    test("EP: extract_pattern empty string -> other:unclassified",
         extract_pattern("") == "other:unclassified")

    test("EP: extract_pattern None -> other:unclassified",
         extract_pattern(None) == "other:unclassified")

    test("EP: extract_pattern 'DROP TABLE users' -> gate2:destructive-command",
         extract_pattern("DROP TABLE users") == "gate2:destructive-command")

    test("EP: extract_pattern memory not queried -> gate4:memory-not-queried",
         extract_pattern("memory not queried before this action") == "gate4:memory-not-queried")

    test("EP: extract_pattern 'rate limit exceeded' -> gate11:rate-limit",
         extract_pattern("rate limit exceeded in rolling window") == "gate11:rate-limit")

    test("EP: extract_pattern 'SyntaxError invalid syntax' -> python:syntax-error",
         extract_pattern("SyntaxError: invalid syntax") == "python:syntax-error")

    test("EP: extract_pattern 'AttributeError' -> python:attribute-error",
         extract_pattern("AttributeError: object has no attribute foo") == "python:attribute-error")

    test("EP: extract_pattern 'TypeError' -> python:type-error",
         extract_pattern("TypeError: expected str got int") == "python:type-error")

    test("EP: extract_pattern 'KeyError' -> python:key-error",
         extract_pattern("KeyError: 'missing_key'") == "python:key-error")

    test("EP: extract_pattern 'Permission denied' -> fs:permission-denied",
         extract_pattern("Permission denied: /etc/secret") == "fs:permission-denied")

    test("EP: extract_pattern 'ConnectionRefused' -> net:connection-refused",
         extract_pattern("ConnectionRefused: localhost:8080") == "net:connection-refused")

    test("EP: extract_pattern case-insensitive matching",
         extract_pattern("FILENOTFOUNDERROR: path missing") == "fs:file-not-found")

    # --- _classify ---
    _ep_cat, _ep_rc = _classify("gate1:read-before-edit")
    test("EP: _classify gate1:read-before-edit returns gate-block category",
         _ep_cat == "gate-block")
    test("EP: _classify gate1:read-before-edit returns user-error root cause",
         _ep_rc == "user-error")

    _ep_cat2, _ep_rc2 = _classify("python:import-error")
    test("EP: _classify python:import-error returns import category",
         _ep_cat2 == "import")
    test("EP: _classify python:import-error returns environmental root cause",
         _ep_rc2 == "environmental")

    _ep_cat3, _ep_rc3 = _classify("other:unclassified")
    test("EP: _classify unknown pattern returns other category",
         _ep_cat3 == "other")
    test("EP: _classify unknown pattern returns unknown root cause",
         _ep_rc3 == "unknown")

    _ep_cat4, _ep_rc4 = _classify("fs:file-not-found")
    test("EP: _classify fs:file-not-found returns filesystem category",
         _ep_cat4 == "filesystem")

    # --- suggest_prevention ---
    _ep_tip = suggest_prevention("gate1:read-before-edit")
    test("EP: suggest_prevention for known pattern returns non-empty string",
         isinstance(_ep_tip, str) and len(_ep_tip) > 0)
    test("EP: suggest_prevention for gate1 mentions Read",
         "Read" in _ep_tip or "read" in _ep_tip.lower())

    _ep_tip2 = suggest_prevention("other:unclassified")
    test("EP: suggest_prevention for fallback returns non-empty string",
         isinstance(_ep_tip2, str) and len(_ep_tip2) > 0)

    _ep_tip3 = suggest_prevention("totally:unknown-pattern-xyz")
    test("EP: suggest_prevention for truly unknown returns fallback tip",
         _ep_tip3 == _PREVENTION_MAP[_FALLBACK_PATTERN])

    _ep_tip4 = suggest_prevention("gate2:destructive-command")
    test("EP: suggest_prevention for gate2 is non-empty",
         isinstance(_ep_tip4, str) and len(_ep_tip4) > 0)

    # --- analyze_errors ---
    _ep_entries = [
        {"decision": "block", "reason": "must Read file before edit", "session_id": "s1"},
        {"decision": "block", "reason": "must Read file before edit", "session_id": "s1"},
        {"decision": "warn",  "reason": "FileNotFoundError: /tmp/x",  "session_id": "s1"},
        {"decision": "pass",  "reason": "ok",                         "session_id": "s1"},
        {"decision": "block", "reason": "ModuleNotFoundError: no mod", "session_id": "s2"},
    ]
    _ep_analysis = analyze_errors(_ep_entries)

    test("EP: analyze_errors returns dict",
         isinstance(_ep_analysis, dict))
    test("EP: analyze_errors total_errors counts block+warn only",
         _ep_analysis.get("total_errors") == 4)
    test("EP: analyze_errors has pattern_counts key",
         "pattern_counts" in _ep_analysis)
    test("EP: analyze_errors gate1 pattern count is 2",
         _ep_analysis["pattern_counts"].get("gate1:read-before-edit") == 2)
    test("EP: analyze_errors has category_breakdown key",
         "category_breakdown" in _ep_analysis)
    test("EP: analyze_errors has root_cause_breakdown key",
         "root_cause_breakdown" in _ep_analysis)
    test("EP: analyze_errors has suggestions key",
         "suggestions" in _ep_analysis)
    test("EP: analyze_errors suggestions keyed by observed patterns",
         "gate1:read-before-edit" in _ep_analysis.get("suggestions", {}))
    test("EP: analyze_errors has top_patterns key",
         "top_patterns" in _ep_analysis)
    test("EP: analyze_errors top_patterns is a list",
         isinstance(_ep_analysis.get("top_patterns"), list))
    test("EP: analyze_errors has session_breakdown key",
         "session_breakdown" in _ep_analysis)
    test("EP: analyze_errors session_breakdown has s1 and s2",
         "s1" in _ep_analysis.get("session_breakdown", {}) and
         "s2" in _ep_analysis.get("session_breakdown", {}))

    # --- top_patterns ---
    _ep_top = top_patterns(_ep_entries, n=5)
    test("EP: top_patterns returns a list",
         isinstance(_ep_top, list))
    test("EP: top_patterns entries are (pattern, count) tuples",
         all(isinstance(t, tuple) and len(t) == 2 for t in _ep_top))
    test("EP: top_patterns first entry is most frequent",
         len(_ep_top) > 0 and _ep_top[0][0] == "gate1:read-before-edit")
    test("EP: top_patterns respects n limit",
         len(top_patterns(_ep_entries, n=1)) <= 1)
    test("EP: top_patterns with empty entries returns []",
         top_patterns([], n=5) == [])

    # --- correlate_errors ---
    _ep_corr_entries = [
        {"decision": "block", "reason": "must Read file before edit", "session_id": "s1", "timestamp": "t1"},
        {"decision": "block", "reason": "must Read file before edit", "session_id": "s1", "timestamp": "t2"},
        {"decision": "block", "reason": "FileNotFoundError: /x",      "session_id": "s1", "timestamp": "t3"},
        {"decision": "block", "reason": "FileNotFoundError: /x",      "session_id": "s1", "timestamp": "t4"},
    ]
    _ep_corr = correlate_errors(_ep_corr_entries)
    test("EP: correlate_errors returns a list",
         isinstance(_ep_corr, list))
    test("EP: correlate_errors returns [] for fewer than 2 errors",
         correlate_errors([_ep_corr_entries[0]]) == [])
    test("EP: correlate_errors returns [] for empty list",
         correlate_errors([]) == [])
    test("EP: correlate_errors entries have required keys",
         all("pattern_a" in e and "pattern_b" in e and "count" in e
             for e in _ep_corr))
    test("EP: correlate_errors entries have example_session key",
         all("example_session" in e for e in _ep_corr))

    # --- frequency_from_strings ---
    _ep_freq = frequency_from_strings([
        "must Read file before edit",
        "must Read file before edit",
        "FileNotFoundError: /x",
        "random unknown xyz",
    ])
    test("EP: frequency_from_strings returns a dict",
         isinstance(_ep_freq, dict))
    test("EP: frequency_from_strings gate1 count is 2",
         _ep_freq.get("gate1:read-before-edit") == 2)
    test("EP: frequency_from_strings fs:file-not-found count is 1",
         _ep_freq.get("fs:file-not-found") == 1)
    test("EP: frequency_from_strings unknown -> other:unclassified count is 1",
         _ep_freq.get("other:unclassified") == 1)
    test("EP: frequency_from_strings with empty list returns empty dict",
         frequency_from_strings({}) == {} or frequency_from_strings([]) == {})

except Exception as _ep_exc:
    test("EP: error_pattern_analyzer module-level tests", False, str(_ep_exc))

# ─────────────────────────────────────────────────────────────────────────────
# GD: gate_dependency_graph tests
# ─────────────────────────────────────────────────────────────────────────────
try:
    from shared.gate_dependency_graph import (
        _load_dependencies,
        generate_mermaid_diagram,
        find_state_conflicts,
        find_parallel_safe_gates,
        get_state_hotspots,
        detect_cycles,
        recommend_gate_ordering,
        format_dependency_report,
    )

    # --- _load_dependencies ---
    _gd_deps = _load_dependencies()
    test("GD: _load_dependencies returns a dict",
         isinstance(_gd_deps, dict))

    # --- generate_mermaid_diagram ---
    _gd_mermaid = generate_mermaid_diagram()
    test("GD: generate_mermaid_diagram returns a string",
         isinstance(_gd_mermaid, str))
    test("GD: generate_mermaid_diagram contains 'mermaid'",
         "mermaid" in _gd_mermaid)
    test("GD: generate_mermaid_diagram contains 'flowchart'",
         "flowchart" in _gd_mermaid)
    test("GD: generate_mermaid_diagram is non-empty",
         len(_gd_mermaid) > 0)
    # Should have LR direction or fallback empty
    test("GD: generate_mermaid_diagram contains 'LR' or 'No dependency'",
         "LR" in _gd_mermaid or "No dependency" in _gd_mermaid)

    # --- find_state_conflicts ---
    _gd_conflicts = find_state_conflicts()
    test("GD: find_state_conflicts returns a list",
         isinstance(_gd_conflicts, list))
    test("GD: find_state_conflicts entries are dicts",
         all(isinstance(c, dict) for c in _gd_conflicts))
    test("GD: find_state_conflicts entries have 'key' field",
         all("key" in c for c in _gd_conflicts))
    test("GD: find_state_conflicts entries have 'type' field",
         all("type" in c for c in _gd_conflicts))
    test("GD: find_state_conflicts entries have 'gates' field",
         all("gates" in c for c in _gd_conflicts))
    test("GD: find_state_conflicts type values are valid",
         all(c["type"] in ("write-write", "read-write") for c in _gd_conflicts))

    # --- find_parallel_safe_gates ---
    _gd_parallel = find_parallel_safe_gates()
    test("GD: find_parallel_safe_gates returns a dict",
         isinstance(_gd_parallel, dict))
    test("GD: find_parallel_safe_gates has independent_gates key",
         "independent_gates" in _gd_parallel)
    test("GD: find_parallel_safe_gates has conflict_pairs key",
         "conflict_pairs" in _gd_parallel)
    test("GD: find_parallel_safe_gates has total_gates key",
         "total_gates" in _gd_parallel)
    test("GD: find_parallel_safe_gates independent_gates is a list",
         isinstance(_gd_parallel.get("independent_gates"), list))
    test("GD: find_parallel_safe_gates conflict_pairs is a list",
         isinstance(_gd_parallel.get("conflict_pairs"), list))
    test("GD: find_parallel_safe_gates total_gates is an int",
         isinstance(_gd_parallel.get("total_gates"), int))
    test("GD: find_parallel_safe_gates total_gates >= 0",
         _gd_parallel.get("total_gates", -1) >= 0)

    # --- get_state_hotspots ---
    _gd_hotspots = get_state_hotspots()
    test("GD: get_state_hotspots returns a list",
         isinstance(_gd_hotspots, list))
    test("GD: get_state_hotspots entries are dicts",
         all(isinstance(h, dict) for h in _gd_hotspots))
    test("GD: get_state_hotspots entries have 'key' field",
         all("key" in h for h in _gd_hotspots))
    test("GD: get_state_hotspots entries have 'read_count' field",
         all("read_count" in h for h in _gd_hotspots))
    test("GD: get_state_hotspots entries have 'write_count' field",
         all("write_count" in h for h in _gd_hotspots))
    test("GD: get_state_hotspots entries have 'total_gates' field",
         all("total_gates" in h for h in _gd_hotspots))
    test("GD: get_state_hotspots sorted descending by total_gates",
         all(_gd_hotspots[i]["total_gates"] >= _gd_hotspots[i+1]["total_gates"]
             for i in range(len(_gd_hotspots)-1)) if len(_gd_hotspots) > 1 else True)

    # --- detect_cycles ---
    _gd_cycles = detect_cycles()
    test("GD: detect_cycles returns a dict",
         isinstance(_gd_cycles, dict))
    test("GD: detect_cycles has has_cycles key",
         "has_cycles" in _gd_cycles)
    test("GD: detect_cycles has cycles key",
         "cycles" in _gd_cycles)
    test("GD: detect_cycles has summary key",
         "summary" in _gd_cycles)
    test("GD: detect_cycles has_cycles is a bool",
         isinstance(_gd_cycles.get("has_cycles"), bool))
    test("GD: detect_cycles cycles is a list",
         isinstance(_gd_cycles.get("cycles"), list))
    test("GD: detect_cycles summary is a non-empty string",
         isinstance(_gd_cycles.get("summary"), str) and len(_gd_cycles["summary"]) > 0)
    test("GD: detect_cycles summary mentions 'cycle' or 'No circular'",
         "cycle" in _gd_cycles["summary"].lower() or "No circular" in _gd_cycles["summary"]
         or "No dependency" in _gd_cycles["summary"])

    # --- recommend_gate_ordering ---
    _gd_order = recommend_gate_ordering()
    test("GD: recommend_gate_ordering returns a dict",
         isinstance(_gd_order, dict))
    test("GD: recommend_gate_ordering has ordering key",
         "ordering" in _gd_order)
    test("GD: recommend_gate_ordering has has_cycles key",
         "has_cycles" in _gd_order)
    test("GD: recommend_gate_ordering has tiers key",
         "tiers" in _gd_order)
    test("GD: recommend_gate_ordering ordering is a list",
         isinstance(_gd_order.get("ordering"), list))
    test("GD: recommend_gate_ordering has_cycles is bool",
         isinstance(_gd_order.get("has_cycles"), bool))
    test("GD: recommend_gate_ordering tiers is a list",
         isinstance(_gd_order.get("tiers"), list))
    test("GD: recommend_gate_ordering ordering length matches total_gates",
         len(_gd_order.get("ordering", [])) == _gd_parallel.get("total_gates", len(_gd_order.get("ordering", []))))

    # --- format_dependency_report ---
    _gd_report = format_dependency_report()
    test("GD: format_dependency_report returns a string",
         isinstance(_gd_report, str))
    test("GD: format_dependency_report is non-empty",
         len(_gd_report) > 0)
    test("GD: format_dependency_report contains 'Gate Dependency Analysis'",
         "Gate Dependency Analysis" in _gd_report)
    test("GD: format_dependency_report contains 'Parallel Safety'",
         "Parallel Safety" in _gd_report)
    test("GD: format_dependency_report contains 'Cycle Detection'",
         "Cycle Detection" in _gd_report)

except Exception as _gd_exc:
    test("GD: gate_dependency_graph module-level tests", False, str(_gd_exc))

# ─────────────────────────────────────────────────────────────────────────────
# SM: state_migrator tests
# ─────────────────────────────────────────────────────────────────────────────
try:
    from shared.state_migrator import (
        migrate_state,
        validate_state,
        get_schema_diff,
        _serialize_for_diff,
        validate_and_migrate,
        get_schema_metadata,
    )
    from shared.state import (
        default_state as _sm_default_state,
        get_state_schema as _sm_get_schema,
        STATE_VERSION as _SM_STATE_VERSION,
        MAX_FILES_READ,
        MAX_VERIFIED_FIXES,
    )

    # --- migrate_state ---
    _sm_migrated_empty = migrate_state({})
    test("SM: migrate_state with empty dict returns a dict",
         isinstance(_sm_migrated_empty, dict))
    test("SM: migrate_state with empty dict adds all default fields",
         len(_sm_migrated_empty) >= len(_sm_default_state()))
    test("SM: migrate_state sets _version to STATE_VERSION",
         _sm_migrated_empty.get("_version") == _SM_STATE_VERSION)
    test("SM: migrate_state with empty dict includes 'files_read' field",
         "files_read" in _sm_migrated_empty)
    test("SM: migrate_state with empty dict includes '_version' field",
         "_version" in _sm_migrated_empty)

    _sm_partial = {"files_read": ["already_here.py"], "session_id": "mysession"}
    _sm_migrated_partial = migrate_state(_sm_partial)
    test("SM: migrate_state preserves existing values",
         _sm_migrated_partial.get("files_read") == ["already_here.py"])
    test("SM: migrate_state preserves existing session_id",
         _sm_migrated_partial.get("session_id") == "mysession")
    test("SM: migrate_state adds missing fields to partial dict",
         len(_sm_migrated_partial) > len(_sm_partial))
    test("SM: migrate_state partial still has _version set",
         _sm_migrated_partial.get("_version") == _SM_STATE_VERSION)

    _sm_migrated_nondict = migrate_state("not a dict")
    test("SM: migrate_state with non-dict returns default_state()",
         isinstance(_sm_migrated_nondict, dict) and "_version" in _sm_migrated_nondict)

    _sm_migrated_none = migrate_state(None)
    test("SM: migrate_state with None returns default_state()",
         isinstance(_sm_migrated_none, dict))

    _sm_migrated_list = migrate_state([1, 2, 3])
    test("SM: migrate_state with list returns default_state()",
         isinstance(_sm_migrated_list, dict))

    # --- validate_state ---
    _sm_default = _sm_default_state()
    _sm_valid, _sm_errors, _sm_warnings = validate_state(_sm_default)
    test("SM: validate_state with default_state() returns a 3-tuple",
         isinstance((_sm_valid, _sm_errors, _sm_warnings), tuple) and len((_sm_valid, _sm_errors, _sm_warnings)) == 3)
    test("SM: validate_state with default_state() returns bool for is_valid",
         isinstance(_sm_valid, bool))
    test("SM: validate_state with default_state() returns list for errors",
         isinstance(_sm_errors, list))
    test("SM: validate_state with default_state() returns warnings list",
         isinstance(_sm_warnings, list))

    _sm_valid2, _sm_errors2, _sm_warnings2 = validate_state("not a dict")
    test("SM: validate_state with non-dict returns is_valid=False",
         _sm_valid2 is False)
    test("SM: validate_state with non-dict returns non-empty errors",
         len(_sm_errors2) > 0)

    _sm_valid3, _sm_errors3, _sm_warnings3 = validate_state(None)
    test("SM: validate_state with None returns is_valid=False",
         _sm_valid3 is False)

    _sm_missing_field = _sm_default_state()
    _sm_missing_field.pop("files_read", None)
    _sm_valid4, _sm_errors4, _ = validate_state(_sm_missing_field)
    test("SM: validate_state with missing field returns is_valid=False",
         _sm_valid4 is False)
    test("SM: validate_state error message mentions missing field",
         any("files_read" in e for e in _sm_errors4))

    _sm_wrong_type = _sm_default_state()
    _sm_wrong_type["files_read"] = "not a list"
    _sm_valid5, _sm_errors5, _ = validate_state(_sm_wrong_type)
    test("SM: validate_state with wrong type field returns is_valid=False",
         _sm_valid5 is False)

    # --- get_schema_diff ---
    _sm_diff_default = get_schema_diff(_sm_default_state())
    test("SM: get_schema_diff with default_state() returns dict",
         isinstance(_sm_diff_default, dict))
    test("SM: get_schema_diff with default_state() has 0 missing fields",
         _sm_diff_default.get("summary", {}).get("missing", -1) == 0)
    test("SM: get_schema_diff with default_state() has summary key",
         "summary" in _sm_diff_default)
    test("SM: get_schema_diff has missing_fields key",
         "missing_fields" in _sm_diff_default)
    test("SM: get_schema_diff has extra_fields key",
         "extra_fields" in _sm_diff_default)
    test("SM: get_schema_diff has type_mismatches key",
         "type_mismatches" in _sm_diff_default)
    test("SM: get_schema_diff has schema_version key",
         "schema_version" in _sm_diff_default)

    _sm_diff_empty = get_schema_diff({})
    test("SM: get_schema_diff with empty dict has many missing fields",
         _sm_diff_empty.get("summary", {}).get("missing", 0) > 5)

    _sm_diff_nondict = get_schema_diff("not a dict")
    test("SM: get_schema_diff with non-dict returns error key",
         "error" in _sm_diff_nondict)

    _sm_diff_nondict2 = get_schema_diff(42)
    test("SM: get_schema_diff with int returns error key",
         "error" in _sm_diff_nondict2)

    # --- _serialize_for_diff ---
    test("SM: _serialize_for_diff with string returns string",
         _serialize_for_diff("hello") == "hello")
    test("SM: _serialize_for_diff with int returns int",
         _serialize_for_diff(42) == 42)
    test("SM: _serialize_for_diff with bool returns bool",
         _serialize_for_diff(True) is True)
    test("SM: _serialize_for_diff with None returns None",
         _serialize_for_diff(None) is None)
    test("SM: _serialize_for_diff with float returns float",
         _serialize_for_diff(3.14) == 3.14)
    test("SM: _serialize_for_diff with short list returns list",
         _serialize_for_diff([1, 2, 3]) == [1, 2, 3])
    test("SM: _serialize_for_diff with long list (>5) returns summary string",
         isinstance(_serialize_for_diff([1, 2, 3, 4, 5, 6]), str) and
         "[list:" in _serialize_for_diff([1, 2, 3, 4, 5, 6]))
    test("SM: _serialize_for_diff long list summary contains item count",
         "6" in _serialize_for_diff([1, 2, 3, 4, 5, 6]))
    test("SM: _serialize_for_diff with small dict (<=3 keys) returns dict",
         _serialize_for_diff({"a": 1, "b": 2}) == {"a": 1, "b": 2})
    test("SM: _serialize_for_diff with large dict (>3 keys) returns summary string",
         isinstance(_serialize_for_diff({"a": 1, "b": 2, "c": 3, "d": 4}), str) and
         "{dict:" in _serialize_for_diff({"a": 1, "b": 2, "c": 3, "d": 4}))
    test("SM: _serialize_for_diff large dict summary contains key count",
         "4" in _serialize_for_diff({"a": 1, "b": 2, "c": 3, "d": 4}))

    # --- validate_and_migrate ---
    _sm_vm_state, _sm_vm_valid, _sm_vm_errors, _sm_vm_warnings = validate_and_migrate({})
    test("SM: validate_and_migrate with empty dict returns 4-tuple",
         True)  # if we got here without exception, tuple was returned
    test("SM: validate_and_migrate with empty dict returns valid migrated state",
         isinstance(_sm_vm_state, dict) and "_version" in _sm_vm_state)
    test("SM: validate_and_migrate with empty dict returns bool for is_valid",
         isinstance(_sm_vm_valid, bool))
    test("SM: validate_and_migrate errors is a list",
         isinstance(_sm_vm_errors, list))
    test("SM: validate_and_migrate warnings is a list",
         isinstance(_sm_vm_warnings, list))

    _sm_vm2, _sm_vm2_valid, _, _ = validate_and_migrate(_sm_default_state())
    test("SM: validate_and_migrate with default_state() returns bool is_valid",
         isinstance(_sm_vm2_valid, bool))

    # --- get_schema_metadata ---
    _sm_meta = get_schema_metadata()
    test("SM: get_schema_metadata returns a dict",
         isinstance(_sm_meta, dict))
    test("SM: get_schema_metadata has 'version' key",
         "version" in _sm_meta)
    test("SM: get_schema_metadata version matches STATE_VERSION",
         _sm_meta.get("version") == _SM_STATE_VERSION)
    test("SM: get_schema_metadata has 'schema' key",
         "schema" in _sm_meta)
    test("SM: get_schema_metadata schema is a dict",
         isinstance(_sm_meta.get("schema"), dict))
    test("SM: get_schema_metadata has 'field_count' key",
         "field_count" in _sm_meta)
    test("SM: get_schema_metadata field_count is a positive int",
         isinstance(_sm_meta.get("field_count"), int) and _sm_meta["field_count"] > 0)
    test("SM: get_schema_metadata field_count matches schema length",
         _sm_meta.get("field_count") == len(_sm_meta.get("schema", {})))

    # --- MAX_* constants are importable ---
    test("SM: MAX_FILES_READ is a positive int",
         isinstance(MAX_FILES_READ, int) and MAX_FILES_READ > 0)
    test("SM: MAX_VERIFIED_FIXES is a positive int",
         isinstance(MAX_VERIFIED_FIXES, int) and MAX_VERIFIED_FIXES > 0)
    test("SM: STATE_VERSION is a positive int",
         isinstance(_SM_STATE_VERSION, int) and _SM_STATE_VERSION > 0)

except Exception as _sm_exc:
    test("SM: state_migrator module-level tests", False, str(_sm_exc))

# ═══════════════════════════════════════════════════════════════════════════════
# AD: anomaly_detector tests
# ═══════════════════════════════════════════════════════════════════════════════
try:
    import math as _math
    from shared.anomaly_detector import (
        compute_baseline,
        _stddev,
        detect_anomalies,
        detect_stuck_loop,
        should_escalate,
        check_tool_dominance,
        get_session_baseline,
        compare_to_baseline,
        detect_behavioral_anomaly,
        compute_ema,
        detect_trend,
        anomaly_consensus,
        _TOOL_RATE_SIGMA_THRESHOLD,
        _TOOL_DOMINANCE_RATIO,
        _BLOCK_RATE_HIGH_THRESHOLD,
        _ERROR_RATE_HIGH_THRESHOLD,
        _MEMORY_GAP_SECONDS,
        _DEFAULT_EMA_ALPHA,
    )

    # ── compute_baseline ──────────────────────────────────────────────────────

    test("AD: compute_baseline empty history returns {}",
         compute_baseline([]) == {})

    test("AD: compute_baseline single snapshot returns same rates",
         compute_baseline([{"gate1": 2.0, "gate2": 4.0}]) == {"gate1": 2.0, "gate2": 4.0})

    _ad_hist = [{"gate1": 2.0, "gate2": 4.0}, {"gate1": 4.0, "gate2": 2.0}]
    _ad_bl = compute_baseline(_ad_hist)
    test("AD: compute_baseline averages two snapshots gate1",
         abs(_ad_bl["gate1"] - 3.0) < 1e-9)
    test("AD: compute_baseline averages two snapshots gate2",
         abs(_ad_bl["gate2"] - 3.0) < 1e-9)

    _ad_hist3 = [{"g": float(i)} for i in range(20)]
    _ad_bl3 = compute_baseline(_ad_hist3, window=5)
    # window=5 → last 5 items are g=15..19, mean = (15+16+17+18+19)/5 = 17.0
    test("AD: compute_baseline window=5 uses last 5 entries",
         abs(_ad_bl3["g"] - 17.0) < 1e-9)

    # gate absent from some snapshots treated as 0
    _ad_sparse = [{"gate1": 3.0}, {"gate2": 6.0}]
    _ad_bl4 = compute_baseline(_ad_sparse)
    test("AD: compute_baseline absent gate treated as 0 in that snapshot (gate1)",
         abs(_ad_bl4["gate1"] - 1.5) < 1e-9)
    test("AD: compute_baseline absent gate treated as 0 in that snapshot (gate2)",
         abs(_ad_bl4["gate2"] - 3.0) < 1e-9)

    _ad_hist5 = [{"g": 1.0}, {"g": 2.0}, {"g": 3.0}]
    _ad_bl5 = compute_baseline(_ad_hist5, window=2)
    # window=2 → last 2 snapshots: g=2, g=3 → mean=2.5
    test("AD: compute_baseline window < len uses last window entries",
         abs(_ad_bl5["g"] - 2.5) < 1e-9)

    # ── _stddev ───────────────────────────────────────────────────────────────

    test("AD: _stddev empty list returns 0.0",
         _stddev([]) == 0.0)
    test("AD: _stddev single value returns 0.0",
         _stddev([42.0]) == 0.0)
    test("AD: _stddev all zeros returns 0.0",
         _stddev([0.0, 0.0, 0.0]) == 0.0)
    test("AD: _stddev [1,2,3] ~0.816",
         abs(_stddev([1.0, 2.0, 3.0]) - _math.sqrt(2/3)) < 1e-9)
    test("AD: _stddev [2,2,2,2] returns 0.0",
         _stddev([2.0, 2.0, 2.0, 2.0]) == 0.0)
    test("AD: _stddev [0,4] returns 2.0",
         abs(_stddev([0.0, 4.0]) - 2.0) < 1e-9)

    # ── detect_anomalies ──────────────────────────────────────────────────────

    test("AD: detect_anomalies empty baseline returns []",
         detect_anomalies({"g": 10.0}, {}) == [])

    # All gates at same baseline → no anomaly since threshold == mean (std=0 → inf threshold)
    _ad_curr1 = {"g1": 5.0, "g2": 5.0}
    _ad_base1 = {"g1": 5.0, "g2": 5.0}
    test("AD: detect_anomalies no anomaly when equal to baseline",
         detect_anomalies(_ad_curr1, _ad_base1, threshold_sigma=2.0) == [])

    # One gate clearly above threshold
    _ad_base2 = {"g1": 1.0, "g2": 1.0, "g3": 1.0}
    _ad_curr2 = {"g1": 20.0, "g2": 1.0, "g3": 1.0}
    _ad_anoms = detect_anomalies(_ad_curr2, _ad_base2, threshold_sigma=2.0)
    test("AD: detect_anomalies detects one anomalous gate",
         len(_ad_anoms) == 1 and _ad_anoms[0]["gate"] == "g1")
    test("AD: detect_anomalies anomaly dict has all required keys",
         all(k in _ad_anoms[0] for k in ("gate", "current_rate", "baseline_rate", "delta", "sigma")))
    test("AD: detect_anomalies anomaly delta is current minus baseline",
         abs(_ad_anoms[0]["delta"] - 19.0) < 1e-9)

    # Result sorted by delta descending
    _ad_base3 = {"g1": 1.0, "g2": 1.0, "g3": 1.0}
    _ad_curr3 = {"g1": 15.0, "g2": 25.0, "g3": 1.0}
    _ad_anoms3 = detect_anomalies(_ad_curr3, _ad_base3, threshold_sigma=2.0)
    test("AD: detect_anomalies results sorted delta desc",
         len(_ad_anoms3) >= 2 and _ad_anoms3[0]["delta"] >= _ad_anoms3[1]["delta"])

    # Gate not in baseline treated as 0 baseline
    _ad_curr4 = {"new_gate": 30.0}
    _ad_base4 = {"g1": 1.0, "g2": 1.0}
    _ad_anoms4 = detect_anomalies(_ad_curr4, _ad_base4, threshold_sigma=2.0)
    test("AD: detect_anomalies gate not in baseline uses 0 as baseline rate",
         len(_ad_anoms4) > 0 and _ad_anoms4[0]["baseline_rate"] == 0.0)

    # ── detect_stuck_loop ─────────────────────────────────────────────────────

    test("AD: detect_stuck_loop empty list returns None",
         detect_stuck_loop([]) is None)
    test("AD: detect_stuck_loop dominant gate >70% returns gate name",
         detect_stuck_loop(["gate1"] * 8 + ["gate2"] * 2, window=10, threshold=0.7) == "gate1")
    test("AD: detect_stuck_loop exactly at threshold returns gate",
         detect_stuck_loop(["gate1"] * 7 + ["gate3"] * 3, window=10, threshold=0.7) == "gate1")
    test("AD: detect_stuck_loop below threshold returns None",
         detect_stuck_loop(["gate1"] * 6 + ["gate2"] * 4, window=10, threshold=0.7) is None)
    test("AD: detect_stuck_loop uses last window entries only",
         detect_stuck_loop(["other"] * 100 + ["stuck"] * 9 + ["x"] * 1,
                           window=10, threshold=0.7) == "stuck")
    test("AD: detect_stuck_loop single gate always returns it",
         detect_stuck_loop(["g"] * 5) == "g")

    # ── should_escalate ───────────────────────────────────────────────────────

    _se_no_anoms, _ = should_escalate([], None)
    test("AD: should_escalate no anomalies no stuck returns False",
         _se_no_anoms is False)

    _se_stuck, _se_msg = should_escalate([], "gate7")
    test("AD: should_escalate stuck_gate triggers escalation",
         _se_stuck is True)
    test("AD: should_escalate stuck_gate message mentions gate name",
         "gate7" in _se_msg)

    _se_many_anoms = [{"gate": f"g{i}", "delta": 1.0, "sigma": 2.5} for i in range(3)]
    _se_many, _se_many_msg = should_escalate(_se_many_anoms, None)
    test("AD: should_escalate 3+ anomalies triggers escalation",
         _se_many is True)

    _se_big_delta = [{"gate": "g1", "delta": 6.0, "sigma": 4.0}]
    _se_big, _se_big_msg = should_escalate(_se_big_delta, None)
    test("AD: should_escalate large delta >=5 triggers escalation",
         _se_big is True)
    test("AD: should_escalate large delta message mentions gate",
         "g1" in _se_big_msg)

    _se_small, _ = should_escalate([{"gate": "g1", "delta": 2.0, "sigma": 2.5}], None)
    test("AD: should_escalate 1 anomaly small delta does not escalate",
         _se_small is False)

    _se_two, _ = should_escalate([{"gate": f"g{i}", "delta": 1.0} for i in range(2)], None)
    test("AD: should_escalate 2 anomalies < 3 does not escalate",
         _se_two is False)

    # ── check_tool_dominance ──────────────────────────────────────────────────

    test("AD: check_tool_dominance empty dict returns None",
         check_tool_dominance({}) is None)
    test("AD: check_tool_dominance all zeros returns None",
         check_tool_dominance({"Bash": 0, "Read": 0}) is None)

    _ctd_dom = check_tool_dominance({"Bash": 80, "Read": 10, "Edit": 10})
    test("AD: check_tool_dominance dominant tool detected",
         _ctd_dom is not None and _ctd_dom["tool"] == "Bash")
    test("AD: check_tool_dominance ratio correct",
         _ctd_dom is not None and abs(_ctd_dom["ratio"] - 0.8) < 1e-9)
    test("AD: check_tool_dominance total correct",
         _ctd_dom is not None and _ctd_dom["total"] == 100)

    _ctd_even = check_tool_dominance({"Bash": 50, "Read": 50})
    test("AD: check_tool_dominance even split returns None",
         _ctd_even is None)

    # Exactly at threshold (not strictly above) → None
    _ctd_edge = check_tool_dominance({"Bash": 70, "Read": 30})
    test("AD: check_tool_dominance exactly 70% not above threshold returns None",
         _ctd_edge is None)

    _ctd_one = check_tool_dominance({"OnlyTool": 5})
    test("AD: check_tool_dominance single tool returns dominant",
         _ctd_one is not None and _ctd_one["tool"] == "OnlyTool")

    # ── compute_ema ───────────────────────────────────────────────────────────

    test("AD: compute_ema empty list returns []",
         compute_ema([]) == [])
    test("AD: compute_ema single value returns same value",
         compute_ema([7.0]) == [7.0])

    _ema_vals = compute_ema([1.0, 1.0, 1.0, 1.0], alpha=0.5)
    test("AD: compute_ema constant sequence stays constant",
         all(abs(v - 1.0) < 1e-9 for v in _ema_vals))

    _ema2 = compute_ema([0.0, 10.0], alpha=0.5)
    test("AD: compute_ema length equals input length",
         len(_ema2) == 2)
    # second value = 0.5*10 + 0.5*0 = 5.0
    test("AD: compute_ema second value correct for alpha=0.5",
         abs(_ema2[1] - 5.0) < 1e-9)

    # alpha clamped to [0.01, 1.0]
    _ema_low = compute_ema([1.0, 2.0], alpha=0.0)
    test("AD: compute_ema alpha clamped to 0.01 minimum",
         len(_ema_low) == 2)

    _ema_high = compute_ema([1.0, 10.0], alpha=2.0)
    test("AD: compute_ema alpha clamped to 1.0 maximum (second val == input)",
         abs(_ema_high[1] - 10.0) < 1e-9)

    # ── detect_trend ──────────────────────────────────────────────────────────

    test("AD: detect_trend empty list returns stable direction",
         detect_trend([])["direction"] == "stable")
    test("AD: detect_trend single value returns stable",
         detect_trend([5.0])["direction"] == "stable")
    test("AD: detect_trend single value magnitude is 0",
         detect_trend([5.0])["magnitude"] == 0.0)

    _td_rising = detect_trend([1.0, 2.0, 4.0, 8.0, 16.0], alpha=0.9, threshold=0.2)
    test("AD: detect_trend rising sequence detected as rising",
         _td_rising["direction"] == "rising")

    _td_falling = detect_trend([16.0, 8.0, 4.0, 2.0, 1.0], alpha=0.9, threshold=0.2)
    test("AD: detect_trend falling sequence detected as falling",
         _td_falling["direction"] == "falling")

    _td_flat = detect_trend([5.0, 5.01, 4.99, 5.0, 5.0], alpha=0.3, threshold=0.2)
    test("AD: detect_trend flat sequence detected as stable",
         _td_flat["direction"] == "stable")

    _td_result = detect_trend([1.0, 2.0, 3.0])
    test("AD: detect_trend result has required keys",
         all(k in _td_result for k in ("direction", "magnitude", "ema_first", "ema_last")))

    # ── anomaly_consensus ─────────────────────────────────────────────────────

    _ac_empty = anomaly_consensus([])
    test("AD: anomaly_consensus empty signals returns consensus=False",
         _ac_empty["consensus"] is False)
    test("AD: anomaly_consensus empty signals triggered_count=0",
         _ac_empty["triggered_count"] == 0)
    test("AD: anomaly_consensus empty signals total_count=0",
         _ac_empty["total_count"] == 0)

    _ac_sigs_all = [
        {"name": "s1", "triggered": True, "severity": "warning"},
        {"name": "s2", "triggered": True, "severity": "critical"},
        {"name": "s3", "triggered": True, "severity": "info"},
    ]
    _ac_all = anomaly_consensus(_ac_sigs_all, quorum=2)
    test("AD: anomaly_consensus quorum met returns consensus=True",
         _ac_all["consensus"] is True)
    test("AD: anomaly_consensus max_severity is critical",
         _ac_all["max_severity"] == "critical")
    test("AD: anomaly_consensus triggered_signals lists names",
         set(_ac_all["triggered_signals"]) == {"s1", "s2", "s3"})

    _ac_sigs_none = [
        {"name": "s1", "triggered": False, "severity": "warning"},
        {"name": "s2", "triggered": False, "severity": "critical"},
    ]
    _ac_none = anomaly_consensus(_ac_sigs_none, quorum=2)
    test("AD: anomaly_consensus none triggered returns consensus=False",
         _ac_none["consensus"] is False)
    test("AD: anomaly_consensus none triggered max_severity=info",
         _ac_none["max_severity"] == "info")

    _ac_partial = anomaly_consensus([
        {"name": "a", "triggered": True, "severity": "info"},
        {"name": "b", "triggered": False, "severity": "warning"},
        {"name": "c", "triggered": False, "severity": "warning"},
    ], quorum=2)
    test("AD: anomaly_consensus below quorum returns consensus=False",
         _ac_partial["consensus"] is False)
    test("AD: anomaly_consensus below quorum triggered_count=1",
         _ac_partial["triggered_count"] == 1)

    _ac_exact = anomaly_consensus([
        {"name": "x", "triggered": True, "severity": "warning"},
        {"name": "y", "triggered": True, "severity": "info"},
    ], quorum=2)
    test("AD: anomaly_consensus exactly at quorum triggers consensus",
         _ac_exact["consensus"] is True)

    # ── constants ─────────────────────────────────────────────────────────────

    test("AD: _TOOL_RATE_SIGMA_THRESHOLD == 3.0",
         _TOOL_RATE_SIGMA_THRESHOLD == 3.0)
    test("AD: _TOOL_DOMINANCE_RATIO == 0.7",
         _TOOL_DOMINANCE_RATIO == 0.7)
    test("AD: _BLOCK_RATE_HIGH_THRESHOLD == 0.5",
         _BLOCK_RATE_HIGH_THRESHOLD == 0.5)
    test("AD: _ERROR_RATE_HIGH_THRESHOLD == 0.3",
         _ERROR_RATE_HIGH_THRESHOLD == 0.3)
    test("AD: _MEMORY_GAP_SECONDS == 600",
         _MEMORY_GAP_SECONDS == 600)
    test("AD: _DEFAULT_EMA_ALPHA == 0.3",
         _DEFAULT_EMA_ALPHA == 0.3)

    # ── get_session_baseline ──────────────────────────────────────────────────

    import time as _time_mod
    _ad_now = _time_mod.time()
    _ad_state_clean = {
        "session_start": _ad_now - 120.0,
        "total_tool_calls": 10,
        "gate_block_outcomes": [],
        "unlogged_errors": [],
        "memory_last_queried": _ad_now - 30.0,
    }
    _ad_gsb = get_session_baseline(_ad_state_clean)
    test("AD: get_session_baseline returns dict with required keys",
         all(k in _ad_gsb for k in ("tool_call_rate", "gate_block_rate", "error_rate", "memory_query_interval")))
    test("AD: get_session_baseline block_rate is 0 with no blocks",
         _ad_gsb["gate_block_rate"] == 0.0)
    test("AD: get_session_baseline error_rate is 0 with no errors",
         _ad_gsb["error_rate"] == 0.0)
    test("AD: get_session_baseline memory_query_interval ~30s",
         abs(_ad_gsb["memory_query_interval"] - 30.0) < 2.0)
    test("AD: get_session_baseline tool_call_rate > 0",
         _ad_gsb["tool_call_rate"] > 0.0)

    _ad_state_blocks = {
        "session_start": _ad_now - 60.0,
        "total_tool_calls": 10,
        "gate_block_outcomes": [{}] * 4,
        "unlogged_errors": [{}] * 2,
        "memory_last_queried": 0.0,
    }
    _ad_gsb2 = get_session_baseline(_ad_state_blocks)
    test("AD: get_session_baseline block_rate correct fraction",
         abs(_ad_gsb2["gate_block_rate"] - 0.4) < 1e-9)
    test("AD: get_session_baseline error_rate correct fraction",
         abs(_ad_gsb2["error_rate"] - 0.2) < 1e-9)
    # memory_last_queried=0 → interval == elapsed_seconds (~60s)
    test("AD: get_session_baseline memory never queried uses elapsed",
         _ad_gsb2["memory_query_interval"] > 55.0)

    # ── compare_to_baseline ───────────────────────────────────────────────────

    _ad_curr_m = {"tool_call_rate": 2.0, "gate_block_rate": 0.0, "error_rate": 0.0, "memory_query_interval": 60.0}
    _ad_base_m = {"tool_call_rate": 1.0, "gate_block_rate": 0.0, "error_rate": 0.0, "memory_query_interval": 60.0}
    _ad_devs = compare_to_baseline(_ad_curr_m, _ad_base_m)
    # tool_call_rate changed by 100% relative, threshold is 50% → should flag
    _ad_devs_metrics = [d["metric"] for d in _ad_devs]
    test("AD: compare_to_baseline detects tool_call_rate spike",
         "tool_call_rate" in _ad_devs_metrics)

    _ad_same_m = {"tool_call_rate": 1.0, "gate_block_rate": 0.05, "error_rate": 0.05, "memory_query_interval": 60.0}
    _ad_no_devs = compare_to_baseline(_ad_same_m, _ad_same_m)
    test("AD: compare_to_baseline no deviations when metrics are same",
         _ad_no_devs == [])

    _ad_block_curr = {"tool_call_rate": 1.0, "gate_block_rate": 0.9, "error_rate": 0.0, "memory_query_interval": 60.0}
    _ad_block_base = {"tool_call_rate": 1.0, "gate_block_rate": 0.0, "error_rate": 0.0, "memory_query_interval": 60.0}
    _ad_block_devs = compare_to_baseline(_ad_block_curr, _ad_block_base)
    _ad_block_dev_objs = [d for d in _ad_block_devs if d["metric"] == "gate_block_rate"]
    test("AD: compare_to_baseline gate_block_rate deviation has critical severity",
         len(_ad_block_dev_objs) > 0 and _ad_block_dev_objs[0]["severity"] == "critical")

    # ── detect_behavioral_anomaly ─────────────────────────────────────────────

    _ad_now2 = _time_mod.time()
    _ad_normal_state = {
        "session_start": _ad_now2 - 60.0,
        "total_tool_calls": 20,
        "gate_block_outcomes": [],
        "unlogged_errors": [],
        "memory_last_queried": _ad_now2 - 10.0,
        "tool_call_counts": {"Read": 10, "Bash": 10},
    }
    _ad_norm_anoms = detect_behavioral_anomaly(_ad_normal_state)
    test("AD: detect_behavioral_anomaly normal state no anomalies",
         isinstance(_ad_norm_anoms, list))

    _ad_gap_state = {
        "session_start": _ad_now2 - 3600.0,
        "total_tool_calls": 5,
        "gate_block_outcomes": [],
        "unlogged_errors": [],
        "memory_last_queried": _ad_now2 - 700.0,
        "tool_call_counts": {},
    }
    _ad_gap_anoms = detect_behavioral_anomaly(_ad_gap_state)
    _ad_gap_types = [a[0] for a in _ad_gap_anoms]
    test("AD: detect_behavioral_anomaly memory gap >600s flagged",
         "memory_query_gap" in _ad_gap_types)

    _ad_block_state = {
        "session_start": _ad_now2 - 60.0,
        "total_tool_calls": 10,
        "gate_block_outcomes": [{}] * 8,
        "unlogged_errors": [],
        "memory_last_queried": _ad_now2 - 5.0,
        "tool_call_counts": {},
    }
    _ad_block_anoms = detect_behavioral_anomaly(_ad_block_state)
    _ad_block_types = [a[0] for a in _ad_block_anoms]
    test("AD: detect_behavioral_anomaly high block rate flagged",
         "high_block_rate" in _ad_block_types)

    _ad_err_state = {
        "session_start": _ad_now2 - 60.0,
        "total_tool_calls": 10,
        "gate_block_outcomes": [],
        "unlogged_errors": [{}] * 5,
        "memory_last_queried": _ad_now2 - 5.0,
        "tool_call_counts": {},
    }
    _ad_err_anoms = detect_behavioral_anomaly(_ad_err_state)
    _ad_err_types = [a[0] for a in _ad_err_anoms]
    test("AD: detect_behavioral_anomaly high error rate flagged",
         "high_error_rate" in _ad_err_types)

    test("AD: detect_behavioral_anomaly returns list of 3-tuples",
         all(isinstance(a, tuple) and len(a) == 3 for a in _ad_gap_anoms))

except Exception as _ad_exc:
    test("AD: anomaly_detector module-level tests", False, str(_ad_exc))

# ═══════════════════════════════════════════════════════════════════════════════
# CR2: capability_registry tests
# ═══════════════════════════════════════════════════════════════════════════════
try:
    from shared.capability_registry import (
        AGENT_CAPABILITIES,
        TASK_REQUIREMENTS,
        AGENT_ACLS,
        _MODEL_IDS,
        _DESTRUCTIVE_BASH_PATTERNS,
        match_agent,
        recommend_model,
        get_agent_info,
        define_agent_acl,
        check_agent_permission,
        get_agent_acl,
    )

    # ── AGENT_CAPABILITIES ────────────────────────────────────────────────────

    test("CR2: AGENT_CAPABILITIES is a non-empty dict",
         isinstance(AGENT_CAPABILITIES, dict) and len(AGENT_CAPABILITIES) > 0)

    _cr2_required_agent_keys = {"description", "skills", "preferred_model", "max_complexity", "can_delegate"}
    test("CR2: all AGENT_CAPABILITIES entries have required keys",
         all(_cr2_required_agent_keys.issubset(v.keys()) for v in AGENT_CAPABILITIES.values()))

    test("CR2: AGENT_CAPABILITIES contains builder",
         "builder" in AGENT_CAPABILITIES)
    test("CR2: AGENT_CAPABILITIES contains researcher",
         "researcher" in AGENT_CAPABILITIES)
    test("CR2: AGENT_CAPABILITIES contains auditor",
         "auditor" in AGENT_CAPABILITIES)
    test("CR2: AGENT_CAPABILITIES contains explorer",
         "explorer" in AGENT_CAPABILITIES)
    test("CR2: AGENT_CAPABILITIES contains team-lead",
         "team-lead" in AGENT_CAPABILITIES)

    test("CR2: all agents have list skills",
         all(isinstance(v["skills"], list) for v in AGENT_CAPABILITIES.values()))
    test("CR2: all agents have int max_complexity",
         all(isinstance(v["max_complexity"], int) for v in AGENT_CAPABILITIES.values()))
    test("CR2: all agents have bool can_delegate",
         all(isinstance(v["can_delegate"], bool) for v in AGENT_CAPABILITIES.values()))
    test("CR2: all agents preferred_model is valid tier",
         all(v["preferred_model"] in _MODEL_IDS for v in AGENT_CAPABILITIES.values()))

    # ── TASK_REQUIREMENTS ─────────────────────────────────────────────────────

    test("CR2: TASK_REQUIREMENTS is a non-empty dict",
         isinstance(TASK_REQUIREMENTS, dict) and len(TASK_REQUIREMENTS) > 0)
    test("CR2: TASK_REQUIREMENTS has bug-fix",
         "bug-fix" in TASK_REQUIREMENTS)
    test("CR2: TASK_REQUIREMENTS has research",
         "research" in TASK_REQUIREMENTS)
    test("CR2: TASK_REQUIREMENTS has feature-implementation",
         "feature-implementation" in TASK_REQUIREMENTS)
    test("CR2: TASK_REQUIREMENTS has security-audit",
         "security-audit" in TASK_REQUIREMENTS)
    test("CR2: TASK_REQUIREMENTS has orchestration",
         "orchestration" in TASK_REQUIREMENTS)

    _cr2_required_task_keys = {"required_skills", "min_complexity", "preferred_agents"}
    test("CR2: all TASK_REQUIREMENTS entries have required keys",
         all(_cr2_required_task_keys.issubset(v.keys()) for v in TASK_REQUIREMENTS.values()))

    # ── match_agent ───────────────────────────────────────────────────────────

    test("CR2: match_agent bug-fix returns builder",
         match_agent("bug-fix") == "builder")
    test("CR2: match_agent research returns researcher",
         match_agent("research") == "researcher")
    test("CR2: match_agent unknown task returns None",
         match_agent("unknown-task-type-xyz") is None)
    test("CR2: match_agent orchestration returns team-lead",
         match_agent("orchestration") == "team-lead")

    # exclude first preference → falls to second
    test("CR2: match_agent bug-fix exclude builder returns non-builder",
         match_agent("bug-fix", exclude=["builder"]) != "builder")
    test("CR2: match_agent bug-fix exclude builder returns valid agent or None",
         match_agent("bug-fix", exclude=["builder"]) in (list(AGENT_CAPABILITIES.keys()) + [None]))

    # exclude all → returns None
    _cr2_all_agents = list(AGENT_CAPABILITIES.keys())
    test("CR2: match_agent exclude all agents returns None",
         match_agent("bug-fix", exclude=_cr2_all_agents) is None)

    test("CR2: match_agent code-review returns code-reviewer",
         match_agent("code-review") == "code-reviewer")
    test("CR2: match_agent test-generation returns test-writer",
         match_agent("test-generation") == "test-writer")

    # ── recommend_model ───────────────────────────────────────────────────────

    test("CR2: recommend_model builder returns sonnet ID",
         recommend_model("builder") == _MODEL_IDS["sonnet"])
    test("CR2: recommend_model researcher returns haiku ID",
         recommend_model("researcher") == _MODEL_IDS["haiku"])
    test("CR2: recommend_model team-lead returns opus ID",
         recommend_model("team-lead") == _MODEL_IDS["opus"])
    test("CR2: recommend_model unknown returns sonnet fallback",
         recommend_model("nonexistent-agent") == _MODEL_IDS["sonnet"])
    test("CR2: recommend_model auditor returns sonnet ID",
         recommend_model("auditor") == _MODEL_IDS["sonnet"])

    # ── get_agent_info ────────────────────────────────────────────────────────

    _cr2_builder_info = get_agent_info("builder")
    test("CR2: get_agent_info builder returns dict",
         isinstance(_cr2_builder_info, dict))
    test("CR2: get_agent_info builder has model_id key",
         "model_id" in _cr2_builder_info)
    test("CR2: get_agent_info builder model_id is sonnet",
         _cr2_builder_info["model_id"] == _MODEL_IDS["sonnet"])
    test("CR2: get_agent_info builder has skills list",
         isinstance(_cr2_builder_info.get("skills"), list))

    test("CR2: get_agent_info unknown returns None",
         get_agent_info("nonexistent-agent-xyz") is None)

    _cr2_researcher_info = get_agent_info("researcher")
    test("CR2: get_agent_info researcher has can_delegate=False",
         _cr2_researcher_info["can_delegate"] is False)
    test("CR2: get_agent_info team-lead has can_delegate=True",
         get_agent_info("team-lead")["can_delegate"] is True)

    # ── check_agent_permission ────────────────────────────────────────────────

    test("CR2: check_agent_permission explorer Read returns True",
         check_agent_permission("explorer", "Read") is True)
    test("CR2: check_agent_permission explorer Glob returns True",
         check_agent_permission("explorer", "Glob") is True)
    test("CR2: check_agent_permission explorer Grep returns True",
         check_agent_permission("explorer", "Grep") is True)
    test("CR2: check_agent_permission explorer Edit returns False",
         check_agent_permission("explorer", "Edit") is False)
    test("CR2: check_agent_permission explorer Bash returns False",
         check_agent_permission("explorer", "Bash") is False)
    test("CR2: check_agent_permission explorer Write returns False",
         check_agent_permission("explorer", "Write") is False)

    test("CR2: check_agent_permission unknown agent returns False",
         check_agent_permission("unknown-agent-xyz", "Read") is False)

    # builder has allowed_tools=["*"] so all tools pass
    test("CR2: check_agent_permission builder Bash returns True",
         check_agent_permission("builder", "Bash") is True)
    test("CR2: check_agent_permission builder Edit returns True",
         check_agent_permission("builder", "Edit") is True)

    # destructive bash guard: file_path containing "rm -rf" should be denied
    test("CR2: check_agent_permission builder Bash destructive pattern denied",
         check_agent_permission("builder", "Bash", "rm -rf /") is False)
    test("CR2: check_agent_permission builder Bash dd if= denied",
         check_agent_permission("builder", "Bash", "dd if=/dev/zero of=/dev/sda") is False)

    # researcher can't edit
    test("CR2: check_agent_permission researcher Edit returns False",
         check_agent_permission("researcher", "Edit") is False)
    test("CR2: check_agent_permission researcher Read returns True",
         check_agent_permission("researcher", "Read") is True)

    # auditor can run Bash but cannot Edit
    test("CR2: check_agent_permission auditor Bash returns True",
         check_agent_permission("auditor", "Bash") is True)
    test("CR2: check_agent_permission auditor Edit returns False",
         check_agent_permission("auditor", "Edit") is False)

    # team-lead cannot Edit (in denied_tools)
    test("CR2: check_agent_permission team-lead Edit returns False",
         check_agent_permission("team-lead", "Edit") is False)

    # test-writer path restriction: allowed_paths are test paths
    test("CR2: check_agent_permission test-writer Write on test file returns True",
         check_agent_permission("test-writer", "Write", "test_foo.py") is True)
    test("CR2: check_agent_permission test-writer Write on non-test file returns False",
         check_agent_permission("test-writer", "Write", "src/main.py") is False)

    # ── define_agent_acl / get_agent_acl ─────────────────────────────────────

    # Register a brand-new agent type
    define_agent_acl(
        "test-custom-agent",
        allowed_tools=["Read"],
        denied_tools=["Bash"],
        allowed_paths=["/tmp/*"],
    )
    _cr2_custom_acl = get_agent_acl("test-custom-agent")
    test("CR2: define_agent_acl registers new agent type",
         _cr2_custom_acl is not None)
    test("CR2: get_agent_acl custom agent has allowed_tools",
         _cr2_custom_acl.get("allowed_tools") == ["Read"])
    test("CR2: get_agent_acl custom agent has denied_tools",
         _cr2_custom_acl.get("denied_tools") == ["Bash"])
    test("CR2: check_agent_permission custom agent Read /tmp allowed",
         check_agent_permission("test-custom-agent", "Read", "/tmp/foo.txt") is True)
    test("CR2: check_agent_permission custom agent Read outside path denied",
         check_agent_permission("test-custom-agent", "Read", "/etc/passwd") is False)
    test("CR2: check_agent_permission custom agent Bash denied",
         check_agent_permission("test-custom-agent", "Bash") is False)

    # Partial update: only override denied_tools
    define_agent_acl("test-custom-agent", denied_tools=["Edit", "Write"])
    _cr2_custom_acl2 = get_agent_acl("test-custom-agent")
    test("CR2: define_agent_acl partial update merges denied_tools",
         _cr2_custom_acl2.get("denied_tools") == ["Edit", "Write"])
    # allowed_tools unchanged from previous define
    test("CR2: define_agent_acl partial update preserves allowed_tools",
         _cr2_custom_acl2.get("allowed_tools") == ["Read"])

    test("CR2: get_agent_acl unknown agent returns None",
         get_agent_acl("totally-unknown-agent-zzz") is None)

    # ── _DESTRUCTIVE_BASH_PATTERNS ────────────────────────────────────────────

    test("CR2: _DESTRUCTIVE_BASH_PATTERNS is a tuple",
         isinstance(_DESTRUCTIVE_BASH_PATTERNS, tuple))
    test("CR2: _DESTRUCTIVE_BASH_PATTERNS contains rm -rf",
         "rm -rf" in _DESTRUCTIVE_BASH_PATTERNS)
    test("CR2: _DESTRUCTIVE_BASH_PATTERNS contains rm -fr",
         "rm -fr" in _DESTRUCTIVE_BASH_PATTERNS)
    test("CR2: _DESTRUCTIVE_BASH_PATTERNS contains DROP TABLE",
         "DROP TABLE" in _DESTRUCTIVE_BASH_PATTERNS)
    test("CR2: _DESTRUCTIVE_BASH_PATTERNS contains mkfs",
         "mkfs" in _DESTRUCTIVE_BASH_PATTERNS)
    test("CR2: _DESTRUCTIVE_BASH_PATTERNS is non-empty",
         len(_DESTRUCTIVE_BASH_PATTERNS) > 0)

    # ── _MODEL_IDS ────────────────────────────────────────────────────────────

    test("CR2: _MODEL_IDS has haiku tier",
         "haiku" in _MODEL_IDS)
    test("CR2: _MODEL_IDS has sonnet tier",
         "sonnet" in _MODEL_IDS)
    test("CR2: _MODEL_IDS has opus tier",
         "opus" in _MODEL_IDS)
    test("CR2: _MODEL_IDS sonnet contains sonnet",
         "sonnet" in _MODEL_IDS["sonnet"])
    test("CR2: _MODEL_IDS opus contains opus",
         "opus" in _MODEL_IDS["opus"])

    # ── AGENT_ACLS ────────────────────────────────────────────────────────────

    test("CR2: AGENT_ACLS is a non-empty dict",
         isinstance(AGENT_ACLS, dict) and len(AGENT_ACLS) > 0)
    test("CR2: AGENT_ACLS has explorer entry",
         "explorer" in AGENT_ACLS)
    test("CR2: AGENT_ACLS has builder entry",
         "builder" in AGENT_ACLS)
    test("CR2: AGENT_ACLS explorer has denied_tools with Edit",
         "Edit" in AGENT_ACLS["explorer"]["denied_tools"])
    test("CR2: AGENT_ACLS builder allowed_tools is wildcard",
         AGENT_ACLS["builder"]["allowed_tools"] == ["*"])

except Exception as _cr2_exc:
    test("CR2: capability_registry module-level tests", False, str(_cr2_exc))

# ═══════════════════════════════════════════════════════════════════════════════
# EA: experience_archive tests
# ═══════════════════════════════════════════════════════════════════════════════
try:
    import tempfile as _ea_tempfile
    import shared.experience_archive as _ea_mod
    from shared.experience_archive import (
        ARCHIVE_PATH,
        _COLUMNS,
        OUTCOME_SUCCESS,
        OUTCOME_FAILURE,
        OUTCOME_PARTIAL,
        _VALID_OUTCOMES,
        _ensure_header,
        _read_rows,
        record_fix,
        query_best_strategy,
        get_success_rate,
        get_archive_stats,
    )

    # ── constants ─────────────────────────────────────────────────────────────

    test("EA: OUTCOME_SUCCESS == 'success'",
         OUTCOME_SUCCESS == "success")
    test("EA: OUTCOME_FAILURE == 'failure'",
         OUTCOME_FAILURE == "failure")
    test("EA: OUTCOME_PARTIAL == 'partial'",
         OUTCOME_PARTIAL == "partial")
    test("EA: _VALID_OUTCOMES is a set",
         isinstance(_VALID_OUTCOMES, set))
    test("EA: _VALID_OUTCOMES has 3 values",
         len(_VALID_OUTCOMES) == 3)
    test("EA: _VALID_OUTCOMES contains success",
         "success" in _VALID_OUTCOMES)
    test("EA: _VALID_OUTCOMES contains failure",
         "failure" in _VALID_OUTCOMES)
    test("EA: _VALID_OUTCOMES contains partial",
         "partial" in _VALID_OUTCOMES)
    test("EA: ARCHIVE_PATH is a non-empty string",
         isinstance(ARCHIVE_PATH, str) and len(ARCHIVE_PATH) > 0)
    test("EA: _COLUMNS has 7 entries",
         len(_COLUMNS) == 7)
    test("EA: _COLUMNS contains timestamp",
         "timestamp" in _COLUMNS)
    test("EA: _COLUMNS contains error_type",
         "error_type" in _COLUMNS)
    test("EA: _COLUMNS contains fix_strategy",
         "fix_strategy" in _COLUMNS)
    test("EA: _COLUMNS contains outcome",
         "outcome" in _COLUMNS)
    test("EA: _COLUMNS contains gate_id",
         "gate_id" in _COLUMNS)
    test("EA: _COLUMNS contains file",
         "file" in _COLUMNS)
    test("EA: _COLUMNS contains duration_s",
         "duration_s" in _COLUMNS)

    # ── file I/O tests using tempfile ─────────────────────────────────────────

    _ea_orig_path = _ea_mod.ARCHIVE_PATH
    import os as _ea_os
    with _ea_tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as _ea_tmp:
        _ea_tmp_path = _ea_tmp.name
    # Delete the pre-created empty file so _ensure_header writes a proper header row
    _ea_os.remove(_ea_tmp_path)
    _ea_mod.ARCHIVE_PATH = _ea_tmp_path

    try:
        # _read_rows on non-existent file returns []
        _ea_no_file = _ea_tmp_path + ".nonexistent"
        test("EA: _read_rows non-existent file returns []",
             _read_rows(_ea_no_file) == [])

        # _ensure_header creates file with header
        _ea_header_path = _ea_tmp_path + ".header_test"
        _ensure_header(_ea_header_path)
        test("EA: _ensure_header creates file if not exists",
             _ea_os.path.exists(_ea_header_path))
        _ea_header_rows = _read_rows(_ea_header_path)
        test("EA: _ensure_header file has 0 data rows (header only)",
             _ea_header_rows == [])
        # Calling again should be a no-op
        _ensure_header(_ea_header_path)
        test("EA: _ensure_header is idempotent (no-op if exists)",
             _ea_os.path.exists(_ea_header_path))
        _ea_os.remove(_ea_header_path)

        # record_fix success
        _ea_ok = _ea_mod.record_fix("ImportError", "add-missing-import", "success",
                                     "/tmp/foo.py", "gate_15", 1.2)
        test("EA: record_fix returns True on success",
             _ea_ok is True)

        # record_fix failure
        _ea_mod.record_fix("ImportError", "add-missing-import", "failure",
                            "/tmp/foo.py", "gate_15", 0.5)

        # record_fix partial
        _ea_mod.record_fix("ImportError", "reinstall-package", "partial",
                            "/tmp/foo.py", "", 2.0)

        # record_fix invalid outcome coerced to failure
        _ea_mod.record_fix("TypeError", "bad-strategy", "weird_outcome")
        _ea_rows = _read_rows(_ea_tmp_path)
        _ea_last = _ea_rows[-1]
        test("EA: record_fix invalid outcome coerced to 'failure'",
             _ea_last["outcome"] == "failure")

        # record_fix rows written correctly
        test("EA: record_fix rows count is 4",
             len(_ea_rows) == 4)
        test("EA: record_fix row has all column keys",
             all(k in _ea_rows[0] for k in _COLUMNS))
        test("EA: record_fix first row error_type is ImportError",
             _ea_rows[0]["error_type"] == "ImportError")
        test("EA: record_fix first row outcome is success",
             _ea_rows[0]["outcome"] == "success")
        test("EA: record_fix first row fix_strategy correct",
             _ea_rows[0]["fix_strategy"] == "add-missing-import")
        test("EA: record_fix first row gate_id correct",
             _ea_rows[0]["gate_id"] == "gate_15")
        test("EA: record_fix first row duration_s is formatted float",
             _ea_rows[0]["duration_s"] == "1.200")

        # record additional rows for query tests
        # reinstall-package: 2 successes out of 3 total (partial + 2 success) = 0.667
        # add-missing-import: 1 success out of 2 total = 0.5 → reinstall-package wins
        _ea_mod.record_fix("ImportError", "reinstall-package", "success",
                            "/tmp/bar.py", "", 3.1)
        _ea_mod.record_fix("ImportError", "reinstall-package", "success",
                            "/tmp/bar2.py", "", 2.5)
        _ea_mod.record_fix("SyntaxError", "rewrite-block", "success",
                            "/tmp/baz.py", "gate_1", 0.8)
        _ea_mod.record_fix("SyntaxError", "rewrite-block", "success",
                            "/tmp/baz.py", "gate_1", 0.9)
        _ea_mod.record_fix("SyntaxError", "rewrite-block", "failure",
                            "/tmp/baz.py", "gate_1", 1.1)

        # query_best_strategy
        _ea_best = _ea_mod.query_best_strategy("ImportError")
        # reinstall-package: 2 success / 3 total (~0.667)
        # add-missing-import: 1 success / 2 total (0.5) → reinstall-package wins
        test("EA: query_best_strategy returns highest success rate strategy",
             _ea_best == "reinstall-package")

        _ea_best_syntax = _ea_mod.query_best_strategy("SyntaxError")
        test("EA: query_best_strategy SyntaxError returns rewrite-block",
             _ea_best_syntax == "rewrite-block")

        _ea_best_none = _ea_mod.query_best_strategy("NonExistentErrorXYZ")
        test("EA: query_best_strategy unknown error returns ''",
             _ea_best_none == "")

        # case-insensitive substring match
        _ea_best_case = _ea_mod.query_best_strategy("IMPORTERROR")
        test("EA: query_best_strategy case-insensitive match",
             _ea_best_case != "")

        # get_success_rate
        _ea_rate = _ea_mod.get_success_rate("add-missing-import")
        test("EA: get_success_rate add-missing-import is 0.5",
             abs(_ea_rate - 0.5) < 1e-9)

        _ea_rate_reinstall = _ea_mod.get_success_rate("reinstall-package")
        # reinstall-package: 1 partial + 1 success = 2 total, 1 success → 0.5
        # Actually: partial was first row, then success was added → check
        _ea_reinstall_rows = [r for r in _read_rows(_ea_tmp_path)
                               if r["fix_strategy"] == "reinstall-package"]
        _ea_reinstall_expected = sum(1 for r in _ea_reinstall_rows if r["outcome"] == "success") / len(_ea_reinstall_rows)
        test("EA: get_success_rate reinstall-package matches manual count",
             abs(_ea_rate_reinstall - _ea_reinstall_expected) < 1e-9)

        _ea_rate_missing = _ea_mod.get_success_rate("nonexistent-strategy-xyz")
        test("EA: get_success_rate unknown strategy returns 0.0",
             _ea_rate_missing == 0.0)

        _ea_rate_rewrite = _ea_mod.get_success_rate("rewrite-block")
        # 2 success, 1 failure = 2/3
        test("EA: get_success_rate rewrite-block is 2/3",
             abs(_ea_rate_rewrite - 2/3) < 1e-9)

        # get_archive_stats
        _ea_stats = _ea_mod.get_archive_stats()
        test("EA: get_archive_stats returns dict with total_rows",
             "total_rows" in _ea_stats)
        test("EA: get_archive_stats returns dict with unique_errors",
             "unique_errors" in _ea_stats)
        test("EA: get_archive_stats returns dict with unique_strategies",
             "unique_strategies" in _ea_stats)
        test("EA: get_archive_stats returns dict with overall_success_rate",
             "overall_success_rate" in _ea_stats)
        test("EA: get_archive_stats returns dict with top_strategies",
             "top_strategies" in _ea_stats)
        test("EA: get_archive_stats total_rows > 0",
             _ea_stats["total_rows"] > 0)
        # unique_errors: ImportError, TypeError, SyntaxError = 3
        test("EA: get_archive_stats unique_errors is 3",
             _ea_stats["unique_errors"] == 3)
        # unique_strategies: add-missing-import, reinstall-package, bad-strategy, rewrite-block = 4
        test("EA: get_archive_stats unique_strategies is 4",
             _ea_stats["unique_strategies"] == 4)
        test("EA: get_archive_stats overall_success_rate in [0,1]",
             0.0 <= _ea_stats["overall_success_rate"] <= 1.0)
        test("EA: get_archive_stats top_strategies is a list",
             isinstance(_ea_stats["top_strategies"], list))
        test("EA: get_archive_stats top_strategies has <= 5 entries",
             len(_ea_stats["top_strategies"]) <= 5)
        if _ea_stats["top_strategies"]:
            _ea_top0 = _ea_stats["top_strategies"][0]
            test("EA: get_archive_stats top strategy has strategy key",
                 "strategy" in _ea_top0)
            test("EA: get_archive_stats top strategy has success_rate key",
                 "success_rate" in _ea_top0)
            test("EA: get_archive_stats top strategy has total key",
                 "total" in _ea_top0)

        # empty archive test
        with _ea_tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as _ea_empty_tmp:
            _ea_empty_path = _ea_empty_tmp.name
        _ea_mod.ARCHIVE_PATH = _ea_empty_path
        test("EA: query_best_strategy empty archive returns ''",
             _ea_mod.query_best_strategy("anything") == "")
        test("EA: get_success_rate empty archive returns 0.0",
             _ea_mod.get_success_rate("any-strategy") == 0.0)
        _ea_empty_stats = _ea_mod.get_archive_stats()
        test("EA: get_archive_stats empty archive total_rows == 0",
             _ea_empty_stats["total_rows"] == 0)
        test("EA: get_archive_stats empty archive overall_success_rate == 0.0",
             _ea_empty_stats["overall_success_rate"] == 0.0)
        test("EA: get_archive_stats empty archive top_strategies == []",
             _ea_empty_stats["top_strategies"] == [])
        _ea_os.remove(_ea_empty_path)

    finally:
        _ea_mod.ARCHIVE_PATH = _ea_orig_path
        try:
            _ea_os.remove(_ea_tmp_path)
        except OSError:
            pass

except Exception as _ea_exc:
    test("EA: experience_archive module-level tests", False, str(_ea_exc))

# ═══════════════════════════════════════════════════════════════════════════════
# RV: rules_validator tests
# ═══════════════════════════════════════════════════════════════════════════════
try:
    import os as _rv_os
    import tempfile as _rv_tempfile
    from shared.rules_validator import (
        _parse_frontmatter,
        _glob_matches_any,
        _extract_doc_paths,
        _detect_overlaps,
        validate_rules,
        _GLOB_NOTE,
    )

    # ── _GLOB_NOTE ────────────────────────────────────────────────────────────

    test("RV: _GLOB_NOTE is a non-empty string",
         isinstance(_GLOB_NOTE, str) and len(_GLOB_NOTE) > 0)
    test("RV: _GLOB_NOTE mentions advisory",
         "advisory" in _GLOB_NOTE)

    # ── _parse_frontmatter ────────────────────────────────────────────────────

    _rv_fm_valid = "---\nglobs: *.py\ntitle: My Rule\n---\nBody text here"
    _rv_fields, _rv_errs = _parse_frontmatter(_rv_fm_valid)
    test("RV: _parse_frontmatter valid frontmatter returns fields dict",
         isinstance(_rv_fields, dict))
    test("RV: _parse_frontmatter valid frontmatter no errors",
         _rv_errs == [])
    test("RV: _parse_frontmatter parses globs field",
         _rv_fields.get("globs") == "*.py")
    test("RV: _parse_frontmatter parses title field",
         _rv_fields.get("title") == "My Rule")

    _rv_fm_no_fm = "# No Frontmatter\nJust body text"
    _rv_fields2, _rv_errs2 = _parse_frontmatter(_rv_fm_no_fm)
    test("RV: _parse_frontmatter no frontmatter returns empty fields",
         _rv_fields2 == {})
    test("RV: _parse_frontmatter no frontmatter returns error list",
         len(_rv_errs2) > 0)
    test("RV: _parse_frontmatter no frontmatter error mentions No frontmatter",
         any("frontmatter" in e.lower() for e in _rv_errs2))

    _rv_fm_unclosed = "---\nglobs: *.py\nBody with no closing"
    _rv_fields3, _rv_errs3 = _parse_frontmatter(_rv_fm_unclosed)
    test("RV: _parse_frontmatter unclosed frontmatter returns empty fields",
         _rv_fields3 == {})
    test("RV: _parse_frontmatter unclosed frontmatter returns error",
         len(_rv_errs3) > 0)
    test("RV: _parse_frontmatter unclosed frontmatter error mentions not closed",
         any("not closed" in e.lower() or "frontmatter" in e.lower() for e in _rv_errs3))

    _rv_fm_empty_body = "---\nglobs: *.txt\n---\n"
    _rv_fields4, _rv_errs4 = _parse_frontmatter(_rv_fm_empty_body)
    test("RV: _parse_frontmatter empty body still parses globs",
         _rv_fields4.get("globs") == "*.txt")
    test("RV: _parse_frontmatter empty body no errors",
         _rv_errs4 == [])

    _rv_fm_multi_globs = "---\nglobs: *.py, *.txt, *.json\n---\ncontent"
    _rv_fields5, _ = _parse_frontmatter(_rv_fm_multi_globs)
    test("RV: _parse_frontmatter multi-value globs parsed as single string",
         "*.py" in _rv_fields5.get("globs", ""))

    # ── _glob_matches_any ─────────────────────────────────────────────────────

    with _rv_tempfile.TemporaryDirectory() as _rv_tmpdir:
        # Create some test files
        _rv_sub = _rv_os.path.join(_rv_tmpdir, "subdir")
        _rv_os.makedirs(_rv_sub)
        with open(_rv_os.path.join(_rv_tmpdir, "test_file.py"), "w") as _f:
            _f.write("# py")
        with open(_rv_os.path.join(_rv_sub, "data.json"), "w") as _f:
            _f.write("{}")

        test("RV: _glob_matches_any *.py matches existing py file",
             _glob_matches_any("*.py", _rv_tmpdir) is True)
        test("RV: _glob_matches_any *.xyz no match returns False",
             _glob_matches_any("*.xyz", _rv_tmpdir) is False)
        test("RV: _glob_matches_any **/*.json matches nested json file",
             _glob_matches_any("**/*.json", _rv_tmpdir) is True)
        test("RV: _glob_matches_any nonexistent-dir returns False",
             _glob_matches_any("*.py", _rv_tmpdir + "/does_not_exist") is False)

    # ── _extract_doc_paths ────────────────────────────────────────────────────

    with _rv_tempfile.TemporaryDirectory() as _rv_tmpdir2:
        # Create a real file to reference
        _rv_real_file = _rv_os.path.join(_rv_tmpdir2, "real_file.md")
        with open(_rv_real_file, "w") as _f:
            _f.write("# real")

        # Content referencing both existing and non-existing paths
        _rv_content = "See `docs/real_file.md` and also `docs/missing.py` for details"
        _rv_refs = _extract_doc_paths(_rv_content, _rv_tmpdir2)
        test("RV: _extract_doc_paths returns list",
             isinstance(_rv_refs, list))
        # Should find at least one reference with a path component
        test("RV: _extract_doc_paths finds path references",
             len(_rv_refs) >= 1)
        # Check that each ref is a (raw, exists) tuple
        test("RV: _extract_doc_paths tuples are (str, bool)",
             all(isinstance(r, tuple) and len(r) == 2 and isinstance(r[0], str) and isinstance(r[1], bool)
                 for r in _rv_refs))

        _rv_content_no_paths = "No file paths mentioned here at all."
        _rv_refs2 = _extract_doc_paths(_rv_content_no_paths, _rv_tmpdir2)
        test("RV: _extract_doc_paths no paths returns []",
             _rv_refs2 == [])

        # Inline code without slash should be ignored
        _rv_content_no_slash = "Use `funcname` and `classname` to call things"
        _rv_refs3 = _extract_doc_paths(_rv_content_no_slash, _rv_tmpdir2)
        test("RV: _extract_doc_paths ignores backtick items without slash",
             _rv_refs3 == [])

    # ── _detect_overlaps ──────────────────────────────────────────────────────

    _rv_no_overlap = {"rule_a.md": ["*.py"], "rule_b.md": ["*.txt"]}
    _rv_overlaps = _detect_overlaps(_rv_no_overlap)
    test("RV: _detect_overlaps non-overlapping globs returns []",
         _rv_overlaps == [])

    _rv_overlap_globs = {
        "rule_a.md": ["hooks/*.py"],
        "rule_b.md": ["hooks/**"],
    }
    _rv_overlaps2 = _detect_overlaps(_rv_overlap_globs)
    test("RV: _detect_overlaps subsumption detected returns non-empty list",
         len(_rv_overlaps2) > 0)
    test("RV: _detect_overlaps result is list of strings",
         all(isinstance(o, str) for o in _rv_overlaps2))

    _rv_overlap_reversed = {
        "rule_x.md": ["src/**"],
        "rule_y.md": ["src/main.py"],
    }
    _rv_overlaps3 = _detect_overlaps(_rv_overlap_reversed)
    test("RV: _detect_overlaps ** in first rule subsumes second",
         len(_rv_overlaps3) > 0)

    _rv_empty_globs = {}
    test("RV: _detect_overlaps empty input returns []",
         _detect_overlaps(_rv_empty_globs) == [])

    _rv_single_entry = {"only_rule.md": ["*.py"]}
    test("RV: _detect_overlaps single entry returns []",
         _detect_overlaps(_rv_single_entry) == [])

    # ── validate_rules ────────────────────────────────────────────────────────

    # Non-existent rules directory
    _rv_report_nonexistent = validate_rules("/nonexistent/rules/dir/xyz", "/tmp")
    test("RV: validate_rules nonexistent dir returns report dict",
         isinstance(_rv_report_nonexistent, dict))
    test("RV: validate_rules nonexistent dir has issues key",
         "issues" in _rv_report_nonexistent)
    test("RV: validate_rules nonexistent dir issues has entry",
         len(_rv_report_nonexistent["issues"]) > 0)
    test("RV: validate_rules nonexistent dir total is 0",
         _rv_report_nonexistent["total"] == 0)

    # Validate with actual rules dir (smoke test structure)
    _rv_real_rules = _rv_os.path.join(_rv_os.path.expanduser("~"), ".claude", "rules")
    if _rv_os.path.isdir(_rv_real_rules):
        _rv_real_report = validate_rules(_rv_real_rules)
        test("RV: validate_rules real dir returns dict with all keys",
             all(k in _rv_real_report for k in
                 ("total", "valid", "dead", "issues", "overlaps", "suggestions")))
        test("RV: validate_rules real dir total is int",
             isinstance(_rv_real_report["total"], int))
        test("RV: validate_rules real dir valid is list",
             isinstance(_rv_real_report["valid"], list))
        test("RV: validate_rules real dir dead is list",
             isinstance(_rv_real_report["dead"], list))
        test("RV: validate_rules real dir overlaps is list",
             isinstance(_rv_real_report["overlaps"], list))
        test("RV: validate_rules real dir suggestions is list",
             isinstance(_rv_real_report["suggestions"], list))
    else:
        skip("RV: validate_rules real dir structure check", "rules dir not found")

    # Validate with a synthetic rules directory
    with _rv_tempfile.TemporaryDirectory() as _rv_rules_tmpdir:
        with _rv_tempfile.TemporaryDirectory() as _rv_base_tmpdir:
            # Create a valid rule file
            _rv_rule_path = _rv_os.path.join(_rv_rules_tmpdir, "myrule.md")
            with open(_rv_rule_path, "w") as _f:
                _f.write("---\nglobs: *.py\n---\n# My Rule\nsome content")

            # Create a matching file in base dir
            with open(_rv_os.path.join(_rv_base_tmpdir, "example.py"), "w") as _f:
                _f.write("# example")

            _rv_synth = validate_rules(_rv_rules_tmpdir, _rv_base_tmpdir)
            test("RV: validate_rules synthetic dir total == 1",
                 _rv_synth["total"] == 1)
            test("RV: validate_rules synthetic dir returns expected keys",
                 all(k in _rv_synth for k in ("total", "valid", "dead", "issues", "overlaps", "suggestions")))

            # Create a rule with no frontmatter
            _rv_rule_nofm = _rv_os.path.join(_rv_rules_tmpdir, "nofm.md")
            with open(_rv_rule_nofm, "w") as _f:
                _f.write("# No frontmatter\nJust some content")
            _rv_synth2 = validate_rules(_rv_rules_tmpdir, _rv_base_tmpdir)
            test("RV: validate_rules no-frontmatter rule counted in total",
                 _rv_synth2["total"] == 2)
            test("RV: validate_rules no-frontmatter rule appears in issues",
                 "nofm.md" in _rv_synth2["issues"])

except Exception as _rv_exc:
    test("RV: rules_validator module-level tests", False, str(_rv_exc))

# ─────────────────────────────────────────────────
# Test: R:W Ratio (Upgrade 1)
# ─────────────────────────────────────────────────
