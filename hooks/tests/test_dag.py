#!/usr/bin/env python3
"""Tests for shared.dag — ConversationDAG SQLite storage."""

import json
import os
import sys
import tempfile
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.dag import ConversationDAG
from shared.dag_hooks import (
    DAGHookRegistry,
    ON_NODE_ADDED,
    ON_BRANCH_SWITCH,
    ON_BRANCH_CREATED,
    ON_BRANCH_RESET,
)


# --- Task 1: DAG core ---


class TestDAGCore:
    def test_create_and_add_node(self):
        with tempfile.TemporaryDirectory() as d:
            dag = ConversationDAG(os.path.join(d, "test.db"))
            nid = dag.add_node(parent_id="", role="user", content="hello")
            assert nid.startswith("nd_")
            node = dag.get_node(nid)
            assert node["role"] == "user"
            assert node["content"] == "hello"
            dag.close()

    def test_ancestor_chain(self):
        with tempfile.TemporaryDirectory() as d:
            dag = ConversationDAG(os.path.join(d, "test.db"))
            n1 = dag.add_node("", "user", "hello")
            n2 = dag.add_node(n1, "assistant", "hi there")
            n3 = dag.add_node(n2, "user", "how are you")
            ancestors = dag.get_ancestors(n3)
            assert len(ancestors) == 3
            assert ancestors[0]["content"] == "hello"
            assert ancestors[2]["content"] == "how are you"
            dag.close()

    def test_branch_and_fork(self):
        with tempfile.TemporaryDirectory() as d:
            dag = ConversationDAG(os.path.join(d, "test.db"))
            n1 = dag.add_node("", "user", "hello")
            n2 = dag.add_node(n1, "assistant", "hi")
            old_branch = dag.current_branch_id()
            bid = dag.new_branch("test-branch")
            assert bid.startswith("br_")
            assert dag.current_branch_id() != old_branch
            head = dag.get_head()
            assert head == ""
            dag.close()

    def test_branch_preserves_fork_point(self):
        with tempfile.TemporaryDirectory() as d:
            dag = ConversationDAG(os.path.join(d, "test.db"))
            n1 = dag.add_node("", "user", "hello")
            n2 = dag.add_node(n1, "assistant", "hi")
            dag.new_branch("fork-test")
            branches = dag.list_branches()
            new_br = [b for b in branches if b["name"] == "fork-test"][0]
            assert new_br["forked_from"] == n2
            dag.close()

    def test_prompt_from(self):
        with tempfile.TemporaryDirectory() as d:
            dag = ConversationDAG(os.path.join(d, "test.db"))
            n1 = dag.add_node("", "user", "hello")
            n2 = dag.add_node(n1, "assistant", "hi")
            msgs = dag.prompt_from(n2)
            assert len(msgs) == 2
            assert msgs[0]["role"] == "user"
            assert msgs[1]["role"] == "assistant"
            dag.close()

    def test_get_head_advances(self):
        with tempfile.TemporaryDirectory() as d:
            dag = ConversationDAG(os.path.join(d, "test.db"))
            assert dag.get_head() == ""
            n1 = dag.add_node("", "user", "hello")
            assert dag.get_head() == n1
            n2 = dag.add_node(n1, "assistant", "hi")
            assert dag.get_head() == n2
            dag.close()

    def test_reset_head(self):
        with tempfile.TemporaryDirectory() as d:
            dag = ConversationDAG(os.path.join(d, "test.db"))
            dag.add_node("", "user", "hello")
            dag.reset_head()
            assert dag.get_head() == ""
            dag.close()

    def test_switch_branch(self):
        with tempfile.TemporaryDirectory() as d:
            dag = ConversationDAG(os.path.join(d, "test.db"))
            dag.add_node("", "user", "hello")
            old = dag.current_branch_id()
            bid = dag.new_branch("other")
            dag.switch_branch(old)
            assert dag.current_branch_id() == old
            dag.close()

    def test_switch_branch_invalid(self):
        with tempfile.TemporaryDirectory() as d:
            dag = ConversationDAG(os.path.join(d, "test.db"))
            with pytest.raises(ValueError):
                dag.switch_branch("br_nonexistent")
            dag.close()

    def test_branch_from(self):
        with tempfile.TemporaryDirectory() as d:
            dag = ConversationDAG(os.path.join(d, "test.db"))
            n1 = dag.add_node("", "user", "hello")
            n2 = dag.add_node(n1, "assistant", "hi")
            bid = dag.branch_from(n2, "sub-branch")
            assert dag.get_head() == n2  # inherits history
            ancestors = dag.get_ancestors(dag.get_head())
            assert len(ancestors) == 2
            dag.close()

    def test_current_branch_info(self):
        with tempfile.TemporaryDirectory() as d:
            dag = ConversationDAG(os.path.join(d, "test.db"))
            dag.add_node("", "user", "hello")
            dag.add_node(dag.get_head(), "assistant", "hi")
            info = dag.current_branch_info()
            assert info["msg_count"] == 2
            assert info["name"] == "main"
            assert info["total_branches"] == 1
            dag.close()

    def test_list_branches(self):
        with tempfile.TemporaryDirectory() as d:
            dag = ConversationDAG(os.path.join(d, "test.db"))
            dag.add_node("", "user", "hello")
            dag.new_branch("b2")
            dag.new_branch("b3")
            branches = dag.list_branches()
            assert len(branches) == 3
            names = {b["name"] for b in branches}
            assert names == {"main", "b2", "b3"}
            dag.close()

    def test_node_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            dag = ConversationDAG(os.path.join(d, "test.db"))
            nid = dag.add_node(
                "", "user", "fix bug", metadata={"memory_ids": ["abc123"]}
            )
            node = dag.get_node(nid)
            assert "abc123" in node["metadata"].get("memory_ids", [])
            dag.close()

    def test_update_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            dag = ConversationDAG(os.path.join(d, "test.db"))
            nid = dag.add_node("", "user", "hello")
            dag.update_metadata(nid, {"memory_ids": ["m1"]})
            node = dag.get_node(nid)
            assert node["metadata"]["memory_ids"] == ["m1"]
            # Merge, not replace
            dag.update_metadata(nid, {"extra": "data"})
            node = dag.get_node(nid)
            assert node["metadata"]["memory_ids"] == ["m1"]
            assert node["metadata"]["extra"] == "data"
            dag.close()

    def test_build_summary(self):
        with tempfile.TemporaryDirectory() as d:
            dag = ConversationDAG(os.path.join(d, "test.db"))
            parent = ""
            for i in range(10):
                role = "user" if i % 2 == 0 else "assistant"
                nid = dag.add_node(parent, role, f"message {i}")
                parent = nid
            summary = dag.build_summary(max_nodes=5)
            assert "message" in summary
            assert len(summary) < 2000
            dag.close()

    def test_build_summary_empty(self):
        with tempfile.TemporaryDirectory() as d:
            dag = ConversationDAG(os.path.join(d, "test.db"))
            assert dag.build_summary() == ""
            dag.close()

    def test_build_summary_with_tool_nodes(self):
        with tempfile.TemporaryDirectory() as d:
            dag = ConversationDAG(os.path.join(d, "test.db"))
            n1 = dag.add_node("", "user", "read file")
            n2 = dag.add_node(
                n1, "tool", json.dumps({"tool_name": "Read", "result": "ok"})
            )
            n3 = dag.add_node(n2, "assistant", "done")
            summary = dag.build_summary()
            assert "tool(Read)" in summary
            dag.close()

    def test_persistence_across_reopen(self):
        with tempfile.TemporaryDirectory() as d:
            db_path = os.path.join(d, "test.db")
            dag = ConversationDAG(db_path)
            dag.add_node("", "user", "hello")
            dag.add_node(dag.get_head(), "assistant", "hi")
            dag.close()
            # Re-open
            dag2 = ConversationDAG(db_path)
            info = dag2.current_branch_info()
            assert info["msg_count"] == 2
            dag2.close()

    def test_feed_user_prompt(self):
        """Simulate what user_prompt_capture.py would do."""
        with tempfile.TemporaryDirectory() as d:
            dag = ConversationDAG(os.path.join(d, "test.db"))
            nid = dag.add_node(
                parent_id=dag.get_head(),
                role="user",
                content="fix the bug",
                model="",
                provider="",
            )
            assert dag.get_head() == nid
            dag.close()

    def test_feed_assistant_message(self):
        with tempfile.TemporaryDirectory() as d:
            dag = ConversationDAG(os.path.join(d, "test.db"))
            u = dag.add_node("", "user", "hello")
            a = dag.add_node(
                u, "assistant", "hi there", model="opus-4", provider="anthropic"
            )
            assert dag.get_head() == a
            node = dag.get_node(a)
            assert node["model"] == "opus-4"
            dag.close()

    def test_feed_tool_result(self):
        with tempfile.TemporaryDirectory() as d:
            dag = ConversationDAG(os.path.join(d, "test.db"))
            u = dag.add_node("", "user", "read file.py")
            t = dag.add_node(
                u,
                "tool",
                json.dumps(
                    {
                        "tool_name": "Read",
                        "tool_input": {"file_path": "/tmp/file.py"},
                        "tool_response": "content here",
                    }
                ),
            )
            assert dag.get_node(t)["role"] == "tool"
            dag.close()


