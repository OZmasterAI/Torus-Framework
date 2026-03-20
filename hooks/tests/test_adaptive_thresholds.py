#!/usr/bin/env python3
"""Tests for shared/adaptive_thresholds.py and shared/learning_loop.py"""
import os
import sys
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.adaptive_thresholds import (
    get_threshold, record_gate_outcome, adjust_thresholds,
    get_threshold_report, load_thresholds, save_thresholds,
    IMMUTABLE_GATES, _default_data,
)

passed = failed = 0

def test(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name} — {detail}")


print("\n--- Adaptive Thresholds: basics ---")

data = _default_data()
test("Default has gate_thresholds", "gate_thresholds" in data)
test("Default has confidence gate", "gates.gate_14_confidence_check" in data["gate_thresholds"])
threshold = get_threshold(data, "gates.gate_14_confidence_check")
test("Default threshold is 0.70", threshold == 0.70, f"got {threshold}")
test("Unknown gate returns 0.5", get_threshold(data, "gates.nonexistent") == 0.5)

print("\n--- Adaptive Thresholds: T1 immutability ---")

for gate in IMMUTABLE_GATES:
    data2 = _default_data()
    record_gate_outcome(data2, gate, gate_blocked=True, tool_succeeded=True)
    test(f"{gate.split('.')[-1]} not tracked", gate not in data2.get("gate_thresholds", {}))

print("\n--- Adaptive Thresholds: outcome recording ---")

data3 = _default_data()
gate = "gates.gate_14_confidence_check"
# Record outcomes
record_gate_outcome(data3, gate, gate_blocked=True, tool_succeeded=False)  # TP
record_gate_outcome(data3, gate, gate_blocked=True, tool_succeeded=True)   # FP
record_gate_outcome(data3, gate, gate_blocked=False, tool_succeeded=True)  # TN
record_gate_outcome(data3, gate, gate_blocked=False, tool_succeeded=False) # FN

entry = data3["gate_thresholds"][gate]
test("TP recorded", entry["true_positives"] == 1)
test("FP recorded", entry["false_positives"] == 1)
test("TN recorded", entry["true_negatives"] == 1)
test("FN recorded", entry["false_negatives"] == 1)

print("\n--- Adaptive Thresholds: adjustment direction ---")

# Tighten: high false negative rate
data4 = _default_data()
gate = "gates.gate_16_code_quality"
entry = data4["gate_thresholds"][gate]
entry["true_negatives"] = 8
entry["false_negatives"] = 3  # 27% FN rate > 10% trigger
entry["true_positives"] = 5
entry["false_positives"] = 0
old_threshold = entry["current"]

adjustments = adjust_thresholds(data4)
new_threshold = data4["gate_thresholds"][gate]["current"]
test("Tightened on high FN", new_threshold > old_threshold, f"{old_threshold} -> {new_threshold}")

# Loosen: high false positive rate
data5 = _default_data()
gate = "gates.gate_16_code_quality"
entry = data5["gate_thresholds"][gate]
entry["true_positives"] = 3
entry["false_positives"] = 4  # 57% FP rate > 20% trigger
entry["true_negatives"] = 10
entry["false_negatives"] = 0
old_threshold = entry["current"]

adjustments = adjust_thresholds(data5)
new_threshold = data5["gate_thresholds"][gate]["current"]
test("Loosened on high FP", new_threshold < old_threshold, f"{old_threshold} -> {new_threshold}")

print("\n--- Adaptive Thresholds: bounds respected ---")

data6 = _default_data()
gate = "gates.gate_14_confidence_check"
entry = data6["gate_thresholds"][gate]
# Extreme false negatives should push threshold up but not past max
entry["true_negatives"] = 1
entry["false_negatives"] = 100
entry["true_positives"] = 1
entry["false_positives"] = 0
for _ in range(50):  # Multiple adjustment passes
    adjust_thresholds(data6)
final = data6["gate_thresholds"][gate]["current"]
test("Max bound respected", final <= 0.95, f"got {final}")
test("Above minimum", final >= 0.50, f"got {final}")

print("\n--- Adaptive Thresholds: feedback log cap ---")

data7 = _default_data()
gate = "gates.gate_14_confidence_check"
entry = data7["gate_thresholds"][gate]
# Create enough samples and run adjustments to fill the log
entry["true_negatives"] = 50
entry["false_negatives"] = 20
entry["true_positives"] = 20
entry["false_positives"] = 20
data7["feedback_log"] = [{"gate": gate, "action": "test", "timestamp": 0}] * 120
adjust_thresholds(data7)
test("Feedback log capped", len(data7["feedback_log"]) <= 100 + 5,  # +buffer for new entries
     f"got {len(data7['feedback_log'])}")

print("\n--- Adaptive Thresholds: report ---")

report = get_threshold_report(data4)
test("Report has thresholds", "thresholds" in report)
test("Report has adjustments", "recent_adjustments" in report)

print("\n--- Adaptive Thresholds: load/save round-trip ---")

with tempfile.TemporaryDirectory() as tmpdir:
    import shared.adaptive_thresholds as at
    old_disk = at._DISK_DIR
    old_ram = at._RAMDISK_DIR
    at._DISK_DIR = tmpdir
    at._RAMDISK_DIR = "/nonexistent"
    try:
        data8 = _default_data()
        record_gate_outcome(data8, "gates.gate_14_confidence_check", True, False)
        save_thresholds(data8)
        loaded = load_thresholds()
        test("Round-trip preserves TP",
             loaded["gate_thresholds"]["gates.gate_14_confidence_check"]["true_positives"] == 1)
    finally:
        at._DISK_DIR = old_disk
        at._RAMDISK_DIR = old_ram

print("\n--- Learning Loop ---")

from shared.learning_loop import process_gate_result, process_fix_outcome, get_learning_stats

# Test get_learning_stats doesn't crash
stats = get_learning_stats()
test("Stats has mastery key", "mastery" in stats)
test("Stats has thresholds key", "thresholds" in stats)

print(f"\n{'='*40}")
print(f"Adaptive Thresholds: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
