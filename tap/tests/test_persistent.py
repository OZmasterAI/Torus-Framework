"""Tests for TAP persistent mode (Hybrid Option C)."""

import json
import os
import subprocess
import time

import pytest

# --- Task 1: Constants + mode tracking ---


def test_persistent_constants_exist():
    from tap.constants import MODE_EPHEMERAL, MODE_STREAMING, WATCHDOG_TIMEOUT

    assert WATCHDOG_TIMEOUT == 30
    assert MODE_STREAMING == "streaming"
    assert MODE_EPHEMERAL == "ephemeral"


def test_managed_agent_has_mode_and_session_id():
    from tap.adapters.mock import MockAdapter
    from tap.agent_manager import ManagedAgent
    from tap.constants import MODE_STREAMING

    proc = subprocess.Popen(
        ["echo"],
        stdout=subprocess.PIPE,
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    agent = ManagedAgent(
        agent_id="test",
        role="test",
        model="sonnet",
        persistent=True,
        adapter=MockAdapter(),
        process=proc,
    )
    assert agent.mode == MODE_STREAMING
    assert agent.session_id is None
    assert agent.degraded_reason is None
    proc.wait()


# --- Task 2: ClaudeStreamParser ---


def test_parse_system_message():
    from tap.adapters.claude import ClaudeStreamParser

    line = '{"type":"system","session_id":"abc-123","model":"claude-sonnet-4-6"}'
    msg = ClaudeStreamParser.parse(line)
    assert msg["type"] == "system"
    assert msg["session_id"] == "abc-123"


def test_parse_result_message():
    from tap.adapters.claude import ClaudeStreamParser

    line = '{"type":"result","subtype":"success","result":"The answer is 4","session_id":"abc-123"}'
    msg = ClaudeStreamParser.parse(line)
    assert msg["type"] == "result"
    assert msg["result"] == "The answer is 4"


def test_parse_assistant_message():
    from tap.adapters.claude import ClaudeStreamParser

    line = '{"type":"assistant","message":{"content":[{"type":"text","text":"Hello"}]}}'
    msg = ClaudeStreamParser.parse(line)
    assert msg["type"] == "assistant"


def test_parse_invalid_json():
    from tap.adapters.claude import ClaudeStreamParser

    msg = ClaudeStreamParser.parse("not json")
    assert msg is None


def test_parse_empty_line():
    from tap.adapters.claude import ClaudeStreamParser

    assert ClaudeStreamParser.parse("") is None
    assert ClaudeStreamParser.parse("   ") is None


def test_is_turn_complete():
    from tap.adapters.claude import ClaudeStreamParser

    assert ClaudeStreamParser.is_turn_complete({"type": "result"}) is True
    assert ClaudeStreamParser.is_turn_complete({"type": "assistant"}) is False
    assert ClaudeStreamParser.is_turn_complete({"type": "system"}) is False


def test_extract_result_from_result():
    from tap.adapters.claude import ClaudeStreamParser

    msg = {"type": "result", "result": "42"}
    assert ClaudeStreamParser.extract_result(msg) == "42"


def test_extract_result_from_assistant():
    from tap.adapters.claude import ClaudeStreamParser

    msg = {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "text", "text": "Hello "},
                {"type": "text", "text": "world"},
            ]
        },
    }
    assert ClaudeStreamParser.extract_result(msg) == "Hello world"


def test_extract_session_id():
    from tap.adapters.claude import ClaudeStreamParser

    assert ClaudeStreamParser.extract_session_id({"session_id": "abc"}) == "abc"
    assert ClaudeStreamParser.extract_session_id({"type": "assistant"}) is None


def test_format_stream_input():
    from tap.adapters.claude import ClaudeStreamParser

    parser = ClaudeStreamParser()
    ndjson = parser.format_prompt("hello world", session_id="abc-123")
    data = json.loads(ndjson.strip())
    assert data["type"] == "user"
    assert data["message"]["content"] == "hello world"
    assert data["session_id"] == "abc-123"
    assert data["parent_tool_use_id"] is None


