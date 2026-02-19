#!/usr/bin/env python3
"""Self-Healing Claude Framework — Boot Sequence

Runs on SessionStart to:
1. Load handoff context from previous session
2. Load live state
3. Inject relevant memories (auto-satisfies Gate 4)
4. Display a dashboard with project status + memory context
5. Reset enforcement state for new session
6. Flush stale capture queue

This ensures every session starts with full context rather than amnesia.
"""

import glob
import gzip
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta

# Add hooks dir to path for shared imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from shared.state import cleanup_all_states
from shared.chromadb_socket import is_worker_available as socket_available, query as socket_query, count as socket_count, flush_queue as socket_flush, remember as socket_remember, WorkerUnavailable

try:
    from shared.ramdisk import ensure_ramdisk as _ramdisk_ensure, get_capture_queue, get_state_dir as _ramdisk_state_dir
    _HAS_RAMDISK_MODULE = True
except ImportError:
    _HAS_RAMDISK_MODULE = False

CLAUDE_DIR = os.path.join(os.path.expanduser("~"), ".claude")
HANDOFF_FILE = os.path.join(CLAUDE_DIR, "HANDOFF.md")
LIVE_STATE_FILE = os.path.join(CLAUDE_DIR, "LIVE_STATE.json")
SIDEBAND_FILE = os.path.join(os.path.dirname(__file__), ".memory_last_queried")
STATE_DIR = _ramdisk_state_dir() if _HAS_RAMDISK_MODULE else os.path.join(os.path.dirname(__file__))


def read_file(path):
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        return None


def extract_summary(handoff_content):
    """Extract the first meaningful line from HANDOFF.md as a summary."""
    if not handoff_content:
        return "No handoff file found"
    for line in handoff_content.split("\n"):
        line = line.strip()
        if line and not line.startswith("#") and not line.startswith("---"):
            return line[:70]
    return "Handoff exists but no summary found"



def load_live_state():
    content = read_file(LIVE_STATE_FILE)
    if content:
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {}
    return {}


def reset_enforcement_state():
    """Reset all gate enforcement state files for a new session.

    Cleans up per-agent state files from the previous session (each team member
    had its own state_*.json file) and the legacy shared state.json.
    The new session's main agent will create its own state file on first tool use.
    """
    cleanup_all_states()



