# /web — Web Page Indexing & Search

## When to use
When user says "web index", "web search", "index this url", "search the web pages",
"what does [url] say about", or wants to store/query web content.

## Steps
1. Parse the user's intent: index | search | list | delete
2. Run the appropriate script:
   - **index**: `python3 ~/.claude/skills/web/scripts/index.py <url> [--preview]`
   - **search**: `python3 ~/.claude/skills/web/scripts/search.py "<query>" [--n 5]`
   - **list**: `python3 ~/.claude/skills/web/scripts/list.py [--pattern <url-glob>]`
   - **delete**: `python3 ~/.claude/skills/web/scripts/delete.py <url-pattern>`
3. Display the output to the user
4. For search results, offer to deep-dive into specific pages or index more URLs
5. If any script fails, report the error — do NOT fall back to WebFetch

## Examples
- `/web index https://docs.python.org/3/library/json.html` — index a page
- `/web index https://example.com --preview` — preview what would be indexed
- `/web search "json parsing"` — search indexed content
- `/web list` — list all indexed URLs
- `/web list --pattern "docs.python.org*"` — list filtered URLs
- `/web delete "docs.python.org"` — remove indexed pages matching pattern
