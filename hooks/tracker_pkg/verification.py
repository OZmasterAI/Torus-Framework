"""Verification scoring and gate block outcome resolution."""
import re
import time

from shared.state import update_gate_effectiveness

BROAD_TEST_COMMANDS = ["pytest", "python -m pytest", "npm test", "cargo test", "go test", "make test"]


def _classify_verification_score(command):
    """Classify a Bash command's verification confidence score.

    Returns an integer score:
      - Full test suite (pytest, npm test, make test, cargo test) = 100
      - Targeted test (pytest test_specific.py, jest file.test.js) = 70
      - Running a script (python script.py, node script.js) = 50
      - Generic commands (ls, git status, echo, cat) = 10
      - Other commands = 30
    """
    for kw in BROAD_TEST_COMMANDS:
        if kw in command:
            rest = command.split(kw, 1)[1].strip()
            # Specific test file or test selector
            if re.search(r'\btest_\w+\.py\b', rest) or '::' in rest:
                return 70  # Targeted test
            if re.search(r'\w+\.test\.(js|ts|tsx)\b', rest):
                return 70  # Jest-style targeted test
            return 100  # Full test suite

    script_runners = ["python ", "python3 ", "node ", "ruby ", "bash ", "sh ", "./"]
    if any(kw in command for kw in script_runners):
        return 50

    generic_cmds = ["ls", "git status", "echo ", "cat ", "pwd", "which "]
    if any(kw in command for kw in generic_cmds):
        return 10

    return 30


def _resolve_gate_block_outcomes(tool_name, tool_input, state):
    """Resolve pending gate block outcomes for effectiveness tracking.

    When a tool call succeeds after a previous block on the same tool+file combo,
    it means the user worked around the block (override) or the block forced a
    better approach (prevented). We distinguish by checking if fix_history was
    queried or memory was checked between the block and the success.
    """
    try:
        outcomes = state.get("gate_block_outcomes", [])
        if not outcomes:
            return

        file_path = tool_input.get("file_path", "") or tool_input.get("notebook_path", "") or tool_input.get("command", "")[:100]
        if not file_path:
            return

        now = time.time()
        remaining = []
        for outcome in outcomes:
            if outcome.get("resolved_by") is not None:
                remaining.append(outcome)
                continue
            # Match: same tool+file combo, within 30 minutes
            if outcome.get("tool") == tool_name and outcome.get("file") == file_path and (now - outcome.get("timestamp", 0)) < 1800:
                gate = outcome.get("gate", "")
                # If memory was queried after the block, it's "prevented" (block forced better approach)
                mem_ts = state.get("memory_last_queried", 0)
                fix_ts = state.get("fix_history_queried", 0)
                block_ts = outcome.get("timestamp", 0)
                if mem_ts > block_ts or fix_ts > block_ts:
                    update_gate_effectiveness(gate, "prevented")
                    outcome["resolved_by"] = "prevented"
                else:
                    update_gate_effectiveness(gate, "overrides")
                    outcome["resolved_by"] = "override"
            remaining.append(outcome)

        # Prune resolved outcomes older than 30 minutes
        state["gate_block_outcomes"] = [o for o in remaining if (now - o.get("timestamp", 0)) < 1800 or o.get("resolved_by") is None]
    except Exception:
        pass  # Effectiveness tracking is fail-open
