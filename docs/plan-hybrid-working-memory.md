# Plan: Hybrid Working Memory

**Status:** Proposed
**Date:** 2026-03-12
**Session:** 421
**Context:** Option 3 (Hybrid) — stay on Claude Code, enhance context management via `rules/working-memory.md`

---

## Overview

A `rules/working-memory.md` file with three layers, each updating at a different cadence. Combines progressive accumulation (from Sapling's operation model) with a per-turn status line and a threshold-triggered expansion. Three triggers, three writers, one file.

## Core Mechanism

Three layers in one file, each with its own update trigger:

| Layer | Trigger | Size | Purpose |
|-------|---------|------|---------|
| **Base** | Every turn (UserPromptSubmit) | ~40 tokens | Current operation, active files, last outcome |
| **Accumulate** | On operation completion (PostToolUse) | +60-80 per op | Operation history, growing progressively |
| **Expand** | At `/clear` warning threshold | +200-350 tokens | Full decisions, causal chains, error context |

## Architecture

```
UserPromptSubmit hook                   PostToolUse hook
    │                                       │
    ├── Update BASE section                 ├── Detect operation boundary
    │   (~40 tokens, current status)        │   (same signals as Sapling)
    │                                       │
    ├── Check turn count against            ├── On boundary detected:
    │   threshold warning level             │   ├── Finalize operation
    │   │                                   │   ├── Generate template summary
    │   └── If threshold approaching:       │   ├── Append to ACCUMULATE section
    │       └── Write EXPAND section        │   ├── FIFO evict if > cap
    │          (decisions, errors, chains)   │   └── Update tracker state
    │                                       │
    └── Rewrite file with all sections      └── Rewrite file with all sections
```

## File Format

```markdown
# Working Memory (auto-generated — do not edit)

## Status
Active: [Op6: design] working-memory.md system | Files: rules/*.md
Last: [Op5: investigate] hook mechanics [success]

## Operations
- [Op1: explore] Session orient — MCP healthy, 8036 memories. [success]
- [Op2: explore] Retrieved Option 2 vs 3 from memory. [success]
- [Op3: explore] Deep Sapling research — 6 agents. 5-stage pipeline,
  no MCP, migration not viable. [success]
- [Op4: explore] 9 diagrams — Focus Agent pattern most relevant. [success]
- [Op5: investigate] Hook mechanics — CAN: modify rules/*.md. CANNOT:
  modify message array or system prompt. [success]

## Context (expanded at threshold)
### Key Decisions
- Option 3 (hybrid) confirmed — stay on Claude Code
- /clear preferred over /compact — working-memory.md = sole continuity
- Progressive growth with threshold expansion

### Causal Chain
- Op2 (research decision) → Op3 (deep research) → Op4 (diagram analysis)
  → Op5 (hook verification) → Op6 (design implementation)

### Unresolved
- (none)

### Files Modified This Session
- (none — research/design session)
```

## Growth Profile

```
 tokens in
 working-memory.md
      │
  800 ┤                                      ╭── cap
      │                                     ╱
  700 ┤                              ╭─────╱  EXPAND kicks in
      │                              │
  400 ┤                         ╱───╱
      │                       ╱        accumulate grows
  300 ┤                  ╱───╱
      │                ╱
  200 ┤           ╱───╱
      │         ╱
  100 ┤    ╱───╱
      │  ╱
   40 ┤─╱ (base only)
      └──────────────────────────────────────
       turn 1  Op1  Op2  Op3  Op4  Op5  threshold  /clear
```

- **Turn 1-4:** ~40 tokens (base only)
- **After Op1 (turn 5):** ~100 tokens (base + 1 op)
- **After Op2 (turn 6):** ~160 tokens (base + 2 ops)
- **During Op3 (turns 7-12):** ~160 tokens (base updates, ops stable)
- **After Op3 (turn 13):** ~220 tokens (base + 3 ops)
- **After Op4 (turn 14):** ~280 tokens (base + 4 ops)
- **After Op5 (turn 15):** ~340 tokens (base + 5 ops)
- **Turns 16-19:** ~340 tokens (base updates, ops stable)
- **Threshold (turn 20):** ~700 tokens (EXPAND section added)
- **After `/clear`:** File persists. ~700 tokens. Sole continuity source.

## Token Cost (21-turn session example)

| Phase | Turns | File size | Subtotal |
|-------|-------|-----------|----------|
| Pre-Op1 | 1-4 (4 turns) | 40 | 160 |
| After Op1 | 5 (1 turn) | 100 | 100 |
| After Op2 | 6 (1 turn) | 160 | 160 |
| During Op3 | 7-12 (6 turns) | 160 | 960 |
| After Op3 | 13 (1 turn) | 220 | 220 |
| After Op4 | 14 (1 turn) | 280 | 280 |
| After Op5 | 15 (1 turn) | 340 | 340 |
| During Op6 | 16-19 (4 turns) | 340 | 1,360 |
| Threshold | 20-21 (2 turns) | 700 | 1,400 |
| **Total** | **21 turns** | | **~4,980** |
| **Average** | | | **~237/turn** |

## Comparison vs Progressive

| Metric | Progressive | Hybrid |
|--------|------------|--------|
| Total tokens (21 turns) | ~4,810 | ~4,980 |
| Quality at turn 8 (`/clear`) | 150 tokens (Ops 1-2) | 160 tokens (Ops 1-2 + status) |
| Quality at turn 15 (`/clear`) | 430 tokens (Ops 1-5 + decisions) | 340 tokens (Ops 1-5 + status) |
| Quality at turn 20 (`/clear`) | 430 tokens | 700 tokens (expanded context) |
| Per-turn awareness | None between ops | Always (base updates every turn) |
| Threshold boost | None | +350 tokens of decisions/chains/errors |
| Implementation complexity | Simple (1 trigger) | Medium (3 triggers) |

## Three Layers Detailed

### Layer 1: Base (UserPromptSubmit, every turn)

```markdown
## Status
Active: [Op6: design] working-memory.md | Files: rules/*.md
Last: [Op5: investigate] hook mechanics [success]
```

~40 tokens. Updates the "Status" section only. Cheap, ensures Claude always knows current operation even between operation boundaries.

Implementation: UserPromptSubmit hook reads operation tracker state from ramdisk, writes two-line status section.

### Layer 2: Accumulate (PostToolUse, on operation boundary)

```markdown
## Operations
- [Op1: explore] Session orient — MCP healthy. [success]
- [Op2: explore] Retrieved Option 2 vs 3. [success]
...
```

+60-80 tokens per operation. Same boundary detection as Progressive plan (Sapling-inspired weighted heuristic). Same template format. Same FIFO eviction at section cap (~500 tokens, ~7-8 operations).

Implementation: PostToolUse hook detects boundary, generates template, appends to Operations section.

### Layer 3: Expand (threshold trigger)

```markdown
## Context (expanded at threshold)
### Key Decisions
- Option 3 confirmed — stay on Claude Code
- /clear preferred over /compact

### Causal Chain
- Op2 → Op3 → Op4 → Op5 → Op6

### Unresolved
- (none)

### Files Modified This Session
- (none)
```

+200-350 tokens. Written once when context utilization approaches the user's `/clear` threshold. Pulls from:
- Decision language detected in assistant text throughout session
- Operation dependency graph (tracked by operation tracker)
- Unresolved errors (operations with `failure` outcome not followed by a fix)
- Files modified across all operations

Implementation: UserPromptSubmit hook checks turn count or context estimation. When threshold approached, queries operation tracker for full context and writes Expand section.

## Threshold Detection

Since we can't directly measure context utilization from hooks, use heuristics:

```python
# Estimate context pressure
EXPAND_TRIGGER_TURN = 60          # or configurable
# OR
EXPAND_TRIGGER_OP_COUNT = 10      # after N operations
# OR
EXPAND_AFTER_CLEAR_WARNING = True  # if user sees "context getting large" warning
```

The simplest: trigger Expand after N turns (configurable, default 60). More sophisticated: estimate token usage from operation tracker metadata (sum of tools invoked, files read, etc.).

## Operation Boundary Detection

Same as Progressive plan — Sapling-inspired weighted hybrid:

```python
BOUNDARY_WEIGHTS = {
    "tool_phase_transition": 0.35,
    "file_scope_change": 0.30,
    "intent_signal": 0.20,
    "temporal_gap": 0.15,
}
BOUNDARY_THRESHOLD = 0.5
```

## State Tracking

Same ramdisk state as Progressive, plus turn counter for threshold:

```python
{
    "current_op_id": 6,
    "current_op_type": "design",
    "current_op_files": ["rules/*.md"],
    "current_op_tools": ["Glob", "Grep"],
    "current_op_start_turn": 16,
    "last_turn_timestamp": 1741816200,
    "total_ops": 6,
    "total_turns": 21,
    "expand_written": false,
    "decisions": [
        "Option 3 confirmed — stay on Claude Code",
        "/clear preferred over /compact"
    ],
    "unresolved_errors": []
}
```

## Implementation Components

| Component | Location | Purpose |
|-----------|----------|---------|
| Operation tracker | `hooks/shared/operation_tracker.py` | Boundary detection, state tracking |
| Base writer | `hooks/shared/working_memory_writer.py` | Status line (Layer 1) |
| Accumulate writer | `hooks/shared/working_memory_writer.py` | Op summaries (Layer 2) |
| Expand writer | `hooks/shared/working_memory_writer.py` | Full context (Layer 3) |
| UserPromptSubmit integration | `hooks/user_prompt_capture.py` | Triggers base + threshold check |
| PostToolUse integration | `hooks/gates/` or new hook | Triggers boundary detection |
| Working memory file | `rules/working-memory.md` | The output |

## `/clear` Lifecycle

1. Session runs, base updates every turn, ops accumulate on boundaries
2. Context grows, threshold approached → Expand section written
3. User sees threshold warning, types `/clear`
4. Message array wiped — fresh context
5. `rules/working-memory.md` persists with full 700-token context (base + ops + expand)
6. Next prompt: Claude reads rules/ → immediately oriented
7. After `/clear`: reset `expand_written = false`, keep ops + base
8. New cycle: base continues updating, new ops accumulate, expand re-triggers later

## Advantages Over Progressive

- **Per-turn awareness** — base layer means Claude always knows current op, even between boundaries
- **Threshold boost** — expand section adds decisions, causal chains, errors right when needed most
- **Better `/clear` timing** — expand section signals to user that it's a good time to `/clear`
- **Richer late-session context** — 700 tokens vs progressive's 430

## Advantages of Progressive Over This

- **Simpler** — one trigger, one writer, one growth curve
- **No coordination** — no need to manage three writers updating the same file
- **Slightly cheaper** — 4,810 vs 4,980 tokens
- **Less can go wrong** — fewer moving parts

## Risks

- File write contention — UserPromptSubmit and PostToolUse could fire close together, both trying to rewrite the file. Mitigate with atomic writes (tmp + rename) and operation tracker as single source of truth.
- Expand trigger timing — if triggered too early, paying 700 tokens for too many turns. If too late, user `/clear`s before expand fires.
- Three writers add complexity — more hooks to maintain, more potential for bugs
- Base layer fires every turn — adds ~5ms hook latency per turn (file write)
