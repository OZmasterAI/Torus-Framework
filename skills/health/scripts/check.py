#!/usr/bin/env python3
"""Torus Framework Health Diagnostic.

Usage:
    python3 check.py [--repair]

Runs 8 checks and prints a JSON report plus human-readable summary.
All checks are read-only by default; --repair enables safe fixes.
"""

import datetime
import glob
import json
import os
import subprocess
import sys
import time

# ── Path constants ─────────────────────────────────────────────────────────────

CLAUDE_DIR = os.path.join(os.path.expanduser("~"), ".claude")
HOOKS_DIR = os.path.join(CLAUDE_DIR, "hooks")
GATES_DIR = os.path.join(HOOKS_DIR, "gates")
AUDIT_DIR = os.path.join(HOOKS_DIR, "audit")
FILE_CLAIMS_PATH = os.path.join(HOOKS_DIR, ".file_claims.json")
MEMORY_DIR = os.path.join(os.path.expanduser("~"), "data", "memory")
CHROMADB_DB = os.path.join(MEMORY_DIR, "chroma.sqlite3")
MEMORY_SERVER = os.path.join(HOOKS_DIR, "memory_server.py")
PRPS_DIR = os.path.join(CLAUDE_DIR, "PRPs")

# Ramdisk path uses current uid
_UID = os.getuid()
RAMDISK_DIR = f"/run/user/{_UID}/claude-hooks"

# Make shared modules importable
sys.path.insert(0, HOOKS_DIR)

REPAIR_MODE = "--repair" in sys.argv

# ── Status helpers ─────────────────────────────────────────────────────────────

STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_FAIL = "fail"

ICON = {STATUS_OK: "✓", STATUS_WARN: "⚠", STATUS_FAIL: "✗"}


def _result(status, detail, **extra):
    r = {"status": status, "detail": detail}
    r.update(extra)
    return r


# ── Check 1: Memory MCP ────────────────────────────────────────────────────────

def check_memory_mcp():
    """Check if Memory MCP is running and ChromaDB is accessible."""
    issues = []

    # Check 1: ChromaDB database file exists and is readable
    if not os.path.exists(CHROMADB_DB):
        issues.append("ChromaDB not found at " + CHROMADB_DB)
    elif not os.access(CHROMADB_DB, os.R_OK):
        issues.append("ChromaDB exists but not readable")

    # Check 2: memory_server.py process is running
    try:
        result = subprocess.run(
            ["pgrep", "-f", "memory_server.py"],
            capture_output=True, text=True, timeout=5,
        )
        process_running = result.returncode == 0
    except Exception:
        process_running = False

    if not process_running:
        issues.append("memory_server.py process not running")

    # Check 3: Get DB size for info
    db_size = ""
    if os.path.exists(CHROMADB_DB):
        size_mb = os.path.getsize(CHROMADB_DB) / (1024 * 1024)
        db_size = f", DB: {size_mb:.1f}MB"

    if not issues:
        return _result(STATUS_OK, f"process running, ChromaDB accessible{db_size}")
    elif process_running or os.path.exists(CHROMADB_DB):
        # Partially working
        return _result(STATUS_WARN, "; ".join(issues) + db_size)
    else:
        return _result(STATUS_FAIL, "; ".join(issues))


# ── Check 2: Gates ─────────────────────────────────────────────────────────────

def check_gates():
    """Verify all gate_*.py files exist and are valid Python."""
    gate_files = sorted(glob.glob(os.path.join(GATES_DIR, "gate_*.py")))
    if not gate_files:
        return _result(STATUS_FAIL, "no gate files found in " + GATES_DIR)

    invalid = []
    for gate_path in gate_files:
        try:
            with open(gate_path, "r") as f:
                source = f.read()
            compile(source, gate_path, "exec")
        except SyntaxError as e:
            invalid.append(f"{os.path.basename(gate_path)}: {e}")
        except OSError as e:
            invalid.append(f"{os.path.basename(gate_path)}: unreadable ({e})")

    total = len(gate_files)
    if invalid:
        return _result(
            STATUS_FAIL,
            f"{total} gates, {len(invalid)} invalid: {'; '.join(invalid)}",
        )
    return _result(STATUS_OK, f"{total} gates, all valid")


# ── Check 3: State Files ───────────────────────────────────────────────────────

