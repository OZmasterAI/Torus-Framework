# Torus-Framework

## MEMORY FIRST (Non-Negotiable)
BEFORE building/fixing: search_knowledge("[topic]")
- >0.5: use directly | 0.2-0.5: get_memory(id) to verify | <0.2: unknown
AFTER any fix/decision/failed-approach/preference: remember_this(content, context, tags)

## THE LOOP
memory check → plan → tests first → build → prove it → track → ship

## CAUSAL CHAIN (for errors)
1. query_fix_history("error") → 2. record_attempt("error", "strategy") → 3. Fix + test → 4. record_outcome(chain_id, result) → 5. remember_this(type:fix)

## FORMATTING
- Max 200 chars/line. No box-drawing tables. Use bullet lists for summaries.

## RULES
1. **Prove it** — Never claim "fixed" without test output
2. **Save to memory** — Every fix, discovery, decision → remember_this()
3. **Protect context** — Delegate heavy ops to sub-agents
4. **Plan mode discipline** — Never write code in plan mode. enter plan → explore + write plan → ExitPlanMode → approval → implement. If rejected, ask what's wrong. Max 1 ExitPlanMode per turn.

## SESSION START (Non-Negotiable)
1. Read HANDOFF.md & LIVE_STATE.json
2. Previous state → present summary, ask "Continue" or "New task"
3. New → archive handoff, reset state | Continue → pick up from "What's Next"
4. User's current instructions ALWAYS override handoff state

## DELEGATION
- Memory MCP + causal chain bridge sub-agents automatically
- 2-5 independent → parallel agents | 2-5 dependent → lead orchestrates
- 5-7 steps → Either (teams preferred)
- 7+ steps → agent teams | Cross-session → agents + memory

## FRUSTRATION: "again"=query memory | "still"=prove it | "why"=investigate | ALL CAPS=re-read

## TAGS
type: error,learning,fix,feature-request,correction,decision,auto-captured,preference
priority: critical,high,medium,low | area: frontend,backend,infra,framework,testing,docs,git
outcome: success,failed | error_pattern: Traceback,npm-ERR
