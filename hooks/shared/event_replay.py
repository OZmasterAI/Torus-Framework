"""Event Replay — shared/event_replay.py

Reads hook event logs from .capture_queue.jsonl and replays them through the
enforcer gate pipeline for regression testing and gate debugging.

Typical usage
-------------
    from shared.event_replay import filter_events, replay_event, diff_results

    # Query events that were originally blocked by gate_01
    events = filter_events(gate_name="gate_01_read_before_edit", blocked=True)

    # Replay a single event through all gates and compare
    original_result = events[0]["_replay_meta"]   # captured original outcome
    replayed = replay_event(events[0])
    diff = diff_results(original_result, replayed)
    if diff["changed"]:
        print("Gate behaviour changed after modification!")
        for gate, change in diff["gate_changes"].items():
            print(f"  {gate}: {change['before']} -> {change['after']}")

Capture queue format (one JSON object per line)
-----------------------------------------------
Each entry in .capture_queue.jsonl is an observation dict with keys:
    document    — human-readable summary string
    metadata    — flat dict of event metadata including tool_name, session_id,
                  exit_code, command_hash, timestamp, etc.
    id          — observation ID (obs_<hash>)

To replay an event the module reconstructs a minimal enforcer-compatible input
dict from the captured metadata and re-runs every applicable gate against it,
capturing each gate's GateResult without side-effects.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import time
from typing import Any

# Ensure hooks/ is on the path so shared.* and gates.* are importable
_HOOKS_DIR = os.path.join(os.path.expanduser("~"), ".claude", "hooks")
if _HOOKS_DIR not in sys.path:
    sys.path.insert(0, _HOOKS_DIR)

from shared.gate_result import GateResult
from shared.state import default_state

# ── Paths ─────────────────────────────────────────────────────────────────────

CAPTURE_QUEUE_PATH = os.path.join(_HOOKS_DIR, ".capture_queue.jsonl")

# Canonical gate list (from shared/gate_registry.py)
from shared.gate_registry import GATE_MODULES as _GATE_MODULES

# Tools that the enforcer never gates (mirrors enforcer.ALWAYS_ALLOWED_TOOLS)
_ALWAYS_ALLOWED_TOOLS = {
    "Read", "Glob", "Grep", "WebFetch", "WebSearch",
    "AskUserQuestion", "EnterPlanMode", "ExitPlanMode",
    "TaskCreate", "TaskUpdate", "TaskList", "TaskGet",
    "TeamCreate", "TeamDelete", "SendMessage", "TaskStop",
}

_MEMORY_TOOL_PREFIXES = ("mcp__memory__", "mcp_memory_")

# Tool-scoped gate dispatch (mirrors enforcer.GATE_TOOL_MAP)
_GATE_TOOL_MAP: dict[str, set[str] | None] = {
    "gates.gate_01_read_before_edit": {"Edit", "Write", "NotebookEdit"},
    "gates.gate_02_no_destroy":       {"Bash"},
    "gates.gate_03_test_before_deploy": {"Bash"},
    "gates.gate_04_memory_first":     {"Edit", "Write", "NotebookEdit", "Task"},
    "gates.gate_05_proof_before_fixed": {"Edit", "Write", "NotebookEdit"},
    "gates.gate_06_save_fix":         {"Edit", "Write", "Task", "Bash", "NotebookEdit"},
    "gates.gate_07_critical_file_guard": {"Edit", "Write", "NotebookEdit"},
    "gates.gate_09_strategy_ban":     {"Edit", "Write", "NotebookEdit"},
    "gates.gate_10_model_enforcement": {"Task"},
    "gates.gate_11_rate_limit":       None,  # Universal
    "gates.gate_13_workspace_isolation": {"Edit", "Write", "NotebookEdit"},
    "gates.gate_14_confidence_check": {"Edit", "Write", "NotebookEdit"},
    "gates.gate_15_causal_chain":     {"Edit", "Write", "NotebookEdit"},
    "gates.gate_16_code_quality":     {"Edit", "Write", "NotebookEdit"},
    "gates.gate_17_injection_defense": {"WebFetch", "WebSearch"},
}

# Module-level cache so repeated replay calls don't re-import gates
_gate_module_cache: dict[str, Any] = {}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _is_memory_tool(tool_name: str) -> bool:
    return any(tool_name.startswith(p) for p in _MEMORY_TOOL_PREFIXES)


def _is_always_allowed(tool_name: str) -> bool:
    return tool_name in _ALWAYS_ALLOWED_TOOLS or _is_memory_tool(tool_name)


def _load_gate(module_name: str):
    """Import and cache a gate module. Returns None if import fails."""
    if module_name in _gate_module_cache:
        return _gate_module_cache[module_name]
    try:
        mod = importlib.import_module(module_name)
        if hasattr(mod, "check"):
            _gate_module_cache[module_name] = mod
            return mod
    except ImportError:
        pass
    _gate_module_cache[module_name] = None  # Cache the miss
    return None


def _gates_for_tool(tool_name: str) -> list:
    """Return loaded gate modules that watch the given tool, in priority order."""
    result = []
    for module_name in _GATE_MODULES:
        mod = _load_gate(module_name)
        if mod is None:
            continue
        watched = _GATE_TOOL_MAP.get(module_name)
        if watched is None or tool_name in watched:
            result.append((module_name, mod))
    return result


def _parse_context(context_str: str) -> dict:
    """Try to parse a context field as JSON.

    The capture queue's context field sometimes holds a raw JSON object
    (e.g. ``{"file_path": "/tmp/foo.py", "file_extension": ".py"}``).
    Returns the parsed dict on success, or an empty dict on failure.
    """
    if not context_str or not context_str.strip().startswith("{"):
        return {}
    try:
        parsed = json.loads(context_str)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass
    return {}


def _extract_tool_input(meta: dict) -> dict:
    """Reconstruct a plausible tool_input dict from capture queue metadata.

    The capture queue stores a flat metadata dict; the original tool_input
    (command, file_path, etc.) is embedded in that metadata.  We reconstruct
    a best-effort tool_input that the gate check() functions can evaluate.

    The context field may be a raw string or a JSON-encoded dict — both
    are handled transparently.
    """
    tool_name = meta.get("tool_name", "")
    tool_input: dict[str, Any] = {}

    raw_context = meta.get("context", "") or ""
    ctx_dict = _parse_context(raw_context)

    # Bash: the command is hashed (command_hash) but the context field may
    # hold a snippet.  Use context if available, fall back to empty string.
    if tool_name == "Bash":
        command = ctx_dict.get("command", raw_context) or meta.get("command_hash", "")
        tool_input["command"] = command

    # Edit / Write / NotebookEdit: context often holds the file path or a JSON
    # object with file_path and related metadata.
    elif tool_name in ("Edit", "Write", "NotebookEdit"):
        # Prefer JSON-parsed file_path, then raw string, then empty
        file_path = (
            ctx_dict.get("file_path", "")
            or ctx_dict.get("notebook_path", "")
            or (raw_context if not ctx_dict else "")
        )
        if tool_name == "NotebookEdit":
            tool_input["notebook_path"] = file_path
        else:
            tool_input["file_path"] = file_path
        tool_input["new_string"] = ""
        tool_input["old_string"] = ""

    # Task: may carry model info in context
    elif tool_name == "Task":
        tool_input["model"] = ctx_dict.get("model", raw_context)

    # WebFetch / WebSearch
    elif tool_name in ("WebFetch", "WebSearch"):
        tool_input["url"] = meta.get("context", "")
        tool_input["query"] = meta.get("context", "")

    return tool_input


def _build_replay_state(session_id: str = "replay") -> dict:
    """Build a clean default state for replay runs.

    Uses default_state() so all gate-required keys are present, then stamps
    a replay-specific session_id so gate side-effects don't pollute live state.
    """
    state = default_state()
    state["_session_id"] = session_id
    state["session_start"] = time.time()
    # Memory was queried — avoids gate_04 false positives during replay
    state["memory_last_queried"] = time.time()
    return state


# ── Public API ────────────────────────────────────────────────────────────────

def load_events(path: str = CAPTURE_QUEUE_PATH) -> list[dict]:
    """Load all events from the capture queue JSONL file.

    Returns a list of raw entry dicts (each has ``document``, ``metadata``,
    and ``id`` keys).  Returns an empty list if the file does not exist or
    cannot be parsed.

    Args:
        path: Absolute path to the JSONL file.  Defaults to the live
              capture queue at ~/.claude/hooks/.capture_queue.jsonl.
    """
    events: list[dict] = []
    if not os.path.isfile(path):
        return events
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if isinstance(entry, dict):
                        events.append(entry)
                except json.JSONDecodeError as exc:
                    # Skip malformed lines; don't raise
                    sys.stderr.write(
                        f"[event_replay] Skipping malformed line {lineno}: {exc}\n"
                    )
    except (IOError, OSError) as exc:
        sys.stderr.write(f"[event_replay] Cannot open capture queue: {exc}\n")
    return events


def filter_events(
    gate_name: str | None = None,
    tool_name: str | None = None,
    blocked: bool | None = None,
    path: str = CAPTURE_QUEUE_PATH,
) -> list[dict]:
    """Query events from the capture queue with optional filters.

    Each returned entry is the raw JSONL dict augmented with a ``_replay_meta``
    key that summarises the original event for diff_results() comparison.

    Args:
        gate_name: Short gate identifier to filter by (e.g. ``"gate_01_read_before_edit"``).
                   Matched as a substring of the ``gate`` metadata field.
                   None means no gate filter.
        tool_name: Exact tool name to filter by (e.g. ``"Edit"``, ``"Bash"``).
                   None means no tool filter.
        blocked:   If True, return only events whose exit_code metadata indicates
                   a block (exit_code == "2").  If False, return only non-blocked
                   events.  None means return all.
        path:      Path to the JSONL capture queue.  Defaults to the live queue.

    Returns:
        List of matching event dicts, each with an additional ``_replay_meta``
        key of the form::

            {
                "tool_name": str,
                "session_id": str,
                "timestamp": str,
                "exit_code": str,
                "originally_blocked": bool,
                "gate": str,           # from metadata if present
                "sentiment": str,
            }
    """
    all_events = load_events(path)
    results: list[dict] = []

    for entry in all_events:
        meta = entry.get("metadata", {})
        ev_tool = meta.get("tool_name", "")
        ev_exit_code = str(meta.get("exit_code", ""))
        ev_gate = meta.get("gate", "")  # may be absent for UserPrompt observations
        ev_blocked = ev_exit_code == "2"

        # Apply filters
        if tool_name is not None and ev_tool != tool_name:
            continue
        if gate_name is not None and gate_name not in ev_gate:
            continue
        if blocked is not None and ev_blocked != blocked:
            continue

        # Attach replay_meta to support diff_results()
        annotated = dict(entry)
        annotated["_replay_meta"] = {
            "tool_name":          ev_tool,
            "session_id":         meta.get("session_id", ""),
            "timestamp":          meta.get("timestamp", ""),
            "exit_code":          ev_exit_code,
            "originally_blocked": ev_blocked,
            "gate":               ev_gate,
            "sentiment":          meta.get("sentiment", ""),
        }
        results.append(annotated)

    return results


def replay_event(
    event_dict: dict,
    state_overrides: dict | None = None,
    dry_run: bool = True,
) -> dict:
    """Re-run all applicable gates against a captured event.

    Reconstructs the tool_name and tool_input from the event's metadata,
    builds a fresh default state, and calls each gate's check() function.
    Does NOT call enforcer.handle_pre_tool_use() because that function has
    side effects (sys.exit, state saves, audit writes).  Instead gates are
    called directly in a controlled sandbox.

    Args:
        event_dict:      A single event dict as returned by filter_events() or
                         load_events().  Must contain a ``metadata`` key.
        state_overrides: Optional dict of state keys to overlay on the default
                         state before running gates.  Useful for testing
                         specific state conditions.
        dry_run:         If True (default), gate side-effects that modify state
                         in-place are isolated to the replay state copy and
                         never saved to disk.  Set to False only when you
                         explicitly want state mutations to persist.

    Returns:
        A dict describing the replay result::

            {
                "tool_name":  str,
                "tool_input": dict,
                "gates_run":  int,
                "skipped_always_allowed": bool,
                "per_gate": {
                    "<gate_short_name>": {
                        "blocked":    bool,
                        "message":    str,
                        "severity":   str,
                        "escalation": str,
                        "duration_ms": float,
                        "error":      str | None,   # set if gate raised
                    },
                    ...
                },
                "final_outcome": "blocked" | "passed" | "skipped",
                "first_blocking_gate": str | None,
                "replay_state": dict,   # the state dict after all gates ran
                "timestamp": float,     # unix timestamp of the replay
            }
    """
    meta = event_dict.get("metadata", {})
    tool_name = meta.get("tool_name", "")
    tool_input = _extract_tool_input(meta)

    # Merge state
    state = _build_replay_state(session_id=f"replay_{meta.get('session_id', 'unknown')}")
    if state_overrides:
        state.update(state_overrides)

    result: dict = {
        "tool_name":              tool_name,
        "tool_input":             tool_input,
        "gates_run":              0,
        "skipped_always_allowed": False,
        "per_gate":               {},
        "final_outcome":          "passed",
        "first_blocking_gate":    None,
        "replay_state":           state,
        "timestamp":              time.time(),
    }

    if not tool_name:
        result["final_outcome"] = "skipped"
        result["error"] = "Empty tool_name in event metadata"
        return result

    if _is_always_allowed(tool_name):
        result["skipped_always_allowed"] = True
        result["final_outcome"] = "skipped"
        return result

    gates = _gates_for_tool(tool_name)
    result["gates_run"] = len(gates)

    for module_name, gate_mod in gates:
        gate_short = module_name.split(".")[-1]
        gate_result: dict = {
            "blocked":    False,
            "message":    "",
            "severity":   "info",
            "escalation": "allow",
            "duration_ms": 0.0,
            "error":       None,
        }
        try:
            t0 = time.time()
            gr: GateResult = gate_mod.check(
                tool_name, tool_input, state, event_type="PreToolUse"
            )
            elapsed_ms = (time.time() - t0) * 1000

            gate_result["blocked"]     = gr.blocked
            gate_result["message"]     = gr.message
            gate_result["severity"]    = gr.severity
            gate_result["escalation"]  = gr.escalation
            gate_result["duration_ms"] = round(elapsed_ms, 3)

            if gr.blocked and result["first_blocking_gate"] is None:
                result["first_blocking_gate"] = gate_short
                result["final_outcome"] = "blocked"

        except Exception as exc:
            elapsed_ms = (time.time() - t0) * 1000
            gate_result["error"]       = str(exc)
            gate_result["duration_ms"] = round(elapsed_ms, 3)

        result["per_gate"][gate_short] = gate_result

    # Omit the live state reference when dry_run=True — caller doesn't need it
    # (the state is still available as result["replay_state"] for inspection)
    if dry_run:
        # Strip mutable state so callers can't accidentally persist it
        # We keep a deep copy; no disk writes happen.
        result["replay_state"] = dict(state)

    return result


def diff_results(original: dict, replayed: dict) -> dict:
    """Compare an original gate outcome with a fresh replay result.

    Identifies gates whose behaviour changed between the captured original and
    the replayed run.  Useful for regression testing after modifying a gate.

    Args:
        original: The ``_replay_meta`` dict from a filter_events() entry, *or*
                  a previous replay_event() result.  The function looks for
                  ``per_gate`` (replay dict) or falls back to the flat
                  ``_replay_meta`` structure (observation metadata).
        replayed: The dict returned by replay_event().

    Returns:
        A dict::

            {
                "changed":       bool,        # True if any gate changed outcome
                "gate_changes":  {
                    "<gate>": {
                        "before": "blocked" | "passed" | "unknown",
                        "after":  "blocked" | "passed" | "error",
                    },
                    ...
                },
                "new_blocks":    list[str],   # gates that now block but didn't before
                "new_passes":    list[str],   # gates that now pass but blocked before
                "summary":       str,
                "original_outcome": str,
                "replayed_outcome": str,
            }
    """
    gate_changes: dict[str, dict] = {}
    new_blocks: list[str] = []
    new_passes: list[str] = []

    replayed_per_gate: dict = replayed.get("per_gate", {})
    replayed_outcome: str = replayed.get("final_outcome", "unknown")

    # Determine original outcome — support both _replay_meta dicts and
    # previously returned replay_event() dicts.
    if "per_gate" in original:
        # original is itself a replay_event() result
        original_per_gate: dict = original.get("per_gate", {})
        original_outcome: str = original.get("final_outcome", "unknown")

        # Compare gate-by-gate
        all_gates = set(original_per_gate) | set(replayed_per_gate)
        for gate in sorted(all_gates):
            orig_gate = original_per_gate.get(gate, {})
            rep_gate  = replayed_per_gate.get(gate, {})

            before = "blocked" if orig_gate.get("blocked") else "passed"
            if "error" in orig_gate and orig_gate["error"]:
                before = "error"
            if gate not in original_per_gate:
                before = "unknown"

            after = "blocked" if rep_gate.get("blocked") else "passed"
            if "error" in rep_gate and rep_gate["error"]:
                after = "error"
            if gate not in replayed_per_gate:
                after = "unknown"

            if before != after:
                gate_changes[gate] = {"before": before, "after": after}
                if after == "blocked":
                    new_blocks.append(gate)
                elif before == "blocked":
                    new_passes.append(gate)

    else:
        # original is a _replay_meta dict (flat observation metadata).
        # We only have the top-level originally_blocked flag.
        original_outcome = (
            "blocked" if original.get("originally_blocked") else "passed"
        )
        # We cannot do per-gate comparison — only top-level diff
        if original_outcome != replayed_outcome:
            gate_changes["<overall>"] = {
                "before": original_outcome,
                "after":  replayed_outcome,
            }
            if replayed_outcome == "blocked":
                new_blocks.append("<overall>")
            elif original_outcome == "blocked":
                new_passes.append("<overall>")

    changed = bool(gate_changes)

    # Build a human-readable summary
    if not changed:
        summary = (
            f"No behaviour change. Both outcomes: {replayed_outcome}."
        )
    else:
        parts: list[str] = []
        if new_blocks:
            parts.append(f"NEW BLOCKS: {', '.join(new_blocks)}")
        if new_passes:
            parts.append(f"NEW PASSES: {', '.join(new_passes)}")
        other = [g for g in gate_changes if g not in new_blocks and g not in new_passes]
        if other:
            parts.append(f"OTHER CHANGES: {', '.join(other)}")
        summary = " | ".join(parts)

    return {
        "changed":           changed,
        "gate_changes":      gate_changes,
        "new_blocks":        new_blocks,
        "new_passes":        new_passes,
        "summary":           summary,
        "original_outcome":  original_outcome,
        "replayed_outcome":  replayed_outcome,
    }


def replay_all(
    path: str = CAPTURE_QUEUE_PATH,
    gate_name: str | None = None,
    tool_name: str | None = None,
    blocked: bool | None = None,
    state_overrides: dict | None = None,
) -> list[dict]:
    """Replay every matching event and return a list of diff results.

    Convenience wrapper around filter_events() + replay_event() + diff_results().
    Useful for running a regression suite after modifying a gate.

    Args:
        path:            Path to capture queue.
        gate_name:       Optional gate filter (substring match).
        tool_name:       Optional exact tool name filter.
        blocked:         Optional filter on original blocked status.
        state_overrides: Optional state overrides applied to every replay.

    Returns:
        List of dicts, each with keys:
            ``event``, ``replayed``, ``diff`` — corresponding to the original
            event, the replay_event() result, and the diff_results() output.
    """
    events = filter_events(
        gate_name=gate_name,
        tool_name=tool_name,
        blocked=blocked,
        path=path,
    )

    output: list[dict] = []
    for event in events:
        replayed = replay_event(event, state_overrides=state_overrides)
        diff = diff_results(event.get("_replay_meta", {}), replayed)
        output.append({
            "event":    event,
            "replayed": replayed,
            "diff":     diff,
        })
    return output


def summarise_replay(replay_results: list[dict]) -> dict:
    """Aggregate replay_all() output into a human-readable summary dict.

    Args:
        replay_results: List returned by replay_all().

    Returns:
        Dict with keys:
            total, changed, unchanged, new_blocks, new_passes,
            changed_events (list of brief summaries).
    """
    total      = len(replay_results)
    changed    = 0
    unchanged  = 0
    new_blocks : list[str] = []
    new_passes : list[str] = []
    changed_events: list[dict] = []

    for item in replay_results:
        diff = item.get("diff", {})
        event_meta = item.get("event", {}).get("_replay_meta", {})
        if diff.get("changed"):
            changed += 1
            new_blocks.extend(diff.get("new_blocks", []))
            new_passes.extend(diff.get("new_passes", []))
            changed_events.append({
                "timestamp":         event_meta.get("timestamp", ""),
                "tool_name":         event_meta.get("tool_name", ""),
                "original_outcome":  diff.get("original_outcome", ""),
                "replayed_outcome":  diff.get("replayed_outcome", ""),
                "summary":           diff.get("summary", ""),
            })
        else:
            unchanged += 1

    return {
        "total":          total,
        "changed":        changed,
        "unchanged":      unchanged,
        "new_blocks":     list(set(new_blocks)),
        "new_passes":     list(set(new_passes)),
        "changed_events": changed_events,
    }


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Replay captured hook events through the enforcer gate pipeline.",
    )
    parser.add_argument(
        "--gate", default=None,
        help="Filter by gate short name substring (e.g. gate_01_read_before_edit)",
    )
    parser.add_argument(
        "--tool", default=None,
        help="Filter by exact tool name (e.g. Edit, Bash)",
    )
    parser.add_argument(
        "--blocked", action="store_true", default=None,
        help="Only show events that were originally blocked",
    )
    parser.add_argument(
        "--path", default=CAPTURE_QUEUE_PATH,
        help="Path to capture queue JSONL (default: ~/.claude/hooks/.capture_queue.jsonl)",
    )
    parser.add_argument(
        "--limit", type=int, default=20,
        help="Maximum number of events to replay (default: 20)",
    )
    parser.add_argument(
        "--json-out", action="store_true",
        help="Output results as JSON (default: human-readable summary)",
    )

    args = parser.parse_args()

    results = replay_all(
        path=args.path,
        gate_name=args.gate,
        tool_name=args.tool,
        blocked=args.blocked if args.blocked else None,
    )
    results = results[: args.limit]

    if args.json_out:
        print(json.dumps(results, indent=2, default=str))
    else:
        summary = summarise_replay(results)
        print(f"Replayed {summary['total']} events.")
        print(f"  Unchanged: {summary['unchanged']}")
        print(f"  Changed:   {summary['changed']}")
        if summary["new_blocks"]:
            print(f"  New blocks (gates now blocking that didn't): {summary['new_blocks']}")
        if summary["new_passes"]:
            print(f"  New passes (gates no longer blocking):       {summary['new_passes']}")
        if summary["changed_events"]:
            print("\nChanged events:")
            for ev in summary["changed_events"]:
                print(f"  [{ev['timestamp']}] {ev['tool_name']}: "
                      f"{ev['original_outcome']} -> {ev['replayed_outcome']} | {ev['summary']}")
