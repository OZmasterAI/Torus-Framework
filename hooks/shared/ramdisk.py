"""Hybrid tmpfs ramdisk for hook I/O optimization.

Moves hot files (audit logs, state, capture queue) to /run/user/<uid>/claude-hooks
which is a per-user tmpfs on systemd Linux (~544 MB/s vs ~1.2 MB/s disk writes).

Audit logs get an async disk mirror (daemon thread) for zero data loss.
State files and capture queue are ephemeral — no mirror needed.

Graceful fallback: if tmpfs is unavailable, all callers get the original disk paths.
"""

import os
import shutil
from concurrent.futures import ThreadPoolExecutor

# Bounded thread pool for async disk mirror writes (replaces per-write Thread spawning)
_mirror_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ramdisk-mirror")

# ── Path constants ────────────────────────────────────────────────────────────

_UID = os.getuid()
RAMDISK_DIR = f"/run/user/{_UID}/claude-hooks"
BACKUP_DIR = os.path.join(os.path.expanduser("~"), ".claude", "hooks", ".disk_backup")

# tmpfs subdirectories
TMPFS_AUDIT_DIR = os.path.join(RAMDISK_DIR, "audit")
TMPFS_STATE_DIR = os.path.join(RAMDISK_DIR, "state")
TMPFS_CAPTURE_QUEUE = os.path.join(RAMDISK_DIR, "capture_queue.jsonl")

# Disk backup subdirectories (mirrors tmpfs audit)
BACKUP_AUDIT_DIR = os.path.join(BACKUP_DIR, "audit")

# Original disk paths (fallback)
_HOOKS_DIR = os.path.join(os.path.expanduser("~"), ".claude", "hooks")
DISK_AUDIT_DIR = os.path.join(_HOOKS_DIR, "audit")
DISK_STATE_DIR = _HOOKS_DIR
DISK_CAPTURE_QUEUE = os.path.join(_HOOKS_DIR, ".capture_queue.jsonl")


# ── Availability check ────────────────────────────────────────────────────────

def is_ramdisk_available():
    """Check if the tmpfs ramdisk is set up and writable.

    Returns True only if the ramdisk base dir exists and is on tmpfs.
    Cached after first call for the lifetime of the process.
    """
    return _is_ramdisk_available_cached()


def _check_ramdisk():
    """Actual check — called once, result cached."""
    try:
        if not os.path.isdir(RAMDISK_DIR):
            return False
        # Verify it's writable
        test_file = os.path.join(RAMDISK_DIR, ".write_test")
        with open(test_file, "w") as f:
            f.write("ok")
        os.remove(test_file)
        return True
    except (OSError, IOError):
        return False


# Simple caching via closure
_cached_result = None


def _is_ramdisk_available_cached():
    global _cached_result
    if _cached_result is None:
        _cached_result = _check_ramdisk()
    return _cached_result


def invalidate_cache():
    """Reset the cached availability check (used after ensure_ramdisk)."""
    global _cached_result
    _cached_result = None


# ── Path resolution helpers ───────────────────────────────────────────────────

def get_audit_dir():
    """Return the active audit directory (tmpfs or disk)."""
    return TMPFS_AUDIT_DIR if is_ramdisk_available() else DISK_AUDIT_DIR


def get_state_dir():
    """Return the active state directory (tmpfs or disk)."""
    return TMPFS_STATE_DIR if is_ramdisk_available() else DISK_STATE_DIR


def get_capture_queue():
    """Return the active capture queue path (tmpfs or disk)."""
    return TMPFS_CAPTURE_QUEUE if is_ramdisk_available() else DISK_CAPTURE_QUEUE


# ── Setup ─────────────────────────────────────────────────────────────────────

