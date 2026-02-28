# Test Workspace

**Created**: 2026-02-14
**Purpose**: Isolated environment for validating Torus Framework gates and workflows

## Overview

This workspace is used for testing and validating the Torus Framework without impacting production workflows. It serves as a safe sandbox for:

- Testing gate enforcement behavior
- Validating PRP workflow mechanics
- Verifying memory MCP integration
- Testing agent delegation patterns
- Experimenting with new framework features

## Structure

```
test-workspace/
├── README.md           # This file
├── sample-code/        # Test files for gate validation
├── test-prp.md         # Sample PRP for workflow testing
└── test-results/       # Output from validation runs
```

## Usage

This workspace is referenced by framework validation tasks and test suites. Do not use for production work.

## Validation Commands

Test that workspace is properly initialized:
```bash
test -f /home/crab/.claude/PRPs/test-workspace/README.md
```

## Notes

- This workspace is excluded from main project workflows
- Created as part of framework-validation PRP
- Safe to reset or delete for testing purposes
