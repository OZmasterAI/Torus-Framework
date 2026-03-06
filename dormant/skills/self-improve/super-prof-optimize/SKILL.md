# /super-prof-optimize — Performance Profiling & Optimization

Merged from: `/profile` + `/optimize`

## When to use
When the user says "super-profile", "super-optimize", "deep profile", "full optimization",
"performance analysis", or wants comprehensive profiling AND optimization in a single workflow
covering both general code and Torus framework-specific bottlenecks.

## Commands
- `/super-prof-optimize` — Full profile + optimize cycle
- `/super-prof-optimize --profile-only` — Profile and analyze without making changes
- `/super-prof-optimize hooks` — Focus on hook/gate latency
- `/super-prof-optimize memory` — Focus on memory/ChromaDB performance
- `/super-prof-optimize gates` — Focus on gate execution time
- `/super-prof-optimize <target>` — Profile a specific file, function, or module

## Steps

### 1. MEMORY CHECK
- `search_knowledge("[target function/module] performance")` — check for prior profiling results
- `search_knowledge("tag:area:performance")` — find historical performance data
- `search_knowledge("optimization performance latency")` — find prior optimization results
- If prior benchmarks exist, use `get_memory(id)` to retrieve baselines for comparison

### 2. DETECT TOOLING
Identify available profiling tools:
- **Python**: `cProfile`, `profile`, `timeit`, `line_profiler`, `py-spy`, `pytest-benchmark`, `memory_profiler`
- **Node/JS**: `--prof`, `clinic`, `0x`, `benchmark.js`
- **General**: `hyperfine` (CLI benchmarking), `time`, `strace`, `perf`
- Check `requirements.txt`, `pyproject.toml`, `package.json` for installed profilers
- If no profiler is available, suggest installing the most appropriate one

### 3. FRAMEWORK-SPECIFIC PROFILING
For Torus framework components specifically:
- Read today's audit log for timing data
- Check state files for `gate_timing` entries
- Measure hook execution: `time python3 ~/.claude/hooks/enforcer.py`
- Count memory operations from audit log
- Find the 3 slowest gates by average execution time
- Find hooks that frequently timeout (>3s)
- Check for redundant memory queries (same query within 60s)
- Look for N+1 patterns in gate checks

### 4. BASELINE
- Run existing benchmarks if available (`pytest-benchmark`, test suites with timing)
- If no benchmarks exist, create a simple timing harness for the target:
  ```python
  import time
  start = time.perf_counter()
  # target operation
  elapsed = time.perf_counter() - start
  print(f"Baseline: {elapsed:.4f}s")
  ```
- Record baseline metrics: execution time, memory usage, call counts
- Save baseline: `remember_this("Baseline: [target] runs in [time]", "profiling [target]", "type:learning,area:performance")`

### 5. PROFILE
Based on the target, run the appropriate profiler:

**Function-level (Python — cProfile):**
```bash
python3 -m cProfile -s cumulative target_script.py 2>&1 | head -30
```

**Line-level (Python — line_profiler, if available):**
```bash
kernprof -l -v target_script.py
```

**Live process (py-spy, if available):**
```bash
py-spy top --pid <PID>
```

**CLI command benchmarking (hyperfine):**
```bash
hyperfine --warmup 3 'command_to_benchmark'
```

**Memory profiling:**
```bash
python3 -m memory_profiler target_script.py
```

**Micro-benchmarks (timeit):**
```python
import timeit
result = timeit.timeit('target_function()', setup='from module import target_function', number=1000)
print(f"Average: {result/1000:.6f}s per call")
```

### 6. ANALYZE
From the profiler output, identify:
- **Top 5 hotspots**: Functions consuming the most cumulative time
- **Call counts**: Functions called excessively (potential loop issues)
- **I/O bottlenecks**: File reads, network calls, database queries
- **Memory allocation hotspots**: Large allocations, leaks, fragmentation
- **Framework-specific patterns**:
  - Hook latency: suggest caching, async execution, or timeout reduction
  - Gate slowness: suggest short-circuit conditions or caching
  - Memory redundancy: suggest query deduplication or TTL extension
  - File I/O: suggest ramdisk usage or batching

Calculate improvement potential for each hotspot:
```
Hotspot: function_name() — 45% of total time
Potential improvement: If optimized 2x, saves ~22% total runtime
```

Present findings as a ranked table:
```
Rank | Function         | Time  | Calls | % Total | Opportunity
-----+------------------+-------+-------+---------+------------
1    | process_data()   | 2.3s  | 1000  | 45%     | HIGH
2    | parse_json()     | 0.8s  | 5000  | 16%     | MEDIUM
3    | validate()       | 0.5s  | 1000  | 10%     | LOW
```

If `--profile-only`: stop here and present the full analysis.

### 7. OPTIMIZE
For each high-opportunity hotspot:
1. **Identify the cause**: Algorithm complexity, I/O, memory, serialization
2. **Propose optimization**: Caching, batching, algorithm change, lazy evaluation
3. **Implement one optimization at a time**:
   - Make the change
   - Run tests after each change (correctness first)
   - Re-profile to measure improvement
   - If no improvement or regression, revert and try next approach
4. **Compare before/after**:
   ```
   Before: process_data() — 2.3s (45% of total)
   After:  process_data() — 0.4s (12% of total)
   Improvement: 5.75x speedup, 33% total runtime reduction
   ```

### 8. VERIFY
- Re-run full profiling after all changes
- Compare before/after metrics for each optimization
- Run the complete test suite to confirm no regressions
- Display summary table:

| Component | Before (ms) | After (ms) | Improvement | Method |
|-----------|-------------|------------|-------------|--------|

### 9. TRACK
Save final results to memory:
```
remember_this(
    "Performance optimization: [target] improved from [baseline] to [final]. "
    "Changes: [what was optimized]. Technique: [algorithm/caching/batching/etc]",
    "profiling and optimizing [target]",
    "type:learning,area:performance,outcome:success"
)
```
- Save with `type:benchmark,area:framework,optimize` tags for longitudinal tracking
- If benchmarks were created, note their location for future regression testing
- Record any performance regressions or tradeoffs discovered

## Rules
- NEVER disable gates or remove safety checks for performance
- Prefer caching over removing functionality
- Always measure before AND after changes
- Save findings to memory with type:benchmark,optimize tags
- Maximum 5 optimizations per invocation
- Only modify one optimization at a time — verify each before proceeding
