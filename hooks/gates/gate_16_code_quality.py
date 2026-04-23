"""Gate 16: CODE QUALITY GUARD (Tier 2 — Advisory)

Pattern-matches code being written via Edit/Write/NotebookEdit to catch
secrets, debug artifacts, and convention violations before they land.

Progressive enforcement: warns 3x per file → blocks on 4th.
Clean edit on same file resets the counter.

Tier 2 (non-safety): gate crash = warn + continue, not block.
"""

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.gate_result import GateResult

GATE_NAME = "GATE 16: CODE QUALITY"

# ── ruff integration ──────────────────────────────────────────────────────────
# shutil resolved lazily on first call to avoid ~90ms cold import at module load.
_RUFF_BIN = None
_RUFF_BIN_RESOLVED = False
_RUFF_CONFIG = os.path.join(os.path.dirname(__file__), "..", ".ruff.toml")


def _get_ruff_bin():
    """Return ruff binary path, resolving once and caching."""
    global _RUFF_BIN, _RUFF_BIN_RESOLVED
    if not _RUFF_BIN_RESOLVED:
        import shutil as _shutil  # lazy: ~90ms cold, only needed for ruff path lookup
        _RUFF_BIN = _shutil.which("ruff") or os.path.expanduser("~/.local/bin/ruff")
        _RUFF_BIN_RESOLVED = True
    return _RUFF_BIN