def test_format_stream_input_default_session():
    from tap.adapters.claude import ClaudeStreamParser

    parser = ClaudeStreamParser()
    ndjson = parser.format_prompt("test")
    data = json.loads(ndjson.strip())
    assert data["session_id"] == "default"


# --- Task 3: ClaudeAdapter spawn_cmd ---


def test_claude_adapter_persistent_uses_stream_json():
    from tap.adapters.claude import ClaudeAdapter

    adapter = ClaudeAdapter(model="sonnet", persistent=True)
    cmd = adapter.spawn_cmd()
    assert "--input-format" in cmd
    assert "stream-json" in cmd
    assert "--output-format" in cmd


def test_claude_adapter_ephemeral_uses_json():
    from tap.adapters.claude import ClaudeAdapter

    adapter = ClaudeAdapter(model="sonnet", persistent=False)
    cmd = adapter.spawn_cmd()
    assert "--input-format" not in cmd
    assert "json" in cmd


def test_claude_adapter_resume_session():
    from tap.adapters.claude import ClaudeAdapter

    adapter = ClaudeAdapter(
        model="sonnet", persistent=False, resume_session_id="sess-abc"
    )
    cmd = adapter.spawn_cmd()
    assert "--resume" in cmd
    assert "sess-abc" in cmd


def test_claude_adapter_format_input_persistent():
    from tap.adapters.claude import ClaudeAdapter

    adapter = ClaudeAdapter(model="sonnet", persistent=True)
    output = adapter.format_input("hello")
    data = json.loads(output.strip())
    assert data["type"] == "user"
    assert data["message"]["content"] == "hello"


def test_claude_adapter_format_input_ephemeral():
    from tap.adapters.claude import ClaudeAdapter

    adapter = ClaudeAdapter(model="sonnet", persistent=False)
    output = adapter.format_input("hello")
    assert output == "hello\n"


# --- Task 4: Watchdog ---


def test_watchdog_detects_idle_after_result():
    from tap.adapters.mock import MockAdapter
    from tap.agent_manager import AgentManager

    mgr = AgentManager(adapter_factory=lambda **kw: MockAdapter(**kw))
    agent = mgr.spawn("w1", role="test", persistent=True)

    # Simulate: result received 31s ago (past 30s timeout)
    agent._last_result_time = time.time() - 31
    agent._result_received = True

    timed_out = mgr._check_watchdog("w1")
    assert timed_out is True


def test_watchdog_does_not_fire_during_active_output():
    from tap.adapters.mock import MockAdapter
    from tap.agent_manager import AgentManager

    mgr = AgentManager(adapter_factory=lambda **kw: MockAdapter(**kw))
    agent = mgr.spawn("w2", role="test", persistent=True)

    agent._last_result_time = None
    agent._result_received = False

    timed_out = mgr._check_watchdog("w2")
    assert timed_out is False


def test_watchdog_does_not_fire_within_timeout():
    from tap.adapters.mock import MockAdapter
    from tap.agent_manager import AgentManager

    mgr = AgentManager(adapter_factory=lambda **kw: MockAdapter(**kw))
    agent = mgr.spawn("w3", role="test", persistent=True)

    # Result received 5s ago — within 30s timeout
    agent._last_result_time = time.time() - 5
    agent._result_received = True

    timed_out = mgr._check_watchdog("w3")
    assert timed_out is False


# --- Task 5: Stream-json send/read ---


def test_send_prompt_persistent_does_not_close_stdin():
    from tap.adapters.mock import MockAdapter
    from tap.agent_manager import AgentManager
    from tap.constants import MODE_STREAMING

    mgr = AgentManager(adapter_factory=lambda **kw: MockAdapter(**kw))
    agent = mgr.spawn("s1", role="test", persistent=True)
    agent.mode = MODE_STREAMING

    mgr.send_prompt("s1", "what is 2+2")
    assert not agent.process.stdin.closed


