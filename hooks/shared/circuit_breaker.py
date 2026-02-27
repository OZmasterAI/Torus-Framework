"""Circuit breaker pattern for the Torus self-healing framework.

Tracks per-service failure rates and transitions between three states:
  CLOSED    — Normal operation, calls pass through.
  OPEN      — Too many failures; calls are rejected immediately (fail-fast).
  HALF_OPEN — Recovery probe; a limited number of successes closes the circuit.

State is persisted to /dev/shm/claude-hooks/circuit_breaker.json (ramdisk) so
that state is shared across hook invocations within a single session.

Design constraints:
  - Fail-open: every public function is wrapped in try/except; never raises.
  - Thread-safe: file writes use an atomic rename via a temp file.
  - No external dependencies beyond the Python standard library.

Typical usage:
    from shared.circuit_breaker import record_success, record_failure, is_open

    if is_open("memory_mcp"):
        # fall back to cached result or skip
        ...
    else:
        try:
            result = call_memory()
            record_success("memory_mcp")
        except Exception:
            record_failure("memory_mcp")
"""

import json
import os
import tempfile
import threading
import time
from typing import Any, Dict, Optional

# ── State constants ─────────────────────────────────────────────────────────────

STATE_CLOSED    = "CLOSED"
STATE_OPEN      = "OPEN"
STATE_HALF_OPEN = "HALF_OPEN"

# ── Persistence paths ───────────────────────────────────────────────────────────

_RAMDISK_DIR  = "/dev/shm/claude-hooks"
_RAMDISK_PATH = os.path.join(_RAMDISK_DIR, "circuit_breaker.json")
_DISK_FALLBACK = os.path.join(
    os.path.expanduser("~"), ".claude", "hooks", ".circuit_breaker.json"
)

# ── Default configuration ───────────────────────────────────────────────────────

DEFAULT_FAILURE_THRESHOLD  = 5   # consecutive failures → OPEN
DEFAULT_RECOVERY_TIMEOUT   = 60  # seconds to wait in OPEN before HALF_OPEN
DEFAULT_SUCCESS_THRESHOLD  = 2   # successes in HALF_OPEN → CLOSED

# ── Module-level lock (guards in-process concurrent access) ────────────────────

_lock = threading.Lock()


# ── Internal helpers ────────────────────────────────────────────────────────────

def _get_path() -> str:
    """Return the best available persistence path."""
    try:
        if os.path.isdir(_RAMDISK_DIR):
            return _RAMDISK_PATH
    except (OSError, IOError):
        pass
    return _DISK_FALLBACK


def _load() -> Dict[str, Any]:
    """Load the persisted circuit-breaker state dict from disk/ramdisk.

    Returns an empty dict on any read/parse error (fail-open).
    """
    path = _get_path()
    try:
        if os.path.isfile(path):
            with open(path, "r") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                return data
    except (OSError, IOError, json.JSONDecodeError, ValueError):
        pass
    return {}


def _save(data: Dict[str, Any]) -> None:
    """Atomically write the circuit-breaker state dict.

    Uses a temp-file + rename for atomicity so a crash mid-write never
    leaves a corrupt file.  Silently swallows all errors (fail-open).
    """
    path = _get_path()
    try:
        dir_ = os.path.dirname(path)
        os.makedirs(dir_, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=dir_, prefix=".cb_tmp_")
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(data, fh, indent=2)
            os.replace(tmp_path, path)
        except Exception:
            # Clean up temp file on write failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except (OSError, IOError, ValueError):
        pass


def _default_service_record(
    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
    recovery_timeout: int  = DEFAULT_RECOVERY_TIMEOUT,
    success_threshold: int = DEFAULT_SUCCESS_THRESHOLD,
) -> Dict[str, Any]:
    """Return a fresh per-service record with all fields initialised."""
    return {
        "state":             STATE_CLOSED,
        "failure_count":     0,
        "success_count":     0,    # consecutive successes while HALF_OPEN
        "last_failure_time": None, # epoch float
        "opened_at":         None, # epoch float when last entered OPEN
        "failure_threshold": failure_threshold,
        "recovery_timeout":  recovery_timeout,
        "success_threshold": success_threshold,
        "total_failures":    0,
        "total_successes":   0,
        "total_rejections":  0,
    }


