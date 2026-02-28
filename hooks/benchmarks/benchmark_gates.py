#!/usr/bin/env python3
"""Gate Performance Benchmark

Imports all active gates from hooks/gates/, runs each gate's check() function
1000 times with realistic scenarios, measures latency percentiles, and reports
a JSON summary to stdout.

Gates exceeding 1ms p95 are flagged as "needs_optimization".

Usage:
    python /home/crab/.claude/hooks/benchmarks/benchmark_gates.py
"""

import importlib
import json
import os
import sys
import time

# Add hooks dir to path so shared imports work
HOOKS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, HOOKS_DIR)

# ── Canonical gate list (from shared/gate_registry.py) ────────────────────────
from shared.gate_registry import GATE_MODULES

# ── Tool map (mirrors enforcer.py GATE_TOOL_MAP) ───────────────────────────────
# Picks a valid/watched tool per gate so the gate actually runs its main logic
# rather than returning early on tool_name mismatch.
GATE_TOOL_MAP = {
    "gates.gate_01_read_before_edit":   "Edit",
    "gates.gate_02_no_destroy":         "Bash",
    "gates.gate_03_test_before_deploy": "Bash",
    "gates.gate_04_memory_first":       "Edit",
    "gates.gate_05_proof_before_fixed": "Edit",
    "gates.gate_06_save_fix":           "Edit",
    "gates.gate_07_critical_file_guard": "Edit",
    "gates.gate_09_strategy_ban":       "Edit",
    "gates.gate_10_model_enforcement":  "Task",
    "gates.gate_11_rate_limit":         "Edit",
    "gates.gate_13_workspace_isolation": "Edit",
    "gates.gate_14_confidence_check":   "Edit",
    "gates.gate_15_causal_chain":       "Edit",
    "gates.gate_16_code_quality":       "Write",
    "gates.gate_17_injection_defense":  "WebFetch",
}

# ── Realistic test scenarios per gate ─────────────────────────────────────────
# Each gate gets one primary scenario (tool_name + tool_input + state fragment).
# The state fragments simulate realistic field values for the state keys each
# gate reads.  BASE_STATE provides sensible defaults; overrides are merged in.

_NOW = time.time()

BASE_STATE = {
    "_session_id": "benchmark-session",
    "files_read": [
        "/home/crab/.claude/hooks/enforcer.py",
        "/home/crab/.claude/hooks/gates/gate_01_read_before_edit.py",
        "/home/crab/.claude/hooks/shared/state.py",
        "/home/crab/.claude/hooks/test_framework.py",
    ],
    "last_test_run": _NOW - 60,          # 1 min ago (fresh enough for Gate 3)
    "last_test_exit_code": 0,
    "last_test_command": "python3 test_framework.py",
    "session_test_baseline": True,
    "memory_last_queried": _NOW - 30,    # 30 sec ago (fresh for Gate 4 & 7)
    "rate_window_timestamps": [_NOW - i * 15 for i in range(5)],  # 5 calls in 2-min window
    "tool_call_count": 10,
    "session_start": _NOW - 300,
    "verified_fixes": [],
    "verification_timestamps": {},
    "unlogged_errors": [],
    "error_pattern_counts": {},
    "error_windows": [],
    "pending_verification": [],
    "verification_scores": {},
    "edit_streak": {},
    "gate6_warn_count": 0,
    "pending_chain_ids": [],
    "last_exit_plan_mode": 0,
    "confidence_warnings_per_file": {},
    "confidence_warned_signals": [],
    "code_quality_warnings_per_file": {},
    "active_bans": {},
    "current_strategy_id": "",
    "successful_strategies": {},
    "recent_test_failure": None,
    "fix_history_queried": _NOW - 10,
    "fixing_error": False,
    "injection_attempts": 0,
    "gate_tune_overrides": {},
    "gate4_exemptions": {},
    "model_agent_usage": {},
    "subagent_total_tokens": 1000,
    "session_token_estimate": 2000,
    "deferred_items": [],
}

