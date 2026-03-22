"""Tests for gate_23_require_tests."""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from gates.gate_23_require_tests import (
    check,
    _is_test_file,
    _is_code_file,
    _is_state_dir,
    _match_test_to_code,
)


class TestIsTestFile(unittest.TestCase):
    def test_test_prefix(self):
        assert _is_test_file("test_foo.py")

    def test_test_suffix(self):
        assert _is_test_file("foo_test.go")

    def test_spec(self):
        assert _is_test_file("foo.spec.ts")

    def test_not_test(self):
        assert not _is_test_file("foo.py")

    def test_empty(self):
        assert not _is_test_file("")

    def test_none(self):
        assert not _is_test_file(None)


class TestIsCodeFile(unittest.TestCase):
    def test_python(self):
        assert _is_code_file("/home/user/foo.py")

    def test_go(self):
        assert _is_code_file("/home/user/foo.go")

    def test_json_not_code(self):
        assert not _is_code_file("/home/user/config.json")

    def test_test_not_code(self):
        assert not _is_code_file("/home/user/test_foo.py")

    def test_empty(self):
        assert not _is_code_file("")


class TestMatchTestToCode(unittest.TestCase):
    def test_prefix_match(self):
        code = ["/home/user/foo.py"]
        matched = _match_test_to_code("/home/user/test_foo.py", code)
        assert len(matched) == 1

    def test_suffix_match(self):
        code = ["/home/user/foo.py"]
        matched = _match_test_to_code("/home/user/foo_test.py", code)
        assert len(matched) == 1

    def test_go_suffix(self):
        code = ["/home/user/handler.go"]
        matched = _match_test_to_code("/home/user/handler_test.go", code)
        assert len(matched) == 1

    def test_no_match(self):
        code = ["/home/user/foo.py"]
        matched = _match_test_to_code("/home/user/test_bar.py", code)
        assert len(matched) == 0

    def test_ts_spec(self):
        code = ["/home/user/app.ts"]
        matched = _match_test_to_code("/home/user/app.spec.ts", code)
        assert len(matched) == 1


def _mock_check(tool_name, file_path, tracker_contents, require_tests=True):
    """Helper: call check() with mocked config and tracker file."""
    saved = {"data": tracker_contents[:]}
    with (
        patch(
            "gates.gate_23_require_tests._load_config",
            return_value={"require_tests": require_tests},
        ),
        patch(
            "gates.gate_23_require_tests._load_tracker",
            return_value=tracker_contents[:],
        ),
        patch(
            "gates.gate_23_require_tests._save_tracker",
            side_effect=lambda d: saved.update({"data": d}),
        ),
    ):
        result = check(tool_name, {"file_path": file_path}, {})
    return result, saved["data"]


class TestCheckPreToolUse(unittest.TestCase):
    def test_disabled_allows_all(self):
        r, _ = _mock_check(
            "Edit", "/home/user/bar.py", ["/home/user/foo.py"], require_tests=False
        )
        assert not r.blocked

    def test_no_untested_files_allows(self):
        r, saved = _mock_check("Edit", "/home/user/foo.py", [])
        assert not r.blocked
        # Current file should now be tracked
        assert os.path.normpath("/home/user/foo.py") in saved

    def test_untested_code_blocks(self):
        r, _ = _mock_check("Edit", "/home/user/bar.py", ["/home/user/foo.py"])
        assert r.blocked
        assert "foo.py" in r.message

    def test_exempt_file_always_allows(self):
        r, _ = _mock_check("Edit", "/home/user/config.json", ["/home/user/foo.py"])
        assert not r.blocked

    def test_test_file_always_allows(self):
        r, saved = _mock_check("Edit", "/home/user/test_foo.py", ["/home/user/foo.py"])
        assert not r.blocked
        # Test file should have cleared foo.py from tracker
        assert len(saved) == 0

    def test_non_watched_tool_allows(self):
        r, _ = _mock_check("Read", "/home/user/bar.py", ["/home/user/foo.py"])
        assert not r.blocked

    def test_multiple_untested_shows_names(self):
        r, _ = _mock_check(
            "Edit", "/home/user/baz.py", ["/home/user/foo.py", "/home/user/bar.py"]
        )
        assert r.blocked
        assert "foo.py" in r.message
        assert "bar.py" in r.message

    def test_first_edit_passes_and_tracks(self):
        """First code edit in session should pass and track the file."""
        r, saved = _mock_check("Edit", "/home/user/brand_new.py", [])
        assert not r.blocked
        assert os.path.normpath("/home/user/brand_new.py") in saved

    def test_test_clears_only_matching(self):
        """Writing test_foo.py should clear foo.py but not bar.py."""
        r, saved = _mock_check(
            "Edit", "/home/user/test_foo.py", ["/home/user/foo.py", "/home/user/bar.py"]
        )
        assert not r.blocked
        assert len(saved) == 1
        assert "bar.py" in saved[0]

    def test_post_tool_use_ignored(self):
        """PostToolUse event should be ignored (always allow)."""
        with patch(
            "gates.gate_23_require_tests._load_config",
            return_value={"require_tests": True},
        ):
            r = check(
                "Edit", {"file_path": "/home/user/foo.py"}, {}, event_type="PostToolUse"
            )
        assert not r.blocked


if __name__ == "__main__":
    unittest.main()
