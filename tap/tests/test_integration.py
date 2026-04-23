"""Integration tests — full spawn/dispatch/result cycle."""

import os
import time

import pytest

import sys

sys.path.insert(0, os.path.expanduser("~/.claude/hooks"))
import shared.agent_channel as _ac

from tap.adapters.mock import MockAdapter
from tap.client import TAPClient
from tap.daemon import TAPDaemon
from tap.storage import TAPStorage


@pytest.fixture()
def system(tmp_path):
    """Full TAP system: daemon + client."""
    sock = str(tmp_path / "tap-integ.sock")
    _ac.DB_PATH = str(tmp_path / "integ.db")

    daemon = TAPDaemon(
        socket_path=sock,
        adapter_factory=MockAdapter,
        storage=TAPStorage(),
    )
    daemon.start_background()
    time.sleep(0.3)
    client = TAPClient(sock)
    yield daemon, client
    daemon.stop()


def test_full_cycle(system):
    """Spawn agent, dispatch task, check status, kill agent."""
    daemon, client = system

    # Spawn
    resp = client.spawn("integ-1", role="tester")
    assert resp["status"] == "ready"

    # Dispatch
    resp = client.send("integ-1", "echo hello", priority=3)
    assert resp["accepted"]
    task_id = resp["task_id"]

    # Check agent status
    status = client.status("integ-1")
    assert status["alive"] is True
    assert status["state"] in ("ready", "working")

    # Check task status
    task = client.task_status(task_id)
    assert task["task_id"] == task_id

    # Kill
    resp = client.kill("integ-1")
    assert resp["killed"] is True

    # Verify gone
    status = client.status("integ-1")
    assert status["alive"] is False


def test_persistent_agent_multiple_tasks(system):
    """Persistent agent handles two tasks without respawn."""
    daemon, client = system

    client.spawn("p1", role="tester", persistent=True)

    # Task 1
    resp1 = client.send("p1", "task one")
    assert resp1["accepted"]

    time.sleep(0.5)

    # Task 2 — same agent, still alive
    resp2 = client.send("p1", "task two")
    assert resp2["accepted"]

    # Agent still running
    status = client.status("p1")
    assert status["alive"] is True

    client.kill("p1")


def test_ephemeral_agent(system):
    """Ephemeral agent works for a task."""
    daemon, client = system

    client.spawn("e1", role="tester", persistent=False)
    resp = client.send("e1", "quick task")
    assert resp["accepted"]

    status = client.status("e1")
    assert status["alive"] is True

    client.kill("e1")


def test_multiple_agents(system):
    """Multiple agents can run concurrently."""
    daemon, client = system

    client.spawn("a1", role="researcher")
    client.spawn("a2", role="builder")
    client.spawn("a3", role="reviewer")

    listing = client.status()
    assert len(listing["agents"]) == 3

    client.send("a1", "research task")
    client.send("a2", "build task")
    client.send("a3", "review task")

    for aid in ("a1", "a2", "a3"):
        s = client.status(aid)
        assert s["alive"] is True

    for aid in ("a1", "a2", "a3"):
        client.kill(aid)


def test_handoff_between_agents(system):
    """Handoff creates a new task for the receiving agent."""
    daemon, client = system

    client.spawn("from-agent", role="researcher")
    client.spawn("to-agent", role="builder")

    # Create initial task
    resp = client.send("from-agent", "initial research")
    task_id = resp["task_id"]

    # Handoff
    handoff = client.handoff(
        from_agent="from-agent",
        to_agent="to-agent",
        task_id=task_id,
        summary="Found 3 options, recommend option B",
    )
    assert handoff["from_agent"] == "from-agent"
    assert handoff["to_agent"] == "to-agent"
    assert handoff["task_id"] is not None

    client.kill("from-agent")
    client.kill("to-agent")


def test_broadcast_received(system):
    """Broadcast is stored and can be read."""
    daemon, client = system

    client.spawn("listener", role="tester")
    resp = client.broadcast("attention all agents", from_agent="orchestrator")
    assert resp["sent"] is True
    client.kill("listener")
