# /review — Code Quality and Convention Check

## When to use
When the user says "review", "check", "lint", "quality", "before commit", "verify code", or wants to check code quality before committing or merging.

Integrates with `/commit` — run `/review` before staging changes.

## Steps

### 1. MEMORY CHECK
- `search_knowledge("type:correction")` — find known anti-patterns and past mistakes
- `search_knowledge("[project name] conventions")` — find project-specific rules
- Note any recurring issues from memory to watch for

### 2. SCAN CHANGES
- `git status` — see staged and unstaged changes
- `git diff` — see unstaged changes in detail
- `git diff --cached` — see staged changes in detail
- Detect file types involved (.py, .js, .ts, .md, .json, etc.)
- If no changes exist, ask the user what to review (specific file, directory, or PR)

### 3. RUN QUALITY TOOLS
Detect and run available linters/type checkers based on file types:

**Python:**
- `python -m py_compile <file>` — syntax check
- `pylint <file>` or `ruff check <file>` — if available
- `mypy <file>` — if available and configured
- `python -m pytest --co -q` — verify tests still collect

**JavaScript/TypeScript:**
- `npx eslint <file>` — if available
- `npx tsc --noEmit` — if tsconfig.json exists

**General:**
- Check for `Makefile`, `pyproject.toml`, `package.json` scripts for project-specific lint commands
- Run whatever the project already uses

### 4. CHECK CONVENTIONS
- **CLAUDE.md compliance**: Verify changes follow project instructions
- **Hardcoded secrets**: Grep for API keys, tokens, passwords, `.env` values in code
  - Pattern: `(api[_-]?key|secret|password|token|credential)\s*[:=]`
  - Flag any matches as Critical severity
- **Style consistency**: Match indentation, naming, and patterns of surrounding code
- **Import hygiene**: Check for unused imports, circular dependencies
- **Error handling**: Verify exceptions are caught appropriately, not silently swallowed
- **TODO/FIXME/HACK**: Flag temporary code markers

### 5. ANALYZE AGAINST MEMORY
- `search_knowledge("type:correction")` — find entries matching patterns in the changed code
- Cross-reference with `query_fix_history()` for error-prone areas
- Check if any changed files appear in past error memories
- Flag code that matches previously-corrected anti-patterns

### 6. REPORT
Organize findings by severity with file:line references:

**Critical** (must fix before commit):
- Security vulnerabilities (hardcoded secrets, injection risks, auth bypass)
- Data loss risks
- Breaking changes without migration

**High** (should fix):
- Logic errors, off-by-one, null pointer risks
- Missing error handling for external calls
- CLAUDE.md convention violations

**Medium** (recommended):
- Style inconsistencies
- Missing type annotations in public APIs
- Overly complex functions (high cyclomatic complexity)

**Low** (informational):
- TODO/FIXME markers
- Minor naming suggestions
- Documentation gaps

Format each finding as:
```
[SEVERITY] file_path:line_number — Description of issue
  Suggestion: How to fix it
```

### 7. FIX
- Present the report and ask the user which issues to fix
- For approved fixes:
  - Apply the fix (Edit tool)
  - Re-run the relevant quality check to verify
  - Show before/after if the change is non-obvious
- For declined fixes, respect the user's decision and move on

### 8. SAVE
- `remember_this("[summary of issues found and fixed]", "code review on [files/feature]", "type:correction,area:[relevant area]")`
- Save recurring patterns as corrections so future reviews catch them
- If a new anti-pattern was found, tag with `priority:high` for future detection
