"""Context extraction from previous session state for boot dashboard."""
import glob
import json
import os
import time
from datetime import datetime

from boot_pkg.util import STATE_DIR


def _extract_recent_errors():
    """Extract top 5 error patterns from the most recent session state file.

    This is called BEFORE reset_enforcement_state() wipes all state files.
    Returns a list of strings like ["SyntaxError (3x)", "ImportError (2x)"].
    """
    try:
        pattern = os.path.join(STATE_DIR, "state_*.json")
        state_files = glob.glob(pattern)

        if not state_files:
            return []

        most_recent = max(state_files, key=os.path.getmtime)

        with open(most_recent) as f:
            state_data = json.load(f)

        error_counts = state_data.get("error_pattern_counts", {})
        if not error_counts:
            return []

        sorted_errors = sorted(error_counts.items(), key=lambda x: x[1], reverse=True)
        top_5 = sorted_errors[:5]

        return [f"{err_type} ({count}x)" for err_type, count in top_5]

    except Exception:
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

    Returns {"verified": N, "pending": M} or None if no data found.
    """
    try:
        pattern = os.path.join(STATE_DIR, "state_*.json")
        state_files = glob.glob(pattern)

        if not state_files:
            return None

        most_recent = max(state_files, key=os.path.getmtime)

        with open(most_recent) as f:
            state_data = json.load(f)

        verified_fixes = state_data.get("verified_fixes", [])
        pending_verification = state_data.get("pending_verification", [])

        if not verified_fixes and not pending_verification:
            return None

        return {"verified": len(verified_fixes), "pending": len(pending_verification)}

    except Exception:
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

    Returns (tool_call_count, tool_summary_string) or (0, None).
    """
    try:
        pattern = os.path.join(STATE_DIR, "state_*.json")
        state_files = glob.glob(pattern)

        if not state_files:
            return (0, None)

        most_recent = max(state_files, key=os.path.getmtime)

        with open(most_recent) as f:
            state_data = json.load(f)

        tool_stats = state_data.get("tool_stats", {})
        tool_call_count = state_data.get("tool_call_count", 0)

        if not tool_stats or tool_call_count == 0:
            return (0, None)

        sorted_tools = sorted(tool_stats.items(), key=lambda x: x[1].get("count", 0), reverse=True)[:3]
        tool_summary = ", ".join(f"{name}:{info.get('count', 0)}" for name, info in sorted_tools)

        return (tool_call_count, tool_summary)

    except Exception:
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
    """
    try:
        from shared.state import get_live_toggle, load_gate_effectiveness
        if not get_live_toggle("gate_auto_tune", False):
            return [], {}

        effectiveness = load_gate_effectiveness()
        if not effectiveness:
            return [], {}

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
        try:
            from shared.audit_log import AUDIT_DIR
            audit_dir = AUDIT_DIR
        except ImportError:
            audit_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "audit")
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
