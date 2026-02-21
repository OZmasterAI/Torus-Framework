#!/usr/bin/env python3
"""SessionStart hook — verify integrity of critical framework files.

On first run, generates SHA256 hashes for critical files and saves them.
On subsequent runs, compares current hashes and warns on mismatches.
Fail-open: always exits 0.
"""

import hashlib
import json
import os
import sys

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
HASH_FILE = os.path.join(HOOKS_DIR, ".integrity_hashes.json")

# Critical files to monitor (relative to hooks dir)
CRITICAL_FILES = [
    "enforcer.py",
    "tracker.py",
    "boot.py",
    "shared/gate_router.py",
    "shared/state.py",
    "shared/gate_result.py",
]


def _sha256(filepath):
    """Compute SHA256 of a file."""
    h = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except (OSError, IOError):
        return None


def main():
    current_hashes = {}
    for rel_path in CRITICAL_FILES:
        full_path = os.path.join(HOOKS_DIR, rel_path)
        h = _sha256(full_path)
        if h:
            current_hashes[rel_path] = h

    # Bootstrap mode: no hash file exists yet
    if not os.path.exists(HASH_FILE):
        try:
            tmp = HASH_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(current_hashes, f, indent=2)
            os.replace(tmp, HASH_FILE)
        except Exception:
            pass
        return

    # Compare against saved hashes
    try:
        with open(HASH_FILE) as f:
            saved_hashes = json.load(f)
    except Exception:
        return

    mismatches = []
    for rel_path, saved_hash in saved_hashes.items():
        current = current_hashes.get(rel_path)
        if current and current != saved_hash:
            mismatches.append(rel_path)

    if mismatches:
        print(f"[INTEGRITY] WARNING: {len(mismatches)} critical file(s) changed since last baseline:",
              file=sys.stderr)
        for m in mismatches:
            print(f"  - {m}", file=sys.stderr)
        print("[INTEGRITY] Run 'python3 hooks/integrity_check.py --update' to accept changes.",
              file=sys.stderr)

    # --update flag: regenerate hashes
    if "--update" in sys.argv:
        try:
            tmp = HASH_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(current_hashes, f, indent=2)
            os.replace(tmp, HASH_FILE)
            print("[INTEGRITY] Hashes updated.", file=sys.stderr)
        except Exception:
            pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
