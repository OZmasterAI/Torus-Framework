"""Tracker Mentor (Module A) — per-action PostToolUse evaluation.

Deterministic signal analysis only. No LLM calls.
Called from orchestrator.py with the mentor_tracker toggle.
"""
from dataclasses import dataclass
from typing import List, Optional

from tracker_pkg import _log_debug

# Test-related keywords for Bash command classification
_TEST_KEYWORDS = ["pytest", "test_framework", "npm test", "cargo test", "go test", "python -m pytest"]
_WEAK_VERIFY = ["ls", "echo", "pwd", "cat"]
_STRONG_VERIFY = ["pytest", "test_framework", "cargo test", "npm test"]


@dataclass
class Signal:
    name: str        # e.g., "test_exit_code", "empty_search", "edit_churn"
    value: float     # 0.0 (bad) to 1.0 (good)
    weight: float    # importance multiplier
    detail: str      # human-readable explanation


@dataclass
class MentorVerdict:
    action: str      # "proceed" | "advise" | "warn" | "escalate"
    score: float     # weighted signal average, 0.0-1.0
    signals: list    # List[Signal]
    message: str     # summary for stderr


# ---------------------------------------------------------------------------
# Individual evaluators
# ---------------------------------------------------------------------------

def _parse_exit_code(tool_response) -> Optional[int]:
    """Extract exit code from tool_response (dict or JSON string)."""
    import json
    if isinstance(tool_response, dict):
        ec = tool_response.get("exit_code",
             tool_response.get("exitCode",
             tool_response.get("status")))
        if ec is not None:
            try:
                return int(ec)
            except (TypeError, ValueError):
                return None
    elif isinstance(tool_response, str):
        try:
            resp = json.loads(tool_response)
            if isinstance(resp, dict):
                ec = resp.get("exit_code",
                     resp.get("exitCode",
                     resp.get("status")))
                if ec is not None:
                    return int(ec)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    return None


def _eval_bash(tool_name, tool_input, tool_response, state) -> List[Signal]:
    """Evaluate Bash tool calls for test results, error loops, verification quality."""
    if tool_name != "Bash":
        return []

    signals: List[Signal] = []
    command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
    exit_code = _parse_exit_code(tool_response)

    is_test = any(kw in command for kw in _TEST_KEYWORDS)

    # Test pass/fail signal
    if is_test and exit_code is not None:
        if exit_code == 0:
            signals.append(Signal("test_pass", 1.0, 2.0, "Tests passed"))
        else:
            signals.append(Signal("test_fail", 0.0, 2.0, f"Tests failed (exit {exit_code})"))

    # Error loop detection
    error_counts = state.get("error_pattern_counts", {}) if isinstance(state, dict) else {}
    for pattern, count in error_counts.items():
        if count >= 3:
            signals.append(Signal(
                "error_loop", 0.1, 1.5,
                f"Same error repeated {count}x: {pattern[:60]}"
            ))
            break  # Report worst only

    # Verification quality
    if any(kw in command for kw in _WEAK_VERIFY):
        signals.append(Signal("verification_quality", 0.1, 0.5, "Weak verification (ls/echo)"))
    elif any(kw in command for kw in _STRONG_VERIFY):
        signals.append(Signal("verification_quality", 1.0, 0.5, "Strong verification (test suite)"))
    else:
        signals.append(Signal("verification_quality", 0.5, 0.3, "Moderate verification"))

    return signals


def _eval_edit(tool_name, tool_input, tool_response, state) -> List[Signal]:
    """Evaluate edit/write calls for churn, reverts, and large changes."""
    if tool_name not in ("Edit", "Write", "NotebookEdit"):
        return []

    signals: List[Signal] = []
    file_path = ""
    if isinstance(tool_input, dict):
        file_path = tool_input.get("file_path", "") or tool_input.get("notebook_path", "")
    edit_streak = state.get("edit_streak", {}) if isinstance(state, dict) else {}

    # Edit churn: same file edited many times without a passing test
    if file_path:
        streak = edit_streak.get(file_path, 0)
        if streak >= 5:
            signals.append(Signal(
                "edit_churn", 0.2, 1.5,
                f"File edited {streak}x without passing test"
            ))

    # Revert and large-edit detection (Edit only)
    if tool_name == "Edit" and isinstance(tool_input, dict):
        old_string = tool_input.get("old_string", "") or ""
        new_string = tool_input.get("new_string", "") or ""
        if old_string and new_string:
            if len(new_string) < len(old_string) * 0.3:
                signals.append(Signal(
                    "possible_revert", 0.3, 1.0,
                    "Edit removed >70% of content — possible revert"
                ))
        if old_string and len(old_string) > 500:
            signals.append(Signal(
                "large_edit", 0.6, 0.3,
                f"Large edit ({len(old_string)} chars replaced)"
            ))

    return signals


