"""Framework Health Monitor for the Torus Self-Healing Framework.

Provides a unified health check across all framework components — gates,
memory MCP (UDS socket), state files, ramdisk, and audit log.

Usage:
    from shared.health_monitor import full_health_check, get_degraded_components

    report = full_health_check("my-session-id")
    print(report["overall_score"])   # 0-100
    print(report["status"])          # "healthy" | "degraded" | "critical"

    degraded = get_degraded_components()
    # ["memory", "ramdisk"]
"""

import importlib
import json
import os
import sys
import time

# Ensure the hooks directory is on sys.path so "shared.*" imports work regardless
# of how this module is invoked (from hooks/ or from shared/ directly).
_HOOKS_DIR = os.path.join(os.path.expanduser("~"), ".claude", "hooks")
if _HOOKS_DIR not in sys.path:
    sys.path.insert(0, _HOOKS_DIR)

# ── Constants ─────────────────────────────────────────────────────────────────

#: All gate module names — canonical list from shared/gate_registry.py.
from shared.gate_registry import GATE_MODULES

#: Component names for degraded-mode detection.
COMPONENT_GATES = "gates"
COMPONENT_MEMORY = "memory"
COMPONENT_STATE = "state"
COMPONENT_RAMDISK = "ramdisk"
COMPONENT_AUDIT = "audit"

# Weights for the overall health score (must sum to 100)
_WEIGHTS = {
    COMPONENT_GATES: 40,
    COMPONENT_MEMORY: 25,
    COMPONENT_STATE: 15,
    COMPONENT_RAMDISK: 10,
    COMPONENT_AUDIT: 10,
}

# Suggested fallbacks when a component is degraded
_FALLBACKS = {
    COMPONENT_MEMORY: (
        "Memory UDS worker is unreachable. "
        "Start memory_server.py or restart the MCP process."
    ),
    COMPONENT_RAMDISK: (
        "Ramdisk (/run/user/<uid>/claude-hooks) is unavailable. "
        "Framework will fall back to disk I/O — performance will be reduced."
    ),
    COMPONENT_AUDIT: (
        "Audit directory is missing or not writable. "
        "Gate decisions will not be logged. Run: mkdir -p ~/.claude/hooks/audit"
    ),
    COMPONENT_GATES: (
        "One or more gate modules failed to import. "
        "The enforcer may skip broken gates. Check Python path and syntax."
    ),
    COMPONENT_STATE: (
        "State file is missing or corrupted. "
        "Gate counters and session context will be reset on next boot."
    ),
}


# ── Component checks ──────────────────────────────────────────────────────────


def check_gates_health() -> dict:
    """Import each gate module and return per-gate status.

    Returns:
        {
            "gates.gate_01_read_before_edit": "ok",
            "gates.gate_02_no_destroy": "error: No module named 'foo'",
            ...
            "summary": {"ok": 16, "error": 1},
            "status": "ok" | "degraded" | "error",
        }
    """
    results: dict = {}
    ok_count = 0
    error_count = 0

    for module_name in GATE_MODULES:
        try:
            # Force a fresh import attempt so we always get the current state.
            if module_name in sys.modules:
                mod = sys.modules[module_name]
            else:
                mod = importlib.import_module(module_name)
            # Verify the gate exports the required `check` function
            if not callable(getattr(mod, "check", None)):
                results[module_name] = "error: missing check() function"
                error_count += 1
            else:
                results[module_name] = "ok"
                ok_count += 1
        except Exception as exc:
            results[module_name] = f"error: {exc}"
            error_count += 1

    results["summary"] = {"ok": ok_count, "error": error_count}
    if error_count == 0:
        results["status"] = "ok"
    elif ok_count == 0:
        results["status"] = "error"
    else:
        results["status"] = "degraded"

    return results


