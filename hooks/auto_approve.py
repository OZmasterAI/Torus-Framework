#!/usr/bin/env python3
"""Auto-approve hook for Claude Code PermissionRequest events.

Security model (deny-before-allow):
    1. DENY patterns are checked FIRST. Any match immediately denies the request
       with a descriptive message. This prevents dangerous commands from ever
       being auto-approved, even if they also match a safe-command pattern.
    2. Safe tool names (Read, Glob, Grep, WebFetch, WebSearch) are auto-approved
       unconditionally — they are read-only by design.
    3. For Bash tools, the command is extracted and checked against an allowlist
       of safe, read-only commands (git status, ls, pytest, etc.).
    4. Anything that doesn't match a deny or allow pattern produces NO output,
       which causes Claude Code to fall through to the normal user prompt.
    5. The entire main block is wrapped in try/except so any crash also produces
       no output (fail-open to user prompt, never fail-open to execution).

Usage (called by Claude Code as a PermissionRequest hook):
    echo '{"tool_name":"Bash","tool_input":{"command":"git status"}}' | python auto_approve.py
"""

import json
import re
import sys

# ---------------------------------------------------------------------------
# Deny patterns — checked FIRST, before any allow logic.
# Each tuple: (compiled regex, human-readable reason for the deny message)
# ---------------------------------------------------------------------------
DENY_PATTERNS = [
    (re.compile(r"\brm\s+-rf\b"),           "rm -rf is blocked"),
    (re.compile(r"\brm\s+-r\s+/"),          "recursive delete at root is blocked"),
    (re.compile(r"\beval\b"),               "eval is blocked"),
    (re.compile(r"\bsudo\b"),               "sudo is blocked"),
    (re.compile(r"\|\s*bash\b"),            "piping to bash is blocked"),
    (re.compile(r"\|\s*sh\b"),              "piping to sh is blocked"),
    (re.compile(r"git\s+push\s+--force"),   "force push is blocked"),
    (re.compile(r"git\s+push\s+-f\b"),      "force push is blocked"),
    (re.compile(r"curl.*\|.*bash"),         "curl-pipe-bash is blocked"),
    (re.compile(r"curl.*\|.*sh\b"),         "curl-pipe-sh is blocked"),
    (re.compile(r"\bchmod\s+777\b"),        "chmod 777 is blocked"),
    (re.compile(r"\bdd\s+if="),             "dd is blocked"),
    (re.compile(r"\bmkfs\b"),               "mkfs is blocked"),
    (re.compile(r">\s*/dev/sd"),            "writing to block device is blocked"),
    (re.compile(r":\(\)\{.*:\|:&\s*\};:"),  "fork bomb is blocked"),
]

# ---------------------------------------------------------------------------
# Tool names that are inherently read-only — auto-approve unconditionally.
# ---------------------------------------------------------------------------
SAFE_TOOLS = {"Read", "Glob", "Grep", "WebFetch", "WebSearch"}

# ---------------------------------------------------------------------------
# Safe command prefixes for Bash — read-only or low-risk commands.
# Matched against the first token(s) of the command string.
# ---------------------------------------------------------------------------
SAFE_COMMAND_PREFIXES = [
    # Read-only git commands
    "git status", "git diff", "git log", "git branch",
    "git show", "git stash list",
    # System info / inspection
    "ls", "pwd", "cat", "head", "tail", "wc", "date",
    "whoami", "which", "echo", "env",
    # Testing frameworks
    "pytest", "python -m pytest", "python3 -m pytest",
    "npm test", "cargo test", "go test",
    # Diagnostic / read-only commands
    "find . -name", "find . -type",
    "grep -r", "grep -rn",
    "ps aux", "ps -ef",
    "df -h", "du -sh",
    "curl -I", "curl --head",
    "file", "stat", "type",
    # Python introspection
    "python3 -c", "python -c",
    "pip list", "pip show", "pip freeze",
]


def make_decision(behavior, message=None):
    """Build the PermissionRequest hook response and print it to stdout."""
    decision = {"behavior": behavior}
    if message:
        decision["message"] = message
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": decision,
        }
    }
    print(json.dumps(payload))


def main():
    data = json.loads(sys.stdin.read())
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    # --- Bash tool: extract command and run deny/allow checks ---
    if tool_name == "Bash":
        command = tool_input.get("command", "")

        # 1. Deny patterns — always checked first
        for pattern, reason in DENY_PATTERNS:
            if pattern.search(command):
                make_decision("deny", reason)
                return

        # 2. Safe command prefixes
        stripped = command.strip()
        for prefix in SAFE_COMMAND_PREFIXES:
            if stripped == prefix or stripped.startswith(prefix + " "):
                make_decision("allow")
                return

        # 3. Version checks: sole argument is --version or -V
        tokens = stripped.split()
        if len(tokens) == 2 and tokens[1] in ("--version", "-V"):
            make_decision("allow")
            return

        # 4. Unknown command — produce no output (fall through to user prompt)
        return

    # --- Read-only tools: auto-approve unconditionally ---
    if tool_name in SAFE_TOOLS:
        make_decision("allow")
        return

    # --- Everything else: no output (fall through to user prompt) ---


# Fail-open: any exception produces no output → user prompt
try:
    main()
except Exception:
    pass
