# Plan: Progressive Working Memory

**Status:** Proposed
**Date:** 2026-03-12
**Session:** 421
**Context:** Option 3 (Hybrid) — stay on Claude Code, enhance context management via `rules/working-memory.md`

---

## Overview

A single `rules/working-memory.md` file that grows organically as operations complete during a session. Claude Code re-reads all `rules/*.md` files on every API turn, so this file acts as persistent, dynamic context that survives `/clear` commands.

## Core Mechanism

**One trigger, one writer:** The file is updated only when an operation boundary is detected (tool phase transition, file scope change, intent signal). Each completed operation adds one summary line (~60-80 tokens). When the file reaches the cap (~800 tokens), the oldest entries are FIFO-evicted.

## Architecture

```
PostToolUse hook
    │
    ├── Detect operation boundary (same signals as Sapling)
    │   ├── Tool-phase transition (read→write, write→verify)
    │   ├── File-scope change (Jaccard < 0.2)
    │   ├── Intent signal ("now let me", "moving on to")
    │   └── Temporal gap (>30s between turns)
    │
    ├── On boundary detected:
    │   ├── Finalize current operation (infer outcome)
    │   ├── Generate template summary (~60-80 tokens)
    │   ├── Append to rules/working-memory.md
    │   ├── FIFO evict oldest if > 800 token cap
    │   └── Update "Active" section with new operation
    │
    └── No boundary: no-op (cheap)
```

## File Format

```markdown
# Working Memory (auto-generated — do not edit)
## Session 421 | Branch: layered-memory

## Completed Operations
- [Op1: explore] Session orient — MCP healthy, 8036 memories. [success]
- [Op2: explore] Retrieved Option 2 vs 3 from memory. [success]
- [Op3: explore] Deep Sapling research — 6 agents. 5-stage pipeline,
  no MCP, migration not viable, backport concepts. [success]
- [Op4: explore] 9 diagrams — Focus Agent pattern most relevant. [success]
- [Op5: investigate] Hook mechanics — CAN: modify rules/*.md (re-read
  every turn). CANNOT: modify message array. [success]

## Key Decisions
- Option 3 confirmed over Option 2 (own runtime)
- /clear preferred over /compact
- Progressive growth strategy selected

## Active
- [Op6: design] Progressive working-memory.md system

## Unresolved
- (none)
```

## Growth Profile

```
 tokens in
 working-memory.md
      │
  800 ┤                              ╭── FIFO cap
      │                             ╱
  600 ┤                        ╱───╱
      │                      ╱
  400 ┤                 ╱───╱
      │               ╱
  200 ┤          ╱───╱
      │        ╱
  100 ┤   ╱───╱
      │  ╱
   30 ┤─╱ (header only)
      └──────────────────────────────
       turn 1   Op1  Op2  Op3  Op4  Op5 ...  /clear
```

- **Turn 1-4:** ~30 tokens (just header)
- **After Op1 (turn 5):** ~90 tokens
- **After Op2 (turn 6):** ~150 tokens
- **After Op3 (turn 13):** ~230 tokens
- **After Op4 (turn 14):** ~310 tokens
- **After Op5 (turn 15):** ~430 tokens (includes decisions section)
- **Turns 16-21:** ~430 tokens (stable until next op completes)
- **After `/clear`:** File persists. ~430 tokens. Sole continuity source.

## Token Cost (21-turn session example)

| Phase | Turns | File size | Subtotal |
|-------|-------|-----------|----------|
| Pre-Op1 | 1-4 (4 turns) | 30 | 120 |
| After Op1 | 5 (1 turn) | 90 | 90 |
| After Op2 | 6 (1 turn) | 150 | 150 |
| During Op3 | 7-12 (6 turns) | 150 | 900 |
| After Op3 | 13 (1 turn) | 230 | 230 |
| After Op4 | 14 (1 turn) | 310 | 310 |
| After Op5 | 15 (1 turn) | 430 | 430 |
| During Op6 | 16-21 (6 turns) | 430 | 2,580 |
| **Total** | **21 turns** | | **~4,810** |
| **Average** | | | **~229/turn** |

## Operation Boundary Detection

Reuse Sapling's weighted hybrid heuristic (adapted to Python):

```python
BOUNDARY_WEIGHTS = {
    "tool_phase_transition": 0.35,  # read→write, write→verify, etc.
    "file_scope_change": 0.30,      # Jaccard similarity < 0.2
    "intent_signal": 0.20,          # Regex on assistant text
    "temporal_gap": 0.15,           # >30s between turns
}
BOUNDARY_THRESHOLD = 0.5
```

Tool phase mapping:
- `read`, `grep`, `glob` → "read"
- `write`, `edit` → "write"
- `bash` → "verify"
- `Agent` → "delegate"

## Operation Summary Template

```
- [Op{id}: {type}] {purpose} — {files}. [{outcome}]
```

Purpose extraction: regex cascade on assistant text for intent phrases ("I'll", "Let me", "Now", "Next"). Fallback: `{type} on {file_list}`.

## Outcome Inference

- Last tool had error → `failure`
- Has writes + successful bash → `success`
- Has writes, no verify → `partial`
- Read-only → `success`

## Key Decisions Section

Updated when the hook detects decision language in assistant text:
- "I'll go with", "decided", "confirmed", "chosen", "selected"
- Append one-liner to Key Decisions section
- Cap at 5 decisions (FIFO)

## `/clear` Lifecycle

1. Session runs, file grows on operation boundaries
2. User types `/clear` when context feels heavy
3. Message array wiped — fresh context
4. `rules/working-memory.md` persists on disk untouched
5. Next prompt: Claude reads rules/ → immediately oriented from working memory
6. New operations append to existing file (continuity across clears)
7. FIFO eviction keeps file bounded at ~800 tokens

## Implementation Components

| Component | Location | Purpose |
|-----------|----------|---------|
| Operation tracker | `hooks/shared/operation_tracker.py` | Detects boundaries, tracks state |
| Memory writer | `hooks/shared/working_memory_writer.py` | Templates, FIFO, file management |
| Hook integration | `hooks/gates/` or PostToolUse hook | Calls tracker after each tool |
| Working memory file | `rules/working-memory.md` | The output — read by Claude Code |

## State Tracking

The operation tracker needs minimal state between hook invocations:

```python
# Stored in sideband file or ramdisk
{
    "current_op_id": 6,
    "current_op_type": "design",
    "current_op_files": ["rules/*.md"],
    "current_op_tools": ["Glob", "Grep"],
    "current_op_start_turn": 16,
    "last_turn_timestamp": 1741816200,
    "total_ops": 6
}
```

Written to ramdisk (`/run/user/{uid}/claude-hooks/operation-state.json`) for fast access. Promoted to disk on operation finalization.

## Advantages

- **Simplest implementation** — one trigger (operation boundary), one writer, one file
- **Always useful** — quality proportional to session age
- **Survives `/clear`** — sole continuity mechanism
- **No timers** — event-driven, not schedule-driven
- **Cheap early** — 30 tokens when you don't need it
- **Strong late** — 430+ tokens when context is noisy
- **Graceful degradation** — if boundary detection is wrong, worst case is slightly stale context

## Risks

- Boundary detection accuracy — false positives (split one op into two) are cheap, false negatives (merge two ops) lose granularity
- Token estimation is heuristic (4 chars ≈ 1 token) — may need tuning
- File must stay under ~800 tokens or it becomes a context burden itself
- No "active status" between operations — file is static until next boundary
