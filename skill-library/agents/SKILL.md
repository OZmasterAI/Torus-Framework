# /agents — Agent Task & Message Coordination

## When to use
When the user says "create a task", "list tasks", "send message to agent", "what tasks are pending", "assign work", or wants to coordinate agent work.

## How it works
Use the native task and messaging tools: `TaskCreate`, `TaskList`, `TaskGet`, `TaskUpdate`, `TaskStop`, and `SendMessage`.

## Actions

### Create a task
```
TaskCreate(subject="...", owner="builder", priority=3, tags=["audit","gates"], description="Why this matters")
```
- `subject` — required (imperative form, e.g. "Fix gate 7")
- `priority` — 1 (highest) to 9 (lowest), default 5
- `owner` — agent name
- `tags` — list of strings
- `description` — the "why" context

### List tasks
```
TaskList()
```

### Get task details
```
TaskGet(taskId="...")
```

### Update a task
```
TaskUpdate(taskId="...", status="completed")
```
- `status` — "pending" | "in_progress" | "completed" | "deleted"

### Send a message
```
SendMessage(to="researcher", message="Look at gate 16", summary="Check gate 16")
```
- `to` — agent name, or `"*"` for broadcast (use sparingly)
- `summary` — required 5-10 word preview

## Steps
1. `search_knowledge("[task topic]")` — check for prior art or related agent work
2. Parse what the user wants (create/list/get/update/send)
3. Call the appropriate native tool with the right parameters
4. Format and display the result
5. If creating multiple tasks, call sequentially when tasks depend on each other
6. `remember_this("[task summary]", "agents coordination", "type:decision")` for significant task plans
