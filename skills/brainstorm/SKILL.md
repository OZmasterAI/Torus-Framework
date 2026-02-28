# /brainstorm — Design Exploration & Option Generation

## When to use
When the user says "brainstorm", "design", "think through", "options for",
"how should we", or needs to explore approaches before implementing.
Replaces EnterPlanMode for non-trivial features.

## Steps

### 1. MEMORY CHECK
- search_knowledge("[topic]") — prior art, known issues, past decisions
- search_knowledge("[topic]", mode="all") — include observations
- If relevant history exists, present it as context before exploring

### 2. EXPLORE
- Read relevant source files, understand existing patterns
- Grep for related implementations, imports, dependencies
- Map the affected area: what files, what APIs, what tests exist
- Identify constraints: framework rules, gate requirements, dependencies

### 3. DESIGN OPTIONS
Generate 2-3 distinct approaches. For each option:
- **Name**: Short descriptive label (e.g., "Gate-based approach")
- **How it works**: 3-5 sentences explaining the mechanism
- **Files affected**: List of files to create/modify
- **Trade-offs**: Pros and cons (be honest, not salesy)
- **Effort**: Small / Medium / Large
- **Risk**: Low / Medium / High

### 4. RECOMMEND
- State which option you recommend and why (1-2 sentences)
- Flag any unknowns or questions that could change the recommendation

### 5. SAVE DESIGN DOC
Write the design doc to docs/plans/<feature-slug>.md with this structure:

  # Design: <Feature Name>
  ## Problem
  ## Context (from memory + exploration)
  ## Options
  ### Option A: ...
  ### Option B: ...
  ### Option C: ...
  ## Recommendation
  ## Open Questions

Also present the options inline in chat for immediate review.

### 6. SAVE TO MEMORY
- remember_this("Design: [feature] — [recommended option summary]",
  "[context]", "type:decision,area:[relevant]")

## Output
- Design doc saved to docs/plans/<feature-slug>.md
- Options presented inline for user review
- User picks an option, then runs /writing-plans to get TDD implementation plan