def check_state_files():
    """Check state_*.json files are valid JSON with correct schema."""
    repairs = []

    # State files may be on ramdisk or disk — check both locations
    search_dirs = [
        os.path.join(RAMDISK_DIR, "state"),
        HOOKS_DIR,
    ]

    state_files = []
    for d in search_dirs:
        state_files.extend(glob.glob(os.path.join(d, "state_*.json")))

    # Deduplicate (same filename in different dirs is actually different files)
    state_files = list(dict.fromkeys(state_files))

    if not state_files:
        return _result(STATUS_OK, "0 files, none active"), repairs

    corrupt = []
    for sf in state_files:
        try:
            with open(sf) as f:
                data = json.load(f)
            if "_version" not in data:
                corrupt.append(os.path.basename(sf) + " (missing _version)")
                if REPAIR_MODE:
                    _repair_state_file(sf, repairs)
        except json.JSONDecodeError:
            corrupt.append(os.path.basename(sf) + " (corrupt JSON)")
            if REPAIR_MODE:
                _repair_state_file(sf, repairs)
        except OSError:
            pass  # File disappeared between glob and read — ignore

    total = len(state_files)
    if corrupt:
        status = STATUS_WARN if REPAIR_MODE and repairs else STATUS_FAIL
        return _result(
            status,
            f"{total} files, {len(corrupt)} corrupt: {', '.join(corrupt)}",
        ), repairs

    return _result(STATUS_OK, f"{total} files, all valid"), repairs


def _repair_state_file(path, repairs):
    """Reset a corrupt state file to default_state()."""
    try:
        from shared.state import default_state, save_state
        session_id = os.path.basename(path).replace("state_", "").replace(".json", "")
        save_state(default_state(), session_id=session_id)
        repairs.append(f"reset corrupt state: {os.path.basename(path)}")
    except Exception as e:
        repairs.append(f"failed to reset {os.path.basename(path)}: {e}")


# ── Check 4: Ramdisk ──────────────────────────────────────────────────────────

def check_ramdisk():
    """Check if the tmpfs ramdisk is mounted and writable."""
    if not os.path.isdir(RAMDISK_DIR):
        return _result(STATUS_WARN, f"not mounted at {RAMDISK_DIR}")

    test_file = os.path.join(RAMDISK_DIR, ".health_write_test")
    try:
        with open(test_file, "w") as f:
            f.write("ok")
        os.remove(test_file)
        return _result(STATUS_OK, f"available at {RAMDISK_DIR}")
    except (OSError, IOError) as e:
        return _result(STATUS_FAIL, f"exists but not writable: {e}")


# ── Check 5: File Claims ───────────────────────────────────────────────────────

def check_file_claims():
    """Check .file_claims.json for stale claims (>2 hours old)."""
    repairs = []
    now = time.time()
    stale_threshold = 2 * 3600  # 2 hours in seconds

    if not os.path.exists(FILE_CLAIMS_PATH):
        return _result(STATUS_OK, "0 active, 0 stale (no claims file)"), repairs

    try:
        with open(FILE_CLAIMS_PATH) as f:
            claims = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return _result(STATUS_WARN, f"claims file unreadable: {e}"), repairs

    if not isinstance(claims, dict):
        return _result(STATUS_WARN, "claims file has unexpected format"), repairs

    total = len(claims)
    stale = {
        path: info
        for path, info in claims.items()
        if isinstance(info, dict) and (now - info.get("claimed_at", now)) > stale_threshold
    }

    if stale and REPAIR_MODE:
        fresh_claims = {p: i for p, i in claims.items() if p not in stale}
        try:
            tmp = FILE_CLAIMS_PATH + ".tmp"
            with open(tmp, "w") as f:
                json.dump(fresh_claims, f, indent=2)
            os.replace(tmp, FILE_CLAIMS_PATH)
            repairs.append(f"removed {len(stale)} stale file claims")
        except OSError as e:
            repairs.append(f"failed to remove stale claims: {e}")

    status = STATUS_OK if not stale else STATUS_WARN
    detail = f"{total} active, {len(stale)} stale"
    return _result(status, detail), repairs


# ── Check 6: Audit Logs ────────────────────────────────────────────────────────

def check_audit_logs():
    """Check today's audit log exists and isn't oversized."""
    today = datetime.date.today().strftime("%Y-%m-%d")
    size_warn_bytes = 5 * 1024 * 1024  # 5 MB

    # Check both ramdisk and disk audit dirs
    audit_dirs = [
        os.path.join(RAMDISK_DIR, "audit"),
        AUDIT_DIR,
        os.path.join(HOOKS_DIR, ".disk_backup", "audit"),
    ]

    found_path = None
    found_size = 0
    for d in audit_dirs:
        candidate = os.path.join(d, f"{today}.jsonl")
        if os.path.exists(candidate):
            found_path = candidate
            found_size = os.path.getsize(candidate)
            break

    if not found_path:
        return _result(STATUS_WARN, f"today's log ({today}.jsonl) not found")

    size_kb = found_size / 1024
    if size_kb >= 1024:
        size_str = f"{size_kb / 1024:.1f}MB"
    else:
        size_str = f"{size_kb:.0f}KB"

    if found_size > size_warn_bytes:
        return _result(STATUS_WARN, f"today's log: {size_str} (>5MB, consider archiving)")

    return _result(STATUS_OK, f"today's log: {size_str}")


