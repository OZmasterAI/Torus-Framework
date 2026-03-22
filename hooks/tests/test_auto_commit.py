"""Tests for auto_commit.py config flags and test-hold logic."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from auto_commit import (
    _is_test_file,
    _is_exempt_file,
    _should_hold,
    _load_config,
    _test_candidates,
    _find_test_files,
    _run_tests,
)


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


class TestTestCandidates(unittest.TestCase):
    def test_python_file(self):
        candidates = _test_candidates("/some/path/foo.py")
        assert "test_foo.py" in candidates
        assert "foo_test.py" in candidates

    def test_go_file(self):
        candidates = _test_candidates("/some/path/bar.go")
        assert "test_bar.py" in candidates
        assert "bar_test.go" in candidates

    def test_ts_file(self):
        candidates = _test_candidates("/some/path/baz.ts")
        assert "baz.test.ts" in candidates
        assert "baz.spec.ts" in candidates


class TestFindTestFiles(unittest.TestCase):
    def test_exempt_files_skipped(self):
        tracked = {"/nonexistent/config.json", "/nonexistent/README.md"}
        assert _find_test_files(tracked) == set()

    def test_test_file_included_directly(self):
        # If a test file is in tracked, it should be in the result
        import tempfile

        with tempfile.NamedTemporaryFile(
            prefix="test_", suffix=".py", delete=False
        ) as f:
            f.write(b"pass\n")
            test_path = f.name
        try:
            result = _find_test_files({test_path})
            assert os.path.realpath(test_path) in result
        finally:
            os.unlink(test_path)

    def test_code_file_finds_matching_test(self):
        import tempfile

        tmpdir = tempfile.mkdtemp()
        code_file = os.path.join(tmpdir, "widget.py")
        test_file = os.path.join(tmpdir, "test_widget.py")
        with open(code_file, "w") as f:
            f.write("pass\n")
        with open(test_file, "w") as f:
            f.write("pass\n")
        try:
            result = _find_test_files({code_file})
            assert os.path.realpath(test_file) in result
        finally:
            os.unlink(code_file)
            os.unlink(test_file)
            os.rmdir(tmpdir)


class TestRunTests(unittest.TestCase):
    def test_empty_set_passes(self):
        passed, output = _run_tests(set())
        assert passed
        assert output == ""

    def test_non_python_ignored(self):
        passed, output = _run_tests({"/fake/foo.test.js"})
        assert passed
        assert output == ""

    def test_passing_test(self):
        import tempfile

        with tempfile.NamedTemporaryFile(
            prefix="test_pass_", suffix=".py", delete=False, mode="w"
        ) as f:
            f.write("def test_ok(): assert True\n")
            test_path = f.name
        try:
            passed, _ = _run_tests({test_path})
            assert passed
        finally:
            os.unlink(test_path)

    def test_failing_test(self):
        import tempfile

        with tempfile.NamedTemporaryFile(
            prefix="test_fail_", suffix=".py", delete=False, mode="w"
        ) as f:
            f.write("def test_bad(): assert False\n")
            test_path = f.name
        try:
            passed, output = _run_tests({test_path})
            assert not passed
            assert output  # should contain failure info
        finally:
            os.unlink(test_path)


if __name__ == "__main__":
    unittest.main()
