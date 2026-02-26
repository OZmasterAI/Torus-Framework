#!/usr/bin/env python3
"""Flush old ramdisk audit logs to disk backup (compressed).

Keeps the last KEEP_DAYS days on ramdisk, compresses older files to
~/.claude/hooks/audit/ as .gz, then removes originals from ramdisk.

Usage:
  python3 flush_audit.py          # flush files older than 2 days
  python3 flush_audit.py --days 1 # flush files older than 1 day
"""

import os
import sys
import gzip
import shutil
from datetime import date, timedelta

RAMDISK = "/run/user/1000/claude-hooks/audit"
DISK = os.path.expanduser("~/.claude/hooks/audit")
KEEP_DAYS = 2


def flush(keep_days=KEEP_DAYS):
    if not os.path.isdir(RAMDISK):
        print("Ramdisk audit dir not found, nothing to flush")
        return 0, 0

    os.makedirs(DISK, exist_ok=True)
    cutoff = date.today() - timedelta(days=keep_days)
    flushed = 0
    bytes_freed = 0

    for fname in sorted(os.listdir(RAMDISK)):
        if not fname.endswith(".jsonl") and not fname.endswith(".jsonl.1"):
            continue
        date_str = fname.split(".")[0]
        try:
            fdate = date.fromisoformat(date_str)
        except ValueError:
            continue
        if fdate >= cutoff:
            continue

        src = os.path.join(RAMDISK, fname)
        dst_gz = os.path.join(DISK, fname + ".gz")
        size = os.path.getsize(src)

        # Compress to disk
        with open(src, "rb") as f_in:
            with gzip.open(dst_gz, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)

        # Verify before removing
        if os.path.exists(dst_gz) and os.path.getsize(dst_gz) > 0:
            os.unlink(src)
            flushed += 1
            bytes_freed += size
            print(f"  {fname} ({size / 1024 / 1024:.1f}MB) -> {os.path.basename(dst_gz)}")
        else:
            print(f"  SKIP {fname} -- gz verification failed")

    print(f"\nFlushed: {flushed} files, freed {bytes_freed / 1024 / 1024:.1f}MB from ramdisk")
    return flushed, bytes_freed


if __name__ == "__main__":
    days = KEEP_DAYS
    if "--days" in sys.argv:
        idx = sys.argv.index("--days")
        if idx + 1 < len(sys.argv):
            days = int(sys.argv[idx + 1])
    flush(days)
