"""Gate 8: TEMPORAL AWARENESS (Tier 3 — Domain-specific)

During high-risk hours (1 AM - 5 AM), requires an extra memory check
before allowing edits. Late-night sessions have historically higher
error rates.

Also warns about long sessions (>3 hours) where fatigue-equivalent
drift may occur.
"""

import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.gate_result import GateResult
from shared.state import get_memory_last_queried

GATE_NAME = "GATE 8: TEMPORAL AWARENESS"

# High-risk hours (24h format)
HIGH_RISK_START = 1   # 1 AM
HIGH_RISK_END = 5     # 5 AM

# Long session warning threshold (seconds)
LONG_SESSION_THRESHOLD = 10800  # 3 hours

# Files exempt by basename
EXEMPT_BASENAMES = {"state.json", "HANDOFF.md", "LIVE_STATE.json", "CLAUDE.md"}

# Directories exempt by normalized path prefix
EXEMPT_DIRS = [
    os.path.join(os.path.expanduser("~"), ".claude", "skills"),
]


def is_exempt(file_path):
    if os.path.basename(file_path) in EXEMPT_BASENAMES:
        return True
    norm = os.path.normpath(file_path)
    for d in EXEMPT_DIRS:
        nd = os.path.normpath(d)
        if norm.startswith(nd + os.sep) or norm == nd:
            return True
    return False


def check(tool_name, tool_input, state, event_type="PreToolUse"):
    if event_type != "PreToolUse":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if tool_name not in ("Edit", "Write", "NotebookEdit"):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Check file exemptions
    file_path = tool_input.get("file_path", "") or tool_input.get("notebook_path", "")
    if is_exempt(file_path):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    now = datetime.now()
    hour = now.hour

    # Late night check: require very recent memory query
    if HIGH_RISK_START <= hour < HIGH_RISK_END:
        last_query = get_memory_last_queried(state)
        elapsed = time.time() - last_query

        # During high-risk hours, memory must be queried within 2 minutes
        if elapsed > 120:
            return GateResult(
                blocked=True,
                message=f"[{GATE_NAME}] BLOCKED: Late night session ({hour:02d}:{now.minute:02d}). "
                        f"Extra caution required — query memory before editing. "
                        f"Use search_knowledge() to verify your approach.",
                gate_name=GATE_NAME,
                severity="warn",
            )

    # Graduated session milestone warnings (advisory, not blocking)
    session_start = state.get("session_start", time.time())
    session_duration = time.time() - session_start
    session_hours = session_duration / 3600

    if session_hours >= 3:
        print(
            f"[{GATE_NAME}] ADVISORY: Session running {int(session_hours)}h+. "
            f"Save progress with /wrap-up before context degrades.",
            file=sys.stderr,
        )
    elif session_hours >= 2:
        print(
            f"[{GATE_NAME}] ADVISORY: Session running 2h+. "
            f"Consider saving key findings to memory.",
            file=sys.stderr,
        )
    elif session_hours >= 1:
        print(
            f"[{GATE_NAME}] ADVISORY: Session running 1h+. "
            f"Good time for a memory checkpoint.",
            file=sys.stderr,
        )

    return GateResult(blocked=False, gate_name=GATE_NAME)
