#!/usr/bin/env python3
"""ConfigChange hook — live settings.json integrity monitor.

Fires when Claude Code detects settings.json or skills changed mid-session.
Compares current settings against a snapshot taken at first fire.
Warns on: hook removal, permission changes, gate-critical key deletions.

Always exits 0 (fail-open, never blocks Claude).

Input (stdin JSON):
  {"session_id": "...", "hook_event_name": "ConfigChange",
   "source": "user_settings|project_settings|...", "file_path": "..."}
"""

import json
import os
import sys

CLAUDE_DIR = os.path.join(os.path.expanduser("~"), ".claude")
SNAPSHOT_FILE = os.path.join(CLAUDE_DIR, "hooks", ".settings_snapshot.json")

# Keys we care about monitoring
CRITICAL_KEYS = {"hooks", "permissions", "statusLine"}

# Hook events that must have at least one handler
REQUIRED_HOOKS = {"PreToolUse", "PostToolUse", "SessionStart"}


def _load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _save_snapshot(data):
    try:
        tmp = SNAPSHOT_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, SNAPSHOT_FILE)
    except Exception:
        pass


def _count_hooks(settings):
    """Count hook handlers per event type."""
    hooks = settings.get("hooks", {})
    counts = {}
    for event, entries in hooks.items():
        if not isinstance(entries, list):
            continue
        total = 0
        for entry in entries:
            for h in entry.get("hooks", []):
                if h.get("command"):
                    total += 1
        counts[event] = total
    return counts


def main():
    try:
        try:
            data = json.loads(sys.stdin.read())
        except (json.JSONDecodeError, ValueError):
            data = {}

        source = data.get("source", "")
        file_path = data.get("file_path", "")

        # Only monitor user_settings and project_settings
        if source not in ("user_settings", "project_settings"):
            sys.exit(0)

        if not file_path or not os.path.exists(file_path):
            sys.exit(0)

        current = _load_json(file_path)
        if current is None:
            print("[CONFIG_CHANGE] WARNING: settings.json is invalid JSON!", file=sys.stderr)
            sys.exit(0)

        # First fire: save snapshot and exit
        snapshot = _load_json(SNAPSHOT_FILE)
        if snapshot is None:
            _save_snapshot(current)
            print(f"[CONFIG_CHANGE] Snapshot saved for {source}", file=sys.stderr)
            sys.exit(0)

        # Compare against snapshot
        warnings = []

        # Check for removed critical keys
        for key in CRITICAL_KEYS:
            if key in snapshot and key not in current:
                warnings.append(f"Critical key '{key}' removed")

        # Check for removed hook events
        old_hooks = _count_hooks(snapshot)
        new_hooks = _count_hooks(current)

        for event in REQUIRED_HOOKS:
            old_count = old_hooks.get(event, 0)
            new_count = new_hooks.get(event, 0)
            if old_count > 0 and new_count == 0:
                warnings.append(f"{event} hooks removed (was {old_count} handler(s), now 0)")
            elif new_count < old_count:
                warnings.append(f"{event} hooks reduced ({old_count} → {new_count})")

        # Check permission mode changes
        old_perm = snapshot.get("permissions", {}).get("defaultMode", "")
        new_perm = current.get("permissions", {}).get("defaultMode", "")
        if old_perm and new_perm and old_perm != new_perm:
            warnings.append(f"Permission mode changed: {old_perm} → {new_perm}")

        if warnings:
            print(f"[CONFIG_CHANGE] WARNING: settings.json modified mid-session ({source}):",
                  file=sys.stderr)
            for w in warnings:
                print(f"  - {w}", file=sys.stderr)
        else:
            print(f"[CONFIG_CHANGE] settings.json changed ({source}) — no critical differences",
                  file=sys.stderr)

        # Update snapshot to current
        _save_snapshot(current)

    except Exception as e:
        print(f"[CONFIG_CHANGE] Error (non-fatal): {e}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