def _ruff_check(file_path: str, content: str) -> list:
    """Run ruff on content via a temp file. Returns [(rule, lineno, msg), ...].
    Fail-open: returns [] on any error (not found, timeout, parse error)."""
    ruff_bin = _get_ruff_bin()
    if not os.path.isfile(ruff_bin):
        return []
    try:
        import subprocess  # lazy: ~77ms cold, only needed when ruff binary exists
        import tempfile
        with tempfile.NamedTemporaryFile(
            suffix=".py", delete=False, mode="w", encoding="utf-8"
        ) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        try:
            cfg = ["--config", _RUFF_CONFIG] if os.path.isfile(_RUFF_CONFIG) else []
            result = subprocess.run(
                [ruff_bin, "check", tmp_path, "--output-format", "concise"] + cfg,
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


# ── AST complexity (lazy) ────────────────────────────────────────────────────
# All ast-dependent analysis lives inside _python_checks() so that import ast
# (~150ms cold) only happens when gate_16 actually processes a .py file.
_COMPLEXITY_WARN_DEFAULT = 12  # advisory warn, non-escalating
_COMPLEXITY_BLOCK_DEFAULT = 20  # escalates G16 counter (blocks at 4th)
_NESTING_WARN_DEFAULT = 4  # 4 levels of nesting is hard to read
_NESTING_BLOCK_DEFAULT = (
    7  # 7+ levels escalates G16 counter (6 is common in legitimate gate code)
)
_LENGTH_WARN_DEFAULT = 80  # advisory: functions over 80 lines
_LENGTH_BLOCK_DEFAULT = (
    150  # escalates G16 counter at 150+ lines (100 too tight for framework)
)

def _python_checks(content: str, tune: dict) -> list:
    """Run AST complexity/nesting/length checks on Python content.

    Imports ast lazily -- only executed when a .py file is actually being written.
    Returns [(name, lineno, severity, escalates), ...] violation tuples.
    """
    import ast  # lazy: ~150ms cold, only needed for Python files

    _BRANCH_NODES = (ast.If, ast.For, ast.While, ast.ExceptHandler, ast.With, ast.Assert, ast.comprehension)
    _NESTING_NODES = (ast.If, ast.For, ast.While, ast.With, ast.Try, ast.ExceptHandler)
    _NESTING_STOP = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

    class _ComplexityVisitor(ast.NodeVisitor):
        def __init__(self): self.results = []
        def visit_FunctionDef(self, node):
            branches = sum(1 for n in ast.walk(node) if isinstance(n, _BRANCH_NODES))
            self.results.append((node.name, branches + 1))
            self.generic_visit(node)
        visit_AsyncFunctionDef = visit_FunctionDef

    def _compute_nesting(node, depth=0):
        max_d = depth
        if isinstance(node, ast.If):
            for child in node.body:
                if isinstance(child, _NESTING_STOP): continue
                cd = _compute_nesting(child, depth + 1 if isinstance(child, _NESTING_NODES) else depth)
                if cd > max_d: max_d = cd
            if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
                cd = _compute_nesting(node.orelse[0], depth)
                if cd > max_d: max_d = cd
            else:
                for child in node.orelse:
                    if isinstance(child, _NESTING_STOP): continue
                    cd = _compute_nesting(child, depth + 1 if isinstance(child, _NESTING_NODES) else depth)
                    if cd > max_d: max_d = cd
        else:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, _NESTING_STOP): continue
                cd = _compute_nesting(child, depth + 1 if isinstance(child, _NESTING_NODES) else depth)
                if cd > max_d: max_d = cd
        return max_d

    class _NestingVisitor(ast.NodeVisitor):
        def __init__(self): self.results = []
        def visit_FunctionDef(self, node):
            self.results.append((node.name, _compute_nesting(node), node.lineno))
            self.generic_visit(node)
        visit_AsyncFunctionDef = visit_FunctionDef

    class _LengthVisitor(ast.NodeVisitor):
        def __init__(self): self.results = []
        def visit_FunctionDef(self, node):
            length = getattr(node, "end_lineno", node.lineno) - node.lineno + 1
            self.results.append((node.name, length, node.lineno))
            self.generic_visit(node)
        visit_AsyncFunctionDef = visit_FunctionDef

    def _ast_complexity(src, warn_at, block_at):
        try:
            v = _ComplexityVisitor(); v.visit(ast.parse(src))
            return [(n, cx, cx >= block_at) for n, cx in v.results if cx >= warn_at]
        except Exception: return []

    def _ast_nesting(src, warn_at, block_at):
        try:
            v = _NestingVisitor(); v.visit(ast.parse(src))
            return [(n, d, ln, d >= block_at) for n, d, ln in v.results if d >= warn_at]
        except Exception: return []

    def _ast_length(src, warn_at, block_at):
        try:
            v = _LengthVisitor(); v.visit(ast.parse(src))
            return [(n, ln_count, ln, ln_count >= block_at) for n, ln_count, ln in v.results if ln_count >= warn_at]
        except Exception: return []

    violations = []
    _warn_at = tune.get("complexity_warn", _COMPLEXITY_WARN_DEFAULT)
    _block_at = tune.get("complexity_block", _COMPLEXITY_BLOCK_DEFAULT)
    for _fn, _cx, _escalates in _ast_complexity(content, _warn_at, _block_at):
        violations.append((f"complexity:{_fn}(={_cx})", 0, "high" if _escalates else "medium", _escalates))
    _nest_warn = tune.get("nesting_warn", _NESTING_WARN_DEFAULT)
    _nest_block = tune.get("nesting_block", _NESTING_BLOCK_DEFAULT)
    for _fn, _depth, _lineno, _escalates in _ast_nesting(content, _nest_warn, _nest_block):
        violations.append((f"nesting:{_fn}(depth={_depth})", _lineno, "high" if _escalates else "medium", _escalates))
    _len_warn = tune.get("length_warn", _LENGTH_WARN_DEFAULT)
    _len_block = tune.get("length_block", _LENGTH_BLOCK_DEFAULT)
    for _fn, _lines, _lineno, _escalates in _ast_length(content, _len_warn, _len_block):
        violations.append((f"length:{_fn}(={_lines}lines)", _lineno, "high" if _escalates else "medium", _escalates))
    return violations

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
    # ast, shutil, subprocess imported lazily inside these calls.
    if file_path.endswith(".py") and content.strip():
        tune = state.get("gate_tune_overrides", {}).get("gate_16_code_quality", {})
        # ruff: F-codes (undefined names, unused imports) and B-codes (bugbear) escalate
        if tune.get("ruff_enabled", True):
            for _code, _lineno, _msg in _ruff_check(file_path, content):
                _escalates = _code.startswith("F") or _code.startswith("B")
                violations.append((f"ruff:{_code}", _lineno, "medium" if _escalates else "low", _escalates))
        # AST complexity, nesting, and length (all lazy-imported inside _python_checks)
        violations.extend(_python_checks(content, tune))

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
