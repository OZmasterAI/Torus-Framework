#!/usr/bin/env python3
"""Test edit streak tracking in Gate 5 and tracker.py"""
import sys
import os

_HOOKS_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(_HOOKS_DIR, "gates"))
sys.path.insert(0, _HOOKS_DIR)

from gate_05_proof_before_fixed import check as gate5_check
from tracker import handle_post_tool_use
from shared.state import load_state, save_state

def test_edit_streak():
    """Test that edit streak tracking works correctly."""
    # Initialize clean state
    state = {
        "pending_verification": [],
        "verification_scores": {},
        "edit_streak": {},
        "files_read": [],
        "tool_call_count": 0
    }

    test_file = "/tmp/sample_module.py"  # NOT test_* — G05 exempts test files

    print("Test 1: First edit should not trigger warning")
    handle_post_tool_use("Edit", {"file_path": test_file}, state, "test-session")
    assert state["edit_streak"][test_file] == 1, f"Expected streak=1, got {state['edit_streak'].get(test_file)}"
    result = gate5_check("Edit", {"file_path": test_file}, state)
    assert not result.blocked, "First edit should not block"
    print("✓ PASS")

    print("\nTest 2: Edit streak increments on subsequent edits")
    handle_post_tool_use("Edit", {"file_path": test_file}, state, "test-session")
    assert state["edit_streak"][test_file] == 2, f"Expected streak=2, got {state['edit_streak'].get(test_file)}"
    handle_post_tool_use("Edit", {"file_path": test_file}, state, "test-session")
    assert state["edit_streak"][test_file] == 3, f"Expected streak=3, got {state['edit_streak'].get(test_file)}"
    print("✓ PASS")

    print("\nTest 3: Warning at 4th edit (streak=3)")
    result = gate5_check("Edit", {"file_path": test_file}, state)
    assert not result.blocked, "4th edit should warn but not block"
    print("✓ PASS (warning issued)")

    print("\nTest 4: Continue to 6th edit")
    handle_post_tool_use("Edit", {"file_path": test_file}, state, "test-session")
    assert state["edit_streak"][test_file] == 4
    handle_post_tool_use("Edit", {"file_path": test_file}, state, "test-session")
    assert state["edit_streak"][test_file] == 5
    print("✓ PASS")

    print("\nTest 5: Block at 6th edit (streak=5)")
    result = gate5_check("Edit", {"file_path": test_file}, state)
    assert result.blocked, "6th edit should block"
    assert "6 times without verification" in result.message
    print("✓ PASS")

    print("\nTest 6: Bash command resets all streaks")
    handle_post_tool_use("Bash", {"command": "pytest"}, state, "test-session")
    assert state["edit_streak"] == {}, f"Expected empty dict, got {state['edit_streak']}"
    print("✓ PASS")

    print("\nTest 7: After reset, editing is allowed again")
    handle_post_tool_use("Edit", {"file_path": test_file}, state, "test-session")
    assert state["edit_streak"][test_file] == 1
    result = gate5_check("Edit", {"file_path": test_file}, state)
    assert not result.blocked, "After reset, first edit should not block"
    print("✓ PASS")

    print("\n" + "="*60)
    print("ALL TESTS PASSED ✓")
    print("="*60)

if __name__ == "__main__":
    test_edit_streak()
