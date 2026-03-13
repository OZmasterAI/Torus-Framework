"""Operation tracker for hybrid working memory.

Tracks tool calls, groups them into operations, and detects operation boundaries
using a weighted multi-signal heuristic inspired by Sapling's operation model.

Boundary detection signals (weighted):
  tool_phase_transition : 0.35 — Read/Grep/Glob -> write -> verify -> delegate
  file_scope_change     : 0.30 — Jaccard similarity of file sets < 0.2
  intent_signal         : 0.20 — regex on assistant text ("I'll", "Now", etc.)
  temporal_gap          : 0.15 — >30s between calls

State persisted to ramdisk: /run/user/{uid}/claude-hooks/state/operations_{session_id}.json
Atomic writes: tmp + os.replace()
File locking: fcntl.flock (matches hooks/shared/state.py pattern)
"""

import fcntl
import json
import logging
import os
import re
import time

logger = logging.getLogger(__name__)

# ── Boundary detection weights ────────────────────────────────────────────────

BOUNDARY_WEIGHTS = {
    "tool_phase_transition": 0.35,
    "file_scope_change": 0.30,
    "intent_signal": 0.20,
    "temporal_gap": 0.15,
}
BOUNDARY_THRESHOLD = 0.5

# Temporal gap threshold in seconds
TEMPORAL_GAP_SECONDS = 30

# ── Tool phase classification ─────────────────────────────────────────────────

_TOOL_PHASE = {
    "Read": "read",
    "Grep": "read",
    "Glob": "read",
    "Edit": "write",
    "Write": "write",
    "NotebookEdit": "write",
    "Bash": "verify",
    "Agent": "delegate",
    "Task": "delegate",
}


def _classify_phase(tool_name: str) -> str:
    """Classify a tool name into a phase string."""
    return _TOOL_PHASE.get(tool_name, "read")


# ── Intent signal regex ───────────────────────────────────────────────────────

_INTENT_RE = re.compile(
    r"(?:I'll|Let me|Now\b|Next\b|Moving on to|moving on to)",
    re.IGNORECASE,
)

# ── Path resolution ───────────────────────────────────────────────────────────

try:
    from shared.ramdisk import get_state_dir, is_ramdisk_available

    _STATE_DIR = get_state_dir()
except ImportError:
    _STATE_DIR = os.path.join(os.path.expanduser("~"), ".claude", "hooks")


def _op_state_file(session_id: str) -> str:
    """Return path to the operations state file for a session."""
    return os.path.join(_STATE_DIR, f"operations_{session_id}.json")


# ── Default state factory ─────────────────────────────────────────────────────


def _default_state() -> dict:
    return {
        "current_op_id": 1,
        "current_op_type": None,
        "current_op_files": [],
        "current_op_tools": [],
        "current_op_purpose": "",
        "current_op_start_turn": 1,
        "current_op_has_error": False,
        "current_op_has_bash": False,
        "last_turn_timestamp": 0.0,
        "last_tool_phase": None,
        "total_turns": 0,
        "total_ops": 0,
        "expand_written": False,
        "unresolved_errors": [],
        "completed_ops": [],
        "summary_threshold_fired": False,
        "summary_clear_countdown": -1,
    }


# ── File I/O helpers ──────────────────────────────────────────────────────────


def _load_state(state_file: str) -> dict:
    """Load operations state from disk/ramdisk. Returns default on any error."""
    lock_path = state_file + ".lock"
    try:
        os.makedirs(os.path.dirname(state_file), exist_ok=True)
        if not os.path.exists(state_file):
            return _default_state()
        with open(lock_path, "a+") as lock_fd:
            try:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_SH)
                with open(state_file) as f:
                    data = json.load(f)
                # Forward-compat: fill any missing keys
                default = _default_state()
                for k, v in default.items():
                    if k not in data:
                        data[k] = v
                return data
            except (json.JSONDecodeError, IOError):
                return _default_state()
            finally:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
    except OSError:
        # Fallback: unlocked read
        try:
            with open(state_file) as f:
                return json.load(f)
        except Exception:
            return _default_state()


def _save_state_to_file(state: dict, state_file: str) -> None:
    """Atomic write with flock — same pattern as state.py save_state()."""
    lock_path = state_file + ".lock"
    try:
        os.makedirs(os.path.dirname(state_file), exist_ok=True)
        with open(lock_path, "a+") as lock_fd:
            try:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
                tmp = state_file + f".tmp.{os.getpid()}"
                with open(tmp, "w") as f:
                    json.dump(state, f, indent=2)
                os.replace(tmp, state_file)
            finally:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
    except Exception as e:
        logger.warning(f"operation_tracker: save_state failed: {e}")


# ── File set helpers ──────────────────────────────────────────────────────────


