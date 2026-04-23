# /trace-memory — Trace a memory entry back to its conversation context

## When to use
When the user asks "why do we know X?", "where did this memory come from?", or wants to trace a memory entry back to the conversation that produced it.

## Steps

1. If a memory ID is provided, use `get_memory(id)` to retrieve it
2. If no memory ID given, use `search_knowledge("[topic]")` to find the relevant memory entry first
3. Look for `dag_node:` in the tags
4. If found, read the DAG node and its ancestors using Python:
   ```python
   import os, sys
   sys.path.insert(0, os.path.expanduser("~/.claude/hooks"))
   from shared.dag import get_session_dag
   dag = get_session_dag()
   trace = dag.trace_node(node_id, context_lines=5)
   ```
5. Present: the memory content, then the conversation excerpt that produced it

## Arguments
- Memory ID (required) — the ID from search_knowledge results

## Output
- Memory content + tags
- Conversation excerpt from DAG (if dag_node tag exists)
- "No DAG link" if the memory predates the DAG system
