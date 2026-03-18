# /clear-topic — Mark a branch as resolved

## When to use
When the user wants to mark a conversation topic/branch as done so it stops consuming context budget in future summaries.

## Steps

1. List active branches:
   ```python
   import sys
   sys.path.insert(0, os.path.expanduser("~/.claude/hooks"))
   from shared.dag import get_session_dag
   dag = get_session_dag()
   active = dag.get_active_branches()
   ```
2. If a label/name is provided, find the matching branch
3. If no argument, show active branches and ask which to resolve
4. Resolve the branch:
   ```python
   dag.resolve_branch(branch_id)
   ```
5. Confirm: "Branch {name} marked as resolved. Nodes preserved but excluded from future summaries."

## Arguments
- Branch label or name (optional) — if omitted, shows list of active branches

## Output
- Confirmation that branch is resolved
- Remaining active branches count
