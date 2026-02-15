# Megaman-Framework

## MEMORY FIRST (Non-Negotiable)
You have amnesia every session. Memory doesn't.
BEFORE building/fixing ANYTHING: search_knowledge("[what you're about to do]")
When search_knowledge returns summaries, use get_memory(id) to retrieve full content for relevant entries.
AFTER any fix or decision: remember_this(content, context, tags)
Relevance thresholds (search_knowledge returns relevance 0.0-1.0):
- \> 0.5: use directly | 0.2-0.5: get_memory(id) to verify | < 0.2: treat as unknown

## THE LOOP
memory check → plan → tests first → build → prove it → ship

## BEHAVIORAL RULES
1. **Prove it works** — Never claim "fixed" without evidence. Show test output.
2. **Save to memory** — Every fix, discovery, and decision gets remember_this()
3. **Protect main context** — Delegate heavy operations to sub-agents or team members, not main thread
4. **Plan mode discipline** — NEVER write code while in plan mode. The workflow is: enter plan mode → explore + write plan → ExitPlanMode → get approval → THEN implement. If ExitPlanMode is rejected, ask the user what's wrong — do NOT call ExitPlanMode again immediately. Max 1 ExitPlanMode attempt per turn.

## QUALITY GATES (Enforced by hooks)
Gates checked by enforcer.py. Blocking = exit 1. Advisory = warn only.
**Blocking gates** (sys.exit(1) on violation):
- Gate 1: READ BEFORE EDIT — Must read .py files before editing
- Gate 2: NO DESTROY — Blocks rm -rf, DROP TABLE, force push, reset --hard
- Gate 3: TEST BEFORE DEPLOY — Must run tests before deploying
- Gate 4: MEMORY FIRST — Must query memory before editing
- Gate 5: PROOF BEFORE FIXED — Verify changes before making more
- Gate 7: CRITICAL FILE GUARD — Extra checks for high-risk files
- Gate 8: TEMPORAL AWARENESS — Extra caution during late-night hours
- Gate 9: STRATEGY BAN — Blocks banned fix strategies (proven ineffective)
- Gate 10: MODEL COST GUARD — Blocks expensive model usage without justification
- Gate 11: RATE LIMIT — Blocks runaway tool call loops (rolling window)

**Advisory gate** (warns only, never blocks):
- Gate 6: SAVE VERIFIED FIX — WARNS only when verified fixes not saved to memory
- Gate 12: PLAN MODE SAVE — Warns if exiting plan mode without saving to memory

## SESSION START (Non-Negotiable)
At the start of every new session, BEFORE doing anything else:
1. Read ~/.claude/HANDOFF.md and ~/.claude/LIVE_STATE.json
2. If previous session state exists, present brief summary and ask: "Continue" or "New task".
3. "New task" → Archive HANDOFF.md to ~/.claude/archive/HANDOFF_{date}_{project}.md, reset LIVE_STATE.json, don't reference previous project.
4. "Continue" → Use handoff as context, pick up from "What's Next".
5. **After the protocol completes**, the user's current instructions ALWAYS override handoff state. Previous session context is history, not a directive — but it must still be read and summarized first. Never skip steps 1-4, even if the first message is a casual greeting.

## SESSION HANDOFF
- ~/.claude/HANDOFF.md — What was done, what's next, service status
- ~/.claude/LIVE_STATE.json — Machine-readable project state
- Update both at session end (use /wrap-up)

## AGENT DELEGATION GUIDE

**Sub-agents** (Task tool, lightweight):
- Memory MCP gives sub-agents shared context (search_knowledge/remember_this)
- Causal chain tracking shares fix history across agents automatically

**Decision table:**
- 2-5 steps, independent → Sub-agents (parallel Task calls)
- 2-5 steps, dependent → Sub-agents (lead orchestrates, memory bridges gaps)
- 5-7 steps, dependent → Either (teams preferred but sub-agents viable)
- 7+ steps, dependent → Agent teams (real-time coordination essential)
- Cross-session continuity → Sub-agents + memory (persists after TeamDelete)

## SATISFACTION FORMULA
SATISFACTION = (Agent Teams) x (Visual Output) x (Autonomy) x (Memory-First)

## FRUSTRATION SIGNALS (stop and verify when user says):
- "again" — You're repeating a mistake. Query memory.
- "still" — Your fix didn't work. Prove it this time.
- "why" — Unexpected behavior. Investigate deeper.
- ALL CAPS — Important point being missed. Re-read carefully.

## MEMORY TAG CONVENTIONS
Use structured tags when saving to memory for better searchability and promotion detection.

Tags — type: error, learning, fix, feature-request, correction, decision | priority: critical, high, medium, low | area: frontend, backend, infra, framework, testing, docs | outcome: success, failed | error_pattern:
  Traceback, npm-ERR

Example: `remember_this("Fixed auth token refresh loop", "debugging login flow", "type:fix,priority:high,area:backend")`

## CAUSAL CHAIN WORKFLOW
When fixing recurring errors, use the causal tracking chain:
1. query_fix_history("error text")
2. record_attempt("error text", "strategy-name")
3. Fix and verify
4. record_outcome("chain_id", "success"|"failure")