def _get_or_create(
    data: Dict[str, Any],
    service: str,
    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
    recovery_timeout: int  = DEFAULT_RECOVERY_TIMEOUT,
    success_threshold: int = DEFAULT_SUCCESS_THRESHOLD,
) -> Dict[str, Any]:
    """Fetch the service record, creating it with defaults if absent."""
    if service not in data:
        data[service] = _default_service_record(
            failure_threshold, recovery_timeout, success_threshold
        )
    rec = data[service]
    # Back-fill any keys added in later versions
    defaults = _default_service_record()
    for key, val in defaults.items():
        rec.setdefault(key, val)
    return rec


def _maybe_recover(rec: Dict[str, Any]) -> None:
    """Transition OPEN → HALF_OPEN if recovery_timeout has elapsed."""
    if rec["state"] == STATE_OPEN:
        opened_at = rec.get("opened_at") or rec.get("last_failure_time", 0) or 0
        elapsed = time.time() - opened_at
        if elapsed >= rec["recovery_timeout"]:
            rec["state"]         = STATE_HALF_OPEN
            rec["failure_count"] = 0
            rec["success_count"] = 0


# ── Public API ──────────────────────────────────────────────────────────────────

def record_success(
    service: str,
    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
    recovery_timeout: int  = DEFAULT_RECOVERY_TIMEOUT,
    success_threshold: int = DEFAULT_SUCCESS_THRESHOLD,
) -> None:
    """Record a successful call for *service*.

    - CLOSED    : reset failure_count.
    - HALF_OPEN : increment success_count; if >= success_threshold → CLOSED.
    - OPEN      : no-op (caller should not be calling if open, but be safe).
    """
    try:
        with _lock:
            data = _load()
            rec  = _get_or_create(
                data, service, failure_threshold, recovery_timeout, success_threshold
            )
            _maybe_recover(rec)

            rec["total_successes"] += 1

            if rec["state"] == STATE_CLOSED:
                rec["failure_count"] = 0

            elif rec["state"] == STATE_HALF_OPEN:
                rec["success_count"] += 1
                if rec["success_count"] >= rec["success_threshold"]:
                    rec["state"]         = STATE_CLOSED
                    rec["failure_count"] = 0
                    rec["success_count"] = 0
                    rec["opened_at"]     = None

            # OPEN: caller is probing despite the open circuit — leave state alone

            _save(data)
    except Exception:
        pass  # Fail-open: never crash the caller


def record_failure(
    service: str,
    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
    recovery_timeout: int  = DEFAULT_RECOVERY_TIMEOUT,
    success_threshold: int = DEFAULT_SUCCESS_THRESHOLD,
) -> None:
    """Record a failed call for *service*.

    - CLOSED    : increment failure_count; if >= failure_threshold → OPEN.
    - HALF_OPEN : reset back to OPEN (probe failed).
    - OPEN      : bump total_failures only.
    """
    try:
        with _lock:
            data = _load()
            rec  = _get_or_create(
                data, service, failure_threshold, recovery_timeout, success_threshold
            )
            _maybe_recover(rec)

            now = time.time()
            rec["last_failure_time"] = now
            rec["total_failures"]   += 1

            if rec["state"] == STATE_CLOSED:
                rec["failure_count"] += 1
                if rec["failure_count"] >= rec["failure_threshold"]:
                    rec["state"]     = STATE_OPEN
                    rec["opened_at"] = now

            elif rec["state"] == STATE_HALF_OPEN:
                # Probe attempt failed — re-open the circuit
                rec["state"]         = STATE_OPEN
                rec["opened_at"]     = now
                rec["failure_count"] = 1
                rec["success_count"] = 0

            # OPEN: already open, nothing to change except counters above

            _save(data)
    except Exception:
        pass  # Fail-open


def is_open(service: str) -> bool:
    """Return True if calls to *service* should be rejected right now.

    A circuit is considered open when it is in STATE_OPEN and the recovery
    timeout has *not* yet elapsed.  Once the timeout elapses the circuit
    transitions to HALF_OPEN and this returns False (allowing one probe).

    Defaults to False (fail-open) on any error.
    """
    try:
        with _lock:
            data = _load()
            if service not in data:
                return False
            rec = data[service]
            _maybe_recover(rec)
            if rec["state"] == STATE_OPEN:
                # Still need to persist the possible HALF_OPEN transition
                _save(data)
                return True
            if rec["state"] != STATE_CLOSED:
                # HALF_OPEN counts as not-open (allow the probe through)
                _save(data)
            return False
    except Exception:
        return False  # Fail-open


def get_state(service: str) -> str:
    """Return the current circuit state string for *service*.

    Returns STATE_CLOSED (fail-open) on any error or if service is unknown.
    """
    try:
        with _lock:
            data = _load()
            if service not in data:
                return STATE_CLOSED
            rec = data[service]
            _maybe_recover(rec)
            _save(data)
            return rec["state"]
    except Exception:
        return STATE_CLOSED  # Fail-open


