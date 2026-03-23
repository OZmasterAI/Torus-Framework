#!/usr/bin/env python3
"""Auto-commit hook for file changes in any git repo.

Two-phase design:
  Phase 1 (PostToolUse, Edit|Write): Stage changed files via git add
  Phase 2 (UserPromptSubmit): Commit all staged changes per repo

Usage:
  echo '{"tool_input":{"file_path":"/home/user/project/foo.py"}}' | python3 auto_commit.py stage
  python3 auto_commit.py commit

FAIL-OPEN: Always exits 0. Auto-commit failures must never block work.
"""

import json
import os
import subprocess
import sys

CLAUDE_DIR = os.path.expanduser("~/.claude")
STAGED_TRACKER = os.path.join(CLAUDE_DIR, "hooks", ".auto_commit_staged.txt")
CONFIG_FILE = os.path.join(CLAUDE_DIR, "config.json")
MAX_FILES_IN_MSG = 3

# Patterns matching test files (mirrors shared/exemptions.py)
_TEST_PATTERNS = ("test_", "_test.", ".test.", "spec_", "_spec.", ".spec.")
_EXEMPT_EXTENSIONS = {
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".cfg",
    ".ini",
    ".txt",
    ".xml",
    ".csv",
    ".lock",
}

# Orchestrator marker — when present, auto-commit is disabled
_ORCH_MARKER = os.path.join(CLAUDE_DIR, "hooks", ".orchestrator_active")


def _load_config():
    """Read config.json. Returns dict with defaults on failure."""
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _is_orchestrator_active():
    """Check if torus-loop orchestrator is running."""
    return os.path.exists(_ORCH_MARKER)


def _is_test_file(path):
    """Check if path is a test file."""
    lower = os.path.basename(path).lower()
    return any(pat in lower for pat in _TEST_PATTERNS)


def _is_exempt_file(path):
    """Check if path is a non-code file (config, docs, etc)."""
    _, ext = os.path.splitext(path)
    return ext.lower() in _EXEMPT_EXTENSIONS


def _should_hold(tracked, require_tests):
    """Return True if commit should be held (code files without tests)."""
    if not require_tests:
        return False
    has_code = False
    has_tests = False
    for f in tracked:
        if _is_exempt_file(f) or _is_test_file(f):
            if _is_test_file(f):
                has_tests = True
            continue
        has_code = True
    return has_code and not has_tests


def _test_candidates(code_path):
    """Return list of possible test file names for a code file."""
    base = os.path.basename(code_path)
    name, _ = os.path.splitext(base)
    return [
        f"test_{base}",
        f"test_{name}.py",
        f"{name}_test.py",
        f"{name}_test.go",
        f"{name}.test.ts",
        f"{name}.test.js",
        f"{name}.spec.ts",
        f"{name}.spec.js",
    ]


def _test_search_dirs(code_path):
    """Return directories to search for test files."""
    code_dir = os.path.dirname(code_path)
    parent = os.path.dirname(code_dir)
    dirs = [code_dir]
    for td in ("tests", "test", "__tests__"):
        dirs.append(os.path.join(code_dir, td))
        dirs.append(os.path.join(parent, td))
    return dirs


def _find_test_files(tracked):
    """Find matching test files on disk for tracked code files."""
    test_files = set()
    for fpath in tracked:
        if _is_exempt_file(fpath) or _is_test_file(fpath):
            if _is_test_file(fpath):
                test_files.add(os.path.realpath(fpath))
            continue
        for search_dir in _test_search_dirs(fpath):
            for candidate in _test_candidates(fpath):
                full = os.path.join(search_dir, candidate)
                if os.path.exists(full):
                    test_files.add(os.path.realpath(full))
    return test_files


def _run_tests(test_files, cwd=None):
    """Run test files. Returns (passed: bool, output: str). 30s timeout."""
    if not test_files:
        return True, ""
    test_cwd = cwd or CLAUDE_DIR
    py_tests = [f for f in test_files if f.endswith(".py")]
    if not py_tests:
        return True, ""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-x", "-q", "--tb=short", "--no-header"]
            + list(py_tests),
            capture_output=True,
            text=True,
            timeout=30,
            cwd=test_cwd,
        )
        return result.returncode == 0, result.stdout + result.stderr
    except FileNotFoundError:
        for tf in py_tests:
            try:
                r = subprocess.run(
                    [sys.executable, tf],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=test_cwd,
                )
                if r.returncode != 0:
                    return False, r.stdout + r.stderr
            except (subprocess.TimeoutExpired, OSError) as exc:
                return False, str(exc)
        return True, ""
    except subprocess.TimeoutExpired:
        return False, "Tests timed out (30s limit)"


