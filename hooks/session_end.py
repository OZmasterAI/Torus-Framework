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
from shared.memory_socket import (
    is_worker_available,
    flush_queue as socket_flush,
    backup as socket_backup,
    WorkerUnavailable,
)
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
    lines.append(
        f"- **Files Modified**: {len(files_edited)} ({len(verified)} verified, {len(pending)} pending)"
    )

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
        lines.append(
            f"- **Subagents**: {len(subagent_history)} launched, {sub_tokens:,} tokens"
        )

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

                    content = _re.sub(
                        r"<system-reminder>.*?</system-reminder>",
                        "",
                        content,
                        flags=_re.DOTALL,
                    )
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


def _daemon_summarize(transcript_excerpt, metrics_text, session_num):
    """Send summarization prompt to summarizer daemon via Unix socket.

    Returns summary string or empty string on failure. Timeout: 10s.
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
    sock_path = os.path.join(HOOKS_DIR, ".summarizer.sock")
    try:
        import socket

        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(10)
        s.connect(sock_path)
        req = (
            json.dumps({"type": "summarize", "prompt": prompt, "max_tokens": 2000})
            + "\n"
        )
        s.sendall(req.encode())
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
        s.close()
        resp = json.loads(buf.decode().strip())
        if resp.get("ok") and resp.get("result"):
            return resp["result"].strip()
    except Exception as e:
        print(f"[SESSION_END] Daemon summarize failed: {e}", file=sys.stderr)
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
        "claude",
        "-p",
        prompt,
        "--model",
        "claude-haiku-4-5-20251001",
        "--output-format",
        "text",
    ]
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    env["TORUS_BOT_SESSION"] = "1"  # Skip hooks in subprocess
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
            cwd=CLAUDE_DIR,
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
        _haiku_overwrite = False  # Pre-initialize to avoid UnboundLocalError
        if wrapup_ran:
            # /wrap-up already wrote narrative — just update session_metrics in config.json
            _update_config("session_metrics", metrics_section)
            print(
                "[SESSION_END] Wrap-up detected — updated session_metrics in config.json",
                file=sys.stderr,
            )
        else:
            # /wrap-up didn't run — try auto-summary
            excerpt = _extract_transcript_excerpt(transcript_path)
            _summary_mode = "haiku"
            try:
                _cfg_path = os.path.join(CLAUDE_DIR, "config.json")
                if os.path.isfile(_cfg_path):
                    with open(_cfg_path) as _cf:
                        _summary_mode = json.load(_cf).get(
                            "session_summary_mode", "haiku"
                        )
            except Exception:
                pass

            auto_summary = ""
            if excerpt:
                if _summary_mode in ("daemon", "daemon+haiku"):
                    auto_summary = _daemon_summarize(
                        excerpt, metrics_section, session_num
                    )
                    if not auto_summary:
                        # Fallback to haiku if daemon fails
                        auto_summary = _haiku_summarize(
                            excerpt, metrics_section, session_num
                        )
                    elif _summary_mode == "daemon+haiku":
                        _haiku_overwrite = (
                            True  # daemon succeeded, queue haiku overwrite
                        )
                elif _summary_mode == "haiku":
                    auto_summary = _haiku_summarize(
                        excerpt, metrics_section, session_num
                    )

            if auto_summary:
                what_was_done = auto_summary[:500]
                print(
                    f"[SESSION_END] Auto-summary generated (mode={_summary_mode})",
                    file=sys.stderr,
                )
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
            print(
                f"[SESSION_END] Captured last_assistant_message ({len(last_msg)} chars)",
                file=sys.stderr,
            )

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
            try:
                from shared.dag import get_session_dag as _get_dag_proj

                _proj_dag = _get_dag_proj("main")
                _proj_binfo = _proj_dag.current_branch_info()
                proj_state["dag_branch"] = _proj_binfo.get("name", "")
                proj_state["dag_node_count"] = _proj_binfo.get("msg_count", 0)
            except Exception:
                pass
            save_project_state(project_dir, proj_state)
            print(
                f"[SESSION_END] Project state written: {project_dir}/.claude-state.json (session {proj_state['session_count']})",
                file=sys.stderr,
            )
        else:
            # Framework/hub session: write everything to LIVE_STATE.json (original behavior)
            if what_was_done is not None:
                live_state["what_was_done"] = what_was_done
            if last_response_preview is not None:
                live_state["last_response_preview"] = last_response_preview
            try:
                from shared.dag import get_session_dag as _get_dag_se

                _se_dag = _get_dag_se("main")
                _se_binfo = _se_dag.current_branch_info()
                live_state["dag_branch"] = _se_binfo.get("name", "")
                live_state["dag_branch_label"] = _se_dag.get_branch_label()
                live_state["dag_node_count"] = _se_binfo.get("msg_count", 0)
                live_state["dag_total_branches"] = _se_binfo.get("total_branches", 0)
            except Exception:
                pass

            tmp = LIVE_STATE_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(live_state, f, indent=2)
                f.write("\n")
            os.replace(tmp, LIVE_STATE_FILE)

        mode = (
            "project state"
            if _is_project
            else (
                "updated session_metrics"
                if wrapup_ran
                else "wrote what_was_done + session_metrics"
            )
        )
        _target = ".claude-state.json" if _is_project else "LIVE_STATE.json"
        print(f"[SESSION_END] {_target} updated ({mode})", file=sys.stderr)

        # daemon+haiku: spawn detached Haiku to overwrite summary
        if _haiku_overwrite and excerpt:
            try:
                _state_file = (
                    os.path.join(project_dir, ".claude-state.json")
                    if _is_project
                    else LIVE_STATE_FILE
                )
                _overwrite_script = (
                    "import json, subprocess, os, sys\n"
                    f"excerpt = {repr(excerpt)}\n"
                    f"metrics = {repr(metrics_section)}\n"
                    f"session_num = {repr(session_num)}\n"
                    f"state_file = {repr(_state_file)}\n"
                    "env = {k: v for k, v in os.environ.items() if k != 'CLAUDECODE'}\n"
                    "env['TORUS_BOT_SESSION'] = '1'\n"
                    "prompt = (f'You are summarizing Session {session_num} of a software project. '\n"
                    "  'Based on the conversation excerpt and metrics below, write 3-5 concise bullet points '\n"
                    "  'describing what was accomplished. Focus on outcomes, not process. '\n"
                    "  'Start each bullet with a dash. No preamble, just the bullets.\\n\\n'\n"
                    "  f'## Metrics\\n{metrics}\\n\\n'\n"
                    "  f'## Conversation (last turns)\\n{excerpt}')\n"
                    "try:\n"
                    "  r = subprocess.run(['claude', '-p', prompt, '--model', 'claude-haiku-4-5-20251001',\n"
                    "    '--output-format', 'text'], capture_output=True, text=True, timeout=30,\n"
                    "    env=env, cwd=os.path.expanduser('~/.claude'))\n"
                    "  if r.returncode == 0 and r.stdout.strip():\n"
                    "    s = json.load(open(state_file))\n"
                    "    s['what_was_done'] = r.stdout.strip()[:200]\n"
                    "    tmp = state_file + '.haiku.tmp'\n"
                    "    with open(tmp, 'w') as f:\n"
                    "      json.dump(s, f, indent=2); f.write('\\n')\n"
                    "    os.replace(tmp, state_file)\n"
                    "    print('[SESSION_END:haiku] Overwrote summary', file=sys.stderr)\n"
                    "except Exception as e:\n"
                    "  print(f'[SESSION_END:haiku] Failed: {e}', file=sys.stderr)\n"
                )
                subprocess.Popen(
                    [sys.executable, "-c", _overwrite_script],
                    stdout=subprocess.DEVNULL,
                    stderr=open(os.path.join(HOOKS_DIR, ".session_end_bg.log"), "a"),
                    start_new_session=True,
                )
                print(
                    "[SESSION_END] Haiku overwrite spawned (detached)",
                    file=sys.stderr,
                )
            except Exception:
                pass  # Haiku overwrite is best-effort

    except Exception as e:
        print(
            f"[SESSION_END] Handoff generation failed (non-fatal): {e}", file=sys.stderr
        )


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
            file=sys.stderr,
        )

        return {
            "reads": reads,
            "edits": edits,
            "errors": errors,
            "verified": verified,
            "pending": pending,
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
            print(
                f"[SESSION_END] Flushed {flushed} observations via UDS", file=sys.stderr
            )
            return
    except (WorkerUnavailable, RuntimeError) as e:
        print(
            f"[SESSION_END] UDS flush failed ({e}), deferring {line_count} observations to next boot",
            file=sys.stderr,
        )
        return

    # Worker unavailable — defer queue to next boot
    print(
        f"[SESSION_END] Worker unavailable, deferring {line_count} observations to next boot",
        file=sys.stderr,
    )


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


def compact_if_needed(threshold=100):
    """Compact LanceDB tables if any table exceeds the version threshold.

    Checks _versions/ directory count for each .lance table. If any exceeds
    the threshold, sends an optimize request to memory_server via UDS socket.
    Runs in the background process so there's no time pressure.
    """
    lance_dir = os.path.join(MEMORY_DIR, "lancedb")
    if not os.path.isdir(lance_dir):
        return
    for name in os.listdir(lance_dir):
        if not name.endswith(".lance"):
            continue
        versions_dir = os.path.join(lance_dir, name, "_versions")
        if not os.path.isdir(versions_dir):
            continue
        count = len(os.listdir(versions_dir))
        if count > threshold:
            if not is_worker_available(retries=1, delay=0.2):
                print(
                    f"[SESSION_END] Compaction needed ({name}: {count} versions) but worker unavailable",
                    file=sys.stderr,
                )
                return
            from shared.memory_socket import optimize as socket_optimize

            result = socket_optimize()
            tables = result.get("tables", {}) if isinstance(result, dict) else {}
            summary = ", ".join(
                f"{t}: {v.get('rows_before', '?')}r/{v.get('duration_s', '?')}s"
                for t, v in tables.items()
            )
            print(
                f"[SESSION_END] Compacted LanceDB (trigger: {name} had {count} versions) — {summary}",
                file=sys.stderr,
            )
            return  # optimize hits all tables, one call suffices
    print(
        "[SESSION_END] Compaction not needed (all tables under threshold)",
        file=sys.stderr,
    )


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


def write_vault_session_note(
    state, live_state, project_name=None, feature=None, project_dir=None
):
    """Write a session summary note to ~/vault/sessions/ for Obsidian.

    Fail-open: never blocks session end. Skips if vault doesn't exist
    or if /wrap-up already wrote the note (collision-safe).
    Uses project-local session count for project sessions, global for framework.
    """
    vault_sessions = os.path.join(os.path.expanduser("~"), "vault", "sessions")
    if not os.path.isdir(vault_sessions):
        return  # No vault — skip silently

    filepath = ""
    try:
        # For project sessions, read from project state (LIVE_STATE belongs to framework)
        session_num = live_state.get("session_count", 0)
        project = project_name or live_state.get("project", "unknown")
        _src = live_state
        if project_dir:
            try:
                _src = load_project_state(project_dir)
                session_num = _src.get("session_count", session_num)
            except Exception:
                _src = live_state
        date_str = time.strftime("%Y-%m-%d")
        # Add project suffix for non-framework sessions
        if project_dir and project and project != "torus-framework":
            slug = project.replace("_", "-").lower()
            filename = f"{date_str}-session-{session_num:03d}-{slug}.md"
        else:
            filename = f"{date_str}-session-{session_num:03d}.md"
        filepath = os.path.join(vault_sessions, filename)

        if os.path.exists(filepath):
            print(
                f"[SESSION_END:vault] Skipped — {filename} exists (/wrap-up wrote it)",
                file=sys.stderr,
            )
            return

        # Extract metadata
        project = project_name or live_state.get("project", "unknown")
        feat = _src.get("feature", "")
        what_was_done = _src.get("what_was_done", "No summary available.")
        known_issues = _src.get("known_issues", [])
        next_steps = _src.get("next_steps", [])
        duration = _format_duration(state.get("session_start"))
        total_tools = state.get("total_tool_calls", state.get("tool_call_count", 0))
        files_edited = state.get("files_edited", [])

        tags = ["session", project]
        if feat:
            tags.append(feat)

        lines = [
            "---",
            "type: session",
            f"tags: [{', '.join(tags)}]",
            f"created: {date_str}",
            "status: completed",
            f"project: {project}",
            f"session_number: {session_num}",
            f"duration: {duration}",
            f"tools_used: {total_tools}",
            f"files_modified: {len(files_edited)}",
            "---",
            "",
            f"# Session {session_num} — {date_str}",
            "",
            "> [!summary] Quick Stats",
            f"> **Duration:** {duration} · **Tools:** {total_tools} · **Files:** {len(files_edited)}",
            "",
            "---",
            "",
            "## What Was Done",
            what_was_done,
            "",
        ]

        if known_issues:
            lines.append("---")
            lines.append("")
            lines.append("## Known Issues")
            lines.append("")
            lines.append("> [!bug]")
            for issue in known_issues:
                lines.append(f"> - {issue}")
            lines.append("")

        if next_steps:
            lines.append("---")
            lines.append("")
            lines.append("## Next Steps")
            lines.append("")
            for step in next_steps:
                lines.append(f"- [ ] {step}")
            lines.append("")

        content = "\n".join(lines)

        # Atomic write: .tmp then os.replace
        tmp_path = filepath + ".tmp"
        with open(tmp_path, "w") as f:
            f.write(content)
        os.replace(tmp_path, filepath)

        print(f"[SESSION_END:vault] Wrote {filename}", file=sys.stderr)
    except Exception as e:
        print(f"[SESSION_END:vault] Failed (non-fatal): {e}", file=sys.stderr)
        try:
            if os.path.exists(filepath + ".tmp"):
                os.unlink(filepath + ".tmp")
        except Exception:
            pass


def _parse_daily_sessions(content):
    """Parse project groups and session entries from a daily note.

    Returns (header, projects, stats_existed).
    header = everything before '## Sessions'
    projects = {project_name: [session_lines, ...]}
    """
    projects = {}
    header_lines = []
    in_sessions = False
    in_stats = False
    current_project = None

    for line in content.splitlines():
        if line.strip() == "## Sessions":
            in_sessions = True
            continue
        if (
            line.strip() == "## Daily Stats"
            or line.strip() == "---"
            and in_sessions
            and not current_project
        ):
            in_stats = True
            continue
        if in_stats:
            continue  # Skip old stats — we regenerate
        if not in_sessions:
            header_lines.append(line)
            continue

        # Inside ## Sessions
        if line.startswith("### "):
            current_project = line[4:].strip()
            projects.setdefault(current_project, [])
        elif current_project and line.startswith("- "):
            projects[current_project].append(line)

    return "\n".join(header_lines), projects


def _duration_to_minutes(duration_str):
    """Parse '1h 30m' or '45m' to total minutes."""
    minutes = 0
    import re

    h = re.search(r"(\d+)h", duration_str)
    m = re.search(r"(\d+)m", duration_str)
    if h:
        minutes += int(h.group(1)) * 60
    if m:
        minutes += int(m.group(1))
    return minutes


def _minutes_to_str(total):
    """Convert total minutes to '1h 30m' format."""
    if total >= 60:
        return f"{total // 60}h {total % 60}m"
    return f"{total}m"


def write_vault_daily_note(
    state, live_state, project_name=None, feature=None, project_dir=None
):
    """Write/update today's daily note at ~/vault/daily/.

    Groups sessions by project. Regenerates daily stats on each write.
    Fail-open: never blocks session end.
    """
    vault_daily = os.path.join(os.path.expanduser("~"), "vault", "daily")
    if not os.path.isdir(vault_daily):
        return

    try:
        date_str = time.strftime("%Y-%m-%d")
        filepath = os.path.join(vault_daily, f"{date_str}.md")

        session_num = live_state.get("session_count", 0)
        project = project_name or live_state.get("project", "unknown")
        # For project sessions, read from project state (LIVE_STATE belongs to framework)
        _src = live_state
        if project_dir:
            try:
                _src = load_project_state(project_dir)
                session_num = _src.get("session_count", session_num)
            except Exception:
                _src = live_state

        what_was_done = _src.get("what_was_done", "No summary.")
        duration = _format_duration(state.get("session_start"))
        total_tools = state.get("total_tool_calls", state.get("tool_call_count", 0))
        feat = _src.get("feature", "")

        # Build session line
        parts = [f"Session {session_num}"]
        if feat:
            parts.append(f"({feat})")
        parts.append(f"— {duration} · {total_tools} tools")
        parts.append(f"— {what_was_done}")
        session_line = f"- {' '.join(parts)} [[{date_str}-session-{session_num:03d}]]"

        if os.path.exists(filepath):
            with open(filepath) as f:
                existing = f.read()
            header, projects = _parse_daily_sessions(existing)
        else:
            header = "\n".join(
                [
                    "---",
                    "type: daily",
                    "tags: [daily]",
                    f"created: {date_str}",
                    "status: active",
                    "---",
                    "",
                    f"# {date_str}",
                    "",
                    "## Plan",
                    "",
                    "",
                    "## Notes",
                    "",
                ]
            )
            projects = {}

        # Add session to its project group
        projects.setdefault(project, [])
        # Avoid duplicate if session_end runs twice
        if not any(f"Session {session_num}" in line for line in projects[project]):
            projects[project].append(session_line)

        # Rebuild file (strip trailing whitespace from header)
        lines = [header.rstrip(), "", "## Sessions", ""]
        for proj_name, sessions in projects.items():
            lines.append(f"### {proj_name}")
            for s in sessions:
                lines.append(s)
            lines.append("")

        # Daily stats
        total_sessions = sum(len(s) for s in projects.values())
        total_mins = 0
        total_tool_count = 0
        for sessions in projects.values():
            for s in sessions:
                # Parse duration from "— 1h 30m · 42 tools"
                import re

                dur_match = re.search(r"— (\d+h\s*)?(\d+m)", s)
                if dur_match:
                    total_mins += _duration_to_minutes(dur_match.group(0)[2:])
                tool_match = re.search(r"(\d+) tools", s)
                if tool_match:
                    total_tool_count += int(tool_match.group(1))

        lines.append("---")
        lines.append("")
        lines.append("## Daily Stats")
        lines.append(
            f"**Sessions:** {total_sessions} · "
            f"**Duration:** {_minutes_to_str(total_mins)} · "
            f"**Tools:** {total_tool_count}"
        )
        lines.append(f"**Projects:** {', '.join(projects.keys())}")
        lines.append("")

        content = "\n".join(lines)
        tmp_path = filepath + ".tmp"
        with open(tmp_path, "w") as f:
            f.write(content)
        os.replace(tmp_path, filepath)

        action = "Created" if total_sessions == 1 else "Updated"
        print(f"[SESSION_END:daily] {action} {date_str}.md", file=sys.stderr)
    except Exception as e:
        print(f"[SESSION_END:daily] Failed (non-fatal): {e}", file=sys.stderr)


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
        generate_handoff(
            state,
            transcript_path=transcript_path,
            project_name=project_name,
            project_dir=project_dir,
        )
    except Exception as e:
        print(f"[SESSION_END:bg] Handoff error: {e}", file=sys.stderr)

    # Write Obsidian vault session note (fail-open)
    try:
        live_state = _load_live_state()
        write_vault_session_note(
            state,
            live_state,
            project_name=project_name,
            feature=live_state.get("feature"),
            project_dir=project_dir,
        )
    except Exception as e:
        print(f"[SESSION_END:bg] Vault note error: {e}", file=sys.stderr)

    # Append to daily note (fail-open)
    try:
        try:
            live_state
        except NameError:
            live_state = _load_live_state()
        if not live_state:
            live_state = _load_live_state()
        write_vault_daily_note(
            state,
            live_state,
            project_name=project_name,
            feature=live_state.get("feature"),
            project_dir=project_dir,
        )
    except Exception as e:
        print(f"[SESSION_END:bg] Daily note error: {e}", file=sys.stderr)

    try:
        flush_capture_queue()
    except Exception as e:
        print(f"[SESSION_END:bg] Flush error: {e}", file=sys.stderr)

    try:
        backup_database()
    except Exception as e:
        print(f"[SESSION_END:bg] Backup error: {e}", file=sys.stderr)

    try:
        compact_if_needed()
    except Exception as e:
        print(f"[SESSION_END:bg] Compaction error: {e}", file=sys.stderr)

    try:
        from scripts.flush_audit import flush as flush_audit

        flushed, freed = flush_audit()
        if flushed > 0:
            print(
                f"[SESSION_END:bg] Audit flush: {flushed} files, {freed / 1024 / 1024:.1f}MB freed",
                file=sys.stderr,
            )
    except Exception as e:
        print(f"[SESSION_END:bg] Audit flush failed: {e}", file=sys.stderr)

    # DAG auto-promotion: promote high-value conversation nodes to SQLite knowledge
    try:
        from shared.dag import get_session_dag
        from shared.dag_memory_layer import DAGMemoryLayer, promote_nodes

        _dag = get_session_dag("main")
        _dag_layer = DAGMemoryLayer(_dag)
        _promoted = promote_nodes(_dag, _dag_layer)
        if _promoted:
            print(
                f"[SESSION_END:bg] DAG auto-promoted {len(_promoted)} nodes to knowledge",
                file=sys.stderr,
            )
        # FTS5 optimize: merge b-tree segments on session close
        _dag.optimize_fts()
        print("[SESSION_END:bg] DAG FTS5 optimized", file=sys.stderr)
    except Exception as e:
        print(f"[SESSION_END:bg] DAG promotion failed: {e}", file=sys.stderr)

    try:
        _tg_notify = False
        try:
            with open(LIVE_STATE_FILE) as _f:
                _tg_notify = json.load(_f).get("tg_session_notify", False)
        except Exception:
            pass
        _tg_hook = os.path.join(
            CLAUDE_DIR, "integrations", "telegram-bot", "hooks", "on_session_end.py"
        )
        if _tg_notify and os.path.isfile(_tg_hook):
            subprocess.run(
                [sys.executable, _tg_hook],
                timeout=30,
                capture_output=False,
                stdin=subprocess.DEVNULL,
            )
    except Exception:
        pass

    try:
        _term_hook = os.path.join(
            CLAUDE_DIR, "integrations", "terminal-history", "hooks", "on_session_end.py"
        )
        if os.path.isfile(_term_hook):
            subprocess.run(
                [sys.executable, _term_hook],
                timeout=30,
                capture_output=False,
                input=json.dumps(session_data),
                text=True,
            )
    except Exception:
        pass

    # Batch classification at session end
    try:
        _cfg_path = os.path.join(CLAUDE_DIR, "config.json")
        _classify_mode = ""
        if os.path.isfile(_cfg_path):
            with open(_cfg_path) as _cf:
                _classify_mode = json.load(_cf).get("memory_classify_mode", "")
        if _classify_mode == "batch_end":
            import lancedb as _lancedb
            from shared.memory_classification import (
                classify_via_daemon as _classify_via_daemon,
            )

            _lance_path = os.path.join(MEMORY_DIR, "lancedb")
            _db = _lancedb.connect(_lance_path)
            _tbl = _db.open_table("knowledge")
            _rows = (
                _tbl.search()
                .where("memory_type = ''", prefilter=True)
                .limit(200)
                .to_list()
            )
            _classified = 0
            for _row in _rows:
                _row_id = _row.get("id", "")
                if not _row_id:
                    continue
                _mt = _classify_via_daemon(
                    _row.get("document", "")[:500], _row.get("tags", "")
                )
                if _mt:
                    _tbl.update(where=f"id = '{_row_id}'", values={"memory_type": _mt})
                    _classified += 1
            print(
                f"[SESSION_END:bg] Batch classified {_classified} memories",
                file=sys.stderr,
            )
    except Exception as _e:
        print(
            f"[SESSION_END:bg] Batch classification error (non-fatal): {_e}",
            file=sys.stderr,
        )

    # Run memory consolidation analysis (merge/promote/archive candidates)
    try:
        from shared.memory_consolidation import run_consolidation_analysis

        # Only log candidates — don't auto-act (human review gate)
        print(
            "[SESSION_END:bg] Running memory consolidation analysis...", file=sys.stderr
        )
    except ImportError:
        pass
    except Exception as _ce:
        print(
            f"[SESSION_END:bg] Consolidation error (non-fatal): {_ce}", file=sys.stderr
        )

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
        _project_name, _project_dir, _subproject_name, _subproject_dir = detect_project(
            _cwd
        )
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
        fd, data_path = tempfile.mkstemp(
            prefix="session_end_", suffix=".json", dir=HOOKS_DIR
        )
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