def _is_port_in_use(port):
    """Check if a TCP port is in use by attempting a socket connect."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            s.connect(("127.0.0.1", port))
            return True
    except (ConnectionRefusedError, OSError):
        return False


def _auto_start_dashboard():
    """Start the dashboard server if not already running on port 7777."""
    try:
        if _is_port_in_use(7777):
            print("  [BOOT] Dashboard already running at http://localhost:7777", file=sys.stderr)
            return

        server_path = os.path.join(CLAUDE_DIR, "dashboard", "server.py")
        if not os.path.isfile(server_path):
            return

        proc = subprocess.Popen(
            [sys.executable, server_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        # Store PID for later cleanup
        pidfile = os.path.join(CLAUDE_DIR, "dashboard", ".dashboard.pid")
        try:
            with open(pidfile, "w") as f:
                f.write(str(proc.pid))
        except OSError:
            pass

        print(f"  [BOOT] Dashboard auto-started at http://localhost:7777 (pid {proc.pid})", file=sys.stderr)
    except Exception:
        pass  # Boot must never crash


def _write_sideband_timestamp():
    """Write fresh sideband timestamp (auto-injection counts as querying memory)."""
    try:
        tmp = SIDEBAND_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"timestamp": time.time()}, f)
        os.replace(tmp, SIDEBAND_FILE)
    except OSError:
        pass


def _extract_recent_errors():
    """Extract top 5 error patterns from the most recent session state file.

    This is called BEFORE reset_enforcement_state() wipes all state files.
    Returns a list of strings like ["SyntaxError (3x)", "ImportError (2x)"].
    """
    try:
        # Find all state_*.json files in the hooks directory
        pattern = os.path.join(STATE_DIR, "state_*.json")
        state_files = glob.glob(pattern)

        if not state_files:
            return []

        # Get the most recent file by modification time
        most_recent = max(state_files, key=os.path.getmtime)

        # Read the state file
        with open(most_recent) as f:
            state_data = json.load(f)

        # Extract error patterns from error_pattern_counts
        error_counts = state_data.get("error_pattern_counts", {})
        if not error_counts:
            return []

        # Sort by count (descending) and take top 5
        sorted_errors = sorted(error_counts.items(), key=lambda x: x[1], reverse=True)
        top_5 = sorted_errors[:5]

        # Format as ["ErrorType (Nx)", ...]
        return [f"{err_type} ({count}x)" for err_type, count in top_5]

    except Exception:
        # Boot must never crash
        return []


def _extract_test_status():
    """Extract last test run info from the most recent session state file.

    Returns a dict with keys: framework, passed (bool), minutes_ago (int or None).
    Returns None if no test info found.
    """
    try:
        pattern = os.path.join(STATE_DIR, "state_*.json")
        state_files = glob.glob(pattern)
        if not state_files:
            return None

        most_recent = max(state_files, key=os.path.getmtime)
        with open(most_recent) as f:
            state_data = json.load(f)

        last_test = state_data.get("last_test_run", 0)
        if last_test == 0:
            return None

        elapsed = time.time() - last_test
        minutes_ago = int(elapsed / 60)
        exit_code = state_data.get("last_test_exit_code", None)
        passed = (exit_code == 0) if exit_code is not None else None
        command = state_data.get("last_test_command", "")

        # Detect framework from command
        framework = "unknown"
        if "pytest" in command:
            framework = "pytest"
        elif "npm test" in command:
            framework = "npm test"
        elif "cargo test" in command:
            framework = "cargo test"
        elif "go test" in command:
            framework = "go test"

        return {"framework": framework, "passed": passed, "minutes_ago": minutes_ago}
    except Exception:
        return None


def _extract_verification_quality():
    """Extract verification quality stats from the most recent session state file.

    This is called BEFORE reset_enforcement_state() wipes all state files.
    Returns {"verified": N, "pending": M} or None if no data found.
    """
    try:
        pattern = os.path.join(STATE_DIR, "state_*.json")
        state_files = glob.glob(pattern)

        if not state_files:
            return None

        # Get the most recent file by modification time
        most_recent = max(state_files, key=os.path.getmtime)

        with open(most_recent) as f:
            state_data = json.load(f)

        verified_fixes = state_data.get("verified_fixes", [])
        pending_verification = state_data.get("pending_verification", [])

        if not verified_fixes and not pending_verification:
            return None

        return {"verified": len(verified_fixes), "pending": len(pending_verification)}

    except Exception:
        # Boot must never crash
        return None


def _extract_session_duration():
    """Extract session duration from the most recent session state file.

    Returns a formatted string like "2h 15m" or "45m" or None if no data.
    """
    try:
        pattern = os.path.join(STATE_DIR, "state_*.json")
        state_files = glob.glob(pattern)
        if not state_files:
            return None

        most_recent = max(state_files, key=os.path.getmtime)
        with open(most_recent) as f:
            state_data = json.load(f)

        session_start = state_data.get("session_start", 0)
        if session_start == 0:
            return None

        elapsed = time.time() - session_start
        if elapsed < 60:
            return None  # Too short to display

        total_minutes = int(elapsed / 60)
        hours = total_minutes // 60
        minutes = total_minutes % 60
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"
    except Exception:
        return None


def _extract_tool_activity():
    """Extract tool usage stats from the most recent session state file.

    This is called BEFORE reset_enforcement_state() wipes all state files.
    Returns (tool_call_count, tool_summary_string) or (0, None).
    """
    try:
        # Find all state_*.json files in the hooks directory
        pattern = os.path.join(STATE_DIR, "state_*.json")
        state_files = glob.glob(pattern)

        if not state_files:
            return (0, None)

        # Get the most recent file by modification time
        most_recent = max(state_files, key=os.path.getmtime)

        # Read the state file
        with open(most_recent) as f:
            state_data = json.load(f)

        # Extract tool stats
        tool_stats = state_data.get("tool_stats", {})
        tool_call_count = state_data.get("tool_call_count", 0)

        if not tool_stats or tool_call_count == 0:
            return (0, None)

        # Sort by count and take top 3
        sorted_tools = sorted(tool_stats.items(), key=lambda x: x[1].get("count", 0), reverse=True)[:3]
        tool_summary = ", ".join(f"{name}:{info.get('count', 0)}" for name, info in sorted_tools)

        return (tool_call_count, tool_summary)

    except Exception:
        # Boot must never crash
        return (0, None)


# Tunable gate parameters: gate_name -> (param_name, default, loosen_by, tighten_by, min_val, max_val)
_TUNABLE_GATES = {
    "gate_04_memory_first":      ("freshness_window",      300,  120,  -60,   120,  900),
    "gate_05_proof_before_fixed": ("max_unverified",        3,    1,    -1,    2,    8),
    "gate_06_save_fix":          ("escalation_threshold",   5,    2,    -1,    3,    10),
    "gate_11_rate_limit":        ("block_threshold",        60,   10,   -5,    30,   120),
    "gate_15_causal_chain":      ("fix_history_freshness",  300,  120,  -60,   120,  900),
}


def _extract_gate_effectiveness_suggestions():
    """Extract gate effectiveness suggestions and compute auto-tune overrides.

    Returns (suggestions_list, overrides_dict).
    Only active when gate_auto_tune toggle is ON.
    When ON: low-effectiveness gates get loosened, high-effectiveness gates get tightened.
    Overrides are written to session state and read by gates at runtime.
    """
    try:
        from shared.state import get_live_toggle, load_gate_effectiveness
        if not get_live_toggle("gate_auto_tune", False):
            return [], {}

        # Read from persistent effectiveness file (accumulates across sessions)
        effectiveness = load_gate_effectiveness()
        if not effectiveness:
            return [], {}

        # Read previous overrides from most recent session state
        pattern = os.path.join(STATE_DIR, "state_*.json")
        state_files = glob.glob(pattern)
        prev_overrides = {}
        if state_files:
            most_recent = max(state_files, key=os.path.getmtime)
            with open(most_recent) as f:
                prev_overrides = json.load(f).get("gate_tune_overrides", {})

        suggestions = []
        overrides = {}
        for gate, stats in effectiveness.items():
            overrides_count = stats.get("overrides", 0)
            prevented = stats.get("prevented", 0)
            total_resolved = prevented + overrides_count
            if total_resolved < 3:
                continue
            eff_pct = round(100 * prevented / total_resolved)

            tunable = _TUNABLE_GATES.get(gate)
            if not tunable:
                continue
            param, default, loosen_by, tighten_by, min_val, max_val = tunable
            current = prev_overrides.get(gate, {}).get(param, default)

            if eff_pct < 50:
                new_val = min(current + loosen_by, max_val)
                overrides[gate] = {param: new_val}
                suggestions.append(f"{gate} {eff_pct}% -> {param}: {current}->{new_val}")
            elif eff_pct >= 90:
                new_val = max(current + tighten_by, min_val)
                overrides[gate] = {param: new_val}
                suggestions.append(f"{gate} {eff_pct}% -> {param}: {current}->{new_val}")

        return suggestions[:5], overrides
    except Exception:
        return [], {}


def _extract_gate_blocks():
    """Extract total gate blocks from recent audit logs.

    Returns count of blocked decisions from last 24h, or 0 if none/error.
    """
    try:
        audit_dir = os.path.join(os.path.dirname(__file__), "audit")
        if not os.path.isdir(audit_dir):
            return 0

        now = datetime.now()
        today = now.strftime("%Y-%m-%d")

        block_count = 0
        audit_file = os.path.join(audit_dir, f"{today}.jsonl")
        if os.path.isfile(audit_file):
            with open(audit_file) as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        if entry.get("decision") == "block":
                            block_count += 1
                    except json.JSONDecodeError:
                        continue
        return block_count
    except Exception:
        return 0


def inject_memories_via_socket(handoff_content, live_state):
    """Query memories via UDS socket for boot dashboard injection."""
    try:
        cnt = socket_count("knowledge")
        if cnt == 0:
            return []
    except (WorkerUnavailable, RuntimeError):
        return []

    # Build search query from handoff context
    query_parts = []
    project = live_state.get("project", "")
    if project:
        query_parts.append(project)
    feature = live_state.get("feature", "")
    if feature:
        query_parts.append(feature)
    if handoff_content:
        in_next = False
        for line in handoff_content.split("\n"):
            stripped = line.strip()
            if "what's next" in stripped.lower() or "whats next" in stripped.lower():
                in_next = True
                continue
            if in_next:
                if stripped.startswith("#") or stripped.startswith("---"):
                    break
                if stripped:
                    query_parts.append(stripped[:100])
    if not query_parts:
        query_parts.append("recent session activity framework")
    search_query = " ".join(query_parts)[:500]

    try:
        results = socket_query(
            "knowledge", [search_query], n_results=min(5, cnt),
            include=["metadatas", "distances"],
        )
    except (WorkerUnavailable, RuntimeError):
        return []

    if not results or not results.get("ids") or not results["ids"][0]:
        return []

    injected = []
    ids = results["ids"][0]
    metas = results["metadatas"][0] if results.get("metadatas") else []
    distances = results["distances"][0] if results.get("distances") else []
    for i, mid in enumerate(ids):
        distance = distances[i] if i < len(distances) else 1.0
        relevance = 1 - distance
        if relevance < 0.3:
            continue
        meta = metas[i] if i < len(metas) else {}
        preview = meta.get("preview", "(no preview)")
        display = preview[:58]
        if len(preview) > 58:
            display += ".."
        injected.append(f"[{mid[:8]}] {display}")
    return injected


# Audit log rotation settings
_AUDIT_COMPRESS_AFTER_DAYS = 2   # Gzip .jsonl files older than this
_AUDIT_DELETE_AFTER_DAYS = 30    # Delete .gz files older than this (DORMANT — set to 0 to activate)
_AUDIT_DELETE_ENABLED = False    # Flip to True to enable deletion of old .gz files


def _rotate_audit_logs():
    """Compress old audit logs, optionally delete ancient ones.

    Runs on each session start. Compresses .jsonl files older than
    _AUDIT_COMPRESS_AFTER_DAYS. Deletion of old .gz is dormant by default.
    """
    hooks_dir = os.path.dirname(__file__)
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


def main():
    # Bot subprocess sessions are lightweight — skip heavy boot
    if os.environ.get("TORUS_BOT_SESSION") == "1":
        print("[BOOT] Bot session — skipping full boot", file=sys.stderr)
        sys.exit(0)

    now = datetime.now()
    hour = now.hour
    day = now.strftime("%A")

    # Ensure ramdisk is set up (before any state/audit operations)
    if _HAS_RAMDISK_MODULE:
        try:
            ramdisk_ok = _ramdisk_ensure()
            if ramdisk_ok:
                print("  [BOOT] Ramdisk initialized at /run/user/{}/claude-hooks".format(os.getuid()), file=sys.stderr)
        except Exception:
            pass  # Ramdisk failure is non-fatal

    # Rotate old audit logs (compress, optionally delete)
    try:
        _rotate_audit_logs()
    except Exception:
        pass  # Rotation failure is non-fatal

    # Load context
    handoff = read_file(HANDOFF_FILE)
    live_state = load_live_state()
    session_num = live_state.get("session_count", "?")
    summary = extract_summary(handoff)

    # Time-based warnings
    time_warning = ""
    if 1 <= hour <= 5:
        time_warning = "  !! LATE NIGHT — Extra caution required !!"
    elif hour >= 22:
        time_warning = "  -- Late evening session --"

    # Project name from live state
    project_name = live_state.get("project", "Self-Healing Claude")
    active_tasks = live_state.get("active_tasks", [])

    # Gate count
    gates_dir = os.path.join(CLAUDE_DIR, "hooks", "gates")
    gate_count = 0
    if os.path.isdir(gates_dir):
        gate_count = len([f for f in os.listdir(gates_dir) if f.startswith("gate_") and f.endswith(".py")])

    # Check if UDS worker (memory_server.py) is available for ChromaDB access
    _worker_available = False
    try:
        _worker_available = socket_available(retries=2, delay=0.3)
    except Exception:
        pass

    # Watchdog: detect ChromaDB truncation/shrinkage early
    db_size_warning = None
    _mem_dir = os.path.join(os.path.expanduser("~"), "data", "memory")
    _db_path = os.path.join(_mem_dir, "chroma.sqlite3")
    _bak_path = os.path.join(_mem_dir, "chroma.sqlite3.backup")
    try:
        if os.path.exists(_db_path):
            _db_size = os.path.getsize(_db_path)
            if _db_size < 1024:  # < 1 KB = near-total truncation
                db_size_warning = f"chroma.sqlite3 is {_db_size} bytes — likely truncated"
            elif os.path.exists(_bak_path):
                _bak_size = os.path.getsize(_bak_path)
                if _bak_size > 0 and _db_size < _bak_size * 0.8:  # < 80% of backup
                    _db_mb = round(_db_size / (1024 * 1024), 1)
                    _bak_mb = round(_bak_size / (1024 * 1024), 1)
                    db_size_warning = f"chroma.sqlite3 shrunk: {_db_mb} MB vs {_bak_mb} MB backup — possible data loss"
    except OSError:
        pass

    # Inject relevant memories
    injected = inject_memories_via_socket(handoff, live_state) if _worker_available else []

    # Telegram L2 memory: search Saved Messages for relevant context
    tg_memories = []
    try:
        _tg_hook = os.path.join(CLAUDE_DIR, "integrations", "telegram-bot", "hooks", "on_session_start.py")
        if os.path.isfile(_tg_hook):
            _tg_query = f"{project_name} {live_state.get('feature', '')}"
            _tg_result = subprocess.run(
                [sys.executable, _tg_hook, _tg_query[:200]],
                capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL,
            )
            if _tg_result.returncode == 0 and _tg_result.stdout.strip():
                _tg_data = json.loads(_tg_result.stdout)
                tg_memories = _tg_data.get("results", [])[:3]
    except Exception:
        pass  # Telegram integration is optional

    # Extract gate effectiveness suggestions + auto-tune overrides (self-evolving)
    gate_suggestions, gate_overrides = _extract_gate_effectiveness_suggestions()

    # Extract recent errors BEFORE reset_enforcement_state() wipes them
    recent_errors = _extract_recent_errors()

    # Extract tool activity from last session
    tool_call_count, tool_summary = _extract_tool_activity()

    # Extract test status from last session
    test_status = _extract_test_status()

    # Extract verification quality from last session
    verification = _extract_verification_quality()

    # Extract session duration from last session
    session_duration = _extract_session_duration()

    # Extract gate blocks from audit log
    gate_blocks = _extract_gate_blocks()

    # Build dashboard
    dashboard = f"""
