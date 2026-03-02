# /diagnose — Gate Effectiveness Analysis

## When to use
When user says "diagnose", "gate health", "which gates fire most", "gate effectiveness",
"analyze gates", "gate stats", "gate report", or wants to understand how framework gates
are performing.

## Commands
- `/diagnose` — Full gate effectiveness analysis for today
- `/diagnose --date YYYY-MM-DD` — Analyze a specific day's audit log

---

## Phase 1: COLLECT — Read Today's Audit Log

Determine today's date and read the audit log:

```python
from datetime import date
today = date.today().isoformat()  # e.g., "2026-02-20"
audit_path = f"~/.claude/hooks/audit/{today}.jsonl"
```

Read the file line by line (it is newline-delimited JSON). If the file does not exist,
report "No audit log found for {today}" and stop.

Also read the gate effectiveness tracker:
```
~/.claude/hooks/.gate_effectiveness.json
```

For each audit log entry, extract:
- `gate` — gate name/label (e.g., "GATE 1: READ BEFORE EDIT")
- `decision` — "block", "warn", or "pass"
- `tool` — which tool triggered the gate
- `timestamp` — for timing analysis
- `session_id` — to identify multi-agent context

Count per gate:
- Total fires
- Blocks (decision == "block")
- Warns (decision == "warn")
- Passes (decision == "pass")

---

## Phase 2: ANALYZE — Calculate Effectiveness Metrics

For each gate compute:

1. **Block rate** = blocks / total_fires (if total_fires > 0)
2. **Warn rate** = warns / total_fires
3. **False positive indicator**: high blocks (>10) + no corresponding test failures
   in state → flag as potentially noisy
3. **Status label**:
   - `EFFECTIVE` — block_rate > 0.05 and total_fires > 5
   - `NOISY` — block_rate > 0.30 and total_fires > 20 (fires a lot, blocks often)
   - `QUIET` — total_fires < 3 (rarely triggered)
   - `WARN-ONLY` — warns > 0 and blocks == 0
   - `PASSING` — passes == total_fires (never blocked or warned)

Also load the `.gate_effectiveness.json` cumulative data to cross-reference
lifetime block counts vs today's counts.

---

## Phase 3: MEMORY CHECK — Search for Known Issues

Run these memory searches:
```
search_knowledge("gate noisy block complaints")
search_knowledge("gate false positive")
search_knowledge("gate disabled tuning")
```

Note any memories with relevance > 0.4 — these are known issues to include in the report.

---

## Phase 4: REPORT — Display the Analysis Table

Output a formatted report:

```
╔══════════════════════════════════════════════════════════════════════════════╗
║            GATE EFFECTIVENESS REPORT — {TODAY}                              ║
╚══════════════════════════════════════════════════════════════════════════════╝

Audit log: {audit_path}   Entries: {total_entries}   Sessions: {unique_sessions}

┌─────────────────────────────┬───────┬────────┬───────┬────────┬────────────┐
│ Gate                        │ Fires │ Blocks │ Warns │ Passes │ Status     │
├─────────────────────────────┼───────┼────────┼───────┼────────┼────────────┤
│ GATE 1: READ BEFORE EDIT    │  ...  │  ...   │  ...  │  ...   │ EFFECTIVE  │
│ GATE 2: NO DESTROY          │  ...  │  ...   │  ...  │  ...   │ EFFECTIVE  │
│ ...                         │  ...  │  ...   │  ...  │  ...   │ ...        │
└─────────────────────────────┴───────┴────────┴───────┴────────┴────────────┘

Lifetime cumulative (from .gate_effectiveness.json):
  Gate with most lifetime blocks: {gate_name} ({count} blocks)
  Gate with most prevented issues: {gate_name} ({count} prevented)
```

**Always show raw numbers, not just percentages.**

---

## Phase 5: RECOMMEND — Gate Tuning Suggestions

Based on the analysis, generate specific recommendations:

**Noisy gates** (high block rate, consider threshold tuning):
- If GATE 1 blocks > 30/day: "Gate 1 is firing frequently — consider checking if read
  is being called unnecessarily, or if the rolling window is too strict."
- If GATE 11 blocks > 10/day: "Rate limit gate may be too tight for current workload."

**Quiet gates** (rarely fires, check if still needed):
- Total fires < 3 over the day: "Gate {N} fired only {count} times — verify it is still
  relevant or if its coverage has been absorbed by another gate."

**Gaps** (gates that should exist but don't based on memory findings):
- If memory search returns gate-related complaints with no corresponding gate, flag it.

**Effective gates** (keep as-is):
- List gates with block_rate 5-20% — these are catching real issues without being noisy.

---

## Rules

- **Read-only analysis** — never modify gate files, enforcer.py, or settings.json
- **Raw numbers always** — show fires/blocks/warns as integers, not just "30%"
- **Save findings** — after generating the report, call:
  ```
  remember_this(
    content="Gate diagnose: {summary of top findings}",
    context="Gate effectiveness report for {today}",
    tags=["type:learning", "area:framework", "diagnose", "gates"]
  )
  ```
- If the audit log has fewer than 10 entries, note "Low data — report may not be
  representative. Run more operations to get meaningful stats."
- If `.gate_effectiveness.json` is missing, skip cumulative section and note it.

---

## Example Output (abbreviated)

```
Gate Effectiveness Report — 2026-02-20
Audit entries: 847  |  Unique sessions: 3

Gate                        Fires  Blocks  Warns  Passes  Status
─────────────────────────── ─────  ──────  ─────  ──────  ──────────
GATE 1: READ BEFORE EDIT      312      55      0     257  NOISY
GATE 2: NO DESTROY            198      91      0     107  NOISY
GATE 4: MEMORY FIRST           44      12      0      32  EFFECTIVE
GATE 5: PROOF BEFORE FIXED     28      15      0      13  EFFECTIVE
GATE 6: SAVE TO MEMORY         55       6     21      28  WARN-ONLY
GATE 11: RATE LIMIT            19       0      0      19  PASSING
GATE 15: CAUSAL CHAIN           2       0      0       2  QUIET

Top recommendation: Gates 1 and 2 have high block rates. Review if patterns
are catching real violations or if threshold adjustment is warranted.
```
