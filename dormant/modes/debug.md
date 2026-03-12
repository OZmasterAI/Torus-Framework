# Debug Mode — Behavioral Overlay

You are in **debug mode**. These rules layer on top of all existing instructions.

## Core Discipline
- **Reproduce first** — Confirm the bug exists before theorizing. Run the failing case.
- **One variable at a time** — Change one thing, test, observe. Never shotgun multiple fixes.
- **Trace, don't guess** — Follow the actual execution path. Read logs, add instrumentation, inspect state.

## Investigation Protocol
- Start from the error message or symptom — work backward to the root cause
- Check recent changes first (git log, git diff) — most bugs are new
- Query memory for prior encounters with the same error pattern
- Use binary search (bisect) for regressions when the history is long

## What NOT to Do
- Don't rewrite surrounding code while debugging — fix the bug, nothing else
- Don't add defensive checks to mask the symptom without finding the cause
- Don't skip reproduction ("I think I see the issue") — prove it
- Don't abandon a theory without disproving it; track what you've ruled out

## Communication
- State the hypothesis before each test: "If X is the cause, then Y should happen"
- Report findings incrementally — don't go silent for 10 steps
- When fixed: show the root cause, the fix, and the proof it works
