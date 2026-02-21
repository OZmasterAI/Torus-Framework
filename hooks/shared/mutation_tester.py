"""Mutation tester for Torus Framework gate modules.

Reads a gate's check() source code via AST, generates mutants by applying
code-level transformations, runs the existing test suite against each mutant,
and reports the mutation kill rate.

Surviving mutants highlight gaps in the test suite — cases where a semantic
change to the gate logic goes undetected by the tests.

Mutation operators applied
--------------------------
  BOOL_FLIP       -- flip True/False literals in boolean context
  CMP_OP_SWAP     -- swap comparison operators (== -> !=, < -> <=, etc.)
  COND_REMOVE     -- replace an ``if`` condition with ``True`` or ``False``
  RETURN_FLIP     -- flip ``.blocked`` in GateResult(blocked=...) calls
  LOGIC_NEGATE    -- negate a sub-expression in a boolean chain (and/or)
  STR_SWAP        -- swap string literals in ``in`` / ``not in`` membership tests

Public API
----------
  mutate_gate(gate_module_path)                  -> MutationReport
  print_report(report)                           -> None  (pretty printer)

The ``MutationReport`` dataclass captures:
  gate_path        -- absolute path to the gate module
  total_mutants    -- number of mutants generated
  killed           -- number of mutants caught by tests
  survived         -- list[MutantResult]  (details of surviving mutants)
  kill_rate        -- float in [0.0, 1.0]
  test_gaps        -- human-readable list of descriptions for surviving mutants

CLI usage
---------
  python3 shared/mutation_tester.py gates/gate_01_read_before_edit.py
  python3 shared/mutation_tester.py gates/gate_02_no_destroy.py --verbose
"""

from __future__ import annotations

import ast
import copy
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class MutantResult:
    """Records one applied mutation and whether it was killed by tests."""
    operator: str          # e.g. "BOOL_FLIP", "CMP_OP_SWAP"
    description: str       # human-readable summary, e.g. "line 55: True -> False"
    lineno: int            # source line number of the mutation
    killed: bool           # True  = tests caught the mutant
    test_output: str       # raw stdout/stderr from the test run (truncated)
    mutant_source: str     # full mutated source code (for debugging)


@dataclass
class MutationReport:
    """Aggregated results for a single gate module."""
    gate_path: str
    total_mutants: int = 0
    killed_count: int = 0
    survived: List[MutantResult] = field(default_factory=list)
    all_results: List[MutantResult] = field(default_factory=list)
    elapsed_sec: float = 0.0

    @property
    def kill_rate(self) -> float:
        if self.total_mutants == 0:
            return 0.0
        return self.killed_count / self.total_mutants

    @property
    def test_gaps(self) -> List[str]:
        """Human-readable descriptions of surviving (uncaught) mutants."""
        return [f"[{m.operator}] {m.description}" for m in self.survived]


# ---------------------------------------------------------------------------
# AST mutation visitors
# ---------------------------------------------------------------------------

class _BoolFlipVisitor(ast.NodeTransformer):
    """Flip True/False constant literals (one mutation per node visit).

    Maintains a counter so we can apply exactly one mutation per pass.
    """

    def __init__(self, target_idx: int):
        self._idx = target_idx
        self._seen = 0
        self.applied = False
        self.lineno = 0
        self.description = ""

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        if isinstance(node.value, bool):  # True / False literals
            if self._seen == self._idx:
                new_val = not node.value
                self.applied = True
                self.lineno = getattr(node, "lineno", 0)
                self.description = f"line {self.lineno}: {node.value!r} -> {new_val!r}"
                self._seen += 1
                return ast.copy_location(ast.Constant(value=new_val), node)
            self._seen += 1
        return node


