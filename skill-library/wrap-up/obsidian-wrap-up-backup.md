3.5. **VAULT SESSION NOTE** — If `~/vault/sessions/` exists:
   - **Session number**: For project sessions, read from `.claude-state.json` in the project dir (project-local count). For framework sessions, read from `LIVE_STATE.json` (global count). NEVER use the global count for project sessions.
   - **Filename**: `YYYY-MM-DD-session-NNN.md` for framework, `YYYY-MM-DD-session-NNN-project-slug.md` for projects (e.g. `session-053-go-sdk-agent.md`)
   - Frontmatter: type, tags, created, status, project, feature, session_number, duration, tools_used, files_modified
   - Body: What Was Done, Decisions, Known Issues, Next Steps (from LIVE_STATE + conversation)
   - If write fails, warn and continue — never block wrap-up
