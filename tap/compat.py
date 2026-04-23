"""TAP compatibility bridge — lets manage.sh use TAP when daemon is running.

Usage from shell:
    python3 -m tap.compat send <role> <task> [priority]
    python3 -m tap.compat status
    python3 -m tap.compat suspend <role>
    python3 -m tap.compat resume <role> [model]
    python3 -m tap.compat is_running

Returns exit 0 if TAP daemon is available, exit 1 if not (fall back to tmux).
"""

from __future__ import annotations

import json
import os
import sys

from .client import TAPClient
from .constants import SOCKET_PATH


def is_running(socket_path: str = SOCKET_PATH) -> bool:
    """Check if TAP daemon is running."""
    if not os.path.exists(socket_path):
        return False
    try:
        client = TAPClient(socket_path)
        resp = client.heartbeat("__daemon__")
        return resp.get("alive", False)
    except Exception:
        return False


def cmd_send(role: str, task: str, priority: int = 5) -> None:
    """Send a task to an agent via TAP."""
    client = TAPClient()
    try:
        resp = client.send(role, task, priority=priority)
        print(
            f"Task created: {resp['task_id'][:8]}... (priority={priority}, role={role})"
        )
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_status() -> None:
    """Show all agent status via TAP."""
    client = TAPClient()
    try:
        resp = client.status()
        agents = resp.get("agents", [])
        if not agents:
            print("No agents running via TAP.")
            return
        print("=== TAP Agents ===")
        for a in agents:
            task = (a.get("current_task_id") or "none")[:8]
            print(
                f"  {a['agent_id']:<25} model={a['model']:<8} "
                f"state={a['state']:<12} persistent={'yes' if a['persistent'] else 'no':<4} "
                f"task={task}"
            )
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_suspend(role: str) -> None:
    """Suspend (kill) an agent via TAP."""
    client = TAPClient()
    try:
        resp = client.kill(role)
        if resp.get("killed"):
            print(f"{role} suspended via TAP")
        else:
            print(f"Agent {role} not found", file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_resume(role: str, model: str = "sonnet") -> None:
    """Resume (spawn) an agent via TAP."""
    client = TAPClient()
    try:
        resp = client.spawn(role, role=role, model=model, persistent=True)
        print(f"{role} resumed via TAP (pid={resp['pid']})")
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    """CLI entry point for compat bridge."""
    if len(sys.argv) < 2:
        print(
            "Usage: python3 -m tap.compat <is_running|send|status|suspend|resume> [args]"
        )
        sys.exit(1)

    action = sys.argv[1]

    if action == "is_running":
        sys.exit(0 if is_running() else 1)
    elif action == "send":
        role = sys.argv[2]
        task = sys.argv[3]
        priority = int(sys.argv[4]) if len(sys.argv) > 4 else 5
        cmd_send(role, task, priority)
    elif action == "status":
        cmd_status()
    elif action == "suspend":
        cmd_suspend(sys.argv[2])
    elif action == "resume":
        role = sys.argv[2]
        model = sys.argv[3] if len(sys.argv) > 3 else "sonnet"
        cmd_resume(role, model)
    else:
        print(f"Unknown action: {action}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
