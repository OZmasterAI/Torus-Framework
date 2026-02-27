"""Canonical gate module registry — single source of truth.

All files that need the gate list import from here instead of
maintaining their own copy.  Gate 11 is intentionally last so that
blocked calls from earlier gates don't inflate the rate counter.
"""

GATE_MODULES = [
    "gates.gate_01_read_before_edit",
    "gates.gate_02_no_destroy",
    "gates.gate_03_test_before_deploy",
    "gates.gate_04_memory_first",
    "gates.gate_05_proof_before_fixed",
    "gates.gate_06_save_fix",
    "gates.gate_07_critical_file_guard",
    # gate_08 DORMANT — re-enable by uncommenting
    "gates.gate_09_strategy_ban",
    "gates.gate_10_model_enforcement",
    # gate_12 MERGED into gate_06
    "gates.gate_13_workspace_isolation",
    "gates.gate_14_confidence_check",
    "gates.gate_15_causal_chain",
    "gates.gate_16_code_quality",
    "gates.gate_17_injection_defense",
    "gates.gate_18_canary",
    "gates.gate_19_hindsight",
    "gates.gate_11_rate_limit",  # Last: earlier blocks don't inflate rate counter
]
