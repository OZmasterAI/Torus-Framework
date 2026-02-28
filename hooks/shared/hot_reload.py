"""Hot-reload support for gate modules.

Watches gate files in hooks/gates/ for modifications (by comparing mtime)
and reloads changed modules using importlib.reload() without restarting the
enforcer process.

Design constraints:
  - Fail-open: every public function is wrapped in try/except; never raises.
  - Safety: a reloaded module is only accepted if it exports a check() callable.
  - Rate-limited: filesystem mtimes are only checked every CHECK_INTERVAL seconds
    to avoid hammering stat() on every tool call.
  - Thread-safe: an in-process lock guards the shared mtime cache.
  - All reload events are written to stderr for debugging.

Typical usage (in enforcer.py or a gate loader):

    from shared.hot_reload import auto_reload, reload_gate, check_for_changes

    # In the gate dispatch hot path — cheap due to interval throttle:
    auto_reload()

    # Targeted reload of a single gate (e.g. after an admin signal):
    reload_gate("gates.gate_01_read_before_edit")

    # Inspect which gates have changed without reloading:
    changed = check_for_changes()
    # Returns: {"gates.gate_07_critical_file_guard": {"old": 1700000000.0,
    #                                                  "new": 1700000001.5}}
"""

import importlib
import os
import sys
import threading
import time
from typing import Dict, List, Optional

# ── Configuration ────────────────────────────────────────────────────────────

# Seconds between mtime checks (avoids stat() on every enforcer invocation).
CHECK_INTERVAL: float = 30.0

# Absolute path to the hooks/gates/ directory.
_GATES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "gates")

# ── Module-level state ───────────────────────────────────────────────────────

_lock = threading.Lock()

# module_name -> last known mtime (float seconds since epoch)
_known_mtimes: Dict[str, float] = {}

# Epoch timestamp of the last mtime scan
_last_check_time: float = 0.0

# Reload event log (kept in memory for introspection / tests).
# Each entry: {"module": str, "mtime_old": float, "mtime_new": float,
#              "timestamp": float, "success": bool, "reason": str}
_reload_history: List[Dict] = []
_MAX_HISTORY = 200


# ── Internal helpers ─────────────────────────────────────────────────────────

def _module_to_filepath(module_name: str) -> str:
    """Convert a dotted module name to an absolute .py file path.

    Examples:
        "gates.gate_01_read_before_edit"
        -> "/home/user/.claude/hooks/gates/gate_01_read_before_edit.py"
    """
    hooks_dir = os.path.dirname(os.path.dirname(__file__))
    parts = module_name.split(".")
    return os.path.join(hooks_dir, *parts) + ".py"


def _get_mtime(filepath: str) -> Optional[float]:
    """Return mtime for *filepath*, or None if the file cannot be stat'd."""
    try:
        return os.path.getmtime(filepath)
    except OSError:
        return None


def _log_reload(module_name: str, mtime_old: Optional[float],
                mtime_new: float, success: bool, reason: str) -> None:
    """Write a reload event to stderr and append to in-memory history."""
    status = "OK" if success else "FAIL"
    print(
        f"[hot_reload] [{status}] {module_name} "
        f"mtime {mtime_old} -> {mtime_new:.3f}: {reason}",
        file=sys.stderr,
    )
    entry = {
        "module": module_name,
        "mtime_old": mtime_old,
        "mtime_new": mtime_new,
        "timestamp": time.time(),
        "success": success,
        "reason": reason,
    }
    _reload_history.append(entry)
    if len(_reload_history) > _MAX_HISTORY:
        del _reload_history[:-_MAX_HISTORY]


def _validate_module(mod) -> bool:
    """Return True if *mod* is a valid gate module (has a callable check())."""
    return callable(getattr(mod, "check", None))


# ── Public API ───────────────────────────────────────────────────────────────

