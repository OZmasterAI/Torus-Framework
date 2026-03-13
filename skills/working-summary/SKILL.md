# /working-summary — Write Context Summary Before Compaction

## When to use
Triggered automatically when context reaches ~65% threshold, or manually
when the user says "working summary", "write summary", "save context".

## Steps
1. **GATHER CONTEXT** — Review the current conversation:
   - What was the original goal/task?
   - What approach was chosen and why?
   - What progress has been made? What's done vs in-progress?
   - What key files were read or modified?
   - What errors/gotchas were encountered?
   - What decisions were made and their rationale?

2. **WRITE SUMMARY** — Write `~/.claude/rules/working-summary.md` with this structure:

   # Working Summary (Claude-written at context threshold)

   ## Goal
   [1-2 sentences: what the user asked for]

   ## Approach
   [2-3 sentences: chosen strategy and why]

   ## Progress
   ### Completed
   - [bullet list of completed items with file:line references]
   ### In Progress
   - [current task and its state]
   ### Remaining
   - [ordered list of what's left]

   ## Key Files
   - [file paths with 1-line description of role/changes]

   ## Decisions & Rationale
   - [decision]: [why, what alternatives were rejected]

   ## Gotchas & Errors
   - [things that went wrong, workarounds found]

   ## Next Steps (post-compaction)
   - [ordered priority list of what to do next]

3. **VERIFY SIZE** — Check that the written file is 2000-10000 chars (500-2500 tokens).
   If under 2000 chars, add more detail. If over 10000 chars, trim to essentials.

4. **CONFIRM** — Print: "[WORKING SUMMARY] Written (N chars). Context preserved for compaction."
