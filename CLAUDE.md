# Torus-Framework

## MEMORY FIRST (Non-Negotiable)
BEFORE building/fixing ANYTHING: search_knowledge("[what you're about to do]")
- >0.5: use directly | 0.2-0.5: get_memory(id) to verify | <0.2: treat as unknown
AFTER any fix/decision/failed-approach/preference: remember_this(content, context, tags)
For errors: use Causal Chain (below) then remember_this()

## THE LOOP
memory check → plan → tests first → build → prove it → track → ship

## CAUSAL CHAIN (for errors)
1. query_fix_history("error") → 2. record_attempt("error", "strategy") → 3. Fix + test → 4. record_outcome(chain_id, result) → 5. remember_this(type:fix)

## BEHAVIORAL RULES
1. **Prove it** — Never claim "fixed" without test output evidence
2. **Save to memory** — Every fix, discovery, decision → remember_this()
3. **Protect context** — Delegate heavy ops to sub-agents
4. **Plan mode** — Never write code in plan mode. explore + plan → ExitPlanMode → approval → implement. If rejected, ask what's wrong. Max 1 ExitPlanMode per turn.
5. **Never guess** — Never assume file paths, branch state, or system state. Read/Glob/search_knowledge first. Unverified = unknown.
6. **Model selection** — Gate 10 enforces model_profile from config.json. Do not override.
7. **Gate awareness** — Gates enforce Edit/Write/Bash/Task automatically. Read/Glob/Grep are ungated — self-enforce rule 5.

## SESSION START (Non-Negotiable)
1. Read HANDOFF.md & LIVE_STATE.json
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

## TAGS
type: error,learning,fix,feature-request,correction,decision,auto-captured,preference
priority: critical,high,medium,low | area: frontend,backend,infra,framework,testing,docs,git
outcome: success,failed | error_pattern: Traceback,npm-ERR
