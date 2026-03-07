# /gate-health-correlation — Gate Redundancy and Synergy Analysis

Analyze gate fire patterns to detect redundant pairs and synergistic pairs, then recommend optimizations.

## Steps

1. Load gate effectiveness data from `~/.claude/hooks/.gate_effectiveness.json`
2. Build a block-pattern matrix: for each tool call, which gates fired and which blocked
3. Compute Pearson correlation between gate block patterns:
   - **Redundant pairs** (r > 0.8): two gates that always block the same things → candidate for merging
   - **Synergistic pairs** (r < -0.5): gates that complement each other → keep both
   - **Independent** (-0.5 < r < 0.8): gates operating on different concerns
4. Calculate overall diversity score (higher = gates cover different concerns)
5. Generate optimization recommendations

## Output
```
Gates analyzed: 17
Overall diversity: 0.73

Redundant pairs (consider merging):
  gate-04 ↔ gate-06: r=0.85 — both check memory state

Synergistic pairs (keep both):
  gate-01 ↔ gate-14: r=-0.62 — read-check vs test-check complement

Recommendations:
  - Consider merging gate-04 and gate-06 logic
  - gate-11 has <1% block rate — candidate for removal
```

## Data Sources
- `~/.claude/hooks/.gate_effectiveness.json` — per-gate block/allow counts
- `~/.claude/hooks/.audit_log.jsonl` — temporal correlation data
