"""gate_graph.py — Dependency graph for gates and shared modules.

Scans all gate files in hooks/gates/, parses their 'from shared.X import ...'
statements, and builds an adjacency list of gate → [shared_modules] dependencies.

Public API:
  build_graph()              -> GateGraph instance
  GateGraph.render_ascii()   -> str  (ASCII dependency tree)
  GateGraph.find_circular_deps() -> list[list[str]]  (circular chains, if any)
  GateGraph.get_impact_analysis(module_name) -> dict  (gates broken if module changes)

The graph also captures intra-shared dependencies (shared modules that import
other shared modules), so impact analysis can propagate transitively.
"""

import ast
import os
import re
from collections import defaultdict, deque
from typing import Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_HOOKS_DIR = os.path.join(os.path.dirname(__file__), "..")
GATES_DIR = os.path.abspath(os.path.join(_HOOKS_DIR, "gates"))
SHARED_DIR = os.path.abspath(os.path.join(_HOOKS_DIR, "shared"))


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_shared_imports(filepath: str) -> List[str]:
    """Return a sorted list of shared module names imported by *filepath*.

    Only 'from shared.X import ...' and 'import shared.X' patterns are
    recognised.  Internal stdlib / third-party imports are ignored.

    Uses Python's AST parser as the primary strategy so that import
    statements embedded inside docstrings or multi-line strings are
    correctly ignored.  Falls back to a line-oriented regex when the
    source cannot be parsed (e.g. syntax errors).
    """
    modules: Set[str] = set()

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
            source = fh.read()
    except OSError:
        return []

    # --- Strategy 1: AST (authoritative — ignores docstring content) ------
    ast_ok = False
    try:
        tree = ast.parse(source, filename=filepath)
        ast_ok = True
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("shared."):
                    modules.add(node.module.split(".")[1])
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("shared."):
                        modules.add(alias.name.split(".")[1])
    except (SyntaxError, ValueError):
        ast_ok = False

    # --- Strategy 2: line-oriented regex (fallback for unparseable files) --
    # Only used when AST failed.  Matches lines that begin with
    # 'from shared.' or 'import shared.' (after optional whitespace),
    # which excludes lines inside string literals in well-formed Python.
    if not ast_ok:
        _FROM_PAT = re.compile(r"^\s*from\s+shared\.(\w+)\s+import", re.MULTILINE)
        _IMPORT_PAT = re.compile(r"^\s*import\s+shared\.(\w+)", re.MULTILINE)
        for m in _FROM_PAT.finditer(source):
            modules.add(m.group(1))
        for m in _IMPORT_PAT.finditer(source):
            modules.add(m.group(1))

    return sorted(modules)


def _gate_label(filename: str) -> str:
    """Convert 'gate_04_memory_first.py' → 'gate_04_memory_first'."""
    return os.path.splitext(os.path.basename(filename))[0]


def _module_label(filename: str) -> str:
    """Convert 'state.py' → 'state'."""
    return os.path.splitext(os.path.basename(filename))[0]


# ---------------------------------------------------------------------------
# GateGraph
# ---------------------------------------------------------------------------

