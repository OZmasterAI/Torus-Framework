---
globs: .claude/hooks/memory_server.py, **/mcp_server/**
---

# Memory MCP Server Rules

## MCP Tool Registration
- Tools are registered via `@mcp.tool()` decorator in memory_server.py
- Each tool function docstring becomes the tool description in Claude Code
- Parameter types must match JSON Schema expectations (str, int, float, bool)

## ChromaDB Collection Handling
- Two collections: "knowledge" (curated memories) and "observations" (auto-captured)
- Always use `get_or_create_collection()` — never `create_collection()`
- Collection metadata: `{"hnsw:space": "cosine"}` for semantic similarity
- ChromaDB can segfault under concurrent access — handle gracefully

## Ingestion Validation
- Validate content is non-empty before upserting
- IDs must be unique — use `fnv1a_hash(content)` for deterministic IDs
- Metadata values must be str, int, float, or bool — no nested objects
- Cap metadata string values at 500 chars to prevent ChromaDB errors

## Sideband Timestamp Protocol
- File: `hooks/.memory_last_queried` — JSON with `{"timestamp": epoch_float}`
- Written by boot.py (auto-injection) and read by gate_04 (memory-first check)
- Use atomic write (write to .tmp then os.replace) to prevent corruption
- This file bridges the gap between MCP tool calls and hook-level state