def get_all_states() -> Dict[str, Dict[str, Any]]:
    """Return a snapshot of all tracked services and their full records.

    Returns an empty dict on any error.
    """
    try:
        with _lock:
            data = _load()
            now  = time.time()
            result = {}
            for svc, rec in data.items():
                _maybe_recover(rec)
                result[svc] = dict(rec)  # shallow copy so callers can't mutate
            if data:
                _save(data)  # persist any OPEN→HALF_OPEN transitions
            return result
    except Exception:
        return {}  # Fail-open


def reset(service: str) -> None:
    """Force the circuit for *service* back to CLOSED, clearing all counters.

    Used for manual recovery or test teardown.
    Silently no-ops on any error.
    """
    try:
        with _lock:
            data = _load()
            if service in data:
                # Preserve configured thresholds, reset everything else
                rec = data[service]
                ft  = rec.get("failure_threshold",  DEFAULT_FAILURE_THRESHOLD)
                rt  = rec.get("recovery_timeout",   DEFAULT_RECOVERY_TIMEOUT)
                st  = rec.get("success_threshold",  DEFAULT_SUCCESS_THRESHOLD)
                data[service] = _default_service_record(ft, rt, st)
            _save(data)
    except Exception:
        pass  # Fail-open


# ── Gate circuit-breaker integration ────────────────────────────────────────────
#
# Gate-specific circuit breaker tracks crashes (exceptions) in individual gate
# modules and temporarily skips them when they crash repeatedly.  This is
# separate from the general service circuit breaker above.
#
# Design:
#   - Tier 1 safety gates (01-03) are NEVER skipped regardless of crash count.
#   - 3 crashes within a 5-minute sliding window → circuit OPENS.
#   - After 60-second cooldown the circuit enters HALF_OPEN (one probe allowed).
#   - A successful probe → circuit CLOSES.  Another crash → re-OPEN.
#   - Gate state is persisted to a dedicated file (survives reboots).

_GATE_CRASH_THRESHOLD = 3    # crashes within window → OPEN
_GATE_CRASH_WINDOW    = 300  # sliding window in seconds (5 minutes)
_GATE_COOLDOWN        = 60   # seconds in OPEN before HALF_OPEN
_GATE_SUCCESS_NEEDED  = 1    # successes in HALF_OPEN → CLOSED

_GATE_STATE_PATH = os.path.join(
    os.path.expanduser("~"), ".claude", "hooks", ".circuit_breaker_state.json"
)

# Tier 1 safety gates: never skipped.
_TIER1_GATE_NAMES = {
    "gate_01_read_before_edit",
    "gate_02_no_destroy",
    "gate_03_test_before_deploy",
}

_gate_lock = threading.Lock()


def _load_gate_state() -> Dict[str, Any]:
    """Load gate circuit-breaker state from disk (fail-open)."""
    try:
        if os.path.isfile(_GATE_STATE_PATH):
            with open(_GATE_STATE_PATH, "r") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                return data
    except (OSError, IOError, json.JSONDecodeError, ValueError):
        pass
    return {}


def _save_gate_state(data: Dict[str, Any]) -> None:
    """Atomically save gate circuit-breaker state (fail-open)."""
    try:
        dir_ = os.path.dirname(_GATE_STATE_PATH)
        os.makedirs(dir_, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=dir_, prefix=".gcb_tmp_")
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(data, fh, indent=2)
            os.replace(tmp_path, _GATE_STATE_PATH)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    except (OSError, IOError, ValueError):
        pass


def _default_gate_record() -> Dict[str, Any]:
    """Return a fresh gate circuit-breaker record."""
    return {
        "state":            STATE_CLOSED,
        "crash_timestamps": [],  # list of epoch floats (sliding window)
        "opened_at":        None,
        "total_crashes":    0,
        "total_skips":      0,
    }


def _get_or_create_gate(data: Dict[str, Any], gate_name: str) -> Dict[str, Any]:
    """Fetch or create a gate record, back-filling missing keys."""
    if gate_name not in data:
        data[gate_name] = _default_gate_record()
    rec = data[gate_name]
    defaults = _default_gate_record()
    for key, val in defaults.items():
        rec.setdefault(key, val)
    return rec


def _prune_crash_window(rec: Dict[str, Any]) -> None:
    """Remove crash timestamps outside the sliding window."""
    cutoff = time.time() - _GATE_CRASH_WINDOW
    rec["crash_timestamps"] = [t for t in rec["crash_timestamps"] if t >= cutoff]


