"""Boot sequence orchestrator — main() entry point."""

import json
import os
import subprocess
import sys

from datetime import datetime

from boot_pkg.util import (
    CLAUDE_DIR,
    read_file,
    load_live_state,
    detect_project,
    load_project_state,
    scan_all_project_states,
    scan_subproject_states,
)
from boot_pkg.memory import (
    inject_memories_via_socket,
    _write_sideband_timestamp,
    socket_available,
    socket_flush,
    socket_remember,
)
from boot_pkg.context import (
    _extract_recent_errors,
    _extract_test_status,
    _extract_verification_quality,
    _extract_session_duration,
    _extract_tool_activity,
    _extract_gate_effectiveness_suggestions,
    _extract_gate_blocks,
    _extract_git_context,
)
from boot_pkg.maintenance import (
    reset_enforcement_state,
    _rotate_audit_logs,
    sync_agent_models,
)
from shared.context_compressor import compress_boot_state

try:
    from shared.ramdisk import ensure_ramdisk as _ramdisk_ensure, get_capture_queue

    _HAS_RAMDISK_MODULE = True
except ImportError:
    _HAS_RAMDISK_MODULE = False

try:
    from shared.gate_health import get_gate_health_report as _get_gate_health_report

    _HAS_GATE_HEALTH = True
except ImportError:
    _HAS_GATE_HEALTH = False


