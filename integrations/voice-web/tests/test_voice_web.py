"""Tests for Torus Voice web app — server.py WebSocket + HTTP endpoints."""

import asyncio
import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Add voice-web to path so we can import server components
_HERE = os.path.dirname(os.path.abspath(__file__))
_VOICE_WEB = os.path.dirname(_HERE)
sys.path.insert(0, _VOICE_WEB)

# Mock tmux_runner before importing server
sys.modules["tmux_runner"] = MagicMock()
import tmux_runner

tmux_runner.TmuxError = type("TmuxError", (Exception,), {})
tmux_runner.run_claude_tmux = AsyncMock(return_value=("Hello from Claude!", None))
tmux_runner.is_tmux_session_alive = AsyncMock(return_value=True)

# Now import server
import server


def _run(coro):
    """Run async coroutine synchronously."""
    return asyncio.new_event_loop().run_until_complete(coro)


TEST_CONFIG = {
    "auth_token": "test-token-123",
    "tmux_target": "claude-bot",
    "port": 8443,
    "host": "0.0.0.0",
    "response_timeout": 120,
    "max_message_length": 4000,
}


class MockWebSocket:
    """Minimal mock for Starlette WebSocket."""

    def __init__(self, query_params=None):
        self.query_params = query_params or {}
        self.accepted = False
        self.closed = False
        self.close_code = None
        self.sent = []
        self._receive_queue = asyncio.Queue()

    async def accept(self):
        self.accepted = True

    async def close(self, code=1000):
        self.closed = True
        self.close_code = code

    async def send_json(self, data):
        self.sent.append(data)

    async def receive_json(self):
        item = await self._receive_queue.get()
        if isinstance(item, Exception):
            raise item
        return item

    def enqueue(self, data):
        self._receive_queue.put_nowait(data)

    def enqueue_disconnect(self):
        from starlette.websockets import WebSocketDisconnect
        self._receive_queue.put_nowait(WebSocketDisconnect())


class TestHealth(unittest.TestCase):
    def setUp(self):
        self._patcher = patch.dict(server.CONFIG, TEST_CONFIG, clear=True)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()

    def test_health_returns_ok(self):
        tmux_runner.is_tmux_session_alive.return_value = True
        request = MagicMock()
        resp = _run(server.health(request))
        body = json.loads(resp.body)
        assert body["status"] == "ok"
        assert body["tmux_alive"] is True
        assert body["tmux_target"] == "claude-bot"

    def test_health_tmux_dead(self):
        tmux_runner.is_tmux_session_alive.return_value = False
        request = MagicMock()
        resp = _run(server.health(request))
        body = json.loads(resp.body)
        assert body["tmux_alive"] is False


class TestWSAuth(unittest.TestCase):
    def setUp(self):
        self._patcher = patch.dict(server.CONFIG, TEST_CONFIG, clear=True)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()

    def test_auth_via_query_param(self):
        ws = MockWebSocket(query_params={"token": "test-token-123"})
        ws.enqueue_disconnect()
        _run(server.ws_endpoint(ws))
        assert ws.accepted
        assert ws.sent[0] == {"type": "status", "text": "authenticated"}

    def test_auth_via_message(self):
        ws = MockWebSocket()
        ws.enqueue({"type": "auth", "token": "test-token-123"})
        ws.enqueue_disconnect()
        _run(server.ws_endpoint(ws))
        assert ws.accepted
        statuses = [m for m in ws.sent if m.get("type") == "status"]
        assert any(s["text"] == "authenticated" for s in statuses)

    def test_auth_bad_token(self):
        ws = MockWebSocket()
        ws.enqueue({"type": "auth", "token": "wrong-token"})
        _run(server.ws_endpoint(ws))
        assert ws.sent[-1] == {"type": "error", "text": "Invalid token"}
        assert ws.closed
        assert ws.close_code == 1008


