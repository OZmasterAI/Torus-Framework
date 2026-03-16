# Implementation Plan: MWP Memory Type (Reference/Working)

## Design Decision
Option C: Filter Only (session 416, decided after devil's advocate review of original plan).
Add `memory_type` field to classify memories as `reference` (stable knowledge) or `working` (session-specific/transient). **Filter only — no scoring changes.** Existing tier system and 15-day decay are untouched. memory_type is searchable metadata that enables targeted retrieval per-query.

### Why Option C over A/B
- Scoring changes (A) add complexity with marginal benefit — two competing scoring axes to debug
- Merging tier+type (B) is destructive and requires perfect classification (58% unclassified in simulation)
- Filter only (C) gives the real value (targeted retrieval) with zero scoring risk
- Misclassification in a filter = missed result. Misclassification in scoring = corrupted ranking.
- Scoring boosts can be added later as a config flag once classifier accuracy is proven (upgrade path to A-lite)

## Prerequisite
Memory v2 layered redesign must be merged first. This plan targets the new architecture:
- `hooks/shared/write_pipeline.py` (or `memory_server.py` WritePipeline) — auto-classification
- `hooks/memory_server.py` — schema, migration, search filter param

## Success Criteria
1. LanceDB `knowledge` table has `memory_type` column (string: `"reference"`, `"working"`, `""`)
2. Auto-migration adds column to existing tables on restart (empty string default)
3. `_classify_memory_type(content, tags)` assigns type on every `remember_this()` call
4. `search_knowledge()` accepts optional `memory_type` filter param with 3 modes:
   - `memory_type=""` (default) — all results, same as today
   - `memory_type="reference"` — only reference memories
   - `memory_type="working"` — only working memories
5. Scoring engine is **untouched** — no decay changes, no boosts, no memory_type awareness
6. All existing tests pass unchanged
7. New tests cover all 5 behaviors above

## Reference vs Working — Classification Rules

**Reference** (stable knowledge):
- Tags contain: `type:decision`, `type:preference`, `type:correction`, `type:learning` with `outcome:success`
- Tags contain: `type:index`, `type:benchmark`
- Content contains: API facts, architecture decisions, config values, thresholds
- High salience score (≥0.40)

**Working** (session-specific, transient):
- Tags contain: `type:auto-captured`, `session<N>`, `needs-enrichment`
- Tags contain: `type:error` without `outcome:success`
- Content contains: session references ("Session 410:"), in-progress notes
- Low salience score (<0.15) AND short content (<200 chars)

**Unclassified** (empty string — same behavior as today):
- Everything else — existing tier+decay handles ranking
- Backfill migration can classify these later (optional future task)

## Future Upgrade Path (not in scope)
Once classifier accuracy is validated over several sessions, scoring boosts can be added:
- A-lite: +0.05 ref boost, 2x working recency, same 15-day decay for all
- Togglable via config flag `memory_type_scoring: true`
- Wire into skills: /brainstorm uses memory_type=reference, session start uses memory_type=working

---

## Tasks

### Task 1: Add `memory_type` column to LanceDB schema
**Test first:**
```python
def test_memory_type_column_exists():
    """knowledge schema includes memory_type field."""
    schema = _KNOWLEDGE_SCHEMA
    assert "memory_type" in schema.names
    assert schema.field("memory_type").type == pa.string()
```

**Implementation:**
- File: `hooks/memory_server.py` (schema section, ~line 173)
- Add `pa.field("memory_type", pa.string())` to `_KNOWLEDGE_SCHEMA` after `cluster_id`
- Auto-migration in `_open_or_create()` handles existing tables (adds column with `''` default)

**Verify:** `python -c "import pyarrow as pa; exec(open('memory_server.py').read().split('_FIX_OUTCOMES')[0]); print([f.name for f in _KNOWLEDGE_SCHEMA])"` shows `memory_type`

**Depends on:** nothing

---

### Task 2: Create `_classify_memory_type()` pure function
**Test first:**
```python
def test_classify_reference_decision():
    """Decisions are reference memories."""
    assert _classify_memory_type("LanceDB uses cosine", "type:decision,area:framework") == "reference"

def test_classify_reference_preference():
    """User preferences are reference."""
    assert _classify_memory_type("Never push without asking", "type:preference") == "reference"

def test_classify_working_auto_captured():
    """Auto-captured observations are working."""
    assert _classify_memory_type("git status output", "type:auto-captured") == "working"

def test_classify_working_session_note():
    """Session-specific notes are working."""
    assert _classify_memory_type("Session 410: added evidence pointers", "type:feature,session410") == "working"

def test_classify_working_error_no_fix():
    """Errors without success outcome are working."""
    assert _classify_memory_type("ImportError in test", "type:error") == "working"

def test_classify_unclassified_default():
    """Ambiguous content returns empty string."""
    assert _classify_memory_type("some generic note", "area:backend") == ""

def test_classify_reference_high_salience():
    """High salience + T1 = reference."""
    assert _classify_memory_type(
        "Critical fix: gate bypass vulnerability patched",
        "type:fix,type:decision,priority:critical,outcome:success"
    ) == "reference"

def test_classify_working_tier3():
    """Tier 3 content is working."""
    assert _classify_memory_type("brief note", "type:auto-captured,tier3-indicator") == "working"
```

**Implementation:**
- File: `hooks/memory_server.py` (near `_classify_tier`, ~line 863)
```python
_REFERENCE_TAGS = {"type:decision", "type:preference", "type:correction", "type:index", "type:benchmark"}
_REFERENCE_COMBO = {"type:learning"}  # only if also has outcome:success
_WORKING_TAGS = {"type:auto-captured", "needs-enrichment"}
_WORKING_ERROR = {"type:error"}  # only if NOT outcome:success

_SESSION_RE = re.compile(r"session\d+", re.IGNORECASE)

def _classify_memory_type(content: str, tags: str) -> str:
    """Classify memory as 'reference', 'working', or '' (unclassified).

    Pure function — no side effects. Called during remember_this().
    """
    tag_set = {t.strip().lower() for t in tags.split(",") if t.strip()} if tags else set()

    # Reference: explicit high-signal tags
    if tag_set & _REFERENCE_TAGS:
        return "reference"
    if tag_set & _REFERENCE_COMBO and "outcome:success" in tag_set:
        return "reference"

    # Reference: high salience + would be T1
    salience = _salience_score(content, tags)
    if salience >= 0.40:
        return "reference"

    # Working: auto-captured, session-specific, unresolved errors
    if tag_set & _WORKING_TAGS:
        return "working"
    if tag_set & _WORKING_ERROR and "outcome:success" not in tag_set:
        return "working"
    if any(_SESSION_RE.match(t) for t in tag_set):
        return "working"

    # Working: low salience
    if salience < 0.15 and len(content) < 200:
        return "working"

    return ""
```

**Verify:** `python -m pytest tests/test_memory_type.py -v`

**Depends on:** Task 1

---

### Task 3: Wire `_classify_memory_type()` into `remember_this()`
**Test first:**
```python
def test_remember_this_sets_memory_type():
    """remember_this() auto-classifies memory_type before upsert."""
    # Mock the upsert and verify the record includes memory_type
    result = remember_this("LanceDB uses cosine similarity", "testing", "type:decision")
    assert result.get("memory_type") in ("reference", "working", "")
```

**Implementation:**
- File: `hooks/memory_server.py` in `remember_this()`, after `_classify_tier()` call
- Add: `memory_type = _classify_memory_type(content, tags)`
- Include `memory_type` in the upsert record dict
- Return `memory_type` in the result dict

**Verify:** `python -m pytest tests/test_mem2x.py -v`

**Depends on:** Task 2

---

### ~~Task 4: REMOVED (Option C — no scoring changes)~~
### ~~Task 5: REMOVED (Option C — no scoring changes)~~

---

### Task 4: Add `memory_type` filter to `search_knowledge()`
**Test first:**
```python
def test_search_filter_reference_only():
    """memory_type='reference' filters to reference memories only."""
    results = search_knowledge("test query", memory_type="reference")
    for r in results.get("results", []):
        assert r.get("memory_type") == "reference"

def test_search_filter_working_only():
    """memory_type='working' filters to working memories only."""
    results = search_knowledge("test query", memory_type="working")
    for r in results.get("results", []):
        assert r.get("memory_type") == "working"

def test_search_filter_empty_returns_all():
    """Empty memory_type returns all types (backward compatible, default)."""
    results = search_knowledge("test query")
    types = {r.get("memory_type", "") for r in results.get("results", [])}
    assert len(types) >= 1  # at least some results
```

**Implementation:**
- File: `hooks/memory_server.py` in `search_knowledge()` signature
- Add param: `memory_type: str = ""` (empty = no filter, default)
- Three modes:
  - `memory_type=""` — all results, same as today
  - `memory_type="reference"` — only reference memories
  - `memory_type="working"` — only working memories
- After primary retrieval, filter: `if memory_type: results = [r for r in results if r.get("memory_type") == memory_type]`
- Update the MCP tool docstring to document the new param

**Verify:** `python -m pytest tests/test_mem2x.py -v`

**Depends on:** Tasks 1, 3

---

### Task 5: Backfill migration script
**Test first:**
```bash
# Dry run — count how many would be classified
python hooks/scripts/backfill_memory_type.py --dry-run
# Should print counts: N reference, M working, K unclassified
```

**Implementation:**
- File: `hooks/scripts/backfill_memory_type.py` (new)
```python
"""Backfill memory_type for existing knowledge entries.

Usage:
    python backfill_memory_type.py [--dry-run]
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from memory_server import _classify_memory_type, _ensure_initialized, collection

def backfill(dry_run=False):
    _ensure_initialized()
    tbl = collection._tbl
    df = tbl.to_pandas()
    counts = {"reference": 0, "working": 0, "": 0}
    updates = []
    for _, row in df.iterrows():
        current = row.get("memory_type", "")
        if current:  # already classified
            continue
        new_type = _classify_memory_type(row["text"], row.get("tags", ""))
        counts[new_type] += 1
        if new_type and not dry_run:
            updates.append({"id": row["id"], "memory_type": new_type})
    print(f"Reference: {counts['reference']}, Working: {counts['working']}, Unclassified: {counts['']}")
    if updates and not dry_run:
        # Batch update via merge
        import pyarrow as pa
        update_tbl = pa.table({"id": [u["id"] for u in updates],
                               "memory_type": [u["memory_type"] for u in updates]})
        tbl.merge(update_tbl, left_on="id", right_on="id")
        print(f"Updated {len(updates)} entries")

if __name__ == "__main__":
    backfill(dry_run="--dry-run" in sys.argv)
```

**Verify:** `python hooks/scripts/backfill_memory_type.py --dry-run`

**Depends on:** Tasks 1, 2

---

## Verification (end-to-end)
```bash
cd ~/.claude/hooks
python -m pytest tests/test_mem2x.py -v
python -m pytest tests/test_shared_deep.py -v
python -m pytest tests/test_memory_type.py -v
python scripts/backfill_memory_type.py --dry-run
```

## Rollback
- Remove `memory_type` from `_KNOWLEDGE_SCHEMA` — column stays in LanceDB but is ignored
- Revert `search_knowledge()` filter — param ignored
- No data loss — the column can sit dormant harmlessly
- Scoring engine was never touched — nothing to revert there

## Estimated Effort
- Tasks 1-3: Schema + classification + wire-in (~1.5 hours)
- Task 4: Search filter (15 min)
- Task 5: Backfill script (30 min)
- **Total: ~2 hours after v2 redesign merges**
