"""Gate 16: CODE QUALITY GUARD (Tier 2 — Advisory)

Pattern-matches code being written via Edit/Write/NotebookEdit to catch
secrets, debug artifacts, and convention violations before they land.

Progressive enforcement: warns 3x per file → blocks on 4th.
Clean edit on same file resets the counter.

Tier 2 (non-safety): gate crash = warn + continue, not block.
"""

import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.gate_result import GateResult

GATE_NAME = "GATE 16: CODE QUALITY"

# ── ruff integration ──────────────────────────────────────────────────────────
_RUFF_BIN = shutil.which("ruff") or "/home/crab/.local/bin/ruff"
_RUFF_CONFIG = os.path.join(os.path.dirname(__file__), "..", ".ruff.toml")


def _ruff_check(file_path: str, content: str) -> list:
    """Run ruff on content via a temp file. Returns [(rule, lineno, msg), ...].
    Fail-open: returns [] on any error (not found, timeout, parse error)."""
    if not os.path.isfile(_RUFF_BIN):
        return []
    try:
        with tempfile.NamedTemporaryFile(
            suffix=".py", delete=False, mode="w", encoding="utf-8"
        ) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        try:
            cfg = ["--config", _RUFF_CONFIG] if os.path.isfile(_RUFF_CONFIG) else []
            result = subprocess.run(
                [_RUFF_BIN, "check", tmp_path, "--output-format", "concise"] + cfg,
                capture_output=True,
                text=True,
                timeout=3,
            )
            violations = []
            for line in result.stdout.splitlines():
                # concise format: "path:line:col: CODE message"
                parts = line.split(":", 3)
                if len(parts) >= 4:
                    try:
                        lineno = int(parts[1])
                        rest = parts[3].strip()
                        code = rest.split()[0] if rest else "?"
                        msg = rest[len(code) :].strip()
                        violations.append((code, lineno, msg))
                    except (ValueError, IndexError):
                        pass
            return violations
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    except Exception:
        return []  # Fail-open


# ── AST complexity ────────────────────────────────────────────────────────────
_COMPLEXITY_WARN_DEFAULT = 12  # advisory warn, non-escalating
_COMPLEXITY_BLOCK_DEFAULT = 20  # escalates G16 counter (blocks at 4th)
_NESTING_WARN_DEFAULT = 4  # 4 levels of nesting is hard to read
_NESTING_BLOCK_DEFAULT = 6  # 6+ levels escalates G16 counter
_LENGTH_WARN_DEFAULT = 60  # advisory: functions over 60 lines
_LENGTH_BLOCK_DEFAULT = 100  # escalates G16 counter at 100+ lines

_BRANCH_NODES = (
    ast.If,
    ast.For,
    ast.While,
    ast.ExceptHandler,
    ast.With,
    ast.Assert,
    ast.comprehension,
)

# Control-flow nodes that increase nesting depth
_NESTING_NODES = (ast.If, ast.For, ast.While, ast.With, ast.Try, ast.ExceptHandler)
# Stop recursing into nested function/class bodies when measuring outer function depth
_NESTING_STOP = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


class _ComplexityVisitor(ast.NodeVisitor):
    def __init__(self):
        self.results = []  # [(func_name, complexity)]

    def visit_FunctionDef(self, node):
        branches = sum(1 for n in ast.walk(node) if isinstance(n, _BRANCH_NODES))
        self.results.append((node.name, branches + 1))
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef


def _ast_complexity(content: str, warn_at: int, block_at: int) -> list:
    """Check cyclomatic complexity for all functions in content.
    Returns [(func_name, complexity, escalates), ...] for functions >= warn_at.
    Fail-open: returns [] on SyntaxError or any parse failure."""
    try:
        tree = ast.parse(content)
        visitor = _ComplexityVisitor()
        visitor.visit(tree)
        results = []
        for name, complexity in visitor.results:
            if complexity >= warn_at:
                escalates = complexity >= block_at
                results.append((name, complexity, escalates))
        return results
    except Exception:
        return []  # Fail-open


def _compute_nesting(node, depth=0):
    """Recursively compute max control-flow nesting depth.
    Does not cross nested function/class boundaries."""
    max_d = depth
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _NESTING_STOP):
            continue
        child_depth = _compute_nesting(
            child, depth + 1 if isinstance(child, _NESTING_NODES) else depth
        )
        if child_depth > max_d:
            max_d = child_depth
    return max_d


