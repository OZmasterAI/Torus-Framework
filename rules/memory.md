---
globs: .claude/hooks/memory_server.py, **/mcp_server/**
---

# Memory MCP Rules

## Tools
- Registered via `@mcp.tool()` in memory_server.py — docstring becomes tool description
- Params must match JSON Schema types (str, int, float, bool)

## LanceDB Storage
- 5 tables: knowledge (curated), observations (auto-captured), fix_outcomes, quarantine, web_pages
- Embedding: nomic-embed-text-v2-moe (768-dim), cosine similarity, flat scan
- ChromaDB is backup only at ~/data/memory/chroma.sqlite3

## Ingestion
- Validate non-empty, `fnv1a_hash(content)` for IDs, metadata: str/int/float/bool only (500 char cap)

## Sideband: Gate 4 reads `hooks/.memory_last_queried` (atomic write) to verify memory queried. See `docs/sideband-protocol.md`
