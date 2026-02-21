# PRP: {Feature Name}

**Created**: {date}
**Status**: draft | approved | implemented | abandoned
**Confidence**: {1-10}/10
**Milestone**: {milestone-number}
**Phase**: {phase-number}

## Goal
{What needs to be built — specific end state}

## Why
- {Business value / user impact}
- {Problems this solves}

## Success Criteria
- [ ] {Specific, testable outcome 1}
- [ ] {Specific, testable outcome 2}
- [ ] {Specific, testable outcome N}

## Context & References

### Documentation
- {url}: {why this is relevant, which sections to read}

### Codebase Patterns
- {file:line}: {pattern to follow and why}

### Memory (prior knowledge)
- {memory search results relevant to this feature}

### Examples
- {~/.claude/examples/pattern-name}: {what to reference}

## Known Gotchas
{CRITICAL: Library quirks, version issues, integration traps, edge cases}
{This section prevents first-pass failures — never leave it empty}

- {Gotcha 1: description and mitigation}
- {Gotcha 2: description and mitigation}

## Codebase Tree (current → desired)

### Current
```
{relevant current file structure}
```

### Desired
```
{what files will be added/modified}
```

## Implementation Tasks (ordered)

### Task 1: {name}
- **Requirement**: {R-id this task fulfills}
- **Files**: {create/modify list}
- **Validate**: `{exact command to verify this task}`
- **Done**: {specific observable outcome proving task is complete}
- **Pattern**: {existing code to mirror}
- **Pseudocode**:
  ```
  {approach with critical details}
  ```

### Task 2: {name}
- **Requirement**: {R-id}
- **Files**: {create/modify list}
- **Validate**: `{exact command to verify this task}`
- **Done**: {specific observable outcome}
- **Pattern**: {existing code to mirror}
- **Pseudocode**:
  ```
  {approach with critical details}
  ```

### Task N: ...

## Validation Gates

### Gate 1: Tests pass
```bash
{exact test command}
```
**Expected**: {what success looks like}

### Gate 2: Manual verification
```bash
{exact verification command}
```
**Expected**: {what success looks like}

## Anti-Patterns
- {What NOT to do — common mistakes for this type of feature}
- {Patterns that look tempting but cause problems}

## Notes
{Any additional context, open questions, or decisions to revisit}
