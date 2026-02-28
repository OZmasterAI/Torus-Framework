"""PostToolUse orchestrator — main handle_post_tool_use and entry point."""
import json
import os
import re
import sys
import time

from shared.state import load_state, save_state, update_gate_effectiveness, get_live_toggle, read_enforcer_sideband, delete_enforcer_sideband
from shared.error_normalizer import fnv1a_hash

from tracker_pkg import _log_debug
from tracker_pkg.errors import _extract_error_pattern, _detect_errors
from tracker_pkg.observations import _capture_observation
from tracker_pkg.verification import _classify_verification_score, _resolve_gate_block_outcomes, BROAD_TEST_COMMANDS
from tracker_pkg.auto_remember import _auto_remember_event

# Gate 17 injection scanning — imported here to run on PostToolUse results
try:
    from gates.gate_17_injection_defense import check as gate_17_check, _is_external_tool as _g17_is_external
except ImportError:
    gate_17_check = None
    _g17_is_external = None

# Token estimation per tool (module-level to avoid per-call dict creation)
_TOKEN_ESTIMATES = {"Bash": 2000, "Edit": 1500, "Write": 1500, "Read": 800, "Glob": 500, "Grep": 500, "NotebookEdit": 1500}

# MCP memory tools
MEMORY_TOOL_PREFIXES = [
    "mcp__memory__",
    "mcp_memory_",
]


def is_memory_tool(tool_name):
    for prefix in MEMORY_TOOL_PREFIXES:
        if tool_name.startswith(prefix):
            return True
    return False


