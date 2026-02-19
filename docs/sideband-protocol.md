# Sideband Timestamp Protocol

Gate 4 blocks edits if memory hasn't been queried recently. But MCP tool calls
(like search_knowledge) happen outside the hook system — hooks can't see them.
This file bridges the gap.

- File: `hooks/.memory_last_queried` — JSON with `{"timestamp": epoch_float}`
- Written by boot.py (auto-injection) and read by gate_04 (memory-first check)
- Use atomic write (write to .tmp then os.replace) to prevent corruption
- This file bridges the gap between MCP tool calls and hook-level state
