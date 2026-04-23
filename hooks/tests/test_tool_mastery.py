#!/usr/bin/env python3
"""Tests for shared/tool_mastery.py"""
import os
import sys
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.tool_mastery import (
    record_tool_use, get_mastery_level, get_task_preferences,
    get_mastery_report, suggest_tool, load_mastery, save_mastery,
    _default_mastery, infer_task_type, MASTERY_LEVELS,
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


print("\n--- Tool Mastery: record_tool_use ---")

data = _default_mastery()
record_tool_use(data, "Edit", "fix", success=True, duration_ms=100)
record_tool_use(data, "Edit", "fix", success=True, duration_ms=200)
record_tool_use(data, "Edit", "fix", success=False, duration_ms=50)
test("Edit fix success=2", data["tool_task_stats"]["Edit"]["fix"]["success"] == 2)
test("Edit fix failure=1", data["tool_task_stats"]["Edit"]["fix"]["failure"] == 1)
test("Duration tracked", data["tool_task_stats"]["Edit"]["fix"]["avg_duration_ms"] > 0)

# Untracked tools ignored
record_tool_use(data, "UnknownTool", "fix")
test("Untracked tool ignored", "UnknownTool" not in data["tool_task_stats"])

# Unknown task type normalized
record_tool_use(data, "Bash", "INVALID_TYPE")
test("Invalid task_type → unknown", "unknown" in data["tool_task_stats"].get("Bash", {}))

print("\n--- Tool Mastery: mastery levels ---")

data2 = _default_mastery()
# Novice: < 10 uses
for _ in range(5):
    record_tool_use(data2, "Grep", "explore", success=True)
test("Novice at 5 uses", get_mastery_level(data2, "Grep")["level"] == "novice")

# Competent: 10-50 uses, > 70% success
for _ in range(6):
    record_tool_use(data2, "Grep", "explore", success=True)
test("Competent at 11 uses", get_mastery_level(data2, "Grep")["level"] == "competent")

# Proficient: 50+ uses, > 80% success
for _ in range(50):
    record_tool_use(data2, "Grep", "explore", success=True)
test("Proficient at 61 uses", get_mastery_level(data2, "Grep")["level"] == "proficient")

# Expert: 200+ uses, > 90% success
for _ in range(150):
    record_tool_use(data2, "Grep", "explore", success=True)
test("Expert at 211 uses", get_mastery_level(data2, "Grep")["level"] == "expert",
     f"got {get_mastery_level(data2, 'Grep')}")

# Low success rate prevents advancement
data3 = _default_mastery()
for _ in range(100):
    record_tool_use(data3, "Bash", "test", success=True)
for _ in range(50):
    record_tool_use(data3, "Bash", "test", success=False)
level = get_mastery_level(data3, "Bash")
test("Low success prevents expert", level["level"] != "expert", f"got {level}")

print("\n--- Tool Mastery: task preferences ---")

data4 = _default_mastery()
# Grep: 95% success, Read: 80% success, Edit: 60% success
for _ in range(19):
    record_tool_use(data4, "Grep", "fix", success=True)
record_tool_use(data4, "Grep", "fix", success=False)

for _ in range(16):
    record_tool_use(data4, "Read", "fix", success=True)
for _ in range(4):
    record_tool_use(data4, "Read", "fix", success=False)

for _ in range(12):
    record_tool_use(data4, "Edit", "fix", success=True)
for _ in range(8):
    record_tool_use(data4, "Edit", "fix", success=False)

prefs = get_task_preferences(data4, "fix")
test("Preferences ordered by success", len(prefs) == 3, f"got {prefs}")
test("Grep first (highest rate)", prefs[0] == "Grep" if prefs else False, f"got {prefs}")
test("Edit last (lowest rate)", prefs[-1] == "Edit" if prefs else False, f"got {prefs}")

print("\n--- Tool Mastery: suggest_tool ---")

test("Suggest returns best tool", suggest_tool(data4, "fix") == "Grep")
test("Suggest with exclude", suggest_tool(data4, "fix", exclude=["Grep"]) == "Read")
test("Suggest with action hint", suggest_tool(data4, "fix", action="search") == "Grep")
test("Suggest edit action", suggest_tool(data4, "fix", action="edit") == "Edit")
test("Suggest returns None if empty", suggest_tool(data4, "nonexistent") is None)

print("\n--- Tool Mastery: report ---")

report = get_mastery_report(data4)
test("Report has levels", "mastery_levels" in report)
test("Report has preferences", "task_preferences" in report)
test("Report has distribution", "level_distribution" in report)
test("Total uses computed", report["total_tool_uses"] > 0)

print("\n--- Tool Mastery: load/save round-trip ---")

with tempfile.TemporaryDirectory() as tmpdir:
    import shared.tool_mastery as tm
    old_disk = tm._DISK_DIR
    old_ramdisk = tm._RAMDISK_DIR
    tm._DISK_DIR = tmpdir
    tm._RAMDISK_DIR = "/nonexistent"  # force disk path
    try:
        data5 = _default_mastery()
        record_tool_use(data5, "Edit", "feature", success=True)
        save_mastery(data5)
        loaded = load_mastery()
        test("Round-trip preserves stats",
             loaded["tool_task_stats"]["Edit"]["feature"]["success"] == 1,
             f"got {loaded.get('tool_task_stats', {}).get('Edit', {})}")
    finally:
        tm._DISK_DIR = old_disk
        tm._RAMDISK_DIR = old_ramdisk

print("\n--- Tool Mastery: infer_task_type ---")

test("Infer fix from state", infer_task_type({"fix_chain_active": True}) == "fix")
test("Infer explore from early reads", infer_task_type({"tool_call_count": 3, "last_tool_name": "Read"}) == "explore")
test("Infer from explicit type", infer_task_type({"current_task_type": "feature"}) == "feature")
test("Default to unknown", infer_task_type({}) == "unknown")

print(f"\n{'='*40}")
print(f"Tool Mastery: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
