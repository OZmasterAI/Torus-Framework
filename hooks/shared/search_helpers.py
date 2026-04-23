"""Search Helpers — query mode detection, result merging, keyword search.

Extracted from memory_server.py as part of Memory v2 Layered Redesign.

Public API:
    from shared.search_helpers import (
        detect_query_mode, merge_results, lance_fts_to_summary,
        lance_keyword_search, fuzzy_keyword_search, generate_fuzzy_variants,
        tag_ids_to_summaries, TagCooccurrence,
    )
"""

import math


def detect_query_mode(query, routing="default"):
    """Route queries to the appropriate search engine.

    Args:
        query:   The search query string.
        routing: Routing strategy — "default" (current heuristics),
                 "fast" (expanded FTS5 keyword routing),
                 "full_hybrid" (both engines for all queries).

    Returns one of: 'tags', 'keyword', 'semantic', 'hybrid'.
    """
    q = query.strip()
    ql = q.lower()

    # Tag queries: always FTS5 regardless of routing
    if ql.startswith("tag:") or ql.startswith("tags:"):
        return "tags"

    # Full Hybrid: everything else goes through both engines
    if routing == "full_hybrid":
        return "hybrid"

    # Keyword: quoted phrases or boolean operators
    if '"' in q or " AND " in q or " OR " in q:
        return "keyword"

    words = q.split()

    # Keyword: 1-2 word queries (likely identifiers or exact terms)
    if len(words) <= 2:
        return "keyword"

    # Fast mode: catch technical 3-4 word queries for FTS5
    if routing == "fast" and len(words) <= 4:
        if any("_" in w or "." in w for w in words):
            return "keyword"
        if any(c.isupper() for w in words for c in w[1:]):
            return "keyword"

    # Semantic: questions or long natural language
    if ql.endswith("?") or ql.startswith(
        ("how ", "why ", "what ", "when ", "where ", "which ")
    ):
        return "semantic"
    if len(words) >= 5:
        return "semantic"

    # Hybrid: 3-4 word ambiguous queries
    return "hybrid"


def merge_results(fts_results, lance_summaries, top_k=15):
    """Merge FTS5 and LanceDB results using Reciprocal Rank Fusion (RRF).

    RRF gives each engine equal weight: score = sum(1/(k+rank)) across engines.
    Items appearing in both engines naturally score ~2x higher.
    k=60 is the standard RRF constant (dampens rank position differences).
    """
    k = 60  # RRF smoothing constant
    scores = {}  # memory_id -> rrf_score
    entries = {}  # memory_id -> best entry dict
    sources = {}  # memory_id -> set of source names

    # Score vector results by rank
    for rank, entry in enumerate(lance_summaries, start=1):
        mid = entry.get("id", "")
        if not mid:
            continue
        scores[mid] = scores.get(mid, 0) + 1 / (k + rank)
        entries[mid] = dict(entry)
        sources[mid] = {"semantic"}

    # Score FTS5 results by rank
    for rank, entry in enumerate(fts_results, start=1):
        mid = entry.get("id", "")
        if not mid:
            continue
        scores[mid] = scores.get(mid, 0) + 1 / (k + rank)
        if mid not in entries:
            entries[mid] = dict(entry)
        sources.setdefault(mid, set()).add("keyword")

    # Inject RRF score as relevance and set match label
    for mid, entry in entries.items():
        entry["relevance"] = scores[mid]
        entry["match"] = "both" if len(sources[mid]) > 1 else sources[mid].pop()

    results = list(entries.values())
    results.sort(key=lambda x: x.get("relevance", 0), reverse=True)

    return results[:top_k]


def lance_fts_to_summary(row, summary_length=120):
    """Convert a LanceDB FTS result row to the standard summary dict format."""
    entry = {
        "id": row.get("id", ""),
        "preview": row.get("preview", row.get("text", "")[:summary_length]),
        "tags": row.get("tags", ""),
        "timestamp": row.get("timestamp", ""),
        "fts_score": round(row.get("_score", 0.0), 4),
    }
    url = row.get("primary_source", "")
    if url:
        entry["url"] = url
    return entry


def lance_keyword_search(
    query, top_k=15, collection=None, fts_ready=False, summary_length=120
):
    """LanceDB native BM25 keyword search. Falls back to empty on error.

    Args:
        query: Search query string
        top_k: Max results
        collection: LanceCollection instance (must have _table attribute)
        fts_ready: Whether FTS index is built
        summary_length: Preview truncation length
    """
    if not fts_ready or collection is None:
        return []
    try:
        rows = collection._table.search(query).limit(top_k).to_list()
        return [lance_fts_to_summary(r, summary_length) for r in rows]
    except Exception:
        return []


def generate_fuzzy_variants(term, max_distance=1):
    """Generate spelling variants within edit distance for fuzzy matching."""
    if len(term) <= 2:
        return [term]

    variants = {term}
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789_"

    for i in range(len(term)):
        variants.add(term[:i] + term[i + 1 :])

    for i in range(len(term)):
        for c in alphabet:
            if c != term[i]:
                variants.add(term[:i] + c + term[i + 1 :])

    for i in range(len(term) - 1):
        variants.add(term[:i] + term[i + 1] + term[i] + term[i + 2 :])

    return list(variants)


