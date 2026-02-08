"""Gate 3: TEST BEFORE DEPLOY (Tier 1 — Safety)

Blocks deployment commands (scp, rsync, ssh deploy, docker push, etc.)
unless tests have been run in the last 30 minutes.

This prevents shipping untested code to production.
"""

import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.gate_result import GateResult

GATE_NAME = "GATE 3: TEST BEFORE DEPLOY"

# Max time (seconds) since last test run before deploy is blocked
TEST_FRESHNESS_WINDOW = 1800  # 30 minutes

# Commands that indicate deployment
DEPLOY_PATTERNS = [
    r"\bscp\b.*\b\d+\.\d+\.\d+\.\d+\b",  # scp to IP address
    r"\bscp\b.*@.*:",                      # scp to hostname
    r"\brsync\b.*:",                         # rsync to remote
    r"\bdocker\s+push\b",                   # docker push
    r"\bkubectl\s+apply\b",                 # k8s deploy
    r"\bkubectl\s+rollout\b",              # k8s rollout
    r"\bgit\s+push\b.*\b(main|master|prod|production)\b",  # git push to main/prod branches
    r"\bssh\b.*deploy",                     # ssh deploy commands
    r"\bfab\s+deploy\b",                    # fabric deploy
    r"\bansible-playbook\b",               # ansible deploy
    r"\bcaprover\b",                        # CapRover deploy
    r"\bheroku\s+push\b",                  # heroku
    r"\bfly\s+deploy\b",                   # fly.io
    r"\bnpm\s+publish\b",                  # npm publish
    r"\bcargo\s+publish\b",                # cargo publish
    r"\btwine\s+upload\b",                 # twine upload (PyPI)
    r"\bgcloud\s+(app\s+deploy|run\s+deploy)\b",  # gcloud deploy
    r"\baws\s+s3\s+sync\b",               # aws s3 sync
]


def check(tool_name, tool_input, state, event_type="PreToolUse"):
    if event_type != "PreToolUse":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if tool_name != "Bash":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    command = tool_input.get("command", "")

    # Check if this looks like a deploy command
    is_deploy = False
    matched_pattern = ""
    for pattern in DEPLOY_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            is_deploy = True
            matched_pattern = pattern
            break

    if not is_deploy:
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Check if tests were run recently
    last_test = state.get("last_test_run", 0)
    elapsed = time.time() - last_test

    if elapsed > TEST_FRESHNESS_WINDOW:
        minutes_ago = int(elapsed / 60) if last_test > 0 else None
        if minutes_ago:
            msg = f"[{GATE_NAME}] BLOCKED: Tests last ran {minutes_ago} minutes ago. Run tests before deploying."
        else:
            msg = f"[{GATE_NAME}] BLOCKED: No tests have been run this session. Run tests before deploying."
        return GateResult(blocked=True, message=msg, gate_name=GATE_NAME)

    return GateResult(blocked=False, gate_name=GATE_NAME)
