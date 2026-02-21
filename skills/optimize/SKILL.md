# /optimize — Performance Optimization Skill

## When to use
When user says "optimize", "speed up", "performance", "slow", "latency",
or wants to improve framework response times and resource usage.

## Commands
- `/optimize` — Full optimization pass
- `/optimize hooks` — Focus on hook latency
- `/optimize memory` — Focus on memory/ChromaDB performance
- `/optimize gates` — Focus on gate execution time

## Flow

### 1. PROFILE
- Read today's audit log for timing data
- Check state files for `gate_timing` entries
- Measure hook execution: `time python3 ~/.claude/hooks/enforcer.py`
- Count memory operations from audit log

### 2. IDENTIFY
- Find the 3 slowest gates by average execution time
- Find hooks that frequently timeout (>3s)
- Check for redundant memory queries (same query within 60s)
- Look for N+1 patterns in gate checks

### 3. ANALYZE
- Cross-reference with memory: `search_knowledge("optimization performance latency")`
- Compare against previous optimization results
- Calculate potential savings for each bottleneck

### 4. OPTIMIZE
For each identified bottleneck:
- Hook latency: suggest caching, async execution, or timeout reduction
- Gate slowness: suggest short-circuit conditions or caching
- Memory redundancy: suggest query deduplication or TTL extension
- File I/O: suggest ramdisk usage or batching

### 5. VERIFY
- Re-run profiling after changes
- Compare before/after metrics
- Save results to memory with `type:benchmark,area:framework,optimize` tags

### 6. REPORT
Display table:
| Component | Before (ms) | After (ms) | Improvement | Method |
|-----------|-------------|------------|-------------|--------|

## Rules
- NEVER disable gates or remove safety checks for performance
- Prefer caching over removing functionality
- Always measure before AND after changes
- Save findings to memory with type:benchmark,optimize tags
- Maximum 5 optimizations per invocation
