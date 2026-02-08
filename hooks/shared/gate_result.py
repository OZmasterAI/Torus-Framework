"""Gate result object returned by every gate check."""


class GateResult:
    def __init__(self, blocked=False, message="", gate_name=""):
        self.blocked = blocked
        self.message = message
        self.gate_name = gate_name

    def __repr__(self):
        status = "BLOCKED" if self.blocked else "PASS"
        return f"GateResult({status}, {self.gate_name})"
