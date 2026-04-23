"""Tests for TAP storage bridge."""

import os
import tempfile

import pytest

# Redirect agent_channel to a temp DB for testing
_tmp = tempfile.mktemp(suffix=".db")
os.environ.setdefault("_TAP_TEST_DB", _tmp)

import sys

sys.path.insert(0, os.path.expanduser("~/.claude/hooks"))
import shared.agent_channel as _ac

_ac.DB_PATH = _tmp  # override before any connections

from tap.storage import TAPStorage


@pytest.fixture(autouse=True)
def clean_db():
    """Reset DB between tests."""
    _ac.DB_PATH = tempfile.mktemp(suffix=".db")
    yield
    try:
        os.unlink(_ac.DB_PATH)
    except OSError:
        pass


def test_dispatch_creates_task():
    store = TAPStorage()
    tid = store.dispatch("agent-1", "fix bug", priority=3)
    assert tid is not None
    task = store.get(tid)
    assert task is not None
    assert (
        task["status"] == "pending"
    )  # dispatch creates, doesn't auto-assign via claim
    assert task["assigned_to"] == "agent-1"


def test_complete_task():
    store = TAPStorage()
    tid = store.dispatch("agent-1", "fix bug")
    ok = store.complete(tid, "fixed in auth.py")
    assert ok is True
    task = store.get(tid)
    assert task["status"] == "done"
    assert "auth.py" in task["result"]


def test_fail_task():
    store = TAPStorage()
    tid = store.dispatch("agent-1", "fix bug")
    ok = store.fail(tid, "could not reproduce")
    assert ok is True
    task = store.get(tid)
    assert task["status"] == "failed"


def test_dispatch_to_role():
    store = TAPStorage()
    tid = store.dispatch_to_role("researcher", "find API docs", priority=2)
    assert tid is not None
    task = store.get(tid)
    assert task["required_role"] == "researcher"
    assert task["priority"] == 2


def test_pending_tasks():
    store = TAPStorage()
    store.dispatch_to_role("researcher", "task A")
    store.dispatch_to_role("builder", "task B")
    store.dispatch_to_role("researcher", "task C")

    all_pending = store.pending()
    assert len(all_pending) == 3

    researcher_pending = store.pending(role="researcher")
    assert len(researcher_pending) == 2


def test_claim_task():
    store = TAPStorage()
    store.dispatch_to_role("researcher", "research task")
    task = store.claim("agent-r1", role="researcher")
    assert task is not None
    assert task["title"] == "research task"
    assert task["status"] == "assigned"

    # No more tasks
    assert store.claim("agent-r2", role="researcher") is None


def test_broadcast_and_read():
    store = TAPStorage()
    ok = store.broadcast("agent-1", "hello all")
    assert ok is True

    msgs = store.read("agent-2", since=0.0)
    assert len(msgs) >= 1
    assert any("hello all" in m["content"] for m in msgs)
