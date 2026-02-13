"""JSONL audit trail for the Self-Healing Claude Framework.

Logs every gate decision (pass, block, warn) to a daily JSONL file
under ~/.claude/hooks/audit/YYYY-MM-DD.jsonl. Designed to never raise
exceptions so it cannot interfere with gate enforcement.

Features:
- File rotation: when a log file exceeds 5MB, rotate to .1, compress old .1
- Max 10 rotated files per day-file
- Compaction: aggregate daily summaries into audit/summary.json
- Cleanup: delete audit files older than 90 days
"""

import gzip
import json
import os
import time
from datetime import datetime, timezone


AUDIT_DIR = os.path.join(os.path.expanduser("~"), ".claude", "hooks", "audit")
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
MAX_ROTATED_FILES = 10
CLEANUP_AGE_DAYS = 90


def _rotate_file(filepath):
    """Rotate a log file: current -> .1, compress old .1 -> .1.gz, shift others.

    Keeps max MAX_ROTATED_FILES rotated copies. Oldest are deleted.
    """
    try:
        # Shift existing rotated files upward (.9 -> .10 gets deleted, .8 -> .9, etc.)
        for i in range(MAX_ROTATED_FILES, 0, -1):
            gz_old = f"{filepath}.{i}.gz"
            gz_new = f"{filepath}.{i + 1}.gz"
            if i >= MAX_ROTATED_FILES:
                # Delete files beyond the max
                if os.path.exists(gz_old):
                    os.remove(gz_old)
                continue
            if os.path.exists(gz_old):
                os.rename(gz_old, gz_new)

        # Compress existing .1 to .1.gz (if it exists)
        rotated_1 = f"{filepath}.1"
        if os.path.exists(rotated_1):
            gz_path = f"{filepath}.1.gz"
            # Shift .1.gz up to .2.gz first (already done in loop above)
            with open(rotated_1, "rb") as f_in:
                with gzip.open(gz_path, "wb") as f_out:
                    f_out.write(f_in.read())
            os.remove(rotated_1)

        # Move current file to .1
        if os.path.exists(filepath):
            os.rename(filepath, rotated_1)

        # Delete any rotated files beyond MAX_ROTATED_FILES
        for i in range(MAX_ROTATED_FILES + 1, MAX_ROTATED_FILES + 5):
            excess = f"{filepath}.{i}.gz"
            if os.path.exists(excess):
                os.remove(excess)
    except Exception:
        pass  # Rotation failure must not break logging


