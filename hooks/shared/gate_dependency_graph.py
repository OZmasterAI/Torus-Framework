"""Gate dependency graph visualization.

Generates mermaid diagrams and conflict reports from the GATE_DEPENDENCIES
dict in enforcer.py. Helps identify:
- State key conflicts between gates (both read-write and write-write)
- Independent gates that can safely run in parallel
- State keys used by the most gates (shared state hotspots)

Usage:
    from shared.gate_dependency_graph import (
        generate_mermaid_diagram,
        find_state_conflicts,
        find_parallel_safe_gates,
        get_state_hotspots,
    )

    print(generate_mermaid_diagram())
    conflicts = find_state_conflicts()
    parallel = find_parallel_safe_gates()
"""

import os
import sys

# Add hooks dir to path
_HOOKS_DIR = os.path.join(os.path.expanduser("~"), ".claude", "hooks")
if _HOOKS_DIR not in sys.path:
    sys.path.insert(0, _HOOKS_DIR)


def _load_dependencies():
    """Load GATE_DEPENDENCIES from enforcer.py."""
    try:
        from enforcer import GATE_DEPENDENCIES
        return GATE_DEPENDENCIES
    except ImportError:
        return {}


def generate_mermaid_diagram():
    """Generate a mermaid flowchart of gate-state dependencies.

    Gates are nodes. State keys are nodes. Arrows show reads/writes.
    """
    deps = _load_dependencies()
    if not deps:
        return "```mermaid\nflowchart LR\n  empty[No dependency data]\n```"

    lines = ["```mermaid", "flowchart LR"]

    # Collect all state keys
    all_keys = set()
    for gate_info in deps.values():
        all_keys.update(gate_info.get("reads", []))
        all_keys.update(gate_info.get("writes", []))

    # Style definitions
    lines.append("  %% Gate nodes")
    for gate_name in sorted(deps.keys()):
        short = gate_name.replace("gate_", "G")
        lines.append(f"  {gate_name}[{short}]")

    lines.append("  %% State key nodes")
    for key in sorted(all_keys):
        safe_id = key.replace(" ", "_")
        lines.append(f"  {safe_id}({key})")

    lines.append("  %% Read edges (dashed)")
    for gate_name, info in sorted(deps.items()):
        for key in info.get("reads", []):
            safe_id = key.replace(" ", "_")
            lines.append(f"  {safe_id} -.-> {gate_name}")

    lines.append("  %% Write edges (solid)")
    for gate_name, info in sorted(deps.items()):
        for key in info.get("writes", []):
            safe_id = key.replace(" ", "_")
            lines.append(f"  {gate_name} --> {safe_id}")

    lines.append("```")
    return "\n".join(lines)


def find_state_conflicts():
    """Find state keys where multiple gates have conflicting access.

    A conflict is when:
    - Two gates write to the same key (write-write conflict)
    - One gate reads a key that another writes (read-write conflict)

    Returns list of dicts: [{key, type, gates}]
    """
    deps = _load_dependencies()
    conflicts = []

    # Build reader/writer maps
    readers = {}   # key -> set of gates
    writers = {}   # key -> set of gates

    for gate_name, info in deps.items():
        for key in info.get("reads", []):
            readers.setdefault(key, set()).add(gate_name)
        for key in info.get("writes", []):
            writers.setdefault(key, set()).add(gate_name)

    # Write-write conflicts
    for key, writing_gates in writers.items():
        if len(writing_gates) > 1:
            conflicts.append({
                "key": key,
                "type": "write-write",
                "gates": sorted(writing_gates),
            })

    # Read-write conflicts (reader != writer)
    for key, reading_gates in readers.items():
        writing_gates = writers.get(key, set())
        if writing_gates:
            cross_gates = reading_gates - writing_gates
            if cross_gates:
                conflicts.append({
                    "key": key,
                    "type": "read-write",
                    "readers": sorted(cross_gates),
                    "writers": sorted(writing_gates),
                    "gates": sorted(cross_gates | writing_gates),
                })

    return conflicts


