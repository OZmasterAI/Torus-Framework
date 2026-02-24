# Framework Domain — Behavioral Overlay

You are working within the **Torus framework** domain. These rules supplement all existing instructions.

## Framework Awareness
- Every hook file runs in a subprocess with 5s timeout — keep operations fast
- Gates return GateResult from shared.gate_result — never construct raw dicts
- State is per-session (keyed by session_id) — team agents don't share state
- Shared modules in hooks/shared/ must be backward-compatible
- Boot pipeline (boot_pkg/) runs on SessionStart — failures must never crash boot

## Edit Discipline for Framework Files
- enforcer.py, memory_server.py, state.py are critical — extra caution
- Test changes against test_framework.py before claiming "fixed"
- Gate changes must preserve the exit code contract: 0=allow, 2=block, 1=error
- Never break the enforcer while the enforcer is running (deadlock risk)

## Memory System
- ChromaDB collections: "knowledge" (curated), "observations" (auto-captured)
- UDS socket to memory_server.py for fast operations — subprocess fallback exists
- Always use get_or_create_collection(), never create_collection()
