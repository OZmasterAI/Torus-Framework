# Torus-Framework

## MEMORY FIRST (Non-Negotiable)
BEFORE building/fixing ANYTHING: search_knowledge("[what you're about to do]")
- \> 0.5 relevance: use directly | 0.2-0.5: get_memory(id) to verify | < 0.2: treat as unknown
AFTER any fix/decision/failed-approach/user-preference: remember_this(content, context, tags)
For ERROR FIX: use the Causal Chain (below) then remember_this()

## THE LOOP
memory check → plan → tests first → build → prove it → track → ship

## CAUSAL CHAIN WORKFLOW
When fixing errors, follow ALL 5 steps:
1. query_fix_history("error text")
2. record_attempt("error text", "strategy-name")
3. Fix and verify with tests
4. record_outcome("chain_id", "success"|"failure")
5. remember_this("Fixed [error] using [strategy]", ..., "type:fix")

## BEHAVIORAL RULES
1. **Prove it works** — Never claim "fixed" without evidence. Show test output.
2. **Save to memory** — Every fix, discovery, and decision gets remember_this()
3. **Protect main context** — Delegate heavy operations to sub-agents
4. **Plan mode discipline** — Never write code in plan mode. enter plan → explore + write plan → ExitPlanMode → approval → implement. If rejected, ask what's wrong. Max 1 ExitPlanMode per turn.
5. **Never guess** — Never assume file paths, branch state, or system state. Read/Glob/search_knowledge first. If you haven't verified it, you don't know it.
6. **Model selection** — Gate 10 enforces model_profile from config.json. Do not override. Do not specify haiku unless the profile allows it.

## SESSION START (Non-Negotiable)
1. Read HANDOFF.md & LIVE_STATE.json
2. If previous state exists, present summary and ask: "Continue" or "New task"
3. "New task" → Archive HANDOFF.md, reset LIVE_STATE.json
4. "Continue" → Use handoff as context, pick up from "What's Next"
5. User's current instructions ALWAYS override handoff state

## AGENT DELEGATION
- Memory MCP gives sub-agents shared context; causal chain shares fix history automatically
- 2-5 steps, independent → Sub-agents (parallel)
- 2-5 steps, dependent → Sub-agents (lead orchestrates, memory bridges)
- 5-7 steps → Either (teams preferred)
- 7+ steps → Agent teams (real-time coordination)
- Cross-session → Sub-agents + memory

## FRUSTRATION SIGNALS (stop and verify):
- "again" — Repeating a mistake. Query memory.
- "still" — Fix didn't work. Prove it this time.
- "why" — Unexpected behavior. Investigate deeper.
- ALL CAPS — Important point missed. Re-read carefully.

## MEMORY TAG CONVENTIONS
Tags: type (error, learning, fix, feature-request, correction, decision, auto-captured, preference) | priority (critical, high, medium, low) | area (frontend, backend, infra, framework, testing, docs, git) | outcome (success, failed) | error_pattern (Traceback, npm-ERR)
