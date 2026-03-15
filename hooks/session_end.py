#!/usr/bin/env python3
"""Self-Healing Claude Framework — Session End Hook

Fires on SessionEnd to:
1. Update LIVE_STATE.json with session metrics and auto-summary if /wrap-up didn't run
2. Flush the capture queue to LanceDB (observations collection)
3. Increment session_count in LIVE_STATE.json

Fail-open: always exits 0.
"""
import glob
import json
import os
import subprocess
import sys
import time
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shared.memory_socket import is_worker_available, flush_queue as socket_flush, backup as socket_backup, WorkerUnavailable
from boot_pkg.util import detect_project, load_project_state, save_project_state

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
CLAUDE_DIR = os.path.join(os.path.expanduser("~"), ".claude")
LIVE_STATE_FILE = os.path.join(CLAUDE_DIR, "LIVE_STATE.json")
ARCHIVE_DIR = os.path.join(CLAUDE_DIR, "archive")
MEMORY_DIR = os.path.join(os.path.expanduser("~"), "data", "memory")
WRAPUP_RECENCY_SECONDS = 1800  # 30 minutes


def _get_capture_queue():
    """Return the active capture queue path (ramdisk or disk fallback)."""
    try:
        from shared.ramdisk import get_capture_queue
        return get_capture_queue()
    except ImportError:
        return os.path.join(HOOKS_DIR, ".capture_queue.jsonl")


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


def _read_last_assistant_message():
    """Read the last_assistant_message captured by stop_cleanup.py.

    Returns the message string (up to 1000 chars) or empty string.
    Cleans up the temp file after reading.
    """
    candidates = []
    try:
        from shared.ramdisk import TMPFS_STATE_DIR
        candidates.append(os.path.join(TMPFS_STATE_DIR, ".last_assistant_message"))
    except ImportError:
        pass
    candidates.append(os.path.join(HOOKS_DIR, ".last_assistant_message"))

    for path in candidates:
        try:
            if os.path.isfile(path):
                with open(path, "r") as f:
                    msg = f.read().strip()
                try:
                    os.unlink(path)
                except OSError:
                    pass
                if msg:
                    return msg
        except OSError:
            continue
    return ""



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



def _extract_transcript_excerpt(transcript_path, max_turns=40):
    """Read the last N assistant+user turns from the transcript JSONL.

    Claude Code transcript format: each line is a JSON object with:
    - "type": "user"|"assistant"|"progress"|"file-history-snapshot"
    - "message": {"role": "...", "content": "..." or [...]}

    Returns a compact text excerpt suitable for Haiku summarization.
    """
    if not transcript_path or not os.path.isfile(transcript_path):
        return ""
    try:
        turns = []
        with open(transcript_path, "r") as f:
            for raw_line in f:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    entry = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                entry_type = entry.get("type", "")
                if entry_type not in ("user", "assistant"):
                    continue
                msg = entry.get("message", {})
                if not msg:
                    continue
                role = msg.get("role", entry_type)
                content = msg.get("content", "")
                if isinstance(content, list):
                    text_parts = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                    content = "\n".join(text_parts)
                if not content:
                    continue
                # Strip system-reminder tags to reduce noise
                if "<system-reminder>" in content:
                    import re as _re
                    content = _re.sub(r"<system-reminder>.*?</system-reminder>", "", content, flags=_re.DOTALL)
                content = content.strip()
                if content:
                    turns.append(f"[{role}]: {content[:500]}")
        # Take last N turns, cap total at ~4000 chars for Haiku prompt
        recent = turns[-max_turns:]
        excerpt = "\n".join(recent)
        if len(excerpt) > 4000:
            excerpt = excerpt[-4000:]
        return excerpt
    except Exception:
        return ""


def _haiku_summarize(transcript_excerpt, metrics_text, session_num):
    """Call claude -p --model haiku to generate a session summary.

    Returns summary string or empty string on failure. Timeout: 15s.
    """
    if not transcript_excerpt:
        return ""
    prompt = (
        f"You are summarizing Session {session_num} of a software project. "
        "Based on the conversation excerpt and metrics below, write 3-5 concise bullet points "
        "describing what was accomplished. Focus on outcomes, not process. "
        "Start each bullet with a dash. No preamble, just the bullets.\n\n"
        f"## Metrics\n{metrics_text}\n\n"
        f"## Conversation (last turns)\n{transcript_excerpt}"
    )
    cmd = [
        "claude", "-p", prompt,
        "--model", "claude-haiku-4-5-20251001",
        "--output-format", "text",
    ]
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    env["TORUS_BOT_SESSION"] = "1"  # Skip hooks in subprocess
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
            env=env, cwd=CLAUDE_DIR,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        print(f"[SESSION_END] Haiku summarize failed: {e}", file=sys.stderr)
    return ""