def _get_co_author(session_id=None):
    """Read current model from session-namespaced statusline snapshot."""
    try:
        snap_path = os.path.join(CLAUDE_DIR, "hooks", ".statusline_snapshot.json")
        if session_id:
            try:
                from shared.state import session_namespaced_path

                snap_path = session_namespaced_path(snap_path, session_id)
            except ImportError:
                pass
        with open(snap_path) as f:
            model = json.load(f).get("model", "")
        if model:
            name = model.replace("claude-", "").replace("-", " ").title()
            return f"Co-Authored-By: Claude {name} <noreply@anthropic.com>"
    except Exception:
        pass
    return "Co-Authored-By: Claude <noreply@anthropic.com>"


def _find_git_root(file_path):
    """Find the git repo root for a file. Returns None if not in a repo."""
    try:
        result = subprocess.run(
            ["git", "-C", os.path.dirname(file_path), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def git(*args, repo_dir=None, timeout=5):
    """Run a git command in the given repo (defaults to ~/.claude)."""
    target = repo_dir or CLAUDE_DIR
    return subprocess.run(
        ["git", "-C", target] + list(args),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def stage():
    """Stage a file if it's inside a git repo."""
    cfg = _load_config()
    if not cfg.get("auto_commit", True):
        return
    if _is_orchestrator_active():
        return

    try:
        payload = json.load(sys.stdin)
    except Exception:
        return

    tool_input = payload.get("tool_input", {})
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except Exception:
            return

    file_path = tool_input.get("file_path", "")
    if not file_path:
        return

    resolved = os.path.realpath(file_path)
    repo_root = _find_git_root(resolved)
    if not repo_root:
        return

    git("add", resolved, repo_dir=repo_root)

    # Track file with its repo root so commit() knows where to commit
    try:
        with open(STAGED_TRACKER, "a") as f:
            f.write(f"{repo_root}\t{resolved}\n")
    except OSError:
        pass


def commit():
    """Commit only files that stage() explicitly tracked, per repo."""
    cfg = _load_config()
    if not cfg.get("auto_commit", True):
        return
    if _is_orchestrator_active():
        return

    # Read session_id from stdin for namespaced snapshot
    _session_id = None
    try:
        payload = json.load(sys.stdin)
        _session_id = payload.get("session_id")
    except Exception:
        pass

    # Read tracker — group files by repo root
    # Format: "repo_root\tfile_path" (new) or bare "file_path" (legacy)
    repos = {}  # repo_root -> set of file paths
    try:
        with open(STAGED_TRACKER) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if "\t" in line:
                    repo_root, fpath = line.split("\t", 1)
                else:
                    # Legacy format: bare path, assume ~/.claude
                    fpath = line
                    repo_root = CLAUDE_DIR
                repos.setdefault(repo_root, set()).add(fpath)
    except (FileNotFoundError, OSError):
        repos = {}

    if not repos:
        return

    # Check test requirement per repo
    all_tracked = set()
    for files in repos.values():
        all_tracked.update(files)

    if cfg.get("auto_commit_require_tests", False):
        if _should_hold(all_tracked, require_tests=True):
            code_names = ", ".join(
                os.path.basename(f)
                for f in all_tracked
                if not _is_exempt_file(f) and not _is_test_file(f)
            )
            print(f"⏸ Holding commit: tests missing for {code_names}", file=sys.stderr)
            return
        # Tests exist — now run them
        test_files = _find_test_files(all_tracked)
        if test_files:
            passed, output = _run_tests(test_files)
            if not passed:
                summary = (
                    output.strip().splitlines()[-1] if output.strip() else "unknown"
                )
                print(f"⏸ Holding commit: tests failed — {summary}", file=sys.stderr)
                return

    # Clear tracker (after test check so held files persist)
    try:
        open(STAGED_TRACKER, "w").close()
    except OSError:
        pass

    # Commit per repo
    for repo_root, tracked in repos.items():
        # Unstage everything, then re-stage ONLY tracked files
        git("reset", "HEAD", "--quiet", repo_dir=repo_root)

        for fpath in tracked:
            git("add", fpath, repo_dir=repo_root)

        result = git("diff", "--cached", "--name-only", repo_dir=repo_root)
        if result.returncode != 0 or not result.stdout.strip():
            continue

        files = [f.strip() for f in result.stdout.strip().splitlines() if f.strip()]
        if not files:
            continue

        basenames = [os.path.basename(f) for f in files]
        if len(basenames) <= MAX_FILES_IN_MSG:
            file_list = ", ".join(basenames)
        else:
            shown = ", ".join(basenames[:MAX_FILES_IN_MSG])
            file_list = f"{shown} +{len(basenames) - MAX_FILES_IN_MSG} more"

        message = f"auto: update {file_list}\n\n{_get_co_author(_session_id)}"
        git("commit", "-m", message, repo_dir=repo_root)


def main():
    if len(sys.argv) < 2:
        return

    mode = sys.argv[1]
    if mode == "stage":
        stage()
    elif mode == "commit":
        commit()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
