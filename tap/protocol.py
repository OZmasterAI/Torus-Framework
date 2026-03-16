"""TAP protocol message definitions (JSON-RPC 2.0)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Session namespace
# ---------------------------------------------------------------------------


@dataclass
class SpawnRequest:
    agent_id: str
    role: str
    model: str = "sonnet"
    adapter: str = "claude"
    persistent: bool = True
    config: dict = field(default_factory=dict)


@dataclass
class SpawnResponse:
    agent_id: str
    pid: int
    socket_path: str
    status: str = "ready"


@dataclass
class KillRequest:
    agent_id: str


@dataclass
class KillResponse:
    agent_id: str
    killed: bool


# ---------------------------------------------------------------------------
# Task namespace
# ---------------------------------------------------------------------------


@dataclass
class TaskDispatch:
    agent_id: str
    title: str
    task_id: str = ""
    description: str = ""
    priority: int = 5
    depends_on: str | None = None


@dataclass
class TaskDispatchResponse:
    task_id: str
    accepted: bool


@dataclass
class TaskStream:
    task_id: str
    event: str  # text, tool_call, tool_result, progress
    data: str = ""


@dataclass
class TaskStatus:
    task_id: str
    status: str  # pending, assigned, running, done, failed
    progress_pct: int = 0
    token_usage: int = 0
    cost: float = 0.0


@dataclass
class TaskResult:
    task_id: str
    status: str
    result: str = ""
    files_changed: list = field(default_factory=list)
    cost: float = 0.0


# ---------------------------------------------------------------------------
# Agent namespace
# ---------------------------------------------------------------------------


@dataclass
class HeartbeatRequest:
    agent_id: str


@dataclass
class Heartbeat:
    agent_id: str
    alive: bool
    state: str = "idle"  # idle, working, dead
    context_pct: float = 0.0
    uptime_s: float = 0.0
    current_task_id: str | None = None


@dataclass
class AgentContext:
    agent_id: str
    tokens_used: int = 0
    tokens_max: int = 0
    model: str = ""
    active_task: str | None = None


# ---------------------------------------------------------------------------
# Coord namespace
# ---------------------------------------------------------------------------


@dataclass
class Broadcast:
    message: str
    from_agent: str = "cli"


@dataclass
class Handoff:
    from_agent: str
    to_agent: str
    task_id: str
    context_summary: str = ""
    files: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------

_ID_COUNTER = 0


def make_request(method: str, params: dict | None = None) -> dict:
    """Build a JSON-RPC 2.0 request."""
    global _ID_COUNTER
    _ID_COUNTER += 1
    return {
        "jsonrpc": "2.0",
        "method": method,
        "params": params or {},
        "id": _ID_COUNTER,
    }


def make_response(req_id: Any, result: dict) -> dict:
    """Build a JSON-RPC 2.0 success response."""
    return {"jsonrpc": "2.0", "result": result, "id": req_id}


def make_error(req_id: Any, code: int, message: str) -> dict:
    """Build a JSON-RPC 2.0 error response."""
    return {
        "jsonrpc": "2.0",
        "error": {"code": code, "message": message},
        "id": req_id,
    }


def to_dict(obj: Any) -> dict:
    """Convert a dataclass to a dict."""
    return asdict(obj)


def encode(msg: dict) -> bytes:
    """Encode a JSON-RPC message to bytes with newline delimiter."""
    return json.dumps(msg).encode() + b"\n"


def decode(data: bytes) -> dict:
    """Decode a JSON-RPC message from bytes."""
    return json.loads(data.strip())
