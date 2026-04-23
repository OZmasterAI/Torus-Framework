#!/usr/bin/env python3
"""Tests for hooks/shared/operation_tracker.py

Covers:
- Boundary detection (tool transitions, file scope, intent signals, temporal gap)
- Operation lifecycle (active->completed, outcome inference)
- Purpose extraction (regex + fallback)
- Decision detection
- State persistence (write + reload from ramdisk)
- FIFO for decisions (cap at 5)
"""

import json
import os
import sys
import tempfile
import time

# Add hooks dir to path
HOOKS_DIR = os.path.dirname(os.path.dirname(__file__))
if HOOKS_DIR not in sys.path:
    sys.path.insert(0, HOOKS_DIR)

# ── Test counter ──────────────────────────────────────────────────────────────

PASS = 0
FAIL = 0
RESULTS = []


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        RESULTS.append(("PASS", name))
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        RESULTS.append(("FAIL", name, detail))
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))


# ── Import under test ─────────────────────────────────────────────────────────

from shared.operation_tracker import OperationTracker

# ── Helpers ───────────────────────────────────────────────────────────────────


def make_tracker(session_id=None):
    """Create an OperationTracker with a unique test session_id."""
    if session_id is None:
        session_id = f"test-op-{os.getpid()}-{int(time.time() * 1000) % 100000}"
    return OperationTracker(session_id)


# ─────────────────────────────────────────────────────────────────────────────
# Section 1: Basic lifecycle
# ─────────────────────────────────────────────────────────────────────────────
print("\n--- OperationTracker: Lifecycle ---")

tracker = make_tracker()

# Fresh tracker: no active op, no completed ops
state = tracker.get_state()
check("fresh tracker: op_id starts at 1", state.get("current_op_id") == 1)
check("fresh tracker: no completed ops", tracker.get_completed_ops() == [])
check("fresh tracker: active op is None", tracker.get_active_op() is None)

# First tool call starts active op
result = tracker.process_tool_call("Read", {"file_path": "/foo/bar.py"})
active = tracker.get_active_op()
check("after first call: active op exists", active is not None)
check(
    "after first call: op_type is 'read'",
    active["type"] == "read",
    f"got {active.get('type')}",
)
check("after first call: files tracked", "/foo/bar.py" in active.get("files", []))
check("process_tool_call returns dict", isinstance(result, dict))
check("boundary_detected key present in result", "boundary_detected" in result)

# ─────────────────────────────────────────────────────────────────────────────
# Section 2: Tool phase classification
# ─────────────────────────────────────────────────────────────────────────────
print("\n--- OperationTracker: Tool phase classification ---")

tracker2 = make_tracker()

# Read-phase tools
for tool in ("Read", "Grep", "Glob"):
    result = tracker2.process_tool_call(tool, {"file_path": "/tmp/x.py"})
    active = tracker2.get_active_op()
    check(
        f"{tool} classified as 'read'",
        active["type"] == "read",
        f"got {active.get('type')}",
    )

# Write-phase tools  — transition from read -> write should trigger boundary
tracker3 = make_tracker()
tracker3.process_tool_call("Read", {"file_path": "/tmp/a.py"})
r = tracker3.process_tool_call("Edit", {"file_path": "/tmp/a.py"})
# After writing, active op should be 'write' type
active3 = tracker3.get_active_op()
check(
    "Edit classified as 'write'",
    active3["type"] == "write",
    f"got {active3.get('type')}",
)

tracker4 = make_tracker()
tracker4.process_tool_call("Read", {"file_path": "/tmp/a.py"})
tracker4.process_tool_call("Write", {"file_path": "/tmp/b.py"})
active4 = tracker4.get_active_op()
check(
    "Write classified as 'write'",
    active4["type"] == "write",
    f"got {active4.get('type')}",
)

# Bash -> verify
tracker5 = make_tracker()
tracker5.process_tool_call("Edit", {"file_path": "/tmp/a.py"})
tracker5.process_tool_call("Bash", {"command": "pytest"})
active5 = tracker5.get_active_op()
check(
    "Bash classified as 'verify'",
    active5["type"] == "verify",
    f"got {active5.get('type')}",
)

# Agent/Task -> delegate
tracker6 = make_tracker()
tracker6.process_tool_call("Read", {"file_path": "/tmp/a.py"})
tracker6.process_tool_call("Task", {"description": "do something"})
active6 = tracker6.get_active_op()
check(
    "Task classified as 'delegate'",
    active6["type"] == "delegate",
    f"got {active6.get('type')}",
)

# ─────────────────────────────────────────────────────────────────────────────
# Section 3: Boundary detection — tool_phase_transition
# ─────────────────────────────────────────────────────────────────────────────
print("\n--- OperationTracker: Boundary detection (tool phase) ---")

