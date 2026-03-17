"""TAP daemon — JSON-RPC server over Unix domain sockets."""

from __future__ import annotations

import json
import os
import socketserver
import threading
import time
from typing import Any, Callable

from .adapters.base import BaseAdapter
from .agent_manager import AgentManager
from .constants import (
    HEARTBEAT_INTERVAL,
    SOCKET_PATH,
    STATE_DEAD,
)
from .protocol import make_error, make_response
from .storage import TAPStorage


class _RPCHandler(socketserver.StreamRequestHandler):
    """Handle one JSON-RPC connection (newline-delimited JSON)."""

    def handle(self):
        for raw_line in self.rfile:
            line = raw_line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                resp = make_error(None, -32700, "Parse error")
                self.wfile.write(json.dumps(resp).encode() + b"\n")
                continue

            req_id = msg.get("id")
            method = msg.get("method", "")
            params = msg.get("params", {})

            try:
                result = self.server.dispatch(method, params)
                resp = make_response(req_id, result)
            except Exception as e:
                resp = make_error(req_id, -32000, str(e))

            self.wfile.write(json.dumps(resp).encode() + b"\n")
            self.wfile.flush()


class _UnixServer(socketserver.ThreadingUnixStreamServer):
    """Threaded Unix socket server with dispatch method."""

    allow_reuse_address = True

    def __init__(self, socket_path: str, dispatch_fn: Callable):
        self.dispatch = dispatch_fn
        if os.path.exists(socket_path):
            os.unlink(socket_path)
        super().__init__(socket_path, _RPCHandler)