class _CmpOpSwapVisitor(ast.NodeTransformer):
    """Swap one comparison operator (==, !=, <, <=, >, >=, In, NotIn)."""

    _SWAPS = {
        ast.Eq:    ast.NotEq,
        ast.NotEq: ast.Eq,
        ast.Lt:    ast.LtE,
        ast.LtE:   ast.Lt,
        ast.Gt:    ast.GtE,
        ast.GtE:   ast.Gt,
        ast.In:    ast.NotIn,
        ast.NotIn: ast.In,
        ast.Is:    ast.IsNot,
        ast.IsNot: ast.Is,
    }

    def __init__(self, target_idx: int):
        self._idx = target_idx
        self._seen = 0
        self.applied = False
        self.lineno = 0
        self.description = ""

    def visit_Compare(self, node: ast.Compare) -> ast.AST:
        new_ops = []
        for op in node.ops:
            op_type = type(op)
            if op_type in self._SWAPS and self._seen == self._idx:
                new_op_type = self._SWAPS[op_type]
                self.applied = True
                self.lineno = getattr(node, "lineno", 0)
                self.description = (
                    f"line {self.lineno}: {op_type.__name__} -> {new_op_type.__name__}"
                )
                new_ops.append(new_op_type())
                self._seen += 1
            else:
                if op_type in self._SWAPS:
                    self._seen += 1
                new_ops.append(op)
        node.ops = new_ops
        self.generic_visit(node)
        return node


class _CondRemoveVisitor(ast.NodeTransformer):
    """Replace one ``if`` condition expression with True or False."""

    def __init__(self, target_idx: int, replace_with: bool = True):
        self._idx = target_idx
        self._replace_with = replace_with
        self._seen = 0
        self.applied = False
        self.lineno = 0
        self.description = ""

    def visit_If(self, node: ast.If) -> ast.AST:
        if self._seen == self._idx:
            self.applied = True
            self.lineno = getattr(node, "lineno", 0)
            # Render old condition using unparse (Python 3.9+)
            try:
                old_cond = ast.unparse(node.test)
            except AttributeError:
                old_cond = "..."
            self.description = (
                f"line {self.lineno}: condition '{old_cond[:60]}' "
                f"-> {self._replace_with!r}"
            )
            node.test = ast.Constant(value=self._replace_with)
            self._seen += 1
        else:
            self._seen += 1
        self.generic_visit(node)
        return node


class _ReturnFlipVisitor(ast.NodeTransformer):
    """Flip the ``blocked=`` keyword argument in GateResult() calls."""

    def __init__(self, target_idx: int):
        self._idx = target_idx
        self._seen = 0
        self.applied = False
        self.lineno = 0
        self.description = ""

    def visit_Call(self, node: ast.Call) -> ast.AST:
        # Match: GateResult(..., blocked=<bool>, ...)
        func_name = ""
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            func_name = node.func.attr

        if func_name == "GateResult":
            for kw in node.keywords:
                if kw.arg == "blocked" and isinstance(kw.value, ast.Constant):
                    if isinstance(kw.value.value, bool):
                        if self._seen == self._idx:
                            new_val = not kw.value.value
                            self.applied = True
                            self.lineno = getattr(node, "lineno", 0)
                            self.description = (
                                f"line {self.lineno}: GateResult(blocked={kw.value.value!r}) "
                                f"-> GateResult(blocked={new_val!r})"
                            )
                            kw.value = ast.Constant(value=new_val)
                            self._seen += 1
                        else:
                            self._seen += 1
        self.generic_visit(node)
        return node


class _LogicNegateVisitor(ast.NodeTransformer):
    """Negate one operand inside a boolean ``and``/``or`` chain."""

    def __init__(self, target_idx: int):
        self._idx = target_idx
        self._seen = 0
        self.applied = False
        self.lineno = 0
        self.description = ""

    def visit_BoolOp(self, node: ast.BoolOp) -> ast.AST:
        new_values = []
        for val in node.values:
            if self._seen == self._idx and not self.applied:
                try:
                    old_expr = ast.unparse(val)
                except AttributeError:
                    old_expr = "..."
                negated = ast.UnaryOp(op=ast.Not(), operand=val)
                ast.copy_location(negated, val)
                ast.fix_missing_locations(negated)
                self.applied = True
                self.lineno = getattr(val, "lineno", getattr(node, "lineno", 0))
                self.description = (
                    f"line {self.lineno}: negate '{old_expr[:60]}' in boolean chain"
                )
                new_values.append(negated)
                self._seen += 1
            else:
                if not self.applied or self._seen < self._idx:
                    self._seen += 1
                new_values.append(val)
        node.values = new_values
        self.generic_visit(node)
        return node