def ensure_ramdisk():
    """Create tmpfs directory structure if parent tmpfs exists.

    Called by boot.py on session start. Creates:
      /run/user/<uid>/claude-hooks/
      /run/user/<uid>/claude-hooks/audit/
      /run/user/<uid>/claude-hooks/state/
      ~/.claude/hooks/.disk_backup/audit/

    Then restores any backed-up audit data to tmpfs.
    Returns True if ramdisk is now available, False otherwise.
    """
    try:
        # Check that the user's run directory exists (systemd tmpfs)
        user_run = f"/run/user/{_UID}"
        if not os.path.isdir(user_run):
            return False

        # Create tmpfs dirs
        os.makedirs(TMPFS_AUDIT_DIR, exist_ok=True)
        os.makedirs(TMPFS_STATE_DIR, exist_ok=True)

        # Create disk backup dirs
        os.makedirs(BACKUP_AUDIT_DIR, exist_ok=True)

        # Restore from backup (crash recovery)
        restore_from_backup()

        # Invalidate cache so subsequent calls see the new dirs
        invalidate_cache()

        return is_ramdisk_available()
    except (OSError, IOError):
        return False


# ── Async disk mirror ─────────────────────────────────────────────────────────

def async_mirror_append(tmpfs_path, content):
    """Write content to tmpfs path, then asynchronously mirror to disk backup.

    The tmpfs write is synchronous (fast — RAM speed).
    The disk mirror is fire-and-forget via a daemon thread.

    Args:
        tmpfs_path: Full path on tmpfs (e.g., /run/user/1000/claude-hooks/audit/2026-02-14.jsonl)
        content: String content to append (should include trailing newline)
    """
    # Synchronous tmpfs write
    try:
        os.makedirs(os.path.dirname(tmpfs_path), exist_ok=True)
        with open(tmpfs_path, "a") as f:
            f.write(content)
    except (OSError, IOError):
        return  # tmpfs write failed — nothing to mirror

    # Async disk backup (daemon thread — dies with process, fail-open)
    def _mirror():
        try:
            # Compute the corresponding backup path
            rel = os.path.relpath(tmpfs_path, RAMDISK_DIR)
            backup_path = os.path.join(BACKUP_DIR, rel)
            os.makedirs(os.path.dirname(backup_path), exist_ok=True)
            with open(backup_path, "a") as f:
                f.write(content)
        except (OSError, IOError):
            pass  # Mirror failure is non-fatal

    _mirror_pool.submit(_mirror)


# ── Backup / Restore ─────────────────────────────────────────────────────────

def restore_from_backup():
    """Copy backed-up audit files from disk to tmpfs on session start.

    Only restores files that don't already exist on tmpfs (no clobber).
    Handles the case where tmpfs was cleared (reboot) but disk backup persists.
    """
    try:
        if not os.path.isdir(BACKUP_AUDIT_DIR):
            return

        for fname in os.listdir(BACKUP_AUDIT_DIR):
            src = os.path.join(BACKUP_AUDIT_DIR, fname)
            dst = os.path.join(TMPFS_AUDIT_DIR, fname)
            if os.path.isfile(src) and not os.path.exists(dst):
                # Only restore .jsonl files (not compressed archives)
                if fname.endswith(".jsonl"):
                    shutil.copy2(src, dst)
    except (OSError, IOError):
        pass  # Restore failure is non-fatal


def sync_to_backup():
    """Sync all tmpfs files to disk backup.

    Called by the systemd shutdown hook and can be invoked manually.
    Copies all current tmpfs audit files to disk backup, overwriting stale versions.
    """
    try:
        if not os.path.isdir(TMPFS_AUDIT_DIR):
            return

        os.makedirs(BACKUP_AUDIT_DIR, exist_ok=True)

        for fname in os.listdir(TMPFS_AUDIT_DIR):
            src = os.path.join(TMPFS_AUDIT_DIR, fname)
            dst = os.path.join(BACKUP_AUDIT_DIR, fname)
            if os.path.isfile(src):
                shutil.copy2(src, dst)
    except (OSError, IOError):
        pass  # Sync failure logged but non-fatal


# ── CLI entry point for systemd service ───────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "sync":
        sync_to_backup()
        print("Synced tmpfs to disk backup.")
    elif len(sys.argv) > 1 and sys.argv[1] == "setup":
        ok = ensure_ramdisk()
        print(f"Ramdisk setup: {'OK' if ok else 'FAILED'}")
    else:
        print(f"Ramdisk available: {is_ramdisk_available()}")
        print(f"  RAMDISK_DIR: {RAMDISK_DIR}")
        print(f"  BACKUP_DIR: {BACKUP_DIR}")