def _eval_search(tool_name, tool_input, tool_response, state) -> List[Signal]:
    """Evaluate Grep/Glob/Read for empty results and search loops."""
    if tool_name not in ("Grep", "Glob", "Read"):
        return []

    signals: List[Signal] = []

    # Empty results detection
    empty = False
    if tool_response is None:
        empty = True
    elif isinstance(tool_response, str):
        stripped = tool_response.strip()
        empty = (
            stripped == ""
            or "0 matches" in stripped
            or stripped.startswith("Error:")
            or stripped.startswith("error:")
        )
    elif isinstance(tool_response, list):
        empty = len(tool_response) == 0
    elif isinstance(tool_response, dict):
        # Check for error keys or empty content
        if tool_response.get("error"):
            empty = True

    if empty:
        signals.append(Signal("empty_search", 0.4, 0.8, f"No results for {tool_name}"))

    # Search-stuck: count recent empty signals from state
    recent_signals = state.get("mentor_signals", []) if isinstance(state, dict) else []
    if empty and isinstance(recent_signals, list):
        consecutive_empties = 0
        for sig in reversed(recent_signals):
            if isinstance(sig, dict) and sig.get("name") == "empty_search":
                consecutive_empties += 1
            else:
                break
        if consecutive_empties >= 2:  # Prior 2 + this one = 3
            signals.append(Signal(
                "search_stuck", 0.1, 1.2,
                f"3+ empty search results in a row"
            ))

    return signals


def _eval_progress(tool_name, tool_input, tool_response, state) -> List[Signal]:
    """Every 10th tool call: run behavioral anomaly check."""
    tool_call_count = state.get("tool_call_count", 0) if isinstance(state, dict) else 0
    if tool_call_count % 10 != 0:
        return []

    signals: List[Signal] = []
    try:
        from shared.anomaly_detector import detect_behavioral_anomaly
        anomalies = detect_behavioral_anomaly(state)
        for anomaly_type, _severity, description in anomalies:
            signals.append(Signal(anomaly_type, 0.2, 1.0, description))
    except Exception as e:
        _log_debug(f"mentor _eval_progress anomaly check failed: {e}")

    return signals


# ---------------------------------------------------------------------------
# Verdict computation
# ---------------------------------------------------------------------------

def _compute_verdict(signals: List[Signal]) -> MentorVerdict:
    """Compute weighted verdict from signal list."""
    if not signals:
        return MentorVerdict("proceed", 1.0, [], "No signals")

    total_weight = sum(s.weight for s in signals)
    if total_weight == 0:
        return MentorVerdict("proceed", 1.0, signals, "No weighted signals")

    score = sum(s.value * s.weight for s in signals) / total_weight

    if score >= 0.7:
        action = "proceed"
    elif score >= 0.5:
        action = "advise"
    elif score >= 0.3:
        action = "warn"
    else:
        action = "escalate"

    issues = [s for s in signals if s.value < 0.7]
    if issues:
        parts = [f"{s.name}={s.value:.1f}" for s in issues[:3]]
        message = f"Mentor ({action}, score={score:.2f}): {', '.join(parts)}"
    else:
        message = ""

    return MentorVerdict(action, score, signals, message)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def evaluate(tool_name, tool_input, tool_response, state):
    """Evaluate a completed tool call and return a MentorVerdict.

    Called from orchestrator.py during PostToolUse handling.
    Updates state["mentor_*"] fields.
    Returns MentorVerdict or None on error (fail-open).
    """
    try:
        signals: List[Signal] = []
        signals.extend(_eval_bash(tool_name, tool_input, tool_response, state))
        signals.extend(_eval_edit(tool_name, tool_input, tool_response, state))
        signals.extend(_eval_search(tool_name, tool_input, tool_response, state))
        signals.extend(_eval_progress(tool_name, tool_input, tool_response, state))

        verdict = _compute_verdict(signals)

        # Update state
        if isinstance(state, dict):
            state["mentor_last_verdict"] = verdict.action
            state["mentor_last_score"] = verdict.score
            state["mentor_signals"] = [
                {"name": s.name, "value": s.value, "weight": s.weight, "detail": s.detail}
                for s in verdict.signals
            ]
            if verdict.action == "escalate":
                state["mentor_escalation_count"] = state.get("mentor_escalation_count", 0) + 1
            elif verdict.action in ("proceed", "advise"):
                state["mentor_escalation_count"] = 0

        _log_debug(f"mentor.evaluate: tool={tool_name} action={verdict.action} score={verdict.score:.2f} signals={len(signals)}")
        return verdict

    except Exception as e:
        _log_debug(f"mentor.evaluate failed (non-blocking): {e}")
        return None