class _NestingVisitor(ast.NodeVisitor):
    def __init__(self):
        self.results = []  # [(func_name, max_depth, lineno)]

    def visit_FunctionDef(self, node):
        depth = _compute_nesting(node)
        self.results.append((node.name, depth, node.lineno))
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef


class _LengthVisitor(ast.NodeVisitor):
    def __init__(self):
        self.results = []  # [(func_name, line_count, lineno)]

    def visit_FunctionDef(self, node):
        length = getattr(node, "end_lineno", node.lineno) - node.lineno + 1
        self.results.append((node.name, length, node.lineno))
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef


def _ast_nesting(content: str, warn_at: int, block_at: int) -> list:
    """Check max control-flow nesting depth for all functions.
    Returns [(func_name, depth, lineno, escalates), ...] for functions >= warn_at.
    Fail-open: returns [] on SyntaxError or any parse failure."""
    try:
        tree = ast.parse(content)
        visitor = _NestingVisitor()
        visitor.visit(tree)
        results = []
        for name, depth, lineno in visitor.results:
            if depth >= warn_at:
                escalates = depth >= block_at
                results.append((name, depth, lineno, escalates))
        return results
    except Exception:
        return []  # Fail-open


def _ast_length(content: str, warn_at: int, block_at: int) -> list:
    """Check function line count.
    Returns [(func_name, lines, lineno, escalates), ...] for functions >= warn_at.
    Fail-open: returns [] on SyntaxError or any parse failure."""
    try:
        tree = ast.parse(content)
        visitor = _LengthVisitor()
        visitor.visit(tree)
        results = []
        for name, length, lineno in visitor.results:
            if length >= warn_at:
                escalates = length >= block_at
                results.append((name, length, lineno, escalates))
        return results
    except Exception:
        return []  # Fail-open


WATCHED_TOOLS = {"Edit", "Write", "NotebookEdit"}
MAX_WARNINGS = 3  # Block on 4th violation per file

CODE_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".rb",
    ".sh",
}

from shared.exemptions import is_exempt_full

# Pattern definitions: (name, compiled_regex, description, severity, escalates)
# escalates=False means the pattern warns but never increments the counter
PATTERNS = [
    (
        "secret-in-code",
        re.compile(
            r'(?i)(api_key|api_secret|password|secret_key|access_token|private_key)\s*=\s*["\'][^"\']{8,}["\']'
        ),
        "hardcoded secret with value ≥8 chars",
        "high",
        True,
    ),
    (
        "debug-print",
        re.compile(
            r"(?m)^\s*(print\(|console\.log\(|debugger;|import pdb|breakpoint\(\))"
        ),
        "debug statement",
        "medium",
        True,
    ),
    (
        "broad-except",
        re.compile(r"except\s*:|except\s+Exception\s*:"),
        "bare/broad except clause",
        "low",
        True,
    ),
    (
        "todo-fixme",
        re.compile(r"(?i)\b(TODO|FIXME|HACK|XXX)\b"),
        "unresolved marker",
        "info",
        False,  # Never escalates
    ),
]


def _is_exempt(file_path):
    """Check if file is exempt from code quality checks (shared + code-ext filter)."""
    if is_exempt_full(file_path):
        return True
    _, ext = os.path.splitext(os.path.basename(file_path))
    return ext.lower() not in CODE_EXTENSIONS


def _get_content(tool_name, tool_input):
    """Extract the code content to scan from tool input."""
    if tool_name == "Edit":
        return tool_input.get("new_string", "")
    elif tool_name == "Write":
        return tool_input.get("content", "")
    elif tool_name == "NotebookEdit":
        return tool_input.get("new_source", "")
    return ""


def _scan_content(content):
    """Run all patterns against content. Returns list of (name, line_num, severity, escalates)."""
    violations = []
    lines = content.split("\n")
    for name, regex, _desc, severity, escalates in PATTERNS:
        for i, line in enumerate(lines, 1):
            if regex.search(line):
                violations.append((name, i, severity, escalates))
                break  # One match per pattern is enough
    return violations


