# /report — Session & Sprint Report Generator

## When to use
When user says "report", "summary", "what did we do", "sprint report",
"session summary", or wants a comprehensive overview of recent work.

## Commands
- `/report` — Current session report
- `/report sprint` — Full sprint report (all sessions on current branch)
- `/report weekly` — Weekly activity summary
- `/report $ARGUMENTS` — Custom report scope

## Flow

### 1. GATHER
- Read LIVE_STATE.json for current session state
- Read HANDOFF.md for session history
- Check git log for recent commits on current branch
- Search memory for session-tagged entries: `search_knowledge("session")`
- Count current tests: run `python3 hooks/test_framework.py 2>&1 | grep RESULTS`

### 2. METRICS
Collect and calculate:
- **Code**: files changed, lines added/removed (from git)
- **Tests**: total, passed, failed, new tests added
- **Memory**: total memories, new memories this session
- **Skills**: total skills, new skills created
- **Agents**: total agents, agents spawned this session
- **Gates**: fire counts, block counts from audit log
- **Duration**: session time from LIVE_STATE

### 3. NARRATIVE
Generate a human-readable summary:
- What was accomplished (bullet points)
- Key decisions made (from memory with type:decision)
- Issues encountered and resolved
- Research findings applied

### 4. COMPARISON
If previous report exists in memory:
- Calculate deltas for all metrics
- Highlight significant changes (>10% delta)
- Trend indicators: ↑ improving, ↓ regressing, → stable

### 5. OUTPUT
Format as markdown with sections:
```
## Session Report — #{session_number}
### Summary
### Metrics
### Key Decisions
### Issues & Fixes
### What's Next
```

## Rules
- Always include raw numbers, not just percentages
- Save report to memory with type:benchmark,area:framework,report tags
- Never fabricate metrics — only report what can be verified
- Include "What's Next" section from LIVE_STATE.json
