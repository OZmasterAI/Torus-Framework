#!/usr/bin/env python3
"""Plan verification loop for /prp plan-phase.

Runs task_manager.py plan-check against requirements, analyzes gaps,
and outputs a revision report. The /prp skill uses this output to
decide whether to revise the plan.

Usage: python3 prp-plan-verify.py <prp-name> <requirements-file> [--round N]

Exit codes:
  0 = plan covers all requirements (pass)
  1 = gaps found (revision needed)
  2 = error (bad args, missing files)
"""

import json
import os
import subprocess
import sys

PRP_DIR = os.path.expanduser("~/.claude/PRPs")
TASK_MANAGER = os.path.join(PRP_DIR, "task_manager.py")
MAX_ROUNDS = 2


def run_plan_check(prp_name, requirements_file):
    """Run plan-check and return parsed result."""
    result = subprocess.run(
        [sys.executable, TASK_MANAGER, "plan-check", prp_name, requirements_file],
        capture_output=True, text=True, timeout=30,
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def load_requirements_text(requirements_file):
    """Load requirement details for gap analysis."""
    if not os.path.exists(requirements_file):
        return {}
    with open(requirements_file) as f:
        content = f.read()

    # Parse requirement blocks: ### R1: Name\n- **Phase**: ...\n- **Acceptance**: ...
    import re
    reqs = {}
    for match in re.finditer(
        r"###\s+(R\d+):\s*(.+?)(?=\n###|\n## |\Z)", content, re.DOTALL
    ):
        rid = match.group(1)
        block = match.group(2).strip()
        # Extract acceptance criteria
        acceptance = ""
        acc_match = re.search(r"\*\*Acceptance\*\*:\s*(.+)", block)
        if acc_match:
            acceptance = acc_match.group(1).strip()
        reqs[rid] = {"name": block.split("\n")[0].strip(), "acceptance": acceptance}
    return reqs


def main():
    if len(sys.argv) < 3:
        print("Usage: prp-plan-verify.py <prp-name> <requirements-file> [--round N]", file=sys.stderr)
        sys.exit(2)

    prp_name = sys.argv[1]
    requirements_file = sys.argv[2]

    current_round = 1
    if "--round" in sys.argv:
        idx = sys.argv.index("--round")
        if idx + 1 < len(sys.argv):
            current_round = int(sys.argv[idx + 1])

    # Run plan-check
    check_result = run_plan_check(prp_name, requirements_file)
    if check_result is None:
        print(json.dumps({"error": "plan-check failed to return valid JSON"}))
        sys.exit(2)

    # If pass, report success
    if check_result.get("pass"):
        report = {
            "status": "pass",
            "round": current_round,
            "total_requirements": check_result["total_requirements"],
            "covered": check_result["covered"],
            "message": f"All {check_result['total_requirements']} requirements covered by tasks.",
        }
        print(json.dumps(report, indent=2))
        sys.exit(0)

    # Gaps found — build revision report
    reqs_text = load_requirements_text(requirements_file)
    uncovered_details = []
    for rid in check_result.get("uncovered", []):
        detail = {"requirement_id": rid}
        if rid in reqs_text:
            detail["name"] = reqs_text[rid]["name"]
            detail["acceptance"] = reqs_text[rid]["acceptance"]
        detail["action"] = f"Add task(s) to cover {rid}"
        uncovered_details.append(detail)

    orphan_details = []
    for orphan in check_result.get("orphan_tasks", []):
        orphan_details.append({
            "task_id": orphan["task_id"],
            "requirement_id": orphan["requirement_id"],
            "action": f"Map task {orphan['task_id']} to a valid requirement or remove it",
        })

    can_revise = current_round < MAX_ROUNDS
    report = {
        "status": "gaps_found",
        "round": current_round,
        "max_rounds": MAX_ROUNDS,
        "can_revise": can_revise,
        "total_requirements": check_result["total_requirements"],
        "covered": check_result["covered"],
        "uncovered": uncovered_details,
        "orphan_tasks": orphan_details,
        "message": (
            f"Round {current_round}/{MAX_ROUNDS}: "
            f"{len(uncovered_details)} uncovered requirement(s), "
            f"{len(orphan_details)} orphan task(s). "
            + ("Revise and re-check." if can_revise else "Max rounds reached — flag to user.")
        ),
    }
    print(json.dumps(report, indent=2))
    sys.exit(1)


if __name__ == "__main__":
    main()
