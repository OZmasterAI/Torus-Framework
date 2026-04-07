# Torus-Framework

## TOOLSHED (single MCP gateway)
All tools route through toolshed: `run_tool(server, tool, args)`
- **memory**: search_knowledge, get_memory, remember_this, fuzzy_search, record_attempt, record_outcome, query_fix_history, health_check, agent_coordination
- **skills-v2**: list_skills, invoke_skill, search_skills, self_improve, skill_usage, skill_health, record_outcome, trigger_evolution, capture_skill, skill_lineage
- **search**: terminal_history_search, transcript_context
- **web-search**: web_search
- Discovery: `list_tools(group="memory")` to see tools in a group

## MEMORY FIRST (Non-Negotiable)
BEFORE building/fixing ANYTHING: `run_tool("memory", "search_knowledge", {"query": "..."})`
- >0.5: use directly | 0.2-0.5: get_memory(id) to verify | <0.2: treat as unknown
AFTER any fix/decision/failed-approach/preference: `run_tool("memory", "remember_this", {"content": "...", "tags": "..."})`
For errors: use Causal Chain (below) then remember_this()

## THE LOOP (mandatory — do not skip steps)
memory → brainstorm → writing-plans → implement → test → review → commit
- All steps are toolshed skills: `run_tool("skills-v2", "invoke_skill", {"name": "brainstorm"})`, etc.
- Do NOT use EnterPlanMode — brainstorm replaces it
- For quick fixes: memory → fix → test → commit (skip brainstorm/writing-plans)

## SKILLS (via toolshed MCP — NOT the built-in Skill tool)
**NEVER use the Skill tool for framework skills** (brainstorm, commit, wrap-up, etc.)
The built-in Skill tool is ONLY for: update-config, simplify, loop, schedule, claude-api, keybindings-help.
All framework skills route through: `run_tool("skills-v2", "invoke_skill", {"name": "..."})`
Discovery: `run_tool("skills-v2", "search_skills", {"query": "..."})`

## CAUSAL CHAIN (for errors)
1. `run_tool("memory", "query_fix_history", {"error_text": "..."})` → 2. record_attempt → 3. Fix + test → 4. record_outcome → 5. remember_this(type:fix)

## BEHAVIORAL RULES
0. **Quality over speed** — Always verify then assert, never assert then verify. Applies to everything: code, conversation, analysis, questions. "Let me check" is always better than a fast wrong answer.
1. **Prove it** — Never claim "fixed" without test output evidence
2. **Save to memory** — Every fix, discovery, decision → remember_this()
3. **Protect context** — Delegate heavy ops to sub-agents
4. **No plan mode** — Use toolshed brainstorm + writing-plans skills instead of EnterPlanMode. Present options directly to user.
5. **Never guess** — Never assume file paths, branch state, or system state. Read/Glob/search_knowledge first. Unverified = unknown.
5b. **Verify ephemeral state** — Memory hits about runtime state (sessions, processes, paths, branches, configs) are hints, not facts. Run a live check (Bash/Read/Glob) before asserting. Memory tells you WHERE to look, not WHAT is true now.
6. **Model selection** — Gate 10 enforces model_profile from config.json. Do not override.
7. **Gate awareness** — Gates enforce Edit/Write/Bash/Task automatically. Read/Glob/Grep are ungated — self-enforce rule 5.
8. **Ask before acting** — Never push, deploy, delete, or take irreversible actions beyond what the user explicitly requested. Ask first.
9. **Working summary** — When you see `[# WARNING # CONTEXT` in tool output, immediately run `run_tool("skills-v2", "invoke_skill", {"name": "working-summary"})` before continuing other work. Do not dismiss or defer.

## SESSION START (Non-Negotiable)
1. Read LIVE_STATE.json
2. Previous state → present summary, ask "Continue" or "New task"
3. New → archive handoff, reset state | Continue → pick up from "What's Next"
4. User's current instructions ALWAYS override handoff state

## AGENT DELEGATION
- Memory MCP + causal chain bridge sub-agents automatically
- 2-5 independent → parallel | 2-5 dependent → lead orchestrates
- 5-7 steps → either (teams preferred) | 7+ → agent teams
- Cross-session → agents + memory

## FRUSTRATION SIGNALS (stop and verify):
- "again" → query memory | "still" → prove it | "why" → investigate | ALL CAPS → re-read

## TESTING RULE
When editing code, write or update tests for changed behavior. Look for existing test runner (package.json scripts, Cargo.toml, Makefile, test_framework.py) in the project root.

## OBSIDIAN VAULT
- Vault at ~/vault — human-readable knowledge layer
- Use `obsidian search query="topic" format=json` when:
  - Starting work on a topic
  - Looking for past decisions/research
  - User asks "what do we know about X"
- Use `obsidian daily:append content="..."` for notable events
- Prefer CLI when Obsidian running, MCP tools when CLI fails
- Session notes auto-written by wrap-up skill and session_end.py — no manual action needed

## TAGS
type: error,learning,fix,feature-request,correction,decision,auto-captured,preference
priority: critical,high,medium,low | area: frontend,backend,infra,framework,testing,docs,git
outcome: success,failed | error_pattern: Traceback,npm-ERR