def _update_config(key, value):
    """Atomically update a single key in config.json."""
    config_path = os.path.join(CLAUDE_DIR, "config.json")
    cfg = {}
    try:
        if os.path.isfile(config_path):
            with open(config_path) as f:
                cfg = json.load(f)
    except (json.JSONDecodeError, OSError):
        pass
    cfg[key] = value
    tmp = config_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    os.replace(tmp, config_path)


def generate_handoff(state, transcript_path="", project_name=None, project_dir=None):
    """Update state with auto-summary and config.json with session metrics.

    If project_dir is set, all state goes to the project's .claude-state.json.
    LIVE_STATE.json is not touched at all for project sessions.
    Framework sessions (project_dir=None) write to LIVE_STATE.json as before.

    session_metrics are written to config.json (persist across task resets).
    """
    _is_project = project_dir is not None
    try:
        live_state = _load_live_state()
        session_num = live_state.get("session_count", "?")

        # Check if /wrap-up already ran:
        # LIVE_STATE.json must have a non-empty what_was_done AND be recently modified
        wrapup_ran = False
        if live_state.get("what_was_done", "").strip():
            try:
                mtime = os.path.getmtime(LIVE_STATE_FILE)
                wrapup_ran = (time.time() - mtime) < WRAPUP_RECENCY_SECONDS
            except OSError:
                pass

        metrics_section = _build_metrics_section(state)

        # Determine what_was_done content
        what_was_done = None
        if wrapup_ran:
            # /wrap-up already wrote narrative — just update session_metrics in config.json
            _update_config("session_metrics", metrics_section)
            print("[SESSION_END] Wrap-up detected — updated session_metrics in config.json", file=sys.stderr)
        else:
            # /wrap-up didn't run — try Haiku auto-summary
            excerpt = _extract_transcript_excerpt(transcript_path)
            haiku_summary = _haiku_summarize(excerpt, metrics_section, session_num) if excerpt else ""

            if haiku_summary:
                what_was_done = haiku_summary[:200]
                print("[SESSION_END] Haiku auto-summary generated", file=sys.stderr)
            else:
                what_was_done = (
                    "Auto-generated — no transcript available. "
                    "Metrics below show session activity."
                )

            _update_config("session_metrics", metrics_section)

        # Capture last_assistant_message from Stop hook for session continuity
        last_msg = _read_last_assistant_message()
        last_response_preview = last_msg[:500] if last_msg else None
        if last_msg:
            print(f"[SESSION_END] Captured last_assistant_message ({len(last_msg)} chars)", file=sys.stderr)

        if _is_project:
            # Project session: write everything to .claude-state.json, don't touch LIVE_STATE.json
            proj_state = load_project_state(project_dir)
            proj_state["project_name"] = project_name
            proj_state["session_count"] = proj_state.get("session_count", 0) + 1
            proj_state["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            if what_was_done is not None:
                proj_state["what_was_done"] = what_was_done
            if last_response_preview is not None:
                proj_state["last_response_preview"] = last_response_preview
            save_project_state(project_dir, proj_state)
            print(f"[SESSION_END] Project state written: {project_dir}/.claude-state.json (session {proj_state['session_count']})", file=sys.stderr)
        else:
            # Framework/hub session: write everything to LIVE_STATE.json (original behavior)
            if what_was_done is not None:
                live_state["what_was_done"] = what_was_done
            if last_response_preview is not None:
                live_state["last_response_preview"] = last_response_preview

            tmp = LIVE_STATE_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(live_state, f, indent=2)
                f.write("\n")
            os.replace(tmp, LIVE_STATE_FILE)

        mode = "project state" if _is_project else ("updated session_metrics" if wrapup_ran else "wrote what_was_done + session_metrics")
        print(f"[SESSION_END] LIVE_STATE.json updated ({mode})", file=sys.stderr)

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
    """Flush capture queue via UDS socket to memory_server.py."""
    capture_queue = _get_capture_queue()
    if not os.path.exists(capture_queue) or os.path.getsize(capture_queue) == 0:
        print("[SESSION_END] Flushed 0 observations", file=sys.stderr)
        return

    # Count lines for reporting
    with open(capture_queue, "r") as f:
        line_count = sum(1 for _ in f)

    # Try UDS socket flush (memory_server.py handles the actual LanceDB upsert)
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
    """Backup database if DB changed since last backup. Fail-open."""
    lance_dir = os.path.join(MEMORY_DIR, "lancedb")
    bak_path = os.path.join(MEMORY_DIR, "lancedb.backup.tar.gz")
    try:
        # Mtime skip: don't re-backup if DB hasn't changed
        if os.path.isdir(lance_dir) and os.path.exists(bak_path):
            db_mtime = os.path.getmtime(lance_dir)
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
    """Increment session_count in LIVE_STATE.json and save session metrics."""
    state = {}
    if os.path.exists(LIVE_STATE_FILE):
        try:
            with open(LIVE_STATE_FILE, "r") as f:
                state = json.load(f)
        except (json.JSONDecodeError, OSError):
            state = {}
    state["session_count"] = state.get("session_count", 0) + 1

    # Store session metrics in config.json (persists across task resets)
    if metrics:
        _update_config("last_session_metrics", metrics)

    tmp = LIVE_STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")
    os.replace(tmp, LIVE_STATE_FILE)
    print(f"[SESSION_END] Session {state['session_count']} complete", file=sys.stderr)


def _run_background(data_path):
    """Background mode: handles all slow operations with no time pressure."""
    try:
        with open(data_path) as f:
            ctx = json.load(f)
    except Exception:
        return
    finally:
        try:
            os.unlink(data_path)
        except OSError:
            pass

    transcript_path = ctx.get("transcript_path", "")
    project_name = ctx.get("project_name")
    project_dir = ctx.get("project_dir")
    session_data = ctx.get("session_data", {})
    state = _load_latest_state()

    try:
        generate_handoff(state, transcript_path=transcript_path,
                         project_name=project_name, project_dir=project_dir)
    except Exception as e:
        print(f"[SESSION_END:bg] Handoff error: {e}", file=sys.stderr)

    try:
        flush_capture_queue()
    except Exception as e:
        print(f"[SESSION_END:bg] Flush error: {e}", file=sys.stderr)

    try:
        backup_database()
    except Exception as e:
        print(f"[SESSION_END:bg] Backup error: {e}", file=sys.stderr)

    try:
        from scripts.flush_audit import flush as flush_audit
        flushed, freed = flush_audit()
        if flushed > 0:
            print(f"[SESSION_END:bg] Audit flush: {flushed} files, {freed / 1024 / 1024:.1f}MB freed", file=sys.stderr)
    except Exception as e:
        print(f"[SESSION_END:bg] Audit flush failed: {e}", file=sys.stderr)

    try:
        _tg_notify = False
        try:
            with open(LIVE_STATE_FILE) as _f:
                _tg_notify = json.load(_f).get("tg_session_notify", False)
        except Exception:
            pass
        _tg_hook = os.path.join(CLAUDE_DIR, "integrations", "telegram-bot", "hooks", "on_session_end.py")
        if _tg_notify and os.path.isfile(_tg_hook):
            subprocess.run([sys.executable, _tg_hook], timeout=30,
                           capture_output=False, stdin=subprocess.DEVNULL)
    except Exception:
        pass

    try:
        _term_hook = os.path.join(CLAUDE_DIR, "integrations", "terminal-history", "hooks", "on_session_end.py")
        if os.path.isfile(_term_hook):
            subprocess.run([sys.executable, _term_hook], timeout=30,
                           capture_output=False, input=json.dumps(session_data), text=True)
    except Exception:
        pass

    print("[SESSION_END:bg] Background work complete", file=sys.stderr)


def main():
    try:
        if os.environ.get("TORUS_BOT_SESSION") == "1":
            print("[SESSION_END] Bot session — skipping lifecycle ops", file=sys.stderr)
            sys.exit(0)

        if len(sys.argv) >= 3 and sys.argv[1] == "--background":
            _run_background(sys.argv[2])
            sys.exit(0)

        # === FAST PATH (must complete within 5s hook timeout) ===
        try:
            _session_data = json.loads(sys.stdin.read())
        except (json.JSONDecodeError, ValueError):
            _session_data = {}
        transcript_path = _session_data.get("transcript_path", "")

        _cwd = _session_data.get("cwd")
        _project_name, _project_dir, _subproject_name, _subproject_dir = detect_project(_cwd)
        _effective_name = _subproject_name or _project_name
        _effective_dir = _subproject_dir or _project_dir

        state = _load_latest_state()
        metrics = {}
        try:
            metrics = session_summary(state)
        except Exception as e:
            print(f"[SESSION_END] Summary error (non-fatal): {e}", file=sys.stderr)

        # Enforcer daemon is shared across sessions — don't kill on exit.
        # Boot.py handles restart if needed.

        if _project_dir is None:
            increment_session_count(metrics)
        elif metrics:
            _update_config("last_session_metrics", metrics)

        # === SPAWN BACKGROUND PROCESS for slow ops ===
        ctx = {
            "transcript_path": transcript_path,
            "project_name": _effective_name,
            "project_dir": _effective_dir,
            "session_data": _session_data,
        }
        fd, data_path = tempfile.mkstemp(prefix="session_end_", suffix=".json", dir=HOOKS_DIR)
        with os.fdopen(fd, "w") as f:
            json.dump(ctx, f)

        log_path = os.path.join(HOOKS_DIR, ".session_end_bg.log")
        subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), "--background", data_path],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=open(log_path, "a"),
            start_new_session=True,
        )
        print("[SESSION_END] Background process spawned for slow ops", file=sys.stderr)

    except Exception as e:
        print(f"[SESSION_END] Error (non-fatal): {e}", file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()
