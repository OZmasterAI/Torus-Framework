---
globs: .claude/hooks/memory_server.py, **/mcp_server/**
---

# Memory MCP Rules

## Tools
- Registered via `@mcp.tool()` in memory_server.py — docstring becomes tool description
- Params must match JSON Schema types (str, int, float, bool)

## SurrealDB Storage (v3 standalone server, ws://127.0.0.1:8822)
- 6 tables: knowledge (curated), observations (auto-captured), fix_outcomes, quarantine, web_pages, clusters
- Embedding: nvidia/nv-embed-v1 (4096-dim), HNSW index, cosine distance
- Graph edges: RELATE (tried_for, resolved, failed_on, derived_from) for causal chains
- Data: ~/data/memory/surrealdb_v3/ | Systemd: surrealdb.service (user)

## Ingestion
- Validate non-empty, `fnv1a_hash(content)` for IDs, metadata: str/int/float/bool only (500 char cap)

## Sideband: Gate 4 reads `hooks/.memory_last_queried` (atomic write) to verify memory queried. See `docs/sideband-protocol.md`
