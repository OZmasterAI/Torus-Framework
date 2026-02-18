#!/usr/bin/env python3
"""Self-Healing Claude Framework — Session End Hook

Fires on SessionEnd to:
1. Generate/update HANDOFF.md with session metrics (always appends metrics;
   writes full metrics-only handoff if /wrap-up didn't run)
2. Flush the capture queue to ChromaDB (observations collection)
3. Increment session_count in LIVE_STATE.json

Fail-open: always exits 0.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shared.chromadb_socket import is_worker_available, flush_queue as socket_flush, backup as socket_backup, WorkerUnavailable

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
CLAUDE_DIR = os.path.join(os.path.expanduser("~"), ".claude")
LIVE_STATE_FILE = os.path.join(CLAUDE_DIR, "LIVE_STATE.json")
HANDOFF_FILE = os.path.join(CLAUDE_DIR, "HANDOFF.md")
ARCHIVE_DIR = os.path.join(CLAUDE_DIR, "archive")
MEMORY_DIR = os.path.join(os.path.expanduser("~"), "data", "memory")
CAPTURE_QUEUE = os.path.join(HOOKS_DIR, ".capture_queue.jsonl")

# If HANDOFF.md was modified within this window, /wrap-up already ran
WRAPUP_RECENCY_SECONDS = 300  # 5 minutes


def _find_state_dir():
    """Return the active state directory (ramdisk or disk)."""
    try:
        from shared.ramdisk import get_state_dir
        return get_state_dir()
    except ImportError:
        return HOOKS_DIR


def _load_latest_state():
    """Load the most recent state_*.json file. Returns dict or {}."""
    state_dir = _find_state_dir()
    state_files = glob.glob(os.path.join(state_dir, "state_*.json"))
    # Also check disk fallback if ramdisk dir differs
    if state_dir != HOOKS_DIR:
        state_files += glob.glob(os.path.join(HOOKS_DIR, "state_*.json"))
    if not state_files:
        return {}
    latest = max(state_files, key=os.path.getmtime)
    try:
        with open(latest, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _load_live_state():
    """Load LIVE_STATE.json. Returns dict or {}."""
    try:
        with open(LIVE_STATE_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError, FileNotFoundError):
        return {}


def _parse_handoff_sections(content):
    """Parse HANDOFF.md into sections by ## headers.

    Returns dict: {header_lower: content_str} e.g. {"what's next": "1. Fix..."}
    """
    sections = {}
    current_header = None
    current_lines = []
    for line in content.splitlines():
        if line.startswith("## "):
            if current_header is not None:
                sections[current_header] = "\n".join(current_lines).strip()
            current_header = line[3:].strip().lower()
            # Strip "(auto-generated)" suffix for matching
            current_header = re.sub(r"\s*\(auto-generated\)\s*$", "", current_header)
            current_lines = []
        elif current_header is not None:
            current_lines.append(line)
    if current_header is not None:
        sections[current_header] = "\n".join(current_lines).strip()
    return sections


def _format_duration(start_ts):
    """Format session duration from start timestamp."""
    if not start_ts:
        return "unknown"
    elapsed = time.time() - start_ts
    hours = int(elapsed // 3600)
    minutes = int((elapsed % 3600) // 60)
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _format_tool_counts(tool_counts):
    """Format tool call counts as compact string."""
    if not tool_counts:
        return "none tracked"
    # Sort by count descending, take top 6
    sorted_tools = sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)[:6]
    parts = [f"{name}: {count}" for name, count in sorted_tools]
    return ", ".join(parts)


def _format_errors(error_counts):
    """Format error pattern counts."""
    if not error_counts:
        return "0"
    total = sum(error_counts.values())
    parts = [f"{pat} x{cnt}" for pat, cnt in error_counts.items()]
    return f"{total} ({', '.join(parts)})"


def _build_metrics_section(state):
    """Build the ## Session Metrics section from state data."""
    lines = ["## Session Metrics (auto-generated)"]

    duration = _format_duration(state.get("session_start"))
    lines.append(f"- **Duration**: {duration}")

    total_calls = state.get("total_tool_calls", state.get("tool_call_count", 0))
    tool_breakdown = _format_tool_counts(state.get("tool_call_counts", {}))
    lines.append(f"- **Tool Calls**: {total_calls} ({tool_breakdown})")

    files_edited = state.get("files_edited", [])
    verified = state.get("verified_fixes", [])
    pending = state.get("pending_verification", [])
    lines.append(f"- **Files Modified**: {len(files_edited)} ({len(verified)} verified, {len(pending)} pending)")

    errors_str = _format_errors(state.get("error_pattern_counts", {}))
    lines.append(f"- **Errors**: {errors_str}")

    test_code = state.get("last_test_exit_code")
    test_baseline = state.get("session_test_baseline", False)
    if test_baseline:
        status = f"exit code {test_code}" if test_code is not None else "ran"
        lines.append(f"- **Tests**: {status}")
    else:
        lines.append("- **Tests**: none this session")

    subagent_history = state.get("subagent_history", [])
    sub_tokens = state.get("subagent_total_tokens", 0)
    if subagent_history:
        lines.append(f"- **Subagents**: {len(subagent_history)} launched, {sub_tokens:,} tokens")

    if files_edited:
        lines.append("")
        lines.append("**Files changed:**")
        for f in files_edited[:15]:  # Cap at 15 to keep it scannable
            tag = ""
            if f in verified:
                tag = " (verified)"
            elif f in pending:
                tag = " (pending)"
            lines.append(f"- `{f}`{tag}")
        if len(files_edited) > 15:
            lines.append(f"- ... and {len(files_edited) - 15} more")

    return "\n".join(lines)


