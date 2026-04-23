# /wrap-up — Session End Protocol

## When to use
When the user says "wrap up", "done", "end session", "save progress", or is finishing work.

## Steps
1. **GATHER** — Run `python3 ~/.claude/skill-library/wrap-up/scripts/gather.py` and parse the JSON output
   - If script fails, fall back to manual: read project state file (use detect_project() to find it — see step 3), git status, search_knowledge
   - The JSON contains: live_state, handoff (content + age), git status, memory count, promotion_candidates, recent_learnings, risk_level, warnings
2. **SAVE TO MEMORY** — Based on gathered data + conversation context, remember_this() for significant work:
   - Bugs fixed and how
   - Decisions made and why
   - New patterns discovered
   - Warnings for future sessions
   - Use promotion_candidates from gathered data to check for recurring patterns
   - If any topic appears 3+ times, suggest promoting to CLAUDE.md as a new rule
   - Present promotion suggestions to user for approval — never auto-promote
<!-- 3.5. UPDATE WIKI — disabled, re-enable when ready
   Read ~/vault/wiki/_index.md. For each topic touched this session, invoke wiki-update.
   Use run_tool("skills-v2", "invoke_skill", {"name": "wiki-update"}) for guidance. -->
4. **UPDATE STATE** — Run `python3 -c "import sys; sys.path.insert(0, '$HOME/.claude/hooks'); from boot_pkg.util import detect_project; n,d,s,sd = detect_project(); print(sd or d or '')"` to detect project root. If it returns a path, write to `{path}/.claude-state.json`. If empty (framework/hub session), write to `~/.claude/LIVE_STATE.json`. This covers `~/projects/`, `~/agents/`, and `~/worktrees/` automatically. In your summary message, say "State saved to .claude-state.json" (for projects) or "State saved to LIVE_STATE.json" (for framework hub) — use the correct name for whichever file you actually wrote to. Write with:
   - Updated session count
   - `feature` — short keyword tag for current work area (e.g. "session-isolation", "github-sync", "none")
   - `what_was_done` — max ~200 chars, action verbs only, no metrics/explanations (full details go to remember_this)
   - `framework_version` — current version string (e.g. "v2.5.3")
   - known_issues (carry forward + any new ones)
   - next_steps (reprioritized by Claude)
   - Do NOT write improvements_shipped, files_modified, or dormant_agent_teams — those are historical and belong in memory/git only
5. **GIT COMMIT** — If gathered git.clean is false:
   - `git add` relevant files
   - `git commit` with descriptive message
   - Do NOT push unless explicitly asked
6. **VERIFY** — Check risk_level from gathered data:
   - GREEN: Proceed to summary
   - YELLOW: Warn user about stale state or uncommitted changes
   - RED: Warn user about memory gaps — suggest corrective actions
7. **DISPLAY SUMMARY** — Show what was saved and what's queued for next session
