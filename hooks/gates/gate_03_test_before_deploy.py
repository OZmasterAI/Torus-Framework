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
    (r"\bscp\b.*\b\d+\.\d+\.\d+\.\d+\b", "remote copy"),
    (r"\bscp\b.*@.*:", "remote copy"),
    (r"\brsync\b.*:", "remote sync"),
    (r"\bdocker\s+push\b", "container"),
    (r"\bkubectl\s+apply\b", "kubernetes"),
    (r"\bkubectl\s+rollout\b", "kubernetes"),
    (r"\bgit\s+push\b.*\b(main|master|prod|production)\b", "git production"),
    (r"\bssh\b.*deploy", "remote deploy"),
    (r"\bfab\s+deploy\b", "fabric"),
    (r"\bansible-playbook\b", "ansible"),
    (r"\bcaprover\b", "caprover"),
    (r"\bheroku\s+push\b", "heroku"),
    (r"\bfly\s+deploy\b", "fly.io"),
    (r"\bnpm\s+publish\b", "package publish"),
    (r"\bcargo\s+publish\b", "package publish"),
    (r"\btwine\s+upload\b", "package publish"),
    (r"\bgcloud\s+(app\s+deploy|run\s+deploy)\b", "gcloud"),
    (r"\baws\s+s3\s+sync\b", "aws"),
    (r"\bhelm\s+(upgrade|install)\b", "helm"),
    (r"\bterraform\s+apply\b", "terraform"),
    (r"\bpulumi\s+up\b", "pulumi"),
    (r"\bserverless\s+deploy\b", "serverless"),
    (r"\bcdk\s+deploy\b", "aws cdk"),
    (r"\bnpm\s+run\s+deploy\b", "npm deploy"),
    (r"\byarn\s+deploy\b", "yarn deploy"),
    (r"\bvercel\b.*--prod\b", "vercel"),
    (r"\bnetlify\s+deploy\b.*--prod\b", "netlify"),
    (r"\brailway\s+up\b", "railway"),
    (r"\bamplify\s+publish\b", "aws amplify"),
]


def _detect_test_framework(state):
    """Detect the test framework from recent test commands in state.

    Returns a string like "pytest", "npm test", "cargo test", or "unknown".
    """
    # Check last test command if available
    last_test_cmd = state.get("last_test_command", "")
    if "test_framework" in last_test_cmd:
        return "python3 test_framework.py"
    if "pytest" in last_test_cmd or "python -m pytest" in last_test_cmd:
        return "pytest"
    if "npm test" in last_test_cmd:
        return "npm test"
    if "cargo test" in last_test_cmd:
        return "cargo test"
    if "go test" in last_test_cmd:
        return "go test"
    if "make test" in last_test_cmd:
        return "make test"

    # Fallback: check tool_stats for Bash commands (no specific command stored)
    tool_stats = state.get("tool_stats", {})
    if tool_stats.get("Bash", {}).get("count", 0) > 0:
        return "pytest"  # Default suggestion for Python projects

    return "unknown"


def check(tool_name, tool_input, state, event_type="PreToolUse"):
    if event_type != "PreToolUse":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if tool_name != "Bash":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if not isinstance(tool_input, dict):
        tool_input = {}

    command = tool_input.get("command", "")

    # Check if this looks like a deploy command
    is_deploy = False
    matched_category = None
    for pattern, category in DEPLOY_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            is_deploy = True
            matched_category = category
            break

    if not is_deploy:
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Check if tests were run recently
    last_test = state.get("last_test_run", 0)
    elapsed = time.time() - last_test

    if elapsed > TEST_FRESHNESS_WINDOW:
        framework = _detect_test_framework(state)
        hint = f" Try: {framework}" if framework != "unknown" else ""
        minutes_ago = int(elapsed / 60) if last_test > 0 else None
        if minutes_ago:
            msg = f"[{GATE_NAME}] BLOCKED: Deploy ({matched_category}) attempted but tests last ran {minutes_ago} minutes ago. Run tests before deploying.{hint}"
        else:
            msg = f"[{GATE_NAME}] BLOCKED: Deploy ({matched_category}) attempted but no tests have been run this session. Run tests before deploying.{hint}"
        return GateResult(blocked=True, message=msg, gate_name=GATE_NAME)

    # Check if last test run actually passed
    last_exit_code = state.get("last_test_exit_code", None)
    if last_exit_code is not None and last_exit_code != 0:
        return GateResult(
            blocked=True,
            message=f"[{GATE_NAME}] BLOCKED: Deploy ({matched_category}) attempted but last test run failed (exit code: {last_exit_code}). Fix tests before deploying.",
            gate_name=GATE_NAME,
        )

    return GateResult(blocked=False, gate_name=GATE_NAME)
