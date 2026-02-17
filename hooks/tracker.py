#!/usr/bin/env python3
"""Self-Healing Claude Framework — Tracker

Post-tool-use state tracker. Runs as a Claude Code hook on PostToolUse events.
Tracks what files were read, memory queries, test runs, edits, error detection,
causal fix chains, and auto-capture observations.

IMPORTANT: This script is FAIL-OPEN. Every code path is wrapped in try/except
and always exits 0. Tracking failures must never block work.

Usage (called by Claude Code hooks):
  echo '{"session_id":"abc","tool_name":"Edit","tool_input":{...}}' | python tracker.py
"""

import json
import os
import re
import sys
import time

# Add parent to path for shared imports
sys.path.insert(0, os.path.dirname(__file__))
from shared.state import load_state, save_state
from shared.error_normalizer import fnv1a_hash

# Auto-capture constants — expanded to include read/search/skill tools
CAPTURABLE_TOOLS = {"Bash", "Edit", "Write", "NotebookEdit", "Read", "Glob", "Grep", "Skill", "WebSearch", "WebFetch", "Task"}
try:
    from shared.ramdisk import get_capture_queue
    CAPTURE_QUEUE = get_capture_queue()
except ImportError:
    CAPTURE_QUEUE = os.path.join(os.path.dirname(__file__), ".capture_queue.jsonl")
MAX_QUEUE_LINES = 500

# Debug logging (opt-in: only writes if file exists)
TRACKER_DEBUG_LOG = os.path.join(os.path.dirname(__file__), ".tracker_debug.log")

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


def _log_debug(msg):
    """Append debug message to tracker log (opt-in: only if file exists).

    Never crashes. Caps file at 1000 lines (truncates from top).
    """
    try:
        if not os.path.exists(TRACKER_DEBUG_LOG):
            return  # Opt-in: only write if file exists

        from datetime import datetime
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] {msg}\n"

        # Append the message
        with open(TRACKER_DEBUG_LOG, "a") as f:
            f.write(log_line)

        # Cap at 1000 lines (truncate from top)
        with open(TRACKER_DEBUG_LOG, "r") as f:
            lines = f.readlines()

        if len(lines) > 1000:
            with open(TRACKER_DEBUG_LOG, "w") as f:
                f.writelines(lines[-1000:])
    except Exception:
        pass  # Debug logging must never crash tracker


def _extract_error_pattern(tool_response):
    """Extract the primary error pattern from test output.

    Looks for common error signatures in test output and returns the first match.
    Returns "unknown" if no pattern found.
    """
    if isinstance(tool_response, dict):
        output = tool_response.get("stdout", "") + tool_response.get("stderr", "")
    elif isinstance(tool_response, str):
        output = tool_response
    else:
        return "unknown"

    ERROR_SIGS = [
        "Traceback", "SyntaxError:", "ImportError:", "ModuleNotFoundError:",
        "TypeError:", "ValueError:", "KeyError:", "AttributeError:",
        "AssertionError:", "NameError:", "FAILED", "npm ERR!", "fatal:",
    ]
    for sig in ERROR_SIGS:
        if sig in output:
            return sig
    return "unknown"


def _deduplicate_error_window(state, pattern):
    """Windowed error deduplication: group same patterns within 60s windows.

    Tracks (pattern, first_seen, last_seen, count) tuples in state["error_windows"].
    If same error pattern appears within 60s, increments count instead of adding new entry.
    Caps at 50 unique patterns.
    """
    now = time.time()
    windows = state.setdefault("error_windows", [])

    # Check for existing window for this pattern
    for window in windows:
        if window["pattern"] == pattern and (now - window["last_seen"]) <= 60:
            window["last_seen"] = now
            window["count"] += 1
            return  # Deduplicated — no new entry needed

    # No recent window found — create new one (cap at 50)
    if len(windows) >= 50:
        # Remove oldest window
        windows.sort(key=lambda w: w["last_seen"])
        windows.pop(0)

    windows.append({
        "pattern": pattern,
        "first_seen": now,
        "last_seen": now,
        "count": 1,
    })


