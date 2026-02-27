#!/usr/bin/env python3
"""Post-phase verification for /prp verify-phase.

Runs task_manager.py verify-phase, analyzes failures by level,
and optionally creates fix tasks in the tasks.json.

Usage: python3 prp-phase-verify.py <prp-name> [--auto-fix]

Exit codes:
  0 = all tasks verified (pass)
  1 = verification failures found
  2 = error (bad args, missing files)
"""

import json
import os
import subprocess
import sys
PRP_DIR = os.path.expanduser("~/.claude/PRPs")
TASK_MANAGER = os.path.join(PRP_DIR, "task_manager.py")


def run_verify_phase(prp_name):
    """Run verify-phase and return parsed result."""
    result = subprocess.run(
        [sys.executable, TASK_MANAGER, "verify-phase", prp_name],
        capture_output=True, text=True, timeout=60,
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def categorize_failures(results):
    """Group failures by verification level."""
    level_1_missing = []   # Files don't exist
    level_2_stubs = []     # Files have TODO/FIXME/stubs
    level_3_unwired = []   # Files not imported/referenced

    for task_result in results:
        if task_result.get("level_1_exists") is False:
            level_1_missing.append(task_result)
        if task_result.get("level_2_substantive") is False:
            level_2_stubs.append(task_result)
        if task_result.get("level_3_wired") is False:
            level_3_unwired.append(task_result)

    return level_1_missing, level_2_stubs, level_3_unwired


def create_fix_tasks(prp_name, level_1, level_2, level_3):
    """Create fix tasks in the tasks.json for each failure category."""
    tasks_path = os.path.join(PRP_DIR, f"{prp_name}.tasks.json")
    if not os.path.exists(tasks_path):
        return []

    with open(tasks_path) as f:
        data = json.load(f)

    existing_ids = [t["id"] for t in data["tasks"]]
    next_id = max(existing_ids) + 1 if existing_ids else 1
    new_tasks = []

    for task_result in level_1:
        missing_files = [
            issue.replace("MISSING: ", "")
            for issue in task_result.get("issues", [])
            if issue.startswith("MISSING:")
        ]
        if missing_files:
            new_tasks.append({
                "id": next_id,
                "name": f"Fix missing files for task {task_result['task_id']}: {task_result['name']}",
                "status": "pending",
                "requirement_id": "",
                "files": missing_files,
                "validate": f"test -f {missing_files[0]}",
                "done": f"All files exist: {', '.join(missing_files)}",
                "depends_on": [],
                "_fix_level": 1,
                "_fix_for_task": task_result["task_id"],
            })
            next_id += 1

    for task_result in level_2:
        stub_files = set()
        for issue in task_result.get("issues", []):
            if issue.startswith("STUB:"):
                # Format: "STUB: filepath:line matches 'PATTERN'"
                parts = issue.split(" ")
                if len(parts) >= 2:
                    file_ref = parts[1]
                    stub_files.add(file_ref.split(":")[0])
        if stub_files:
            new_tasks.append({
                "id": next_id,
                "name": f"Replace stubs in task {task_result['task_id']}: {task_result['name']}",
                "status": "pending",
                "requirement_id": "",
                "files": sorted(stub_files),
                "validate": f"! grep -rn 'TODO\\|FIXME\\|NotImplementedError' {' '.join(sorted(stub_files))}",
                "done": f"No stubs remain in: {', '.join(sorted(stub_files))}",
                "depends_on": [],
                "_fix_level": 2,
                "_fix_for_task": task_result["task_id"],
            })
            next_id += 1

    for task_result in level_3:
        unwired_files = [
            issue.replace("UNWIRED: ", "").split(" not ")[0]
            for issue in task_result.get("issues", [])
            if issue.startswith("UNWIRED:")
        ]
        if unwired_files:
            new_tasks.append({
                "id": next_id,
                "name": f"Wire imports for task {task_result['task_id']}: {task_result['name']}",
                "status": "pending",
                "requirement_id": "",
                "files": unwired_files,
                "validate": "",
                "done": f"Files referenced by sibling modules: {', '.join(unwired_files)}",
                "depends_on": [],
                "_fix_level": 3,
                "_fix_for_task": task_result["task_id"],
            })
            next_id += 1

    if new_tasks:
        data["tasks"].extend(new_tasks)
        tmp = tasks_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, tasks_path)

    return new_tasks


def main():
    if len(sys.argv) < 2:
        print("Usage: prp-phase-verify.py <prp-name> [--auto-fix]", file=sys.stderr)
        sys.exit(2)

    prp_name = sys.argv[1]
    auto_fix = "--auto-fix" in sys.argv

    # Run verify-phase
    verify_result = run_verify_phase(prp_name)
    if verify_result is None:
        print(json.dumps({"error": "verify-phase failed to return valid JSON"}))
        sys.exit(2)

    # If all pass, report success
    if verify_result.get("all_pass"):
        report = {
            "status": "pass",
            "verified_tasks": verify_result["verified_tasks"],
            "message": f"All {verify_result['verified_tasks']} completed tasks passed 3-level verification.",
        }
        print(json.dumps(report, indent=2))
        sys.exit(0)

    # Categorize failures
    results = verify_result.get("results", [])
    level_1, level_2, level_3 = categorize_failures(results)

    # Optionally create fix tasks
    fix_tasks = []
    if auto_fix:
        fix_tasks = create_fix_tasks(prp_name, level_1, level_2, level_3)

    report = {
        "status": "failures_found",
        "verified_tasks": verify_result["verified_tasks"],
        "failures": {
            "level_1_missing": len(level_1),
            "level_2_stubs": len(level_2),
            "level_3_unwired": len(level_3),
        },
        "details": {
            "missing": [
                {"task_id": t["task_id"], "name": t["name"], "issues": t["issues"]}
                for t in level_1
            ],
            "stubs": [
                {"task_id": t["task_id"], "name": t["name"], "issues": t["issues"]}
                for t in level_2
            ],
            "unwired": [
                {"task_id": t["task_id"], "name": t["name"], "issues": t["issues"]}
                for t in level_3
            ],
        },
        "fix_tasks_created": len(fix_tasks),
        "message": (
            f"Verification failures: {len(level_1)} missing, {len(level_2)} stubs, {len(level_3)} unwired. "
            + (f"{len(fix_tasks)} fix tasks added to tasks.json." if fix_tasks else "Run with --auto-fix to create fix tasks.")
        ),
    }
    print(json.dumps(report, indent=2))
    sys.exit(1)


if __name__ == "__main__":
    main()
