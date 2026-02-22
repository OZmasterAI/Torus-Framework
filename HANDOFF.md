# Session 188 — Switch to nomic-embed-text-v2-moe

## What Was Done
- Replaced Alibaba-NLP/gte-multilingual-base (broken, required 25-line monkey-patch) with nomic-ai/nomic-embed-text-v2-moe (clean, no patches)
- Removed entire buffer-patching block from `_init_chromadb()` in memory_server.py
- Installed `einops` dependency required by nomic model
- Removed stale `.embedding_migration_done` marker so migration re-runs on next MCP restart
- Fixed pre-existing test bugs: datetime import ordering, suggest_promotions crash when ChromaDB not initialized (lazy init guard)
- Reset Gate 6 escalation counter (was stuck at 11 due to MCP being down)
- Tests: 1311 passed, 1 pre-existing failure (compaction regression, unrelated)

## Model Comparison
| | thenlper/gte-base (old) | Alibaba (patched, abandoned) | nomic (new) |
|---|---|---|---|
| Context | 512 tokens | 8,192 tokens | 8,192 tokens |
| MTEB | ~66% | ~68% | ~67% |
| Patches | None | 4 buffer reinits | None |
| Matryoshka | No | No | Yes (768→256) |
| Architecture | Standard | Standard | MoE (305M active) |
| Disk | ~440MB | 580MB | ~950MB |

## Service Status
- Memory MCP: DOWN (needs restart to load nomic model + run migration)
- Tests: 1311 passed, 1 pre-existing failure
- Framework: v2.5.3 (Torus)
- Gates: 16 active (G8 dormant, G12 fully purged)
- Ramdisk: active
- Branch: Self-Sprint-2
- Embedding: nomic-ai/nomic-embed-text-v2-moe (768-dim, 8192 tokens, migration pending)

## What's Next
1. **Restart MCP server** — triggers `_migrate_embeddings()` + `_backfill_tiers()` with nomic model
2. Verify search quality post-migration, tune dedup thresholds if needed
3. Merge Self-Sprint-2 into main (all audit items complete)
4. Save session learnings to memory once MCP is back (Alibaba bug details, nomic selection rationale)

## Risk: GREEN
No monkey patches. Clean model swap. Backup exists at ~/data/memory/backup_minilm_20260222.json.
