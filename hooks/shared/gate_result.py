"""Gate result object returned by every gate check."""


class GateResult:
    def __init__(self, blocked=False, message="", gate_name="", severity="info", duration_ms=None, metadata=None):
        self.blocked = blocked
        self.message = message
        self.gate_name = gate_name
        self.severity = severity  # "info", "warn", "error", "critical"
        self.duration_ms = duration_ms
        self.metadata = metadata or {}

    def to_dict(self):
        """Returns all fields as a dictionary for structured logging."""
        return {
            "blocked": self.blocked,
            "message": self.message,
            "gate_name": self.gate_name,
            "severity": self.severity,
            "duration_ms": self.duration_ms,
            "metadata": self.metadata
        }

    @property
    def is_warning(self):
        """Returns True if this is an advisory warning (not blocking)."""
        return self.severity == "warn" and not self.blocked

    def __repr__(self):
        status = "BLOCKED" if self.blocked else "PASS"
        if self.severity != "info":
            return f"GateResult({status}, {self.gate_name}, severity={self.severity})"
        return f"GateResult({status}, {self.gate_name})"
