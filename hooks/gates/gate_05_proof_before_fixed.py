"""Gate 5: PROOF BEFORE FIXED (Tier 2 — Quality)

After editing a file, blocks further edits to OTHER files until the
previous edit has been verified (by running a command, test, or check).

This prevents the pattern where Claude says "fixed" and moves on
without ever verifying the fix actually works.

Blocks immediately at BLOCK_THRESHOLD unverified files (no warn phase).

The pending_verification list is cleared when:
- A Bash command is run (tests, running scripts, curl, etc.)
- Only the specific verified files are cleared
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.gate_result import GateResult
from shared.gate_helpers import extract_file_path, is_test_file, safe_tool_input

GATE_NAME = "GATE 5: PROOF BEFORE FIXED"

# Block immediately at this many unverified files (no warn phase)
BLOCK_THRESHOLD = 3

from shared.exemptions import is_exempt_base as is_exempt


def check(tool_name, tool_input, state, event_type="PreToolUse"):
    if event_type != "PreToolUse":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if tool_name not in ("Edit", "Write", "NotebookEdit"):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    tool_input = safe_tool_input(tool_input)

    file_path = extract_file_path(tool_input)

    # Check exemptions
    if is_exempt(file_path):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Test files are inherently verification — exempt from proof requirements
    if is_test_file(file_path):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Check pending verifications with progressive scoring
    pending = state.get("pending_verification", [])
    verification_scores = state.get("verification_scores", {})

    # Allow editing the same file that's pending (iterating on a fix)
    pending_other = [p for p in pending if p != file_path]

    # Track consecutive edits to the same file without verification
    edit_streak = state.get("edit_streak", {})
    current_streak = edit_streak.get(file_path, 0)

    # Warn at 4+ same-file edits without verification
    if current_streak >= 3:
        print(
            f"[{GATE_NAME}] WARNING: {os.path.basename(file_path)} edited "
            f"{current_streak + 1} times without verification. "
            f"Run any Bash command (test, lint, script) to verify and reset the counter.",
            file=sys.stderr,
        )

    # Block at 6+ same-file edits without verification
    if current_streak >= 5:
        return GateResult(
            blocked=True,
            message=f"[{GATE_NAME}] BLOCKED: {os.path.basename(file_path)} edited "
                    f"{current_streak + 1} times without verification. "
                    f"Run any Bash command (test, script, or check) to reset and continue.",
            gate_name=GATE_NAME,
        )

    # Count effective unverified: partially scored files count less
    effective_unverified = 0.0
    for p in pending_other:
        score = verification_scores.get(p, 0)
        if score > 0:
            effective_unverified += 0.5  # Partial verification reduces urgency
        else:
            effective_unverified += 1.0

    tune = state.get("gate_tune_overrides", {}).get("gate_05_proof_before_fixed", {})
    block_at = tune.get("block_threshold", BLOCK_THRESHOLD)

    if effective_unverified >= block_at:
        file_list = ", ".join(os.path.basename(p) for p in pending_other[:5])
        return GateResult(
            blocked=True,
            message=f"[{GATE_NAME}] BLOCKED: {len(pending_other)} files with unverified edits ({file_list}). Run any Bash command (pytest, python script, etc.) to verify and clear pending files.",
            gate_name=GATE_NAME,
        )

    return GateResult(blocked=False, gate_name=GATE_NAME)