def _archive_handoff():
    """Archive current HANDOFF.md if it exists."""
    if not os.path.exists(HANDOFF_FILE):
        return
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    date_str = time.strftime("%Y-%m-%d")
    archive_path = os.path.join(ARCHIVE_DIR, f"HANDOFF_{date_str}_auto.md")
    # Avoid overwriting existing archive for today
    if os.path.exists(archive_path):
        archive_path = os.path.join(ARCHIVE_DIR, f"HANDOFF_{date_str}_auto_{int(time.time())}.md")
    try:
        shutil.copy2(HANDOFF_FILE, archive_path)
    except OSError as e:
        print(f"[SESSION_END] Archive failed (non-fatal): {e}", file=sys.stderr)


def generate_handoff(state):
    """Generate or update HANDOFF.md with session metrics.

    Mode A: Always appends a Session Metrics section.
    If /wrap-up didn't run (HANDOFF.md mtime > 5min), also generates a full
    metrics-only handoff, carrying forward What's Next and Known Issues.
    """
    try:
        live_state = _load_live_state()
        session_num = live_state.get("session_count", "?")

        # Check if /wrap-up already ran (HANDOFF.md recently modified)
        wrapup_ran = False
        old_sections = {}
        old_content = ""
        if os.path.exists(HANDOFF_FILE):
            try:
                mtime = os.path.getmtime(HANDOFF_FILE)
                wrapup_ran = (time.time() - mtime) < WRAPUP_RECENCY_SECONDS
                with open(HANDOFF_FILE, "r") as f:
                    old_content = f.read()
                old_sections = _parse_handoff_sections(old_content)
            except OSError:
                pass

        metrics_section = _build_metrics_section(state)

        if wrapup_ran:
            # /wrap-up already wrote narrative — just append metrics
            # Strip any previous trailing auto-generated metrics section
            content = old_content.rstrip()
            marker = "## Session Metrics (auto-generated)"
            if marker in content:
                # Use rfind to strip only the LAST occurrence (in case it appears mid-doc)
                last_pos = content.rfind(marker)
                # Only strip if it's the last ## section (nothing but metrics after it)
                after_marker = content[last_pos + len(marker):]
                if "## " not in after_marker:
                    content = content[:last_pos].rstrip()
            content += "\n\n" + metrics_section + "\n"
        else:
            # /wrap-up didn't run — generate full metrics-only handoff
            # Archive the old one first
            _archive_handoff()

            # Carry forward What's Next and Known Issues from previous handoff
            whats_next = old_sections.get("what's next", "No prior data — run /wrap-up for intelligent prioritization.")
            known_issues = old_sections.get("known issues", "None carried forward.")
            service_status = old_sections.get("service status", "")

            lines = [
                f"# Session {session_num} — Auto-Generated Handoff",
                "",
                "## What Was Done",
                "*(Auto-generated — /wrap-up was not run. Metrics below show session activity.)*",
                "",
                metrics_section,
                "",
                "## What's Next",
                whats_next,
                "",
                "## Known Issues",
                known_issues,
            ]
            if service_status:
                lines += ["", "## Service Status", service_status]
            content = "\n".join(lines) + "\n"

        # Atomic write
        tmp = HANDOFF_FILE + ".tmp"
        with open(tmp, "w") as f:
            f.write(content)
        os.replace(tmp, HANDOFF_FILE)

        mode = "appended metrics" if wrapup_ran else "full auto-handoff"
        print(f"[SESSION_END] Handoff updated ({mode})", file=sys.stderr)

    except Exception as e:
        print(f"[SESSION_END] Handoff generation failed (non-fatal): {e}", file=sys.stderr)


