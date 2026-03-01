---
globs: .claude/hooks/**, .claude/hooks/gates/**
---

# Hook & Gate Rules

## Gate Contract
- Export `check(tool_name, tool_input, state, event_type="PreToolUse")` → `GateResult`
- `from shared.gate_result import GateResult(blocked, message, gate_name, severity, duration_ms, metadata, escalation)` — never dicts
- severity: "info" | "warn" | "error" | "critical"
- escalation: "block" | "ask" | "warn" | "allow" (inferred from `blocked` if omitted)
- Properties: `is_ask` (escalation=="ask"), `is_warning` (severity=="warn" and not blocked)

## Exit Codes
- `0` = allow | `2` = block (PreToolUse only, stderr shown to Claude) | `1` = non-blocking error (proceeds)
- ALWAYS `sys.exit(2)` for blocking — `sys.exit(1)` does NOT block

## Tiers
- T1 (gates 1-3): fail-closed (exceptions block). All others: fail-open. Set in `enforcer.py:TIER1_SAFETY_GATES`

## Gate 13: Main session always exempt. See `docs/gate13-reference.md`

## Testing
- `hooks/test_framework.py` — main suite (all gates + shared modules)
- `hooks/tests/` — 11 focused test files (safety, quality, operational, integration, etc.)
- All gates must have coverage in at least one location