# ── Check 7: Deferred Items ────────────────────────────────────────────────────

def check_deferred_items():
    """Count deferred items from Gate 9 PRP deferred files."""
    deferred_files = glob.glob(os.path.join(PRPS_DIR, "*.deferred.md"))

    if not deferred_files:
        return _result(STATUS_OK, "0 deferred")

    total_entries = 0
    per_prp = {}
    for df in deferred_files:
        prp_name = os.path.basename(df).replace(".deferred.md", "")
        try:
            with open(df) as f:
                count = sum(1 for line in f if line.startswith("###"))
            per_prp[prp_name] = count
            total_entries += count
        except OSError:
            pass

    if total_entries == 0:
        return _result(STATUS_OK, "0 deferred")

    breakdown = ", ".join(f"{k}: {v}" for k, v in per_prp.items())
    status = STATUS_WARN if total_entries > 5 else STATUS_OK
    return _result(status, f"{total_entries} deferred ({breakdown})")


# ── Check 8: PRPs ──────────────────────────────────────────────────────────────

def check_prps():
    """Check PRP task files for stuck in_progress tasks (>2 hours)."""
    now = time.time()
    stuck_threshold = 2 * 3600
    task_files = glob.glob(os.path.join(PRPS_DIR, "*.tasks.json"))
    # Exclude templates directory
    task_files = [f for f in task_files if "templates" not in f]

    if not task_files:
        return _result(STATUS_OK, "0 active PRPs")

    active_count = len(task_files)
    stuck = []

    for tf in task_files:
        prp_name = os.path.basename(tf).replace(".tasks.json", "")
        try:
            with open(tf) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        tasks = data.get("tasks", [])
        for task in tasks:
            if task.get("status") != "in_progress":
                continue
            # Try to detect stuck tasks via started_at timestamp
            started_at = task.get("started_at")
            if started_at is None:
                continue
            try:
                if isinstance(started_at, str):
                    # Parse ISO format
                    dt = datetime.datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                    started_ts = dt.timestamp()
                else:
                    started_ts = float(started_at)
                if (now - started_ts) > stuck_threshold:
                    stuck.append(f"{prp_name}#{task.get('id', '?')}")
            except (ValueError, TypeError):
                pass

    if stuck:
        return _result(
            STATUS_WARN,
            f"{active_count} active, {len(stuck)} stuck: {', '.join(stuck)}",
        )
    return _result(STATUS_OK, f"{active_count} active, 0 stuck")


# ── Overall status ─────────────────────────────────────────────────────────────

def overall_status(checks):
    """Derive overall status from individual check results."""
    statuses = [v["status"] for v in checks.values()]
    if STATUS_FAIL in statuses:
        return "unhealthy"
    if STATUS_WARN in statuses:
        return "degraded"
    return "healthy"


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    all_repairs = []

    # Run all checks
    memory_result = check_memory_mcp()
    gates_result = check_gates()
    state_result, state_repairs = check_state_files()
    ramdisk_result = check_ramdisk()
    claims_result, claims_repairs = check_file_claims()
    audit_result = check_audit_logs()
    deferred_result = check_deferred_items()
    prps_result = check_prps()

    all_repairs.extend(state_repairs)
    all_repairs.extend(claims_repairs)

    checks = {
        "memory_mcp": memory_result,
        "gates": gates_result,
        "state_files": state_result,
        "ramdisk": ramdisk_result,
        "file_claims": claims_result,
        "audit_logs": audit_result,
        "deferred_items": deferred_result,
        "prps": prps_result,
    }

    status = overall_status(checks)
    timestamp = datetime.datetime.now().isoformat(timespec="seconds")

    report = {
        "status": status,
        "checks": checks,
        "repairs": all_repairs,
        "timestamp": timestamp,
    }

    # ── Human-readable summary ─────────────────────────────────────────────────
    labels = {
        "memory_mcp": "Memory MCP",
        "gates": "Gates",
        "state_files": "State files",
        "ramdisk": "Ramdisk",
        "file_claims": "File claims",
        "audit_logs": "Audit logs",
        "deferred_items": "Deferred items",
        "prps": "PRPs",
    }

    print("Torus Framework Health Check")
    print("═" * 29)
    for key, label in labels.items():
        r = checks[key]
        icon = ICON[r["status"]]
        print(f"{icon} {label}: {r['detail']}")

    if all_repairs:
        print()
        print("Repairs performed:")
        for r in all_repairs:
            print(f"  - {r}")

    print()
    print(f"Status: {status.upper()}")

    # ── JSON report ────────────────────────────────────────────────────────────
    print()
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
