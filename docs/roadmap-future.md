# Roadmap — Future

## Smart Memory Merging (Compactor v2)

**Status:** Proposed

**Problem:** The current compactor only does straight dedup (>0.95 cosine — delete duplicates, keep survivor). Entries in the 0.85–0.95 similarity range are related but distinct — two partial memories about the same topic that would be more useful as one comprehensive entry.

**Proposed: Two-tier compaction**
- **Tier 1 (>0.95 cosine):** Straight dedup as now. Keep survivor, delete rest.
- **Tier 2 (0.85–0.95 cosine):** Merge entries into one richer entry, re-embed via NIM API.

**Merge strategies (no LLM needed):**
- Pick the longest/richest entry as survivor, append unique details from others
- Concatenate non-overlapping sentences from each entry
- Union tags, keep highest tier, use newest timestamp

**Re-embedding:** After merging text, call NIM API (nvidia/nv-embed-v1) to get a fresh 4096-dim vector for the combined entry.

**Tradeoffs:**
- (+) Better retrieval — one comprehensive entry ranks higher than two partial ones
- (+) Reduces memory count while preserving information
- (+) No LLM cost — mechanical merge only
- (-) NIM API cost per merge (~1 call per merged cluster)
- (-) Risk of losing nuance if merge is too aggressive
- (-) Need audit log of what was merged for quality verification

**Prerequisites:**
- Clean up dead `_embed()` / `_get_embedding_fn()` code from memory_compactor.py
- Add NIM embed helper (reuse pattern from skill_search.py or memory_server.py)
- Add merge audit log (JSON, similar to existing purge audit trails)