def _extract_files(tool_input: dict) -> list:
    """Extract file paths from a tool input dict."""
    files = []
    for key in ("file_path", "notebook_path", "path"):
        val = tool_input.get(key)
        if val and isinstance(val, str):
            files.append(val)
    return files


def _jaccard(set_a: set, set_b: set) -> float:
    """Jaccard similarity between two sets. Returns 1.0 if both empty."""
    if not set_a and not set_b:
        return 1.0
    union = set_a | set_b
    if not union:
        return 1.0
    return len(set_a & set_b) / len(union)


# ── Purpose extraction ────────────────────────────────────────────────────────


def _extract_purpose(assistant_text: str, op_type: str, files: list) -> str:
    """Extract purpose from assistant text using regex cascade, with fallback."""
    if assistant_text:
        # Try to find the phrase after the intent keyword
        m = re.search(
            r"(?:I'll|Let me|Now\b|Next\b|Moving on to|moving on to)\s+(.{5,80}?)(?:[.!?\n]|$)",
            assistant_text,
            re.IGNORECASE,
        )
        if m:
            return m.group(1).strip()[:100]
        # Try any meaningful sentence
        sentences = re.split(r"[.!?\n]", assistant_text)
        for s in sentences:
            s = s.strip()
            if 10 <= len(s) <= 120:
                return s[:100]
    # Fallback: "{type} on {files}"
    if files:
        names = [os.path.basename(f) for f in files[:2]]
        return f"{op_type} on {', '.join(names)}"
    return f"{op_type} operation"


# ── Outcome inference ─────────────────────────────────────────────────────────


def _infer_outcome(state: dict) -> str:
    """Infer operation outcome from accumulated tool call state."""
    if state.get("current_op_has_error"):
        return "failure"
    tools = state.get("current_op_tools", [])
    has_write = any(_classify_phase(t) == "write" for t in tools)
    has_bash = state.get("current_op_has_bash", False)
    is_read_only = not has_write and not has_bash

    if is_read_only:
        return "success"
    if has_write and has_bash:
        return "success"
    if has_write and not has_bash:
        return "partial"
    return "success"


# ── OperationTracker ──────────────────────────────────────────────────────────


