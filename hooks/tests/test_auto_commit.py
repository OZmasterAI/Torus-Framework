"""Tests for auto_commit.py config flags and test-hold logic."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from auto_commit import _is_test_file, _is_exempt_file, _should_hold, _load_config


class TestIsTestFile(unittest.TestCase):
    def test_test_prefix(self):
        assert _is_test_file("test_foo.py")

    def test_test_suffix_py(self):
        assert _is_test_file("foo_test.py")

    def test_test_suffix_go(self):
        assert _is_test_file("foo_test.go")

    def test_spec_suffix(self):
        assert _is_test_file("foo.spec.ts")

    def test_dot_test(self):
        assert _is_test_file("foo.test.js")

    def test_not_test(self):
        assert not _is_test_file("foo.py")

    def test_not_test_go(self):
        assert not _is_test_file("foo.go")


class TestIsExemptFile(unittest.TestCase):
    def test_json(self):
        assert _is_exempt_file("config.json")

    def test_md(self):
        assert _is_exempt_file("README.md")

    def test_yaml(self):
        assert _is_exempt_file("config.yaml")

    def test_sh(self):
        assert _is_exempt_file("run.sh")

    def test_py_not_exempt(self):
        assert not _is_exempt_file("foo.py")

    def test_go_not_exempt(self):
        assert not _is_exempt_file("foo.go")

    def test_ts_not_exempt(self):
        assert not _is_exempt_file("index.ts")


class TestShouldHold(unittest.TestCase):
    def test_code_only_holds(self):
        tracked = {"/home/user/.claude/hooks/shared/foo.py"}
        assert _should_hold(tracked, require_tests=True)

    def test_code_plus_test_does_not_hold(self):
        tracked = {
            "/home/user/.claude/hooks/shared/foo.py",
            "/home/user/.claude/hooks/tests/test_foo.py",
        }
        assert not _should_hold(tracked, require_tests=True)

    def test_exempt_only_does_not_hold(self):
        tracked = {"/home/user/.claude/LIVE_STATE.json"}
        assert not _should_hold(tracked, require_tests=True)

    def test_disabled_does_not_hold(self):
        tracked = {"/home/user/.claude/hooks/shared/foo.py"}
        assert not _should_hold(tracked, require_tests=False)

    def test_mixed_code_and_exempt_holds_if_no_tests(self):
        tracked = {
            "/home/user/.claude/hooks/shared/foo.py",
            "/home/user/.claude/LIVE_STATE.json",
        }
        assert _should_hold(tracked, require_tests=True)

    def test_mixed_code_exempt_and_test_does_not_hold(self):
        tracked = {
            "/home/user/.claude/hooks/shared/foo.py",
            "/home/user/.claude/LIVE_STATE.json",
            "/home/user/.claude/hooks/tests/test_foo.py",
        }
        assert not _should_hold(tracked, require_tests=True)

    def test_empty_tracked_does_not_hold(self):
        assert not _should_hold(set(), require_tests=True)

    def test_test_only_does_not_hold(self):
        tracked = {"/home/user/.claude/hooks/tests/test_foo.py"}
        assert not _should_hold(tracked, require_tests=True)


class TestLoadConfig(unittest.TestCase):
    def test_returns_dict_on_missing_file(self):
        import auto_commit

        original = auto_commit.CONFIG_FILE
        try:
            auto_commit.CONFIG_FILE = "/nonexistent/config.json"
            result = _load_config()
            assert isinstance(result, dict)
            assert result == {}
        finally:
            auto_commit.CONFIG_FILE = original


if __name__ == "__main__":
    unittest.main()
