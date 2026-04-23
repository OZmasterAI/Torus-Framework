# /wiki-update — Update Wiki Pages

## When to use
After fixes, decisions, discoveries, or during wrap-up. Anytime knowledge should be committed to the wiki.

## Steps
1. **FIND RELEVANT PAGES** — Read `~/vault/wiki/_index.md` to find pages related to the current topic
2. **UPDATE OR CREATE** — For each touched topic:
   - If page exists: revise content, update `last_updated` and `session` in frontmatter, add `mem:` links for new LanceDB entries
   - If no page exists: create one using the template below
3. **CROSS-REFERENCE** — Update `## Related` sections bidirectionally:
   - If page A now links to page B, ensure page B links back to page A
   - Use `[[wikilinks]]` for all cross-references
4. **UPDATE INDEX** — If new pages were created, add them to `~/vault/wiki/_index.md` in the appropriate section
5. **APPEND LOG** — Add one-line entry to `~/vault/wiki/log.md`:
   `## [YYYY-MM-DD] verb | topic — details`

## Page Template
When creating new wiki pages, use this format:
---
type: wiki
last_updated: YYYY-MM-DD
session: NNN
project: project-name
tags: [relevant, tags]
---
# Page Title
One-sentence summary of what this page covers.
File: `path/to/source.py` | Context: brief context

## Current State
[Synthesized understanding — always kept current, not historical]

## Known Issues
- Active issues or bypasses (use strikethrough ~~for fixed ones~~ with session + mem: link)

## Related
- [[other-page]] — relationship description

## Evidence
- `mem:abc123def45` — description of what this memory contains

## Rules
- Frontmatter fields: type, last_updated, session, project, tags — all required
- `mem:` links use first 11 chars of LanceDB ID
- All writes use atomic pattern: write to .tmp, then os.replace()
- Never delete existing content — revise or strikethrough instead
- Cross-references MUST be bidirectional

## Filing answers back
When a session produces a novel synthesis, comparison, analysis, or architectural insight that would be valuable across sessions:
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

## Project Pages
Project instances detect their project via `detect_project()` and update `wiki/projects/<slug>.md`.
Each project instance updates its own page plus any cross-cutting pages (patterns, systems).

### Project Page Template
```markdown
---
type: wiki
project: <project-name>
last_updated: YYYY-MM-DD
session: NNN
tags: [project, <stack-tags>]
---
# <Project Name>

## Status
Current phase and what's active.

## Current Work
What's being built or fixed right now.

## Known Issues
- Active bugs or blockers

## Architecture
Stack, key files, deployment.

## Related
- [[torus-framework]] — shared framework
- [[other-relevant-page]] — relationship
```

### Project Detection
Run: `python3 -c "import sys; sys.path.insert(0, '$HOME/.claude/hooks'); from boot_pkg.util import detect_project; n,d,s,sd = detect_project(); print(n or 'framework')"`
- Returns project name → write to `wiki/projects/<slug>.md`
- Returns "framework" → update system/pattern pages, not a project page
- `gather.py` wiki state check uses absolute path `~/vault/wiki/` — works from any CWD
