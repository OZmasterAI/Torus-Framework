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
- Validate non-empty, use `fnv1a_hash(content)` for IDs, metadata must be str/int/float/bool (no nested objects, 500 char cap)

## Sideband Timestamp Protocol
- Gate 4 sideband: boot.py writes `hooks/.memory_last_queried` (atomic write), gate_04 reads it to verify memory was queried. See `docs/sideband-protocol.md` for details.
