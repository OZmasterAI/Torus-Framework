You are executing task {task_id} of PRP "{prp_name}".

## Task
{task_name}

## Files to modify
{file_list}

## Validation
Run this command to verify: `{validate_command}`

## Rules
1. Query memory first: search_knowledge("{task_name}")
2. Read all files before editing
3. Implement ONLY this task — do not touch other tasks
4. Run the validation command and show output
5. If validation passes, save to memory: remember_this("Completed task {task_id}: {task_name}", "torus-loop iteration", "type:fix,area:framework")
6. If validation fails, describe what went wrong clearly

## Agent Channel
If you discover something other agents should know (API patterns, gotchas, interface changes), broadcast it:
```python
import sys; sys.path.insert(0, '/home/crab/.claude/hooks')
from shared.agent_channel import post_message
post_message('task-{task_id}', 'discovery', 'what you found')
```

## Context
- You have access to Memory MCP — use search_knowledge() to find relevant prior work
- All framework gates are active — follow the read-before-edit pattern
- Focus exclusively on this single task for maximum quality
