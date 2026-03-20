"""Cross-agent file coordination — prevents parallel agents from clobbering edits.

Uses fcntl.flock on per-file lock files stored on ramdisk at:
  /run/user/{uid}/claude-hooks/locks/

Each file being edited gets a corresponding .lock file (path-hash based).
Locks include the owning session_id and a timestamp. Stale locks (older than
timeout) are automatically cleaned up on acquire.

Fail-open: if anything in this module crashes, callers should allow the
edit anyway. The enforcer wraps all calls in try/except.
"""

import fcntl
import hashlib
import json
import os
import time

# Lock directory on ramdisk (fast, ephemeral — cleared on reboot)
_UID = os.getuid()
_LOCK_DIR = f"/run/user/{_UID}/claude-hooks/locks"

# Fallback lock dir if ramdisk unavailable
_FALLBACK_LOCK_DIR = os.path.join(
    os.path.expanduser("~"), ".claude", "hooks", ".locks"
)

# Default lock timeout in seconds
DEFAULT_TIMEOUT = 30


def _get_lock_dir():
    """Return the active lock directory, creating it if needed.

    Prefers ramdisk; falls back to disk if ramdisk unavailable.
    Returns None if neither can be created (fail-open: caller should allow).
    """
    for d in (_LOCK_DIR, _FALLBACK_LOCK_DIR):
        try:
            os.makedirs(d, exist_ok=True)
            # Verify writable
            test_path = os.path.join(d, ".write_test")
            with open(test_path, "w") as f:
                f.write("ok")
            os.remove(test_path)
            return d
        except (OSError, IOError):
            continue
    return None


def _lock_file_path(file_path, lock_dir=None):
    """Return the lock file path for a given target file.

    Uses a SHA-256 hash of the normalized file path to avoid
    filesystem issues with deep paths or special characters.
    """
    if lock_dir is None:
        lock_dir = _get_lock_dir()
        if lock_dir is None:
            return None
    normalized = os.path.normpath(os.path.abspath(file_path))
    path_hash = hashlib.sha256(normalized.encode()).hexdigest()[:16]
    return os.path.join(lock_dir, f"{path_hash}.lock")


def _read_lock_meta(lock_path):
    """Read the metadata from a lock file (session_id, timestamp, file_path).

    Returns dict or None if unreadable.
    """
    try:
        with open(lock_path, "r") as f:
            return json.load(f)
    except (OSError, IOError, json.JSONDecodeError, ValueError):
        return None


def _write_lock_meta(lock_path, session_id, file_path):
    """Write lock metadata atomically."""
    meta = {
        "session_id": session_id,
        "file_path": os.path.normpath(os.path.abspath(file_path)),
        "acquired_at": time.time(),
        "pid": os.getpid(),
    }
    tmp_path = lock_path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(meta, f)
    os.rename(tmp_path, lock_path)


def acquire_lock(file_path, session_id, timeout=DEFAULT_TIMEOUT):
    """Acquire an exclusive lock on a file for the given session.

    Returns True if lock acquired, False if held by another session.
    Stale locks (older than timeout) are automatically reclaimed.
    Same-session re-acquisition is always allowed (reentrant).

    Raises nothing — returns False on any internal error (fail-open
    is handled by the caller, not here).
    """
    lock_dir = _get_lock_dir()
    if lock_dir is None:
        return True  # No lock dir available — fail-open

    lock_path = _lock_file_path(file_path, lock_dir)
    if lock_path is None:
        return True  # fail-open

    try:
        # Try to get an exclusive flock on the lock file
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            # Non-blocking flock attempt
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (IOError, OSError):
            # Could not get flock — someone else holds it
            os.close(fd)
            # Check if the existing lock is stale or same-session
            meta = _read_lock_meta(lock_path)
            if meta is None:
                # Unreadable lock file — reclaim it
                return _force_acquire(lock_path, file_path, session_id)
            if meta.get("session_id") == session_id:
                return True  # Same session — reentrant
            age = time.time() - meta.get("acquired_at", 0)
            if age > timeout:
                # Stale lock — reclaim
                return _force_acquire(lock_path, file_path, session_id)
            return False  # Held by another session, not stale

        # Got the flock — check metadata then decide
        _should_acquire = True
        try:
            # Check existing metadata for another fresh session
            meta = _read_lock_meta(lock_path)
            if meta is not None:
                if meta.get("session_id") != session_id:
                    age = time.time() - meta.get("acquired_at", 0)
                    if age <= timeout:
                        # Another session holds it and it's fresh
                        _should_acquire = False

            if _should_acquire:
                _write_lock_meta(lock_path, session_id, file_path)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

        return _should_acquire

    except (OSError, IOError):
        return True  # fail-open on any I/O error


def _force_acquire(lock_path, file_path, session_id):
    """Force-acquire a lock by overwriting stale/unreadable metadata."""
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)  # Blocking — brief wait OK for reclaim
            _write_lock_meta(lock_path, session_id, file_path)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        return True
    except (OSError, IOError):
        return True  # fail-open


def release_lock(file_path, session_id):
    """Release a lock held by the given session.

    Only releases if the lock is actually owned by this session.
    Returns True if released (or not held), False if owned by another session.
    """
    lock_dir = _get_lock_dir()
    if lock_dir is None:
        return True

    lock_path = _lock_file_path(file_path, lock_dir)
    if lock_path is None:
        return True

    try:
        if not os.path.exists(lock_path):
            return True  # No lock to release

        meta = _read_lock_meta(lock_path)
        if meta is None:
            # Unreadable — just remove it
            try:
                os.remove(lock_path)
            except OSError:
                pass
            return True

        if meta.get("session_id") != session_id:
            return False  # Not our lock

        try:
            os.remove(lock_path)
        except OSError:
            pass
        return True

    except (OSError, IOError):
        return True  # fail-open


def is_locked(file_path, exclude_session=None, timeout=DEFAULT_TIMEOUT):
    """Check if a file is locked by another session.

    Args:
        file_path: The file to check.
        exclude_session: If provided, locks held by this session are ignored.
        timeout: Locks older than this are considered stale.

    Returns a dict with lock info if locked by another session, or None if free.
    """
    lock_dir = _get_lock_dir()
    if lock_dir is None:
        return None  # fail-open

    lock_path = _lock_file_path(file_path, lock_dir)
    if lock_path is None:
        return None

    try:
        if not os.path.exists(lock_path):
            return None

        meta = _read_lock_meta(lock_path)
        if meta is None:
            return None  # Unreadable — treat as unlocked

        # Check staleness
        age = time.time() - meta.get("acquired_at", 0)
        if age > timeout:
            return None  # Stale lock

        # Check if same session
        if exclude_session and meta.get("session_id") == exclude_session:
            return None

        return meta

    except (OSError, IOError):
        return None  # fail-open


def cleanup_stale_locks(timeout=DEFAULT_TIMEOUT):
    """Remove all stale lock files. Called during session boot."""
    lock_dir = _get_lock_dir()
    if lock_dir is None:
        return 0

    removed = 0
    try:
        for fname in os.listdir(lock_dir):
            if not fname.endswith(".lock"):
                continue
            lock_path = os.path.join(lock_dir, fname)
            meta = _read_lock_meta(lock_path)
            if meta is None:
                try:
                    os.remove(lock_path)
                    removed += 1
                except OSError:
                    pass
                continue
            age = time.time() - meta.get("acquired_at", 0)
            if age > timeout:
                try:
                    os.remove(lock_path)
                    removed += 1
                except OSError:
                    pass
    except (OSError, IOError):
        pass
    return removed