GATE_SCENARIOS = {
    # Gate 1: file already read → fast allow path
    "gates.gate_01_read_before_edit": {
        "tool_input": {
            "file_path": "/home/crab/.claude/hooks/enforcer.py",
            "old_string": "import json",
            "new_string": "import json  # benchmark",
        },
        "state_overrides": {},
    },
    # Gate 2: harmless git command → fast allow path
    "gates.gate_02_no_destroy": {
        "tool_input": {
            "command": "git status && git log --oneline -5",
        },
        "state_overrides": {},
    },
    # Gate 3: non-deploy command → early return
    "gates.gate_03_test_before_deploy": {
        "tool_input": {
            "command": "python3 test_framework.py -v",
        },
        "state_overrides": {},
    },
    # Gate 4: memory queried 30s ago → fast allow (uses state; sideband file is separate)
    "gates.gate_04_memory_first": {
        "tool_input": {
            "file_path": "/home/crab/.claude/hooks/enforcer.py",
            "old_string": "# old",
            "new_string": "# new",
        },
        "state_overrides": {
            "memory_last_queried": _NOW - 30,
        },
    },
    # Gate 5: no pending verifications → fast allow
    "gates.gate_05_proof_before_fixed": {
        "tool_input": {
            "file_path": "/home/crab/.claude/hooks/enforcer.py",
            "old_string": "# old",
            "new_string": "# new",
        },
        "state_overrides": {
            "pending_verification": [],
            "verification_scores": {},
            "edit_streak": {},
        },
    },
    # Gate 6: nothing to warn about → fast path (minimal state fields)
    "gates.gate_06_save_fix": {
        "tool_input": {
            "file_path": "/home/crab/.claude/hooks/enforcer.py",
            "old_string": "# old",
            "new_string": "# new",
        },
        "state_overrides": {
            "verified_fixes": [],
            "unlogged_errors": [],
            "error_pattern_counts": {},
            "edit_streak": {},
            "pending_chain_ids": [],
            "last_exit_plan_mode": 0,
            "gate6_warn_count": 0,
        },
    },
    # Gate 7: critical file + memory fresh → allow (exercises regex matching + time check)
    "gates.gate_07_critical_file_guard": {
        "tool_input": {
            "file_path": "/home/crab/.claude/hooks/gates/gate_01_read_before_edit.py",
            "old_string": "# old",
            "new_string": "# new",
        },
        "state_overrides": {
            "memory_last_queried": _NOW - 30,
        },
    },
    # Gate 9: no active strategy → inert early return
    "gates.gate_09_strategy_ban": {
        "tool_input": {
            "file_path": "/home/crab/.claude/hooks/enforcer.py",
            "old_string": "# old",
            "new_string": "# new",
        },
        "state_overrides": {
            "current_strategy_id": "",
            "active_bans": {},
        },
    },
    # Gate 10: Task with model specified → exercises advisory path
    "gates.gate_10_model_enforcement": {
        "tool_input": {
            "description": "Run tests and report failures",
            "subagent_type": "stress-tester",
            "model": "sonnet",
            "prompt": "Run all tests in test_framework.py and report failures.",
        },
        "state_overrides": {
            "model_agent_usage": {},
        },
    },
    # Gate 11: low rate (5 calls in 120s window) → fast allow; exercises list filter
    "gates.gate_11_rate_limit": {
        "tool_input": {
            "file_path": "/home/crab/.claude/hooks/enforcer.py",
            "old_string": "# old",
            "new_string": "# new",
        },
        "state_overrides": {
            "rate_window_timestamps": [_NOW - i * 15 for i in range(5)],
        },
    },
    # Gate 13: session_id == "main" → exempt, immediate return
    "gates.gate_13_workspace_isolation": {
        "tool_input": {
            "file_path": "/home/crab/.claude/hooks/enforcer.py",
            "old_string": "# old",
            "new_string": "# new",
        },
        "state_overrides": {
            "_session_id": "main",
        },
    },
    # Gate 14: HANDOFF.md → exempt file, immediate return
    "gates.gate_14_confidence_check": {
        "tool_input": {
            "file_path": "/home/crab/.claude/HANDOFF.md",
            "content": "# Handoff\n",
        },
        "state_overrides": {},
    },
    # Gate 15: no recent failure → immediate return
    "gates.gate_15_causal_chain": {
        "tool_input": {
            "file_path": "/home/crab/.claude/hooks/enforcer.py",
            "old_string": "# old",
            "new_string": "# new",
        },
        "state_overrides": {
            "recent_test_failure": None,
            "fixing_error": False,
        },
    },
    # Gate 16: clean code → no violations, reset path
    "gates.gate_16_code_quality": {
        "tool_input": {
            "file_path": "/home/crab/.claude/hooks/gates/gate_01_read_before_edit.py",
            "content": (
                "def helper(x):\n"
                "    \"\"\"Return x squared.\"\"\"\n"
                "    return x * x\n"
                "\n"
                "def greet(name):\n"
                "    \"\"\"Return greeting string.\"\"\"\n"
                "    return f'Hello, {name}!'\n"
            ),
        },
        "state_overrides": {
            "code_quality_warnings_per_file": {},
        },
    },
    # Gate 17: benign web content at PostToolUse → scan path without matches
    "gates.gate_17_injection_defense": {
        "tool_input": {
            "content": (
                "Welcome to Example.com!\n\n"
                "This page contains documentation about Python best practices.\n"
                "See the help section for more information about configuration.\n"
                "Contact support at help@example.com for assistance.\n"
            ),
        },
        "state_overrides": {
            "injection_attempts": 0,
        },
        "event_type": "PostToolUse",  # Gate 17 only scans on PostToolUse
    },
}


