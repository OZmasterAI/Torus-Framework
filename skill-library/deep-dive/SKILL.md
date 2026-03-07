# /deep-dive — Comprehensive Memory Context Retrieval

## When to use
When the user says "deep dive", "full context", "what do we know about", or needs comprehensive institutional knowledge on a topic.

## Steps
1. **BROAD SEARCH** — Cast a wide net:
   - `search_knowledge("[topic]", top_k=50)` — returns up to 50 results with full relevance scoring
   - `search_knowledge("[relevant tags]", mode="tags")` — find entries by structured tags
   - `search_knowledge("[topic]", mode="all")` — also includes auto-captured observations
2. **EXPAND RELEVANT HITS** — For the top 5-10 most relevant results:
   - `get_memory(id)` to retrieve full content (search only returns previews)
3. **CHECK FIX HISTORY** (if error-related):
   - `query_fix_history("[error text]")` — see what strategies worked or failed
4. **SYNTHESIZE** — Present findings organized by:
   - **Timeline**: When things happened (oldest to newest)
   - **Decisions**: Key choices made and their rationale
   - **Issues**: Known problems, past bugs, and their resolutions
   - **Patterns**: Recurring themes or learnings
   - **Gaps**: What we DON'T know (topics with no memory entries)
5. **SAVE SYNTHESIS** (if the deep-dive revealed new insights):
   - `remember_this("[synthesis summary]", "deep-dive on [topic]", "type:learning")`