def check_memory_health() -> dict:
    """Check whether the ChromaDB UDS worker (memory_server.py) is reachable.

    Returns:
        {
            "socket_path": "~/.claude/hooks/.chromadb.sock",
            "socket_exists": True | False,
            "worker_reachable": True | False,
            "ping_response": "pong" | None,
            "knowledge_count": <int> | None,
            "status": "ok" | "degraded" | "error",
            "error": <str> | None,
        }
    """
    result: dict = {
        "socket_path": None,
        "socket_exists": False,
        "worker_reachable": False,
        "ping_response": None,
        "knowledge_count": None,
        "status": "error",
        "error": None,
    }

    try:
        from shared.chromadb_socket import (
            SOCKET_PATH,
            is_worker_available,
            ping,
            count,
        )
        result["socket_path"] = SOCKET_PATH
        result["socket_exists"] = os.path.exists(SOCKET_PATH)

        # Quick reachability check (retries=1 to keep health checks fast)
        available = is_worker_available(retries=1, delay=0.1)
        result["worker_reachable"] = available

        if available:
            try:
                result["ping_response"] = ping()
            except Exception as ping_err:
                result["ping_response"] = None
                result["error"] = f"ping failed: {ping_err}"

            try:
                result["knowledge_count"] = count("knowledge")
            except Exception:
                pass  # Non-fatal — count is informational

            result["status"] = "ok" if result["ping_response"] == "pong" else "degraded"
        else:
            result["status"] = "error"
            result["error"] = "UDS worker not reachable"

    except ImportError as imp_err:
        result["status"] = "error"
        result["error"] = f"chromadb_socket import failed: {imp_err}"

    return result


def check_state_health(session_id: str = "default") -> dict:
    """Validate the state file for a given session.

    Returns:
        {
            "session_id": "...",
            "state_file": "/path/to/state_<id>.json",
            "file_exists": True | False,
            "valid_json": True | False,
            "schema_version": <int> | None,
            "size_bytes": <int> | None,
            "status": "ok" | "degraded" | "error",
            "error": <str> | None,
        }
    """
    result: dict = {
        "session_id": session_id,
        "state_file": None,
        "file_exists": False,
        "valid_json": False,
        "schema_version": None,
        "size_bytes": None,
        "status": "error",
        "error": None,
    }

    try:
        from shared.state import state_file_for, load_state
        state_path = state_file_for(session_id)
        result["state_file"] = state_path
        result["file_exists"] = os.path.isfile(state_path)

        if result["file_exists"]:
            result["size_bytes"] = os.path.getsize(state_path)
            try:
                with open(state_path, "r") as fh:
                    data = json.load(fh)
                result["valid_json"] = True
                result["schema_version"] = data.get("_version")
                result["status"] = "ok"
            except (json.JSONDecodeError, OSError) as json_err:
                result["valid_json"] = False
                result["status"] = "error"
                result["error"] = f"JSON parse failed: {json_err}"
        else:
            # Missing state file is degraded (not critical — it gets re-created on boot)
            result["status"] = "degraded"
            result["error"] = f"State file not found: {state_path}"

    except ImportError as imp_err:
        result["status"] = "error"
        result["error"] = f"state module import failed: {imp_err}"

    return result


