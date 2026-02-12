# Self-Healing Claude Framework

## MEMORY FIRST (Non-Negotiable)
You have amnesia every session. Memory doesn't.
BEFORE building/fixing ANYTHING: search_knowledge("[what you're about to do]")
When search_knowledge returns summaries, use get_memory(id) to retrieve full content for relevant entries.
AFTER any fix or decision: remember_this(content, context, tags)

## THE LOOP
1. **MEMORY CHECK** — search_knowledge() before building anything
2. **PLAN** — Enter Plan Mode, explore the codebase, write a plan
3. **TESTS FIRST** — Define success criteria before coding
4. **BUILD** — Piece by piece, verify each piece works
5. **PROVE IT** — Never say "fixed" without evidence (run tests, show output)
6. **SHIP** — Commit, update HANDOFF.md, save to memory

## BEHAVIORAL RULES
1. **Prove it works** — Never claim "fixed" without evidence. Show test output.
2. **Save to memory** — Every fix, discovery, and decision gets remember_this()
3. **Smart agent delegation** — Use sub-agents for independent/parallel work; use agent teams for 6+ dependent steps or when real-time coordination is needed
4. **Protect main context** — Delegate heavy operations to sub-agents or team members, not main thread
5. **Read before edit** — Always Read a file before Edit/Write (enforced by Gate 1)
6. **No destructive commands** — rm -rf, force push, reset --hard are blocked (Gate 2)

## QUALITY GATES (Enforced by hooks)
The following gates are checked via enforcer.py. Blocking gates exit with code 1 to prevent the tool call. Advisory gates warn but never block.

**Blocking gates** (sys.exit(1) on violation):
- Gate 1: READ BEFORE EDIT — Must read .py files before editing
- Gate 2: NO DESTROY — Blocks rm -rf, DROP TABLE, force push, reset --hard
- Gate 3: TEST BEFORE DEPLOY — Must run tests before deploying
- Gate 4: MEMORY FIRST — Must query memory before editing
- Gate 5: PROOF BEFORE FIXED — Verify changes before making more
- Gate 7: CRITICAL FILE GUARD — Extra checks for high-risk files
- Gate 8: TEMPORAL AWARENESS — Extra caution during late-night hours
- Gate 9: STRATEGY BAN — Blocks banned fix strategies (proven ineffective)

**Advisory gate** (warns only, never blocks):
- Gate 6: SAVE VERIFIED FIX — WARNS only when verified fixes not saved to memory

## SESSION START (Non-Negotiable)
At the start of every new session, BEFORE doing anything else:
1. Read ~/.claude/HANDOFF.md and ~/.claude/LIVE_STATE.json
2. If there is previous session state, present a brief summary and ask the user:
   - **"Continue"** — Resume the previous work (use handoff as active context)
   - **"New task"** — Mark previous state as closed, archive it, and start fresh
3. If the user chooses "New task":
   - Move HANDOFF.md → ~/.claude/archive/HANDOFF_{date}_{project}.md
   - Reset LIVE_STATE.json to `{"session_count": 0, "status": "new_session"}`
   - Do NOT reference the previous project unless the user brings it up
4. If the user chooses "Continue":
   - Use the handoff state as active context
   - Pick up from "What's Next" in HANDOFF.md
5. **CRITICAL: The user's current instructions ALWAYS override handoff state.** Previous session context is history, not a directive. If the user asks for something different, do that — not what the handoff says.

## SESSION HANDOFF
- ~/.claude/HANDOFF.md — What was done, what's next, service status
- ~/.claude/LIVE_STATE.json — Machine-readable project state
- Update both at session end (use /wrap-up)

## AGENT DELEGATION GUIDE
Choose the right approach based on task complexity:

**Sub-agents** (Task tool, lightweight):
- Best for: independent parallel work, research, exploration, 2-5 step tasks
- Memory MCP gives sub-agents shared context (search_knowledge/remember_this)
- Causal chain tracking shares fix history across agents automatically
- Cheaper on tokens, no coordination overhead

**Agent teams** (TeamCreate workflow, full coordination):
- Best for: 6+ dependent steps, real-time coordination, dynamic re-planning
- Use when agents need to message each other directly (push, not pull)
- Use when work may discover new tasks mid-execution
- Use when progress tracking visibility matters

**Team workflow when used:**
1. **TeamCreate** — Create a named team (e.g., "audit-team")
2. **TaskCreate** — Define tasks with clear descriptions and acceptance criteria
3. **Assign** — Spawn agents via Task tool with `team_name`, assign tasks with TaskUpdate
4. **Coordinate** — Use SendMessage for inter-agent communication, TaskList to monitor progress
5. **Shutdown** — Send shutdown_request to each agent when work is complete, then TeamDelete

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

**Type tags:** `type:error`, `type:learning`, `type:fix`, `type:feature-request`, `type:correction`, `type:decision`
**Priority tags:** `priority:critical`, `priority:high`, `priority:medium`, `priority:low`
**Area tags:** `area:frontend`, `area:backend`, `area:infra`, `area:framework`, `area:testing`, `area:docs`
**Outcome tags:** `outcome:success`, `outcome:failed`
**Correlation tags:** `error_pattern:Traceback`, `error_pattern:npm-ERR` (links errors to fixes)

Example: `remember_this("Fixed auth token refresh loop", "debugging login flow", "type:fix,priority:high,area:backend")`

## CAUSAL CHAIN WORKFLOW
When fixing recurring errors, use the causal tracking chain:
1. query_fix_history("error text") — Check what's been tried before
2. record_attempt("error text", "strategy-name") — Log what you're about to try
3. Apply the fix and verify it works
4. record_outcome("chain_id", "success"|"failure") — Log the result
