# /wrap-up — Session End Protocol

## When to use
When the user says "wrap up", "done", "end session", "save progress", or is finishing work.

## Steps
1. **SAVE TO MEMORY** — remember_this() for every significant thing done this session:
   - Bugs fixed and how
   - Decisions made and why
   - New patterns discovered
   - Warnings for future sessions
1b. **PROMOTION CHECK** — Search memory for recurring patterns:
   - Query memory for `type:error` and `type:learning` entries
   - If any topic appears 3+ times across sessions, suggest promoting to CLAUDE.md as a new rule
   - Present promotion suggestions to user for approval before adding
   - Never auto-promote without explicit user consent
1c. **KNOWLEDGE TRANSFER** — Extract session learnings for the next session:
   - Use search_knowledge("type:learning") to find learning entries from this session
   - Extract the top 5 most relevant learnings (prioritize by recency and relevance)
   - Generate a "## Key Learnings" section with concise bullet points summarizing each
   - This section will be prepended to HANDOFF.md in the UPDATE HANDOFF step below
   - If no type:learning entries exist, note any significant decisions or fixes as learnings
1d. **CONTINUITY CHECK** — Verify session handoff readiness:
   - Check if HANDOFF.md was updated within the last 4 hours (stale = older than 4h)
   - Check if memories were saved this session (search_knowledge for recent timestamps)
   - Check for uncommitted git changes (`git status --porcelain`)
   - Display risk indicators:
     - GREEN: All checks pass (handoff fresh, memories saved, git clean)
     - YELLOW: Stale handoff (>4h old) or uncommitted changes exist
     - RED: No memories saved this session (memory gap risk)
   - If YELLOW or RED, warn the user and suggest corrective actions before ending
2. **UPDATE HANDOFF** — Use the Write tool to update ~/.claude/HANDOFF.md with:
   - Session number (increment from previous)
   - What was done this session
   - What's next (prioritized)
   - Any active issues or warnings
   - Service/deployment status
3. **UPDATE LIVE STATE** — Use the Write tool to update ~/.claude/LIVE_STATE.json with:
   - Updated session count
   - Current active tasks
   - Known issues
   - Recent fixes
4. **GIT COMMIT** — If there are uncommitted changes:
   - `git add` relevant files
   - `git commit` with descriptive message
   - Do NOT push unless explicitly asked
5. **VERIFY** — Quick check:
   - No uncommitted changes (or intentionally left)
   - Memory saved
   - Handoff updated
   - State file current
6. **DISPLAY SUMMARY** — Show what was saved and what's queued for next session