class _StrSwapVisitor(ast.NodeTransformer):
    """In membership tests (x in COLLECTION), swap the collection literal string.

    Targets string constants that appear as the right side of an ``in`` / ``not in``
    comparison, replacing them with a clearly different sentinel string so that
    any test checking membership will detect the change.
    """

    _SENTINEL_PREFIX = "__MUTANT__"

    def __init__(self, target_idx: int):
        self._idx = target_idx
        self._seen = 0
        self.applied = False
        self.lineno = 0
        self.description = ""

    def visit_Compare(self, node: ast.Compare) -> ast.AST:
        for i, (op, comp) in enumerate(zip(node.ops, node.comparators)):
            if isinstance(op, (ast.In, ast.NotIn)) and isinstance(comp, ast.Constant):
                if isinstance(comp.value, str) and self._seen == self._idx:
                    old_val = comp.value
                    new_val = self._SENTINEL_PREFIX + old_val
                    self.applied = True
                    self.lineno = getattr(node, "lineno", 0)
                    self.description = (
                        f"line {self.lineno}: membership string "
                        f"'{old_val[:40]}' -> '{new_val[:40]}'"
                    )
                    node.comparators[i] = ast.Constant(value=new_val)
                    self._seen += 1
                elif isinstance(comp.value, str):
                    self._seen += 1
        self.generic_visit(node)
        return node


# ---------------------------------------------------------------------------
# Mutation generation engine
# ---------------------------------------------------------------------------

def _count_targets(tree: ast.AST, visitor_class, **kwargs) -> int:
    """Count how many mutation targets a visitor would find in *tree*."""
    # Dry run: probe increasing indices until visitor doesn't apply
    count = 0
    for idx in range(200):  # upper bound safeguard
        v = visitor_class(idx, **kwargs)
        v.visit(copy.deepcopy(tree))
        if not v.applied:
            break
        count += 1
    return count


def _apply_mutation(
    source: str,
    tree: ast.AST,
    visitor_class,
    target_idx: int,
    operator_name: str,
    **kwargs,
) -> Optional[MutantResult]:
    """Apply one mutation and return a MutantResult (or None if not applicable)."""
    tree_copy = copy.deepcopy(tree)
    visitor = visitor_class(target_idx, **kwargs)
    new_tree = visitor.visit(tree_copy)

    if not visitor.applied:
        return None

    ast.fix_missing_locations(new_tree)
    try:
        mutant_source = ast.unparse(new_tree)
    except Exception:
        mutant_source = source

    return MutantResult(
        operator=operator_name,
        description=visitor.description,
        lineno=visitor.lineno,
        killed=False,
        test_output="",
        mutant_source=mutant_source,
    )


def generate_mutants(gate_source: str) -> List[Tuple[MutantResult, str]]:
    """Parse *gate_source* and return a list of (MutantResult, mutant_source) pairs.

    Each tuple represents one applied mutation. The MutantResult has ``killed``
    set to False; the caller is responsible for running tests and updating it.

    Parameters
    ----------
    gate_source:
        Complete Python source of the gate module.

    Returns
    -------
    list of (MutantResult, mutant_source_str)
    """
    tree = ast.parse(gate_source)
    mutants: List[Tuple[MutantResult, str]] = []

    # Simple operators: one config each
    simple_operators = [
        ("BOOL_FLIP",    _BoolFlipVisitor,    {}),
        ("CMP_OP_SWAP",  _CmpOpSwapVisitor,   {}),
        ("RETURN_FLIP",  _ReturnFlipVisitor,  {}),
        ("LOGIC_NEGATE", _LogicNegateVisitor, {}),
        ("STR_SWAP",     _StrSwapVisitor,     {}),
    ]

    for op_name, visitor_class, extra_kwargs in simple_operators:
        n_targets = _count_targets(tree, visitor_class, **extra_kwargs)
        for idx in range(n_targets):
            result = _apply_mutation(
                gate_source, tree, visitor_class, idx, op_name, **extra_kwargs
            )
            if result is not None:
                mutants.append((result, result.mutant_source))

    # COND_REMOVE: two passes (replace with True, then False)
    for replace_val in (True, False):
        n_targets = _count_targets(tree, _CondRemoveVisitor, replace_with=replace_val)
        for idx in range(n_targets):
            result = _apply_mutation(
                gate_source, tree, _CondRemoveVisitor, idx,
                f"COND_REMOVE({'True' if replace_val else 'False'})",
                replace_with=replace_val,
            )
            if result is not None:
                mutants.append((result, result.mutant_source))

    return mutants


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def _find_test_framework(gate_path: str) -> Optional[str]:
    """Walk up from *gate_path* to find test_framework.py."""
    current = os.path.abspath(gate_path)
    for _ in range(10):
        current = os.path.dirname(current)
        candidate = os.path.join(current, "test_framework.py")
        if os.path.exists(candidate):
            return candidate
        if current == os.path.dirname(current):
            break
    return None


