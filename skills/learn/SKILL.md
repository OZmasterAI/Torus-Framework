---
name: learn
description: Learn from external sources (URLs, topics, questions) and integrate knowledge into the framework. Researches, analyzes, cross-references memory, synthesizes actionable findings, and optionally applies code improvements following The Loop.
---

# /learn — Learn from External Sources and Integrate Knowledge

## When to use
When the user says "learn about", "teach me", "integrate this", "read this article", "what can we adopt from", or provides a URL/topic they want absorbed into the framework's institutional knowledge.

## Invocation Examples
- `/learn https://docs.example.com/feature` — learn from a URL
- `/learn topic: "structured concurrency in Python"` — research a topic
- `/learn "how does X handle Y?"` — answer a question and remember the findings
- `/learn --apply topic` — learn AND propose code changes if improvements are found

## Steps

### 1. GATHER — Collect raw material
Accept one of three input forms:
- **URL**: `WebFetch(url)` to retrieve the page content directly
- **Topic/Question**: `WebSearch("[topic] best practices site:docs OR github OR arxiv")` (2-3 targeted queries), then `WebFetch` the top 2-3 results
- **Both**: If a URL is given alongside a question, fetch the URL first, then search for complementary context

During gather, also pull related memory:
- `search_knowledge("[topic]", top_k=20)` to surface what we already know
- If memory relevance > 0.5 for several results, present existing knowledge and ask the user if external research is still needed before fetching

### 2. ANALYZE — Extract what matters for our framework
From the raw fetched content, identify:
- **Key patterns**: Architectural patterns, design decisions, algorithms
- **Techniques**: Implementation techniques directly applicable to our codebase
- **Best practices**: Conventions, rules of thumb, anti-patterns to avoid
- **APIs / interfaces**: New tools, libraries, or protocols worth knowing
- **Limits / caveats**: Where the technique breaks down or doesn't apply

Focus the analysis on relevance to the torus-framework: gates, hooks, memory system, agent orchestration, skills, and the CLAUDE.md behavioral rules.

### 3. CROSS-REFERENCE — Check against existing knowledge
- `search_knowledge("[each key pattern found]", mode="all")` — find overlapping memories
- For any high-relevance hit (> 0.4): `get_memory(id)` to read the full entry
- Identify:
  - **Confirms**: Finding matches what we already knew (note convergence, no re-save needed)
  - **Extends**: Finding adds depth to existing knowledge (save as extension)
  - **Contradicts**: Finding conflicts with existing memory (flag to user, do NOT silently overwrite)
  - **New**: No related memory — save as fresh learning

### 4. SYNTHESIZE — Distill to actionable improvements
Produce a structured synthesis:

```
## Topic: [topic name]
### Source(s): [URLs or search terms]
### Date: [today's date]

**Core insight**: [1-2 sentence summary]

**Key findings**:
1. [Finding] — [why it matters to us]
2. ...

**Applicable to torus-framework**:
- [Specific area: gate / hook / memory / skill / orchestration]
  → [Concrete suggested change or adoption]

**Anti-patterns to avoid**:
- [What NOT to do, and why]

**Gaps / uncertainties**:
- [What couldn't be verified, what needs more research]
```

If the user used `--apply` flag or the findings clearly map to concrete improvements, proceed to step 5. Otherwise, present synthesis and ask: "Should I apply any of these as code changes?"

### 5. INTEGRATE — Apply improvements following The Loop
Only when the user approves (or `--apply` was given and changes are unambiguous):

For each proposed improvement:
1. **Plan Mode** — Enter plan mode, write out the specific file changes
2. **Approval** — Present the plan, wait for user confirmation
3. **Build** — Follow The Loop: read file → edit → test → prove
4. **Verify** — Run tests, show output
5. **Commit** — Stage and commit only when user asks

Gate discipline: all quality gates still apply. Do NOT skip Gate 1 (read before edit), Gate 3 (test before deploy), or Gate 5 (proof before fixed).

### 6. REMEMBER — Persist all findings
Save to memory regardless of whether code changes were made:

For each significant finding (new or extending):
```python
remember_this(
    content="[specific finding with enough detail to be useful standalone]",
    context="/learn on [topic] from [source URL or search]",
    tags="type:learning,priority:[high|medium|low],area:[framework|infra|backend|frontend],topic:[slug]"
)
```

Rules for what to save:
- Save **findings**, not just "I learned about X" — include the actual content
- One `remember_this` per distinct concept (don't bundle 5 ideas into 1 memory)
- Tag with `type:learning` always
- Tag with `area:framework` if it affects torus-framework internals
- If the finding influenced a code change, add `outcome:success` and reference the file changed

### 7. TEACH — Present a concise summary to the user
End with a clear, human-readable summary:

```
## What I Learned: [Topic]

**TL;DR**: [1-3 sentences]

**Key takeaways**:
1. [Takeaway]
2. [Takeaway]
3. [Takeaway]

**Saved to memory**: [N] entries tagged `type:learning`

**Applied**: [Yes — [N] files changed] | [No — findings saved for future reference]

**Suggested next steps** (optional):
- [If further research, code changes, or a PRP is warranted]
```

## Rules
- NEVER silently overwrite contradicting memory — flag conflicts to the user
- NEVER apply code changes without explicit approval (unless `--apply` was given AND the change is unambiguous)
- ALWAYS save at least one `remember_this` per /learn invocation, even if no new information was found (note what was confirmed)
- If a topic is too broad, break it into 3-5 focused sub-questions and research each
- If fetching fails (404, paywall, timeout), fall back to WebSearch and note the limitation
- Cap external fetches at 5 pages per /learn invocation to avoid token bloat — if more depth is needed, suggest `/research --depth deep`
- Tag memory saves consistently: `type:learning` is mandatory; add `area:*` and a topic slug for retrieval
- Cross-reference BEFORE saving — avoid duplicate memories on the same concept
- If `--apply` produces changes to gate files or memory_server.py, apply Gate 7 extra caution rules
