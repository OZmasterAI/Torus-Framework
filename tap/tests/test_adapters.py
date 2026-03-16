"""Tests for TAP adapters."""

from tap.adapters.claude import ClaudeAdapter
from tap.adapters.generic import GenericAdapter
from tap.adapters.goose import GooseAdapter
from tap.adapters.mock import MockAdapter


def test_claude_adapter_cmd():
    a = ClaudeAdapter(model="opus")
    cmd = a.spawn_cmd()
    assert "claude" in cmd[0]
    assert "--model" in cmd
    assert "opus" in cmd


def test_claude_adapter_name():
    a = ClaudeAdapter()
    assert a.name == "claude"


def test_goose_adapter_persistent():
    g = GooseAdapter(persistent=True)
    cmd = g.spawn_cmd()
    assert "goose" in cmd[0]
    assert "session" in cmd


def test_goose_adapter_ephemeral():
    g = GooseAdapter(persistent=False)
    cmd = g.spawn_cmd()
    assert "goose" in cmd[0]
    assert "run" in cmd
    assert "--no-session" in cmd


def test_generic_adapter_cmd():
    a = GenericAdapter(cmd=["echo", "hello"])
    assert a.spawn_cmd() == ["echo", "hello"]


def test_generic_adapter_isolates_cmd():
    """Mutating the returned cmd should not affect the adapter."""
    a = GenericAdapter(cmd=["echo", "hello"])
    cmd = a.spawn_cmd()
    cmd.append("extra")
    assert a.spawn_cmd() == ["echo", "hello"]


def test_mock_adapter_cmd():
    m = MockAdapter()
    cmd = m.spawn_cmd()
    assert "python" in cmd[0] or "python3" in cmd[0]
    assert "-c" in cmd


def test_adapter_format_input():
    a = MockAdapter()
    assert a.format_input("hello") == "hello\n"


def test_adapter_parse_output():
    a = MockAdapter()
    assert a.parse_output("  result: hello  ") == "result: hello"
