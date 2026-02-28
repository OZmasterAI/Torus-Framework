"""Functional tests for shared/gate_router.py"""
import sys
import os
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.gate_result import GateResult
import shared.gate_router as gr
from shared.gate_router import (
    get_applicable_gates,
    get_routing_stats,
    route_gates,
    _reset_stats,
    TIER1,
    TIER2,
    GATE_TOOL_MAP,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def tier_of(module_name):
    if module_name in TIER1:
        return 1
    if module_name in TIER2:
        return 2
    return 3

def _make_mock_gate(name, blocked=False, ask=False):
    mod = types.ModuleType(name)
    def check(tool_name, tool_input, state, event_type="PreToolUse"):
        esc = "ask" if ask else ("block" if blocked else "allow")
        return GateResult(
            blocked=blocked,
            message=f"{name} ran",
            gate_name=name,
            escalation=esc,
        )
    mod.check = check
    return mod

def _install_all_mocks(overrides=None):
    """Put pass-through mocks in sys.modules for every gate, then clear router cache."""
    overrides = overrides or {}
    gate_names = [
        "gates.gate_01_read_before_edit",
        "gates.gate_02_no_destroy",
        "gates.gate_03_test_before_deploy",
        "gates.gate_04_memory_first",
        "gates.gate_05_proof_before_fixed",
        "gates.gate_06_save_fix",
        "gates.gate_07_critical_file_guard",
        "gates.gate_09_strategy_ban",
        "gates.gate_10_model_enforcement",
        "gates.gate_11_rate_limit",
        "gates.gate_13_workspace_isolation",
        "gates.gate_14_confidence_check",
        "gates.gate_15_causal_chain",
        "gates.gate_16_code_quality",
        "gates.gate_17_injection_defense",
    ]
    for g in gate_names:
        if g in overrides:
            sys.modules[g] = overrides[g]
        else:
            sys.modules[g] = _make_mock_gate(g)
    gr._loaded.clear()

# ---------------------------------------------------------------------------
# Test 1: get_applicable_gates — tool filtering
# ---------------------------------------------------------------------------

def test_tool_filtering():
    edit_gates = get_applicable_gates("Edit")
    assert "gates.gate_01_read_before_edit" in edit_gates, "gate_01 must apply to Edit"
    assert "gates.gate_10_model_enforcement" not in edit_gates, "gate_10 must NOT apply to Edit"
    assert "gates.gate_02_no_destroy" not in edit_gates, "gate_02 (Bash-only) must NOT apply to Edit"
    assert "gates.gate_11_rate_limit" in edit_gates, "gate_11 (universal) must apply to Edit"

    task_gates = get_applicable_gates("Task")
    assert "gates.gate_04_memory_first" in task_gates
    assert "gates.gate_10_model_enforcement" in task_gates
    assert "gates.gate_01_read_before_edit" not in task_gates

    bash_gates = get_applicable_gates("Bash")
    assert "gates.gate_02_no_destroy" in bash_gates
    assert "gates.gate_03_test_before_deploy" in bash_gates
    assert "gates.gate_01_read_before_edit" not in bash_gates

    wf_gates = get_applicable_gates("WebFetch")
    assert "gates.gate_11_rate_limit" in wf_gates
    assert "gates.gate_17_injection_defense" in wf_gates
    assert "gates.gate_01_read_before_edit" not in wf_gates

    print("PASS: test_tool_filtering")

# ---------------------------------------------------------------------------
# Test 2: get_applicable_gates — priority ordering within result
# ---------------------------------------------------------------------------

def test_priority_ordering():
    for tool in ("Edit", "Bash", "Task", "WebFetch", "Write"):
        gates = get_applicable_gates(tool)
        tiers = [tier_of(g) for g in gates]
        assert tiers == sorted(tiers), (
            f"Ordering wrong for '{tool}': {list(zip(gates, tiers))}"
        )
    print("PASS: test_priority_ordering")

# ---------------------------------------------------------------------------
# Test 3: get_routing_stats initial / empty state
# ---------------------------------------------------------------------------

def test_stats_empty():
    _reset_stats()
    s = get_routing_stats()
    assert s["calls"] == 0
    assert s["gates_run"] == 0
    assert s["gates_skipped"] == 0
    assert s["tier1_blocks"] == 0
    assert s["skip_rate"] == 0.0
    assert s["avg_routing_ms"] == 0.0
    assert s["last_routing_ms"] == 0.0
    print("PASS: test_stats_empty")

# ---------------------------------------------------------------------------
# Test 4: route_gates normal path (no blocks)
# ---------------------------------------------------------------------------

def test_route_normal():
    _install_all_mocks()
    _reset_stats()

    results = route_gates("Edit", {"file_path": "foo.py"}, {})
    s = get_routing_stats()

    assert s["calls"] == 1
    assert all(not r.blocked for r in results), "No gate should block on normal path"
    assert s["gates_run"] > 0
    assert s["tier1_blocks"] == 0
    print(f"PASS: test_route_normal — {s['gates_run']} gates ran, {s['gates_skipped']} skipped")

# ---------------------------------------------------------------------------
# Test 5: route_gates short-circuit on Tier 1 block
# ---------------------------------------------------------------------------

def test_route_tier1_shortcircuit():
    _install_all_mocks(overrides={
        "gates.gate_01_read_before_edit": _make_mock_gate("gate_01", blocked=True),
    })
    _reset_stats()

    results = route_gates("Edit", {"file_path": "foo.py"}, {})
    s = get_routing_stats()

    # gate_01 is the first applicable Tier-1 gate for Edit
    assert len(results) == 1, f"Expected 1 result after short-circuit, got {len(results)}"
    assert results[0].blocked
    assert s["tier1_blocks"] == 1
    assert s["gates_skipped"] > 0, "Skipped count must be >0 after short-circuit"
    print(f"PASS: test_route_tier1_shortcircuit — {s['gates_skipped']} gates skipped after block")

# ---------------------------------------------------------------------------
# Test 6: route_gates short-circuit on Tier 1 ask
# ---------------------------------------------------------------------------

def test_route_tier1_ask():
    _install_all_mocks(overrides={
        "gates.gate_02_no_destroy": _make_mock_gate("gate_02", ask=True),
    })
    _reset_stats()

    # gate_02 is Tier-1 and applies to Bash
    results = route_gates("Bash", {"command": "rm -rf /"}, {})
    s = get_routing_stats()

    assert any(r.is_ask for r in results), "Expected an 'ask' result from gate_02"
    assert s["tier1_blocks"] == 1, "ask should count as tier1_block for short-circuit purposes"
    print(f"PASS: test_route_tier1_ask — short-circuited after ask, {s['gates_skipped']} skipped")

# ---------------------------------------------------------------------------
# Test 7: stats accumulate across multiple calls
# ---------------------------------------------------------------------------

def test_stats_accumulate():
    _install_all_mocks()
    _reset_stats()

    route_gates("Edit", {"file_path": "a.py"}, {})
    route_gates("Edit", {"file_path": "b.py"}, {})
    route_gates("Bash", {"command": "ls"}, {})

    s = get_routing_stats()
    assert s["calls"] == 3
    assert s["gates_run"] > 3        # Multiple gates per call
    assert s["avg_routing_ms"] >= 0.0
    assert s["last_routing_ms"] >= 0.0
    print(f"PASS: test_stats_accumulate — {s['calls']} calls, {s['gates_run']} total gate runs")

# ---------------------------------------------------------------------------
# Test 8: skip_rate calculation
# ---------------------------------------------------------------------------

def test_skip_rate():
    _install_all_mocks()
    _reset_stats()

    # Use a tool with very few applicable gates to force a high skip rate
    route_gates("Task", {}, {})
    s = get_routing_stats()
    total = s["gates_run"] + s["gates_skipped"]
    if total > 0:
        expected = round(s["gates_skipped"] / total, 4)
        assert abs(s["skip_rate"] - expected) < 0.0001, (
            f"skip_rate {s['skip_rate']} != expected {expected}"
        )
    print(f"PASS: test_skip_rate — skip_rate={s['skip_rate']}")

# ---------------------------------------------------------------------------
# Run all tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_tool_filtering()
    test_priority_ordering()
    test_stats_empty()
    test_route_normal()
    test_route_tier1_shortcircuit()
    test_route_tier1_ask()
    test_stats_accumulate()
    test_skip_rate()
    print("\nAll gate_router tests PASSED.")
