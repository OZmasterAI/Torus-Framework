#!/usr/bin/env python3
"""Gate fuzzer — adversarial robustness testing for the Torus Framework gate system.

Generates random and adversarial tool_name/tool_input combinations, runs each
gate's check() function with fuzzed inputs, and reports any gate that raises
an unhandled exception. Gates must never crash — they may block or allow,
but they must always return a GateResult.

Usage:
    python fuzz_gates.py [--iterations N] [--seed SEED] [--gate GATE_MODULE]

Output:
    JSON report to stdout with per-gate crash counts, exception details,
    and summary statistics.
"""

import argparse
import importlib
import json
import os
import random
import string
import sys
import time
import traceback

# Ensure hooks directory is on the import path
_HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HOOKS_DIR)

from shared.gate_result import GateResult
from shared.state import default_state

# ---------------------------------------------------------------------------
# Canonical gate list (from shared/gate_registry.py)
# ---------------------------------------------------------------------------
from shared.gate_registry import GATE_MODULES

# ---------------------------------------------------------------------------
# Tool name corpus
# ---------------------------------------------------------------------------
TOOL_NAMES = [
    "Edit", "Write", "Read", "Bash", "Glob", "Grep",
    "NotebookEdit", "WebFetch", "WebSearch",
    "mcp__memory__search_knowledge", "mcp__memory__remember_this",
    "mcp__memory__get_memory", "mcp__memory__record_attempt",
    "mcp__memory__record_outcome", "mcp__memory__query_fix_history",
    "AskUserQuestion", "EnterPlanMode", "ExitPlanMode",
    "TaskCreate", "TaskUpdate", "TaskList",
    "TeamCreate", "TeamDelete", "SendMessage",
]

# ---------------------------------------------------------------------------
# Adversarial string generators
# ---------------------------------------------------------------------------

def _random_printable(rng, min_len=0, max_len=64):
    length = rng.randint(min_len, max_len)
    return "".join(rng.choices(string.printable, k=length))

def _very_long_string(rng):
    length = rng.randint(10_000, 100_000)
    char = rng.choice(string.ascii_letters + string.digits + " \t\n/\\")
    return char * length

def _unicode_string(rng):
    """Mix of scripts, surrogates, RTL marks, combining chars, nulls in unicode."""
    segments = [
        "\u0000\u0001\u0002\u0003",           # control chars / null bytes
        "\ufffd\ufffe\uffff",                  # BOM / replacement char
        "\u202e\u200b\u200f",                  # RTL override, zero-width, RTL mark
        "日本語テスト",                          # Japanese
        "مرحبا بالعالم",                        # Arabic (RTL)
        "Ю Ж Й Ф Ц Ш Щ",                      # Cyrillic
        "𠀀𠀁𠀂𡁑𢀕",                          # CJK ext B (4-byte)
        "\ud800\udfff",                        # Surrogate pair (raw)
        "\U0001f600\U0001f4a9\U0001f525",      # Emoji
        "\t\r\n\r\n\t   \t",                   # Whitespace variants
    ]
    parts = rng.choices(segments, k=rng.randint(1, 5))
    return "".join(parts)

def _null_byte_string(rng):
    payload = _random_printable(rng, 1, 30)
    pos = rng.randint(0, len(payload))
    return payload[:pos] + "\x00" + payload[pos:]

def _path_traversal(rng):
    traversals = [
        "../../../../etc/passwd",
        "..\\..\\..\\windows\\system32\\config\\sam",
        "/etc/shadow",
        "~/.ssh/id_rsa",
        "~/.aws/credentials",
        "/proc/self/environ",
        "file:///etc/hosts",
        "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd",
        "....//....//....//etc/passwd",
        "/dev/sda",
        "/dev/null",
        "\x00/etc/passwd",
        "C:\\Windows\\System32\\drivers\\etc\\hosts",
        "/home/crab/.claude/hooks/../../../etc/passwd",
    ]
    return rng.choice(traversals)

def _nested_object(rng, depth=0):
    if depth >= 5 or rng.random() < 0.3:
        return rng.choice([
            _random_printable(rng),
            rng.randint(-2**31, 2**31),
            rng.random(),
            None,
            True,
            False,
            [],
        ])
    kind = rng.choice(["dict", "list"])
    if kind == "dict":
        return {
            _random_printable(rng, 1, 20): _nested_object(rng, depth + 1)
            for _ in range(rng.randint(0, 4))
        }
    else:
        return [_nested_object(rng, depth + 1) for _ in range(rng.randint(0, 4))]

