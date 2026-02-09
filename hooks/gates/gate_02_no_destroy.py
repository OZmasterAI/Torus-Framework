"""Gate 2: NO DESTROY (Tier 1 — Safety)

Blocks dangerous destructive commands that could cause irreversible damage:
  - rm -rf (recursive force delete)
  - DROP TABLE / DROP DATABASE
  - git push --force / git push -f (to main/master)
  - git reset --hard
  - git clean -f
  - git checkout . (discard all changes)
  - mkfs (format filesystem)
  - dd if= (raw disk write)

These are the commands that, in 556 sessions, caused the most damage when
executed accidentally by an AI assistant.
"""

import os
import re
import shlex
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.gate_result import GateResult

GATE_NAME = "GATE 2: NO DESTROY"

# Patterns to block in Bash commands
DANGEROUS_PATTERNS = [
    # rm with recursive+force in any flag order, including split flags and full paths
    (r"(?:/[^\s]*/)?rm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r)\b", "rm -rf (recursive force delete)"),
    (r"(?:/[^\s]*/)?rm\s+-rf\b", "rm -rf (recursive force delete)"),
    (r"(?:/[^\s]*/)?rm\s+(-r\s+-f|-f\s+-r|--recursive\s+--force|--force\s+--recursive)\b", "rm -r -f (split flags)"),
    (r"(?:/[^\s]*/)?rm\s+--recursive\s+--force\b", "rm --recursive --force"),
    (r"(?:/[^\s]*/)?rm\s+--force\s+--recursive\b", "rm --force --recursive"),
    (r"(?:/[^\s]*/)?rm\s+.*--force\b.*--recursive\b", "rm --force --recursive"),
    (r"(?:/[^\s]*/)?rm\s+.*--recursive\b.*--force\b", "rm --recursive --force"),
    # SQL destructive operations (expanded)
    (r"DROP\s+(TABLE|DATABASE|SCHEMA|VIEW|INDEX|FUNCTION|PROCEDURE|TRIGGER)\b", "DROP database object"),
    (r"TRUNCATE\s+TABLE\b", "TRUNCATE TABLE"),
    # Git destructive operations
    (r"git\s+push\s+.*--force\b", "git push --force"),
    (r"git\s+push\s+.*-f\b", "git push -f (force)"),
    (r"git\s+reset\s+--hard\b", "git reset --hard"),
    (r"git\s+clean\s+-[a-zA-Z]*f", "git clean -f"),
    (r"git\s+checkout\s+\.\s*(?:$|[;&|])", "git checkout . (discard all changes)"),
    (r"git\s+restore\s+\.\s*(?:$|[;&|])", "git restore . (discard all changes)"),
    # Filesystem destruction
    (r"mkfs\.", "mkfs (format filesystem)"),
    (r"\bdd\s+if=", "dd (raw disk write)"),
    (r":\(\)\s*\{", "fork bomb"),
    (r">\s*/dev/sd[a-z]", "write to raw disk device"),
    (r"chmod\s+-R\s+777\s+/\s*(?:$|[;&|])", "chmod -R 777 / (open permissions on root)"),
    # Alternative deletion tools
    (r"\bfind\b.*\s-delete\b", "find -delete (recursive file deletion)"),
    (r"\btruncate\s+-s\s*0\b", "truncate -s 0 (zero file contents)"),
    (r"\bshred\b", "shred (secure file destruction)"),
    # Dangerous rsync (can delete target contents)
    (r"\brsync\b.*--delete\b", "rsync --delete (can remove target files)"),
    # Shell wrapping / indirection (can hide any destructive command)
    (r"\beval\s+", "eval (shell command indirection)"),
    (r"\bbash\s+-c\s+", "bash -c (shell command wrapping)"),
    (r"\bsh\s+-c\s+", "sh -c (shell command wrapping)"),
    (r"\|\s*(ba)?sh\b", "pipe to shell (command indirection)"),
    (r"<<<\s*", "heredoc execution"),
    (r"\bexec\s+", "exec (replace current process)"),
    (r"\bsource\s+", "source (execute script in current shell)"),
    # SQL mass deletion without WHERE clause
    (r"\bDELETE\s+FROM\s+", "DELETE FROM (SQL mass deletion)"),
    # Git destructive operations (additional)
    (r"git\s+checkout\s+--\s+\.", "git checkout -- . (discard all changes)"),
    (r"git\s+stash\s+drop", "git stash drop (destroy stashed changes)"),
]


def _rm_has_recursive_and_force(command):
    """Check if an rm command has both recursive and force flags anywhere in its arguments.

    Uses shlex tokenization to handle flag ordering like: rm -r somedir -f
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        # If shlex can't parse it, fall back to simple split
        tokens = command.split()

    # Find rm commands (including with full path like /usr/bin/rm)
    for i, token in enumerate(tokens):
        basename = os.path.basename(token)
        if basename != "rm":
            continue
        # Check remaining tokens for both -r/--recursive and -f/--force
        rest = tokens[i + 1:]
        has_recursive = False
        has_force = False
        for arg in rest:
            if arg == "--":
                break  # End of flags
            if arg.startswith("-") and not arg.startswith("--"):
                # Short flags like -r, -f, -v, or combined like -rv
                flags = arg[1:]
                if "r" in flags:
                    has_recursive = True
                if "f" in flags:
                    has_force = True
            elif arg == "--recursive":
                has_recursive = True
            elif arg == "--force":
                has_force = True
        if has_recursive and has_force:
            return True
    return False


def check(tool_name, tool_input, state, event_type="PreToolUse"):
    if event_type != "PreToolUse":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if tool_name != "Bash":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    command = tool_input.get("command", "")

    for pattern, description in DANGEROUS_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return GateResult(
                blocked=True,
                message=f"[{GATE_NAME}] BLOCKED: Detected '{description}' in command. This is a destructive operation.",
                gate_name=GATE_NAME,
            )

    # Check for rm with split recursive+force flags (e.g., rm -r dir -f)
    if _rm_has_recursive_and_force(command):
        return GateResult(
            blocked=True,
            message=f"[{GATE_NAME}] BLOCKED: Detected 'rm with -r and -f flags' in command. This is a destructive operation.",
            gate_name=GATE_NAME,
        )

    return GateResult(blocked=False, gate_name=GATE_NAME)