def main():
    # Bot subprocess sessions are lightweight — skip heavy boot
    if os.environ.get("TORUS_BOT_SESSION") == "1":
        print("[BOOT] Bot session — skipping full boot", file=sys.stderr)
        sys.exit(0)

    # Read stdin for cwd (Claude Code passes JSON with cwd on SessionStart)
    _boot_cwd = None
    try:
        import select

        if select.select([sys.stdin], [], [], 0)[0]:
            _stdin_data = json.loads(sys.stdin.read())
            _boot_cwd = _stdin_data.get("cwd")
    except Exception:
        pass

    # Detect if we're in a project under ~/projects/
    _project_name, _project_dir, _subproject_name, _subproject_dir = detect_project(
        _boot_cwd
    )
    _is_project_session = _project_name is not None
    _effective_dir = _subproject_dir or _project_dir
    _effective_name = (
        f"{_project_name}/{_subproject_name}" if _subproject_name else _project_name
    )

    now = datetime.now()
    hour = now.hour
    day = now.strftime("%A")

    # Ensure ramdisk is set up (before any state/audit operations)
    if _HAS_RAMDISK_MODULE:
        try:
            ramdisk_ok = _ramdisk_ensure()
            if ramdisk_ok:
                print(
                    "  [BOOT] Ramdisk initialized at /run/user/{}/claude-hooks".format(
                        os.getuid()
                    ),
                    file=sys.stderr,
                )
        except Exception:
            pass  # Ramdisk failure is non-fatal

    # Rotate old audit logs (compress, optionally delete)
    try:
        _rotate_audit_logs()
    except Exception:
        pass  # Rotation failure is non-fatal

    # Sync agent .md frontmatter models to active profile
    try:
        sync_agent_models()
    except Exception:
        pass  # Agent model sync is non-fatal

    # Load context
    live_state = load_live_state()

    # Override with project-specific state if in a project session
    _project_state = {}
    if _is_project_session:
        _project_state = load_project_state(_effective_dir)
        if _project_state:
            session_num = _project_state.get("session_count", 1)
            summary = (
                _project_state.get("what_was_done", "") or "No prior session data"
            )[:100]
        else:
            # First session for this project/subproject — don't inherit framework state
            session_num = 1
            summary = "First session for this project"
    else:
        session_num = live_state.get("session_count", "?")
        summary = (live_state.get("what_was_done", "") or "No prior session data")[:100]

    # Domain mastery: load active domain (only if explicitly activated by user)
    _domain_name = None
    _domain_mastery = ""
    _domain_behavior = ""
    try:
        from shared.domain_registry import (
            get_active_domain,
            get_domain_context_for_injection,
        )

        _domain_name = get_active_domain()
        if _domain_name:
            _domain_mastery, _domain_behavior = get_domain_context_for_injection(
                _domain_name
            )
    except Exception:
        pass  # Domain system is non-fatal

    # Time-based warnings
    time_warning = ""
    if 1 <= hour <= 5:
        time_warning = "  !! LATE NIGHT — Extra caution required !!"
    elif hour >= 22:
        time_warning = "  -- Late evening session --"

    # Project name from live state (or project state if in a project session)
    if _is_project_session:
        project_name = _project_state.get("project_name", _effective_name)
        active_tasks = _project_state.get("active_tasks", [])
    else:
        project_name = live_state.get("project", "Self-Healing Claude")
        active_tasks = live_state.get("active_tasks", [])

    # Gate count
    gates_dir = os.path.join(CLAUDE_DIR, "hooks", "gates")
    gate_count = 0
    if os.path.isdir(gates_dir):
        gate_count = len(
            [
                f
                for f in os.listdir(gates_dir)
                if f.startswith("gate_") and f.endswith(".py")
            ]
        )

    # Check if UDS worker (memory_server.py) is available
    _worker_available = False
    try:
        _worker_available = socket_available(retries=1, delay=0.1)
    except Exception:
        pass

    # Optionally start enforcer daemon for fast gate checking
    try:
        _cfg_path = os.path.join(CLAUDE_DIR, "config.json")
        _cfg = {}
        if os.path.isfile(_cfg_path):
            with open(_cfg_path) as _f:
                _cfg = json.load(_f)
        if _cfg.get("enforcer_daemon", False):
            _hooks_dir = os.path.join(CLAUDE_DIR, "hooks")
            _daemon_path = os.path.join(_hooks_dir, "enforcer_daemon.py")
            _sock_path = os.path.join(_hooks_dir, ".enforcer.sock")
            _daemon_running = False
            if os.path.exists(_sock_path):
                try:
                    import socket as _sock

                    _s = _sock.socket(_sock.AF_UNIX, _sock.SOCK_STREAM)
                    _s.settimeout(1)
                    _s.connect(_sock_path)
                    _s.sendall(b'{"method":"ping"}\n')
                    _resp = _s.recv(1024)
                    _s.close()
                    _daemon_running = b"pong" in _resp
                except Exception:
                    pass
            if not _daemon_running and os.path.isfile(_daemon_path):
                subprocess.Popen(
                    [sys.executable, _daemon_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                print("  [BOOT] Enforcer daemon started", file=sys.stderr)
            elif _daemon_running:
                print("  [BOOT] Enforcer daemon already running", file=sys.stderr)
    except Exception:
        pass  # Daemon startup is optional, never block boot

    # Auto-start memory server (streamable-http, default transport)
    try:
        _mem_server_path = os.path.join(CLAUDE_DIR, "hooks", "memory_server.py")
        if os.path.isfile(_mem_server_path):
            _mem_running = False
            try:
                import socket as _sock

                _s = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
                _s.settimeout(1)
                _s.connect(("127.0.0.1", 8741))
                _s.close()
                _mem_running = True
            except Exception:
                pass
            if not _mem_running:
                subprocess.Popen(
                    [sys.executable, _mem_server_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                print(
                    "  [BOOT] Memory server started (streamable-http, port 8741)",
                    file=sys.stderr,
                )
            else:
                print(
                    "  [BOOT] Memory server already running (port 8741)",
                    file=sys.stderr,
                )
    except Exception:
        pass  # Memory server startup is optional, never block boot

    # Batch classification at session start
    try:
        if _cfg.get("memory_classify_mode") == "batch_start":
            import lancedb as _lancedb

            sys.path.insert(0, os.path.join(CLAUDE_DIR, "hooks"))
            from shared.memory_classification import (
                classify_via_daemon as _classify_via_daemon,
            )

            _mem_dir_batch = os.path.join(os.path.expanduser("~"), "data", "memory")
            _lance_path_batch = os.path.join(_mem_dir_batch, "lancedb")
            _db_batch = _lancedb.connect(_lance_path_batch)
            _tbl_batch = _db_batch.open_table("knowledge")
            _rows_batch = (
                _tbl_batch.search()
                .where("memory_type = ''", prefilter=True)
                .limit(200)
                .to_list()
            )
            _classified_batch = 0
            for _row_b in _rows_batch:
                _row_id_b = _row_b.get("id", "")
                if not _row_id_b:
                    continue
                _mt_b = _classify_via_daemon(
                    _row_b.get("document", "")[:500], _row_b.get("tags", "")
                )
                if _mt_b:
                    _tbl_batch.update(
                        where=f"id = '{_row_id_b}'", values={"memory_type": _mt_b}
                    )
                    _classified_batch += 1
            print(
                f"  [BOOT] Batch classified {_classified_batch} memories",
                file=sys.stderr,
            )
    except Exception:
        pass  # Batch classification is non-fatal

    # Watchdog: verify LanceDB directory exists
    db_size_warning = None
    _mem_dir = os.path.join(os.path.expanduser("~"), "data", "memory")
    _lance_dir = os.path.join(_mem_dir, "lancedb")
    try:
        if not os.path.isdir(_lance_dir):
            db_size_warning = (
                "LanceDB directory missing — memory database may not be initialized"
            )
    except OSError:
        pass

    # Inject relevant memories (timeout-safe — socket may accept but worker stall)
    injected = []
    if _worker_available:
        try:
            injected = inject_memories_via_socket(live_state)
        except Exception:
            pass  # Memory injection failure must never crash boot

    # Telegram L2 memory: search Saved Messages for relevant context
    tg_memories = []
    try:
        _tg_hook = os.path.join(
            CLAUDE_DIR, "integrations", "telegram-bot", "hooks", "on_session_start.py"
        )
        if os.path.isfile(_tg_hook):
            _tg_query = f"{project_name} {live_state.get('feature', '')}"
            _tg_result = subprocess.run(
                [sys.executable, _tg_hook, _tg_query[:200]],
                capture_output=True,
                text=True,
                timeout=10,
                stdin=subprocess.DEVNULL,
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

    # Extract git context for session priming
    git_context = _extract_git_context()

    # Build dashboard
    dashboard = f"""
+====================================================================+
|  {project_name:<20} | Session {session_num:<6} | {day} {hour:02d}:{now.minute:02d}             |
|====================================================================|
|  LAST SESSION: {summary:<53}|
|--------------------------------------------------------------------|
|  GATES ACTIVE: {gate_count:<3} | MEMORY: ~/data/memory/                     |
|--------------------------------------------------------------------|"""

    if git_context:
        branch = git_context["branch"]
        uncommitted = git_context["uncommitted_count"]
        git_line = f"GIT: {branch}"
        if uncommitted > 0:
            git_line += f" ({uncommitted} uncommitted)"
        dashboard += f"\n|  {git_line:<66}|"
        dashboard += (
            "\n|--------------------------------------------------------------------|"
        )

    if time_warning:
        dashboard += f"\n|  {time_warning:<67}|"
        dashboard += (
            "\n|--------------------------------------------------------------------|"
        )

    if db_size_warning:
        dashboard += f"\n|  DB WATCHDOG: {db_size_warning:<54}|"
        dashboard += (
            "\n|--------------------------------------------------------------------|"
        )

    if active_tasks:
        dashboard += (
            "\n|  ACTIVE TASKS:                                                     |"
        )
        for task in active_tasks[:3]:
            dashboard += f"\n|    - {task:<63}|"
        dashboard += (
            "\n|--------------------------------------------------------------------|"
        )

    if injected:
        dashboard += f"\n|  MEMORY CONTEXT ({len(injected)} relevant):{'':>42}|"
        for line in injected:
            dashboard += f"\n|    {line:<64}|"
        dashboard += (
            "\n|--------------------------------------------------------------------|"
        )

    if tg_memories:
        dashboard += f"\n|  TELEGRAM L2 ({len(tg_memories)} relevant):{'':>43}|"
        for tm in tg_memories:
            preview = tm.get("text", "")[:60]
            if len(tm.get("text", "")) > 60:
                preview += ".."
            dashboard += f"\n|    {preview:<64}|"
        dashboard += (
            "\n|--------------------------------------------------------------------|"
        )

    if recent_errors:
        dashboard += (
            "\n|  RECENT ERRORS (from last session):                               |"
        )
        for err in recent_errors:
            dashboard += f"\n|    - {err:<61}|"
        dashboard += (
            "\n|--------------------------------------------------------------------|"
        )

    # Test status from last session
    if test_status:
        status_icon = (
            "PASS"
            if test_status["passed"]
            else ("FAIL" if test_status["passed"] is not None else "??")
        )
        fw = test_status["framework"]
        mins = test_status["minutes_ago"]
        test_line = f"Last test: {status_icon} ({fw}, {mins}m ago)"
        dashboard += f"\n|  {test_line:<66}|"
        dashboard += (
            "\n|--------------------------------------------------------------------|"
        )

    # Verification quality from last session
    if verification:
        vq_line = f"VERIFICATION: {verification['verified']} verified, {verification['pending']} pending"
        dashboard += f"\n|  {vq_line:<66}|"
        dashboard += (
            "\n|--------------------------------------------------------------------|"
        )

    # Session duration from last session
    if session_duration:
        dur_line = f"Session duration: {session_duration}"
        dashboard += f"\n|  {dur_line:<66}|"
        dashboard += (
            "\n|--------------------------------------------------------------------|"
        )

    # Tool activity from last session
    if tool_summary:
        activity_line = f"Tool activity: {tool_call_count} calls ({tool_summary})"
        dashboard += f"\n|  {activity_line:<66}|"
        dashboard += (
            "\n|--------------------------------------------------------------------|"
        )

    # Gate block stats from audit log
    if gate_blocks > 0:
        block_line = f"Gate blocks today: {gate_blocks}"
        dashboard += f"\n|  {block_line:<66}|"
        dashboard += (
            "\n|--------------------------------------------------------------------|"
        )

    # Gate effectiveness suggestions (self-evolving)
    if gate_suggestions:
        dashboard += (
            "\n|  GATE EFFECTIVENESS (auto-tune):                                   |"
        )
        for gs in gate_suggestions:
            gs_display = gs[:62]
            dashboard += f"\n|    {gs_display:<64}|"
        dashboard += (
            "\n|--------------------------------------------------------------------|"
        )

    # Hub mode: show all project states when launched from ~/.claude/
    if not _is_project_session:
        _all_project_states = scan_all_project_states()
        if _all_project_states:
            dashboard += "\n|  PROJECT STATES:                                                   |"
            for ps in _all_project_states:
                pname = ps.get("project_name", "?")
                pwhat = (ps.get("what_was_done", "") or "no data")[:50]
                dashboard += f"\n|    {pname}: {pwhat:<{63 - len(pname)}}|"
            dashboard += "\n|--------------------------------------------------------------------|"

    # Project-hub mode: show subproject states when at project level (no subproject)
    if _is_project_session and not _subproject_name:
        _sub_states = scan_subproject_states(_project_dir)
        if _sub_states:
            dashboard += "\n|  SUBPROJECT STATES:                                                |"
            for ss in _sub_states:
                sname = ss.get("project_name", "?")
                swhat = (ss.get("what_was_done", "") or "no data")[:50]
                dashboard += f"\n|    {sname}: {swhat:<{63 - len(sname)}}|"
            dashboard += "\n|--------------------------------------------------------------------|"

    if _domain_name:
        dom_label = f"DOMAIN: {_domain_name}"
        if _domain_mastery:
            dom_label += f" (mastery loaded, {len(_domain_mastery)} chars)"
        else:
            dom_label += " (no mastery yet)"
        dashboard += f"\n|  {dom_label:<66}|"
        dashboard += (
            "\n|--------------------------------------------------------------------|"
        )

    dashboard += """
|  TIP: Query memory about your task before starting work.           |
+====================================================================+
"""

    # Print to stderr (displayed in user's terminal)
    print(dashboard, file=sys.stderr)

    # Gate health summary line
    if _HAS_GATE_HEALTH:
        try:
            _health = _get_gate_health_report()
            _gate_count = _health.get("gate_count", 0)
            _degraded = len(_health.get("degraded_gates", []))
            _score = _health.get("health_score", 100)
            _avg_ms = _health.get("routing_stats", {}).get("avg_routing_ms", 0)
            print(
                f"[BOOT] Gates: {_gate_count} tracked, {_degraded} degraded, health {_score}/100, avg {_avg_ms:.1f}ms",
                file=sys.stderr,
            )
        except Exception:
            pass  # Gate health is non-critical

    # Print to stdout (INJECTED INTO CLAUDE'S CONVERSATION CONTEXT)
    context_parts = [f"<session-start-context>"]
    context_parts.append(f"Session {session_num} | Project: {project_name}")
    # Build context state for Claude's conversation
    if _is_project_session:
        # Project/subproject sessions: use project state exclusively, never leak LIVE_STATE
        if _project_state:
            PROJECT_CONTEXT_KEYS = {
                "session_count",
                "project_name",
                "feature",
                "what_was_done",
                "next_steps",
                "known_issues",
            }
            filtered = {
                k: v for k, v in _project_state.items() if k in PROJECT_CONTEXT_KEYS
            }
            filtered["project"] = _effective_name
        else:
            # First session — minimal context
            filtered = {
                "project": _effective_name,
                "session_count": 1,
                "what_was_done": "First session for this project",
            }
        # Truncate variable-length fields to cap token cost.
        if "what_was_done" in filtered:
            wd = filtered["what_was_done"]
            if len(wd) > 200:
                filtered["what_was_done"] = wd[:200] + "..."
        if "next_steps" in filtered:
            filtered["next_steps"] = filtered["next_steps"][:3]
        if "known_issues" in filtered:
            filtered["known_issues"] = filtered["known_issues"][:3]
        context_parts.append(f"project_state: {compress_boot_state(filtered)}")
    elif live_state:
        # Framework/hub sessions: use LIVE_STATE.json
        CONTEXT_KEYS = {
            "session_count",
            "project",
            "feature",
            "framework_version",
            "what_was_done",
            "next_steps",
            "known_issues",
        }
        filtered = {k: v for k, v in live_state.items() if k in CONTEXT_KEYS}
        if "what_was_done" in filtered:
            wd = filtered["what_was_done"]
            if len(wd) > 200:
                filtered["what_was_done"] = wd[:200] + "..."
        if "next_steps" in filtered:
            filtered["next_steps"] = filtered["next_steps"][:3]
        if "known_issues" in filtered:
            filtered["known_issues"] = filtered["known_issues"][:3]
        context_parts.append(f"LIVE_STATE.json: {compress_boot_state(filtered)}")
    if git_context:
        git_info = f"Git: branch={git_context['branch']}"
        if git_context["uncommitted_count"] > 0:
            git_info += f", {git_context['uncommitted_count']} uncommitted files"
        context_parts.append(git_info)
    if active_tasks:
        context_parts.append(f"Active tasks: {', '.join(active_tasks[:5])}")
    if injected:
        context_parts.append(f"Relevant memories: {'; '.join(injected)}")
    if tg_memories:
        tg_summaries = [
            f"[{tm.get('date', '?')}] {tm.get('text', '')[:100]}" for tm in tg_memories
        ]
        context_parts.append(f"Telegram L2 memories: {'; '.join(tg_summaries)}")
    if _domain_name:
        context_parts.append(f"Active domain: {_domain_name}")
        if _domain_mastery:
            context_parts.append(
                f'<domain-mastery domain="{_domain_name}">\n{_domain_mastery}\n</domain-mastery>'
            )
        if _domain_behavior:
            context_parts.append(
                f'<domain-behavior domain="{_domain_name}">\n{_domain_behavior}\n</domain-behavior>'
            )
    context_parts.append(
        "PROTOCOL: Present session number, brief summary, completed list (what was done last session), "
        "and remaining list (what's next) in ONE message. "
        "Ask: 'Continue or New task?' "
        "If user says continue, ask which item to tackle — do NOT auto-start work."
    )
    # Scribe agent directive — launch a named Haiku background agent for session notes
    _scribe_feed = os.path.join(
        f"/run/user/{os.getuid()}/claude-hooks",
        f".scribe_feed_{session_num}.jsonl",
    )
    context_parts.append(
        f'SCRIBE: launch Agent(name="scribe", model="haiku", run_in_background=true, '
        f'prompt="You are the scribe for this session. Feed file: {_scribe_feed} — '
        f'wait for finalize message.") — see agents/scribe.md'
    )
    # Inject working-memory and working-summary (hook-injected, not auto-loaded from rules/)
    _hooks_dir_inject = os.path.join(CLAUDE_DIR, "hooks")
    for _inject_file in ["working-memory.md", "working-summary.md"]:
        _inject_path = os.path.join(_hooks_dir_inject, _inject_file)
        try:
            with open(_inject_path) as _f:
                _inject_content = _f.read().strip()
                if _inject_content:
                    context_parts.append(_inject_content)
        except OSError:
            pass  # File missing at first session — skip silently
    # DAG: create per-session branch + inject context (B+C model)
    try:
        sys.path.insert(0, os.path.join(CLAUDE_DIR, "hooks"))
        from shared.dag import get_session_dag

        _dag = get_session_dag("main")
        # Create a new branch for this session with project scoping
        _dag.start_session_branch(
            session_num,
            project=_project_name,
            subproject=_subproject_name,
        )
        _dag_info = _dag.current_branch_info()
        _dag_total = _dag._db.execute("SELECT COUNT(*) FROM branches").fetchone()[0]
        context_parts.append(f"DAG: branch={_dag_info['name']} | {_dag_total} branches")
    except Exception:
        pass  # Fail-open

    context_parts.append("</session-start-context>")
    print("\n".join(context_parts))

    # Reset state
    reset_enforcement_state()

    # Write auto-tune overrides to fresh session state (gates read these at runtime)
    if gate_overrides:
        try:
            from shared.state import load_state, save_state

            _tune_state = load_state(session_id="main")
            _tune_state["gate_tune_overrides"] = gate_overrides
            save_state(_tune_state, session_id="main")
            print(
                f"  [BOOT] Auto-tune: {len(gate_overrides)} gate threshold(s) adjusted",
                file=sys.stderr,
            )
        except Exception:
            pass  # Boot must never crash

    # Clean up workspace isolation claims (fresh session = fresh claims)
    claims_file = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), ".file_claims.json"
    )
    try:
        if os.path.exists(claims_file):
            os.remove(claims_file)
    except OSError:
        pass

    # Flush stale capture queue from previous session (crash recovery)
    try:
        capture_queue = (
            get_capture_queue()
            if _HAS_RAMDISK_MODULE
            else os.path.join(
                os.path.dirname(os.path.dirname(__file__)), ".capture_queue.jsonl"
            )
        )
        if (
            _worker_available
            and os.path.exists(capture_queue)
            and os.path.getsize(capture_queue) > 0
        ):
            flushed = socket_flush()
            print(
                f"  [BOOT] Flushed {flushed} stale observations via UDS",
                file=sys.stderr,
            )
    except Exception:
        pass  # Boot must never crash

    # Ingest auto-remember queue from previous session
    try:
        auto_queue = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), ".auto_remember_queue.jsonl"
        )
        if (
            _worker_available
            and os.path.exists(auto_queue)
            and os.path.getsize(auto_queue) > 0
        ):
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
                print(
                    f"  [BOOT] Ingested {ingested} auto-remember entries via UDS",
                    file=sys.stderr,
                )
    except Exception:
        pass  # Boot must never crash

    # Sideband timestamp removed — Gate 4 should only pass when Claude
    # actually queries memory, not auto-satisfied at boot
