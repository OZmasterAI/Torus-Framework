# /wiki-ingest — Ingest External Sources into Wiki

## When to use
When the user says "ingest this", "add this source", "process this article", or when new files appear in `~/vault/raw/`.

## Steps
1. **READ SOURCE** — Read the source document (URL, file, or pasted text)
2. **SAVE RAW** — Copy/save the source to `~/vault/raw/<date>-<slug>.md` as immutable reference
3. **DISCUSS** — Briefly discuss key takeaways with the user
4. **FIND PAGES** — Read `~/vault/wiki/_index.md` to identify which existing pages to update
5. **UPDATE PAGES** — For each relevant topic (a single source may touch 5-15 pages):
   - Revise summaries with new information
   - Add cross-references to the new source
   - Flag contradictions with existing wiki content explicitly:
     > [!warning] Contradiction
     > Source X claims Y, but [[existing-page]] states Z. Needs resolution.
6. **CREATE PAGES** — If the source introduces new topics, create new wiki pages
7. **UPDATE INDEX** — Add new pages to `~/vault/wiki/_index.md`
8. **APPEND LOG** — Add ingest entry to `~/vault/wiki/log.md`:
   `## [YYYY-MM-DD] ingest | source-name — key topics updated`
9. **REMEMBER** — `remember_this()` with raw source summary for LanceDB backup

## Source Types
- **URL**: Fetch and extract content, save rendered markdown to `raw/`
- **File**: Copy to `raw/`, process content
- **Pasted text**: Save as `raw/<date>-paste-<slug>.md`
- **Obsidian Web Clipper**: Files dropped into `raw/` by browser extension

## Rules
- Never modify files in `raw/` after initial save — they are immutable reference copies
- Always flag contradictions rather than silently overwriting
- Use `mem:` links when the source content has also been stored via remember_this()
