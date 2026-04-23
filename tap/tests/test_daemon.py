"""Tests for TAP daemon and client."""

import os
import tempfile
import time

import pytest

# Override agent_channel DB for tests
import sys

sys.path.insert(0, os.path.expanduser("~/.claude/hooks"))
import shared.agent_channel as _ac

from tap.adapters.mock import MockAdapter
from tap.client import TAPClient
from tap.daemon import TAPDaemon
from tap.storage import TAPStorage


@pytest.fixture()
def daemon(tmp_path):
    """Start a daemon with mock adapter on a temp socket."""
    sock = str(tmp_path / "tap-test.sock")
    _ac.DB_PATH = str(tmp_path / "test.db")

    d = TAPDaemon(
        socket_path=sock,
        adapter_factory=MockAdapter,
        storage=TAPStorage(),
    )
    d.start_background()
    time.sleep(0.3)  # let server bind
    yield d, sock
    d.stop()


def test_daemon_accepts_connection(daemon):
    d, sock = daemon
    client = TAPClient(sock)
    resp = client.heartbeat("__daemon__")
    assert resp["alive"] is True
    assert resp["state"] == "running"


def test_spawn_via_rpc(daemon):
    d, sock = daemon
    client = TAPClient(sock)
    resp = client.spawn("test-1", role="tester", model="mock")
    assert resp["status"] == "ready"
    assert resp["agent_id"] == "test-1"
    assert resp["pid"] > 0


def test_dispatch_via_rpc(daemon):
    d, sock = daemon
    client = TAPClient(sock)
    client.spawn("t1", role="tester")
    resp = client.send("t1", "test task")
    assert resp["accepted"] is True
    assert resp["task_id"]


def test_kill_via_rpc(daemon):
    d, sock = daemon
    client = TAPClient(sock)
    client.spawn("k1", role="tester")
    resp = client.kill("k1")
    assert resp["killed"] is True


def test_agent_list(daemon):
    d, sock = daemon
    client = TAPClient(sock)
    client.spawn("a1", role="r1")
    client.spawn("a2", role="r2")
    resp = client.status()
    assert len(resp["agents"]) == 2
    ids = {a["agent_id"] for a in resp["agents"]}
    assert ids == {"a1", "a2"}


def test_agent_heartbeat(daemon):
    d, sock = daemon
    client = TAPClient(sock)
    client.spawn("h1", role="tester")
    resp = client.status("h1")
    assert resp["alive"] is True
    assert resp["agent_id"] == "h1"


def test_broadcast(daemon):
    d, sock = daemon
    client = TAPClient(sock)
    resp = client.broadcast("hello all", from_agent="test")
    assert resp["sent"] is True


def test_unknown_method(daemon):
    d, sock = daemon
    client = TAPClient(sock)
    with pytest.raises(RuntimeError, match="Unknown method"):
        client.call("nonexistent/method", {})


def test_task_status(daemon):
    d, sock = daemon
    client = TAPClient(sock)
    client.spawn("s1", role="tester")
    resp = client.send("s1", "status task")
    tid = resp["task_id"]
    status = client.task_status(tid)
    assert status["task_id"] == tid
    assert status["status"] == "pending"
