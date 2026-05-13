# /graph — Query the Code Graph

Answer any codebase question using the toroidal-indexer code graph. One tool call, compact result — no grep/find/glob.

## Usage

```
/graph <question>                              # natural language query
/graph what calls calculateWeeklyAIRewards     # callers query
/graph blast radius of jwt-auth.ts             # impact analysis
/graph path from Scheduler to AIUsageLog       # shortest call chain
/graph hubs                                    # most-connected nodes
/graph clusters                                # community overview
```

## How It Works

All indexer tools route through toolshed MCP: `run_tool("indexer", "<tool>", {args})`.

The **primary tool** is `code_query` — it does BFS/DFS graph traversal server-side and returns a compact text summary of nodes + edges within a token budget. One call answers most questions.

### Step 1 — Resolve project name

```
PROJECT = basename of current working directory
```

### Step 2 — Read project context via MCP resource (optional, ~150 tokens)

Before querying, read the compact project summary to understand graph size and top hubs:
```
ReadMcpResourceTool("indexer://project/PROJECT/context")
```

For cluster overview (~300 tokens): `ReadMcpResourceTool("indexer://project/PROJECT/clusters")`
For hub details (~200 tokens): `ReadMcpResourceTool("indexer://project/PROJECT/hubs")`

These replace reading the full GRAPH_REPORT.md (~2000 tokens). Only read resources when you need orientation — skip for targeted queries where you already know what to look for.

### Step 3 — Call code_query (default for most questions)

```
run_tool("indexer", "code_query", {
  "project": "PROJECT",
  "question": "the user's question or key terms",
  "depth": 2,
  "budget": 2000
})
```

Returns pre-formatted text: scored seed nodes → BFS traversal → NODES list with file:line → EDGES list with relationship types. All in ~1500-2000 tokens.

Seed selection uses hybrid BM25 + vector similarity search. Semantic queries like "authentication flow" will find JWT/login symbols even without exact substring matches.

The `code_query` result IS the answer for most questions. Parse the NODES and EDGES, present them as a call chain or dependency tree, and you're done. No need to read source files or make additional tool calls.

### Step 4 — Use targeted tools only when needed

For specific structural queries, these single-purpose tools are more precise:

| Query type | Tool | When to prefer over code_query |
|-----------|------|-------------------------------|
| "what calls X" | `code_callers(project, file, function, depth)` | When you know the exact function and want exhaustive callers |
| "blast radius of X" | `code_blast_radius(project, file, function, depth)` | Complete list of all transitive dependents |
| "path from A to B" | `code_path(project, from_file, from_name, to_file, to_name)` | Exact shortest path between two known nodes |
| "top hubs" | `code_hubs(project, top_n)` | Most-connected nodes by degree |
| "clusters" | `code_clusters(project)` | All communities with labels |
| "cluster members" | `code_cluster_members(project, label)` | All nodes in a specific cluster |
| "who reads X" | `code_readers(project, file, field)` | Who accesses a specific field |
| "find X" | `code_search(project, query, limit)` | Fuzzy search by name or path |

These each return structured metadata (`{name, file, line}`). Present the results directly — **do not read each returned file**. The metadata IS the answer.

### Step 5 — Read source only for "how does X work" questions

Only read source when the user needs to understand **implementation logic**, not **structure/connections**.

- Read at most **1 file** — the target the user asked about
- For structural queries (callers, blast radius, hubs, clusters, paths), **never read source** — present index metadata directly

### Step 6 — Answer with citations

Format results as visual graph structures:

```
Scheduler.start (lib/scheduler.ts:78)
  → startAIWeeklyRewards (lib/scheduler.ts:301)
    → calculateWeeklyAIRewards (lib/ai-gateway.ts:0)
      → AIUsageLog (models/AIUsageLog.ts:0)
```

For blast radius, show the tree:
```
jwt-auth.ts — 59 downstream dependents
  ├── app/api/admin/rewards/route.ts
  ├── app/api/auth/login/route.ts
  ├── tests/integration/admin-protection.test.ts
  └── ... (56 more)
```

## Token budget

The whole point of this skill is efficiency. Target:
- **1 tool call** via `code_query` for most questions (~1500 tokens returned)
- **1-2 tool calls** for targeted queries (blast_radius, callers, etc.)
- **0 source file reads** for structural queries
- **1 source file read max** for "how does X work" questions

If you're making more than 3 tool calls total, you're doing it wrong. Use `code_query` instead of chaining search → callers → readers → blast_radius.

## Proactive triggering

Trigger automatically when the user asks about codebase structure/architecture and `.claude/GRAPH_REPORT.md` exists. Do NOT trigger for direct edits, test runs, or debugging.

## Honesty rules

- Never invent connections. If the graph returns nothing, say so.
- Never fall back to grep/find/glob.
- Always cite file:line from the index metadata.
- If `GRAPH_REPORT.md` is missing, say: "No graph index found."
