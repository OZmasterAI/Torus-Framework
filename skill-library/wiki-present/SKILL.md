# /wiki-present — Generate Marp Presentations from Wiki

## When to use
When the user says "make a presentation", "slides for X", "present this topic", or wants to share wiki knowledge visually.

## Steps
1. **IDENTIFY TOPIC** — Determine what the presentation covers
2. **READ WIKI** — Read relevant wiki pages from `~/vault/wiki/` for source material
3. **GENERATE SLIDES** — Create a Marp markdown file at `~/vault/wiki/presentations/<topic-slug>.md`
4. **CROSS-REFERENCE** — Add wikilinks to source pages in speaker notes

## Marp Format
Use this frontmatter:
---
marp: true
theme: default
paginate: true
---

Slide separator: `---` between slides
Standard markdown for content
`![bg](image)` for background images
`<!-- _class: lead -->` for title slides

## Slide Structure
1. Title slide — topic + date + source wiki pages
2. Overview — key points from wiki synthesis
3-N. Detail slides — one per major section from wiki pages
N+1. Architecture diagram (if applicable, use Mermaid or ASCII)
N+2. Summary + links to wiki pages for further reading

## Rules
- Presentations live in `~/vault/wiki/presentations/`
- Always cite source wiki pages in speaker notes: `<!-- Source: [[page-name]] -->`
- Keep slides concise — wiki pages have the full detail
- Update log.md when creating presentations