def _find_hooks_dir(gate_path: str) -> Optional[str]:
    """Walk up from *gate_path* to find the hooks/ directory."""
    current = os.path.abspath(gate_path)
    for _ in range(10):
        current = os.path.dirname(current)
        if os.path.basename(current) == "hooks":
            return current
        candidate = os.path.join(current, "hooks")
        if os.path.isdir(candidate):
            return candidate
        if current == os.path.dirname(current):
            break
    return None


def _run_tests_against_mutant(
    mutant_source: str,
    original_gate_path: str,
    test_framework_path: str,
    timeout: int = 60,
) -> Tuple[bool, str]:
    """Write mutant over a temp copy of the gate, run tests, report result.

    Strategy: Write the mutant source into a shadow gates/ directory inside a
    temp dir, then run test_framework.py in a subprocess that has that temp dir
    first on PYTHONPATH so Python resolves the mutant gate instead of the real one.

    Returns
    -------
    (killed, output_text)
        killed = True if tests failed (the mutant was caught by tests)
    """
    hooks_dir = _find_hooks_dir(original_gate_path)
    if hooks_dir is None:
        hooks_dir = os.path.dirname(original_gate_path)

    gate_basename = os.path.basename(original_gate_path)
    gate_module_name = os.path.splitext(gate_basename)[0]

    with tempfile.TemporaryDirectory(prefix="torus_mutant_") as tmpdir:
        # Create shadow gates/ directory inside tmpdir
        shadow_gates_dir = os.path.join(tmpdir, "gates")
        os.makedirs(shadow_gates_dir, exist_ok=True)

        # Write mutant gate file
        mutant_gate_path = os.path.join(shadow_gates_dir, gate_basename)
        with open(mutant_gate_path, "w", encoding="utf-8") as fh:
            fh.write(mutant_source)

        # Copy shared/ from hooks_dir so imports resolve
        real_shared_dir = os.path.join(hooks_dir, "shared")
        shadow_shared_dir = os.path.join(tmpdir, "shared")
        if os.path.isdir(real_shared_dir):
            shutil.copytree(real_shared_dir, shadow_shared_dir)

        # Build the test runner wrapper: patches sys.path so the mutant shadows
        # the real gate module for the duration of the test run.
        wrapper_source = textwrap.dedent(f"""\
            import sys
            import os
            import importlib
            import importlib.util

            _tmpdir    = {tmpdir!r}
            _hooks_dir = {hooks_dir!r}

            # tmpdir must come first so the mutant gate is found before the real one
            sys.path.insert(0, _tmpdir)
            sys.path.insert(1, _hooks_dir)

            # Force-register the mutant module under the gate's canonical name
            _gate_name   = {gate_module_name!r}
            _mutant_path = os.path.join(_tmpdir, "gates", {gate_basename!r})

            _spec = importlib.util.spec_from_file_location(
                _gate_name,
                _mutant_path,
                submodule_search_locations=[],
            )
            _mod = importlib.util.module_from_spec(_spec)
            sys.modules[_gate_name] = _mod
            _spec.loader.exec_module(_mod)

            # Execute the test framework in the same process context
            _tf_path = {test_framework_path!r}
            exec(
                compile(open(_tf_path).read(), _tf_path, "exec"),
                {{"__file__": _tf_path, "__name__": "__main__"}},
            )
        """)

        wrapper_path = os.path.join(tmpdir, "_run_mutant_tests.py")
        with open(wrapper_path, "w", encoding="utf-8") as fh:
            fh.write(wrapper_source)

        env = os.environ.copy()
        existing_pp = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            f"{tmpdir}{os.pathsep}{hooks_dir}"
            + (f"{os.pathsep}{existing_pp}" if existing_pp else "")
        )

        try:
            proc = subprocess.run(
                [sys.executable, wrapper_path],
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            output = (proc.stdout + proc.stderr)[-3000:]  # last 3 KB
            # Mutant is killed if test suite exits non-zero
            killed = proc.returncode != 0
            return killed, output
        except subprocess.TimeoutExpired:
            return True, "[TIMEOUT] Test run exceeded limit — counted as killed"
        except Exception as exc:
            return False, f"[ERROR] Runner exception: {exc}"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def mutate_gate(
    gate_module_path: str,
    *,
    verbose: bool = False,
    test_timeout: int = 60,
    max_mutants: Optional[int] = None,
) -> MutationReport:
    """Run mutation testing on a gate module and return a MutationReport.

    Reads the gate source via AST, generates mutants by applying six mutation
    operators, runs test_framework.py against each mutant in an isolated
    subprocess, and returns a report identifying surviving mutants as test gaps.

    Parameters
    ----------
    gate_module_path:
        Absolute or relative path to the gate .py file to test.
    verbose:
        If True, print progress to stderr as each mutant is tested.
    test_timeout:
        Seconds to allow each test run (default 60). The full test suite
        takes ~30-40 s; set higher for slow machines.
    max_mutants:
        Cap the number of mutants tested. None = test all mutants.
        Useful for quick smoke-checks during development.

    Returns
    -------
    MutationReport
        Contains kill_rate, survived mutants, and test_gaps list.

    Raises
    ------
    FileNotFoundError
        If the gate module does not exist.
    RuntimeError
        If test_framework.py cannot be located by walking up from gate_path.
    SyntaxError
        If the gate module cannot be parsed as valid Python.

    Example
    -------
    >>> from shared.mutation_tester import mutate_gate, print_report
    >>> report = mutate_gate("gates/gate_01_read_before_edit.py", verbose=True)
    >>> print_report(report)
    >>> print(f"Kill rate: {report.kill_rate:.1%}")
    >>> for gap in report.test_gaps:
    ...     print(gap)
    """
    gate_path = os.path.abspath(gate_module_path)
    if not os.path.exists(gate_path):
        raise FileNotFoundError(f"Gate module not found: {gate_path}")

    with open(gate_path, "r", encoding="utf-8") as fh:
        gate_source = fh.read()

    # Validate parseable before generating mutants
    ast.parse(gate_source)

    test_framework_path = _find_test_framework(gate_path)
    if test_framework_path is None:
        raise RuntimeError(
            f"Could not locate test_framework.py starting from: {gate_path}"
        )

    if verbose:
        print(f"[mutation_tester] Gate:  {gate_path}", file=sys.stderr)
        print(f"[mutation_tester] Tests: {test_framework_path}", file=sys.stderr)

    t0 = time.time()

    # Generate all mutants from the gate source
    mutant_pairs = generate_mutants(gate_source)

    if max_mutants is not None:
        mutant_pairs = mutant_pairs[:max_mutants]

    if verbose:
        print(
            f"[mutation_tester] Generated {len(mutant_pairs)} mutants — "
            f"running test suite against each...",
            file=sys.stderr,
        )

    report = MutationReport(gate_path=gate_path)
    report.total_mutants = len(mutant_pairs)

    for i, (mut_result, mutant_src) in enumerate(mutant_pairs, 1):
        if verbose:
            label = f"{mut_result.operator}: {mut_result.description[:65]}"
            print(
                f"  [{i:3d}/{len(mutant_pairs)}] {label:<70s} ... ",
                file=sys.stderr,
                end="",
                flush=True,
            )

        killed, output = _run_tests_against_mutant(
            mutant_src, gate_path, test_framework_path, timeout=test_timeout
        )

        mut_result.killed = killed
        mut_result.test_output = output
        mut_result.mutant_source = mutant_src

        report.all_results.append(mut_result)
        if killed:
            report.killed_count += 1
            if verbose:
                print("KILLED", file=sys.stderr)
        else:
            report.survived.append(mut_result)
            if verbose:
                print("SURVIVED", file=sys.stderr)

    report.elapsed_sec = time.time() - t0
    return report


# ---------------------------------------------------------------------------
# Pretty printer
# ---------------------------------------------------------------------------

def print_report(report: MutationReport, *, verbose: bool = False) -> None:
    """Print a human-readable mutation testing report to stdout.

    Parameters
    ----------
    report:
        The MutationReport returned by mutate_gate().
    verbose:
        If True, also print the first 20 lines of the mutant source for
        each surviving mutant (useful for diagnosing test gaps).
    """
    gate_name = os.path.basename(report.gate_path)
    bar_width = 50
    filled = int(report.kill_rate * bar_width)
    bar = "#" * filled + "-" * (bar_width - filled)

    print()
    print("=" * 70)
    print(f"  MUTATION TESTING REPORT")
    print(f"  Gate: {gate_name}")
    print("=" * 70)
    print(f"  Gate path:     {report.gate_path}")
    print(f"  Total mutants: {report.total_mutants}")
    print(f"  Killed:        {report.killed_count}")
    print(f"  Survived:      {len(report.survived)}")
    print(f"  Kill rate:     {report.kill_rate:.1%}  [{bar}]")
    print(f"  Elapsed:       {report.elapsed_sec:.1f}s")
    print()

    # Per-operator breakdown
    op_stats: Dict[str, Dict[str, int]] = {}
    for m in report.all_results:
        op_stats.setdefault(m.operator, {"killed": 0, "survived": 0})
        if m.killed:
            op_stats[m.operator]["killed"] += 1
        else:
            op_stats[m.operator]["survived"] += 1

    if op_stats:
        print("  Operator breakdown:")
        for op_name in sorted(op_stats):
            counts = op_stats[op_name]
            total = counts["killed"] + counts["survived"]
            rate = counts["killed"] / total if total else 0.0
            print(
                f"    {op_name:<26s}  {counts['killed']:3d}/{total:3d} killed"
                f"  ({rate:.0%})"
            )
        print()

    # Surviving mutants = test gaps
    if report.survived:
        print(f"  TEST GAPS — {len(report.survived)} surviving mutant(s):")
        print("  These mutations were NOT caught by the test suite.")
        print("  Each represents a code change the tests cannot detect.")
        print()
        for i, m in enumerate(report.survived, 1):
            print(f"  [{i:2d}] {m.operator:<22s}  line {m.lineno}")
            print(f"       {m.description}")
            if verbose and m.mutant_source:
                lines = m.mutant_source.splitlines()[:20]
                print("       --- mutant source (first 20 lines) ---")
                for line in lines:
                    print(f"         {line}")
            print()
    else:
        print("  All mutants KILLED — test suite comprehensively covers this gate.")

    # Advisory warning for very low kill rates
    if report.kill_rate < 0.5 and report.total_mutants > 0:
        print()
        print("  WARNING: Kill rate below 50%.")
        print("  The test suite misses significant coverage. Suggested gaps:")
        for gap in report.test_gaps[:5]:
            print(f"    - {gap}")

    print("=" * 70)
    print()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Run mutation testing on a Torus Framework gate module "
            "to identify test coverage gaps."
        )
    )
    parser.add_argument(
        "gate",
        help=(
            "Path to the gate .py file to mutate "
            "(e.g. gates/gate_01_read_before_edit.py)"
        ),
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print per-mutant progress and surviving mutant sources",
    )
    parser.add_argument(
        "--max-mutants", "-m",
        type=int,
        default=None,
        metavar="N",
        help="Test only the first N mutants (quick smoke-check mode)",
    )
    parser.add_argument(
        "--timeout", "-t",
        type=int,
        default=60,
        help="Seconds allowed per mutant test run (default: 60)",
    )

    args = parser.parse_args()

    gate_abs = os.path.abspath(args.gate)
    print(f"[mutation_tester] Targeting: {gate_abs}", file=sys.stderr)

    try:
        report = mutate_gate(
            gate_abs,
            verbose=args.verbose,
            test_timeout=args.timeout,
            max_mutants=args.max_mutants,
        )
    except (FileNotFoundError, RuntimeError, SyntaxError) as exc:
        print(f"[mutation_tester] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    print_report(report, verbose=args.verbose)

    # Exit 1 if kill rate is below 60% (signals weak test coverage)
    if report.kill_rate < 0.6 and report.total_mutants > 0:
        sys.exit(1)
