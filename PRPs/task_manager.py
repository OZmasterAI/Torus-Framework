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
        "total": len(data["tasks"]),
        "counts": counts,
        "tasks": [{"id": t["id"], "name": t["name"], "status": t["status"]} for t in data["tasks"]],
    }
    print(json.dumps(summary, indent=2))


def cmd_next(prp_name):
    """Print next pending or failed task as JSON. Exit 1 if none remain."""
    data = load_tasks(prp_name)
    # Priority: failed tasks first (retry), then pending
    for status in ("failed", "pending"):
        for task in data["tasks"]:
            if task["status"] == status:
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


def main():
    if len(sys.argv) < 3:
        print("Usage: task_manager.py <command> <prp-name> [args...]", file=sys.stderr)
        print("Commands: status, next, update <task-id> <status>, validate <task-id>", file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]
    prp_name = sys.argv[2]

    if cmd == "status":
        cmd_status(prp_name)
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
    else:
        print(f"Error: Unknown command '{cmd}'", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