# --- Task 2: DAG hooks ---


class TestDAGHooks:
    def test_hook_fires(self):
        reg = DAGHookRegistry()
        fired = []
        reg.register(ON_NODE_ADDED, lambda data: fired.append(data))
        reg.fire(ON_NODE_ADDED, {"node_id": "nd_abc", "role": "user"})
        assert len(fired) == 1
        assert fired[0]["node_id"] == "nd_abc"

    def test_hook_priority_ordering(self):
        reg = DAGHookRegistry()
        order = []
        reg.register(ON_NODE_ADDED, lambda d: order.append("b"), priority=200)
        reg.register(ON_NODE_ADDED, lambda d: order.append("a"), priority=100)
        reg.fire(ON_NODE_ADDED, {})
        assert order == ["a", "b"]

    def test_hook_fail_open(self):
        """Handler exceptions should not propagate."""
        reg = DAGHookRegistry()
        reg.register(ON_NODE_ADDED, lambda d: 1 / 0, name="crasher")
        reg.register(ON_NODE_ADDED, lambda d: d.update({"reached": True}), name="after")
        data = {}
        reg.fire(ON_NODE_ADDED, data)  # Should not raise
        assert data.get("reached") is True

    def test_multiple_events(self):
        reg = DAGHookRegistry()
        added = []
        switched = []
        reg.register(ON_NODE_ADDED, lambda d: added.append(d))
        reg.register(ON_BRANCH_SWITCH, lambda d: switched.append(d))
        reg.fire(ON_NODE_ADDED, {"id": "1"})
        reg.fire(ON_BRANCH_SWITCH, {"old": "a", "new": "b"})
        assert len(added) == 1
        assert len(switched) == 1

    def test_list_handlers(self):
        reg = DAGHookRegistry()
        reg.register(ON_NODE_ADDED, lambda d: None, name="h1", priority=50)
        reg.register(ON_NODE_ADDED, lambda d: None, name="h2", priority=100)
        handlers = reg.list_handlers(ON_NODE_ADDED)
        assert handlers == [(50, "h1"), (100, "h2")]