def find_parallel_safe_gates():
    """Find groups of gates that can safely run in parallel.

    Two gates are parallel-safe if they don't share any state keys
    (no read-write or write-write conflicts between them).

    Returns dict with:
        independent_gates: list of gates with no state dependencies at all
        conflict_pairs: list of (gate_a, gate_b) that must NOT run in parallel
    """
    deps = _load_dependencies()

    # Gates with zero reads and writes are always independent
    independent = []
    for gate_name, info in deps.items():
        if not info.get("reads") and not info.get("writes"):
            independent.append(gate_name)

    # Find conflict pairs (gates that share written keys)
    conflict_pairs = set()
    writers = {}  # key -> set of gates
    all_access = {}  # key -> set of gates (read or write)

    for gate_name, info in deps.items():
        for key in info.get("writes", []):
            writers.setdefault(key, set()).add(gate_name)
            all_access.setdefault(key, set()).add(gate_name)
        for key in info.get("reads", []):
            all_access.setdefault(key, set()).add(gate_name)

    # A conflict exists when a writer and any other accessor share a key
    for key, writing_gates in writers.items():
        accessing_gates = all_access.get(key, set())
        for writer in writing_gates:
            for other in accessing_gates:
                if writer != other:
                    pair = tuple(sorted([writer, other]))
                    conflict_pairs.add(pair)

    return {
        "independent_gates": sorted(independent),
        "conflict_pairs": sorted(conflict_pairs),
        "total_gates": len(deps),
    }


def get_state_hotspots():
    """Find state keys accessed by the most gates.

    Returns list of (key, read_count, write_count, total_gates) sorted by total.
    """
    deps = _load_dependencies()
    key_reads = {}
    key_writes = {}

    for gate_name, info in deps.items():
        for key in info.get("reads", []):
            key_reads[key] = key_reads.get(key, 0) + 1
        for key in info.get("writes", []):
            key_writes[key] = key_writes.get(key, 0) + 1

    all_keys = set(key_reads.keys()) | set(key_writes.keys())
    hotspots = []
    for key in all_keys:
        r = key_reads.get(key, 0)
        w = key_writes.get(key, 0)
        hotspots.append({
            "key": key,
            "read_count": r,
            "write_count": w,
            "total_gates": r + w,
        })

    hotspots.sort(key=lambda x: x["total_gates"], reverse=True)
    return hotspots


def detect_cycles():
    """Detect circular dependencies in the gate graph.

    Uses DFS-based cycle detection on the state-dependency graph.
    A cycle exists when gate A writes key X, gate B reads key X and writes
    key Y, and gate A reads key Y (or longer chains).

    Returns dict with:
        has_cycles  : bool
        cycles      : list[list[str]] — each cycle as a list of gate names
        summary     : str — human-readable summary
    """
    deps = _load_dependencies()
    if not deps:
        return {"has_cycles": False, "cycles": [], "summary": "No dependency data"}

    # Build adjacency: gate_a -> gate_b means gate_a writes a key that gate_b reads
    writers = {}  # key -> set of gates that write it
    readers = {}  # key -> set of gates that read it
    for gate_name, info in deps.items():
        for key in info.get("writes", []):
            writers.setdefault(key, set()).add(gate_name)
        for key in info.get("reads", []):
            readers.setdefault(key, set()).add(gate_name)

    adj = {}  # gate -> set of gates it feeds data to
    for key, w_gates in writers.items():
        r_gates = readers.get(key, set())
        for w in w_gates:
            for r in r_gates:
                if w != r:
                    adj.setdefault(w, set()).add(r)

    # DFS cycle detection
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {g: WHITE for g in deps}
    cycles = []
    path = []

    def dfs(u):
        color[u] = GRAY
        path.append(u)
        for v in adj.get(u, []):
            if v not in color:
                continue
            if color[v] == GRAY:
                # Found cycle: extract from path
                idx = path.index(v)
                cycles.append(list(path[idx:]))
            elif color[v] == WHITE:
                dfs(v)
        path.pop()
        color[u] = BLACK

    for gate in deps:
        if color[gate] == WHITE:
            dfs(gate)

    has_cycles = len(cycles) > 0
    if has_cycles:
        summary = f"{len(cycles)} cycle(s) detected: " + "; ".join(
            " -> ".join(c) + " -> " + c[0] for c in cycles[:5]
        )
    else:
        summary = "No circular dependencies detected"

    return {"has_cycles": has_cycles, "cycles": cycles, "summary": summary}


