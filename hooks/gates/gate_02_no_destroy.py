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
# Each tuple: (regex_pattern, description)
# The description string is used as a key for SAFE_EXCEPTIONS below.
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
    # Allow optional C-style comments (/* ... */) between DROP and the object keyword,
    # since SQL parsers ignore comments and they could bypass a naive whitespace-only regex.
    (r"DROP\s+(?:/\*.*?\*/\s*)?(TABLE|DATABASE|SCHEMA|VIEW|INDEX|FUNCTION|PROCEDURE|TRIGGER)\b", "DROP database object"),
    (r"TRUNCATE\s+TABLE\b", "TRUNCATE TABLE"),
    # Git destructive operations
    (r"git\s+push\s+.*--force\b", "git push --force"),
    (r"git\s+push\s+.*-f\b", "git push -f (force)"),
    # Allow flags between 'git' and 'reset' (e.g. git -C path reset ...)
    # and between 'reset' and '--hard' (e.g. git reset -q --hard).
    (r"git\b.*\breset\b.*--hard\b", "git reset --hard"),
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
    # Disk encryption/partition destruction
    (r"\bcryptsetup\s+(luksFormat|luksErase|erase|remove)\b", "cryptsetup LUKS destruction"),
    (r"\b(wipefs|sgdisk\s+--zap-all)\b", "disk signature/partition wipe"),
    # Dangerous rsync (can delete target contents)
    (r"\brsync\b.*--delete\b", "rsync --delete (can remove target files)"),
    # Shell wrapping / indirection (can hide any destructive command)
    (r"\beval\s+", "eval (shell command indirection)"),
    (r"\bbash\s+-c\s+", "bash -c (shell command wrapping)"),
    (r"\bsh\s+-c\s+", "sh -c (shell command wrapping)"),
    (r"\|\s*(ba)?sh\b", "pipe to shell (command indirection)"),
    (r"<<<\s*", "heredoc execution (<<<)"),
    (r"(?<!<)<<(?!<)\s*", "heredoc input (<<)"),
    (r"\bexec\s+", "exec (replace current process)"),
    (r"(?:^|[;&|]\s*)source\s+", "source (execute script in current shell)"),
    # SQL mass deletion without WHERE clause
    (r"\bDELETE\s+FROM\s+", "DELETE FROM (SQL mass deletion)"),
    # Git destructive operations (additional)
    (r"git\s+checkout\s+--\s+\.", "git checkout -- . (discard all changes)"),
    (r"git\s+stash\s+drop", "git stash drop (destroy stashed changes)"),
]

# Safe exceptions: when a dangerous pattern matches, these overrides are checked.
# If the command also matches a safe exception for that pattern, it is allowed through.
# Format: (exact_description_from_DANGEROUS_PATTERNS, safe_regex_pattern)
# NOTE: Bypass vectors (eval, bash -c, sh -c, pipe-to-shell) have NO exceptions.
SAFE_EXCEPTIONS = [
    # source: handled by _source_is_safe() below (path validation with realpath)
    # exec: handled by _exec_is_safe() below (shlex-based, not regex)
    # DELETE FROM: allow targeted SQL deletes that include a WHERE clause
    ("DELETE FROM (SQL mass deletion)",
     r"\bDELETE\s+FROM\s+\S+\s+WHERE\b"),
    # git stash drop: allow dropping a specific numbered stash reference
    ("git stash drop (destroy stashed changes)",
     r"git\s+stash\s+drop\s+stash@\{\d+\}"),
]