# --- Task 3: DAG hooks wired into DAG core ---


class TestDAGWithHooks:
    def test_add_node_fires_hook(self):
        with tempfile.TemporaryDirectory() as d:
            dag = ConversationDAG(os.path.join(d, "test.db"))
            hooks = DAGHookRegistry()
            fired = []
            hooks.register(ON_NODE_ADDED, lambda data: fired.append(data))
            dag.set_hooks(hooks)
            dag.add_node("", "user", "hello")
            assert len(fired) == 1
            assert fired[0]["role"] == "user"
            dag.close()

    def test_new_branch_fires_hook(self):
        with tempfile.TemporaryDirectory() as d:
            dag = ConversationDAG(os.path.join(d, "test.db"))
            hooks = DAGHookRegistry()
            created = []
            hooks.register(ON_BRANCH_CREATED, lambda data: created.append(data))
            dag.set_hooks(hooks)
            dag.new_branch("test")
            assert len(created) == 1
            assert created[0]["name"] == "test"
            dag.close()

    def test_switch_branch_fires_hook(self):
        with tempfile.TemporaryDirectory() as d:
            dag = ConversationDAG(os.path.join(d, "test.db"))
            hooks = DAGHookRegistry()
            switched = []
            hooks.register(ON_BRANCH_SWITCH, lambda data: switched.append(data))
            dag.set_hooks(hooks)
            old = dag.current_branch_id()
            bid = dag.new_branch("other")
            dag.switch_branch(old)
            assert len(switched) == 1
            assert switched[0]["old_branch"] == bid
            assert switched[0]["new_branch"] == old
            dag.close()

    def test_reset_head_fires_hook(self):
        with tempfile.TemporaryDirectory() as d:
            dag = ConversationDAG(os.path.join(d, "test.db"))
            hooks = DAGHookRegistry()
            resets = []
            hooks.register(ON_BRANCH_RESET, lambda data: resets.append(data))
            dag.set_hooks(hooks)
            dag.add_node("", "user", "hello")
            dag.reset_head()
            assert len(resets) == 1
            dag.close()

    def test_clear_creates_branch(self):
        """Simulate /clear interception."""
        with tempfile.TemporaryDirectory() as d:
            dag = ConversationDAG(os.path.join(d, "test.db"))
            dag.add_node("", "user", "hello")
            dag.add_node(dag.get_head(), "assistant", "hi")
            old_branch = dag.current_branch_id()
            dag.new_branch(f"clear-{int(time.time())}")
            assert dag.current_branch_id() != old_branch
            assert dag.get_head() == ""
            branches = dag.list_branches()
            assert len(branches) == 2
            dag.close()
