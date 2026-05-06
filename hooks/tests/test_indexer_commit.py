"""Tests for the indexer_commit PostToolUse hook."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, patch


class TestIgnoresNonBashTools:
    """Hook should exit early (return False) for non-Bash tools."""

    def test_edit_tool_ignored(self):
        from indexer_commit import _handle_event

        event = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/some/file.py",
                "old_string": "a",
                "new_string": "b",
            },
        }
        result = _handle_event(event)
        assert result is False

    def test_write_tool_ignored(self):
        from indexer_commit import _handle_event

        event = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/some/file.py", "content": "hello"},
        }
        result = _handle_event(event)
        assert result is False

    def test_read_tool_ignored(self):
        from indexer_commit import _handle_event

        event = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/some/file.py"},
        }
        result = _handle_event(event)
        assert result is False

    def test_empty_tool_name_ignored(self):
        from indexer_commit import _handle_event

        event = {"tool_name": "", "tool_input": {}}
        result = _handle_event(event)
        assert result is False


class TestIgnoresNonCommitBash:
    """Hook should exit early for Bash commands that are not git commit."""

    def test_git_status_ignored(self):
        from indexer_commit import _handle_event

        event = {
            "tool_name": "Bash",
            "tool_input": {"command": "git status"},
        }
        result = _handle_event(event)
        assert result is False

    def test_ls_ignored(self):
        from indexer_commit import _handle_event

        event = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls -la"},
        }
        result = _handle_event(event)
        assert result is False

    def test_git_diff_ignored(self):
        from indexer_commit import _handle_event

        event = {
            "tool_name": "Bash",
            "tool_input": {"command": "git diff HEAD~1"},
        }
        result = _handle_event(event)
        assert result is False

    def test_git_log_ignored(self):
        from indexer_commit import _handle_event

        event = {
            "tool_name": "Bash",
            "tool_input": {"command": "git log --oneline -5"},
        }
        result = _handle_event(event)
        assert result is False

    def test_empty_command_ignored(self):
        from indexer_commit import _handle_event

        event = {
            "tool_name": "Bash",
            "tool_input": {"command": ""},
        }
        result = _handle_event(event)
        assert result is False

    def test_missing_command_ignored(self):
        from indexer_commit import _handle_event

        event = {
            "tool_name": "Bash",
            "tool_input": {},
        }
        result = _handle_event(event)
        assert result is False


class TestDetectsGitCommit:
    """Hook should trigger incremental build on git commit commands."""

    @patch("indexer_commit.get_changed_files")
    @patch("indexer_commit.init_code_tables")
    @patch("indexer_commit.connect_code_graph")
    @patch("indexer_commit.incremental_build")
    def test_simple_git_commit(self, mock_incr, mock_connect, mock_init, mock_changed):
        from indexer_commit import _handle_event

        mock_db = MagicMock()
        mock_connect.return_value = mock_db
        mock_changed.return_value = ["hooks/shared/foo.py"]

        event = {
            "tool_name": "Bash",
            "tool_input": {"command": 'git commit -m "fix: something"'},
        }
        result = _handle_event(event)
        assert result is True
        mock_connect.assert_called_once()
        mock_init.assert_called_once_with(mock_db)
        mock_changed.assert_called_once()
        mock_incr.assert_called_once()

    @patch("indexer_commit.get_changed_files")
    @patch("indexer_commit.init_code_tables")
    @patch("indexer_commit.connect_code_graph")
    @patch("indexer_commit.incremental_build")
    def test_git_commit_with_heredoc(
        self, mock_incr, mock_connect, mock_init, mock_changed
    ):
        from indexer_commit import _handle_event

        mock_db = MagicMock()
        mock_connect.return_value = mock_db
        mock_changed.return_value = ["main.py"]

        event = {
            "tool_name": "Bash",
            "tool_input": {
                "command": "git commit -m \"$(cat <<'EOF'\nfeat: new feature\nEOF\n)\""
            },
        }
        result = _handle_event(event)
        assert result is True
        mock_incr.assert_called_once()

    @patch("indexer_commit.get_changed_files")
    @patch("indexer_commit.init_code_tables")
    @patch("indexer_commit.connect_code_graph")
    @patch("indexer_commit.incremental_build")
    def test_chained_git_add_and_commit(
        self, mock_incr, mock_connect, mock_init, mock_changed
    ):
        from indexer_commit import _handle_event

        mock_db = MagicMock()
        mock_connect.return_value = mock_db
        mock_changed.return_value = ["utils.py"]

        event = {
            "tool_name": "Bash",
            "tool_input": {"command": "git add file.py && git commit -m 'update'"},
        }
        result = _handle_event(event)
        assert result is True

    @patch("indexer_commit.get_changed_files")
    @patch("indexer_commit.init_code_tables")
    @patch("indexer_commit.connect_code_graph")
    @patch("indexer_commit.incremental_build")
    def test_no_changed_files_skips_build(
        self, mock_incr, mock_connect, mock_init, mock_changed
    ):
        from indexer_commit import _handle_event

        mock_db = MagicMock()
        mock_connect.return_value = mock_db
        mock_changed.return_value = []

        event = {
            "tool_name": "Bash",
            "tool_input": {"command": 'git commit -m "empty"'},
        }
        result = _handle_event(event)
        # Should still return True (detected commit) but not call incremental_build
        assert result is True
        mock_incr.assert_not_called()

    @patch("indexer_commit.get_changed_files")
    @patch("indexer_commit.init_code_tables")
    @patch("indexer_commit.connect_code_graph")
    @patch("indexer_commit.incremental_build")
    def test_passes_project_info(
        self, mock_incr, mock_connect, mock_init, mock_changed
    ):
        from indexer_commit import _handle_event

        mock_db = MagicMock()
        mock_connect.return_value = mock_db
        mock_changed.return_value = ["src/app.py"]

        event = {
            "tool_name": "Bash",
            "tool_input": {"command": 'git commit -m "test"'},
        }
        _handle_event(event)

        # Verify incremental_build was called with db, project_root, project_name, changed_files
        args = mock_incr.call_args[0]
        assert args[0] is mock_db
        assert isinstance(args[1], str)  # project_root
        assert isinstance(args[2], str)  # project_name
        assert args[3] == ["src/app.py"]


class TestExits0OnError:
    """Hook must never crash -- always fail open."""

    def test_malformed_event_returns_false(self):
        from indexer_commit import _handle_event

        result = _handle_event({})
        assert result is False

    def test_none_event_returns_false(self):
        from indexer_commit import _handle_event

        result = _handle_event(None)
        assert result is False

    def test_string_event_returns_false(self):
        from indexer_commit import _handle_event

        result = _handle_event("not a dict")
        assert result is False

    @patch("indexer_commit.connect_code_graph", side_effect=Exception("DB down"))
    def test_db_connection_failure_returns_false(self, mock_connect):
        from indexer_commit import _handle_event

        event = {
            "tool_name": "Bash",
            "tool_input": {"command": 'git commit -m "test"'},
        }
        result = _handle_event(event)
        assert result is False

    @patch("indexer_commit.get_changed_files", side_effect=RuntimeError("git failed"))
    @patch("indexer_commit.init_code_tables")
    @patch("indexer_commit.connect_code_graph")
    def test_get_changed_files_failure_returns_false(
        self, mock_connect, mock_init, mock_changed
    ):
        from indexer_commit import _handle_event

        mock_connect.return_value = MagicMock()
        event = {
            "tool_name": "Bash",
            "tool_input": {"command": 'git commit -m "test"'},
        }
        result = _handle_event(event)
        assert result is False

    @patch("indexer_commit.incremental_build", side_effect=Exception("build failed"))
    @patch("indexer_commit.get_changed_files", return_value=["foo.py"])
    @patch("indexer_commit.init_code_tables")
    @patch("indexer_commit.connect_code_graph")
    def test_incremental_build_failure_returns_false(
        self, mock_connect, mock_init, mock_changed, mock_incr
    ):
        from indexer_commit import _handle_event

        mock_connect.return_value = MagicMock()
        event = {
            "tool_name": "Bash",
            "tool_input": {"command": 'git commit -m "test"'},
        }
        result = _handle_event(event)
        assert result is False
