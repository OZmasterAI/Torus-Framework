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
5. If validation passes, save to memory: remember_this("Completed task {task_id}: {task_name}", "megaman-loop iteration", "type:fix,area:framework")
6. If validation fails, describe what went wrong clearly

## Context
- You have access to Memory MCP — use search_knowledge() to find relevant prior work
- All framework gates are active — follow the read-before-edit pattern
- Focus exclusively on this single task for maximum quality