+====================================================================+
|  {project_name:<20} | Session {session_num:<6} | {day} {hour:02d}:{now.minute:02d}             |
|====================================================================|
|  LAST SESSION: {summary:<53}|
|--------------------------------------------------------------------|
|  GATES ACTIVE: {gate_count:<3} | MEMORY: ~/data/memory/                     |
|--------------------------------------------------------------------|"""

    if time_warning:
        dashboard += f"\n|  {time_warning:<67}|"
        dashboard += "\n|--------------------------------------------------------------------|"

    if db_size_warning:
        dashboard += f"\n|  DB WATCHDOG: {db_size_warning:<54}|"
        dashboard += "\n|--------------------------------------------------------------------|"

    if active_tasks:
        dashboard += "\n|  ACTIVE TASKS:                                                     |"
        for task in active_tasks[:3]:
            dashboard += f"\n|    - {task:<63}|"
        dashboard += "\n|--------------------------------------------------------------------|"

    if injected:
        dashboard += f"\n|  MEMORY CONTEXT ({len(injected)} relevant):{'':>42}|"
        for line in injected:
            dashboard += f"\n|    {line:<64}|"
        dashboard += "\n|--------------------------------------------------------------------|"

    if tg_memories:
        dashboard += f"\n|  TELEGRAM L2 ({len(tg_memories)} relevant):{'':>43}|"
        for tm in tg_memories:
            preview = tm.get("text", "")[:60]
            if len(tm.get("text", "")) > 60:
                preview += ".."
            dashboard += f"\n|    {preview:<64}|"
        dashboard += "\n|--------------------------------------------------------------------|"

    if recent_errors:
        dashboard += "\n|  RECENT ERRORS (from last session):                               |"
        for err in recent_errors:
            dashboard += f"\n|    - {err:<61}|"
        dashboard += "\n|--------------------------------------------------------------------|"

    # Test status from last session
    if test_status:
        status_icon = "PASS" if test_status["passed"] else ("FAIL" if test_status["passed"] is not None else "??")
        fw = test_status["framework"]
        mins = test_status["minutes_ago"]
        test_line = f"Last test: {status_icon} ({fw}, {mins}m ago)"
        dashboard += f"\n|  {test_line:<66}|"
        dashboard += "\n|--------------------------------------------------------------------|"

    # Verification quality from last session
    if verification:
        vq_line = f"VERIFICATION: {verification['verified']} verified, {verification['pending']} pending"
        dashboard += f"\n|  {vq_line:<66}|"
        dashboard += "\n|--------------------------------------------------------------------|"

    # Session duration from last session
    if session_duration:
        dur_line = f"Session duration: {session_duration}"
        dashboard += f"\n|  {dur_line:<66}|"
        dashboard += "\n|--------------------------------------------------------------------|"

    # Tool activity from last session
    if tool_summary:
        activity_line = f"Tool activity: {tool_call_count} calls ({tool_summary})"
        dashboard += f"\n|  {activity_line:<66}|"
        dashboard += "\n|--------------------------------------------------------------------|"

    # Gate block stats from audit log
    if gate_blocks > 0:
        block_line = f"Gate blocks today: {gate_blocks}"
        dashboard += f"\n|  {block_line:<66}|"
        dashboard += "\n|--------------------------------------------------------------------|"

    # Gate effectiveness suggestions (self-evolving)
    if gate_suggestions:
        dashboard += "\n|  GATE EFFECTIVENESS (auto-tune):                                   |"
        for gs in gate_suggestions:
            gs_display = gs[:62]
            dashboard += f"\n|    {gs_display:<64}|"
        dashboard += "\n|--------------------------------------------------------------------|"

    dashboard += """
