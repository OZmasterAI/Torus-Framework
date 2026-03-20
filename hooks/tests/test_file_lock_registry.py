#!/usr/bin/env python3
"""Tests for cross-agent file coordination (file_lock_registry)."""
import json
import os
import sys
import time
import tempfile
import shutil

# Add hooks dir to path
HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HOOKS_DIR not in sys.path:
    sys.path.insert(0, HOOKS_DIR)

from tests.harness import test, skip, HOOKS_DIR as _HD
from shared.file_lock_registry import (
    acquire_lock,
    release_lock,
    is_locked,
    cleanup_stale_locks,
    _get_lock_dir,
    _lock_file_path,
    _read_lock_meta,
    DEFAULT_TIMEOUT,
)

print("\n=== File Lock Registry Tests ===\n")

# Use a temp dir for lock files to avoid polluting ramdisk/hooks
_test_lock_dir = tempfile.mkdtemp(prefix="flr_test_")

# Monkey-patch _get_lock_dir to use temp dir
import shared.file_lock_registry as flr_mod
_orig_get_lock_dir = flr_mod._get_lock_dir
flr_mod._get_lock_dir = lambda: _test_lock_dir


# ── Basic acquire/release ──────────────────────────────────────────

test_file = "/tmp/test_target.py"
session_a = "session-aaaa-1111"
session_b = "session-bbbb-2222"

# Test 1: Acquire lock succeeds
result = acquire_lock(test_file, session_a)
test("acquire_lock returns True for new lock", result is True)

# Test 2: Same session can re-acquire (reentrant)
result = acquire_lock(test_file, session_a)
test("acquire_lock is reentrant for same session", result is True)

# Test 3: Different session is blocked
result = acquire_lock(test_file, session_b)
test("acquire_lock returns False for different session", result is False)

# Test 4: is_locked returns info for other session
lock_info = is_locked(test_file, exclude_session=session_b)
test("is_locked returns lock info for other session", lock_info is not None)
test("is_locked reports correct session_id", lock_info and lock_info.get("session_id") == session_a)

# Test 5: is_locked returns None for lock owner
lock_info = is_locked(test_file, exclude_session=session_a)
test("is_locked returns None for lock owner", lock_info is None)

# Test 6: Release by owner succeeds
result = release_lock(test_file, session_a)
test("release_lock by owner returns True", result is True)

# Test 7: After release, file is unlocked
lock_info = is_locked(test_file)
test("is_locked returns None after release", lock_info is None)

# Test 8: Release non-existent lock is fine
result = release_lock("/tmp/never_locked.py", session_a)
test("release_lock for non-existent lock returns True", result is True)

# Test 9: Cannot release lock owned by another
acquire_lock(test_file, session_a)
result = release_lock(test_file, session_b)
test("release_lock by non-owner returns False", result is False)
release_lock(test_file, session_a)  # cleanup


# ── Stale lock reclamation ─────────────────────────────────────────

# Test 10: Stale locks get reclaimed
acquire_lock(test_file, session_a, timeout=1)
# Manually backdate the lock
lock_path = _lock_file_path(test_file, _test_lock_dir)
meta = _read_lock_meta(lock_path)
meta["acquired_at"] = time.time() - 60  # 60 seconds ago
with open(lock_path, "w") as f:
    json.dump(meta, f)

# Now session_b should be able to acquire (lock is stale)
result = acquire_lock(test_file, session_b, timeout=1)
test("stale lock is reclaimed by new session", result is True)
release_lock(test_file, session_b)


# ── cleanup_stale_locks ───────────────────────────────────────────

# Test 11: cleanup_stale_locks removes stale locks
acquire_lock(test_file, session_a)
lock_path = _lock_file_path(test_file, _test_lock_dir)
meta = _read_lock_meta(lock_path)
meta["acquired_at"] = time.time() - 120
with open(lock_path, "w") as f:
    json.dump(meta, f)

removed = cleanup_stale_locks(timeout=1)
test("cleanup_stale_locks removes stale locks", removed >= 1)


# ── Multiple files ─────────────────────────────────────────────────

# Test 12: Different files can be locked by different sessions
file_x = "/tmp/file_x.py"
file_y = "/tmp/file_y.py"
r1 = acquire_lock(file_x, session_a)
r2 = acquire_lock(file_y, session_b)
test("different files can be locked by different sessions", r1 and r2)
release_lock(file_x, session_a)
release_lock(file_y, session_b)


# ── Fail-open behavior ────────────────────────────────────────────

# Test 13: _get_lock_dir returning None causes fail-open
flr_mod._get_lock_dir = lambda: None
result = acquire_lock(test_file, session_a)
test("acquire_lock returns True (fail-open) when no lock dir", result is True)

lock_info = is_locked(test_file)
test("is_locked returns None (fail-open) when no lock dir", lock_info is None)

result = release_lock(test_file, session_a)
test("release_lock returns True (fail-open) when no lock dir", result is True)

# Restore
flr_mod._get_lock_dir = lambda: _test_lock_dir


# ── Enforcer integration (direct function call) ───────────────────

# Test 14: Enforcer blocks when file locked by another session
from shared.gate_result import GateResult
from shared.state import load_state, save_state, default_state

# We test the enforcer logic by simulating what handle_pre_tool_use does
acquire_lock(test_file, session_a)

# Simulate the enforcer check for session_b
_fp = test_file
_lock_info = is_locked(_fp, exclude_session=session_b)
test("enforcer integration: is_locked detects lock from other session",
     _lock_info is not None and _lock_info.get("session_id") == session_a)

release_lock(test_file, session_a)

# After release, should be clear
_lock_info = is_locked(_fp, exclude_session=session_b)
test("enforcer integration: is_locked clear after release", _lock_info is None)


# ── Cleanup ───────────────────────────────────────────────────────

# Restore original
flr_mod._get_lock_dir = _orig_get_lock_dir
shutil.rmtree(_test_lock_dir, ignore_errors=True)

# Print results
from tests.harness import PASS, FAIL, RESULTS
print()
for r in RESULTS:
    print(r)
print(f"\nTotal: {PASS} passed, {FAIL} failed")
print("\n=== File Lock Registry Tests Complete ===")
if FAIL > 0:
    sys.exit(1)
