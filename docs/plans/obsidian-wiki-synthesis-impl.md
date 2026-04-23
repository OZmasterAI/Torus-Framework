# Implementation Plan: Obsidian Wiki Synthesis Layer

## Design Decision
Add a Karpathy-style synthesized wiki layer to the existing Obsidian vault.
LanceDB stays as the raw store; the wiki becomes the human-readable, pre-compiled
synthesis with memory ID links back to evidence. Full vault reset first — current
content (session dumps, stale entity stubs) is not useful.

Inspired by: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f

## Success Criteria
- [ ] Vault reset: only `.obsidian/` survives, everything else cleared
- [ ] `wiki/_index.md` exists and catalogs all pages
- [ ] `wiki/log.md` exists as chronological changelog
- [ ] Wrap-up skill updates relevant wiki pages (not just session dumps)
- [ ] Wiki pages contain `mem:` links back to LanceDB IDs
- [ ] All project instances write wiki pages (not just framework hub)
- [ ] `session_end.py` vault functions rewritten for wiki updates
- [ ] Existing tests still pass: `python3 hooks/test_framework.py`
- [ ] Lint skill exists for periodic wiki health checks
- [ ] Ingest skill exists for processing external sources into wiki
- [ ] Query workflow reads wiki pages before/alongside search_knowledge()
- [ ] Good session syntheses get filed back as wiki pages

## Architecture

```
LanceDB (raw store) ←→ Wiki pages (synthesis + mem: links)
     ↑                        ↑
 remember_this()          wrap-up wiki-update step
 search_knowledge()       Claude reads wiki pages first
                          human browses in Obsidian
```

### Operations (aligned with Karpathy)
- **Ingest**: Feed a source (article, doc, paper) → LLM reads it → integrates into
  multiple wiki pages, updates cross-references, appends to log.md
- **Query**: Read `_index.md` → find relevant wiki pages → read them → synthesize answer.
  Use `search_knowledge()` to fill gaps the wiki doesn't cover yet.
  Good answers get filed back as new wiki pages.
- **Lint**: Periodic health check — stale pages, orphans, contradictions, missing cross-refs
- **Update**: During wrap-up — revise wiki pages touched by the session's work

Vault structure after reset:
```
~/vault/
├── .obsidian/              # preserved — plugins, settings, theme
├── wiki/
│   ├── _index.md           # master catalog, updated on every wiki write
│   ├── log.md              # chronological changelog (append-only)
│   ├── gates/              # one page per gate (living docs)
│   ├── systems/            # memory, enforcer, skills, routing, state
│   ├── patterns/           # known bypasses, common fixes, test patterns
│   └── projects/           # per-project synthesis pages
├── research/               # (empty, ready for future use)
└── raw/                    # (empty, for Karpathy-style source ingestion later)
```

Wiki page format:
```markdown
---
type: wiki
last_updated: 2026-04-23
session: 675
project: torus-framework
---
# Gate 01: Read Before Edit
Blocks Edit/Write if target file hasn't been Read in this session.
File: `hooks/gates/gate_01_read_before_edit.py` | Tier: T1 fail-closed

## Current State
[synthesized understanding — always current]

## Known Bypasses
- ~~Path traversal via `../`~~ — fixed s673 `mem:a1b2c3d4`
- ~~Extensionless file bypass~~ — fixed s673 `mem:e5f6g7h8`

## Related
- [[gate-02-no-destroy]] — complementary safety gate
- [[enforcer]] — orchestrates execution
```

## Tasks

### Task 1: Tag and reset vault
- **Test first**: `ls ~/vault/ | grep -v .obsidian | wc -l` should equal 0 after reset
- **Implementation**:
  - `cd ~/vault && git tag pre-wiki-reset` to preserve history
  - Remove everything except `.obsidian/` and `.git/`
  - Create empty directory structure: `wiki/`, `wiki/gates/`, `wiki/systems/`, `wiki/patterns/`, `wiki/projects/`, `research/`, `raw/`
  - Commit: "reset: clear vault for wiki synthesis layer"
- **Verify**: `ls ~/vault/wiki/` shows expected dirs; `.obsidian/` intact; `git log --oneline -1` shows reset commit
- **Depends on**: none

