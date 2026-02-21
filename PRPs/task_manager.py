#!/usr/bin/env python3
"""Task manager for PRP JSON task tracking.

Used by torus-loop.sh orchestrator and /prp status command.
Reads/writes ~/.claude/PRPs/<prp-name>.tasks.json alongside PRP markdown files.
"""

import json
import os
import subprocess
import sys
PRP_DIR = os.path.expanduser("~/.claude/PRPs")


def tasks_file(prp_name):
    """Return path to a PRP's tasks.json file."""
    return os.path.join(PRP_DIR, f"{prp_name}.tasks.json")


def load_tasks(prp_name):
    """Load tasks.json for a PRP. Exit with error if not found."""
    path = tasks_file(prp_name)
    if not os.path.exists(path):
        print(f"Error: No tasks file found at {path}", file=sys.stderr)
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


def save_tasks(prp_name, data):
    """Atomically write tasks.json for a PRP."""
    path = tasks_file(prp_name)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def cmd_status(prp_name):
    """Print JSON status summary."""
    data = load_tasks(prp_name)
    counts = {"pending": 0, "in_progress": 0, "passed": 0, "failed": 0}
    for task in data["tasks"]:
        counts[task["status"]] = counts.get(task["status"], 0) + 1
    summary = {
        "prp": prp_name,
        "milestone": data.get("milestone", 0),
        "phase": data.get("phase", 0),
        "total": len(data["tasks"]),
        "counts": counts,
        "tasks": [
            {
                "id": t["id"],
                "name": t["name"],
                "status": t["status"],
                "requirement_id": t.get("requirement_id", ""),
            }
            for t in data["tasks"]
        ],
    }
    print(json.dumps(summary, indent=2))


def cmd_next(prp_name):
    """Print next pending or failed task as JSON. Exit 1 if none remain."""
    data = load_tasks(prp_name)
    # Priority: failed tasks first (retry), then pending
    for status in ("failed", "pending"):
        for task in data["tasks"]:
            if task["status"] == status:
                # Skip failed tasks that have on_fail routing (target handles it)
                if status == "failed" and task.get("on_fail") is not None:
                    continue
                # Check dependencies are all passed
                deps_met = all(
                    t["status"] == "passed"
                    for t in data["tasks"]
                    if t["id"] in task.get("depends_on", [])
                )
                if deps_met:
                    print(json.dumps(task, indent=2))
                    return
    # No actionable tasks
    print(json.dumps({"done": True}))
    sys.exit(1)


def cmd_update(prp_name, task_id, new_status):
    """Update a task's status."""
    valid = ("pending", "in_progress", "passed", "failed")
    if new_status not in valid:
        print(f"Error: Invalid status '{new_status}'. Must be one of: {', '.join(valid)}", file=sys.stderr)
        sys.exit(1)
    data = load_tasks(prp_name)
    for task in data["tasks"]:
        if task["id"] == int(task_id):
            task["status"] = new_status
            save_tasks(prp_name, data)
            print(json.dumps({"id": task["id"], "status": new_status}))
            return
    print(f"Error: Task {task_id} not found", file=sys.stderr)
    sys.exit(1)