def test_send_prompt_ephemeral_closes_stdin():
    from tap.adapters.mock import MockAdapter
    from tap.agent_manager import AgentManager
    from tap.constants import MODE_EPHEMERAL

    mgr = AgentManager(adapter_factory=lambda **kw: MockAdapter(**kw))
    agent = mgr.spawn("s2", role="test", persistent=False)
    agent.mode = MODE_EPHEMERAL

    mgr.send_prompt("s2", "what is 2+2")
    assert agent.process.stdin.closed


def test_read_stream_output_captures_session_id():
    from tap.adapters.claude import ClaudeStreamParser

    system_line = '{"type":"system","session_id":"captured-id","model":"sonnet"}'
    msg = ClaudeStreamParser.parse(system_line)
    sid = ClaudeStreamParser.extract_session_id(msg)
    assert sid == "captured-id"


# --- Task 6: Fallback ---


def test_fallback_on_dead_process():
    from tap.adapters.mock import MockAdapter
    from tap.agent_manager import AgentManager
    from tap.constants import MODE_EPHEMERAL

    mgr = AgentManager(adapter_factory=lambda **kw: MockAdapter(**kw))
    agent = mgr.spawn("f1", role="test", persistent=True)
    agent.session_id = "saved-session-id"

    # Kill the process to simulate crash
    agent.process.kill()
    agent.process.wait()

    recovered = mgr._fallback_to_ephemeral("f1")
    assert recovered is True

    agent = mgr.get("f1")
    assert agent.mode == MODE_EPHEMERAL
    assert agent.degraded_reason is not None
    assert agent.alive


def test_fallback_preserves_session_id():
    from tap.adapters.mock import MockAdapter
    from tap.agent_manager import AgentManager

    mgr = AgentManager(adapter_factory=lambda **kw: MockAdapter(**kw))
    agent = mgr.spawn("f2", role="test", persistent=True)
    agent.session_id = "keep-this-id"
    agent.process.kill()
    agent.process.wait()

    mgr._fallback_to_ephemeral("f2")
    agent = mgr.get("f2")
    assert agent.session_id == "keep-this-id"


def test_fallback_nonexistent_agent():
    from tap.adapters.mock import MockAdapter
    from tap.agent_manager import AgentManager

    mgr = AgentManager(adapter_factory=lambda **kw: MockAdapter(**kw))
    assert mgr._fallback_to_ephemeral("nope") is False


# --- Task 7: Daemon RPC mode info ---


def test_agent_list_shows_mode(tmp_path):
    os.environ["TAP_DB_PATH"] = str(tmp_path / "tap.db")
    from tap.adapters.mock import MockAdapter
    from tap.daemon import TAPDaemon

    sock = str(tmp_path / "tap.sock")
    daemon = TAPDaemon(
        socket_path=sock,
        adapter_factory=lambda **kw: MockAdapter(**kw),
    )
    daemon.start_background()
    try:
        daemon._dispatch("session/spawn", {"agent_id": "m1", "role": "test"})
        listing = daemon._dispatch("agent/list", {})
        agent_info = listing["agents"][0]
        assert "mode" in agent_info
        assert agent_info["mode"] in ("streaming", "ephemeral")
    finally:
        daemon.stop()
        os.environ.pop("TAP_DB_PATH", None)


def test_heartbeat_shows_mode(tmp_path):
    os.environ["TAP_DB_PATH"] = str(tmp_path / "tap.db")
    from tap.adapters.mock import MockAdapter
    from tap.daemon import TAPDaemon

    sock = str(tmp_path / "tap.sock")
    daemon = TAPDaemon(
        socket_path=sock,
        adapter_factory=lambda **kw: MockAdapter(**kw),
    )
    daemon.start_background()
    try:
        daemon._dispatch("session/spawn", {"agent_id": "m2", "role": "test"})
        hb = daemon._dispatch("agent/heartbeat", {"agent_id": "m2"})
        assert "mode" in hb
    finally:
        daemon.stop()
        os.environ.pop("TAP_DB_PATH", None)