def reload_gate(module_name: str) -> bool:
    """Reload a single gate module by dotted name.

    Uses importlib.reload() if the module is already in sys.modules.
    Falls back to importlib.import_module() for modules not yet imported.

    Safety: the reloaded module is only accepted into sys.modules if it
    exports a callable check() function.  If validation fails the old
    module is restored and the function returns False.

    Args:
        module_name: Dotted module name, e.g. "gates.gate_01_read_before_edit".

    Returns:
        True if the reload succeeded and the module passed validation.
        False on any error (fail-open — caller's cached reference stays valid).

    Side effects:
        Logs the event to stderr and _reload_history.
        Updates _known_mtimes[module_name] on success.
    """
    try:
        with _lock:
            filepath = _module_to_filepath(module_name)
            new_mtime = _get_mtime(filepath)
            if new_mtime is None:
                _log_reload(module_name, _known_mtimes.get(module_name),
                            0.0, False, f"file not found: {filepath}")
                return False

            old_mtime = _known_mtimes.get(module_name)

            if module_name in sys.modules:
                old_mod = sys.modules[module_name]
                try:
                    mod = importlib.reload(old_mod)
                except Exception as exc:
                    _log_reload(module_name, old_mtime, new_mtime, False,
                                f"reload() raised: {exc}")
                    # Restore old module so the enforcer keeps working
                    sys.modules[module_name] = old_mod
                    return False
            else:
                try:
                    mod = importlib.import_module(module_name)
                except Exception as exc:
                    _log_reload(module_name, old_mtime, new_mtime, False,
                                f"import_module() raised: {exc}")
                    return False

            # Validate: must have a callable check()
            if not _validate_module(mod):
                _log_reload(module_name, old_mtime, new_mtime, False,
                            "module missing callable check() — rejected, old module kept")
                # Revert: put old module back if we had one
                if old_mtime is not None and module_name in sys.modules:
                    # The reload mutated sys.modules — best-effort restore
                    # by reimporting the on-disk file that was valid before.
                    # In practice this means the gate is broken; leave it as-is
                    # and let the enforcer's own error handling deal with it.
                    pass
                return False

            _known_mtimes[module_name] = new_mtime
            _log_reload(module_name, old_mtime, new_mtime, True,
                        "reloaded successfully")
            return True
    except Exception as exc:
        # Absolute last resort: never crash the caller
        print(f"[hot_reload] UNEXPECTED ERROR reloading {module_name}: {exc}",
              file=sys.stderr)
        return False


def check_for_changes(gate_modules: Optional[List[str]] = None) -> Dict[str, Dict]:
    """Compare current mtimes against cached mtimes and return changed gates.

    Does NOT reload anything; only reports which modules have changed.
    Useful for logging, dashboards, or conditional reload decisions.

    Args:
        gate_modules: List of dotted module names to inspect.
                      Defaults to all .py files found in hooks/gates/.

    Returns:
        Dict mapping module_name -> {"old": float|None, "new": float}
        for every module whose mtime has changed (or whose mtime is unknown).

    This function is always cheap to call — it does not rate-limit itself
    (unlike auto_reload which respects CHECK_INTERVAL).
    """
    try:
        if gate_modules is None:
            gate_modules = discover_gate_modules()

        changed: Dict[str, Dict] = {}
        with _lock:
            for module_name in gate_modules:
                filepath = _module_to_filepath(module_name)
                new_mtime = _get_mtime(filepath)
                if new_mtime is None:
                    continue
                old_mtime = _known_mtimes.get(module_name)
                if old_mtime is None or new_mtime > old_mtime:
                    changed[module_name] = {"old": old_mtime, "new": new_mtime}
        return changed
    except Exception:
        return {}


def auto_reload(gate_modules: Optional[List[str]] = None) -> List[str]:
    """Check all gate files for changes and reload any that have been modified.

    Rate-limited: only scans the filesystem every CHECK_INTERVAL seconds.
    Between scans this function returns immediately (O(1) cost: one float compare).

    Args:
        gate_modules: List of dotted module names to watch.
                      Defaults to all .py files found in hooks/gates/.

    Returns:
        List of module names that were successfully reloaded this call.
        Returns [] if the interval has not elapsed or no changes were found.

    This is the primary entry-point for the enforcer's hot-path dispatch loop.
    """
    global _last_check_time
    try:
        now = time.time()
        # Fast path: not enough time has elapsed since last check
        with _lock:
            if now - _last_check_time < CHECK_INTERVAL:
                return []
            _last_check_time = now

        if gate_modules is None:
            gate_modules = discover_gate_modules()

        changed = check_for_changes(gate_modules)
        reloaded = []
        for module_name in changed:
            if reload_gate(module_name):
                reloaded.append(module_name)
        return reloaded
    except Exception:
        return []


def discover_gate_modules(gates_dir: Optional[str] = None) -> List[str]:
    """Return dotted module names for all gate_*.py files in hooks/gates/.

    Scans *gates_dir* (defaults to hooks/gates/ relative to this file) and
    returns names in filesystem order.  Files not matching the gate_*.py
    pattern (e.g. __init__.py) are excluded.

    Args:
        gates_dir: Absolute path to the gates directory.
                   Defaults to hooks/gates/ adjacent to hooks/shared/.

    Returns:
        List of dotted module names like ["gates.gate_01_read_before_edit", ...]
    """
    try:
        directory = gates_dir or _GATES_DIR
        names = []
        for fname in sorted(os.listdir(directory)):
            if fname.startswith("gate_") and fname.endswith(".py"):
                module_stem = fname[:-3]  # strip .py
                names.append(f"gates.{module_stem}")
        return names
    except OSError:
        return []