def cmd_validate(prp_name, task_id):
    """Run validation command for a task, update status based on exit code."""
    data = load_tasks(prp_name)
    task = None
    for t in data["tasks"]:
        if t["id"] == int(task_id):
            task = t
            break
    if not task:
        print(f"Error: Task {task_id} not found", file=sys.stderr)
        sys.exit(1)

    validate_cmd = task.get("validate", "")
    if not validate_cmd:
        print(f"Warning: No validation command for task {task_id}, marking passed", file=sys.stderr)
        task["status"] = "passed"
        save_tasks(prp_name, data)
        print(json.dumps({"id": task["id"], "status": "passed", "reason": "no_validation"}))
        return

    # Use task's cwd if specified, otherwise derive from first file's directory
    cwd = task.get("cwd", "")
    if not cwd and task.get("files"):
        cwd = os.path.dirname(task["files"][0])
    cwd = cwd or None  # None = inherit current directory

    try:
        result = subprocess.run(
            validate_cmd, shell=True, capture_output=True, text=True, timeout=300,
            cwd=cwd,
        )
        new_status = "passed" if result.returncode == 0 else "failed"
        task["status"] = new_status
        # on_fail routing: activate fallback task when this one fails
        if new_status == "failed" and task.get("on_fail") is not None:
            target_id = task["on_fail"]
            for t in data["tasks"]:
                if t["id"] == target_id and t["status"] != "passed":
                    t["status"] = "pending"
                    break
        save_tasks(prp_name, data)
        output = {
            "id": task["id"],
            "status": new_status,
            "returncode": result.returncode,
            "stdout": result.stdout[-500:] if result.stdout else "",
            "stderr": result.stderr[-500:] if result.stderr else "",
        }
        print(json.dumps(output, indent=2))
        sys.exit(0 if new_status == "passed" else 1)
    except subprocess.TimeoutExpired:
        task["status"] = "failed"
        save_tasks(prp_name, data)
        print(json.dumps({"id": task["id"], "status": "failed", "reason": "timeout"}))
        sys.exit(1)


def cmd_wave(prp_name):
    """Print all currently eligible tasks as a JSON array. Exit 1 if none."""
    data = load_tasks(prp_name)
    eligible = []
    for status in ("failed", "pending"):
        for task in data["tasks"]:
            if task["status"] == status:
                # Skip failed tasks that have on_fail routing
                if status == "failed" and task.get("on_fail") is not None:
                    continue
                deps_met = all(
                    t["status"] == "passed"
                    for t in data["tasks"]
                    if t["id"] in task.get("depends_on", [])
                )
                if deps_met:
                    eligible.append(task)
    if not eligible:
        print(json.dumps({"done": True}))
        sys.exit(1)
    print(json.dumps(eligible, indent=2))


def cmd_plan_check(prp_name, requirements_file):
    """Check if tasks cover all requirements. Returns gaps."""
    data = load_tasks(prp_name)

    # Load requirements file and extract R-ids
    if not os.path.exists(requirements_file):
        print(f"Error: Requirements file not found: {requirements_file}", file=sys.stderr)
        sys.exit(1)
    with open(requirements_file) as f:
        req_content = f.read()

    # Extract requirement IDs (### R1:, ### R2:, etc.)
    import re
    req_ids = set(re.findall(r"###\s+(R\d+):", req_content))

    # Map tasks to requirement IDs
    covered = set()
    orphan_tasks = []
    for task in data["tasks"]:
        rid = task.get("requirement_id", "")
        if rid and rid in req_ids:
            covered.add(rid)
        elif rid:
            orphan_tasks.append({"task_id": task["id"], "requirement_id": rid})
        else:
            orphan_tasks.append({"task_id": task["id"], "requirement_id": "(none)"})

    uncovered = sorted(req_ids - covered)
    result = {
        "prp": prp_name,
        "total_requirements": len(req_ids),
        "covered": len(covered),
        "uncovered": uncovered,
        "orphan_tasks": orphan_tasks,
        "pass": len(uncovered) == 0 and len(orphan_tasks) == 0,
    }
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["pass"] else 1)