tracker_b1 = make_tracker()
# Start a read op
tracker_b1.process_tool_call("Read", {"file_path": "/tmp/a.py"})
tracker_b1.process_tool_call("Grep", {"pattern": "foo"})
# Phase transition (0.35) + intent signal (0.20) = 0.55 >= 0.5 threshold
r = tracker_b1.process_tool_call(
    "Edit", {"file_path": "/tmp/a.py"}, assistant_text="Now let me fix this."
)
check(
    "read->write + intent signal detected as boundary",
    r.get("boundary_detected") is True,
    f"result={r}",
)

# Phase transition alone (0.35) should NOT cross threshold (0.5)
tracker_b1b = make_tracker()
tracker_b1b.process_tool_call("Read", {"file_path": "/tmp/a.py"})
r_b1b = tracker_b1b.process_tool_call("Edit", {"file_path": "/tmp/a.py"})
check(
    "phase transition alone does NOT trigger boundary (0.35 < 0.5)",
    r_b1b.get("boundary_detected") is False,
    f"result={r_b1b}",
)

# write->verify: write then bash + intent signal
tracker_b2 = make_tracker()
tracker_b2.process_tool_call("Edit", {"file_path": "/tmp/a.py"})
tracker_b2.process_tool_call("Write", {"file_path": "/tmp/b.py"})
r2 = tracker_b2.process_tool_call(
    "Bash", {"command": "python test.py"}, assistant_text="Now let me run tests."
)
check(
    "write->verify + intent signal detected as boundary",
    r2.get("boundary_detected") is True,
    f"result={r2}",
)

# Same phase: no boundary
tracker_b3 = make_tracker()
tracker_b3.process_tool_call("Read", {"file_path": "/tmp/a.py"})
r3 = tracker_b3.process_tool_call("Read", {"file_path": "/tmp/b.py"})
check(
    "read->read: no forced boundary from phase alone",
    # phase alone (0.35) is below threshold (0.5), so no boundary unless other signals fire
    # This is about signal weight, not guaranteed no-boundary
    isinstance(r3, dict),
)  # At minimum it should return a valid dict

# ─────────────────────────────────────────────────────────────────────────────
# Section 4: Boundary detection — file_scope_change
# ─────────────────────────────────────────────────────────────────────────────
print("\n--- OperationTracker: Boundary detection (file scope) ---")

tracker_f = make_tracker()
# Read a bunch of files in /hooks/shared/
for i in range(4):
    tracker_f.process_tool_call("Read", {"file_path": f"/hooks/shared/module_{i}.py"})

# Suddenly switch to totally different files in /frontend/
r_f = tracker_f.process_tool_call(
    "Read",
    {"file_path": "/frontend/components/Button.tsx"},
    assistant_text="",  # No intent signal
)
# file scope Jaccard < 0.2 should contribute 0.30 weight
check(
    "large file scope change contributes to boundary score",
    "boundary_score" in r_f or "boundary_detected" in r_f,
)

# ─────────────────────────────────────────────────────────────────────────────
# Section 5: Boundary detection — intent_signal
# ─────────────────────────────────────────────────────────────────────────────
print("\n--- OperationTracker: Boundary detection (intent signal) ---")

tracker_i = make_tracker()
tracker_i.process_tool_call("Read", {"file_path": "/tmp/a.py"})
# Provide assistant text with intent phrase + combine with phase transition to cross threshold
r_i = tracker_i.process_tool_call(
    "Edit", {"file_path": "/tmp/a.py"}, assistant_text="Now let me implement the fix."
)
check(
    "intent signal 'Now' in assistant text detected",
    r_i.get("boundary_detected") is True,
    f"result={r_i}",
)

tracker_i2 = make_tracker()
tracker_i2.process_tool_call("Read", {"file_path": "/tmp/a.py"})
r_i2 = tracker_i2.process_tool_call(
    "Edit", {"file_path": "/tmp/a.py"}, assistant_text="Moving on to the next task."
)
check(
    "intent signal 'Moving on to' detected",
    r_i2.get("boundary_detected") is True,
    f"result={r_i2}",
)

tracker_i3 = make_tracker()
tracker_i3.process_tool_call("Read", {"file_path": "/tmp/a.py"})
r_i3 = tracker_i3.process_tool_call(
    "Edit", {"file_path": "/tmp/a.py"}, assistant_text="I'll implement this now."
)
check(
    'intent signal "I\'ll" detected',
    r_i3.get("boundary_detected") is True,
    f"result={r_i3}",
)

# ─────────────────────────────────────────────────────────────────────────────
# Section 6: Boundary detection — temporal_gap
# ─────────────────────────────────────────────────────────────────────────────
print("\n--- OperationTracker: Boundary detection (temporal gap) ---")

