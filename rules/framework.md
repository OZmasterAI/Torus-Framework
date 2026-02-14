---
globs: .claude/CLAUDE.md, .claude/settings.json, .claude/hooks/shared/**
---

# Framework Core Rules

## Shared Module Rules
- All shared utilities live in `hooks/shared/` — never duplicate logic in individual gates
- Shared modules: `state.py`, `gate_result.py`, `audit_log.py`, `error_normalizer.py`, `observation.py`
- Import via: `from shared.module_name import function_name`
- Shared modules must be backward-compatible — never remove public functions

## State Schema Versioning
- State schema version is tracked in `shared/state.py`
- When adding new state fields, add them to `default_state()` with sensible defaults
- Existing state files missing new fields get defaults via `.get(key, default)` pattern
- Never rename or remove existing state fields without a migration path

## Hook Registration Protocol
- Hooks are registered in `.claude/settings.json` under the `hooks` key
- Each hook maps an event type (PreToolUse, PostToolUse, SessionStart, etc.) to a command
- The command receives JSON on stdin and must exit with appropriate code
- Hook timeout: 5 seconds (default) — gates must complete within this window

## CLAUDE.md Token Budget
- Current CLAUDE.md is ~1,321 tokens — keep it under 2,000 tokens
- Every line in CLAUDE.md is injected into EVERY prompt — high per-token cost
- Prefer rules/ files (path-scoped) over CLAUDE.md (always-injected) for domain-specific guidance
- Move domain-specific rules to SubagentStart hook injection when they only apply to sub-agents