def _detect_errors(tool_input, tool_response, state):
    """Scan Bash output for error patterns, track in state."""
    ERROR_PATTERNS = [
        "Traceback", "SyntaxError:", "ImportError:", "ModuleNotFoundError:",
        "Permission denied", "npm ERR!", "fatal:", "error[E", "FAILED",
        "command not found", "No such file or directory",
        "ConnectionRefusedError", "OSError:",
    ]
    # Handle both string and dict tool_response defensively
    if isinstance(tool_response, dict):
        output = tool_response.get("stdout", "") + tool_response.get("stderr", "")
    else:
        output = str(tool_response)

    command = tool_input.get("command", "")
    for pattern in ERROR_PATTERNS:
        if pattern in output:
            entry = {"pattern": pattern, "command": command, "timestamp": time.time()}
            state.setdefault("unlogged_errors", []).append(entry)
            # Track pattern recurrence for repair loop detection
            counts = state.setdefault("error_pattern_counts", {})
            counts[pattern] = counts.get(pattern, 0) + 1
            # Windowed deduplication
            _deduplicate_error_window(state, pattern)
            break  # One entry per Bash tool call max


def _observation_key(tool_name, tool_input):
    """Generate a deduplication key for an observation based on tool and key inputs.

    Returns a string that represents the essential identity of this observation.
    """
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")[:200]
        return f"Bash:{cmd}"
    elif tool_name == "Read":
        fp = tool_input.get("file_path", "")
        return f"Read:{fp}"
    elif tool_name in ("Edit", "Write"):
        fp = tool_input.get("file_path", "")
        # Include content hash so different edits to the same file are not deduplicated
        if tool_name == "Edit":
            content_snippet = tool_input.get("old_string", "")[:100]
        else:
            content_snippet = tool_input.get("content", "")[:100]
        if content_snippet:
            content_hash = fnv1a_hash(content_snippet)
            return f"{tool_name}:{fp}:{content_hash}"
        return f"{tool_name}:{fp}"
    elif tool_name == "Glob":
        pattern = tool_input.get("pattern", "")
        return f"Glob:{pattern}"
    elif tool_name == "Grep":
        pattern = tool_input.get("pattern", "")
        path = tool_input.get("path", "")
        return f"Grep:{pattern}:{path}"
    elif tool_name == "WebSearch":
        query = tool_input.get("query", "")[:100]
        return f"WebSearch:{query}"
    elif tool_name == "WebFetch":
        url = tool_input.get("url", "")
        return f"WebFetch:{url}"
    else:
        return tool_name


def _is_recent_duplicate(obs_hash):
    """Check if an observation hash appears in the last 20 lines of the queue.

    Returns True if duplicate found, False otherwise.
    Fail-open: any exception returns False (allow capture).
    """
    try:
        if not os.path.exists(CAPTURE_QUEUE):
            return False

        with open(CAPTURE_QUEUE, "r") as f:
            lines = f.readlines()

        # Check last 20 lines
        for line in lines[-20:]:
            try:
                obs = json.loads(line)
                if obs.get("_obs_hash") == obs_hash:
                    return True
            except (json.JSONDecodeError, TypeError):
                continue

        return False
    except Exception:
        return False  # Fail-open: allow capture on any error


def _capture_observation(tool_name, tool_input, tool_response, session_id, state):
    """Append observation to queue file. Never raises — capture must not crash tracker."""
    try:
        if tool_name not in CAPTURABLE_TOOLS:
            return

        # Near-duplicate detection
        obs_hash = None
        try:
            obs_key = _observation_key(tool_name, tool_input)
            obs_hash = fnv1a_hash(obs_key)

            if _is_recent_duplicate(obs_hash):
                return  # Skip duplicate observation
        except Exception as e:
            _log_debug(f"dedup check failed (allowing capture): {e}")
            obs_hash = None  # Fail-open: continue with capture

        from shared.observation import compress_observation
        obs = compress_observation(tool_name, tool_input, tool_response, session_id, state=state)

        # Add dedup hash to observation if we computed it
        if obs_hash is not None:
            obs["_obs_hash"] = obs_hash

        with open(CAPTURE_QUEUE, "a") as f:
            f.write(json.dumps(obs) + "\n")
        # Cap check every 50 calls
        if state.get("tool_call_count", 0) % 50 == 0:
            _cap_queue_file()
    except Exception as e:
        _log_debug(f"capture_observation failed: {e}")


