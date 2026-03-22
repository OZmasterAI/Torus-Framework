"""Tests for gate_23_require_tests."""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from gates.gate_23_require_tests import (
    check,
    _code_files_without_tests,
    _is_test_file,
    _is_state_dir,
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


class TestCodeFilesWithoutTests(unittest.TestCase):
    def test_code_only(self):
        unmatched = _code_files_without_tests(["/home/user/foo.py"])
        assert len(unmatched) == 1

    def test_code_with_matching_test(self):
        unmatched = _code_files_without_tests(
            [
                "/home/user/foo.py",
                "/home/user/test_foo.py",
            ]
        )
        assert len(unmatched) == 0

    def test_code_with_suffix_test(self):
        unmatched = _code_files_without_tests(
            [
                "/home/user/foo.py",
                "/home/user/foo_test.py",
            ]
        )
        assert len(unmatched) == 0

    def test_multiple_code_partial_tests(self):
        unmatched = _code_files_without_tests(
            [
                "/home/user/foo.py",
                "/home/user/bar.py",
                "/home/user/test_foo.py",
            ]
        )
        assert len(unmatched) == 1
        assert "bar.py" in os.path.basename(unmatched[0])

    def test_exempt_files_excluded(self):
        unmatched = _code_files_without_tests(
            [
                "/home/user/config.json",
                "/home/user/README.md",
            ]
        )
        assert len(unmatched) == 0

    def test_empty_pending(self):
        assert _code_files_without_tests([]) == []

    def test_go_test_suffix(self):
        unmatched = _code_files_without_tests(
            [
                "/home/user/handler.go",
                "/home/user/handler_test.go",
            ]
        )
        assert len(unmatched) == 0

    def test_ts_spec(self):
        unmatched = _code_files_without_tests(
            [
                "/home/user/app.ts",
                "/home/user/app.spec.ts",
            ]
        )
        assert len(unmatched) == 0


class TestCheckGate(unittest.TestCase):
    def _check(self, tool_name, file_path, state, require_tests=False):
        with patch(
            "gates.gate_23_require_tests._load_config",
            return_value={"require_tests": require_tests},
        ):
            return check(tool_name, {"file_path": file_path}, state)

    def test_disabled_allows_all(self):
        r = self._check(
            "Edit",
            "/home/user/foo.py",
            {"pending_verification": ["/home/user/bar.py"]},
            require_tests=False,
        )
        assert not r.blocked

    def test_no_prior_edits_allows(self):
        r = self._check(
            "Edit",
            "/home/user/foo.py",
            {"pending_verification": []},
            require_tests=True,
        )
        assert not r.blocked

    def test_prior_code_no_tests_blocks(self):
        r = self._check(
            "Edit",
            "/home/user/baz.py",
            {"pending_verification": ["/home/user/foo.py"]},
            require_tests=True,
        )
        assert r.blocked
        assert "foo.py" in r.message

    def test_prior_code_with_tests_allows(self):
        r = self._check(
            "Edit",
            "/home/user/baz.py",
            {
                "pending_verification": [
                    "/home/user/foo.py",
                    "/home/user/test_foo.py",
                ]
            },
            require_tests=True,
        )
        assert not r.blocked

    def test_exempt_file_always_allows(self):
        r = self._check(
            "Edit",
            "/home/user/config.json",
            {"pending_verification": ["/home/user/foo.py"]},
            require_tests=True,
        )
        assert not r.blocked

    def test_test_file_always_allows(self):
        r = self._check(
            "Edit",
            "/home/user/test_foo.py",
            {"pending_verification": ["/home/user/foo.py"]},
            require_tests=True,
        )
        assert not r.blocked

    def test_non_watched_tool_allows(self):
        r = self._check(
            "Read",
            "/home/user/foo.py",
            {"pending_verification": ["/home/user/bar.py"]},
            require_tests=True,
        )
        assert not r.blocked

    def test_post_tool_use_allows(self):
        with patch(
            "gates.gate_23_require_tests._load_config",
            return_value={"require_tests": True},
        ):
            r = check(
                "Edit",
                {"file_path": "/home/user/foo.py"},
                {"pending_verification": ["/home/user/bar.py"]},
                event_type="PostToolUse",
            )
        assert not r.blocked


if __name__ == "__main__":
    unittest.main()