class GateGraph:
    """Holds the dependency graph and provides analysis utilities.

    Attributes
    ----------
    gates : list[str]
        Sorted gate labels (e.g. 'gate_01_read_before_edit').
    shared_modules : list[str]
        Sorted shared module names (e.g. 'gate_result', 'state').
    gate_deps : dict[str, list[str]]
        gate_label → list of shared_module names it imports.
    module_deps : dict[str, list[str]]
        shared_module → list of other shared_modules it imports.
    """

    def __init__(
        self,
        gate_deps: Dict[str, List[str]],
        module_deps: Dict[str, List[str]],
        shared_modules: List[str],
    ):
        self.gate_deps: Dict[str, List[str]] = gate_deps
        self.module_deps: Dict[str, List[str]] = module_deps
        self.shared_modules: List[str] = sorted(shared_modules)
        self.gates: List[str] = sorted(gate_deps.keys())

    # ------------------------------------------------------------------
    # ASCII rendering
    # ------------------------------------------------------------------

    def render_ascii(self) -> str:
        """Return an ASCII dependency tree showing gate → shared module edges.

        Format::

            GATE DEPENDENCY TREE
            ════════════════════════════════════════
            gate_01_read_before_edit
              └── gate_result
            gate_04_memory_first
              ├── gate_result
              └── state
            ...

            SHARED MODULE INTERNAL DEPENDENCIES
            ════════════════════════════════════════
            gate_router
              └── gate_result
            ...
        """
        lines: List[str] = []

        lines.append("GATE DEPENDENCY TREE")
        lines.append("=" * 56)

        for gate in self.gates:
            lines.append(gate)
            deps = self.gate_deps.get(gate, [])
            if not deps:
                lines.append("  (no shared module imports)")
            else:
                for i, dep in enumerate(deps):
                    connector = "└──" if i == len(deps) - 1 else "├──"
                    lines.append(f"  {connector} {dep}")

        # Intra-shared dependencies
        intra = {mod: deps for mod, deps in self.module_deps.items() if deps}
        if intra:
            lines.append("")
            lines.append("SHARED MODULE INTERNAL DEPENDENCIES")
            lines.append("=" * 56)
            for mod in sorted(intra):
                lines.append(mod)
                deps = intra[mod]
                for i, dep in enumerate(deps):
                    connector = "└──" if i == len(deps) - 1 else "├──"
                    lines.append(f"  {connector} {dep}")

        lines.append("")
        lines.append("SUMMARY")
        lines.append("=" * 56)
        lines.append(f"  Gates scanned : {len(self.gates)}")
        lines.append(f"  Shared modules: {len(self.shared_modules)}")

        # Module usage frequency
        usage: Dict[str, int] = defaultdict(int)
        for deps in self.gate_deps.values():
            for d in deps:
                usage[d] += 1
        if usage:
            lines.append("  Module usage (gates that import it):")
            for mod in sorted(usage, key=lambda m: -usage[m]):
                lines.append(f"    {mod:<30} {usage[mod]} gate(s)")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Circular dependency detection
    # ------------------------------------------------------------------

    def find_circular_deps(self) -> List[List[str]]:
        """Detect circular import chains among shared modules.

        Returns a list of cycles.  Each cycle is a list of module names
        that form a loop, e.g. ['a', 'b', 'c', 'a'].

        Gates are excluded from cycle detection because they only import
        shared modules (never the reverse), so they cannot participate in
        a cycle.

        Uses iterative DFS (Johnson's algorithm light — finds all simple
        cycles via repeated DFS with node removal).
        """
        # Build adjacency map restricted to shared modules only
        adj: Dict[str, List[str]] = {}
        for mod in self.shared_modules:
            neighbors = [d for d in self.module_deps.get(mod, []) if d in self.shared_modules]
            adj[mod] = neighbors

        cycles: List[List[str]] = []
        visited: Set[str] = set()

        def _dfs(node: str, path: List[str], on_stack: Set[str]) -> None:
            visited.add(node)
            on_stack.add(node)
            path.append(node)

            for neighbor in adj.get(node, []):
                if neighbor not in visited:
                    _dfs(neighbor, path, on_stack)
                elif neighbor in on_stack:
                    # Found a cycle — extract the loop portion
                    idx = path.index(neighbor)
                    cycle = path[idx:] + [neighbor]
                    # Deduplicate: normalise by rotating to smallest element
                    min_node = min(cycle[:-1])
                    min_idx = cycle.index(min_node)
                    normalised = cycle[min_idx:-1] + cycle[:min_idx] + [min_node]
                    if normalised not in cycles:
                        cycles.append(normalised)

            path.pop()
            on_stack.discard(node)

        for mod in self.shared_modules:
            if mod not in visited:
                _dfs(mod, [], set())

        return cycles

    # ------------------------------------------------------------------
    # Impact analysis
    # ------------------------------------------------------------------

    def get_impact_analysis(self, module_name: str) -> Dict:
        """Show which gates (and shared modules) break if *module_name* changes.

        The analysis is transitive: if module A depends on module B, and
        gate G depends on A, then changing B will indirectly break G.

        Returns a dict with keys:
          - "module"          : str  — the queried module name
          - "exists"          : bool — whether the module is known
          - "direct_gates"    : list[str] — gates that directly import this module
          - "indirect_gates"  : list[str] — gates impacted via transitive shared deps
          - "all_gates"       : list[str] — union of direct + indirect (sorted)
          - "direct_modules"  : list[str] — shared modules that directly import this
          - "transitive_modules": list[str] — all shared modules reachable upward
          - "impact_score"    : int  — total number of gates affected
          - "risk_level"      : str  — "critical" / "high" / "medium" / "low"
        """
        exists = module_name in self.shared_modules

        # -- BFS upward through module_deps to find all modules that
        #    (transitively) depend on module_name ---------------------------
        reverse_module_adj: Dict[str, List[str]] = defaultdict(list)
        for mod, deps in self.module_deps.items():
            for dep in deps:
                reverse_module_adj[dep].append(mod)

        transitive_mods: Set[str] = set()
        queue: deque = deque([module_name])
        seen: Set[str] = {module_name}
        while queue:
            current = queue.popleft()
            for upstream in reverse_module_adj.get(current, []):
                if upstream not in seen:
                    seen.add(upstream)
                    transitive_mods.add(upstream)
                    queue.append(upstream)

        direct_modules = sorted(reverse_module_adj.get(module_name, []))

        # -- Gates that directly import the module -------------------------
        direct_gates: List[str] = []
        for gate, deps in self.gate_deps.items():
            if module_name in deps:
                direct_gates.append(gate)
        direct_gates.sort()

        # -- Gates that import any transitively-dependent module -----------
        indirect_gates: List[str] = []
        for gate, deps in self.gate_deps.items():
            if gate not in direct_gates:
                for dep in deps:
                    if dep in transitive_mods:
                        indirect_gates.append(gate)
                        break
        indirect_gates.sort()

        all_gates = sorted(set(direct_gates + indirect_gates))
        impact_score = len(all_gates)

        total_gates = len(self.gates)
        if total_gates > 0:
            ratio = impact_score / total_gates
        else:
            ratio = 0.0

        if ratio >= 0.75:
            risk_level = "critical"
        elif ratio >= 0.4:
            risk_level = "high"
        elif ratio >= 0.15:
            risk_level = "medium"
        else:
            risk_level = "low"

        return {
            "module": module_name,
            "exists": exists,
            "direct_gates": direct_gates,
            "indirect_gates": indirect_gates,
            "all_gates": all_gates,
            "direct_modules": direct_modules,
            "transitive_modules": sorted(transitive_mods),
            "impact_score": impact_score,
            "risk_level": risk_level,
        }

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"GateGraph(gates={len(self.gates)}, "
            f"shared_modules={len(self.shared_modules)})"
        )


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------