def check(tool_name, tool_input, state, event_type="PreToolUse"):
    """Check code quality patterns in written content."""
    if event_type != "PreToolUse":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if tool_name not in WATCHED_TOOLS:
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if not isinstance(tool_input, dict):
        tool_input = {}

    file_path = tool_input.get("file_path", "") or tool_input.get("notebook_path", "")

    if _is_exempt(file_path):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    content = _get_content(tool_name, tool_input)
    if not content or not content.strip():
        return GateResult(blocked=False, gate_name=GATE_NAME)

    violations = _scan_content(content)

    # Python-only: ruff + AST complexity (non-Python files use regex patterns only)
    if file_path.endswith(".py") and content.strip():
        tune = state.get("gate_tune_overrides", {}).get("gate_16_code_quality", {})
        # ruff: F-codes (undefined names, unused imports) and B-codes (bugbear) escalate
        if tune.get("ruff_enabled", True):
            for _code, _lineno, _msg in _ruff_check(file_path, content):
                _escalates = _code.startswith("F") or _code.startswith("B")
                violations.append(
                    (
                        f"ruff:{_code}",
                        _lineno,
                        "medium" if _escalates else "low",
                        _escalates,
                    )
                )
        # AST complexity: warn at 12, escalate counter at 20 (tunable)
        _warn_at = tune.get("complexity_warn", _COMPLEXITY_WARN_DEFAULT)
        _block_at = tune.get("complexity_block", _COMPLEXITY_BLOCK_DEFAULT)
        for _fn, _cx, _escalates in _ast_complexity(content, _warn_at, _block_at):
            violations.append(
                (
                    f"complexity:{_fn}(={_cx})",
                    0,
                    "high" if _escalates else "medium",
                    _escalates,
                )
            )
        # AST nesting depth: warn at 4, escalate at 6 (tunable)
        _nest_warn = tune.get("nesting_warn", _NESTING_WARN_DEFAULT)
        _nest_block = tune.get("nesting_block", _NESTING_BLOCK_DEFAULT)
        for _fn, _depth, _lineno, _escalates in _ast_nesting(
            content, _nest_warn, _nest_block
        ):
            violations.append(
                (
                    f"nesting:{_fn}(depth={_depth})",
                    _lineno,
                    "high" if _escalates else "medium",
                    _escalates,
                )
            )
        # Function length: warn at 60 lines, escalate at 100 (tunable)
        _len_warn = tune.get("length_warn", _LENGTH_WARN_DEFAULT)
        _len_block = tune.get("length_block", _LENGTH_BLOCK_DEFAULT)
        for _fn, _lines, _lineno, _escalates in _ast_length(
            content, _len_warn, _len_block
        ):
            violations.append(
                (
                    f"length:{_fn}(={_lines}lines)",
                    _lineno,
                    "high" if _escalates else "medium",
                    _escalates,
                )
            )

    if not violations:
        # Clean edit — reset counter for this file
        per_file = state.get("code_quality_warnings_per_file", {})
        per_file.pop(file_path, None)
        state["code_quality_warnings_per_file"] = per_file
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Count escalating violations only
    escalating = [v for v in violations if v[3]]

    per_file = state.get("code_quality_warnings_per_file", {})
    file_count = per_file.get(file_path, 0)

    if escalating:
        file_count += 1
        per_file[file_path] = file_count
        state["code_quality_warnings_per_file"] = per_file

    violation_strs = [f"{v[0]} (line {v[1]})" for v in violations]
    detail = ", ".join(violation_strs)

    if escalating and file_count > MAX_WARNINGS:
        msg = (
            f"[{GATE_NAME}] BLOCKED: Code quality issues: {detail}. "
            f"({file_count} violations on {os.path.basename(file_path)} — "
            f"exceeded {MAX_WARNINGS} warning limit). Re-edit without the violation to clear. "
            f"If also blocked by Gate 6, call remember_this() first."
        )
        return GateResult(
            blocked=True, gate_name=GATE_NAME, message=msg, severity="warn"
        )

    # Warning path
    msg = (
        f"[{GATE_NAME}] WARNING ({file_count}/{MAX_WARNINGS}): {detail} "
        f"in {os.path.basename(file_path)}"
    )
    print(msg, file=sys.stderr)
    return GateResult(blocked=False, gate_name=GATE_NAME, message=msg, severity="warn")
