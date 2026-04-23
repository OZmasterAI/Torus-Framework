You are executing task {task_id} of PRP "{prp_name}".

## Task
{task_name}

## Files to modify
{file_list}

## Validation
Run this command to verify: `{validate_command}`

## Rules
1. Query memory first: search_knowledge("{task_name}")
2. Check fix history: query_fix_history("{task_name}")
3. Read all files before editing
4. Before making changes, record your strategy: record_attempt("{task_name}", "brief description of your approach")
5. Implement ONLY this task — do not touch other tasks
6. Run the validation command and show output
7. If validation passes:
   - record_outcome(chain_id, "success")
   - remember_this("Completed task {task_id}: {task_name}", "torus-loop iteration", "type:fix,area:framework")
8. If validation fails (you have up to 3 internal retries):
   - record_outcome(chain_id, "failure")
   - Analyze WHY it failed — do not retry the same approach
   - record_attempt("{task_name}", "new approach: ...")
   - Try a different strategy and re-validate
   - After 3 failed attempts, stop and describe what went wrong clearly

## Agent Channel
If you discover something other agents should know (API patterns, gotchas, interface changes), broadcast it:
```python
import sys; sys.path.insert(0, '~/.claude/hooks')
from shared.agent_channel import post_message
post_message('task-{task_id}', 'discovery', 'what you found')
```

## Context
- You have access to Memory MCP — use search_knowledge() to find relevant prior work
- All framework gates are active — follow the read-before-edit pattern
- Focus exclusively on this single task for maximum quality
