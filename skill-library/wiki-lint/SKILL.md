# /wiki-lint — Wiki Health Check

## When to use
Periodic maintenance, when user asks "check wiki" or "wiki health", or during idle loops.

## Steps
1. **SCAN** — Read all files under `~/vault/wiki/` recursively
2. **CHECK** each page for:
   - **Stale pages**: `last_updated` in frontmatter older than 2 weeks
   - **Orphan pages**: no inbound `[[wikilinks]]` from any other page
   - **Dead links**: `[[wikilinks]]` that point to nonexistent files
   - **Broken mem: links**: `mem:` IDs that don't resolve via `get_memory(id)`
   - **Missing cross-refs**: page A links to B, but B doesn't link back to A
   - **Missing frontmatter**: pages without `type`, `last_updated`, or `session` fields
   - **Index drift**: pages that exist but aren't listed in `_index.md`
3. **REPORT** findings grouped by severity:
   - Critical: broken mem: links, dead wikilinks
   - Warning: stale pages, orphans, missing cross-refs
   - Info: index drift, missing optional frontmatter fields
4. **FIX** with user approval — never auto-fix without asking

## Output Format
```
Wiki Health Report — YYYY-MM-DD
Pages scanned: N

Critical (N):
- [[page-name]] — broken mem:abc123def45 link
- [[other-page]] — dead link to [[nonexistent]]

Warnings (N):
- [[stale-page]] — last updated 21 days ago
- [[orphan-page]] — no inbound links

Info (N):
- [[unlisted-page]] — not in _index.md
```
