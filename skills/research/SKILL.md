# /research — Structured Research with Memory Integration

## When to use
When the user says "research", "look into", "investigate", "find out about", "what is", or needs to gather information before making a decision.

## Depth Tiers
Use `--depth <tier>` to set research intensity (default: standard):
| Tier | Agents | Hops | Time | Use Case |
|------|--------|------|------|----------|
| quick | 0 (direct) | 0 | ~30s | Simple factual lookups |
| standard | 2-4 | 1 | 2-5min | General research (default) |
| deep | 4-6 | 2 | 5-10min | Comprehensive investigation |
| exhaustive | 6+ team | 3 | 10-20min | Full academic-level research |

## Hop Patterns (for deep/exhaustive)
- **entity-expansion**: X → related entities → explore each (Company → Products → Competitors)
- **temporal**: current state → recent changes → historical context → future implications
- **conceptual-deepening**: overview → details → examples → edge cases → limitations
- **causal-chains**: observation → immediate cause → root cause → fix options

## Steps
1. **MEMORY CHECK** — search_knowledge("[topic]", top_k=50) for existing knowledge on the topic:
   - Check what we already know before searching externally
   - `search_knowledge("[topic]", mode="all")` for related past observations
   - If sufficient knowledge exists, present it and ask if deeper research is needed
2. **SCOPE** — Define 3-5 specific research questions:
   - Break the broad topic into focused, answerable questions
   - Prioritize questions by impact on the user's decision
   - Present the research plan to the user for confirmation
3. **GATHER** — Launch sub-agents based on depth tier (quick: direct calls, standard: 2-4, deep: 4-6 with hop patterns, exhaustive: 6+ team with multi-hop):
   - **Web researcher**: WebSearch + WebFetch for online sources (docs, articles, comparisons)
   - **Codebase explorer**: Glob + Grep + Read for relevant local code, patterns, and dependencies
   - **Memory miner**: search_knowledge (mode="all" for observations too) for past decisions and learnings
   - Each agent targets specific research questions from Step 2
4. **SYNTHESIZE** — Combine findings into a structured report:
   - **Key Findings**: Direct answers to each research question
   - **Evidence**: Links, code references, and memory entries supporting each finding
   - **Gaps**: Questions that couldn't be fully answered
   - **Recommendations**: Actionable next steps based on findings
   - **Trade-offs**: Pros/cons if comparing options
5. **SAVE** — remember_this() for each significant finding:
   - Tag with "type:learning" and relevant area tags
   - Save key decisions and their rationale
   - Save links to important resources for future reference
6. **PRESENT** — Display formatted report to user:
   - Use clear markdown headings and bullet points
   - Highlight the most important findings
   - End with a clear recommendation or set of options
