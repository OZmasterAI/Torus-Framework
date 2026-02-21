# /teach — Framework Knowledge Transfer

## When to use
When user says "teach", "explain framework", "onboard", "how does this work",
"tutorial", "walk me through", or wants a structured overview of the Torus framework.

## Commands
- `/teach` — Full framework tutorial
- `/teach architecture` — Deep-dive on architecture only
- `/teach patterns` — Key patterns and conventions
- `/teach pitfalls` — Common mistakes and how to avoid them
- `/teach $ARGUMENTS` — Focus on a specific area (e.g., "gates", "memory", "agents")

## Flow

### Phase 1: INVENTORY
Query memory for high-value patterns:
```python
search_knowledge("type:learning", top_k=30)
search_knowledge("type:fix", top_k=20)
search_knowledge("type:decision", top_k=20)
```
Count entries by category:
- Architectural decisions
- Key patterns / conventions
- Common pitfalls / fixes
- Best practices

### Phase 2: CURATE
Select the 10 most important entries by:
1. Relevance to requested topic (or all topics if no argument)
2. Recency (prefer entries from last 10 sessions)
3. Tag priority: `priority:critical` > `priority:high` > `priority:medium`
4. Outcome: prefer `outcome:success` entries

For each selected entry, call `get_memory(id)` to retrieve full content.
Note the memory ID for citation.

### Phase 3: FORMAT
Structure the tutorial as markdown with these sections:

```markdown
## Architecture
Overview of how the framework is organized: gates, hooks, memory, agents, skills.
Reference key files: enforcer.py, memory_server.py, CLAUDE.md.

## Key Patterns
The recurring conventions every contributor must know:
- Memory-first workflow
- The Loop (memory → plan → test → build → prove → ship)
- Gate contracts and exit codes
- Agent delegation rules

## Common Pitfalls
Mistakes that have burned us before (cited from fix memory):
- [pitfall] — [memory_id] — [how to avoid]

## Best Practices
Proven approaches (cited from decision/learning memory):
- [practice] — [memory_id] — [why it matters]
```

### Phase 4: DELIVER
Present the tutorial in clear markdown.
After each section, offer: "Want me to deep-dive on [section]?"

End with:
```
## Summary
Covered: [N] key patterns, [M] common pitfalls, [K] best practices
Memory sources: [list of memory IDs cited]

Ask me to `/teach [topic]` to go deeper on any section.
```

Save the teaching session to memory:
```python
remember_this(
    content="Teaching session: [topic covered]. Key concepts: [list]. Memory IDs cited: [list].",
    context="/teach invocation",
    tags="type:learning,teach,area:framework,priority:medium"
)
```

## Rules
- Read-only skill — never modify files
- Always cite memory IDs for every claim (format: `[mem-id]`)
- If fewer than 5 relevant memories exist, supplement with direct file reads
- Save every teaching session to memory with `type:learning,teach` tags
- Never invent framework behavior — only teach what is in memory or source files
- If user asks about a specific file, read it and teach from source
- Maximum 10 curated memories per invocation to keep output focused
