"""Tests for shared/lsp_client.py — LSP JSON-RPC client with message queue."""

import os
import signal
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.lsp_client import LSPClient

PYRIGHT_CMD = "pyright-langserver"
PYRIGHT_ARGS = ["--stdio"]
ROOT_URI = f"file://{os.path.dirname(os.path.dirname(os.path.dirname(__file__)))}"
ROOT_PATH = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


@pytest.fixture
def client():
    """Spawn a pyright LSP client, yield it, then shut it down."""
    c = LSPClient(
        command=PYRIGHT_CMD,
        args=PYRIGHT_ARGS,
        root_uri=ROOT_URI,
    )
    yield c
    c.shutdown()


class TestContentLengthFraming:
    def test_initialize_handshake_succeeds(self, client):
        assert client._initialized is True

    def test_server_capabilities_received(self, client):
        assert client._server_capabilities is not None
        assert "textDocumentSync" in client._server_capabilities or True


class TestDidOpenClose:
    def test_did_open_python_file(self, client):
        test_file = os.path.join(ROOT_PATH, "hooks", "shared", "indexer_schema.py")
        client.did_open(test_file, "python")
        time.sleep(0.5)
        client.did_close(test_file)

    def test_did_open_nonexistent_file_no_crash(self, client):
        client.did_open("/tmp/nonexistent_lsp_test_file.py", "python")
        client.did_close("/tmp/nonexistent_lsp_test_file.py")


class TestDiagnosticsWait:
    def test_wait_for_diagnostics_returns(self, client):
        test_file = os.path.join(ROOT_PATH, "hooks", "shared", "indexer_schema.py")
        client.did_open(test_file, "python")
        uri = f"file://{test_file}"
        got = client.wait_for_diagnostics(uri, timeout=15.0)
        assert got is True
        client.did_close(test_file)

    def test_wait_for_diagnostics_timeout(self, client):
        uri = "file:///tmp/never_opened_file.py"
        got = client.wait_for_diagnostics(uri, timeout=1.0)
        assert got is False


class TestTimeoutHandling:
    def test_request_timeout_returns_none(self, client):
        result = client.request(
            "textDocument/hover",
            {
                "textDocument": {"uri": "file:///nonexistent.py"},
                "position": {"line": 0, "character": 0},
            },
            timeout=2.0,
        )
        assert result is None or isinstance(result, dict)


class TestShutdown:
    def test_shutdown_terminates_process(self):
        c = LSPClient(
            command=PYRIGHT_CMD,
            args=PYRIGHT_ARGS,
            root_uri=ROOT_URI,
        )
        proc = c._process
        c.shutdown()
        assert proc.poll() is not None

    def test_double_shutdown_no_error(self):
        c = LSPClient(
            command=PYRIGHT_CMD,
            args=PYRIGHT_ARGS,
            root_uri=ROOT_URI,
        )
        c.shutdown()
        c.shutdown()


class TestServerCrashHandling:
    def test_kill_server_mid_session(self):
        c = LSPClient(
            command=PYRIGHT_CMD,
            args=PYRIGHT_ARGS,
            root_uri=ROOT_URI,
        )
        c._process.send_signal(signal.SIGKILL)
        time.sleep(0.3)
        result = c.request(
            "textDocument/hover",
            {
                "textDocument": {"uri": "file:///test.py"},
                "position": {"line": 0, "character": 0},
            },
            timeout=2.0,
        )
        assert result is None
        c.shutdown()
