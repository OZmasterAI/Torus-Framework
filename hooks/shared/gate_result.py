"""Gate result object returned by every gate check.

Supports graduated escalation via the 'escalation' field:
- "block": Hard block, tool call is prevented (default when blocked=True)
- "ask": Show permission prompt to user for approval
- "warn": Advisory warning only, tool call proceeds
- "allow": Explicit allow (default when blocked=False)
"""


class GateResult:
    VALID_ESCALATIONS = ("block", "ask", "warn", "allow")

    def __init__(self, blocked=False, message="", gate_name="", severity="info",
                 duration_ms=None, metadata=None, escalation=None):
        self.blocked = blocked
        self.message = message
        self.gate_name = gate_name
        self.severity = severity  # "info", "warn", "error", "critical"
        self.duration_ms = duration_ms
        self.metadata = metadata or {}
        # Graduated escalation: infer from blocked if not explicit
        if escalation is not None:
            self.escalation = escalation if escalation in self.VALID_ESCALATIONS else "block"
        else:
            self.escalation = "block" if blocked else "allow"

    def to_dict(self):
        """Returns all fields as a dictionary for structured logging."""
        return {
            "blocked": self.blocked,
            "message": self.message,
            "gate_name": self.gate_name,
            "severity": self.severity,
            "duration_ms": self.duration_ms,
            "metadata": self.metadata,
            "escalation": self.escalation
        }

    def to_hook_decision(self):
        """Returns Claude Code hookSpecificOutput JSON for graduated decisions.

        Maps escalation levels to Claude Code's permissionDecision protocol:
        - "block" -> "deny"
        - "ask" -> "ask" (shows permission prompt to user)
        - "warn"/"allow" -> None (no hook output, tool proceeds)
        """
        if self.escalation == "block":
            return {"hookSpecificOutput": {"permissionDecision": "deny", "reason": self.message}}
        elif self.escalation == "ask":
            return {"hookSpecificOutput": {"permissionDecision": "ask"}}
        return None

    @property
    def is_warning(self):
        """Returns True if this is an advisory warning (not blocking)."""
        return self.severity == "warn" and not self.blocked

    @property
    def is_ask(self):
        """Returns True if this gate wants user confirmation."""
        return self.escalation == "ask"

    def __repr__(self):
        status = "BLOCKED" if self.blocked else "PASS"
        if self.escalation not in ("block", "allow"):
            return f"GateResult({status}, {self.gate_name}, escalation={self.escalation})"
        if self.severity != "info":
            return f"GateResult({status}, {self.gate_name}, severity={self.severity})"
        return f"GateResult({status}, {self.gate_name})"