def build_graph(
    gates_dir: Optional[str] = None,
    shared_dir: Optional[str] = None,
) -> GateGraph:
    """Scan gates/ and shared/ directories and return a GateGraph.

    Parameters
    ----------
    gates_dir : str, optional
        Override the default gates directory path.
    shared_dir : str, optional
        Override the default shared directory path.
    """
    gates_dir = gates_dir or GATES_DIR
    shared_dir = shared_dir or SHARED_DIR

    # -- Discover shared modules -------------------------------------------
    shared_modules: List[str] = []
    module_deps: Dict[str, List[str]] = {}

    if os.path.isdir(shared_dir):
        for fname in sorted(os.listdir(shared_dir)):
            if not fname.endswith(".py") or fname == "__init__.py":
                continue
            label = _module_label(fname)
            shared_modules.append(label)
            fpath = os.path.join(shared_dir, fname)
            module_deps[label] = _parse_shared_imports(fpath)

    # -- Discover and parse gate files -------------------------------------
    gate_deps: Dict[str, List[str]] = {}

    if os.path.isdir(gates_dir):
        for fname in sorted(os.listdir(gates_dir)):
            if not fname.endswith(".py") or fname in ("__init__.py",):
                continue
            if not fname.startswith("gate_"):
                continue
            label = _gate_label(fname)
            fpath = os.path.join(gates_dir, fname)
            gate_deps[label] = _parse_shared_imports(fpath)

    return GateGraph(
        gate_deps=gate_deps,
        module_deps=module_deps,
        shared_modules=shared_modules,
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    g = build_graph()

    if len(sys.argv) >= 2:
        cmd = sys.argv[1]

        if cmd == "ascii":
            print(g.render_ascii())

        elif cmd == "cycles":
            cycles = g.find_circular_deps()
            if cycles:
                print(f"Found {len(cycles)} circular dependency chain(s):")
                for i, cycle in enumerate(cycles, 1):
                    print(f"  {i}. {' -> '.join(cycle)}")
            else:
                print("No circular dependencies detected.")

        elif cmd == "impact" and len(sys.argv) >= 3:
            module = sys.argv[2]
            result = g.get_impact_analysis(module)
            print(f"Impact analysis for shared module: '{module}'")
            print(f"  Exists in graph : {result['exists']}")
            print(f"  Risk level      : {result['risk_level'].upper()}")
            print(f"  Impact score    : {result['impact_score']} gate(s) affected")
            if result["direct_gates"]:
                print(f"  Direct gates ({len(result['direct_gates'])}):")
                for g_name in result["direct_gates"]:
                    print(f"    - {g_name}")
            if result["indirect_gates"]:
                print(f"  Indirect gates ({len(result['indirect_gates'])}):")
                for g_name in result["indirect_gates"]:
                    print(f"    - {g_name}")
            if result["direct_modules"]:
                print(f"  Shared modules that import '{module}' directly:")
                for m in result["direct_modules"]:
                    print(f"    - {m}")
            if result["transitive_modules"]:
                print(f"  Transitive shared module dependents:")
                for m in result["transitive_modules"]:
                    print(f"    - {m}")

        elif cmd == "help":
            print("Usage: python gate_graph.py [ascii | cycles | impact <module> | help]")

        else:
            print(f"Unknown command '{cmd}'. Use: ascii | cycles | impact <module> | help",
                  file=sys.stderr)
            sys.exit(1)

    else:
        # Default: print ASCII tree
        print(g.render_ascii())
        print()
        cycles = g.find_circular_deps()
        if cycles:
            print(f"WARNING: {len(cycles)} circular dependency chain(s) detected:")
            for cycle in cycles:
                print(f"  {' -> '.join(cycle)}")
        else:
            print("No circular dependencies detected.")