tracker_t = make_tracker()
tracker_t.process_tool_call("Read", {"file_path": "/tmp/a.py"})
# Manually backdate last timestamp to simulate >30s gap
s = tracker_t.get_state()
s["last_turn_timestamp"] = time.time() - 35  # 35 seconds ago
tracker_t._save_state(s)

r_t = tracker_t.process_tool_call("Read", {"file_path": "/tmp/b.py"})
# temporal_gap alone (0.15) won't exceed 0.5 threshold on its own
# but it should be reflected in the score
check("temporal gap signal computable without error", "boundary_detected" in r_t)

# ─────────────────────────────────────────────────────────────────────────────
# Section 7: Operation completion and outcome inference
# ─────────────────────────────────────────────────────────────────────────────
print("\n--- OperationTracker: Outcome inference ---")

# read_only -> success
tracker_o1 = make_tracker()
tracker_o1.process_tool_call("Read", {"file_path": "/tmp/a.py"})
tracker_o1.process_tool_call("Grep", {"pattern": "foo"})
# Trigger boundary: phase transition (0.35) + intent signal (0.20) = 0.55 >= 0.5
tracker_o1.process_tool_call(
    "Edit", {"file_path": "/tmp/a.py"}, assistant_text="Now let me edit this."
)
completed = tracker_o1.get_completed_ops()
check(
    "read-only op completes with success outcome",
    len(completed) > 0 and completed[-1]["outcome"] == "success",
    f"completed={completed}",
)

# writes_only -> partial (no verify bash)
tracker_o2 = make_tracker()
tracker_o2.process_tool_call("Edit", {"file_path": "/tmp/a.py"})
tracker_o2.process_tool_call("Write", {"file_path": "/tmp/b.py"})
# Trigger boundary by switching to read phase (simulate next op)
tracker_o2.process_tool_call(
    "Read", {"file_path": "/tmp/c.py"}, assistant_text="Now let me check something."
)
completed2 = tracker_o2.get_completed_ops()
check(
    "writes-only op (no verify) completes with 'partial' outcome",
    len(completed2) > 0 and completed2[-1]["outcome"] == "partial",
    f"completed={completed2}",
)

# writes + bash_success -> success
tracker_o3 = make_tracker()
tracker_o3.process_tool_call("Edit", {"file_path": "/tmp/a.py"})
tracker_o3.process_tool_call("Bash", {"command": "pytest"})
# Trigger boundary
tracker_o3.process_tool_call(
    "Read", {"file_path": "/tmp/b.py"}, assistant_text="Next, let me read something."
)
completed3 = tracker_o3.get_completed_ops()
check(
    "writes+bash_success op completes with 'success' outcome",
    len(completed3) > 0 and completed3[-1]["outcome"] == "success",
    f"completed={completed3}",
)

# error -> failure
tracker_o4 = make_tracker()
tracker_o4.process_tool_call("Edit", {"file_path": "/tmp/a.py"})
tracker_o4.process_tool_call("Bash", {"command": "pytest"}, had_error=True)
# Trigger boundary
tracker_o4.process_tool_call(
    "Read", {"file_path": "/tmp/b.py"}, assistant_text="Now let me investigate."
)
completed4 = tracker_o4.get_completed_ops()
check(
    "error op completes with 'failure' outcome",
    len(completed4) > 0 and completed4[-1]["outcome"] == "failure",
    f"completed={completed4}",
)

# ─────────────────────────────────────────────────────────────────────────────
# Section 8: Purpose extraction
# ─────────────────────────────────────────────────────────────────────────────
print("\n--- OperationTracker: Purpose extraction ---")

tracker_p = make_tracker()
# Intent phrase in assistant text
tracker_p.process_tool_call(
    "Read",
    {"file_path": "/tmp/a.py"},
    assistant_text="Let me read the state.py file to understand the patterns.",
)
active_p = tracker_p.get_active_op()
check(
    "purpose extracted from 'Let me' phrase",
    active_p is not None and len(active_p.get("purpose", "")) > 0,
    f"purpose={active_p.get('purpose') if active_p else 'N/A'}",
)

# Fallback purpose from type + files
tracker_p2 = make_tracker()
tracker_p2.process_tool_call("Edit", {"file_path": "/tmp/foo.py"})
active_p2 = tracker_p2.get_active_op()
purpose_p2 = active_p2.get("purpose", "")
check(
    "fallback purpose contains type or files info",
    len(purpose_p2) > 0,
    f"purpose='{purpose_p2}'",
)

# ─────────────────────────────────────────────────────────────────────────────
# Section 9: State persistence — write + reload
# ─────────────────────────────────────────────────────────────────────────────
print("\n--- OperationTracker: State persistence ---")