def _gate_maybe_recover(rec: Dict[str, Any]) -> None:
    """Transition OPEN → HALF_OPEN if cooldown has elapsed."""
    if rec["state"] == STATE_OPEN:
        opened_at = rec.get("opened_at") or 0
        if time.time() - opened_at >= _GATE_COOLDOWN:
            rec["state"] = STATE_HALF_OPEN


def should_skip_gate(gate_name: str) -> bool:
    """Return True if *gate_name*'s circuit is OPEN (caller should skip it).

    Returns False for CLOSED (normal) and HALF_OPEN (probe allowed through).
    Tier 1 safety gates always return False — they are never skipped.
    Defaults to False (fail-open) on any error.
    """
    if gate_name in _TIER1_GATE_NAMES:
        return False
    try:
        with _gate_lock:
            data = _load_gate_state()
            if gate_name not in data:
                return False
            rec = data[gate_name]
            _gate_maybe_recover(rec)
            if rec["state"] == STATE_OPEN:
                rec["total_skips"] = rec.get("total_skips", 0) + 1
                _save_gate_state(data)
                return True
            if rec["state"] == STATE_HALF_OPEN:
                _save_gate_state(data)
            return False
    except Exception:
        return False  # Fail-open


def record_gate_result(gate_name: str, success: bool) -> None:
    """Record a gate execution outcome for circuit-breaker tracking.

    On crash (success=False):
      - Append timestamp to sliding window.
      - Prune entries outside _GATE_CRASH_WINDOW.
      - If crash count >= _GATE_CRASH_THRESHOLD → OPEN.
      - In HALF_OPEN on crash → re-OPEN.

    On success (success=True):
      - In HALF_OPEN → CLOSED (probe succeeded).
      - In CLOSED → no-op (normal operation).

    Tier 1 gates are tracked but never put into OPEN state (safety invariant).
    Silently swallows all errors (fail-open).
    """
    try:
        with _gate_lock:
            data = _load_gate_state()
            rec = _get_or_create_gate(data, gate_name)
            _gate_maybe_recover(rec)

            if not success:
                # Crash: record in sliding window
                now = time.time()
                rec["crash_timestamps"].append(now)
                _prune_crash_window(rec)
                rec["total_crashes"] = rec.get("total_crashes", 0) + 1

                # Never open Tier 1 gate circuits
                if gate_name not in _TIER1_GATE_NAMES:
                    if rec["state"] == STATE_HALF_OPEN:
                        rec["state"]     = STATE_OPEN
                        rec["opened_at"] = now
                    elif rec["state"] == STATE_CLOSED:
                        if len(rec["crash_timestamps"]) >= _GATE_CRASH_THRESHOLD:
                            rec["state"]     = STATE_OPEN
                            rec["opened_at"] = now
            else:
                # Success: probe in HALF_OPEN closes the circuit
                if rec["state"] == STATE_HALF_OPEN:
                    rec["state"]            = STATE_CLOSED
                    rec["crash_timestamps"] = []
                    rec["opened_at"]        = None

            _save_gate_state(data)
    except Exception:
        pass  # Fail-open


def get_gate_circuit_state(gate_name: str) -> str:
    """Return the circuit-breaker state string for *gate_name*.

    Returns STATE_CLOSED on unknown gate or error (fail-open).
    """
    try:
        with _gate_lock:
            data = _load_gate_state()
            if gate_name not in data:
                return STATE_CLOSED
            rec = data[gate_name]
            _gate_maybe_recover(rec)
            _save_gate_state(data)
            return rec["state"]
    except Exception:
        return STATE_CLOSED


def reset_gate_circuit(gate_name: str) -> None:
    """Force the gate circuit for *gate_name* back to CLOSED (for tests)."""
    try:
        with _gate_lock:
            data = _load_gate_state()
            data[gate_name] = _default_gate_record()
            _save_gate_state(data)
    except Exception:
        pass


def get_all_gate_states() -> Dict[str, Dict[str, Any]]:
    """Return a snapshot of all tracked gate circuit-breaker records."""
    try:
        with _gate_lock:
            data = _load_gate_state()
            return {k: dict(v) for k, v in data.items()}
    except Exception:
        return {}