def handle_post_tool_use(tool_name, tool_input, state, session_id="main", tool_response=None):
    """Track state after a tool call completes."""
    state["tool_call_count"] = state.get("tool_call_count", 0) + 1

    # Per-tool call counting for session metrics
    tool_call_counts = state.setdefault("tool_call_counts", {})
    tool_call_counts[tool_name] = tool_call_counts.get(tool_name, 0) + 1
    state["total_tool_calls"] = state.get("total_tool_calls", 0) + 1
    # Cap tool_call_counts at 50 keys (defensive, prevent unbounded growth)
    if len(tool_call_counts) > 50:
        sorted_tools = sorted(tool_call_counts.items(), key=lambda x: x[1])
        for k, _ in sorted_tools[:len(tool_call_counts) - 50]:
            del tool_call_counts[k]

    # Per-tool call stats
    tool_stats = state.setdefault("tool_stats", {})
    tool_entry = tool_stats.setdefault(tool_name, {"count": 0})
    tool_entry["count"] += 1

    # Token estimation (self-evolving: budget-aware degradation)
    token_est = _TOKEN_ESTIMATES.get(tool_name, 800)  # Default 800 for unknown tools
    if tool_name != "Task":  # Task tokens tracked separately in subagent_total_tokens
        state["session_token_estimate"] = state.get("session_token_estimate", 0) + token_est

    # Gate effectiveness: resolve pending block outcomes
    _resolve_gate_block_outcomes(tool_name, tool_input, state)

    # Auto-expire fixing_error after 30 minutes of staleness
    # Prevents permanent fixing_error=True when tests never pass
    if state.get("fixing_error", False):
        recent_failure = state.get("recent_test_failure")
        if isinstance(recent_failure, dict):
            failure_age = time.time() - recent_failure.get("timestamp", time.time())
            if failure_age > 1800:  # 30 minutes
                state["fixing_error"] = False
                state["recent_test_failure"] = None
                _log_debug("fixing_error auto-expired after 30 min staleness")

    # Track file reads (normalize paths to prevent bypass via ./foo vs foo)
    if tool_name == "Read":
        file_path = tool_input.get("file_path", "")
        if file_path:
            file_path = os.path.normpath(file_path)
            if file_path not in state.get("files_read", []):
                state["files_read"].append(file_path)

    # Track files edited (Edit/Write) for dashboard visibility
    if tool_name in ("Edit", "Write"):
        file_path = tool_input.get("file_path", "")
        if file_path:
            file_path = os.path.normpath(file_path)
            files_edited = state.setdefault("files_edited", [])
            if file_path not in files_edited:
                files_edited.append(file_path)
            # Cap at 200 entries
            if len(files_edited) > 200:
                state["files_edited"] = files_edited[-200:]

    # Write file claims for workspace isolation (Gate 13)
    if tool_name in ("Edit", "Write", "NotebookEdit"):
        try:
            import fcntl
            claim_path = tool_input.get("file_path", "") or tool_input.get("notebook_path", "")
            claim_session = state.get("_session_id", "main")
            if claim_path and claim_session != "main":
                claim_path = os.path.normpath(claim_path)
                claims_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".file_claims.json")
                claims = {}
                if os.path.exists(claims_file):
                    try:
                        with open(claims_file, "r") as f:
                            fcntl.flock(f, fcntl.LOCK_SH)
                            try:
                                claims = json.load(f)
                            finally:
                                fcntl.flock(f, fcntl.LOCK_UN)
                    except (json.JSONDecodeError, OSError, ValueError):
                        claims = {}
                claims[claim_path] = {
                    "session_id": claim_session,
                    "claimed_at": time.time(),
                }
                try:
                    with open(claims_file, "w") as f:
                        fcntl.flock(f, fcntl.LOCK_EX)
                        try:
                            json.dump(claims, f)
                        finally:
                            fcntl.flock(f, fcntl.LOCK_UN)
                except OSError:
                    pass
        except Exception as e:
            _log_debug(f"file claim write failed: {e}")

    # Track memory queries
    if is_memory_tool(tool_name):
        state["memory_last_queried"] = time.time()
        # F1: Redundant sideband write — keeps sideband fresh so Gate 4
        # doesn't block long-running subagents after the 5-min window
        try:
            from boot_pkg.memory import _write_sideband_timestamp
            _write_sideband_timestamp()
        except Exception:
            pass  # Best-effort redundancy

    if tool_name == "mcp__memory__remember_this":
        # Only reset Gate 6 counters if memory was actually saved (not deduped/rejected)
        resp = {}
        if isinstance(tool_response, dict):
            resp = tool_response
        elif isinstance(tool_response, str):
            try:
                resp = json.loads(tool_response)
            except Exception:
                pass
        was_rejected = resp.get("rejected", False) or resp.get("deduplicated", False)
        if not was_rejected:
            state["unlogged_errors"] = []
            state["error_pattern_counts"] = {}
            state["gate6_warn_count"] = 0  # Reset Gate 6 escalation on memory save
            state["verified_fixes"] = []  # Clear verified fixes — user saved to memory

    # Track skill invocations
    if tool_name == "Skill":
        try:
            skill_name = tool_input.get("skill", "") or tool_input.get("name", "")
            if skill_name:
                usage = state.setdefault("skill_usage", {})
                usage[skill_name] = usage.get(skill_name, 0) + 1
                recent = state.setdefault("recent_skills", [])
                recent.append({"name": skill_name, "timestamp": time.time()})
                # Cap at 50 recent entries
                if len(recent) > 50:
                    state["recent_skills"] = recent[-50:]
        except Exception as e:
            _log_debug(f"skill tracking failed: {e}")

    # Track ExitPlanMode for Gate 12
    if tool_name == "ExitPlanMode":
        state["last_exit_plan_mode"] = time.time()

    # Track test runs + causal chain auto-detect (Option A)
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        if any(kw in command for kw in ["pytest", "python -m pytest", "npm test", "cargo test", "go test", "test_framework.py"]):
            state["last_test_run"] = time.time()
            state["last_test_command"] = command[:200]
            state["session_test_baseline"] = True
            # Capture exit code from tool_response (Claude Code provides it there)
            exit_code = 0
            if tool_response is not None:
                if isinstance(tool_response, dict):
                    exit_code = tool_response.get("exit_code",
                                tool_response.get("exitCode",
                                tool_response.get("status", 0)))
                elif isinstance(tool_response, str):
                    try:
                        resp = json.loads(tool_response)
                        if isinstance(resp, dict):
                            exit_code = resp.get("exit_code",
                                        resp.get("exitCode",
                                        resp.get("status", 0)))
                    except (json.JSONDecodeError, TypeError):
                        pass
            state["last_test_exit_code"] = exit_code

            # Causal chain auto-detect: set recent_test_failure on non-zero exit
            if exit_code and exit_code != 0:
                # Detect primary error pattern from output
                error_pattern = _extract_error_pattern(tool_response)
                state["recent_test_failure"] = {
                    "pattern": error_pattern,
                    "timestamp": time.time(),
                    "command": command[:200],
                }
                state["fixing_error"] = True
            else:
                # Tests passed — clear error state
                # Trigger C: Error fix verified (critical — useful in current session)
                was_fixing = state.get("fixing_error", False)
                if was_fixing:
                    error_info = state.get("recent_test_failure", {})
                    pattern = error_info.get("pattern", "unknown") if isinstance(error_info, dict) else "unknown"
                    edited = list(state.get("files_edited", state.get("pending_verification", [])))[-5:]
                    _auto_remember_event(
                        f"Error fixed: {pattern}. Files edited: {', '.join(edited)}",
                        context=f"Test passed after fixing error: {command[:100]}",
                        tags="type:auto-captured,type:fix,area:framework",
                        critical=True, state=state,
                    )
                # Trigger A: Test run snapshot (queued for boot)
                edited_files = list(state.get("files_edited", state.get("pending_verification", [])))[-10:]
                _auto_remember_event(
                    f"Tests passed: {command[:150]}. Files modified this session: {', '.join(edited_files) if edited_files else 'none'}",
                    context="auto-captured test run snapshot",
                    tags="type:auto-captured,area:testing",
                    critical=False, state=state,
                )
                state["recent_test_failure"] = None
                state["fixing_error"] = False
                state["confidence_warned_signals"] = []  # Reset G14 signal suppression

        # Trigger B: Git commit (queued for boot)
        if "git commit" in command:
            _auto_remember_event(
                f"Git commit: {command[:200]}",
                context="auto-captured git commit",
                tags="type:auto-captured,area:git",
                critical=False, state=state,
            )

    # Track edits for pending verification (including NotebookEdit)
    if tool_name in ("Edit", "Write", "NotebookEdit"):
        file_path = tool_input.get("file_path", "") or tool_input.get("notebook_path", "")
        if file_path and file_path not in state.get("pending_verification", []):
            pending = state.get("pending_verification", [])
            pending.append(file_path)
            state["pending_verification"] = pending

        # Track edit streak per file
        edit_streak = state.setdefault("edit_streak", {})
        file_path = tool_input.get("file_path", "") or tool_input.get("notebook_path", "")
        if file_path:
            old_count = edit_streak.get(file_path, 0)
            edit_streak[file_path] = old_count + 1
            # Trigger D: Heavy edit session (first time crossing threshold per file)
            new_count = edit_streak[file_path]
            if old_count < 3 and new_count >= 3:
                _auto_remember_event(
                    f"Heavy editing: {file_path} ({new_count} edits this session)",
                    context="auto-captured heavy edit pattern",
                    tags="type:auto-captured,area:framework",
                    critical=False, state=state,
                )

    # Progressive verification scoring: accumulate confidence scores for pending files
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        score = _classify_verification_score(command)
        scores = state.setdefault("verification_scores", {})
        pending = state.get("pending_verification", [])

        # Reset edit streaks on verification
        state["edit_streak"] = {}

        if any(kw in command for kw in BROAD_TEST_COMMANDS):
            # Broad tests apply score to all pending files
            for fp in pending:
                scores[fp] = scores.get(fp, 0) + score
        else:
            # Targeted commands: score only files referenced in command
            for filepath in pending:
                basename = os.path.basename(filepath)
                stem = os.path.splitext(basename)[0]
                matched = (
                    re.search(r'\b' + re.escape(filepath) + r'\b', command)
                    or re.search(r'\b' + re.escape(basename) + r'\b', command)
                    or re.search(r'\b' + re.escape(stem) + r'\b', command)
                )
                if matched:
                    # Direct file execution (score >= 30) gets minimum 70 — running
                    # the exact file you edited is strong verification evidence
                    effective_score = max(score, 70) if score >= 30 else score
                    scores[filepath] = scores.get(filepath, 0) + effective_score

        # Clear files that have reached the verification threshold (>= 70)
        # Exclude temp files from verified_fixes (they trigger false positives in gate 6)
        _EXCLUDED_PREFIXES = ("/tmp/", "/var/tmp/", "/dev/")
        remaining = []
        for fp in pending:
            if scores.get(fp, 0) >= 70:
                if not any(fp.startswith(p) for p in _EXCLUDED_PREFIXES):
                    state.setdefault("verified_fixes", []).append(fp)
                    state.setdefault("verification_timestamps", {})[fp] = time.time()
                scores.pop(fp, None)
            else:
                remaining.append(fp)
        state["pending_verification"] = remaining

    # Detect errors in Bash output
    if tool_name == "Bash" and tool_response is not None:
        _detect_errors(tool_input, tool_response, state)

    # Causal fix tracking: record_attempt
    if tool_name == "mcp__memory__record_attempt":
        try:
            error_text = tool_input.get("error_text", "")
            strategy_id = tool_input.get("strategy_id", "")
            if error_text and strategy_id:
                from shared.error_normalizer import error_signature
                _, error_hash = error_signature(error_text)
                strategy_hash = fnv1a_hash(strategy_id)
                chain_id = f"{error_hash}_{strategy_hash}"
                state["current_strategy_id"] = strategy_id
                state["current_error_signature"] = error_hash
                pending = state.setdefault("pending_chain_ids", [])
                if chain_id not in pending:
                    pending.append(chain_id)
        except Exception as e:
            _log_debug(f"record_attempt tracking failed: {e}")

    # Causal fix tracking: record_outcome
    if tool_name == "mcp__memory__record_outcome":
        try:
            resp = tool_response if isinstance(tool_response, dict) else {}
            if isinstance(tool_response, str):
                try:
                    resp = json.loads(tool_response)
                except (json.JSONDecodeError, TypeError):
                    resp = {}
            strategy_id = resp.get("strategy_id", "") or state.get("current_strategy_id", "")
            outcome = resp.get("outcome", "")

            if strategy_id:
                # Track successful strategies
                if outcome == "success":
                    successes = state.setdefault("successful_strategies", {})
                    if strategy_id not in successes:
                        successes[strategy_id] = {"success_count": 0, "last_success": 0}
                    successes[strategy_id]["success_count"] += 1
                    successes[strategy_id]["last_success"] = time.time()

                # Track failures with retry budget (dict format)
                if resp.get("banned") or outcome == "failure":
                    bans = state.get("active_bans", [])
                    # Migrate list → dict if needed
                    if isinstance(bans, list):
                        bans_dict = {}
                        for sid in bans:
                            bans_dict[sid] = {"fail_count": 3, "first_failed": time.time(), "last_failed": time.time()}
                        bans = bans_dict
                        state["active_bans"] = bans
                    if strategy_id not in bans:
                        bans[strategy_id] = {"fail_count": 0, "first_failed": time.time(), "last_failed": time.time()}
                    if resp.get("banned"):
                        # Explicit ban from MCP: immediately set to ban threshold
                        bans[strategy_id]["fail_count"] = max(bans[strategy_id].get("fail_count", 0), 3)
                    else:
                        # Gradual failure: increment retry budget
                        bans[strategy_id]["fail_count"] = bans[strategy_id].get("fail_count", 0) + 1
                    bans[strategy_id]["last_failed"] = time.time()

            state["pending_chain_ids"] = []
            state["current_strategy_id"] = ""
        except Exception as e:
            _log_debug(f"record_outcome tracking failed: {e}")

    # Causal fix tracking: query_fix_history
    if tool_name == "mcp__memory__query_fix_history":
        state["fix_history_queried"] = time.time()
        try:
            resp = tool_response if isinstance(tool_response, dict) else {}
            if isinstance(tool_response, str):
                try:
                    resp = json.loads(tool_response)
                except (json.JSONDecodeError, TypeError):
                    resp = {}
            banned_list = resp.get("banned", [])
            bans = state.get("active_bans", [])
            # Migrate list → dict if needed
            if isinstance(bans, list):
                bans_dict = {}
                for sid in bans:
                    bans_dict[sid] = {"fail_count": 3, "first_failed": time.time(), "last_failed": time.time()}
                bans = bans_dict
                state["active_bans"] = bans
            for entry in banned_list:
                sid = entry.get("strategy_id", "") if isinstance(entry, dict) else ""
                if sid and sid not in bans:
                    bans[sid] = {"fail_count": 3, "first_failed": time.time(), "last_failed": time.time()}
        except Exception as e:
            _log_debug(f"query_fix_history tracking failed: {e}")

    # Gate 17: Injection defense — scan external tool results for prompt injection
    if gate_17_check is not None and _g17_is_external is not None:
        try:
            if _g17_is_external(tool_name) and tool_response:
                # Build tool_input-like dict with response content for gate_17 to scan
                resp_content = tool_response
                if isinstance(tool_response, dict):
                    resp_content = tool_response.get("content", "") or tool_response.get("output", "") or str(tool_response)
                g17_input = {"content": str(resp_content)[:50000]}  # Cap scan size
                result = gate_17_check(tool_name, g17_input, state, event_type="PostToolUse")
                if result.message:
                    print(result.message, file=sys.stderr)
                    # Record effectiveness
                    try:
                        update_gate_effectiveness("gate_17_injection_defense", "block")
                    except Exception:
                        pass
        except Exception as e:
            _log_debug(f"Gate 17 scan failed (non-blocking): {e}")

    # Analytics tool usage tracking (for Upgrades C+F)
    if tool_name.startswith("mcp__analytics__"):
        state["analytics_last_queried"] = time.time()
        state["analytics_warn_count"] = 0  # Reset F-track counter
        # Per-tool timestamp for C cooldowns
        alu = state.get("analytics_last_used", {})
        if not isinstance(alu, dict):
            alu = {}
        # Extract short tool name: mcp__analytics__gate_dashboard → gate_dashboard
        short_name = tool_name.replace("mcp__analytics__", "")
        alu[short_name] = time.time()
        state["analytics_last_used"] = alu

    _capture_observation(tool_name, tool_input, tool_response, session_id, state)

    # ── Mentor System (A+D+E+F) — all toggle-gated, all fail-open ──
    state["mentor_warned_this_cycle"] = False  # Reset at start of mentor block
    _mentor_t0 = time.time()
    _mentor_all = get_live_toggle("mentor_all")

    if _mentor_all or get_live_toggle("mentor_tracker"):
        try:
            from tracker_pkg.mentor import evaluate as mentor_evaluate
            verdict_a = mentor_evaluate(tool_name, tool_input, tool_response, state)
            if verdict_a and verdict_a.action in ("warn", "escalate"):
                print(f"[MENTOR] {verdict_a.message}", file=sys.stderr)
                state["mentor_warned_this_cycle"] = True
        except Exception as e:
            _log_debug(f"Mentor tracker failed (non-blocking): {e}")

    if (_mentor_all or get_live_toggle("mentor_outcome_chains")) and state.get("tool_call_count", 0) % 10 == 0:
        if time.time() - _mentor_t0 < 2.5:
            try:
                from tracker_pkg.outcome_chains import evaluate as chains_evaluate
                verdict_d = chains_evaluate(tool_name, tool_input, tool_response, state)
                if verdict_d and verdict_d.get("message") and not state.get("mentor_warned_this_cycle"):
                    print(f"[MENTOR:CHAINS] {verdict_d['message']}", file=sys.stderr)
            except Exception as e:
                _log_debug(f"Mentor outcome chains failed (non-blocking): {e}")

    if _mentor_all or get_live_toggle("mentor_memory"):
        if time.time() - _mentor_t0 < 2.5:
            try:
                from tracker_pkg.mentor_memory import evaluate as memory_evaluate
                verdict_e = memory_evaluate(tool_name, tool_input, tool_response, state)
                if verdict_e and verdict_e.get("context") and not state.get("mentor_warned_this_cycle"):
                    print(f"[MENTOR:MEMORY] {verdict_e['context']}", file=sys.stderr)
            except Exception as e:
                _log_debug(f"Mentor memory failed (non-blocking): {e}")

    if _mentor_all or get_live_toggle("mentor_analytics"):
        if time.time() - _mentor_t0 < 2.5:
            try:
                from tracker_pkg.mentor_analytics import evaluate as analytics_evaluate
                nudges_f = analytics_evaluate(tool_name, tool_input, tool_response, state)
                if nudges_f and not state.get("mentor_warned_this_cycle"):
                    # Max 1 nudge per cycle
                    print(f"[MENTOR:ANALYTICS] {nudges_f[0]}", file=sys.stderr)
            except Exception as e:
                _log_debug(f"Mentor analytics failed (non-blocking): {e}")

    # Session duration nudge — once per milestone (1h, 2h, 3h)
    session_hours = (time.time() - state.get("session_start", time.time())) / 3600
    last_nudge = state.get("session_duration_nudge_hour", 0)
    if session_hours >= 3 and last_nudge < 3:
        state["session_duration_nudge_hour"] = 3
        print("[SESSION] ADVISORY: Session running 3h+. Save progress with /wrap-up before context degrades.", file=sys.stderr)
    elif session_hours >= 2 and last_nudge < 2:
        state["session_duration_nudge_hour"] = 2
        print("[SESSION] ADVISORY: Session running 2h+. Consider saving key findings to memory.", file=sys.stderr)
    elif session_hours >= 1 and last_nudge < 1:
        state["session_duration_nudge_hour"] = 1
        print("[SESSION] ADVISORY: Session running 1h+. Good time for a memory checkpoint.", file=sys.stderr)

    save_state(state, session_id=session_id)
    # Promote complete: delete enforcer sideband (tracker is now the source of truth)
    delete_enforcer_sideband(session_id)


