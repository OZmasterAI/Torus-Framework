"""Tests for Torus Voice web app — fire-and-forget server.py."""

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

import server
from server import TmuxError


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
        self._tmux_patch = patch("server.is_tmux_session_alive", new_callable=AsyncMock)
        self.mock_alive = self._tmux_patch.start()

    def tearDown(self):
        self._tmux_patch.stop()
        self._patcher.stop()

    def test_health_returns_ok(self):
        self.mock_alive.return_value = True
        request = MagicMock()
        resp = _run(server.health(request))
        body = json.loads(resp.body)
        assert body["status"] == "ok"
        assert body["tmux_alive"] is True
        assert body["tmux_target"] == "claude-bot"

    def test_health_tmux_dead(self):
        self.mock_alive.return_value = False
        request = MagicMock()
        resp = _run(server.health(request))
        body = json.loads(resp.body)
        assert body["tmux_alive"] is False


class TestWSAuth(unittest.TestCase):
    def setUp(self):
        self._patcher = patch.dict(server.CONFIG, TEST_CONFIG, clear=True)
        self._patcher.start()
        self._tmux_patch = patch("server.send_to_tmux", new_callable=AsyncMock)
        self.mock_tmux = self._tmux_patch.start()

    def tearDown(self):
        self._tmux_patch.stop()
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
        self._tmux_patch = patch("server.send_to_tmux", new_callable=AsyncMock)
        self.mock_tmux = self._tmux_patch.start()

    def tearDown(self):
        self._tmux_patch.stop()
        self._patcher.stop()

    def test_send_message_gets_confirmation(self):
        ws = MockWebSocket(query_params={"token": "test-token-123"})
        ws.enqueue({"type": "message", "text": "Hello Claude"})
        ws.enqueue_disconnect()
        _run(server.ws_endpoint(ws))

        types = [m["type"] for m in ws.sent]
        assert "sent" in types
        sent_msg = next(m for m in ws.sent if m["type"] == "sent")
        assert sent_msg["text"] == "Sent!"

    def test_send_to_tmux_called(self):
        ws = MockWebSocket(query_params={"token": "test-token-123"})
        ws.enqueue({"type": "message", "text": "Hello Claude"})
        ws.enqueue_disconnect()
        _run(server.ws_endpoint(ws))

        self.mock_tmux.assert_called_once_with("Hello Claude", target="claude-bot")

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
        self.mock_tmux.side_effect = TmuxError("tmux target not found")

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


class TestSendToTmux(unittest.TestCase):
    """Test the fire-and-forget send_to_tmux function."""

    def test_send_calls_send_keys(self):
        with patch("server.is_tmux_session_alive", new_callable=AsyncMock) as mock_alive, \
             patch("server._send_keys", new_callable=AsyncMock) as mock_keys:
            mock_alive.return_value = True
            _run(server.send_to_tmux("hello world", target="claude-bot"))
            mock_keys.assert_called_once_with("claude-bot", "hello world")

    def test_send_raises_when_tmux_dead(self):
        with patch("server.is_tmux_session_alive", new_callable=AsyncMock) as mock_alive:
            mock_alive.return_value = False
            with self.assertRaises(TmuxError) as ctx:
                _run(server.send_to_tmux("hello", target="claude-bot"))
            assert "not found" in str(ctx.exception)


if __name__ == "__main__":
    unittest.main()
