#!/usr/bin/env python3
"""Audit Log Rotation — Compresses old logs, deletes ancient ones.

Manages disk usage for the framework's audit trail:
- Compresses .jsonl files older than 7 days to .jsonl.gz
- Deletes .jsonl.gz files older than 30 days
- Reports disk usage before and after

Usage:
    python3 audit_rotation.py              # Dry run
    python3 audit_rotation.py --execute    # Actually rotate
    python3 audit_rotation.py --days-compress 3 --days-delete 14
"""

import argparse
import gzip
import os
import shutil
import sys
import time
from datetime import date, timedelta

AUDIT_DIRS = [
    os.path.join(os.path.expanduser("~"), ".claude", "hooks", "audit"),
    "/run/user/1000/claude-hooks/audit",
]

DEFAULT_COMPRESS_DAYS = 7
DEFAULT_DELETE_DAYS = 30


def _dir_size(path):
    """Calculate total size of a directory in bytes."""
    total = 0
    if not os.path.isdir(path):
        return 0
    for entry in os.scandir(path):
        if entry.is_file():
            total += entry.stat().st_size
    return total


def scan_audit_files():
    """Scan all audit directories for log files.

    Returns list of dicts: [{path, filename, ext, date_str, age_days, size_bytes}]
    """
    files = []
    today = date.today()

    for audit_dir in AUDIT_DIRS:
        if not os.path.isdir(audit_dir):
            continue
        for entry in os.scandir(audit_dir):
            if not entry.is_file():
                continue
            name = entry.name
            # Parse date from filename (YYYY-MM-DD.jsonl or YYYY-MM-DD.jsonl.gz)
            date_str = name.split(".")[0]
            try:
                file_date = date.fromisoformat(date_str)
                age_days = (today - file_date).days
            except ValueError:
                continue

            ext = ".jsonl.gz" if name.endswith(".jsonl.gz") else ".jsonl" if name.endswith(".jsonl") else ""
            if not ext:
                continue

            files.append({
                "path": entry.path,
                "filename": name,
                "ext": ext,
                "date_str": date_str,
                "age_days": age_days,
                "size_bytes": entry.stat().st_size,
            })

    return sorted(files, key=lambda x: x["date_str"])


def rotate(compress_days=DEFAULT_COMPRESS_DAYS, delete_days=DEFAULT_DELETE_DAYS, dry_run=True):
    """Execute audit log rotation.

    Returns dict with rotation results.
    """
    files = scan_audit_files()

    # Calculate before size
    before_size = sum(f["size_bytes"] for f in files)

    compressed = []
    deleted = []
    errors = []

    for f in files:
        # Delete old compressed files
        if f["ext"] == ".jsonl.gz" and f["age_days"] > delete_days:
            if not dry_run:
                try:
                    os.unlink(f["path"])
                    deleted.append(f["filename"])
                except OSError as e:
                    errors.append(f"Delete {f['filename']}: {e}")
            else:
                deleted.append(f["filename"])
            continue

        # Compress old uncompressed files
        if f["ext"] == ".jsonl" and f["age_days"] > compress_days:
            gz_path = f["path"] + ".gz"
            if not dry_run:
                try:
                    with open(f["path"], "rb") as f_in:
                        with gzip.open(gz_path, "wb", compresslevel=6) as f_out:
                            shutil.copyfileobj(f_in, f_out)
                    os.unlink(f["path"])
                    compressed.append(f["filename"])
                except Exception as e:
                    errors.append(f"Compress {f['filename']}: {e}")
            else:
                compressed.append(f["filename"])

    # Calculate after size
    after_files = scan_audit_files() if not dry_run else files
    after_size = sum(f["size_bytes"] for f in after_files) if not dry_run else before_size

    return {
        "dry_run": dry_run,
        "total_files": len(files),
        "compressed": len(compressed),
        "deleted": len(deleted),
        "errors": errors,
        "before_size_mb": round(before_size / (1024 * 1024), 2),
        "after_size_mb": round(after_size / (1024 * 1024), 2),
        "saved_mb": round((before_size - after_size) / (1024 * 1024), 2) if not dry_run else 0,
    }


def main():
    parser = argparse.ArgumentParser(description="Audit Log Rotation")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--days-compress", type=int, default=DEFAULT_COMPRESS_DAYS)
    parser.add_argument("--days-delete", type=int, default=DEFAULT_DELETE_DAYS)
    args = parser.parse_args()

    result = rotate(args.days_compress, args.days_delete, dry_run=not args.execute)

    mode = "EXECUTED" if args.execute else "DRY RUN"
    print(f"Audit Rotation ({mode})")
    print(f"  Files scanned: {result['total_files']}")
    print(f"  Compressed: {result['compressed']}")
    print(f"  Deleted: {result['deleted']}")
    print(f"  Disk: {result['before_size_mb']}MB -> {result['after_size_mb']}MB")
    if result['errors']:
        print(f"  Errors: {len(result['errors'])}")


if __name__ == "__main__":
    main()