def main():
    """Main entry point — fail-open: always exits 0."""
    try:
        # Read tool call data from stdin (Claude Code hook protocol)
        try:
            data = json.load(sys.stdin)
        except (json.JSONDecodeError, EOFError):
            # PostToolUse is non-critical tracking — safe to skip
            sys.exit(0)

        tool_name = data.get("tool_name", "")
        if not tool_name:
            sys.exit(0)

        tool_input = data.get("tool_input", {})
        session_id = data.get("session_id", "main")
        tool_response = data.get("tool_response")

        state = load_state(session_id=session_id)
        state["_session_id"] = session_id

        # Merge enforcer sideband — gate mutations from PreToolUse that
        # haven't been promoted to disk state yet
        _enforcer_pending = read_enforcer_sideband(session_id)
        if _enforcer_pending is not None:
            for _k, _v in _enforcer_pending.items():
                if _k.startswith("_") and _k != "_sideband_refreshed":
                    continue
                state[_k] = _v

        handle_post_tool_use(tool_name, tool_input, state, session_id=session_id, tool_response=tool_response)
    except Exception as e:
        # FAIL-OPEN: tracker crashes must never block work
        print(f"[TRACKER] Warning: Tracker error (non-blocking): {e}", file=sys.stderr)
    finally:
        sys.exit(0)
