# /profile — Performance Profiling & Optimization

## When to use
When the user says "profile", "benchmark", "slow", "performance", "optimize", "bottleneck", "timing", or wants to measure, analyze, or improve the performance of code, functions, endpoints, or workflows.

## Steps

### 1. MEMORY CHECK
- `search_knowledge("[target function/module] performance")` — check for prior profiling results and benchmarks
- `search_knowledge("tag:area:performance")` — find historical performance data
- If prior benchmarks exist, use `get_memory(id)` to retrieve baselines for comparison

### 2. DETECT TOOLING
Identify available profiling tools in the project:
- **Python**: `cProfile`, `profile`, `timeit`, `line_profiler`, `py-spy`, `pytest-benchmark`, `memory_profiler`
- **Node/JS**: `--prof`, `clinic`, `0x`, `benchmark.js`
- **General**: `hyperfine` (CLI benchmarking), `time`, `strace`, `perf`
- Check `requirements.txt`, `pyproject.toml`, `package.json` for installed profilers
- If no profiler is available, suggest installing the most appropriate one for the stack

### 3. BASELINE
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

### 4. PROFILE
Based on what the user wants to profile, run the appropriate profiler:

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

### 5. ANALYZE
From the profiler output, identify:
- **Top 5 hotspots**: Functions consuming the most cumulative time
- **Call counts**: Functions called excessively (potential loop issues)
- **I/O bottlenecks**: File reads, network calls, database queries
- **Memory allocation hotspots**: Large allocations, leaks, fragmentation
- Calculate improvement potential for each hotspot:
  ```
  Hotspot: function_name() — 45% of total time
  Potential improvement: If optimized 2x, saves ~22% total runtime
  ```
- Present findings as a ranked table:
  ```
  Rank | Function         | Time  | Calls | % Total | Opportunity
  -----+------------------+-------+-------+---------+------------
  1    | process_data()   | 2.3s  | 1000  | 45%     | HIGH
  2    | parse_json()     | 0.8s  | 5000  | 16%     | MEDIUM
  3    | validate()       | 0.5s  | 1000  | 10%     | LOW
  ```

### 6. OPTIMIZE
For each high-opportunity hotspot:
1. **Identify the cause**: Algorithm complexity, I/O, memory, serialization
2. **Propose optimization**: Caching, batching, algorithm change, lazy evaluation
3. **Implement using /build loop**:
   - Make one optimization at a time
   - Run tests after each change (correctness first)
   - Re-profile to measure improvement
   - If no improvement or regression, revert and try next approach
4. **Compare before/after**:
   ```
   Before: process_data() — 2.3s (45% of total)
   After:  process_data() — 0.4s (12% of total)
   Improvement: 5.75x speedup, 33% total runtime reduction
   ```

### 7. TRACK
- Save final results to memory:
  ```
  remember_this(
      "Performance optimization: [target] improved from [baseline] to [final]. "
      "Changes: [what was optimized]. Technique: [algorithm/caching/batching/etc]",
      "profiling and optimizing [target]",
      "type:learning,area:performance,outcome:success"
  )
  ```
- If benchmarks were created, note their location for future regression testing
- Record any performance regressions or tradeoffs discovered