def log_gate_decision(gate_name, tool_name, decision, reason, session_id="", state_keys=None, severity="info"):
    """Append a gate decision record to today's audit log.

    Args:
        gate_name: Name of the gate (e.g. "Gate 1: READ BEFORE EDIT").
        tool_name: The tool being checked (e.g. "Edit", "Bash").
        decision: One of "pass", "block", or "warn".
        reason: Human-readable explanation of the decision.
        session_id: Optional session identifier for correlation.
        state_keys: Optional list of state keys accessed during the gate check.
        severity: Severity level - "info", "warn", "error", or "critical".
    """
    try:
        os.makedirs(AUDIT_DIR, exist_ok=True)

        now = datetime.now(timezone.utc)
        filename = now.strftime("%Y-%m-%d") + ".jsonl"
        filepath = os.path.join(AUDIT_DIR, filename)

        # Check if rotation is needed before writing
        if os.path.exists(filepath):
            try:
                size = os.path.getsize(filepath)
                if size > MAX_FILE_SIZE:
                    _rotate_file(filepath)
            except OSError:
                pass

        entry = {
            "timestamp": now.isoformat(),
            "gate": gate_name,
            "tool": tool_name,
            "decision": decision,
            "reason": reason,
            "session_id": session_id,
            "state_keys": state_keys or [],
            "severity": severity,
        }

        with open(filepath, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


# Alias for backward compatibility
log_event = log_gate_decision


def compact_audit_logs():
    """Aggregate all JSONL audit files into daily summaries.

    Reads all .jsonl files from the audit directory, aggregates gate decisions
    by date, and writes a summary to audit/summary.json.

    Returns:
        dict: Summary data written to file, or error info.
    """
    try:
        os.makedirs(AUDIT_DIR, exist_ok=True)

        daily_stats = {}  # {date_str: {gate_name: {pass: N, block: N, warn: N}}}

        # Process all JSONL files (including rotated .1 files)
        for fname in os.listdir(AUDIT_DIR):
            fpath = os.path.join(AUDIT_DIR, fname)

            if fname.endswith(".jsonl"):
                _process_jsonl_file(fpath, daily_stats)
            elif fname.endswith(".jsonl.1"):
                _process_jsonl_file(fpath, daily_stats)
            elif fname.endswith(".gz"):
                _process_gzipped_file(fpath, daily_stats)

        # Build summary
        summary = []
        for date_str in sorted(daily_stats.keys()):
            gates = daily_stats[date_str]
            total_events = sum(
                gates[g].get("pass", 0) + gates[g].get("block", 0) + gates[g].get("warn", 0)
                for g in gates
            )
            summary.append({
                "date": date_str,
                "gates": gates,
                "total_events": total_events,
            })

        summary_path = os.path.join(AUDIT_DIR, "summary.json")
        tmp_path = summary_path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(summary, f, indent=2)
        os.replace(tmp_path, summary_path)

        return {"summary_file": summary_path, "days": len(summary), "status": "ok"}

    except Exception as e:
        return {"error": str(e), "status": "failed"}


def _process_jsonl_file(fpath, daily_stats):
    """Process a plain JSONL file and aggregate into daily_stats."""
    try:
        with open(fpath, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    _aggregate_entry(entry, daily_stats)
                except json.JSONDecodeError:
                    continue
    except (IOError, OSError):
        pass


def _process_gzipped_file(fpath, daily_stats):
    """Process a gzip-compressed JSONL file and aggregate into daily_stats."""
    try:
        with gzip.open(fpath, "rt") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    _aggregate_entry(entry, daily_stats)
                except json.JSONDecodeError:
                    continue
    except (IOError, OSError, gzip.BadGzipFile):
        pass


def _aggregate_entry(entry, daily_stats):
    """Aggregate a single audit entry into the daily_stats dict."""
    ts = entry.get("timestamp", "")
    gate = entry.get("gate", "unknown")
    decision = entry.get("decision", "unknown")
    severity = entry.get("severity", "info")

    # Extract date from ISO timestamp
    date_str = ts[:10] if len(ts) >= 10 else "unknown"

    if date_str not in daily_stats:
        daily_stats[date_str] = {}
    if gate not in daily_stats[date_str]:
        daily_stats[date_str][gate] = {
            "pass": 0, "block": 0, "warn": 0,
            "severity_dist": {"info": 0, "warn": 0, "error": 0, "critical": 0},
        }

    if decision in ("pass", "block", "warn"):
        daily_stats[date_str][gate][decision] += 1

    if severity in ("info", "warn", "error", "critical"):
        daily_stats[date_str][gate]["severity_dist"][severity] += 1
    else:
        daily_stats[date_str][gate]["severity_dist"]["info"] += 1


def cleanup_old_audit_files(max_age_days=CLEANUP_AGE_DAYS):
    """Delete audit files older than max_age_days.

    Checks file modification time. Removes .jsonl, .jsonl.N, and .gz files.

    Args:
        max_age_days: Maximum age in days before deletion (default 90).

    Returns:
        dict: Number of files deleted and any errors.
    """
    deleted = 0
    errors = 0
    cutoff = time.time() - (max_age_days * 86400)

    try:
        if not os.path.isdir(AUDIT_DIR):
            return {"deleted": 0, "errors": 0, "status": "no_audit_dir"}

        for fname in os.listdir(AUDIT_DIR):
            # Only process audit-related files
            if not (fname.endswith(".jsonl") or ".jsonl." in fname or fname.endswith(".gz")):
                continue
            # Don't delete summary.json
            if fname == "summary.json" or fname.endswith(".tmp"):
                continue

            fpath = os.path.join(AUDIT_DIR, fname)
            try:
                mtime = os.path.getmtime(fpath)
                if mtime < cutoff:
                    os.remove(fpath)
                    deleted += 1
            except OSError:
                errors += 1

    except Exception:
        errors += 1

    return {"deleted": deleted, "errors": errors, "status": "ok"}
