"""TAP CLI — command-line interface for the TAP daemon."""

from __future__ import annotations

import argparse
import sys

from .adapters.claude import ClaudeAdapter
from .adapters.goose import GooseAdapter
from .adapters.mock import MockAdapter
from .client import TAPClient
from .constants import SOCKET_PATH
from .daemon import TAPDaemon
from .storage import TAPStorage

ADAPTERS = {
    "claude": ClaudeAdapter,
    "goose": GooseAdapter,
    "mock": MockAdapter,
}


def cmd_daemon(args):
    """Start the TAP daemon (foreground)."""
    adapter_cls = ADAPTERS.get(args.adapter, ClaudeAdapter)
    daemon = TAPDaemon(
        socket_path=args.socket,
        adapter_factory=adapter_cls,
        storage=TAPStorage(),
    )
    print(f"TAP daemon starting on {args.socket} (adapter={args.adapter})")
    daemon.run_forever()


def cmd_spawn(args):
    """Spawn a new agent."""
    client = TAPClient(args.socket)
    resp = client.spawn(
        agent_id=args.agent_id,
        role=args.role or args.agent_id,
        model=args.model,
        persistent=not args.ephemeral,
    )
    print(f"Spawned {resp['agent_id']} (pid={resp['pid']}, status={resp['status']})")


def cmd_kill(args):
    """Kill an agent."""
    client = TAPClient(args.socket)
    resp = client.kill(args.agent_id)
    if resp["killed"]:
        print(f"Killed {args.agent_id}")
    else:
        print(f"Agent {args.agent_id} not found", file=sys.stderr)
        sys.exit(1)


def cmd_send(args):
    """Dispatch a task to an agent."""
    client = TAPClient(args.socket)
    task_text = " ".join(args.task)
    resp = client.send(
        agent_id=args.agent_id,
        task=task_text,
        priority=args.priority,
    )
    print(f"Task {resp['task_id'][:8]}... dispatched (accepted={resp['accepted']})")


def cmd_status(args):
    """Show agent status."""
    client = TAPClient(args.socket)
    if args.agent_id:
        resp = client.status(args.agent_id)
        _print_agent_status(resp)
    else:
        resp = client.status()
        agents = resp.get("agents", [])
        if not agents:
            print("No agents running.")
            return
        print(
            f"{'AGENT':<20} {'ROLE':<15} {'MODEL':<10} "
            f"{'STATE':<10} {'MODE':<12} {'TASK'}"
        )
        print("-" * 85)
        for a in agents:
            task = (a.get("current_task_id") or "-")[:8]
            mode = a.get(
                "mode", "ephemeral" if not a.get("persistent") else "streaming"
            )
            degraded = a.get("degraded_reason")
            mode_display = f"{mode}*" if degraded else mode
            print(
                f"{a['agent_id']:<20} {a['role']:<15} {a['model']:<10} "
                f"{a['state']:<10} {mode_display:<12} {task}"
            )


def _print_agent_status(resp):
    """Print single agent status."""
    print(f"Agent:    {resp.get('agent_id', '?')}")
    print(f"Alive:    {resp.get('alive', '?')}")
    print(f"State:    {resp.get('state', '?')}")
    print(f"Mode:     {resp.get('mode', '?')}")
    print(f"Uptime:   {resp.get('uptime_s', 0):.1f}s")
    print(f"Context:  {resp.get('context_pct', 0):.1f}%")
    task = resp.get("current_task_id") or "none"
    print(f"Task:     {task}")
    degraded = resp.get("degraded_reason")
    if degraded:
        print(f"Degraded: {degraded}")


def cmd_broadcast(args):
    """Broadcast a message to all agents."""
    client = TAPClient(args.socket)
    message = " ".join(args.message)
    resp = client.broadcast(message)
    print(f"Broadcast sent: {resp.get('sent', False)}")


def cmd_handoff(args):
    """Hand off a task between agents."""
    client = TAPClient(args.socket)
    resp = client.handoff(
        from_agent=args.from_agent,
        to_agent=args.to_agent,
        task_id=args.task_id,
        summary=args.summary or "",
    )
    print(
        f"Handoff: {resp.get('from_agent')} -> {resp.get('to_agent')} "
        f"(task={resp.get('task_id', '?')[:8]}...)"
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="tap",
        description="TAP — Toroidal Agent Protocol CLI",
    )
    parser.add_argument(
        "--socket",
        default=SOCKET_PATH,
        help=f"Daemon socket path (default: {SOCKET_PATH})",
    )

    sub = parser.add_subparsers(dest="command", help="Available commands")

    # daemon
    p = sub.add_parser("daemon", help="Start the TAP daemon")
    p.add_argument(
        "--adapter", default="claude", choices=ADAPTERS.keys(), help="Agent adapter"
    )

    # spawn
    p = sub.add_parser("spawn", help="Spawn a new agent")
    p.add_argument("agent_id", help="Agent identifier")
    p.add_argument("--role", default="", help="Agent role (defaults to agent_id)")
    p.add_argument("--model", default="sonnet", help="Model to use")
    p.add_argument(
        "--ephemeral", action="store_true", help="Ephemeral mode (no persistence)"
    )

    # kill
    p = sub.add_parser("kill", help="Kill an agent")
    p.add_argument("agent_id", help="Agent to kill")

    # send
    p = sub.add_parser("send", help="Dispatch a task to an agent")
    p.add_argument("agent_id", help="Target agent")
    p.add_argument("task", nargs="+", help="Task description")
    p.add_argument(
        "--priority", type=int, default=5, help="Priority (1=highest, 10=lowest)"
    )

    # status
    p = sub.add_parser("status", help="Show agent status")
    p.add_argument("agent_id", nargs="?", help="Specific agent (omit for all)")

    # broadcast
    p = sub.add_parser("broadcast", help="Broadcast message to all agents")
    p.add_argument("message", nargs="+", help="Message text")

    # handoff
    p = sub.add_parser("handoff", help="Hand off task between agents")
    p.add_argument("from_agent", help="Source agent")
    p.add_argument("to_agent", help="Target agent")
    p.add_argument("task_id", help="Task ID to hand off")
    p.add_argument("--summary", help="Context summary for receiving agent")

    return parser


def run_cli(argv: list[str] | None = None):
    """Run the TAP CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        sys.exit(0)

    commands = {
        "daemon": cmd_daemon,
        "spawn": cmd_spawn,
        "kill": cmd_kill,
        "send": cmd_send,
        "status": cmd_status,
        "broadcast": cmd_broadcast,
        "handoff": cmd_handoff,
    }

    fn = commands.get(args.command)
    if fn:
        fn(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    run_cli()
