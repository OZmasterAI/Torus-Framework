"""Outcome Chains (Module D) — sequence analysis for tool call patterns.

Fires every 10th PostToolUse call. Detects churn, stuck loops, and healthy patterns.
Called from orchestrator.py with the mentor_outcome_chains toggle.
"""
from typing import Optional

from tracker_pkg import _log_debug


# Pattern definitions
CHURN_PATTERN = ["Edit", "Edit", "Edit", "Bash"]  # edit-edit-edit-test = churn
HEALTHY_PATTERNS = [
    ["Read", "Edit", "Bash"],     # read-edit-test
    ["Grep", "Read", "Edit"],     # search-read-edit
    ["Glob", "Read", "Edit"],     # find-read-edit
]

STUCK_THRESHOLD = 0.7  # 70% same tool in window = stuck
WINDOW_SIZE = 20       # last 20 tool calls


def evaluate(tool_name, tool_input, tool_response, state):
    """Evaluate tool call sequences every 10th call.

    Updates state["mentor_chain_pattern"] and state["mentor_chain_score"].
    Returns a dict {"pattern": str, "score": float, "message": str} or None.
    """
    try:
        tool_call_count = state.get("tool_call_count", 0)
        # Only fire every 10th call
        if tool_call_count % 10 != 0:
            return None

        # Build recent tool sequence from tool_call_counts
        # We use the capture queue approach — but for simplicity, use state's tool_call_counts
        # to derive recent patterns
        tool_counts = state.get("tool_call_counts", {})
        total = state.get("total_tool_calls", 0)

        if total < 10:
            return None

        pattern = ""
        score = 1.0
        message = ""

        # Check 1: Stuck loop — one tool dominates
        if tool_counts:
            max_tool = max(tool_counts, key=lambda t: tool_counts[t])
            max_count = tool_counts[max_tool]
            ratio = max_count / total if total > 0 else 0
            if ratio >= STUCK_THRESHOLD:
                pattern = "stuck"
                score = 0.2
                message = f"Stuck loop: {max_tool} is {ratio:.0%} of last {total} calls"

        # Check 2: Churn detection — high edit count with low test pass rate
        if not pattern:
            edit_count = sum(tool_counts.get(t, 0) for t in ("Edit", "Write", "NotebookEdit"))
            test_count = tool_counts.get("Bash", 0)  # Approximation
            if edit_count > 0 and total > 0:
                edit_ratio = edit_count / total
                if edit_ratio > 0.6 and test_count < edit_count * 0.3:
                    pattern = "churn"
                    score = 0.3
                    message = f"Edit churn: {edit_count} edits vs {test_count} bash calls (edit ratio {edit_ratio:.0%})"

        # Check 3: Healthy patterns — good read/edit/test ratio
        if not pattern:
            read_count = sum(tool_counts.get(t, 0) for t in ("Read", "Grep", "Glob"))
            edit_count = sum(tool_counts.get(t, 0) for t in ("Edit", "Write"))
            test_count = tool_counts.get("Bash", 0)
            if read_count > 0 and edit_count > 0 and test_count > 0:
                # Healthy ratio: reads >= edits, tests > 0
                if read_count >= edit_count * 0.5 and test_count >= edit_count * 0.3:
                    pattern = "healthy"
                    score = 0.9
                    message = f"Healthy pattern: {read_count}R/{edit_count}E/{test_count}T"

        if not pattern:
            pattern = ""
            score = 0.7  # Neutral

        # Update state
        state["mentor_chain_pattern"] = pattern
        state["mentor_chain_score"] = score

        _log_debug(f"outcome_chains: pattern={pattern} score={score:.2f}")

        return {"pattern": pattern, "score": score, "message": message}

    except Exception as e:
        _log_debug(f"outcome_chains.evaluate failed (non-blocking): {e}")
        return None
