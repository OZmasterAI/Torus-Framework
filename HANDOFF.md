# Session 21 — Mode Parameter for search_knowledge

## What Was Done

### Feature: Expose `mode` parameter on `search_knowledge()`
- Added optional `mode` parameter: `"keyword"`, `"semantic"`, `"hybrid"`, `"tags"`, or `""` (auto-detect)
- Invalid mode values silently fall back to auto-detect (graceful degradation)
- Fully backward compatible — empty string default preserves existing behavior
- 5 new tests added (302 → 307, 0 failures)

### Memory: FTS5 persistence deferred
- Saved decision to memory (ID: `c78153e4ef918f97`)
- Revisit when memory count exceeds ~800-1000 entries (currently 194)

### Verification
| Check | Result |
|-------|--------|
| Tests | 307 passed, 0 failed |
| Backward compat | Empty mode = auto-detect, same as before |
| Invalid mode | Falls back to auto-detect silently |
| Forced keyword | Long questions routed to FTS5 when forced |
| Forced semantic | Single words routed to ChromaDB when forced |

## What's Next
1. **Restart MCP server** — Required for the new `mode` parameter to appear in live sessions
2. **Verify live** — Test `search_knowledge("ChromaDB", mode="semantic")` returns `mode: "semantic"` (not keyword)
3. **Consider**: FTS5 index persistence — revisit when memory count > 800 (currently 194)

## Service Status
- Memory MCP server: **needs restart** to load mode parameter
- Enforcer: active (unchanged)
- Boot: active (unchanged)
- Tests: 307 passing, 0 failures
- ChromaDB: ~/data/memory/ — 194 curated memories
- FTS5: in-memory, 194 indexed entries

## Key Files Changed (Session 21)
| File | Action |
|------|--------|
| `hooks/memory_server.py` | MODIFIED — added `mode` parameter to `search_knowledge()` |
| `hooks/test_framework.py` | MODIFIED — +5 new tests (302 → 307) |

## Key Memory IDs
- `c792edac3d61b4ea` — Mode parameter feature summary
- `c78153e4ef918f97` — FTS5 persistence deferred decision
