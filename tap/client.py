"""TAP client — connect to a running TAP daemon via Unix socket."""

from __future__ import annotations

import json
import socket
from typing import Any

from .constants import SOCKET_PATH
from .protocol import make_request


class TAPClient:
    """JSON-RPC client for TAP daemon."""

    def __init__(self, socket_path: str = SOCKET_PATH):
        self.socket_path = socket_path

    def call(self, method: str, params: dict | None = None) -> dict:
        """Send a JSON-RPC request and return the result."""
        req = make_request(method, params)
        data = json.dumps(req).encode() + b"\n"

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(self.socket_path)
            sock.sendall(data)

            # Read response (newline-delimited)
            buf = b""
            while b"\n" not in buf:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buf += chunk

            resp = json.loads(buf.strip())
            if "error" in resp:
                raise RuntimeError(resp["error"]["message"])
            return resp.get("result", {})
        finally:
            sock.close()

    # -- Convenience methods ---------------------------------------------

    def spawn(
        self,
        agent_id: str,
        role: str = "",
        model: str = "sonnet",
        persistent: bool = True,
    ) -> dict:
        """Spawn a new agent."""
        return self.call(
            "session/spawn",
            {
                "agent_id": agent_id,
                "role": role or agent_id,
                "model": model,
                "persistent": persistent,
            },
        )

    def kill(self, agent_id: str) -> dict:
        """Kill an agent."""
        return self.call("session/kill", {"agent_id": agent_id})

    def send(
        self,
        agent_id: str,
        task: str,
        description: str = "",
        priority: int = 5,
    ) -> dict:
        """Dispatch a task to an agent."""
        return self.call(
            "task/dispatch",
            {
                "agent_id": agent_id,
                "title": task,
                "description": description,
                "priority": priority,
            },
        )

    def task_status(self, task_id: str) -> dict:
        """Get task status."""
        return self.call("task/status", {"task_id": task_id})

    def task_result(self, task_id: str) -> dict:
        """Get task result."""
        return self.call("task/result", {"task_id": task_id})

    def status(self, agent_id: str | None = None) -> dict:
        """Get agent status or list all agents."""
        if agent_id:
            return self.call("agent/heartbeat", {"agent_id": agent_id})
        return self.call("agent/list", {})

    def heartbeat(self, agent_id: str = "__daemon__") -> dict:
        """Check if daemon/agent is alive."""
        return self.call("agent/heartbeat", {"agent_id": agent_id})

    def broadcast(self, message: str, from_agent: str = "cli") -> dict:
        """Broadcast a message to all agents."""
        return self.call(
            "coord/broadcast",
            {
                "message": message,
                "from_agent": from_agent,
            },
        )

    def handoff(
        self,
        from_agent: str,
        to_agent: str,
        task_id: str,
        summary: str = "",
    ) -> dict:
        """Hand off a task from one agent to another."""
        return self.call(
            "coord/handoff",
            {
                "from_agent": from_agent,
                "to_agent": to_agent,
                "task_id": task_id,
                "context_summary": summary,
            },
        )