class OperationTracker:
    """Tracks tool calls, groups into operations, detects boundaries.

    State is persisted to ramdisk on every process_tool_call() call.
    Each Claude Code session has its own state file keyed by session_id.
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._state_file = _op_state_file(session_id)
        self._state = _load_state(self._state_file)

    # ── Public API ────────────────────────────────────────────────────────────

    def process_tool_call(
        self,
        tool_name: str,
        tool_input: dict,
        assistant_text: str = "",
        had_error: bool = False,
    ) -> dict:
        """Process a single tool call, update state, detect boundaries.

        Returns a dict with:
          boundary_detected: bool
          boundary_score: float
          completed_op: dict | None  (the op that was just completed, if any)
        """
        try:
            return self._process(tool_name, tool_input, assistant_text, had_error)
        except Exception as e:
            logger.warning(f"operation_tracker.process_tool_call error: {e}")
            return {
                "boundary_detected": False,
                "boundary_score": 0.0,
                "completed_op": None,
            }

    def get_state(self) -> dict:
        """Return a copy of the current tracker state."""
        return dict(self._state)

    def get_active_op(self) -> dict | None:
        """Return the current active operation as a dict, or None if no calls yet."""
        if self._state.get("current_op_type") is None:
            return None
        return {
            "id": self._state["current_op_id"],
            "type": self._state["current_op_type"],
            "files": list(self._state.get("current_op_files", [])),
            "tools": list(self._state.get("current_op_tools", [])),
            "purpose": self._state.get("current_op_purpose", ""),
            "start_turn": self._state.get("current_op_start_turn", 1),
        }

    def get_completed_ops(self) -> list:
        """Return list of completed operation dicts."""
        return list(self._state.get("completed_ops", []))

    def _save_state(self, state: dict) -> None:
        """Save state to disk/ramdisk (public for test access)."""
        self._state = state
        _save_state_to_file(state, self._state_file)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _process(
        self,
        tool_name: str,
        tool_input: dict,
        assistant_text: str,
        had_error: bool,
    ) -> dict:
        state = self._state
        now = time.time()

        # Increment turn counter
        state["total_turns"] = state.get("total_turns", 0) + 1

        # Classify current tool phase
        current_phase = _classify_phase(tool_name)

        # Extract files involved in this call
        new_files = _extract_files(tool_input)

        # ── Boundary scoring ──────────────────────────────────────────────────

        boundary_score = 0.0
        last_phase = state.get("last_tool_phase")

        # Signal 1: tool_phase_transition (0.35)
        # Fires on any phase change (read->write, write->verify, etc.)
        if last_phase is not None and last_phase != current_phase:
            boundary_score += BOUNDARY_WEIGHTS["tool_phase_transition"]

        # Signal 2: file_scope_change (0.30)
        # Fires when Jaccard similarity of current op files vs new file set < 0.2
        current_files = set(state.get("current_op_files", []))
        new_file_set = set(new_files)
        if current_files and new_file_set:
            similarity = _jaccard(current_files, new_file_set)
            if similarity < 0.2:
                boundary_score += BOUNDARY_WEIGHTS["file_scope_change"]

        # Signal 3: intent_signal (0.20)
        # Fires on pattern match in assistant text
        if assistant_text and _INTENT_RE.search(assistant_text):
            boundary_score += BOUNDARY_WEIGHTS["intent_signal"]

        # Signal 4: temporal_gap (0.15)
        # Fires if >30s since last call and there is an active op
        last_ts = state.get("last_turn_timestamp", 0.0)
        if (
            last_ts > 0
            and (now - last_ts) > TEMPORAL_GAP_SECONDS
            and state.get("current_op_type") is not None
        ):
            boundary_score += BOUNDARY_WEIGHTS["temporal_gap"]

        boundary_detected = boundary_score >= BOUNDARY_THRESHOLD
        completed_op = None

        # ── Complete current op if boundary detected ───────────────────────────

        if boundary_detected and state.get("current_op_type") is not None:
            completed_op = self._complete_current_op(state, had_error=False)

        # ── Start or continue active op ────────────────────────────────────────

        if state.get("current_op_type") is None or boundary_detected:
            # Start new op
            # Note: current_op_id already incremented by _complete_current_op()
            # when boundary fires; for first-ever op it stays at 1 from default
            state["current_op_type"] = current_phase
            state["current_op_files"] = list(new_files)
            state["current_op_tools"] = [tool_name]
            state["current_op_purpose"] = _extract_purpose(
                assistant_text, current_phase, new_files
            )
            state["current_op_start_turn"] = state["total_turns"]
            state["current_op_has_error"] = had_error
            state["current_op_has_bash"] = tool_name == "Bash"
        else:
            # Continue current op
            # Update type to reflect dominant recent phase (allow upgrades: read->write->verify)
            phase_priority = {"read": 0, "write": 1, "verify": 2, "delegate": 3}
            curr_priority = phase_priority.get(state.get("current_op_type", "read"), 0)
            new_priority = phase_priority.get(current_phase, 0)
            if new_priority > curr_priority:
                state["current_op_type"] = current_phase

            # Add new files
            existing = state.get("current_op_files", [])
            for f in new_files:
                if f not in existing:
                    existing.append(f)
            state["current_op_files"] = existing

            # Add tool to tools list
            tools = state.get("current_op_tools", [])
            tools.append(tool_name)
            state["current_op_tools"] = tools

            # Track error and bash
            if had_error:
                state["current_op_has_error"] = True
            if tool_name == "Bash":
                state["current_op_has_bash"] = True

            # Update purpose if we have a better one from assistant text
            if assistant_text and not state.get("current_op_purpose"):
                state["current_op_purpose"] = _extract_purpose(
                    assistant_text, state["current_op_type"], state["current_op_files"]
                )

        # Update tracking fields
        state["last_tool_phase"] = current_phase
        state["last_turn_timestamp"] = now

        # Persist
        _save_state_to_file(state, self._state_file)

        return {
            "boundary_detected": boundary_detected,
            "boundary_score": round(boundary_score, 4),
            "completed_op": completed_op,
        }

    def _complete_current_op(self, state: dict, had_error: bool = False) -> dict:
        """Finalize the current operation, append to completed_ops, reset current."""
        if had_error:
            state["current_op_has_error"] = True

        outcome = _infer_outcome(state)

        op = {
            "id": state.get("current_op_id", 1),
            "type": state.get("current_op_type", "read"),
            "files": list(state.get("current_op_files", [])),
            "tools": list(state.get("current_op_tools", [])),
            "purpose": state.get("current_op_purpose", ""),
            "outcome": outcome,
            "start_turn": state.get("current_op_start_turn", 1),
            "end_turn": state.get("total_turns", 1),
        }

        # Track unresolved errors
        if outcome == "failure":
            state.setdefault("unresolved_errors", []).append(
                f"Op{op['id']}: {op['purpose'][:60]}"
            )

        completed = state.get("completed_ops", [])
        completed.append(op)
        state["completed_ops"] = completed
        state["total_ops"] = state.get("total_ops", 0) + 1

        # Advance op_id
        state["current_op_id"] = state.get("current_op_id", 1) + 1

        # Reset current op fields
        state["current_op_type"] = None
        state["current_op_files"] = []
        state["current_op_tools"] = []
        state["current_op_purpose"] = ""
        state["current_op_has_error"] = False
        state["current_op_has_bash"] = False

        return op
