# /tag-branch — Label the current DAG branch with a task name

## When to use
When the user wants to tag/label the current conversation branch with a task description for branch-aware working memory.

## Steps

1. Extract the label from the user's input
2. Tag the current branch:
   ```python
   import sys
   sys.path.insert(0, os.path.expanduser("~/.claude/hooks"))
   from shared.dag import get_session_dag
   dag = get_session_dag()
   dag.label_branch(dag.current_branch_id(), label)
   info = dag.current_branch_info()
   ```
3. Confirm: "Branch {name} labeled: {label}"

## Arguments
- Label (required) — task description for this branch (e.g. "auth-fix", "dag-implementation")

## Output
- Confirmation with branch name and new label