class TAPDaemon:
    """Main TAP daemon — orchestrates agents via JSON-RPC."""

    def __init__(
        self,
        socket_path: str = SOCKET_PATH,
        adapter_factory: Callable[..., BaseAdapter] | None = None,
        storage: TAPStorage | None = None,
    ):
        self.socket_path = socket_path
        self.manager = AgentManager(adapter_factory=adapter_factory)
        self.storage = storage or TAPStorage()
        self._server: _UnixServer | None = None
        self._heartbeat_thread: threading.Thread | None = None
        self._running = False

    def _dispatch(self, method: str, params: dict) -> dict:
        """Route a JSON-RPC method to the appropriate handler."""
        handlers = {
            "session/spawn": self._handle_spawn,
            "session/kill": self._handle_kill,
            "task/dispatch": self._handle_task_dispatch,
            "task/status": self._handle_task_status,
            "task/result": self._handle_task_result,
            "agent/heartbeat": self._handle_heartbeat,
            "agent/context": self._handle_context,
            "agent/list": self._handle_list,
            "coord/broadcast": self._handle_broadcast,
            "coord/handoff": self._handle_handoff,
        }
        handler = handlers.get(method)
        if handler is None:
            raise ValueError(f"Unknown method: {method}")
        return handler(params)

    # -- session/* -------------------------------------------------------

    def _handle_spawn(self, params: dict) -> dict:
        agent_id = params.get("agent_id", "")
        if not agent_id:
            raise ValueError("agent_id required")
        role = params.get("role", agent_id)
        model = params.get("model", "sonnet")
        persistent = params.get("persistent", True)

        agent = self.manager.spawn(
            agent_id=agent_id,
            role=role,
            model=model,
            persistent=persistent,
        )
        return {
            "agent_id": agent.agent_id,
            "pid": agent.process.pid,
            "socket_path": self.socket_path,
            "status": "ready",
        }

    def _handle_kill(self, params: dict) -> dict:
        agent_id = params.get("agent_id", "")
        killed = self.manager.kill(agent_id)
        return {"agent_id": agent_id, "killed": killed}

    # -- task/* ----------------------------------------------------------

    def _handle_task_dispatch(self, params: dict) -> dict:
        agent_id = params.get("agent_id", "")
        title = params.get("title", "")
        description = params.get("description", "")
        priority = params.get("priority", 5)

        if not agent_id or not title:
            raise ValueError("agent_id and title required")

        task_id = self.storage.dispatch(
            agent_id=agent_id,
            title=title,
            description=description,
            priority=priority,
            depends_on=params.get("depends_on"),
        )
        if not task_id:
            raise ValueError("Failed to create task")

        agent = self.manager.get(agent_id)
        if agent and agent.alive:
            prompt = title
            if description:
                prompt = f"{title}\n\n{description}"
            self.manager.send_prompt(agent_id, prompt)
            agent.current_task_id = task_id

        return {"task_id": task_id, "accepted": True}

    def _handle_task_status(self, params: dict) -> dict:
        task_id = params.get("task_id", "")
        if task_id:
            task = self.storage.get(task_id)
            if task:
                return {
                    "task_id": task_id,
                    "status": task["status"],
                    "progress_pct": 0,
                    "token_usage": 0,
                    "cost": 0.0,
                }
        return {"task_id": task_id, "status": "unknown"}

    def _handle_task_result(self, params: dict) -> dict:
        task_id = params.get("task_id", "")
        task = self.storage.get(task_id)
        if task:
            return {
                "task_id": task_id,
                "status": task["status"],
                "result": task.get("result", ""),
                "files_changed": [],
                "cost": 0.0,
            }
        return {"task_id": task_id, "status": "unknown", "result": ""}

    # -- agent/* ---------------------------------------------------------

    def _handle_heartbeat(self, params: dict) -> dict:
        agent_id = params.get("agent_id", "")
        if agent_id == "__daemon__":
            return {"agent_id": "__daemon__", "alive": True, "state": "running"}

        agent = self.manager.get(agent_id)
        if agent is None:
            return {"agent_id": agent_id, "alive": False, "state": "unknown"}

        return {
            "agent_id": agent_id,
            "alive": agent.alive,
            "state": agent.state,
            "context_pct": 0.0,
            "uptime_s": agent.uptime_s,
            "current_task_id": agent.current_task_id,
        }

    def _handle_context(self, params: dict) -> dict:
        agent_id = params.get("agent_id", "")
        agent = self.manager.get(agent_id)
        if agent is None:
            return {"agent_id": agent_id, "tokens_used": 0, "tokens_max": 0}
        return {
            "agent_id": agent_id,
            "tokens_used": 0,
            "tokens_max": 0,
            "model": agent.model,
            "active_task": agent.current_task_id,
        }

    def _handle_list(self, params: dict) -> dict:
        agents = self.manager.list_agents()
        return {
            "agents": [
                {
                    "agent_id": a.agent_id,
                    "role": a.role,
                    "model": a.model,
                    "state": a.state,
                    "persistent": a.persistent,
                    "alive": a.alive,
                    "uptime_s": a.uptime_s,
                    "current_task_id": a.current_task_id,
                }
                for a in agents
            ]
        }

    # -- coord/* ---------------------------------------------------------

    def _handle_broadcast(self, params: dict) -> dict:
        message = params.get("message", "")
        from_agent = params.get("from_agent", "cli")
        ok = self.storage.broadcast(from_agent, message)
        return {"sent": ok}

    def _handle_handoff(self, params: dict) -> dict:
        from_agent = params.get("from_agent", "")
        to_agent = params.get("to_agent", "")
        task_id = params.get("task_id", "")
        summary = params.get("context_summary", "")

        new_task_id = self.storage.dispatch(
            agent_id=to_agent,
            title=f"Handoff from {from_agent}: {task_id}",
            description=summary,
            priority=3,
        )
        return {"task_id": new_task_id, "from_agent": from_agent, "to_agent": to_agent}

    # -- lifecycle -------------------------------------------------------

    def _heartbeat_loop(self):
        while self._running:
            dead = self.manager.check_heartbeats()
            for agent_id in dead:
                agent = self.manager.get(agent_id)
                if agent and agent.current_task_id:
                    self.storage.fail(agent.current_task_id, "agent died")
            time.sleep(HEARTBEAT_INTERVAL)

    def start_background(self):
        """Start the daemon in background threads."""
        self._running = True
        self._server = _UnixServer(self.socket_path, self._dispatch)

        server_thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        server_thread.start()

        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True
        )
        self._heartbeat_thread.start()

    def stop(self):
        """Stop the daemon and clean up."""
        self._running = False
        for agent in self.manager.list_agents():
            self.manager.kill(agent.agent_id)
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)

    def run_forever(self):
        """Start daemon and block until interrupted."""
        self.start_background()
        try:
            while self._running:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()