def recommend_gate_ordering():
    """Recommend optimal gate execution ordering.

    Uses topological sort (Kahn's algorithm) to find a valid ordering
    that respects data dependencies. Gates with no dependencies come first.
    Falls back to alphabetical if the graph has cycles.

    Returns dict with:
        ordering     : list[str] — recommended gate execution order
        has_cycles   : bool — if True, ordering is approximate
        tiers        : list[list[str]] — gates grouped by dependency depth
    """
    deps = _load_dependencies()
    if not deps:
        return {"ordering": [], "has_cycles": False, "tiers": []}

    # Build adjacency: if gate A writes key X and gate B reads key X, then A -> B
    writers = {}
    readers = {}
    for gate_name, info in deps.items():
        for key in info.get("writes", []):
            writers.setdefault(key, set()).add(gate_name)
        for key in info.get("reads", []):
            readers.setdefault(key, set()).add(gate_name)

    adj = {}
    in_degree = {g: 0 for g in deps}
    for key, w_gates in writers.items():
        r_gates = readers.get(key, set())
        for w in w_gates:
            for r in r_gates:
                if w != r:
                    if r not in adj.get(w, set()):
                        adj.setdefault(w, set()).add(r)
                        in_degree[r] = in_degree.get(r, 0) + 1

    # Kahn's algorithm — topological sort with tier tracking
    queue = sorted([g for g, d in in_degree.items() if d == 0])
    ordering = []
    tiers = []

    while queue:
        tiers.append(sorted(queue))
        next_queue = []
        for u in queue:
            ordering.append(u)
            for v in adj.get(u, []):
                in_degree[v] -= 1
                if in_degree[v] == 0:
                    next_queue.append(v)
        queue = sorted(next_queue)

    has_cycles = len(ordering) < len(deps)
    if has_cycles:
        # Add remaining gates (in cycles) at the end
        remaining = sorted(set(deps.keys()) - set(ordering))
        ordering.extend(remaining)
        tiers.append(remaining)

    return {"ordering": ordering, "has_cycles": has_cycles, "tiers": tiers}


def format_dependency_report():
    """Generate a comprehensive dependency analysis report."""
    lines = [
        "Gate Dependency Analysis",
        "=" * 55,
    ]

    # Hotspots
    hotspots = get_state_hotspots()
    if hotspots:
        lines.append("\nState Key Hotspots (most-accessed keys):")
        for h in hotspots[:10]:
            lines.append(
                f"  {h['key']:<40} "
                f"R:{h['read_count']} W:{h['write_count']} "
                f"total:{h['total_gates']}"
            )

    # Conflicts
    conflicts = find_state_conflicts()
    if conflicts:
        lines.append(f"\nState Conflicts ({len(conflicts)}):")
        for c in conflicts:
            lines.append(f"  [{c['type']}] {c['key']}: {', '.join(c['gates'])}")

    # Parallel safety
    parallel = find_parallel_safe_gates()
    lines.append(f"\nParallel Safety:")
    lines.append(f"  Independent gates: {len(parallel['independent_gates'])}")
    lines.append(f"  Conflict pairs: {len(parallel['conflict_pairs'])}")
    if parallel["independent_gates"]:
        for g in parallel["independent_gates"]:
            lines.append(f"    - {g}")

    # Cycle detection
    cycle_info = detect_cycles()
    lines.append(f"\nCycle Detection:")
    lines.append(f"  {cycle_info['summary']}")

    # Recommended ordering
    order_info = recommend_gate_ordering()
    if order_info["ordering"]:
        lines.append(f"\nRecommended Gate Ordering ({len(order_info['tiers'])} tiers):")
        for i, tier in enumerate(order_info["tiers"]):
            lines.append(f"  Tier {i}: {', '.join(tier)}")

    lines.append("=" * 55)
    return "\n".join(lines)
