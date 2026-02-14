---
globs: .claude/hooks/**, .claude/hooks/gates/**
---

# Hook & Gate Development Rules

## Gate Contract
- Every gate module MUST export a `check(tool_name, tool_input, state, event_type="PreToolUse")` function
- Return type: `GateResult(blocked=bool, message=str, gate_name=str, severity=str)`
- severity values: "info", "warn", "error"
- Use `from shared.gate_result import GateResult` — never construct dicts

## Exit Codes
- `sys.exit(1)` = block the tool call (only valid for PreToolUse)
- `sys.exit(0)` = allow (or for PostToolUse/other events, always exit 0)
- NEVER use `sys.exit(2)` — Claude Code interprets exit 2 as "block and show custom message"

## Fail-Closed vs Fail-Open
- Tier 1 safety gates (gates 1-3): fail-CLOSED — exceptions block the tool call
- Tier 2+ quality gates: fail-OPEN — exceptions log a warning and continue
- Gate tier is set in `enforcer.py:TIER1_SAFETY_GATES`

## State Rules
- Import state via `from shared.state import load_state, save_state`
- Never add new fields to state without updating `shared/state.py:default_state()`
- State is per-agent (keyed by session_id) — team members don't share state
- Always handle missing keys with `.get(key, default)` for backward compatibility

## Testing
- All gates must have tests in `hooks/test_framework.py`
- Test both the blocking and allowing paths
- Test with edge cases: empty tool_input, missing state keys, stale timestamps
