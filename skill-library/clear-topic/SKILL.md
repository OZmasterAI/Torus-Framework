# /clear-topic — Mark a branch as resolved

## When to use
When the user wants to mark a conversation topic/branch as done so it stops consuming context budget in future summaries.

## Steps

1. Check memory for any notes about this branch/topic: `search_knowledge("[branch label]")` — surface prior context
2. List active branches:
   ```python
   import os, sys
   sys.path.insert(0, os.path.expanduser("~/.claude/hooks"))
   from shared.dag import get_session_dag
   dag = get_session_dag()
   active = dag.get_active_branches()
   ```
3. If a label/name is provided, find the matching branch
4. If no argument, show active branches and ask which to resolve
5. Resolve the branch:
   ```python
   dag.resolve_branch(branch_id)
   ```
6. Confirm: "Branch {name} marked as resolved. Nodes preserved but excluded from future summaries."
7. Save to memory: `remember_this("Resolved branch: [label]", "clear-topic", "type:decision")`

## Arguments
- Branch label or name (optional) — if omitted, shows list of active branches

## Output
- Confirmation that branch is resolved
- Remaining active branches count
