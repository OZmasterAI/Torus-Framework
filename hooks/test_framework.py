#!/usr/bin/env python3
"""Torus Framework Test Suite -- Master Runner

Imports test modules (tests run at import time), then prints summary.
"""
import sys
import os

# Ensure hooks dir is on path
sys.path.insert(0, os.path.dirname(__file__))

from tests import harness

print("=" * 70)
print("  SELF-HEALING CLAUDE FRAMEWORK -- TEST SUITE")
print("=" * 70)

# Import each module (tests run at import time)
from tests import test_state_tracking
from tests import test_gates_safety
from tests import test_gates_quality
from tests import test_gates_operational
from tests import test_shared_core
from tests import test_integration
from tests import test_analytics
from tests import test_shared_deep

# Restore sideband backup
if harness._SIDEBAND_BACKUP is not None:
    with open(harness.MEMORY_TIMESTAMP_FILE, "w") as f:
        f.write(harness._SIDEBAND_BACKUP)

# Self-check: results list should only contain PASS/FAIL/SKIP
# Use startswith to avoid false matches on test names containing "FAIL"/"PASS"
test_sc_pass = sum(1 for r in harness.RESULTS if r.strip().startswith("PASS") or r.strip().startswith("SKIP"))
test_sc_fail = sum(1 for r in harness.RESULTS if r.strip().startswith("FAIL"))
harness.test("SC: passed tests show PASS", test_sc_pass == harness.PASS)
harness.test("SC: failed tests show FAIL", test_sc_fail == harness.FAIL)

# SUMMARY
print("\n" + "=" * 70)
print(f"  RESULTS: {harness.PASS} passed, {harness.FAIL} failed, {harness.PASS + harness.FAIL} total")
print("=" * 70)

if harness.FAIL > 0:
    print("\nFAILURES:")
    for r in harness.RESULTS:
        if r.strip().startswith("FAIL"):
            print(r)

print()
if __name__ == "__main__":
    sys.exit(0 if harness.FAIL == 0 else 1)
