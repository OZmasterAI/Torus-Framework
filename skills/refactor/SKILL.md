# /refactor — Safe, Incremental Code Refactoring

## When to use
When the user says "refactor", "extract", "rename", "simplify", "dead code", "cleanup", "restructure", or wants to reorganize code without changing behavior.

Complements `/fix` (behavior changes) and `/review` (analysis only) by performing **structural improvements** while preserving correctness.

## Steps

### 1. MEMORY CHECK
- `search_knowledge("refactor")` — find prior refactoring attempts and lessons learned
- `search_knowledge("[target file or module]")` — check for known issues in the area
- `query_fix_history("[target area]")` — check if past refactors caused regressions
- If prior refactoring caused problems, present the history and adjust approach

### 2. SCOPE
Clarify the refactoring type and boundaries with the user:

**Refactoring types:**
- **Extract function** — Pull a block of code into a named function
- **Extract constant** — Replace magic numbers/strings with named constants
- **Rename symbol** — Rename a function, variable, class, or module across the codebase
- **Simplify logic** — Reduce complexity (flatten nesting, simplify conditionals, remove duplication)
- **Dead code removal** — Remove unreachable or unused code
- **Move/reorganize** — Relocate code to a more appropriate file or module

**Define boundaries:**
- Single file, module, or entire codebase?
- Which functions/classes are in scope?
- Are tests in scope for refactoring too?

If the scope is unclear, ask the user before proceeding.

### 3. IMPACT ANALYSIS
Before touching any code, assess the blast radius:

- **Grep all usages** of the target symbol/code pattern
- **Count affected files** — show the user exactly what will change
- **Check for dynamic references** — string-based lookups, reflection, config files, templates
- **Check for public API exposure** — will external consumers be affected?
- **Map dependencies** — what imports/calls the target? What does it import/call?

Present the impact summary to the user:
```
Refactoring: [description]
Affected files: N
  - file_a.py:L10 — definition
  - file_b.py:L25, L40 — usage
  - test_file.py:L15 — test reference
Dynamic references: [none found / list them]
Public API impact: [none / description]
```

Get user confirmation before proceeding.

### 4. SAFETY NET
Establish a baseline BEFORE making any changes:

- **Run the full test suite** — record the exact pass/fail count
- **Record the baseline**: `N tests passed, M tests failed, K tests skipped`
- If tests already fail, note which ones — these are pre-existing, not caused by refactoring
- If no test suite exists, define manual verification steps with the user
- **Take a snapshot**: note the current git status so changes can be reverted if needed

### 5. REFACTOR IN STEPS
Apply changes **one logical step at a time**, never all at once:

**For each step:**
1. Make a single, focused change (one rename, one extraction, one simplification)
2. Run tests immediately after the change
3. If tests pass — continue to next step
4. If tests fail — **revert the step immediately** and diagnose:
   - Was a usage missed? (Check dynamic references)
   - Was behavior accidentally changed? (Compare logic)
   - Is the test itself wrong? (Only if clearly outdated)
5. Do NOT accumulate multiple unverified changes

**Step ordering for multi-step refactors:**
1. Rename/move the definition first
2. Update all static references
3. Update dynamic references (config, templates, string lookups)
4. Update tests to match new structure
5. Remove old code only after everything passes

### 6. VERIFY
After all refactoring steps are complete:

- **Run the full test suite again** — compare to baseline from Step 4
- **Test count check**: pass count must be >= baseline (no tests lost)
- **Failure check**: no NEW test failures introduced
- **Run linters** if available (`ruff`, `pylint`, `eslint`, `tsc --noEmit`)
- **Check for new warnings** that weren't present before
- **Grep for leftover references** to old names/patterns
- Show the user proof: test output, before/after comparison

If verification fails, revert to the last known-good state and report what went wrong.

### 7. SAVE
- `remember_this("[what was refactored and how]", "refactoring [target]", "type:fix,area:refactoring,outcome:success")`
- Include: files changed, refactoring type, test results before/after
- If the refactoring revealed a pattern worth remembering, save it separately
- If the user wants a commit, suggest invoking `/commit`

## Kill Rule
If a refactoring step causes cascading failures:
- STOP and revert to the last passing state
- Save what you learned: `remember_this("[what broke and why]", "refactoring [target]", "type:learning,area:refactoring,outcome:failed")`
- Present alternatives to the user rather than forcing the refactor through