### Task 2: Create _index.md and log.md seed files
- **Test first**: `cat ~/vault/wiki/_index.md` should contain YAML frontmatter + section headers
- **Implementation**:
  - Write `wiki/_index.md` with frontmatter (`type: index`), sections for Gates, Systems, Patterns, Projects — all empty initially
  - Write `wiki/log.md` with frontmatter (`type: log`), header, and first entry: "Wiki initialized"
  - Both files follow Obsidian markdown conventions (wikilinks, callouts, frontmatter)
- **Verify**: Open in Obsidian or `cat` both files; valid YAML frontmatter
- **Depends on**: Task 1

### Task 3: Create wiki-update skill
- **Test first**: `run_tool("skills-v2", "search_skills", {"query": "wiki-update"})` should find the skill
- **Implementation**:
  - Create `skill-library/wiki-update/SKILL.md` with:
    - When to use: after fixes, decisions, discoveries, during wrap-up
    - Steps: (1) Read `wiki/_index.md` to find relevant pages. (2) For each touched topic, update or create the wiki page — revise content, update frontmatter, add `mem:` links. (3) Update `_index.md` if new pages created. (4) Append entry to `log.md`.
    - Page creation rules: frontmatter template, wikilink conventions, `mem:ID` format
    - Cross-referencing rules: link related pages, update "Related" sections bidirectionally
  - Register skill with toolshed if needed
- **Verify**: `run_tool("skills-v2", "invoke_skill", {"name": "wiki-update"})` returns skill content
- **Depends on**: Task 2

### Task 4: Create wiki-lint skill
- **Test first**: `run_tool("skills-v2", "search_skills", {"query": "wiki-lint"})` should find the skill
- **Implementation**:
  - Create `skill-library/wiki-lint/SKILL.md` with:
    - When to use: periodic maintenance, user asks "check wiki", during idle loops
    - Steps: (1) Scan all wiki pages. (2) Check for: stale pages (last_updated > 2 weeks), orphan pages (no inbound wikilinks), contradictions between pages, missing pages (wikilinks that point to nonexistent files), broken `mem:` links. (3) Report findings. (4) Fix with user approval.
- **Verify**: Skill searchable and invokable
- **Depends on**: Task 3

### Task 5: Add wiki-update step to wrap-up skill
- **Test first**: `grep "wiki" ~/crab/.claude/skill-library/wrap-up/SKILL.md` should show new step
- **Implementation**:
  - Edit `skill-library/wrap-up/SKILL.md`:
    - Add step 3.5 (between SAVE TO MEMORY and UPDATE STATE):
      ```
      3.5. **UPDATE WIKI** — Read `~/vault/wiki/_index.md`. For each topic touched
      this session, invoke wiki-update: revise the relevant wiki page(s), add mem:
      links for any remember_this() calls made in step 2, update cross-references.
      If a new topic emerged, create a page and add it to the index. Append a
      one-line entry to log.md.
      ```
    - The step is fail-open: if vault doesn't exist or wiki-update fails, warn and continue
  - Edit `skill-library/wrap-up/scripts/gather.py`:
    - Add `gather_wiki_state()` function: check if `~/vault/wiki/_index.md` exists, count wiki pages, find stale pages
    - Include wiki state in gathered JSON output
- **Verify**: Read SKILL.md, confirm step 3.5 exists; run gather.py, confirm wiki state in output
- **Depends on**: Task 3

