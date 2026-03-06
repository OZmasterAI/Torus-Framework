"""Maintenance operations for boot sequence — audit rotation and cleanup."""
import gzip
import os
import re
import shutil
import sys
import tempfile
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


_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
_MODEL_LINE_RE = re.compile(r"^model:\s*(.+)$", re.MULTILINE)


def sync_agent_models():
    """Rewrite agent .md frontmatter model: field based on active profile.

    Only writes files where the model value actually changed.
    Uses atomic writes (tempfile + os.rename) to prevent corruption.
    """
    from shared.state import get_live_toggle
    from shared.model_profiles import get_model_for_agent

    profile_name = get_live_toggle("model_profile", "balanced") or "balanced"
    agents_dir = os.path.join(os.path.expanduser("~"), ".claude", "agents")
    if not os.path.isdir(agents_dir):
        return

    changed = 0
    for fname in os.listdir(agents_dir):
        if not fname.endswith(".md"):
            continue
        agent_name = fname[:-3]  # strip .md
        target_model = get_model_for_agent(profile_name, agent_name)
        if not target_model:
            continue  # Unknown agent, skip

        fpath = os.path.join(agents_dir, fname)
        try:
            with open(fpath, "r") as f:
                content = f.read()
        except OSError:
            continue

        fm_match = _FRONTMATTER_RE.match(content)
        if not fm_match:
            continue  # No frontmatter, skip

        frontmatter = fm_match.group(1)
        model_match = _MODEL_LINE_RE.search(frontmatter)
        if not model_match:
            continue  # No model: line, skip

        current_model = model_match.group(1).strip()
        if current_model == target_model:
            continue  # Already correct, no-op

        # Replace model: line in frontmatter
        new_frontmatter = _MODEL_LINE_RE.sub(f"model: {target_model}", frontmatter)
        new_content = f"---\n{new_frontmatter}\n---\n" + content[fm_match.end():]

        # Atomic write: tempfile in same dir + rename
        fd, tmp_path = tempfile.mkstemp(dir=agents_dir, suffix=".md.tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(new_content)
            os.rename(tmp_path, fpath)
            changed += 1
        except Exception:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    if changed:
        print(f"  [BOOT] Synced {changed} agent model(s) to profile '{profile_name}'", file=sys.stderr)