def _percentile(sorted_data, pct):
    """Compute pct-th percentile from a pre-sorted list (pct in 0-100)."""
    n = len(sorted_data)
    if n == 0:
        return 0.0
    idx = (pct / 100.0) * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return sorted_data[lo] * (1.0 - frac) + sorted_data[hi] * frac


def load_gate(module_name):
    """Import a gate module by dotted name. Returns module or None on failure."""
    try:
        mod = importlib.import_module(module_name)
        return mod if hasattr(mod, "check") else None
    except ImportError:
        return None


def build_state(base, overrides):
    """Merge base state with per-gate overrides. Returns a fresh shallow copy."""
    state = dict(base)
    state.update(overrides)
    return state


def run_gate_benchmark(module_name, gate_mod, n_iterations=1000):
    """Run gate.check() n_iterations times. Returns list of latencies in ms."""
    scenario = GATE_SCENARIOS.get(module_name, {})
    tool_name = GATE_TOOL_MAP.get(module_name, "Edit")
    tool_input = scenario.get(
        "tool_input",
        {"file_path": "/tmp/test.py", "old_string": "x", "new_string": "y"},
    )
    state_overrides = scenario.get("state_overrides", {})
    event_type = scenario.get("event_type", "PreToolUse")

    latencies = []
    for _ in range(n_iterations):
        # Fresh state copy per iteration to avoid cross-iteration contamination
        state = build_state(BASE_STATE, state_overrides)
        t0 = time.perf_counter()
        try:
            gate_mod.check(tool_name, tool_input, state, event_type=event_type)
        except Exception:
            pass  # Measure latency even if the gate crashes
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)  # convert to ms

    return latencies