def check_ramdisk_health() -> dict:
    """Verify ramdisk (tmpfs) paths exist and are writable.

    Returns:
        {
            "ramdisk_dir": "/run/user/<uid>/claude-hooks",
            "ramdisk_available": True | False,
            "audit_dir": "/run/user/<uid>/claude-hooks/audit",
            "audit_dir_exists": True | False,
            "state_dir": "/run/user/<uid>/claude-hooks/state",
            "state_dir_exists": True | False,
            "writable": True | False,
            "fallback_active": True | False,
            "status": "ok" | "degraded" | "error",
            "error": <str> | None,
        }
    """
    result: dict = {
        "ramdisk_dir": None,
        "ramdisk_available": False,
        "audit_dir": None,
        "audit_dir_exists": False,
        "state_dir": None,
        "state_dir_exists": False,
        "writable": False,
        "fallback_active": False,
        "status": "error",
        "error": None,
    }

    try:
        from shared.ramdisk import (
            RAMDISK_DIR,
            TMPFS_AUDIT_DIR,
            TMPFS_STATE_DIR,
            is_ramdisk_available,
        )

        result["ramdisk_dir"] = RAMDISK_DIR
        result["audit_dir"] = TMPFS_AUDIT_DIR
        result["state_dir"] = TMPFS_STATE_DIR

        available = is_ramdisk_available()
        result["ramdisk_available"] = available
        result["audit_dir_exists"] = os.path.isdir(TMPFS_AUDIT_DIR)
        result["state_dir_exists"] = os.path.isdir(TMPFS_STATE_DIR)

        if available:
            # Confirm writability with a quick probe
            test_path = os.path.join(RAMDISK_DIR, ".health_probe")
            try:
                with open(test_path, "w") as fh:
                    fh.write("ok")
                os.remove(test_path)
                result["writable"] = True
                result["status"] = "ok"
            except (OSError, IOError) as write_err:
                result["writable"] = False
                result["status"] = "degraded"
                result["error"] = f"Ramdisk not writable: {write_err}"
        else:
            result["fallback_active"] = True
            result["status"] = "degraded"
            result["error"] = (
                f"Ramdisk directory {RAMDISK_DIR} not available; "
                "framework is using disk I/O fallback."
            )

    except ImportError as imp_err:
        result["status"] = "error"
        result["error"] = f"ramdisk module import failed: {imp_err}"

    return result


def check_audit_health() -> dict:
    """Verify the audit log directory exists and is writable.

    Returns:
        {
            "audit_dir": "/path/to/audit",
            "dir_exists": True | False,
            "writable": True | False,
            "recent_log_files": <int>,
            "status": "ok" | "degraded" | "error",
            "error": <str> | None,
        }
    """
    result: dict = {
        "audit_dir": None,
        "dir_exists": False,
        "writable": False,
        "recent_log_files": 0,
        "status": "error",
        "error": None,
    }

    try:
        from shared.ramdisk import get_audit_dir
        audit_dir = get_audit_dir()
    except ImportError:
        # Fallback to the disk path if ramdisk module unavailable
        audit_dir = os.path.join(os.path.expanduser("~"), ".claude", "hooks", "audit")

    result["audit_dir"] = audit_dir
    result["dir_exists"] = os.path.isdir(audit_dir)

    if result["dir_exists"]:
        # Count .jsonl files (active log files)
        try:
            files = [f for f in os.listdir(audit_dir) if f.endswith(".jsonl")]
            result["recent_log_files"] = len(files)
        except OSError:
            pass

        # Write probe
        test_path = os.path.join(audit_dir, ".health_probe")
        try:
            with open(test_path, "w") as fh:
                fh.write("ok")
            os.remove(test_path)
            result["writable"] = True
            result["status"] = "ok"
        except (OSError, IOError) as write_err:
            result["writable"] = False
            result["status"] = "degraded"
            result["error"] = f"Audit dir not writable: {write_err}"
    else:
        result["status"] = "error"
        result["error"] = f"Audit directory not found: {audit_dir}"

    return result


# ── Aggregation ───────────────────────────────────────────────────────────────

# Module-level cache for most recent full check (cleared by full_health_check)
_last_report: dict = {}