def _shell_injection(rng):
    payloads = [
        "; rm -rf /",
        "$(rm -rf /)",
        "`rm -rf /`",
        "| cat /etc/passwd",
        "&& DROP TABLE users;",
        "\n\nrm -rf /\n",
        "${IFS}rm${IFS}-rf${IFS}/",
        "'; DROP TABLE users; --",
        "git push --force origin main",
        "git reset --hard HEAD~100",
        "git clean -f -d",
    ]
    return rng.choice(payloads)

def _empty_or_none(rng):
    return rng.choice(["", None, 0, False, [], {}])

def _type_confusion(rng):
    """Wrong type for a field that is expected to be a string."""
    return rng.choice([42, 3.14, True, False, [], {}])

# ---------------------------------------------------------------------------
# Input field generators keyed by likely field names
# ---------------------------------------------------------------------------

_FIELD_GENERATORS = {
    "file_path": lambda rng: rng.choice([
        _random_printable(rng, 1, 200),
        _path_traversal(rng),
        _very_long_string(rng),
        _unicode_string(rng),
        _null_byte_string(rng),
        "",
        None,
        "/home/crab/.claude/hooks/enforcer.py",
        "/etc/passwd",
    ]),
    "notebook_path": lambda rng: rng.choice([
        _random_printable(rng, 1, 200),
        _path_traversal(rng),
        _very_long_string(rng),
        "",
    ]),
    "command": lambda rng: rng.choice([
        _random_printable(rng),
        _shell_injection(rng),
        _very_long_string(rng),
        _unicode_string(rng),
        _null_byte_string(rng),
        "",
        None,
        "pytest tests/",
        "git status",
        "git push --force origin main",
        "rm -rf /tmp/test",
        "DROP TABLE users;",
        "git reset --hard",
        "exec python3 -c 'import os; os.system(\"id\")'",
    ]),
    "old_string": lambda rng: rng.choice([
        _random_printable(rng),
        _very_long_string(rng),
        _unicode_string(rng),
        _null_byte_string(rng),
        "",
    ]),
    "new_string": lambda rng: rng.choice([
        _random_printable(rng),
        _very_long_string(rng),
        _unicode_string(rng),
        _null_byte_string(rng),
        "import pdb; pdb.set_trace()",
        "password = 'supersecret123'",
        "except:",
    ]),
    "content": lambda rng: rng.choice([
        _random_printable(rng),
        _very_long_string(rng),
        _unicode_string(rng),
        "print('debug')\npassword='abc123secret'\nexcept:",
    ]),
    "pattern": lambda rng: _random_printable(rng),
    "query": lambda rng: _random_printable(rng),
}

_ALL_FIELD_NAMES = list(_FIELD_GENERATORS.keys()) + [
    "session_id", "tool_name", "description", "replace_all",
    "limit", "offset", "glob", "path", "cell_number",
]

# Tool-to-likely-fields mapping for semi-realistic inputs
_TOOL_FIELDS = {
    "Edit": ["file_path", "old_string", "new_string", "replace_all"],
    "Write": ["file_path", "content"],
    "Read": ["file_path", "limit", "offset"],
    "Bash": ["command", "description", "run_in_background", "timeout"],
    "Glob": ["pattern", "path"],
    "Grep": ["pattern", "path", "glob", "output_mode"],
    "NotebookEdit": ["notebook_path", "new_source", "cell_number"],
}


def _fuzz_value(rng):
    """Return an arbitrary fuzzed value (any type)."""
    kind = rng.randint(0, 9)
    if kind == 0:
        return _very_long_string(rng)
    elif kind == 1:
        return _unicode_string(rng)
    elif kind == 2:
        return _null_byte_string(rng)
    elif kind == 3:
        return _path_traversal(rng)
    elif kind == 4:
        return _nested_object(rng)
    elif kind == 5:
        return _shell_injection(rng)
    elif kind == 6:
        return _empty_or_none(rng)
    elif kind == 7:
        return _random_printable(rng)
    elif kind == 8:
        return rng.randint(-2**63, 2**63)
    else:
        return None


