"""JSONL audit trail for the Self-Healing Claude Framework.

Logs every gate decision (pass, block, warn) to a daily JSONL file
under ~/.claude/hooks/audit/YYYY-MM-DD.jsonl. Designed to never raise
exceptions so it cannot interfere with gate enforcement.
"""

import json
import os
import time
from datetime import datetime, timezone


AUDIT_DIR = os.path.join(os.path.expanduser("~"), ".claude", "hooks", "audit")


def log_gate_decision(gate_name, tool_name, decision, reason, session_id=""):
    """Append a gate decision record to today's audit log.

    Args:
        gate_name: Name of the gate (e.g. "Gate 1: READ BEFORE EDIT").
        tool_name: The tool being checked (e.g. "Edit", "Bash").
        decision: One of "pass", "block", or "warn".
        reason: Human-readable explanation of the decision.
        session_id: Optional session identifier for correlation.
    """
    try:
        os.makedirs(AUDIT_DIR, exist_ok=True)

        now = datetime.now(timezone.utc)
        filename = now.strftime("%Y-%m-%d") + ".jsonl"
        filepath = os.path.join(AUDIT_DIR, filename)

        entry = {
            "timestamp": now.isoformat(),
            "gate": gate_name,
            "tool": tool_name,
            "decision": decision,
            "reason": reason,
            "session_id": session_id,
        }

        with open(filepath, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass
