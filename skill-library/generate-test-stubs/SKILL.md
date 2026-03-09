# /generate-test-stubs — Auto-Generate Test Stubs

Scan a Python module using AST analysis and generate ready-to-run test stubs.

## Steps

1. User provides a module path (absolute, or relative to `~/.claude/hooks/`)
2. Read the module file
3. Identify all public functions (not starting with `_`)
4. Classify each function:
   - **gate_check**: has `(tool_name, tool_input, state)` signature → test with GateResult assertions
   - **shared_util**: utility function → test with input/output assertions
   - **skill_entry**: has `() -> dict` signature → test return structure
5. Generate test code in `test_framework.py` style:
   - Import the module
   - Create test functions with descriptive names
   - Add assertions for return types, expected keys, edge cases
6. Present the generated test code for user review

## Output
Complete Python test code ready to paste into `hooks/test_framework.py` or a standalone test file.

## Notes
- Uses `shared.test_generator.scan_module` and `generate_tests` if available
- Falls back to manual AST parsing via `import ast` if shared module unavailable