def cmd_verify_phase(prp_name):
    """3-level verification of completed tasks: exists, substantive, wired."""
    data = load_tasks(prp_name)
    results = []

    for task in data["tasks"]:
        if task["status"] != "passed":
            continue

        task_result = {
            "task_id": task["id"],
            "name": task["name"],
            "level_1_exists": True,
            "level_2_substantive": True,
            "level_3_wired": True,
            "issues": [],
        }

        for filepath in task.get("files", []):
            expanded = os.path.expanduser(filepath)
            # Level 1: File exists
            if not os.path.exists(expanded):
                task_result["level_1_exists"] = False
                task_result["issues"].append(f"MISSING: {filepath}")
                continue

            # Level 2: Not a stub (check for TODO, placeholder, pass-only)
            # Line-by-line check: skip lines that are inside string literals (stub detection code)
            with open(expanded) as f:
                lines = f.readlines()
            stub_patterns = [
                ("TODO", r'\bTODO\b'),
                ("FIXME", r'\bFIXME\b'),
                ("NotImplementedError", r'raise\s+NotImplementedError'),
                ("placeholder", r'pass\s*#\s*placeholder'),
            ]
            import re as _re
            for marker_name, pattern in stub_patterns:
                for line_num, line in enumerate(lines, 1):
                    stripped = line.strip()
                    # Skip comments that are checking for stubs (meta-detection)
                    if stripped.startswith("#") or stripped.startswith("//"):
                        continue
                    # Skip lines inside string literals (e.g. stub_markers = ["TODO", ...])
                    if '["' in stripped or "'" + marker_name + "'" in stripped or '"' + marker_name + '"' in stripped:
                        continue
                    if _re.search(pattern, line):
                        task_result["level_2_substantive"] = False
                        task_result["issues"].append(f"STUB: {filepath}:{line_num} matches '{marker_name}'")
                        break  # One hit per pattern per file is enough

            # Level 3: Wired (file is imported/referenced somewhere)
            basename = os.path.basename(filepath)
            name_no_ext = os.path.splitext(basename)[0]
            parent_dir = os.path.dirname(expanded)
            wired = False
            if parent_dir and os.path.isdir(parent_dir):
                for other in os.listdir(parent_dir):
                    other_path = os.path.join(parent_dir, other)
                    if other_path == expanded or not os.path.isfile(other_path):
                        continue
                    try:
                        with open(other_path) as of:
                            other_content = of.read(10000)
                        if name_no_ext in other_content or basename in other_content:
                            wired = True
                            break
                    except (UnicodeDecodeError, PermissionError):
                        continue
            if not wired:
                task_result["level_3_wired"] = False
                task_result["issues"].append(f"UNWIRED: {filepath} not referenced by sibling files")

        results.append(task_result)

    all_pass = all(
        r["level_1_exists"] and r["level_2_substantive"] and r["level_3_wired"]
        for r in results
    )
    output = {
        "prp": prp_name,
        "phase": data.get("phase", 0),
        "verified_tasks": len(results),
        "all_pass": all_pass,
        "results": results,
    }
    print(json.dumps(output, indent=2))
    sys.exit(0 if all_pass else 1)


def main():
    if len(sys.argv) < 3:
        print("Usage: task_manager.py <command> <prp-name> [args...]", file=sys.stderr)
        print("Commands: status, wave, next, update, validate, plan-check, verify-phase", file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]
    prp_name = sys.argv[2]

    if cmd == "status":
        cmd_status(prp_name)
    elif cmd == "wave":
        cmd_wave(prp_name)
    elif cmd == "next":
        cmd_next(prp_name)
    elif cmd == "update":
        if len(sys.argv) < 5:
            print("Usage: task_manager.py update <prp-name> <task-id> <status>", file=sys.stderr)
            sys.exit(1)
        cmd_update(prp_name, sys.argv[3], sys.argv[4])
    elif cmd == "validate":
        if len(sys.argv) < 4:
            print("Usage: task_manager.py validate <prp-name> <task-id>", file=sys.stderr)
            sys.exit(1)
        cmd_validate(prp_name, sys.argv[3])
    elif cmd == "plan-check":
        if len(sys.argv) < 4:
            print("Usage: task_manager.py plan-check <prp-name> <requirements-file>", file=sys.stderr)
            sys.exit(1)
        cmd_plan_check(prp_name, sys.argv[3])
    elif cmd == "verify-phase":
        cmd_verify_phase(prp_name)
    else:
        print(f"Error: Unknown command '{cmd}'", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
