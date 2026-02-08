# /fix — Auto-Diagnose and Fix Issues

## When to use
When the user says "fix", "debug", "broken", or encounters an error.

## Steps
1. **MEMORY CHECK** — search_knowledge() for the error message or symptom
2. **GATHER CONTEXT**:
   - Read any error logs or stack traces the user provided
   - Read the relevant source files
   - Check git status for recent changes
3. **DIAGNOSE**:
   - Identify the root cause (not just the symptom)
   - Check memory for similar past issues
   - If the issue was seen before, use the previous fix as starting point
4. **FIX**:
   - Enter Plan Mode if the fix is non-trivial
   - Make the minimal change needed
   - Follow The Loop: fix → test → prove → save
5. **VERIFY**:
   - Run tests or reproduce the scenario
   - Show proof the fix works (test output, curl response, etc.)
6. **SAVE**:
   - remember_this() with the bug description, root cause, and fix
   - Tag with "bug,fix,[component name]"