def generate_tool_input(rng, tool_name):
    """Generate a fuzzed tool_input dict for the given tool_name."""
    strategy = rng.randint(0, 5)

    if strategy == 0:
        # Completely empty
        return {}

    elif strategy == 1:
        # None itself (not a dict)
        return None

    elif strategy == 2:
        # Completely random keys and values — no relation to real fields
        return {
            _random_printable(rng, 1, 20): _fuzz_value(rng)
            for _ in range(rng.randint(0, 10))
        }

    elif strategy == 3:
        # Realistic field names with adversarial values
        fields = _TOOL_FIELDS.get(tool_name, list(_FIELD_GENERATORS.keys()))
        result = {}
        chosen = rng.sample(fields, k=min(rng.randint(1, len(fields)), len(fields)))
        for field in chosen:
            gen = _FIELD_GENERATORS.get(field)
            result[field] = gen(rng) if gen else _fuzz_value(rng)
        return result

    elif strategy == 4:
        # Mix of real and garbage keys
        result = {}
        n_real = rng.randint(0, 3)
        n_junk = rng.randint(0, 5)
        real_fields = list(_FIELD_GENERATORS.keys())
        for f in rng.sample(real_fields, k=min(n_real, len(real_fields))):
            gen = _FIELD_GENERATORS.get(f)
            result[f] = gen(rng) if gen else _fuzz_value(rng)
        for _ in range(n_junk):
            # junk keys must be strings; coerce to avoid unhashable type errors
            try:
                k = str(_fuzz_value(rng))[:100]
            except Exception:
                k = "junk"
            result[k] = _fuzz_value(rng)
        return result

    else:
        # Deeply nested adversarial object
        return _nested_object(rng, depth=0)


def generate_event_type(rng):
    return rng.choice([
        "PreToolUse", "PostToolUse", "SessionStart", "SessionEnd",
        "", None, "INVALID", _random_printable(rng, 1, 30),
    ])


def generate_state(rng):
    """Return a fuzzed state dict — mostly valid but with random mutations."""
    state = default_state()
    strategy = rng.randint(0, 3)

    if strategy == 0:
        # Fully valid default state
        return state

    elif strategy == 1:
        # Valid state but some fields replaced with adversarial values
        fields_to_corrupt = rng.sample(list(state.keys()), k=rng.randint(1, min(5, len(state))))
        for f in fields_to_corrupt:
            state[f] = _fuzz_value(rng)
        return state

    elif strategy == 2:
        # Empty dict
        return {}

    else:
        # Completely random dict
        return {
            _random_printable(rng, 1, 20): _fuzz_value(rng)
            for _ in range(rng.randint(0, 20))
        }


# ---------------------------------------------------------------------------
# Fuzzer core
# ---------------------------------------------------------------------------

class GateCrash:
    """Records a single crash event."""

    def __init__(self, iteration, tool_name, tool_input, state,
                 event_type, exc_type, exc_msg, tb):
        self.iteration = iteration
        self.tool_name = tool_name
        self.tool_input = tool_input
        self.state = state
        self.event_type = event_type
        self.exc_type = exc_type
        self.exc_msg = exc_msg
        self.traceback = tb

    def to_dict(self):
        def _safe_repr(v):
            try:
                s = repr(v)
                return s[:500] if len(s) > 500 else s
            except Exception:
                return "<unrepresentable>"

        return {
            "iteration": self.iteration,
            "tool_name": self.tool_name,
            "tool_input": _safe_repr(self.tool_input),
            "state_keys": (
                list(self.state.keys())
                if isinstance(self.state, dict)
                else _safe_repr(self.state)
            ),
            "event_type": self.event_type,
            "exception_type": self.exc_type,
            "exception_message": self.exc_msg,
            "traceback": self.traceback,
        }