def estimate_pipeline_latency(gate_results):
    """Estimate total enforcer pipeline latency for a typical Edit call.

    Sums p50 and p95 for all gates that fire on Edit tool calls.
    Excludes Bash-only gates (02, 03), Task-only gate (10), and
    WebFetch-only gate (17) since they return early on Edit.
    """
    # Gates that actually execute check logic for "Edit" tool calls
    edit_active_gates = {
        "gate_01_read_before_edit",
        "gate_04_memory_first",
        "gate_05_proof_before_fixed",
        "gate_06_save_fix",
        "gate_07_critical_file_guard",
        "gate_09_strategy_ban",
        "gate_11_rate_limit",    # universal (None in GATE_TOOL_MAP)
        "gate_13_workspace_isolation",
        "gate_14_confidence_check",
        "gate_15_causal_chain",
        "gate_16_code_quality",
    }

    p50_sum = 0.0
    p95_sum = 0.0
    gate_count = 0
    contributing_gates = []

    for gate_short, result in gate_results.items():
        if gate_short in edit_active_gates:
            p50_sum += result["latency_ms"]["p50"]
            p95_sum += result["latency_ms"]["p95"]
            gate_count += 1
            contributing_gates.append(gate_short)

    return {
        "tool": "Edit",
        "gates_in_pipeline": gate_count,
        "contributing_gates": sorted(contributing_gates),
        "estimated_p50_ms": round(p50_sum, 4),
        "estimated_p95_ms": round(p95_sum, 4),
        "note": (
            "Sum of per-gate p50/p95. Real enforcer also pays: "
            "load_state(), save_state(), audit_log.log_gate_decision(), "
            "circuit_breaker.should_skip_gate(), qtable update, and "
            "gate_timing analytics (typically +0.5-3ms per call)."
        ),
    }


def main():
    n_iterations = 1000
    p95_threshold_ms = 1.0

    results = {}
    load_errors = {}

    for module_name in GATE_MODULES:
        gate_mod = load_gate(module_name)
        if gate_mod is None:
            load_errors[module_name] = "failed to import or missing check()"
            continue

        latencies = run_gate_benchmark(module_name, gate_mod, n_iterations)
        sorted_lat = sorted(latencies)

        p50 = _percentile(sorted_lat, 50)
        p95 = _percentile(sorted_lat, 95)
        p99 = _percentile(sorted_lat, 99)
        mean_lat = sum(latencies) / len(latencies)

        gate_short = module_name.split(".")[-1]
        gate_name = getattr(gate_mod, "GATE_NAME", gate_short)
        scenario = GATE_SCENARIOS.get(module_name, {})
        event_type = scenario.get("event_type", "PreToolUse")

        results[gate_short] = {
            "module": module_name,
            "gate_name": gate_name,
            "benchmark_tool": GATE_TOOL_MAP.get(module_name, "Edit"),
            "benchmark_event_type": event_type,
            "benchmark_scenario": "realistic allow path (normal operation)",
            "iterations": n_iterations,
            "latency_ms": {
                "min":  round(sorted_lat[0], 4),
                "mean": round(mean_lat, 4),
                "p50":  round(p50, 4),
                "p95":  round(p95, 4),
                "p99":  round(p99, 4),
                "max":  round(sorted_lat[-1], 4),
            },
            "needs_optimization": p95 > p95_threshold_ms,
            "optimization_threshold_ms": p95_threshold_ms,
        }

    pipeline = estimate_pipeline_latency(results)

    flagged = sorted(
        [g for g, r in results.items() if r["needs_optimization"]],
        key=lambda g: results[g]["latency_ms"]["p95"],
        reverse=True,
    )
    all_p95s = [r["latency_ms"]["p95"] for r in results.values()]
    avg_p95 = round(sum(all_p95s) / len(all_p95s), 4) if all_p95s else 0.0
    max_p95_gate = max(results.items(), key=lambda kv: kv[1]["latency_ms"]["p95"])[0] if results else None

    output = {
        "benchmark_metadata": {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "n_iterations": n_iterations,
            "optimization_flag_threshold_ms": p95_threshold_ms,
            "gates_benchmarked": len(results),
            "gates_failed_to_load": len(load_errors),
            "gates_needing_optimization": len(flagged),
            "average_p95_ms_across_gates": avg_p95,
            "slowest_gate_p95": max_p95_gate,
        },
        "gates": results,
        "pipeline_estimate": pipeline,
        "load_errors": load_errors,
        "optimization_candidates": flagged,
    }

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
