#!/usr/bin/env python3
"""Auto-commit hook for ~/.claude/ file changes.

Two-phase design:
  Phase 1 (PostToolUse, Edit|Write): Stage changed files via git add
  Phase 2 (UserPromptSubmit): Commit all staged changes in one batch

Usage:
  echo '{"tool_input":{"file_path":"/home/user/.claude/hooks/foo.py"}}' | python3 auto_commit.py stage
  python3 auto_commit.py commit

FAIL-OPEN: Always exits 0. Auto-commit failures must never block work.
"""

import json
import os
import subprocess
import sys

CLAUDE_DIR = os.path.expanduser("~/.claude")
STAGED_TRACKER = os.path.join(CLAUDE_DIR, "hooks", ".auto_commit_staged.txt")
MAX_FILES_IN_MSG = 3


def _get_co_author():
    """Read current model from statusline snapshot, fall back to generic."""
    try:
        snap_path = os.path.join(CLAUDE_DIR, "hooks", ".statusline_snapshot.json")
        with open(snap_path) as f:
            model = json.load(f).get("model", "")
        if model:
            # e.g. "claude-opus-4-6" → "Claude Opus 4.6"
            name = model.replace("claude-", "").replace("-", " ").title()
            return f"Co-Authored-By: Claude {name} <noreply@anthropic.com>"
    except Exception:
        pass
    return "Co-Authored-By: Claude <noreply@anthropic.com>"


def git(*args, timeout=5):
    """Run a git command in the ~/.claude directory."""
    return subprocess.run(
        ["git", "-C", CLAUDE_DIR] + list(args),
        capture_output=True, text=True, timeout=timeout,
    )


def stage():
    """Stage a file if it's inside ~/.claude/."""
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

    # Resolve to absolute and check it's inside ~/.claude/
    resolved = os.path.realpath(file_path)
    claude_real = os.path.realpath(CLAUDE_DIR)
    if not resolved.startswith(claude_real + os.sep) and resolved != claude_real:
        return

    git("add", resolved)

    # Track this file so commit() only commits our staged files
    try:
        with open(STAGED_TRACKER, "a") as f:
            f.write(resolved + "\n")
    except OSError:
        pass


def commit():
    """Commit only files that stage() explicitly tracked.

    This prevents committing unrelated index changes from manual git
    operations (git rm --cached, git add, etc.) which can create
    revert commits that undo prior work.
    """
    # Read tracker — only commit files we explicitly staged
    try:
        with open(STAGED_TRACKER) as f:
            tracked = {line.strip() for line in f if line.strip()}
    except (FileNotFoundError, OSError):
        tracked = set()

    if not tracked:
        return

    # Clear tracker immediately (atomic: truncate before commit)
    try:
        open(STAGED_TRACKER, "w").close()
    except OSError:
        pass

    # Unstage everything, then re-stage ONLY tracked files
    # This prevents stale index entries from manual git operations
    git("reset", "HEAD", "--quiet")

    for fpath in tracked:
        git("add", fpath)

    result = git("diff", "--cached", "--name-only")
    if result.returncode != 0 or not result.stdout.strip():
        return

    files = [f.strip() for f in result.stdout.strip().splitlines() if f.strip()]
    if not files:
        return

    # Build message from basenames
    basenames = [os.path.basename(f) for f in files]
    if len(basenames) <= MAX_FILES_IN_MSG:
        file_list = ", ".join(basenames)
    else:
        shown = ", ".join(basenames[:MAX_FILES_IN_MSG])
        file_list = f"{shown} +{len(basenames) - MAX_FILES_IN_MSG} more"

    message = f"auto: update {file_list}\n\n{_get_co_author()}"
    git("commit", "-m", message)


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
