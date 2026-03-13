# Working Memory (auto-generated — do not edit)
## Session eb269d3c-a4af-4d | Branch: layered-memory

## Status
Active: [Op86: read] read on LIVE_STATE.json | Files: LIVE_STATE.json
Last: [Op85: verify] read on gate_helpers.py [failure]

## Operations
- [Op63: write] write on report.py (report.py) [failure]
- [Op64: verify] read on circuit_breaker.py (circuit_breaker.py, search_cache.py) [failure]
- [Op65: verify] read on anomaly_detector.py (anomaly_detector.py) [failure]
- [Op66: verify] read on search_helpers.py (search_helpers.py, lance_collection.py) [failure]
- [Op67: verify] read on anomaly_detector.py (anomaly_detector.py) [failure]
- [Op68: verify] read on search_helpers.py (search_helpers.py, anomaly_detector.py) [failure]
- [Op69: verify] read on test_operation_tracker.py (test_operation_tracker.py, test_working_memory_writer.py) [failure]
- [Op70: verify] read on anomaly_detector.py (anomaly_detector.py, test_operation_tracker.py) [failure]
- [Op71: verify] read on search_helpers.py (search_helpers.py, test_working_memory_writer.py) [failure]
- [Op72: verify] read on lance_collection.py (lance_collection.py, anomaly_detector.py) [failure]
- [Op73: verify] read on gate_helpers.py (gate_helpers.py) [failure]
- [Op74: verify] write on lance_collection.py (lance_collection.py, gate_helpers.py) [failure]
- [Op75: verify] read on anomaly_detector.py (anomaly_detector.py, context.py) [failure]
- [Op76: verify] read on gate_helpers.py (gate_helpers.py, anomaly_detector.py) [failure]
- [Op77: verify] read on harness.py (harness.py) [failure]
- [Op78: verify] read on enforcer_shim.py (enforcer_shim.py) [failure]
- [Op79: verify] read on gate_01_read_before_edit.py (gate_01_read_before_edit.py) [failure]
- [Op80: verify] read on enforcer_shim.py (enforcer_shim.py) [failure]
- [Op81: verify] read on test_lance_collection.py (test_lance_collection.py) [failure]
- [Op82: verify] read on memory_maintenance.py (memory_maintenance.py) [failure]
- [Op83: verify] read on lance_collection.py (lance_collection.py) [failure]
- [Op84: verify] read on test_lance_collection.py (test_lance_collection.py, test_sprint_improvements.py) [failure]
- [Op85: verify] read on gate_helpers.py (gate_helpers.py) [failure]

## Context (expanded at threshold)
### Key Decisions
- (none captured)
### Causal Chain
- Op73 (read on gate_helpers.py) → Op74 (write on lance_collection.py)
- Op75 (read on anomaly_detector.py) → Op76 (read on gate_helpers.py)
### Unresolved
- Op83: read on lance_collection.py
- Op84: read on test_lance_collection.py
- Op85: read on gate_helpers.py
### Files Modified This Session
- /home/crab/.claude/hooks/shared/operation_tracker.py
- /home/crab/agents/sprint-gates/hooks/shared/gate_router.py
- /home/crab/agents/sprint-refactor/hooks/shared/gate_helpers.py
- /home/crab/agents/sprint-features/hooks/shared/feature_flags.py
- /home/crab/agents/sprint-tests/hooks/tests/test_working_memory_writer.py
- /home/crab/agents/sprint-features/skill-library/sprint-report/SKILL.md
- /home/crab/agents/sprint-memory/hooks/shared/operation_tracker.py
- /home/crab/agents/sprint-features/skill-library/sprint-report/scripts/report.py
