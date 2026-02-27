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
WATCHED_TOOLS = {"Edit", "Write", "NotebookEdit"}
MAX_WARNINGS = 3  # Block on 4th violation per file

CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".rb", ".sh",
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
        return GateResult(blocked=True, gate_name=GATE_NAME, message=msg, severity="warn")

    # Warning path
    msg = (
        f"[{GATE_NAME}] WARNING ({file_count}/{MAX_WARNINGS}): {detail} "
        f"in {os.path.basename(file_path)}"
    )
    print(msg, file=sys.stderr)
    return GateResult(blocked=False, gate_name=GATE_NAME, message=msg, severity="warn")