# ── Smoke test / CLI entry point ────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    TEST_SVC = "__cb_smoke_test__"

    passed = 0
    failed = 0
    errors = []

    def assert_eq(label, actual, expected):
        global passed, failed
        if actual == expected:
            passed += 1
            print(f"  PASS  {label}")
        else:
            failed += 1
            errors.append(f"  FAIL  {label} — expected {expected!r}, got {actual!r}")
            print(errors[-1])

    def assert_true(label, value):
        assert_eq(label, bool(value), True)

    def assert_false(label, value):
        assert_eq(label, bool(value), False)

    print("Circuit Breaker smoke test")
    print("-" * 40)

    # ── Setup: clean slate ──────────────────────────────────────────────────────
    reset(TEST_SVC)

    # 1. Fresh service starts CLOSED
    assert_eq("1. initial state is CLOSED", get_state(TEST_SVC), STATE_CLOSED)

    # 2. is_open returns False when CLOSED
    assert_false("2. is_open is False when CLOSED", is_open(TEST_SVC))

    # 3. Successes in CLOSED state don't open the circuit
    for _ in range(10):
        record_success(TEST_SVC)
    assert_eq("3. state stays CLOSED after successes", get_state(TEST_SVC), STATE_CLOSED)

    # 4. Failures below threshold don't open the circuit
    for _ in range(DEFAULT_FAILURE_THRESHOLD - 1):
        record_failure(TEST_SVC)
    assert_eq("4. state stays CLOSED below threshold", get_state(TEST_SVC), STATE_CLOSED)

    # 5. One more failure crosses the threshold → OPEN
    record_failure(TEST_SVC)
    assert_eq("5. state transitions to OPEN at threshold", get_state(TEST_SVC), STATE_OPEN)

    # 6. is_open returns True when OPEN
    assert_true("6. is_open is True when OPEN", is_open(TEST_SVC))

    # 7. get_all_states includes our service
    all_states = get_all_states()
    assert_true("7. get_all_states includes test service", TEST_SVC in all_states)

    # 8. Simulate recovery timeout by back-dating opened_at
    data = _load()
    data[TEST_SVC]["opened_at"] = time.time() - DEFAULT_RECOVERY_TIMEOUT - 1
    _save(data)
    assert_eq("8. state transitions to HALF_OPEN after timeout", get_state(TEST_SVC), STATE_HALF_OPEN)

    # 9. is_open returns False in HALF_OPEN (allow probe)
    assert_false("9. is_open is False in HALF_OPEN", is_open(TEST_SVC))

    # 10. Enough successes in HALF_OPEN → CLOSED
    for _ in range(DEFAULT_SUCCESS_THRESHOLD):
        record_success(TEST_SVC)
    assert_eq("10. HALF_OPEN closes after success_threshold successes",
              get_state(TEST_SVC), STATE_CLOSED)

    # 11. Failure in HALF_OPEN re-opens the circuit
    # Re-trigger OPEN first
    reset(TEST_SVC)
    for _ in range(DEFAULT_FAILURE_THRESHOLD):
        record_failure(TEST_SVC)
    data = _load()
    data[TEST_SVC]["opened_at"] = time.time() - DEFAULT_RECOVERY_TIMEOUT - 1
    _save(data)
    assert_eq("11a. back in HALF_OPEN for re-open test",
              get_state(TEST_SVC), STATE_HALF_OPEN)
    record_failure(TEST_SVC)  # probe fails
    assert_eq("11b. failure in HALF_OPEN re-opens circuit",
              get_state(TEST_SVC), STATE_OPEN)

    # 12. reset() restores CLOSED state and clears counters
    reset(TEST_SVC)
    assert_eq("12. reset() restores CLOSED state", get_state(TEST_SVC), STATE_CLOSED)

    # 13. Custom thresholds are respected
    CUSTOM_SVC = "__cb_smoke_custom__"
    reset(CUSTOM_SVC)
    for _ in range(2):
        record_failure(CUSTOM_SVC, failure_threshold=2)
    assert_eq("13. custom failure_threshold=2 triggers OPEN",
              get_state(CUSTOM_SVC), STATE_OPEN)
    reset(CUSTOM_SVC)

    # 14. is_open returns False for an unknown service (fail-open default)
    assert_false("14. is_open is False for unknown service", is_open("__unknown_svc__"))

    # 15. Persistence path is ramdisk when available
    assert_true("15. persistence path is /dev/shm/claude-hooks/circuit_breaker.json",
                _get_path() == _RAMDISK_PATH or os.path.isfile(_get_path()))

    # ── Cleanup ─────────────────────────────────────────────────────────────────
    reset(TEST_SVC)
    reset(CUSTOM_SVC)

    print("-" * 40)
    total = passed + failed
    print(f"Results: {passed}/{total} passed", end="")
    if failed:
        print(f", {failed} FAILED")
        sys.exit(1)
    else:
        print(" — all OK")
        sys.exit(0)
