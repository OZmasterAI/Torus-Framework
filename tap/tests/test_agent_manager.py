"""Tests for TAP agent manager."""

import time

from tap.adapters.mock import MockAdapter
from tap.agent_manager import AgentManager
from tap.constants import STATE_DEAD, STATE_READY, STATE_WORKING


def _make_mgr():
    return AgentManager(adapter_factory=MockAdapter)


def test_spawn_agent():
    mgr = _make_mgr()
    agent = mgr.spawn("test-1", role="tester")
    assert agent.state == STATE_READY
    assert agent.process.pid > 0
    assert agent.alive
    mgr.kill("test-1")


def test_spawn_persistent():
    mgr = _make_mgr()
    agent = mgr.spawn("test-p", role="tester", persistent=True)
    assert agent.persistent is True
    mgr.kill("test-p")


def test_spawn_ephemeral():
    mgr = _make_mgr()
    agent = mgr.spawn("test-e", role="tester", persistent=False)
    assert agent.persistent is False
    mgr.kill("test-e")


def test_kill_agent():
    mgr = _make_mgr()
    mgr.spawn("test-k", role="tester")
    assert mgr.get("test-k") is not None
    mgr.kill("test-k")
    assert mgr.get("test-k") is None


def test_kill_nonexistent():
    mgr = _make_mgr()
    assert mgr.kill("nonexistent") is False


def test_heartbeat_detects_dead():
    mgr = _make_mgr()
    agent = mgr.spawn("test-d", role="tester")
    agent.process.kill()
    agent.process.wait()
    dead = mgr.check_heartbeats()
    assert "test-d" in dead
    assert mgr.get("test-d").state == STATE_DEAD
    mgr.kill("test-d")


def test_list_agents():
    mgr = _make_mgr()
    mgr.spawn("a1", role="r1")
    mgr.spawn("a2", role="r2")
    agents = mgr.list_agents()
    assert len(agents) == 2
    ids = {a.agent_id for a in agents}
    assert ids == {"a1", "a2"}
    mgr.kill("a1")
    mgr.kill("a2")


def test_send_prompt():
    mgr = _make_mgr()
    mgr.spawn("test-s", role="tester")
    ok = mgr.send_prompt("test-s", "hello world")
    assert ok is True
    assert mgr.get("test-s").state == STATE_WORKING
    mgr.kill("test-s")


def test_send_prompt_dead_agent():
    mgr = _make_mgr()
    assert mgr.send_prompt("nonexistent", "hello") is False


def test_read_output():
    mgr = _make_mgr()
    mgr.spawn("test-r", role="tester")
    mgr.send_prompt("test-r", "ping")
    time.sleep(0.5)
    output = mgr.read_output("test-r", timeout=2.0)
    assert output is not None
    assert "ping" in output
    mgr.kill("test-r")


def test_spawn_duplicate_alive_raises():
    mgr = _make_mgr()
    mgr.spawn("dup", role="tester")
    try:
        mgr.spawn("dup", role="tester")
        assert False, "Should have raised ValueError"
    except ValueError:
        pass
    mgr.kill("dup")


def test_spawn_over_dead_agent():
    mgr = _make_mgr()
    agent = mgr.spawn("respawn", role="tester")
    agent.process.kill()
    agent.process.wait()
    # Should be able to respawn
    new_agent = mgr.spawn("respawn", role="tester")
    assert new_agent.alive
    mgr.kill("respawn")