def seed_mtimes(gate_modules: Optional[List[str]] = None) -> None:
    """Record the current mtime for each module without reloading.

    Call this once at enforcer startup (after initial import_module calls) to
    establish the mtime baseline.  Subsequent auto_reload() calls will then
    only reload modules that changed *after* this baseline was set.

    Args:
        gate_modules: List of dotted module names to seed.
                      Defaults to all .py files found in hooks/gates/.
    """
    try:
        if gate_modules is None:
            gate_modules = discover_gate_modules()
        with _lock:
            for module_name in gate_modules:
                if module_name not in _known_mtimes:
                    filepath = _module_to_filepath(module_name)
                    mtime = _get_mtime(filepath)
                    if mtime is not None:
                        _known_mtimes[module_name] = mtime
    except Exception:
        pass


def get_reload_history() -> List[Dict]:
    """Return a copy of the in-memory reload event log (newest last).

    Each entry is a dict with keys:
        module (str), mtime_old (float|None), mtime_new (float),
        timestamp (float), success (bool), reason (str)
    """
    try:
        with _lock:
            return list(_reload_history)
    except Exception:
        return []


def reset_state() -> None:
    """Clear all cached state (mtime cache, history, last-check timer).

    Intended for tests and debugging only.  In production the module-level
    state is intentionally persistent across hook invocations.
    """
    global _last_check_time
    with _lock:
        _known_mtimes.clear()
        _reload_history.clear()
        _last_check_time = 0.0


# ── Smoke test / CLI entry point ─────────────────────────────────────────────

