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
- Import state via `from shared.state import load_state, save_state`
- State is per-agent (keyed by session_id) — team members don't share state
- When adding new state fields, add them to `default_state()` with sensible defaults
- Existing state files missing new fields get defaults via `.get(key, default)` pattern
- Never rename or remove existing state fields without a migration path

## Hook Registration Protocol
- Hooks are registered in `.claude/settings.json` under the `hooks` key
- Each hook maps an event type (PreToolUse, PostToolUse, SessionStart, etc.) to a command
- The command receives JSON on stdin and must exit with appropriate code
- Hook timeout: 5 seconds (default) — gates must complete within this window

## CLAUDE.md Token Budget
- Keep CLAUDE.md under 2,000 tokens — every line is injected into every prompt
