# /test — Run, Write, and Debug Tests

## When to use
When the user says "test", "run tests", "write tests", "failing test", "test suite", or encounters test failures.

## Steps
1. **MEMORY CHECK** — search_knowledge() for the project's test framework, past test failures, and known test patterns
2. **DISCOVER**:
   - Glob for test files: `test_*`, `*_test.*`, `*.test.*`, `*.spec.*`, `spec/`, `tests/`, `__tests__/`
   - Identify the test framework (pytest, jest, cargo test, go test, vitest, mocha, etc.)
   - Read config files (pytest.ini, jest.config.*, Cargo.toml, go.mod, vitest.config.*)
   - Check for existing test scripts in package.json or Makefile
3. **RUN**:
   - Execute the test suite with verbose output
   - Capture stdout/stderr and exit code
   - Parse failures: extract failing test names, assertions, and stack traces
   - If a specific test is requested, run only that test
4. **DIAGNOSE** (for failures):
   - Read the failing test file and the source code it tests
   - Identify whether the failure is in the test or the source
   - search_knowledge() for similar past failures
   - query_fix_history() if the error pattern has been seen before
5. **FIX** (if user asks to fix):
   - Enter Plan Mode if the fix touches multiple files
   - Make the minimal change needed to fix the failure
   - Re-run the specific failing test to confirm the fix
   - Re-run the full suite to check for regressions
   - Show proof: display passing test output
6. **WRITE** (if user asks to write tests):
   - Read the source code to be tested
   - Identify edge cases: empty inputs, boundaries, error paths, happy paths
   - Follow existing test patterns in the project (naming, structure, assertions)
   - Write tests incrementally — run after each test to verify it passes
   - Aim for meaningful coverage, not just line count
7. **SAVE**:
   - remember_this() with test results, failures found, and fixes applied
   - Tag with "type:fix,area:testing" for fixes or "type:feature,area:testing" for new tests
   - record_outcome() if a causal chain was tracked