def full_health_check(session_id: str = "default") -> dict:
    """Run all component health checks and return a combined report.

    Returns:
        {
            "timestamp": <float>,
            "session_id": "...",
            "components": {
                "gates": { ... },
                "memory": { ... },
                "state": { ... },
                "ramdisk": { ... },
                "audit": { ... },
            },
            "overall_score": 0-100,
            "status": "healthy" | "degraded" | "critical",
            "degraded_components": ["memory", "ramdisk"],
            "fallback_suggestions": {"memory": "...", ...},
            "duration_ms": <float>,
        }
    """
    global _last_report
    t0 = time.monotonic()

    components = {
        COMPONENT_GATES: check_gates_health(),
        COMPONENT_MEMORY: check_memory_health(),
        COMPONENT_STATE: check_state_health(session_id),
        COMPONENT_RAMDISK: check_ramdisk_health(),
        COMPONENT_AUDIT: check_audit_health(),
    }

    # Score each component: ok=100, degraded=50, error=0
    _STATUS_SCORES = {"ok": 100, "degraded": 50, "error": 0}
    weighted_sum = 0
    for comp, weight in _WEIGHTS.items():
        comp_status = components[comp].get("status", "error")
        weighted_sum += _STATUS_SCORES.get(comp_status, 0) * weight

    overall_score = weighted_sum // 100  # divide by sum-of-weights (100)

    # Determine global status thresholds
    if overall_score >= 80:
        status = "healthy"
    elif overall_score >= 40:
        status = "degraded"
    else:
        status = "critical"

    # Identify degraded/errored components
    degraded = [
        comp for comp in _WEIGHTS
        if components[comp].get("status") in ("degraded", "error")
    ]

    # Build fallback suggestions for affected components
    suggestions = {
        comp: _FALLBACKS[comp]
        for comp in degraded
        if comp in _FALLBACKS
    }

    duration_ms = round((time.monotonic() - t0) * 1000, 2)

    report = {
        "timestamp": time.time(),
        "session_id": session_id,
        "components": components,
        "overall_score": overall_score,
        "status": status,
        "degraded_components": degraded,
        "fallback_suggestions": suggestions,
        "duration_ms": duration_ms,
    }

    _last_report = report
    return report


def get_degraded_components() -> list:
    """Return the list of component names that are not in 'ok' state.

    Uses the most recent full_health_check() result if available, otherwise
    runs a fresh check with session_id="default".

    Returns:
        list of str, e.g. ["memory", "ramdisk"]
    """
    if _last_report:
        return list(_last_report.get("degraded_components", []))
    # No cached report — run a lightweight fresh check
    report = full_health_check("default")
    return list(report.get("degraded_components", []))


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Torus Framework Health Monitor")
    parser.add_argument(
        "--session-id", default="default", help="Session ID for state file lookup"
    )
    parser.add_argument(
        "--json", action="store_true", help="Output full report as JSON"
    )
    parser.add_argument(
        "--component", choices=list(_WEIGHTS.keys()),
        help="Check a single component only"
    )
    args = parser.parse_args()

    if args.component:
        check_fn = {
            COMPONENT_GATES: check_gates_health,
            COMPONENT_MEMORY: check_memory_health,
            COMPONENT_STATE: lambda: check_state_health(args.session_id),
            COMPONENT_RAMDISK: check_ramdisk_health,
            COMPONENT_AUDIT: check_audit_health,
        }[args.component]
        result = check_fn()
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"[{args.component.upper()}] status={result.get('status', '?')}")
            if result.get("error"):
                print(f"  error: {result['error']}")
    else:
        report = full_health_check(args.session_id)

        if args.json:
            print(json.dumps(report, indent=2))
        else:
            score = report["overall_score"]
            status = report["status"].upper()
            duration = report["duration_ms"]
            print(f"Framework Health: {status} (score={score}/100, {duration}ms)")
            print()
            for comp, data in report["components"].items():
                comp_status = data.get("status", "?")
                indicator = {"ok": "OK  ", "degraded": "WARN", "error": "FAIL"}.get(
                    comp_status, "????"
                )
                print(f"  [{indicator}] {comp}")
                if comp == COMPONENT_GATES and comp_status != "ok":
                    summary = data.get("summary", {})
                    print(
                        f"         gates ok={summary.get('ok', 0)}"
                        f" error={summary.get('error', 0)}"
                    )
                    for mod, mod_status in data.items():
                        if mod not in ("summary", "status") and "error" in mod_status:
                            print(f"         {mod}: {mod_status}")
                elif data.get("error"):
                    print(f"         {data['error']}")
            print()
            if report["degraded_components"]:
                print("Degraded components:")
                for comp in report["degraded_components"]:
                    suggestion = report["fallback_suggestions"].get(comp, "")
                    print(f"  - {comp}: {suggestion}")