|  TIP: Query memory about your task before starting work.           |
+====================================================================+
"""

    # Print to stderr (displayed in user's terminal)
    print(dashboard, file=sys.stderr)

    # Print to stdout (INJECTED INTO CLAUDE'S CONVERSATION CONTEXT)
    # This is the mechanical fix for the session start protocol.
    # SessionStart stdout is one of only two hook types where stdout
    # becomes conversation context (the other is UserPromptSubmit).
    context_parts = [f"<session-start-context>"]
    context_parts.append(f"Session {session_num} | Project: {project_name}")
    if handoff:
        # Include the full handoff so Claude has complete context
        context_parts.append(f"HANDOFF.md contents:\n{handoff}")
    else:
        context_parts.append("No HANDOFF.md found — this may be a fresh project.")
    if live_state:
        context_parts.append(f"LIVE_STATE.json: {json.dumps(live_state, indent=2)}")
    if active_tasks:
        context_parts.append(f"Active tasks: {', '.join(active_tasks[:5])}")
    if injected:
        context_parts.append(f"Relevant memories: {'; '.join(injected)}")
    if tg_memories:
        tg_summaries = [f"[{tm.get('date', '?')}] {tm.get('text', '')[:100]}" for tm in tg_memories]
        context_parts.append(f"Telegram L2 memories: {'; '.join(tg_summaries)}")
    # Build toggle status table from LIVE_STATE — (key, default, description)
    _toggles = [
        ("Terminal L2 always-on",  "terminal_l2_always", True,  "Always run terminal FTS5 search (OFF = only when L1 < 0.3)"),
        ("Terminal L2 enrichment", "context_enrichment",  False, "Attach ±30min terminal history to ChromaDB results"),
        ("TG L3 always-on",       "tg_l3_always",        False, "Always run Telegram FTS5 search (OFF = only when L1 < 0.3)"),
        ("TG L3 enrichment",      "tg_enrichment",       False, "Attach ±30min Telegram messages to ChromaDB results"),
        ("Telegram bot",           "tg_bot_tmux",         False, "Start/stop Telegram bot in dedicated tmux session"),
        ("Gate auto-tune",        "gate_auto_tune",      False, "Auto-adjust gate thresholds based on effectiveness data"),
        ("Chain memory",          "chain_memory",        False, "Remember and reuse successful skill chain sequences"),
        ("Session notify",        "tg_session_notify",   False, "Send session summary to Telegram on end"),
        ("Mirror messages",       "tg_mirror_messages",  False, "Send all Claude responses to Telegram"),
        ("Budget degradation",    "budget_degradation",  False, "Auto-degrade models when approaching token budget"),
    ]
    _toggle_lines = []
    _toggle_keys = []
    for label, key, default, desc in _toggles:
        val = live_state.get(key, default) if live_state else default
        _toggle_lines.append(f"{label}: {'ON' if val else 'OFF'} — {desc}")
        _toggle_keys.append(key)
    # Budget has a numeric value too
    _budget_val = live_state.get("session_token_budget", 0) if live_state else 0
    _toggle_lines.append(f"Session token budget: {_budget_val} — Max tokens per session (0 = unlimited)")
    _toggle_keys.append("session_token_budget")
    # Check Telegram bot config status
    _tg_config_path = os.path.join(CLAUDE_DIR, "integrations", "telegram-bot", "config.json")
    _tg_config_status = "not configured"
    try:
        with open(_tg_config_path) as f:
            _tg_conf = json.load(f)
        _tg_token = _tg_conf.get("bot_token", "")
        _tg_users = _tg_conf.get("allowed_users", [])
        if _tg_token and _tg_users:
            _tg_config_status = f"configured (token: ...{_tg_token[-6:]}, users: {_tg_users})"
        else:
            _tg_config_status = "incomplete — missing " + (
                "bot_token" if not _tg_token else "allowed_users"
            )
    except (OSError, json.JSONDecodeError):
        _tg_config_status = "config.json missing"

    _toggle_display = " | ".join(_toggle_lines)
    _toggle_key_list = ", ".join(_toggle_keys)
    context_parts.append(
        "PROTOCOL: Present session number, brief summary, completed list (what was done last session), "
        "and remaining list (what's next) in ONE message. "
        "IMPORTANT — Always display the current toggle states table to the user in your greeting. "
        f"Current toggles: {_toggle_display}. "
        f"Telegram bot config: {_tg_config_status}. "
        "Ask: 'Continue or New task?' "
        "If user says continue, ask which item to tackle — do NOT auto-start work. "
        "If user changes any toggle, update the corresponding LIVE_STATE.json field "
        f"({_toggle_key_list}). "
        "SPECIAL — Telegram bot toggle (tg_bot_tmux): "
        "When user turns ON: (1) Check config at integrations/telegram-bot/config.json — "
        "if bot_token or allowed_users missing, ask user for them using AskUserQuestion "
        "(bot token from @BotFather, Telegram user ID for whitelist). "
        "If already configured, ask if they want to keep or change the current bot_token and allowed_users. "
        "(2) Update config.json with any changes. "
        "(3) Start the bot: create tmux session 'claude-bot' and run "
        "'python3 integrations/telegram-bot/bot.py' in it. "
        "(4) Update LIVE_STATE.json tg_bot_tmux=true. "
        "When user turns OFF: (1) Kill the bot process in tmux session 'claude-bot'. "
        "(2) Update LIVE_STATE.json tg_bot_tmux=false."
    )
    context_parts.append("</session-start-context>")
    print("\n".join(context_parts))

    # Auto-start dashboard server
    _auto_start_dashboard()

    # Reset state
    reset_enforcement_state()

    # Write auto-tune overrides to fresh session state (gates read these at runtime)
    if gate_overrides:
        try:
            from shared.state import load_state, save_state
            _tune_state = load_state(session_id="main")
            _tune_state["gate_tune_overrides"] = gate_overrides
            save_state(_tune_state, session_id="main")
            print(f"  [BOOT] Auto-tune: {len(gate_overrides)} gate threshold(s) adjusted", file=sys.stderr)
        except Exception:
            pass  # Boot must never crash

    # Clean up workspace isolation claims (fresh session = fresh claims)
    claims_file = os.path.join(os.path.dirname(__file__), ".file_claims.json")
    try:
        if os.path.exists(claims_file):
            os.remove(claims_file)
    except OSError:
        pass

    # Flush stale capture queue from previous session (crash recovery)
    try:
        capture_queue = get_capture_queue() if _HAS_RAMDISK_MODULE else os.path.join(os.path.dirname(__file__), ".capture_queue.jsonl")
        if _worker_available and os.path.exists(capture_queue) and os.path.getsize(capture_queue) > 0:
            flushed = socket_flush()
            print(f"  [BOOT] Flushed {flushed} stale observations via UDS", file=sys.stderr)
    except Exception:
        pass  # Boot must never crash

    # Ingest auto-remember queue from previous session
    try:
        auto_queue = os.path.join(os.path.dirname(__file__), ".auto_remember_queue.jsonl")
        if _worker_available and os.path.exists(auto_queue) and os.path.getsize(auto_queue) > 0:
            # Atomically read and clear
            tmp_path = auto_queue + ".ingesting"
            os.replace(auto_queue, tmp_path)
            ingested = 0
            with open(tmp_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        socket_remember(
                            entry.get("content", ""),
                            entry.get("context", ""),
                            entry.get("tags", ""),
                        )
                        ingested += 1
                    except Exception:
                        pass  # Skip malformed entries
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            if ingested > 0:
                print(f"  [BOOT] Ingested {ingested} auto-remember entries via UDS", file=sys.stderr)
    except Exception:
        pass  # Boot must never crash

    # Write sideband timestamp (auto-injection satisfies Gate 4)
    _write_sideband_timestamp()


if __name__ == "__main__":
    main()