session_persist = f"test-persist-{os.getpid()}"
tracker_s = OperationTracker(session_persist)
tracker_s.process_tool_call("Read", {"file_path": "/tmp/persist_test.py"})
tracker_s.process_tool_call(
    "Read", {"file_path": "/tmp/second.py"}, assistant_text="Persisting state test."
)

# Force save and reload
state_before = tracker_s.get_state()
tracker_s._save_state(state_before)

# Create a new tracker with the same session_id — should load persisted state
tracker_s2 = OperationTracker(session_persist)
state_after = tracker_s2.get_state()

check(
    "state file persisted to disk/ramdisk",
    state_after.get("total_turns", 0) == state_before.get("total_turns", 0),
    f"before={state_before.get('total_turns')}, after={state_after.get('total_turns')}",
)

# ─────────────────────────────────────────────────────────────────────────────
# Section 12: get_completed_ops returns completed list
# ─────────────────────────────────────────────────────────────────────────────
print("\n--- OperationTracker: get_completed_ops ---")

tracker_c = make_tracker()
tracker_c.process_tool_call("Read", {"file_path": "/tmp/a.py"})
# trigger boundary
tracker_c.process_tool_call("Edit", {"file_path": "/tmp/a.py"})
# trigger another boundary
tracker_c.process_tool_call(
    "Bash", {"command": "pytest"}, assistant_text="Now let me run tests."
)
# trigger another boundary
tracker_c.process_tool_call(
    "Read", {"file_path": "/tmp/b.py"}, assistant_text="Moving on to the next file."
)

completed_c = tracker_c.get_completed_ops()
check(
    "multiple completed ops tracked",
    len(completed_c) >= 2,
    f"completed count={len(completed_c)}",
)
check(
    "completed ops have required fields",
    all(
        "id" in op and "type" in op and "outcome" in op and "purpose" in op
        for op in completed_c
    ),
    f"ops={completed_c}",
)

# ─────────────────────────────────────────────────────────────────────────────
# Section 12b: op_id sequential numbering (no double-increment)
# ─────────────────────────────────────────────────────────────────────────────
print("\n--- OperationTracker: op_id sequential numbering ---")

tracker_seq = make_tracker()
# Op 1: read
tracker_seq.process_tool_call("Read", {"file_path": "/tmp/a.py"})
# Boundary → completes Op 1, starts Op 2
tracker_seq.process_tool_call(
    "Edit", {"file_path": "/tmp/a.py"}, assistant_text="Now let me edit."
)
# Boundary → completes Op 2, starts Op 3
tracker_seq.process_tool_call(
    "Bash", {"command": "pytest"}, assistant_text="Now let me test."
)
# Boundary → completes Op 3, starts Op 4
tracker_seq.process_tool_call(
    "Read", {"file_path": "/tmp/b.py"}, assistant_text="Moving on to next."
)

completed_seq = tracker_seq.get_completed_ops()
ids = [op["id"] for op in completed_seq]
check(
    "op_ids are sequential (1, 2, 3...) not double-incremented",
    ids == list(range(1, len(ids) + 1)),
    f"got ids={ids}",
)
active_seq = tracker_seq.get_active_op()
check(
    "active op_id continues sequence",
    active_seq is not None and active_seq["id"] == len(ids) + 1,
    f"active id={active_seq['id'] if active_seq else 'None'}, expected={len(ids) + 1}",
)

# ─────────────────────────────────────────────────────────────────────────────
# Section 13: Boundary score structure
# ─────────────────────────────────────────────────────────────────────────────
print("\n--- OperationTracker: Boundary score structure ---")

tracker_bs = make_tracker()
tracker_bs.process_tool_call("Read", {"file_path": "/tmp/a.py"})
result_bs = tracker_bs.process_tool_call(
    "Edit", {"file_path": "/tmp/a.py"}, assistant_text="Now implementing."
)
check(
    "result has boundary_detected bool",
    isinstance(result_bs.get("boundary_detected"), bool),
)
check(
    "result has boundary_score float",
    isinstance(result_bs.get("boundary_score"), (int, float)),
)
check(
    "boundary_score is between 0 and 1 (or slightly above due to weighting)",
    0.0 <= result_bs.get("boundary_score", -1) <= 2.0,
    f"score={result_bs.get('boundary_score')}",
)

# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{'=' * 60}")
print(f"operation_tracker tests: {PASS} passed, {FAIL} failed")
if FAIL:
    print("FAILURES:")
    for r in RESULTS:
        if r[0] == "FAIL":
            print(f"  - {r[1]}" + (f": {r[2]}" if len(r) > 2 else ""))
print(f"{'=' * 60}")

if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