def session_summary(state=None):
    """Extract compact metrics from session state and print summary.

    If state is not provided, loads the most recent state_*.json file.
    Returns a dict of metrics for LIVE_STATE.json.
    """
    try:
        if state is None:
            state = _load_latest_state()
        if not state:
            return {}

        reads = len(state.get("files_read", []))
        edits = len(state.get("files_edited", state.get("edit_streak", {})))
        errors = len(state.get("error_pattern_counts", {}))
        verified = len(state.get("verified_fixes", []))
        pending = len(state.get("pending_verification", []))

        print(
            f"[SESSION_END] Metrics: {reads}R {edits}W | {errors} errors | {verified}V {pending}P",
            file=sys.stderr
        )

        return {
            "reads": reads,
            "edits": edits,
            "errors": errors,
            "verified": verified,
            "pending": pending
        }
    except Exception as e:
        print(f"[SESSION_END] Summary error (non-fatal): {e}", file=sys.stderr)
        return {}


def flush_capture_queue():
    """Flush .capture_queue.jsonl via UDS socket to memory_server.py."""
    if not os.path.exists(CAPTURE_QUEUE) or os.path.getsize(CAPTURE_QUEUE) == 0:
        print("[SESSION_END] Flushed 0 observations", file=sys.stderr)
        return

    # Count lines for reporting
    with open(CAPTURE_QUEUE, "r") as f:
        line_count = sum(1 for _ in f)

    # Try UDS socket flush (memory_server.py handles the actual ChromaDB upsert)
    try:
        if is_worker_available(retries=2, delay=0.3):
            flushed = socket_flush()
            print(f"[SESSION_END] Flushed {flushed} observations via UDS", file=sys.stderr)
            return
    except (WorkerUnavailable, RuntimeError) as e:
        print(f"[SESSION_END] UDS flush failed ({e}), deferring {line_count} observations to next boot", file=sys.stderr)
        return

    # Worker unavailable — defer queue to next boot
    print(f"[SESSION_END] Worker unavailable, deferring {line_count} observations to next boot", file=sys.stderr)


def backup_database():
    """Backup ChromaDB if DB changed since last backup. Fail-open."""
    db_path = os.path.join(MEMORY_DIR, "chroma.sqlite3")
    bak_path = os.path.join(MEMORY_DIR, "chroma.sqlite3.backup")
    try:
        # Mtime skip: don't re-backup if DB hasn't changed
        if os.path.exists(db_path) and os.path.exists(bak_path):
            db_mtime = os.path.getmtime(db_path)
            bak_mtime = os.path.getmtime(bak_path)
            if bak_mtime >= db_mtime:
                print("[SESSION_END] Backup skipped (DB unchanged)", file=sys.stderr)
                return
        if not is_worker_available(retries=1, delay=0.2):
            print("[SESSION_END] Backup skipped (worker unavailable)", file=sys.stderr)
            return
        result = socket_backup()
        size_mb = round(result.get("size_bytes", 0) / (1024 * 1024), 2)
        print(f"[SESSION_END] Backup created ({size_mb} MB)", file=sys.stderr)
    except Exception as e:
        print(f"[SESSION_END] Backup failed (non-fatal): {e}", file=sys.stderr)


def increment_session_count(metrics=None):
    """Atomically increment session_count in LIVE_STATE.json."""
    state = {}
    if os.path.exists(LIVE_STATE_FILE):
        try:
            with open(LIVE_STATE_FILE, "r") as f:
                state = json.load(f)
        except (json.JSONDecodeError, OSError):
            state = {}
    state["session_count"] = state.get("session_count", 0) + 1

    # Store session metrics if provided
    if metrics:
        state["last_session_metrics"] = metrics

    tmp = LIVE_STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")
    os.replace(tmp, LIVE_STATE_FILE)
    print(f"[SESSION_END] Session {state['session_count']} complete", file=sys.stderr)


def main():
    try:
        # Read stdin (session data, may include session_id)
        try:
            _session_data = json.loads(sys.stdin.read())
        except (json.JSONDecodeError, ValueError):
            _session_data = {}

        # Load state once, share across functions
        state = _load_latest_state()

        # Get session summary metrics
        metrics = {}
        try:
            metrics = session_summary(state)
        except Exception as e:
            print(f"[SESSION_END] Summary error (non-fatal): {e}", file=sys.stderr)

        # Generate/update HANDOFF.md (before flush, while state is fresh)
        try:
            generate_handoff(state)
        except Exception as e:
            print(f"[SESSION_END] Handoff error (non-fatal): {e}", file=sys.stderr)

        flush_capture_queue()
        backup_database()

        # Telegram Bot: post session summary to FTS5 + notify OZ
        try:
            _tg_hook = os.path.join(CLAUDE_DIR, "integrations", "telegram-bot", "hooks", "on_session_end.py")
            if os.path.isfile(_tg_hook):
                subprocess.run([sys.executable, _tg_hook], timeout=15, capture_output=False, stdin=subprocess.DEVNULL)
        except Exception:
            pass  # Telegram integration is optional, never block session end

        increment_session_count(metrics)
    except Exception as e:
        print(f"[SESSION_END] Error (non-fatal): {e}", file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()
