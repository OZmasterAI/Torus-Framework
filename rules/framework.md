---
globs: .claude/CLAUDE.md, .claude/settings.json, .claude/hooks/shared/**, .claude/hooks/gates/**
---

# Framework Core Rules (v3.2.0)

## Gates (21 active, gate_08 dormant)
- 21 gate files in `hooks/gates/`. Enforced via `enforcer.py` → `enforcer_shim.py`
- **T1 fail-closed (gates 01-03):** exceptions block. Set in `enforcer.py:TIER1_SAFETY_GATES`
- **T2+ fail-open:** exceptions warn, execution continues
- Q-learning gate reordering (`gate_router.py`), 60s result cache, circuit breakers

## Shared Modules (~97 modules)
- Live in `hooks/shared/` — never duplicate in gates. Import: `from shared.X import Y`
- Core: `state.py`, `gate_result.py`, `audit_log.py`, `error_normalizer.py`, `observation.py`
- Infrastructure: `gate_router.py`, `gate_registry.py`, `circuit_breaker.py`, `ramdisk.py`, `memory_socket.py`
- Analysis: `metrics_collector.py`, `health_monitor.py`, `anomaly_detector.py`, `gate_correlator.py`
- Learning: `chain_sdk.py`, `chain_refinement.py`, `ltp_tracker.py`, `knowledge_graph.py`
- Backward-compatible — never remove public functions

## State (schema v3)
- `from shared.state import load_state, save_state` — per-agent keyed by session_id
- New fields: add to `default_state()`, access via `.get(key, default)`
- Never rename/remove fields without migration (v1→v2→v3 chain exists)
- Ramdisk fast path: `/run/user/{uid}/claude-hooks/` with async disk mirror
- Sideband: `enforcer_sideband_{session_id}.json` on ramdisk, promoted by `tracker.py`

## Hooks (14 event types, 18 entries)
- Registered in `settings.json` under `hooks` key, JSON on stdin, 5s timeout
- Exit codes: 0=allow, 2=block (PreToolUse only), 1=non-blocking error

## CLAUDE.md: keep under 2,000 tokens
