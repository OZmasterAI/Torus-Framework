# Torus-Framework

## MEMORY FIRST (Non-Negotiable)
BEFORE building/fixing ANYTHING: search_knowledge("[what you're about to do]")
- >0.5: use directly | 0.2-0.5: get_memory(id) to verify | <0.2: treat as unknown
AFTER any fix/decision/failed-approach/preference: remember_this(content, context, tags)
For errors: use Causal Chain (below) then remember_this()

## THE LOOP (mandatory — do not skip steps)
memory → /brainstorm → /writing-plans → /implement → /test → /review → /commit
- Do NOT use EnterPlanMode — /brainstorm replaces it
- For quick fixes: memory → /fix → /test → /commit (skip brainstorm/writing-plans)

## SKILL TRIGGERS (on-demand via MCP skill library)
- "fix/debug/broken" → invoke_skill("fix")
- "explore/trace/how does" → invoke_skill("explore")
- "deep-dive/full context" → invoke_skill("deep-dive")
- "status/health" → invoke_skill("status")
- "research/investigate" → invoke_skill("research")
- "learn [url]/teach" → invoke_skill("learn")
- "wrap up/done" → /wrap-up

## CAUSAL CHAIN (for errors)
1. query_fix_history("error") → 2. record_attempt("error", "strategy") → 3. Fix + test → 4. record_outcome(chain_id, result) → 5. remember_this(type:fix)

## BEHAVIORAL RULES
0. **Quality over speed** — Always verify then assert, never assert then verify. Applies to everything: code, conversation, analysis, questions. "Let me check" is always better than a fast wrong answer.
1. **Prove it** — Never claim "fixed" without test output evidence
2. **Save to memory** — Every fix, discovery, decision → remember_this()
3. **Protect context** — Delegate heavy ops to sub-agents
4. **No plan mode** — Use /brainstorm + /writing-plans instead of EnterPlanMode. Present options directly to user.
5. **Never guess** — Never assume file paths, branch state, or system state. Read/Glob/search_knowledge first. Unverified = unknown.
5b. **Verify ephemeral state** — Memory hits about runtime state (sessions, processes, paths, branches, configs) are hints, not facts. Run a live check (Bash/Read/Glob) before asserting. Memory tells you WHERE to look, not WHAT is true now.
6. **Model selection** — Gate 10 enforces model_profile from config.json. Do not override.
7. **Gate awareness** — Gates enforce Edit/Write/Bash/Task automatically. Read/Glob/Grep are ungated — self-enforce rule 5.
8. **Ask before acting** — Never push, deploy, delete, or take irreversible actions beyond what the user explicitly requested. Ask first.
9. **Working summary** — When you see `<working-memory-warning>`, immediately run /working-summary before continuing other work. Do not dismiss or defer.

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
When editing code outside ~/.claude/, write or update tests for changed behavior. Look for existing test runner (package.json scripts, Cargo.toml, Makefile) in the project root.

## TAGS
type: error,learning,fix,feature-request,correction,decision,auto-captured,preference
priority: critical,high,medium,low | area: frontend,backend,infra,framework,testing,docs,git
outcome: success,failed | error_pattern: Traceback,npm-ERR