### Task 6: Rewrite session_end.py vault functions for wiki
- **Test first**: Existing tests pass: `cd ~/.claude/hooks && python3 -m pytest tests/test_session_end.py -x`
- **Implementation**:
  - Remove old `write_vault_session_note()` function (lines 725-840) — replace with `append_wiki_log()`:
    - Appends one-line session entry to `~/vault/wiki/log.md`
    - Format: `## [YYYY-MM-DD] session NNN | project | feature — what_was_done`
    - Fail-open, atomic write
  - Remove old `write_vault_daily_note()` function (lines 904-1020) — no replacement needed (daily grouping is log.md's job now)
  - Re-enable the vault call in `_run_background()` (lines 1051-1080) pointing to new `append_wiki_log()`
  - Update tests in `tests/test_session_end.py` for new function signatures
- **Verify**: `python3 -m pytest tests/test_session_end.py -x` passes; manual test: run session_end hook, check log.md updated
- **Depends on**: Task 1, Task 2

### Task 7: Wire project instances into wiki
- **Test first**: From `/projects/torus-web-design`, wrap-up should mention wiki update
- **Implementation**:
  - `detect_project()` already returns project info — wiki-update skill uses this to:
    - Write project-specific pages to `wiki/projects/<project-slug>.md`
    - Use project name in frontmatter and wikilinks
  - Ensure `gather.py` wiki state check works from any CWD (use absolute path `~/vault/wiki/`)
  - Add project wiki page template to wiki-update skill:
    ```markdown
    ---
    type: wiki
    project: <project-name>
    last_updated: <date>
    session: <N>
    ---
    # <Project Name>
    ## Status
    ## Current Work
    ## Known Issues
    ## Architecture
    ## Related
    ```
  - Each project instance updates its own page + any cross-cutting pages (patterns, systems)
- **Verify**: Simulate wrap-up from a project dir; check `wiki/projects/` has the project page
- **Depends on**: Task 5, Task 6

### Task 8: Create wiki-ingest skill
- **Test first**: `run_tool("skills-v2", "search_skills", {"query": "wiki-ingest"})` should find the skill
- **Implementation**:
  - Create `skill-library/wiki-ingest/SKILL.md` with:
    - When to use: user says "ingest this", "add this source", "process this article", or new files appear in `raw/`
    - Steps: (1) Read the source document. (2) Discuss key takeaways with user. (3) Identify which wiki pages to update (read `_index.md`). (4) Update existing pages with new information — revise summaries, add cross-references, note contradictions with existing claims. (5) Create new pages if needed. (6) Update `_index.md`. (7) Append ingest entry to `log.md`. (8) `remember_this()` with raw source summary for LanceDB.
    - A single source may touch 5-15 wiki pages — that's expected
    - If source contradicts existing wiki content, flag it explicitly on the page
    - Sources saved to `raw/` folder as immutable reference (Obsidian Web Clipper can drop files here too)
  - Register skill with toolshed if needed
- **Verify**: Skill searchable and invokable
- **Depends on**: Task 2

### Task 9: Add query-against-wiki to session workflow
- **Test first**: `grep "wiki" ~/.claude/CLAUDE.md` should show wiki query rule
- **Implementation**:
  - Add to CLAUDE.md `MEMORY FIRST` section (or new `WIKI` section):
    ```
    ## WIKI (alongside MEMORY)
    When starting work on a topic, read ~/vault/wiki/_index.md.
    If relevant pages exist, read them before search_knowledge().
    Wiki pages have pre-compiled synthesis; search_knowledge() fills gaps
    the wiki doesn't cover yet.
    ```
  - Update session-start skill (if exists) to include wiki page reading
  - This is a behavioral rule, not code — Claude reads wiki pages as part of context gathering
- **Verify**: Start a new session, confirm Claude reads wiki pages when relevant topics exist
- **Depends on**: Task 2

### Task 10: Add file-answers-back to wiki-update skill
- **Test first**: `grep -i "file.*back\|synthesis.*page" ~/.claude/skill-library/wiki-update/SKILL.md` should match
- **Implementation**:
  - Add section to `wiki-update/SKILL.md`:
    ```
    ## Filing answers back
    When a session produces a novel synthesis, comparison, analysis, or
    architectural insight that would be valuable across sessions:
    1. Create a new wiki page for it (e.g., wiki/patterns/karpathy-vs-torus.md)
    2. Add frontmatter with type: wiki, source: conversation
    3. Cross-reference from related existing pages
    4. Update _index.md
    5. Append to log.md
    
    Signs something should be filed back:
    - Comparison tables or analysis that took significant reasoning
    - Architectural decisions with tradeoffs documented
    - Debugging insights that connect multiple systems
    - Patterns discovered across sessions
    ```
  - Also add to wrap-up SKILL.md step 3.5: "If this session produced a novel synthesis or comparison, file it back as a new wiki page."
- **Verify**: Read wiki-update SKILL.md, confirm filing-back section exists
- **Depends on**: Task 3

### Task 11: Seed initial wiki pages from conversation context
- **Test first**: `ls ~/vault/wiki/gates/ | wc -l` should be > 0
- **Implementation**:
  - NOT auto-generated from LanceDB — that produced thin stubs last time
  - Instead: create 5-10 starter pages with real synthesized content:
    - `wiki/systems/memory.md` — LanceDB, search_knowledge, remember_this, tables
    - `wiki/systems/enforcer.md` — gate pipeline, tiers, routing, caching
    - `wiki/systems/skills.md` — toolshed, skill-library, invoke_skill
    - `wiki/gates/gate-01-read-before-edit.md` — with recent bypass fixes
    - `wiki/gates/gate-02-no-destroy.md` — with recent security fixes
    - `wiki/projects/torus-framework.md` — current state
    - `wiki/projects/torus-web-design.md` — current state
    - `wiki/projects/torus-hyperbft.md` — current state
    - `wiki/patterns/common-fixes.md` — recurring fix patterns
  - Each page has real content (not stubs), `mem:` links where applicable, wikilinks
  - Update `_index.md` with all created pages
  - Append entries to `log.md`
- **Verify**: All pages valid markdown with frontmatter; `_index.md` lists them all; graph view shows connections
- **Depends on**: Task 2

### Task 12: Add Dataview queries to wiki pages
- **Test first**: `grep -c dataview ~/vault/wiki/_index.md` should be > 0
- **Implementation**:
  - Dataview plugin is already installed in `.obsidian/`
  - Add Dataview query blocks to `_index.md`:
    - Table of all wiki pages sorted by `last_updated` (shows what's current vs stale)
    - Table of pages grouped by `project`
    - Table of recently created pages (last 7 days)
  - Add Dataview query to each project page:
    - List all wiki pages where `project` matches (shows everything related to that project)
  - Ensure all wiki page frontmatter includes queryable fields: `type`, `last_updated`, `session`, `project`, `tags`
  - Example query block in `_index.md`:
    ````
    ```dataview
    TABLE last_updated, project, type
    FROM "wiki"
    SORT last_updated DESC
    LIMIT 20
    ```
    ````
- **Verify**: Open `_index.md` in Obsidian, confirm Dataview tables render with live data
- **Depends on**: Task 11

### Task 13: Add Marp slide generation support
- **Test first**: `cat ~/.claude/skill-library/wiki-present/SKILL.md | head -5` should exist
- **Implementation**:
  - Verify Marp plugin is installed in `.obsidian/` (install if not)
  - Create `skill-library/wiki-present/SKILL.md` with:
    - When to use: user says "make a presentation", "slides for X", "present this"
    - Steps: (1) Read relevant wiki pages for the topic. (2) Generate a Marp markdown file at `~/vault/wiki/presentations/<topic>.md`. (3) Use Marp frontmatter (`marp: true`, `theme`, `paginate`). (4) Structure: title slide, key points from wiki pages, architecture diagrams, summary. (5) Cross-reference source wiki pages.
    - Marp format reference: `---` separates slides, standard markdown for content, `![bg](image)` for backgrounds
  - Add `wiki/presentations/` to vault directory structure
- **Verify**: Skill invokable; test slide renders in Obsidian Marp preview
- **Depends on**: Task 2

## Verification (end-to-end)
1. Open Obsidian → vault shows clean wiki structure, graph view shows connected pages
2. Run a framework session → wrap-up updates relevant wiki pages + log.md
3. Run a project session (e.g., torus-web-design) → wrap-up updates project page + any cross-cutting pages
4. `search_knowledge()` still works as before (LanceDB untouched)
5. Wiki pages contain `mem:` links that resolve via `get_memory(id)`
6. `wiki-lint` skill finds no issues on fresh wiki
7. Ingest a test source → verify multiple wiki pages updated + source saved to `raw/`
8. Start a session on a wiki-covered topic → Claude reads wiki pages before search_knowledge()
9. Session produces a synthesis → verify it gets filed back as a wiki page
10. `_index.md` Dataview tables render in Obsidian with live data
11. Marp presentation generates and previews from wiki content

## Future (not in scope now, build when needed)
- **qmd search**: Local search engine over wiki files (BM25 + vector search). Karpathy
  recommends https://github.com/tobi/qmd — has CLI and MCP server. Build when wiki
  exceeds ~100 pages and `_index.md` scanning becomes too slow.
- **Obsidian Web Clipper**: Browser extension that clips articles as markdown to `raw/`.
  User installs it themselves; wiki-ingest skill already handles `raw/` files.

## Rollback
- `cd ~/vault && git revert HEAD` to undo any wiki changes
- `git checkout pre-wiki-reset` to restore full old vault
- Comment out step 3.5 in wrap-up SKILL.md to disable wiki updates
- Re-comment vault calls in session_end.py (same as current state)
- LanceDB is never touched — no rollback needed there
