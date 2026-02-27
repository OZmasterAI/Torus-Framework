"""Auto-remember queue and capture queue management."""
import json
import os
import time

from tracker_pkg import _log_debug

# Auto-remember imports (fail-open: if UDS unavailable, queue to disk)
try:
    from shared.chromadb_socket import remember as socket_remember, is_worker_available as _uds_available
except ImportError:
    socket_remember = None
    _uds_available = lambda: False

_HOOKS_DIR = os.path.dirname(os.path.dirname(__file__))

AUTO_REMEMBER_QUEUE = os.path.join(_HOOKS_DIR, ".auto_remember_queue.jsonl")
MAX_AUTO_REMEMBER_PER_SESSION = 10

# Auto-capture constants — expanded to include read/search/skill tools
CAPTURABLE_TOOLS = {"Bash", "Edit", "Write", "NotebookEdit", "Read", "Glob", "Grep", "Skill", "WebSearch", "WebFetch", "Task"}

try:
    from shared.ramdisk import get_capture_queue
    CAPTURE_QUEUE = get_capture_queue()
except ImportError:
    CAPTURE_QUEUE = os.path.join(_HOOKS_DIR, ".capture_queue.jsonl")

MAX_QUEUE_LINES = 500


def _auto_remember_event(content, context="", tags="", critical=False, state=None):
    """Queue or immediately save an auto-remember event.

    critical=True: attempt UDS save immediately (useful in current session).
    critical=False: append to .auto_remember_queue.jsonl for boot-time ingestion.
    Rate-limited to MAX_AUTO_REMEMBER_PER_SESSION per session.
    """
    try:
        if state is None:
            state = {}
        count = state.get("auto_remember_count", 0)
        if count >= MAX_AUTO_REMEMBER_PER_SESSION:
            return  # Rate limit hit
        state["auto_remember_count"] = count + 1

        if critical and socket_remember is not None:
            try:
                if _uds_available():
                    socket_remember(content, context, tags)
                    return
            except Exception:
                pass  # Fall through to queue

        # Queue for boot-time ingestion
        entry = json.dumps({
            "content": content, "context": context, "tags": tags,
            "timestamp": time.time(),
        })
        with open(AUTO_REMEMBER_QUEUE, "a") as f:
            f.write(entry + "\n")
    except Exception:
        pass  # Auto-remember is fail-open


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
