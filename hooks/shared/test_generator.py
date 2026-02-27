"""Auto-generate test stubs for Torus Framework components.

Scans a Python module and produces test stubs matching the style used in
test_framework.py (check function with PASS/FAIL output, run_enforcer helper,
and direct gate.check() unit tests).

Three function types are detected and given appropriate test scaffolding:

  gate_check    -- functions named ``check`` that take (tool_name, tool_input,
                   state, event_type="PreToolUse") as the standard gate contract.
  shared_util   -- public functions in shared/ modules (anything that is not a
                   gate check and whose module lives under shared/).
  skill_entry   -- public functions in a module that exposes a ``run()`` or
                   ``execute()`` entry point, or whose module lives under a
                   skills/ directory.

Public API
----------
  scan_module(path)                        -> list[(func_name, args, docstring, func_type)]
  generate_tests(scan_result, module_path) -> str
  generate_smoke_test(module_path)         -> str

The ``func_type`` field is one of: "gate_check", "shared_util", "skill_entry",
or "unknown".

Usage (CLI)
-----------
  python3 shared/test_generator.py shared/gate_router.py
  python3 shared/test_generator.py gates/gate_01_read_before_edit.py
  python3 shared/test_generator.py --output /tmp/test_mymod.py shared/my_module.py
"""

import ast
import os
import sys
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

# (func_name, args_list, docstring_or_empty, func_type)
ScanEntry = Tuple[str, List[str], str, str]


# ---------------------------------------------------------------------------
# Module-type detection helpers
# ---------------------------------------------------------------------------

def _is_gate_module(path: str) -> bool:
    """Return True if *path* looks like a gate module."""
    basename = os.path.basename(path)
    return basename.startswith("gate_") and basename.endswith(".py")


def _is_shared_module(path: str) -> bool:
    """Return True if *path* lives inside a shared/ directory."""
    normalized = os.path.normpath(path)
    parts = normalized.split(os.sep)
    return "shared" in parts


def _is_skill_module(path: str) -> bool:
    """Return True if *path* lives inside a skills/ directory."""
    normalized = os.path.normpath(path)
    parts = normalized.split(os.sep)
    return "skills" in parts


def _classify_function(func_name: str, args: List[str], module_path: str) -> str:
    """Classify a function as gate_check, shared_util, skill_entry, or unknown."""
    # Standard gate contract: check(tool_name, tool_input, state, ...)
    if (
        func_name == "check"
        and len(args) >= 3
        and "tool_name" in args
        and "tool_input" in args
        and "state" in args
    ):
        return "gate_check"

    if _is_skill_module(module_path) or func_name in ("run", "execute", "main"):
        return "skill_entry"

    if _is_shared_module(module_path):
        return "shared_util"

    return "unknown"


# ---------------------------------------------------------------------------
# AST-based scanner (safe -- does not import the module)
# ---------------------------------------------------------------------------

def scan_module(path: str) -> List[ScanEntry]:
    """Scan a Python source file and return metadata for each public function.

    Uses the AST so the module is never imported -- safe to use on files that
    have side-effects on import (e.g. gate modules that call sys.exit).

    Parameters
    ----------
    path:
        Absolute or relative path to the .py source file.

    Returns
    -------
    list of (func_name, args, docstring, func_type)
        *args* is the list of positional/keyword argument names (no ``self``).
        *docstring* is the first-line summary (empty string if absent).
        *func_type* is one of ``"gate_check"``, ``"shared_util"``,
        ``"skill_entry"``, or ``"unknown"``.

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    SyntaxError
        If *path* cannot be parsed as valid Python.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Module not found: {path}")

    with open(path, "r", encoding="utf-8") as fh:
        source = fh.read()

    tree = ast.parse(source, filename=path)
    results: List[ScanEntry] = []

    # Only scan top-level function definitions (skip nested helpers).
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        func_name: str = node.name

        # Skip private/dunder functions
        if func_name.startswith("_"):
            continue

        # Collect argument names (skip 'self' / 'cls')
        args: List[str] = []
        for arg in node.args.args:
            if arg.arg not in ("self", "cls"):
                args.append(arg.arg)

        # Extract docstring first line only
        docstring = ""
        if (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            raw_doc = node.body[0].value.value.strip()
            docstring = raw_doc.splitlines()[0].rstrip(".")

        func_type = _classify_function(func_name, args, path)
        results.append((func_name, args, docstring, func_type))

    return results


# ---------------------------------------------------------------------------
# Code-generation helpers
# ---------------------------------------------------------------------------

_HEADER_TEMPLATE = """\
#!/usr/bin/env python3
\"\"\"Auto-generated test stubs for {module_name}.

Generated by shared/test_generator.py.  Fill in assertions -- do not delete
the PASS/FAIL framework boilerplate.
\"\"\"

import os
import sys

# Ensure hooks/ directory is on the path
_HOOKS_DIR = {hooks_abs!r}  # absolute path injected at generation time
sys.path.insert(0, _HOOKS_DIR)

from shared.state import load_state, save_state, reset_state, default_state
from shared.gate_result import GateResult

