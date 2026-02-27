#!/usr/bin/env python3
"""SessionStart hook — thin shim, delegates to boot_pkg/.

All imports are re-exported so that existing consumers (test_framework.py)
continue to work with `from boot import X` and `patch("boot.X")`.
"""
import os
import sys

# Ensure hooks dir is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from shared.chromadb_socket import (  # noqa: E402, F401
    count as socket_count,
    query as socket_query,
)
from boot_pkg.memory import (  # noqa: E402, F401
    inject_memories_via_socket as _inject_impl,
    _write_sideband_timestamp,
    SIDEBAND_FILE,
)
from boot_pkg.context import (  # noqa: E402, F401
    _extract_test_status,
    _extract_verification_quality,
    _extract_session_duration,
    _extract_gate_blocks,
)
from boot_pkg.orchestrator import main as _main  # noqa: E402, F401


def inject_memories_via_socket(handoff_content, live_state):
    """Wrapper that passes shim-level socket_count/socket_query for test patching.

    Tests use patch("boot.socket_count") which replaces the name in this module.
    This wrapper reads from this module's globals (patchable) and passes them
    to the real implementation.
    """
    return _inject_impl(handoff_content, live_state, _socket_count=socket_count, _socket_query=socket_query)


if __name__ == "__main__":
    _main()
