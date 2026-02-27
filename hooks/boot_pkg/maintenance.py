"""Maintenance operations for boot sequence — audit rotation and cleanup."""
import gzip
import os
import shutil
import sys
from datetime import datetime

from shared.state import cleanup_all_states

# Audit log rotation settings
_AUDIT_COMPRESS_AFTER_DAYS = 2   # Gzip .jsonl files older than this
_AUDIT_DELETE_AFTER_DAYS = 30    # Delete .gz files older than this (DORMANT — set to 0 to activate)
_AUDIT_DELETE_ENABLED = False    # Flip to True to enable deletion of old .gz files


def reset_enforcement_state():
    """Reset all gate enforcement state files for a new session."""
    cleanup_all_states()


def _rotate_audit_logs():
    """Compress old audit logs, optionally delete ancient ones.

    Runs on each session start. Compresses .jsonl files older than
    _AUDIT_COMPRESS_AFTER_DAYS. Deletion of old .gz is dormant by default.
    """
    hooks_dir = os.path.dirname(os.path.dirname(__file__))
    audit_dirs = [
        os.path.join(hooks_dir, "audit"),
        os.path.join(hooks_dir, ".disk_backup", "audit"),
    ]
    today = datetime.now().date()
    compressed = 0
    deleted = 0

    for audit_dir in audit_dirs:
        if not os.path.isdir(audit_dir):
            continue
        for fname in os.listdir(audit_dir):
            fpath = os.path.join(audit_dir, fname)
            if not os.path.isfile(fpath):
                continue

            # Compress: raw .jsonl (and .jsonl.N rotated) files older than threshold
            if ".jsonl" in fname and not fname.endswith(".gz"):
                file_age = (today - datetime.fromtimestamp(os.path.getmtime(fpath)).date()).days
                if file_age >= _AUDIT_COMPRESS_AFTER_DAYS:
                    try:
                        gz_path = fpath + ".gz"
                        with open(fpath, "rb") as f_in, gzip.open(gz_path, "wb") as f_out:
                            shutil.copyfileobj(f_in, f_out)
                        os.remove(fpath)
                        compressed += 1
                    except Exception:
                        pass  # Compression failure is non-fatal

            # Delete: old .gz files (DORMANT by default)
            elif fname.endswith(".gz") and _AUDIT_DELETE_ENABLED and _AUDIT_DELETE_AFTER_DAYS > 0:
                file_age = (today - datetime.fromtimestamp(os.path.getmtime(fpath)).date()).days
                if file_age >= _AUDIT_DELETE_AFTER_DAYS:
                    try:
                        os.remove(fpath)
                        deleted += 1
                    except Exception:
                        pass

    if compressed or deleted:
        parts = []
        if compressed:
            parts.append(f"{compressed} compressed")
        if deleted:
            parts.append(f"{deleted} deleted")
        print(f"  [BOOT] Audit rotation: {', '.join(parts)}", file=sys.stderr)