# ---------------------------------------------------------------------------
# Test harness (mirrors test_framework.py)
# ---------------------------------------------------------------------------

PASS = 0
FAIL = 0
RESULTS = []

TEST_SESSION = "test-generated"


def test(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        RESULTS.append(f"  PASS  {{name}}")
    else:
        FAIL += 1
        RESULTS.append(f"  FAIL  {{name}} -- {{detail}}")

"""

_IMPORT_MODULE_TEMPLATE = """\
# ---------------------------------------------------------------------------
# Import the module under test
# ---------------------------------------------------------------------------
import importlib.util as _ilu

_spec = _ilu.spec_from_file_location("{module_name}", {module_path!r})
_mod  = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

"""

# Gate check() -- standard contract: (tool_name, tool_input, state, event_type)
_GATE_CHECK_TEMPLATE = """\
# -------------------------------------------------
# Tests: {func_name}()  [{func_type}]
# {docstring}
# -------------------------------------------------
print("\\n--- {func_name} ---")

# Standard mock objects for a gate check() test
_tool_input_allow = {{"file_path": "/tmp/test_allow.py"}}
_tool_input_block = {{"file_path": "/tmp/test_block.py"}}

reset_state(session_id=TEST_SESSION)
_state = load_state(session_id=TEST_SESSION)

# TODO: populate _state with any prerequisite session data, e.g.:
#   _state["files_read"] = ["/tmp/test_allow.py"]
#   save_state(_state, session_id=TEST_SESSION)

_result = _mod.{func_name}("Edit", _tool_input_allow, _state)
test(
    "{func_name}: returns GateResult",
    isinstance(_result, GateResult),
    f"got {{type(_result)}}",
)
test(
    "{func_name}: has gate_name set",
    bool(_result.gate_name),
    "gate_name was empty",
)
# TODO: add assertions for expected block/allow behaviour, e.g.:
# test("{func_name}: allows valid input", not _result.blocked, _result.message)
#
# _result2 = _mod.{func_name}("Edit", _tool_input_block, _state)
# test("{func_name}: blocks invalid input", _result2.blocked, "expected block")

"""

# Shared utility -- state_setup placeholder is filled in by generate_tests
_SHARED_UTIL_TEMPLATE = """\
# -------------------------------------------------
# Tests: {func_name}()  [{func_type}]
# {docstring}
# -------------------------------------------------
print("\\n--- {func_name} ---")

{state_setup}# TODO: replace stub arguments with real values
_args = ({stub_args})
try:
    _result = _mod.{func_name}(*_args)
    test("{func_name}: returns without exception", True)
except Exception as _exc:
    test("{func_name}: returns without exception", False, str(_exc))
# TODO: add specific assertions about _result, e.g.:
# test("{func_name}: result is a list",  isinstance(_result, list))
# test("{func_name}: result is non-empty", len(_result) > 0)

"""

_SKILL_ENTRY_TEMPLATE = """\
# -------------------------------------------------
# Tests: {func_name}()  [{func_type}]
# {docstring}
# -------------------------------------------------
print("\\n--- {func_name} ---")

reset_state(session_id=TEST_SESSION)
_state = load_state(session_id=TEST_SESSION)

# TODO: populate state / env as required by this skill entry point
# TODO: replace stub arguments with real values
_args = ({stub_args})
try:
    _result = _mod.{func_name}(*_args)
    test("{func_name}: runs without exception", True)
except Exception as _exc:
    test("{func_name}: runs without exception", False, str(_exc))
# TODO: add assertions about _result

"""

_UNKNOWN_TEMPLATE = """\
# -------------------------------------------------
# Tests: {func_name}()  [{func_type}]
# {docstring}
# -------------------------------------------------
print("\\n--- {func_name} ---")

# TODO: replace stub arguments with real values
_args = ({stub_args})
try:
    _result = _mod.{func_name}(*_args)
    test("{func_name}: runs without exception", True)
except Exception as _exc:
    test("{func_name}: runs without exception", False, str(_exc))

"""

_FOOTER_TEMPLATE = """\
# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print()
print("=" * 60)
for line in RESULTS:
    print(line)
print("=" * 60)
print(f"Result: {PASS} passed, {FAIL} failed")
if FAIL:
    sys.exit(1)
"""


def _stub_args(args: List[str]) -> str:
    """Produce a placeholder argument string for *args*.

    All placeholders are valid Python literals (no inline comments inside the
    tuple literal) so the generated source always parses without syntax errors.
    Returns empty string for empty arg lists (generates ``()``).
    """
    if not args:
        return ""
    placeholders = []
    for a in args:
        if "path" in a:
            placeholders.append(f'"/tmp/stub_{a}.py"')
        elif "state" in a:
            # _state is always defined in the template before _args is built
            placeholders.append("_state")
        elif "name" in a:
            placeholders.append(f'"{a}_value"')
        elif "input" in a:
            placeholders.append("{}")
        else:
            placeholders.append("None")
    if len(placeholders) == 1:
        # Single-element tuple needs a trailing comma
        return placeholders[0] + ","
    return ", ".join(placeholders)


def _needs_state_stub(args: List[str]) -> bool:
    """Return True if any argument name contains 'state'."""
    return any("state" in a for a in args)


def _state_setup_block() -> str:
    """Return the boilerplate that initialises _state for shared_util tests."""
    return (
        "reset_state(session_id=TEST_SESSION)\n"
        "_state = load_state(session_id=TEST_SESSION)\n\n"
    )


def _hooks_rel_from(module_path: str) -> str:
    """Return a relative path string from *module_path*'s dir to hooks/."""
    module_dir = os.path.dirname(os.path.abspath(module_path))
    hooks_dir = _find_hooks_dir(module_path)
    if hooks_dir:
        try:
            return os.path.relpath(hooks_dir, start=module_dir)
        except ValueError:
            pass
    return "."


def _find_hooks_dir(module_path: str) -> Optional[str]:
    """Walk up from *module_path* looking for the hooks/ directory."""
    current = os.path.abspath(module_path)
    for _ in range(12):
        current = os.path.dirname(current)
        if os.path.basename(current) == "hooks":
            return current
        candidate = os.path.join(current, "hooks")
        if os.path.isdir(candidate):
            return candidate
        # Stop at filesystem root
        if current == os.path.dirname(current):
            break
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_tests(scan_result: List[ScanEntry], module_path: str) -> str:
    """Generate a complete test file string from a scan_module() result.

    Parameters
    ----------
    scan_result:
        Output of scan_module().
    module_path:
        Path to the module under test (absolute or relative; resolved
        internally).

    Returns
    -------
    str
        Python source code for the test file.  Write to a .py file and run
        with ``python3`` to execute the generated stubs.
    """
    abs_path = os.path.abspath(module_path)
    module_name = os.path.splitext(os.path.basename(abs_path))[0]
    hooks_abs = _find_hooks_dir(abs_path) or os.path.dirname(abs_path)

    parts = [
        _HEADER_TEMPLATE.format(module_name=module_name, hooks_abs=hooks_abs),
        _IMPORT_MODULE_TEMPLATE.format(
            module_name=module_name,
            module_path=abs_path,
        ),
        f'print("=" * 60)\n'
        f'print("  Tests for: {module_name}")\n'
        f'print("=" * 60)\n\n',
    ]

    for func_name, args, docstring, func_type in scan_result:
        stub = _stub_args(args)
        ctx = dict(
            func_name=func_name,
            func_type=func_type,
            docstring=docstring or f"(no docstring -- {func_name})",
            stub_args=stub,
        )

        if func_type == "gate_check":
            parts.append(_GATE_CHECK_TEMPLATE.format(**ctx))

        elif func_type == "shared_util":
            # Inject _state setup only when the function accepts a state arg
            ctx["state_setup"] = (
                _state_setup_block() if _needs_state_stub(args) else ""
            )
            parts.append(_SHARED_UTIL_TEMPLATE.format(**ctx))

        elif func_type == "skill_entry":
            parts.append(_SKILL_ENTRY_TEMPLATE.format(**ctx))

        else:
            parts.append(_UNKNOWN_TEMPLATE.format(**ctx))

    parts.append(_FOOTER_TEMPLATE)
    return "".join(parts)


def generate_smoke_test(module_path: str) -> str:
    """Scan *module_path* and return a ready-to-run test file string.

    Convenience one-liner: calls scan_module() then generate_tests().

    Parameters
    ----------
    module_path:
        Path to the Python module to generate tests for.

    Returns
    -------
    str
        Complete Python test source.
    """
    scan_result = scan_module(module_path)
    return generate_tests(scan_result, module_path)


# ---------------------------------------------------------------------------
# __main__ smoke test -- generates stubs for shared/gate_router.py by default
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Auto-generate test stubs for a Torus Framework module."
    )
    parser.add_argument(
        "module",
        nargs="?",
        default=os.path.join(os.path.dirname(__file__), "gate_router.py"),
        help=(
            "Path to the Python module to scan "
            "(default: shared/gate_router.py)"
        ),
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Write generated tests to this file (default: print to stdout)",
    )
    cli_args = parser.parse_args()

    target = os.path.abspath(cli_args.module)
    print(f"[test_generator] Scanning: {target}", file=sys.stderr)

    scan = scan_module(target)
    print(
        f"[test_generator] Found {len(scan)} public function(s):",
        file=sys.stderr,
    )
    for fname, fargs, fdoc, ftype in scan:
        arg_str = ", ".join(fargs) if fargs else "(no args)"
        print(f"  [{ftype:12s}] {fname}({arg_str})", file=sys.stderr)
        if fdoc:
            print(f"               {fdoc}", file=sys.stderr)

    generated = generate_tests(scan, target)

    if cli_args.output:
        with open(cli_args.output, "w", encoding="utf-8") as fh:
            fh.write(generated)
        print(f"[test_generator] Written to: {cli_args.output}", file=sys.stderr)
    else:
        print(generated)
