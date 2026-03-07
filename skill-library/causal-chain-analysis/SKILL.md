# /causal-chain-analysis — Fix Outcome Pattern Analysis

Analyze causal chain fix outcomes to detect recurring failures, ineffective strategies, and suggest better approaches.

## Steps

1. Query fix history: `query_fix_history("")` to get all recorded outcomes
2. Group outcomes by strategy:
   - Count successes and failures per strategy
   - Calculate effectiveness rate
3. Identify recurring failures:
   - Errors that appear 3+ times with failed fixes
   - Strategies that consistently fail (< 30% success rate)
4. Compute chain health score (0-100):
   - Base: overall success rate × 100
   - Penalty: -10 per recurring failure pattern
   - Bonus: +5 per strategy with > 80% success rate
5. Generate recommendations

## Output
```
Chain Health: 72/100 (trend: improving)

Strategy Effectiveness:
  "read-then-fix": 15/18 (83%) — EFFECTIVE
  "grep-and-replace": 3/10 (30%) — INEFFECTIVE
  "retry-same": 1/8 (12%) — AVOID

Recurring Failures:
  "ImportError: shared.X" — 5 occurrences, 2 strategies tried
  "Gate 14 cascade" — 3 occurrences, same strategy each time

Recommendations:
  - Stop using "retry-same" strategy (12% success)
  - "ImportError" pattern needs a new approach — prior strategies ineffective
```

## Data Sources
- `query_fix_history` memory tool — fix outcome records
- `search_knowledge("type:fix")` — fix memories with context
