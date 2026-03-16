# /agents — Agent Task & Message Coordination

## When to use
When the user says "create a task", "list tasks", "send message to agent", "what tasks are pending", "assign work", or wants to coordinate agent work.

## How it works
This skill wraps the `agent_coordination` MCP tool. Parse the user's intent and call the tool with the right action.

## Actions

### Create a task
```
agent_coordination(action="create_task", title="...", created_by="main", priority=3, assigned_to="builder", tags="audit,gates", goal="Why this matters")
```
- `title` — required
- `priority` — 1 (highest) to 9 (lowest), default 5
- `assigned_to` — agent name, sends notification if set
- `tags` — comma-separated
- `goal` — the "why" context
- `depends_on` — task_id that must be done first
- `required_role` — only agents with this role can claim it
- `parent_task_id` — links as subtask, auto-inherits goal

### List tasks
```
agent_coordination(action="list_tasks", status="pending", agent_id="builder", tag="audit")
```
All filters are optional and combinable.

### Claim a task
```
agent_coordination(action="claim_task", agent_id="builder", role="builder", tag="gates")
```
Atomically grabs the highest-priority pending task matching filters.

### Complete a task
```
agent_coordination(action="complete_task", task_id="...", result="42 tests passed")
```
Marks done and broadcasts completion to the message channel.

### Send a message
```
agent_coordination(action="send_message", content="Look at gate 16", to_agent="researcher", agent_id="main")
```
- `to_agent` — "all" for broadcast, or specific agent name
- `msg_type` — "info", "request", "warning", "discovery", "status"

### Read messages
```
agent_coordination(action="read_messages", agent_id="researcher", since_minutes=30)
```

## Steps
1. Parse what the user wants (create/list/claim/complete/send/read)
2. Call `agent_coordination` MCP tool with the right action and parameters
3. Format and display the result
4. If creating multiple tasks, call sequentially (depends_on needs previous task_id)
