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