def test_context_shows_session_id(tmp_path):
    os.environ["TAP_DB_PATH"] = str(tmp_path / "tap.db")
    from tap.adapters.mock import MockAdapter
    from tap.daemon import TAPDaemon

    sock = str(tmp_path / "tap.sock")
    daemon = TAPDaemon(
        socket_path=sock,
        adapter_factory=lambda **kw: MockAdapter(**kw),
    )
    daemon.start_background()
    try:
        daemon._dispatch("session/spawn", {"agent_id": "m3", "role": "test"})
        ctx = daemon._dispatch("agent/context", {"agent_id": "m3"})
        assert "session_id" in ctx
        assert "mode" in ctx
    finally:
        daemon.stop()
        os.environ.pop("TAP_DB_PATH", None)


# --- Task 9: Integration tests ---


def test_persistent_multi_turn_same_process(tmp_path):
    """Spawn persistent agent, send 3 tasks — same process stays alive."""
    os.environ["TAP_DB_PATH"] = str(tmp_path / "tap.db")
    from tap.adapters.mock import MockAdapter
    from tap.daemon import TAPDaemon

    sock = str(tmp_path / "tap.sock")
    daemon = TAPDaemon(
        socket_path=sock,
        adapter_factory=lambda **kw: MockAdapter(**kw),
    )
    daemon.start_background()
    try:
        daemon._dispatch(
            "session/spawn", {"agent_id": "p1", "role": "test", "persistent": True}
        )
        agent = daemon.manager.get("p1")
        pid_1 = agent.process.pid

        for i in range(3):
            daemon._dispatch(
                "task/dispatch",
                {
                    "agent_id": "p1",
                    "title": f"task {i}",
                    "description": f"do thing {i}",
                },
            )

        assert agent.process.pid == pid_1
        assert agent.alive
    finally:
        daemon.stop()
        os.environ.pop("TAP_DB_PATH", None)


def test_fallback_integration(tmp_path):
    """Spawn persistent, kill process, fallback to ephemeral, verify alive."""
    os.environ["TAP_DB_PATH"] = str(tmp_path / "tap.db")
    from tap.adapters.mock import MockAdapter
    from tap.constants import MODE_EPHEMERAL
    from tap.daemon import TAPDaemon

    sock = str(tmp_path / "tap.sock")
    daemon = TAPDaemon(
        socket_path=sock,
        adapter_factory=lambda **kw: MockAdapter(**kw),
    )
    daemon.start_background()
    try:
        daemon._dispatch(
            "session/spawn", {"agent_id": "fb1", "role": "test", "persistent": True}
        )
        agent = daemon.manager.get("fb1")
        agent.session_id = "test-session"

        agent.process.kill()
        agent.process.wait()
        daemon.manager._fallback_to_ephemeral("fb1")

        agent = daemon.manager.get("fb1")
        assert agent.mode == MODE_EPHEMERAL
        assert agent.alive
        assert agent.degraded_reason is not None

        listing = daemon._dispatch("agent/list", {})
        agent_info = listing["agents"][0]
        assert agent_info["mode"] == MODE_EPHEMERAL
        assert agent_info["degraded_reason"] is not None
    finally:
        daemon.stop()
        os.environ.pop("TAP_DB_PATH", None)


def test_ephemeral_mode_unchanged(tmp_path):
    """Ephemeral agents should work exactly as before."""
    os.environ["TAP_DB_PATH"] = str(tmp_path / "tap.db")
    from tap.adapters.mock import MockAdapter
    from tap.daemon import TAPDaemon

    sock = str(tmp_path / "tap.sock")
    daemon = TAPDaemon(
        socket_path=sock,
        adapter_factory=lambda **kw: MockAdapter(**kw),
    )
    daemon.start_background()
    try:
        daemon._dispatch(
            "session/spawn", {"agent_id": "e1", "role": "test", "persistent": False}
        )
        agent = daemon.manager.get("e1")
        assert agent.persistent is False
    finally:
        daemon.stop()
        os.environ.pop("TAP_DB_PATH", None)