def fuzzy_keyword_search(
    query, table_name="knowledge", top_k=10, collections=None, fts_ready=False
):
    """Search with fuzzy term expansion for typo tolerance.

    Args:
        query: Search query string
        table_name: Which table to search
        top_k: Max results
        collections: Dict mapping table_name -> LanceCollection
        fts_ready: Whether FTS index is built
    """
    if not fts_ready or not collections:
        return []

    tbl_coll = collections.get(table_name)
    if tbl_coll is None:
        return []

    terms = query.lower().split()
    if not terms:
        return []

    all_variants = []
    exact_terms = set(terms)
    for term in terms:
        all_variants.extend(generate_fuzzy_variants(term))

    expanded_query = " OR ".join(set(all_variants))

    try:
        rows = (
            tbl_coll._table.search(expanded_query, query_type="fts")
            .limit(top_k * 2)
            .to_list()
        )
        if not rows:
            return []

        scored_results = []
        for row in rows:
            text_lower = str(row.get("text", "")).lower()
            boost = 1.0
            for term in exact_terms:
                if term in text_lower:
                    boost = 2.0
                    break
            scored_results.append(
                {
                    "id": str(row.get("id", "")),
                    "text": str(row.get("text", ""))[:500],
                    "relevance": float(row.get("_score", 0.5)) * boost,
                    "tags": str(row.get("tags", "")),
                    "match_type": "exact" if boost > 1.0 else "fuzzy",
                }
            )

        scored_results.sort(key=lambda x: x["relevance"], reverse=True)
        return scored_results[:top_k]
    except Exception:
        return []


def tag_ids_to_summaries(memory_ids, collection=None):
    """Fetch full metadata from LanceDB for a list of memory IDs."""
    if not memory_ids or collection is None:
        return []
    try:
        data = collection.get(ids=list(memory_ids), include=["metadatas"])
        results = []
        for i, mid in enumerate(data.get("ids", [])):
            meta = data["metadatas"][i] if i < len(data.get("metadatas", [])) else {}
            entry = {
                "id": mid,
                "preview": meta.get("preview", ""),
                "tags": meta.get("tags", ""),
                "timestamp": meta.get("timestamp", ""),
            }
            url = meta.get("primary_source", "")
            if url:
                entry["url"] = url
            results.append(entry)
        return results
    except Exception:
        return []


class TagCooccurrence:
    """Tag co-occurrence matrix with PMI-based expansion."""

    _REBUILD_COOLDOWN = 60

    def __init__(self):
        self.cooccurrence = {}
        self.counts = {}
        self.dirty = True
        self.total_memories = 0
        self._last_build = 0

    def build(self, tag_index):
        """Build tag co-occurrence matrix from tag index."""
        import time

        self._last_build = time.monotonic()
        conn = tag_index.conn
        rows = conn.execute("SELECT memory_id, tag FROM tags").fetchall()

        mem_tags = {}
        tag_totals = {}
        for mid, tag in rows:
            mem_tags.setdefault(mid, set()).add(tag)
            tag_totals[tag] = tag_totals.get(tag, 0) + 1

        cooccur = {}
        for _mid, tagset in mem_tags.items():
            tags = list(tagset)
            for i in range(len(tags)):
                for j in range(len(tags)):
                    if i != j:
                        cooccur.setdefault(tags[i], {})
                        cooccur[tags[i]][tags[j]] = cooccur[tags[i]].get(tags[j], 0) + 1

        self.cooccurrence = cooccur
        self.counts = tag_totals
        self.total_memories = len(mem_tags)
        self.dirty = False

    def get_expanded_tags(self, query, tag_index=None):
        """Find tags that co-occur with tags matching the query (PMI > 1.0)."""
        import time

        if (
            self.dirty
            and tag_index
            and (time.monotonic() - self._last_build >= self._REBUILD_COOLDOWN)
        ):
            self.build(tag_index)

        if not self.counts:
            return []

        query_lower = query.lower().strip()
        query_tokens = set(query_lower.split())

        matched_tags = []
        for tag in self.counts:
            tag_lower = tag.lower()
            if len(tag_lower) < 4:
                continue
            if tag_lower == query_lower or tag_lower in query_tokens:
                matched_tags.append(tag)

        if not matched_tags:
            return []

        expanded = set()
        matched_set = set(matched_tags)
        N = self.total_memories
        for tag in matched_tags:
            if tag not in self.cooccurrence:
                continue
            count_x = self.counts.get(tag, 1)
            for co_tag, co_count in self.cooccurrence[tag].items():
                if co_tag in matched_set:
                    continue
                count_y = self.counts.get(co_tag, 1)
                if N > 0 and count_x > 0 and count_y > 0:
                    tag_pmi = math.log2((co_count * N) / (count_x * count_y))
                    if tag_pmi > 1.0:
                        expanded.add(co_tag)

        return list(expanded)[:15]
