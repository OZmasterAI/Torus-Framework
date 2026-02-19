"""tracker_pkg — decomposed PostToolUse tracker."""
import os
import sys

# Ensure hooks dir is on sys.path for shared imports
_HOOKS_DIR = os.path.dirname(os.path.dirname(__file__))
if _HOOKS_DIR not in sys.path:
    sys.path.insert(0, _HOOKS_DIR)

# Shared debug logging used by multiple submodules
TRACKER_DEBUG_LOG = os.path.join(_HOOKS_DIR, ".tracker_debug.log")


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

        with open(TRACKER_DEBUG_LOG, "a") as f:
            f.write(log_line)

        with open(TRACKER_DEBUG_LOG, "r") as f:
            lines = f.readlines()

        if len(lines) > 1000:
            with open(TRACKER_DEBUG_LOG, "w") as f:
                f.writelines(lines[-1000:])
    except Exception:
        pass  # Debug logging must never crash tracker
