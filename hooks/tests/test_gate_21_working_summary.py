"""Tests for Gate 21: Working Summary enforcement."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gates.gate_21_working_summary import check, GATE_NAME


class TestGate21ThresholdInactive:
    """When threshold hasn't fired, gate allows everything."""

    def test_allows_edit(self):
        state = {"summary_threshold_fired": False}
        result = check("Edit", {"file_path": "/tmp/test.py"}, state)
        assert not result.blocked

    def test_allows_bash(self):
        state = {"summary_threshold_fired": False}
        result = check("Bash", {"command": "ls"}, state)
        assert not result.blocked

    def test_allows_write(self):
        state = {"summary_threshold_fired": False}
        result = check("Write", {"file_path": "/tmp/test.py"}, state)
        assert not result.blocked

    def test_allows_when_key_missing(self):
        state = {}
        result = check("Edit", {"file_path": "/tmp/test.py"}, state)
        assert not result.blocked


class TestGate21ThresholdActive:
    """When threshold has fired, gate blocks gated tools until summary written."""

    def test_blocks_edit(self):
        state = {"summary_threshold_fired": True}
        result = check(
            "Edit", {"file_path": "/tmp/test.py"}, state, _summary_size_override=100
        )
        assert result.blocked
        assert "WORKING SUMMARY" in result.message

    def test_blocks_write(self):
        state = {"summary_threshold_fired": True}
        result = check(
            "Write", {"file_path": "/tmp/test.py"}, state, _summary_size_override=100
        )
        assert result.blocked

    def test_blocks_bash(self):
        state = {"summary_threshold_fired": True}
        result = check("Bash", {"command": "ls"}, state, _summary_size_override=0)
        assert result.blocked

    def test_blocks_notebook_edit(self):
        state = {"summary_threshold_fired": True}
        result = check("NotebookEdit", {}, state, _summary_size_override=0)
        assert result.blocked

    def test_blocks_task(self):
        state = {"summary_threshold_fired": True}
        result = check("Task", {}, state, _summary_size_override=0)
        assert result.blocked

    def test_allows_after_summary_written(self):
        state = {"summary_threshold_fired": True}
        result = check(
            "Edit", {"file_path": "/tmp/test.py"}, state, _summary_size_override=3000
        )
        assert not result.blocked

    def test_allows_at_exact_threshold(self):
        state = {"summary_threshold_fired": True}
        result = check(
            "Edit", {"file_path": "/tmp/test.py"}, state, _summary_size_override=2000
        )
        assert not result.blocked


class TestGate21AlwaysAllowed:
    """Read-only, memory, and skill tools are never blocked."""

    @pytest.mark.parametrize("tool", ["Read", "Grep", "Glob", "WebSearch", "WebFetch"])
    def test_allows_read_tools(self, tool):
        state = {"summary_threshold_fired": True}
        result = check(tool, {}, state)
        assert not result.blocked

    def test_allows_memory_tools(self):
        state = {"summary_threshold_fired": True}
        for tool in [
            "mcp__memory__search_knowledge",
            "mcp__memory__remember_this",
            "mcp__memory__get_memory",
            "mcp_memory_search",
        ]:
            result = check(tool, {}, state)
            assert not result.blocked

    def test_allows_skill_invocation(self):
        state = {"summary_threshold_fired": True}
        result = check("Skill", {"skill": "working-summary"}, state)
        assert not result.blocked

    def test_allows_unknown_tool(self):
        state = {"summary_threshold_fired": True}
        result = check("SomeNewTool", {}, state)
        assert not result.blocked


class TestGate21Exemptions:
    """File-based exemptions."""

    def test_exempts_working_summary_file(self):
        state = {"summary_threshold_fired": True}
        summary_path = os.path.expanduser("~/.claude/hooks/working-summary.md")
        result = check(
            "Write", {"file_path": summary_path}, state, _summary_size_override=0
        )
        assert not result.blocked

    def test_exempts_skills_dir(self):
        state = {"summary_threshold_fired": True}
        skill_path = os.path.expanduser("~/.claude/skill-library/test/SKILL.md")
        result = check(
            "Write", {"file_path": skill_path}, state, _summary_size_override=0
        )
        assert not result.blocked

    def test_exempts_state_json(self):
        state = {"summary_threshold_fired": True}
        result = check(
            "Write", {"file_path": "/tmp/state.json"}, state, _summary_size_override=0
        )
        assert not result.blocked


class TestGate21EventType:
    """Only PreToolUse event type triggers the gate."""

    def test_allows_post_tool_use(self):
        state = {"summary_threshold_fired": True}
        result = check(
            "Edit", {"file_path": "/tmp/test.py"}, state, event_type="PostToolUse"
        )
        assert not result.blocked

    def test_allows_notification(self):
        state = {"summary_threshold_fired": True}
        result = check("Edit", {}, state, event_type="Notification")
        assert not result.blocked