BROAD_TEST_COMMANDS = ["pytest", "python -m pytest", "npm test", "cargo test", "go test", "make test"]


def _classify_verification_score(command):
    """Classify a Bash command's verification confidence score.

    Returns an integer score:
      - Full test suite (pytest, npm test, make test, cargo test) = 100
      - Targeted test (pytest test_specific.py, jest file.test.js) = 70
      - Running a script (python script.py, node script.js) = 50
      - Generic commands (ls, git status, echo, cat) = 10
      - Other commands = 30
    """
    for kw in BROAD_TEST_COMMANDS:
        if kw in command:
            rest = command.split(kw, 1)[1].strip()
            # Specific test file or test selector
            if re.search(r'\btest_\w+\.py\b', rest) or '::' in rest:
                return 70  # Targeted test
            if re.search(r'\w+\.test\.(js|ts|tsx)\b', rest):
                return 70  # Jest-style targeted test
            return 100  # Full test suite

    script_runners = ["python ", "python3 ", "node ", "ruby ", "bash ", "sh ", "./"]
    if any(kw in command for kw in script_runners):
        return 50

    generic_cmds = ["ls", "git status", "echo ", "cat ", "pwd", "which "]
    if any(kw in command for kw in generic_cmds):
        return 10

    return 30


def _cap_queue_file():
    """Truncate queue with priority-aware retention if over 500 lines.

    High-priority observations (errors) survive compaction longer than
    low-priority ones (reads). Keeps all high-priority entries plus
    the most recent medium/low entries to fill up to 300 lines.
    """
    try:
        with open(CAPTURE_QUEUE, "r") as f:
            lines = f.readlines()
        if len(lines) <= MAX_QUEUE_LINES:
            return

        # Separate by priority
        high, rest = [], []
        for line in lines:
            try:
                obs = json.loads(line)
                meta = obs.get("metadata", {})
                if meta.get("priority") == "high":
                    high.append(line)
                else:
                    rest.append(line)
            except (json.JSONDecodeError, TypeError):
                rest.append(line)

        # Keep all high-priority (capped at 150), fill rest from recent
        high = high[-150:]
        remaining_budget = 300 - len(high)
        kept = high + rest[-max(remaining_budget, 50):]

        with open(CAPTURE_QUEUE + ".tmp", "w") as f:
            f.writelines(kept)
        os.replace(CAPTURE_QUEUE + ".tmp", CAPTURE_QUEUE)
    except Exception as e:
        _log_debug(f"cap_queue_file failed: {e}")


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
                claims_file = os.path.join(os.path.dirname(__file__), ".file_claims.json")
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
        if any(kw in command for kw in ["pytest", "python -m pytest", "npm test", "cargo test", "go test"]):
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
                state["recent_test_failure"] = None
                state["fixing_error"] = False

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
            edit_streak[file_path] = edit_streak.get(file_path, 0) + 1

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
            from shared.error_normalizer import error_signature, fnv1a_hash
            error_text = tool_input.get("error_text", "")
            strategy_id = tool_input.get("strategy_id", "")
            if error_text and strategy_id:
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

    _capture_observation(tool_name, tool_input, tool_response, session_id, state)

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

        handle_post_tool_use(tool_name, tool_input, state, session_id=session_id, tool_response=tool_response)
    except Exception as e:
        # FAIL-OPEN: tracker crashes must never block work
        print(f"[TRACKER] Warning: Tracker error (non-blocking): {e}", file=sys.stderr)
    finally:
        sys.exit(0)


if __name__ == "__main__":
    main()
