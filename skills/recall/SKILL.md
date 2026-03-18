# /recall — Search conversation history by topic

## When to use
When the user asks "what did we discuss about X?", "when did we talk about Y?", or wants to find past conversation context that may have been lost to compaction.

## Steps

1. Extract the search query from the user's input
2. Search DAG nodes using Python:
   ```python
   import sys
   sys.path.insert(0, os.path.expanduser("~/.claude/hooks"))
   from shared.dag import get_session_dag
   dag = get_session_dag()
   results = dag.search_nodes(query, max_results=10)
   ```
3. For each result, show: role, content preview, branch name, timestamp
4. If user wants more context on a specific result, use `dag.trace_node(node_id)`

## Arguments
- Search query (required) — what to search for in conversation history

## Output
- Matching conversation nodes with context
- Branch info for each match
- "No matches" if nothing found