def _is_safe_exception(command, description):
    """Check if a command that matched a dangerous pattern is actually a known-safe usage.

    Uses SAFE_EXCEPTIONS for regex-based overrides and special-case logic
    for patterns (like <<<) that need more sophisticated analysis.
    """
    # Check regex-based exceptions
    for exc_desc, exc_pattern in SAFE_EXCEPTIONS:
        if exc_desc == description and re.search(exc_pattern, command, re.IGNORECASE):
            return True

    # Special case: exec interpreter hand-off (shlex-based tokenization)
    if description == "exec (replace current process)":
        return _exec_is_safe(command)

    # Special case: <<< here-strings are safe when not feeding to a shell
    if description == "heredoc execution (<<<)":
        # Extract the command word immediately before <<<
        # Handles: wc -w <<< "hello", grep -c "x" <<< "$var"
        m = re.search(r"\b(\w+)\b[^|;&]*<<<", command)
        if m and m.group(1).lower() not in ("bash", "sh", "zsh", "eval", "exec"):
            return True

    # Special case: << heredocs are safe when feeding to non-shell commands
    if description == "heredoc input (<<)":
        # Extract the command word before <<
        # Safe: cat << EOF, wc << EOF, tee << EOF
        # Dangerous: bash << EOF, sh << EOF, python3 << EOF
        DANGEROUS_HEREDOC_CMDS = {"bash", "sh", "zsh", "eval", "exec",
                                   "python", "python2", "python3", "node",
                                   "ruby", "perl"}
        m = re.search(r"\b(\w+)\b[^|;&]*(?<!<)<<(?!<)", command)
        if m and m.group(1).lower() not in DANGEROUS_HEREDOC_CMDS:
            return True

    # Special case: source with symlink validation
    if description == "source (execute script in current shell)":
        return _source_is_safe(command)

    return False


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


def _exec_is_safe(command):
    """Check if an exec command is a safe interpreter hand-off.

    Uses shlex tokenization to detect -c/-e flags and heredoc << anywhere
    in the argument list, not just immediately after the interpreter name.
    This fixes the flag-interleaving bypass where 'exec python3 -W default -c "code"'
    would slip past a regex-based negative lookahead.

    Allows: exec python3 app.py, exec node server.js, exec cargo run
    Blocks: exec python3 -c "code", exec python3 -W default -c "code",
            exec python3 << 'EOF', exec node -e "code"
    """
    SAFE_INTERPRETERS = {
        "python", "python2", "python3", "node", "ruby", "java",
        "perl", "npm", "npx",
    }
    SAFE_MULTI_WORD = {("cargo", "run"), ("go", "run")}
    DANGEROUS_FLAGS = {"-c", "-e"}

    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()

    for i, token in enumerate(tokens):
        if token != "exec":
            continue
        rest = tokens[i + 1:]
        if not rest:
            return False

        interpreter = rest[0]
        args_start = 1

        # Check single-word interpreters
        if interpreter not in SAFE_INTERPRETERS:
            # Check multi-word interpreters (cargo run, go run)
            if len(rest) > 1 and (interpreter, rest[1]) in SAFE_MULTI_WORD:
                args_start = 2
            else:
                return False

        # Scan ALL remaining args for dangerous flags or heredoc input
        for arg in rest[args_start:]:
            if arg in DANGEROUS_FLAGS:
                return False
            if arg.startswith("<<"):
                return False

        return True

    return False


def _source_is_safe(command):
    """Check if a source command is safe by validating both filename and resolved path.

    Only allows sourcing files that:
    1. Match known-safe filenames (activate, .bashrc, .profile, etc.)
    2. Resolve (via os.path.realpath) to a path under $HOME, /etc/, or /usr/local/

    This prevents symlink attacks where /tmp/activate -> /tmp/malicious.sh.
    """
    SAFE_FILENAMES = {"activate", ".bashrc", ".bash_profile", ".profile",
                      ".zshrc", ".zprofile", ".envrc"}
    ALLOWED_PREFIXES = [
        os.path.expanduser("~"),  # Current user's home
        "/home/",                 # Any user home directory (Linux)
        "/Users/",                # Any user home directory (macOS)
        "/etc/",                  # System configuration
        "/usr/local/",            # Local installations
        "/usr/",                  # System packages
        "/opt/",                  # Optional packages
    ]

    # Extract the path argument from the source command
    m = re.search(r"\bsource\s+(\S+)", command)
    if not m:
        return False

    source_path = m.group(1)
    basename = os.path.basename(source_path)

    # Check filename matches a known-safe name
    if basename not in SAFE_FILENAMES:
        return False

    # Resolve symlinks and validate the real path is in an allowed directory
    try:
        real_path = os.path.realpath(source_path)
    except (OSError, ValueError):
        return False

    for prefix in ALLOWED_PREFIXES:
        if real_path.startswith(prefix):
            return True

    return False


def check(tool_name, tool_input, state, event_type="PreToolUse"):
    if event_type != "PreToolUse":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if tool_name != "Bash":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if not isinstance(tool_input, dict):
        tool_input = {}

    command = tool_input.get("command", "")

    for pattern, description in DANGEROUS_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            # Check if this matches a known-safe exception before blocking
            if _is_safe_exception(command, description):
                continue
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