def fuzz_gate(module_name, iterations, rng):
    """Fuzz a single gate module for `iterations` rounds.

    Returns:
        (crashes: list[GateCrash], report: dict)
    """
    try:
        module = importlib.import_module(module_name)
    except Exception as e:
        return [], {
            "module": module_name,
            "load_error": str(e),
            "skipped": True,
        }

    if not hasattr(module, "check"):
        return [], {
            "module": module_name,
            "load_error": "No check() function found",
            "skipped": True,
        }

    gate_check = module.check
    crashes = []
    bad_returns = []
    counts = {"pass": 0, "block": 0, "crash": 0, "bad_return": 0}

    for i in range(iterations):
        # Generate fuzzed inputs
        tool_name = rng.choice(TOOL_NAMES + [
            _random_printable(rng, 1, 40),
            "",
            None,
        ])
        tool_input = generate_tool_input(rng, tool_name)
        state = generate_state(rng)
        event_type = generate_event_type(rng)

        try:
            result = gate_check(tool_name, tool_input, state, event_type)
        except Exception:
            tb = traceback.format_exc()
            exc_lines = tb.strip().splitlines()
            exc_type = exc_lines[-1].split(":")[0] if exc_lines else "Unknown"
            exc_msg = exc_lines[-1] if exc_lines else ""
            crashes.append(GateCrash(
                iteration=i,
                tool_name=tool_name,
                tool_input=tool_input,
                state=state,
                event_type=event_type,
                exc_type=exc_type,
                exc_msg=exc_msg,
                tb=tb,
            ))
            counts["crash"] += 1
            continue

        # Validate return type
        if not isinstance(result, GateResult):
            bad_returns.append({
                "iteration": i,
                "tool_name": tool_name,
                "event_type": event_type,
                "returned_type": type(result).__name__,
                "returned_value": repr(result)[:200],
            })
            counts["bad_return"] += 1
            continue

        if result.blocked:
            counts["block"] += 1
        else:
            counts["pass"] += 1

    gate_name = getattr(module, "GATE_NAME", module_name)
    report = {
        "module": module_name,
        "gate_name": gate_name,
        "iterations": iterations,
        "counts": counts,
        "crashed": len(crashes) > 0,
        "crashes": [c.to_dict() for c in crashes],
        "bad_returns": bad_returns,
        "skipped": False,
    }
    return crashes, report


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Fuzz the Torus Framework gate check() functions for crash resilience. "
            "Outputs a JSON report to stdout. Exits 1 if any gate crashed, 0 otherwise."
        )
    )
    parser.add_argument(
        "--iterations", "-n", type=int, default=500,
        help="Number of fuzz iterations per gate (default: 500)"
    )
    parser.add_argument(
        "--seed", "-s", type=int, default=None,
        help="Random seed for reproducibility (default: random)"
    )
    parser.add_argument(
        "--gate", "-g", type=str, default=None,
        help="Fuzz a single gate module only (e.g. gates.gate_02_no_destroy)"
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true",
        help="Suppress per-gate progress to stderr"
    )
    args = parser.parse_args()

    seed = args.seed if args.seed is not None else random.randint(0, 2**32 - 1)
    rng = random.Random(seed)
    gates_to_fuzz = [args.gate] if args.gate else GATE_MODULES

    started_at = time.time()
    all_reports = []
    total_crashes = 0
    total_bad_returns = 0
    crashed_gates = []

    for module_name in gates_to_fuzz:
        if not args.quiet:
            print(f"[fuzz] {module_name} ({args.iterations} iterations)...", file=sys.stderr)

        crashes, report = fuzz_gate(module_name, args.iterations, rng)
        all_reports.append(report)
        total_crashes += len(crashes)
        total_bad_returns += len(report.get("bad_returns", []))

        if crashes:
            crashed_gates.append(module_name)
            if not args.quiet:
                first = crashes[0]
                print(
                    f"  !! CRASHED {len(crashes)}x — "
                    f"first: {first.exc_type}: {first.exc_msg[:80]}",
                    file=sys.stderr,
                )
        elif not args.quiet:
            c = report.get("counts", {})
            print(
                f"  ok  pass={c.get('pass', 0)} block={c.get('block', 0)}",
                file=sys.stderr,
            )

    elapsed = time.time() - started_at

    summary = {
        "fuzz_run": {
            "seed": seed,
            "iterations_per_gate": args.iterations,
            "gates_fuzzed": len(gates_to_fuzz),
            "total_iterations": args.iterations * len(gates_to_fuzz),
            "elapsed_seconds": round(elapsed, 3),
            "total_crashes": total_crashes,
            "total_bad_returns": total_bad_returns,
            "crashed_gates": crashed_gates,
            "all_gates_resilient": len(crashed_gates) == 0,
        },
        "gates": all_reports,
    }

    print(json.dumps(summary, indent=2))

    # Exit non-zero if any gate crashed — useful in CI pipelines
    sys.exit(1 if crashed_gates else 0)


if __name__ == "__main__":
    main()
