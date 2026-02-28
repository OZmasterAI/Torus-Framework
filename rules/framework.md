---
globs: .claude/CLAUDE.md, .claude/settings.json, .claude/hooks/shared/**
---

# Framework Core Rules

## Shared Modules
- Live in `hooks/shared/` (~66 modules) — never duplicate in gates. Import: `from shared.X import Y`
- Core: `state.py`, `gate_result.py`, `audit_log.py`, `error_normalizer.py`, `observation.py`
- Infrastructure: `gate_router.py`, `gate_helpers.py`, `circuit_breaker.py`, `memory_socket.py`, `ramdisk.py`
- Analysis: `domain_registry.py`, `security_profiles.py`, `health_monitor.py`, `gate_timing.py`
- Backward-compatible — never remove public functions

## State
- `from shared.state import load_state, save_state` — per-agent keyed by session_id
- New fields: add to `default_state()`, access via `.get(key, default)`
- Never rename/remove fields without migration

## Hooks
- Registered in `settings.json` under `hooks` key, JSON on stdin, 5s timeout
- Exit codes: 0=allow, 2=block (PreToolUse only), 1=non-blocking error

## CLAUDE.md: keep under 2,000 tokens