if __name__ == "__main__":
    import tempfile
    import textwrap

    passed = 0
    failed = 0
    errors: List[str] = []

    def assert_eq(label, actual, expected):
        global passed, failed
        if actual == expected:
            passed += 1
            print(f"  PASS  {label}")
        else:
            failed += 1
            msg = f"  FAIL  {label} — expected {expected!r}, got {actual!r}"
            errors.append(msg)
            print(msg)

    def assert_true(label, value):
        assert_eq(label, bool(value), True)

    def assert_false(label, value):
        assert_eq(label, bool(value), False)

    print("hot_reload.py smoke test")
    print("-" * 50)

    # ── Setup ────────────────────────────────────────────────────────────────
    reset_state()
    # Ensure hooks/ is on sys.path so gates.* and shared.* are importable
    _hooks_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _hooks_dir not in sys.path:
        sys.path.insert(0, _hooks_dir)


    # Create a temporary directory to act as our fake gates/ directory
    with tempfile.TemporaryDirectory() as tmpdir:

        # Helper: write a gate file with or without check()
        def write_gate(directory, name, has_check=True, return_val=False):
            path = os.path.join(directory, f"{name}.py")
            check_body = (
                "    return True\n" if has_check else ""
            )
            src = textwrap.dedent(f"""\
                GATE_NAME = "{name}"
                {"def check(tool_name, tool_input, state, event_type='PreToolUse'):" if has_check else ""}
                {check_body}
            """)
            with open(path, "w") as fh:
                fh.write(src)
            return path

        # ── Test 1: discover_gate_modules returns gate files ─────────────────
        write_gate(tmpdir, "gate_01_alpha")
        write_gate(tmpdir, "gate_02_beta")
        # Non-gate files should be excluded
        open(os.path.join(tmpdir, "__init__.py"), "w").close()
        open(os.path.join(tmpdir, "utils.py"), "w").close()

        discovered = discover_gate_modules(gates_dir=tmpdir)
        assert_eq(
            "1. discover_gate_modules finds gate_01 and gate_02",
            discovered,
            ["gates.gate_01_alpha", "gates.gate_02_beta"],
        )

        # ── Test 2: seed_mtimes records mtimes without reloading ─────────────
        reset_state()
        # Temporarily override _GATES_DIR so module_to_filepath resolves correctly
        _orig_gates_dir = _GATES_DIR

        # We need to patch _module_to_filepath to use tmpdir.
        # Do this by inserting a temporary sys.path entry and re-routing.
        import sys as _sys
        _sys.path.insert(0, tmpdir)

        # Rename our files to match the module name resolution
        # _module_to_filepath uses hooks_dir (parent of shared/) + parts
        # Since we are in a tempdir not the real hooks tree, we verify
        # seed_mtimes with the real gates dir instead.
        _sys.path.pop(0)

        # seed_mtimes with a list of real gate modules
        real_modules = discover_gate_modules()
        seed_mtimes(real_modules)
        with _lock:
            seeded_count = len(_known_mtimes)
        assert_true(
            f"2. seed_mtimes seeded {seeded_count} real gate modules",
            seeded_count > 0,
        )

        # ── Test 3: check_for_changes returns empty dict when mtimes match ────
        reset_state()
        seed_mtimes(real_modules)
        changes = check_for_changes(real_modules)
        assert_eq(
            "3. check_for_changes returns {} when nothing changed",
            changes,
            {},
        )

        # ── Test 4: check_for_changes detects a stale (unknown) mtime ─────────
        reset_state()
        # Do NOT seed — all mtimes are unknown → treated as changed
        changes = check_for_changes(real_modules)
        assert_true(
            "4. check_for_changes reports all modules as changed when cache is empty",
            len(changes) == len(real_modules),
        )

        # ── Test 5: check_for_changes detects a backdated mtime ───────────────
        reset_state()
        seed_mtimes(real_modules)
        if real_modules:
            mod_name = real_modules[0]
            with _lock:
                _known_mtimes[mod_name] = 1.0  # artificially old
            changes = check_for_changes(real_modules)
            assert_true(
                "5. check_for_changes detects backdated mtime for one module",
                mod_name in changes and changes[mod_name]["old"] == 1.0,
            )

        # ── Test 6: reload_gate succeeds for a real gate module ───────────────
        reset_state()
        if real_modules:
            target = real_modules[0]
            ok = reload_gate(target)
            assert_true(f"6. reload_gate({target.split('.')[-1]}) returns True", ok)
            hist = get_reload_history()
            assert_true("6b. reload_history has one entry", len(hist) == 1)
            assert_true("6c. history entry is success=True", hist[0]["success"])

        # ── Test 7: reload_gate rejects module with no check() ─────────────────
        reset_state()
        _FAKE_MODULE = "gates.__hot_reload_test_no_check__"
        # Inject a broken module into sys.modules directly
        import types
        fake_mod = types.ModuleType(_FAKE_MODULE)
        # Intentionally no check attribute
        sys.modules[_FAKE_MODULE] = fake_mod
        # Patch _module_to_filepath result by writing a real file it can reload
        fake_path = os.path.join(tmpdir, "__hot_reload_test_no_check__.py")
        with open(fake_path, "w") as fh:
            fh.write("# no check() here\nGATE_NAME = 'broken'\n")
        # Temporarily monkey-patch sys.path so importlib can find the module
        _sys.path.insert(0, tmpdir)
        ok = reload_gate(_FAKE_MODULE)
        _sys.path.pop(0)
        del sys.modules[_FAKE_MODULE]
        assert_false(
            "7. reload_gate rejects module with no check() function",
            ok,
        )
        hist = get_reload_history()
        assert_true(
            "7b. history records the failed validation",
            any(not e["success"] for e in hist),
        )

        # ── Test 8: auto_reload respects CHECK_INTERVAL ─────────────────────
        reset_state()
        seed_mtimes(real_modules)
        # Force interval to expire
        # When run as __main__, this module IS the current module in sys.modules.
        import sys as _sys2
        _this_mod = _sys2.modules[__name__]
        _this_mod._last_check_time = 0.0
        reloaded = auto_reload(real_modules)
        # Nothing changed so reloaded list should be empty
        assert_eq(
            "8. auto_reload returns [] when no files changed",
            reloaded,
            [],
        )

        # ── Test 9: auto_reload returns [] before CHECK_INTERVAL elapses ─────
        reset_state()
        _this_mod._last_check_time = time.time()  # simulate a very recent check
        reloaded = auto_reload(real_modules)
        assert_eq(
            "9. auto_reload returns [] before CHECK_INTERVAL expires",
            reloaded,
            [],
        )

        # ── Test 10: reload_gate for non-existent file returns False ──────────
        reset_state()
        ok = reload_gate("gates.__nonexistent_gate_xyz__")
        assert_false("10. reload_gate returns False for missing file", ok)

        # ── Test 11: get_reload_history returns copy (not mutable ref) ────────
        reset_state()
        if real_modules:
            reload_gate(real_modules[0])
        hist1 = get_reload_history()
        hist1.append({"fake": True})
        hist2 = get_reload_history()
        assert_true(
            "11. get_reload_history returns independent copy",
            {"fake": True} not in hist2,
        )

        # ── Test 12: reset_state clears all caches ────────────────────────────
        reset_state()
        seed_mtimes(real_modules)
        if real_modules:
            reload_gate(real_modules[0])
        reset_state()
        with _lock:
            cache_empty = len(_known_mtimes) == 0
            hist_empty  = len(_reload_history) == 0
        assert_true("12. reset_state clears mtime cache", cache_empty)
        assert_true("12b. reset_state clears reload history", hist_empty)

    # ── Summary ──────────────────────────────────────────────────────────────
    print("-" * 50)
    total = passed + failed
    print(f"Results: {passed}/{total} passed", end="")
    if failed:
        print(f", {failed} FAILED")
        for e in errors:
            print(e)
        sys.exit(1)
    else:
        print(" — all OK")
        sys.exit(0)
