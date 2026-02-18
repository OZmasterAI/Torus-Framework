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

## QUALITY GATES (Enforced by hooks)
Gates checked by enforcer.py. Blocking = exit 2. Advisory = warn only.
**Blocking gates:**
- Gate 1: READ BEFORE EDIT — Must read .py files before editing
- Gate 2: NO DESTROY — Blocks rm -rf, DROP TABLE, force push, reset --hard
- Gate 3: TEST BEFORE DEPLOY — Must run tests before deploying
- Gate 4: MEMORY FIRST — Must query memory before editing
- Gate 5: PROOF BEFORE FIXED — Verify changes before making more
- Gate 7: CRITICAL FILE GUARD — Extra checks for high-risk files
- Gate 8: TEMPORAL AWARENESS — Extra caution during late-night hours
- Gate 9: STRATEGY BAN — Blocks proven-ineffective fix strategies
- Gate 10: MODEL COST GUARD — Blocks expensive model usage without justification
- Gate 11: RATE LIMIT — Blocks runaway tool call loops (rolling window)
- Gate 13: WORKSPACE ISOLATION — Prevents concurrent file edits across agents
- Gate 14: CONFIDENCE CHECK — Progressive readiness enforcement (3-strike escalation)
- Gate 15: CAUSAL CHAIN — Blocks edits after test failure until query_fix_history called

**Advisory gates** (warn only, never block):
- Gate 6: SAVE VERIFIED FIX — Warns when verified fixes not saved to memory
- Gate 12: PLAN MODE SAVE — Warns if exiting plan mode without saving to memory

## SESSION START (Non-Negotiable)
1. Read HANDOFF.md & LIVE_STATE.json
2. If previous state exists, present summary and ask: "Continue" or "New task"
3. "New task" → Archive HANDOFF.md, reset LIVE_STATE.json
4. "Continue" → Use handoff as context, pick up from "What's Next"
5. User's current instructions ALWAYS override handoff state

## SESSION HANDOFF
- HANDOFF.md — What was done, what's next, service status
- LIVE_STATE.json — Machine-readable project state
- Update both at session end (use /wrap-up)

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