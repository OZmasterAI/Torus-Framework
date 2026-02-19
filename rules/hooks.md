---
globs: .claude/hooks/**, .claude/hooks/gates/**
---

# Hook & Gate Development Rules

## Gate Contract
- Every gate module MUST export a `check(tool_name, tool_input, state, event_type="PreToolUse")` function
- Return type: `GateResult(blocked=bool, message=str, gate_name=str, severity=str)`
- severity values: "info", "warn", "error", "critical"
- Use `from shared.gate_result import GateResult` — never construct dicts

## Exit Codes
- `sys.exit(0)` = allow (or for PostToolUse/other events, always exit 0)
- `sys.exit(2)` = block the tool call (only valid for PreToolUse); stderr is shown to Claude
- `sys.exit(1)` = non-blocking error (tool call PROCEEDS, error is logged)
- ALWAYS use `sys.exit(2)` for blocking — `sys.exit(1)` does NOT mechanically block

## Fail-Closed vs Fail-Open
- Tier 1 gates (1-3) fail-closed (exceptions block); all others fail-open. Set in `enforcer.py:TIER1_SAFETY_GATES`

## Gate 13: Workspace Isolation
- Main session always exempt from workspace isolation. See `docs/gate13-reference.md` for full exemption table.

## Testing
- All gates must have tests in `hooks/test_framework.py`