class TestWSMessages(unittest.TestCase):
    def setUp(self):
        self._patcher = patch.dict(server.CONFIG, TEST_CONFIG, clear=True)
        self._patcher.start()
        tmux_runner.run_claude_tmux.side_effect = None
        tmux_runner.run_claude_tmux.return_value = ("Hello from Claude!", None)

    def tearDown(self):
        self._patcher.stop()

    def test_send_message_gets_response(self):
        tmux_runner.run_claude_tmux.return_value = ("Test response", None)

        ws = MockWebSocket(query_params={"token": "test-token-123"})
        ws.enqueue({"type": "message", "text": "Hello Claude"})
        ws.enqueue_disconnect()
        _run(server.ws_endpoint(ws))

        types = [m["type"] for m in ws.sent]
        assert "status" in types
        assert "response" in types
        resp = next(m for m in ws.sent if m["type"] == "response")
        assert resp["text"] == "Test response"

    def test_thinking_status_sent(self):
        tmux_runner.run_claude_tmux.return_value = ("Response", None)

        ws = MockWebSocket(query_params={"token": "test-token-123"})
        ws.enqueue({"type": "message", "text": "test"})
        ws.enqueue_disconnect()
        _run(server.ws_endpoint(ws))

        statuses = [m for m in ws.sent if m.get("text") == "thinking"]
        assert len(statuses) == 1

    def test_empty_message_rejected(self):
        ws = MockWebSocket(query_params={"token": "test-token-123"})
        ws.enqueue({"type": "message", "text": "   "})
        ws.enqueue_disconnect()
        _run(server.ws_endpoint(ws))

        errors = [m for m in ws.sent if m["type"] == "error"]
        assert any("Empty" in e["text"] for e in errors)

    def test_message_too_long(self):
        ws = MockWebSocket(query_params={"token": "test-token-123"})
        ws.enqueue({"type": "message", "text": "x" * 5000})
        ws.enqueue_disconnect()
        _run(server.ws_endpoint(ws))

        errors = [m for m in ws.sent if m["type"] == "error"]
        assert any("too long" in e["text"] for e in errors)

    def test_tmux_error_sent_to_client(self):
        tmux_runner.run_claude_tmux.side_effect = tmux_runner.TmuxError("tmux target not found")

        ws = MockWebSocket(query_params={"token": "test-token-123"})
        ws.enqueue({"type": "message", "text": "Hello"})
        ws.enqueue_disconnect()
        _run(server.ws_endpoint(ws))

        errors = [m for m in ws.sent if m["type"] == "error"]
        assert any("tmux target not found" in e["text"] for e in errors)

    def test_non_message_type_ignored(self):
        ws = MockWebSocket(query_params={"token": "test-token-123"})
        ws.enqueue({"type": "ping"})
        ws.enqueue_disconnect()
        _run(server.ws_endpoint(ws))

        assert ws.sent[0] == {"type": "status", "text": "authenticated"}
        assert len(ws.sent) == 1


class TestConfig(unittest.TestCase):
    def test_config_has_required_keys(self):
        cfg = server.CONFIG
        assert "auth_token" in cfg
        assert "tmux_target" in cfg
        assert "port" in cfg

    def test_static_dir_exists(self):
        static = os.path.join(_VOICE_WEB, "static")
        assert os.path.isdir(static)

    def test_index_html_exists(self):
        index = os.path.join(_VOICE_WEB, "static", "index.html")
        assert os.path.isfile(index)


class TestTmuxRunnerIntegration(unittest.TestCase):
    def setUp(self):
        self._patcher = patch.dict(server.CONFIG, TEST_CONFIG, clear=True)
        self._patcher.start()
        tmux_runner.run_claude_tmux.side_effect = None
        tmux_runner.run_claude_tmux.return_value = ("OK", None)

    def tearDown(self):
        self._patcher.stop()

    def test_run_claude_tmux_called_with_correct_args(self):
        ws = MockWebSocket(query_params={"token": "test-token-123"})
        ws.enqueue({"type": "message", "text": "test message"})
        ws.enqueue_disconnect()
        _run(server.ws_endpoint(ws))

        tmux_runner.run_claude_tmux.assert_called_with(
            "test message",
            tmux_target="claude-bot",
            timeout=120,
        )


if __name__ == "__main__":
    unittest.main()
