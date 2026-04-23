#!/usr/bin/env python3
"""Tests for shared/skill_tracker.py"""
import os
import sys
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.skill_tracker import (
    record_skill_invocation, get_skill_stats, get_skill_recommendations,
    get_improvement_candidates, load_skill_data, save_skill_data,
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


print("\n--- Skill Tracker: record_skill_invocation ---")

data = {"skills": {}, "last_updated": 0.0}
record_skill_invocation(data, "fix", success=True, context="fixed import bug", duration_s=30)
record_skill_invocation(data, "fix", success=True, context="fixed typo")
record_skill_invocation(data, "fix", success=False, context="tried to fix memory leak", error_hint="timeout")

test("Success count", data["skills"]["fix"]["success_count"] == 2)
test("Failure count", data["skills"]["fix"]["failure_count"] == 1)
test("Duration tracked", data["skills"]["fix"]["total_duration_s"] == 30)
test("Invocations recorded", len(data["skills"]["fix"]["invocations"]) == 3)
test("Success contexts", len(data["skills"]["fix"]["success_contexts"]) == 2)
test("Failure contexts", len(data["skills"]["fix"]["failure_contexts"]) == 1)

print("\n--- Skill Tracker: get_skill_stats ---")

stats = get_skill_stats(data, "fix")
test("Stats success_rate", abs(stats["success_rate"] - 0.6667) < 0.01, f"got {stats['success_rate']}")
test("Stats total", stats["total_invocations"] == 3)
test("Stats avg_duration", stats["avg_duration_s"] == 10.0)  # 30/3
test("Unknown skill defaults", get_skill_stats(data, "nonexistent")["success_rate"] == 1.0)

print("\n--- Skill Tracker: improvement candidates ---")

data2 = {"skills": {}, "last_updated": 0.0}
# Good skill: 95% success
for _ in range(19):
    record_skill_invocation(data2, "commit", success=True, context="auto commit")
record_skill_invocation(data2, "commit", success=False, context="commit hook failed")

# Bad skill: 40% success
for _ in range(4):
    record_skill_invocation(data2, "deploy", success=True, context="deployed to staging")
for _ in range(6):
    record_skill_invocation(data2, "deploy", success=False, context="deploy failed on production")

# Too few invocations
record_skill_invocation(data2, "rare", success=False)

candidates = get_improvement_candidates(data2)
test("Deploy is candidate", any(c["skill"] == "deploy" for c in candidates))
test("Commit not candidate (>95%)", not any(c["skill"] == "commit" for c in candidates))
test("Rare not candidate (too few)", not any(c["skill"] == "rare" for c in candidates))

if candidates:
    test("Deploy ranked first", candidates[0]["skill"] == "deploy",
         f"got {candidates[0]['skill']}")

print("\n--- Skill Tracker: recommendations ---")

recs = get_skill_recommendations(data2)
test("Recommendations generated", len(recs) > 0)
if recs:
    test("Deploy has suggestions", any(r["skill"] == "deploy" and r["suggestions"] for r in recs))

print("\n--- Skill Tracker: load/save round-trip ---")

with tempfile.TemporaryDirectory() as tmpdir:
    import shared.skill_tracker as st
    old_disk = st._DISK_DIR
    old_ram = st._RAMDISK_DIR
    st._DISK_DIR = tmpdir
    st._RAMDISK_DIR = "/nonexistent"
    try:
        save_skill_data(data2)
        loaded = load_skill_data()
        test("Round-trip preserves data",
             loaded["skills"]["deploy"]["failure_count"] == 6,
             f"got {loaded.get('skills', {}).get('deploy', {})}")
    finally:
        st._DISK_DIR = old_disk
        st._RAMDISK_DIR = old_ram

print(f"\n{'='*40}")
print(f"Skill Tracker: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
