#!/usr/bin/env python3
"""PostToolUse hook — thin shim, delegates to tracker_pkg/.

All imports are re-exported so that existing consumers (test_framework.py,
tests/test_edit_streak.py, etc.) continue to work with `from tracker import X`.
"""
import os
import sys

# Ensure hooks dir is on sys.path
sys.path.insert(0, os.path.dirname(__file__))

from tracker_pkg.orchestrator import (  # noqa: E402, F401
    handle_post_tool_use,
    main as _main,
    is_memory_tool,
    MEMORY_TOOL_PREFIXES,
    _TOKEN_ESTIMATES,
)
from tracker_pkg import _log_debug, TRACKER_DEBUG_LOG  # noqa: E402, F401
from tracker_pkg.observations import (  # noqa: E402, F401
    _observation_key,
    _is_recent_duplicate,
    _capture_observation,
)
from tracker_pkg.auto_remember import (  # noqa: E402, F401
    _auto_remember_event,
    _cap_queue_file,
    AUTO_REMEMBER_QUEUE,
    MAX_AUTO_REMEMBER_PER_SESSION,
    CAPTURABLE_TOOLS,
    CAPTURE_QUEUE,
    MAX_QUEUE_LINES,
)
from tracker_pkg.verification import (  # noqa: E402, F401
    _resolve_gate_block_outcomes,
    _classify_verification_score,
    BROAD_TEST_COMMANDS,
)
from tracker_pkg.errors import (  # noqa: E402, F401
    _extract_error_pattern,
    _deduplicate_error_window,
    _detect_errors,
)

if __name__ == "__main__":
    _main()
