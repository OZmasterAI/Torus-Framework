# /explore — Interactive Codebase Deep-Dive

## When to use
When the user says "explore", "understand", "trace", "how does", "show me", "find all", "architecture", "flow", or wants to understand how a codebase, module, function, or data flow works.

Complements `/deep-dive` (memory-only retrieval) by doing **real-time codebase exploration** with live file reads, grep, and call tracing.

## Steps

### 1. MEMORY CHECK
- `search_knowledge("[topic or codebase area]")` — check for prior explorations
- `search_knowledge("[topic]", mode="all")` — also includes auto-captured observations
- If prior exploration exists, present it and ask if the user wants a fresh look or to build on it

### 2. SCOPE
- Clarify what the user wants to understand:
  - **Function**: How does `functionName()` work? Who calls it? What does it call?
  - **Module**: What does this module do? What are its exports and dependencies?
  - **Data flow**: How does data X get from point A to point B?
  - **Architecture**: What's the high-level structure of this project/subsystem?
- If the scope is unclear, ask the user before proceeding

### 3. MAP STRUCTURE
- **Glob** for matching files: `**/*.py`, `**/module_name/**`, etc.
- **Grep** for key identifiers: function names, class names, imports, config keys
- **Read** key files: entry points, index files, main modules, config files
- Build a mental map of:
  - File tree (relevant subset)
  - Key exports and entry points
  - Configuration and constants

### 4. TRACE FLOW
Choose the appropriate trace based on the scope from Step 2:

**For functions:**
- Find the definition (Grep for `def funcName` / `function funcName` / `class ClassName`)
- Find all callers (Grep for `funcName(`)
- Find all callees (Read the function body, identify function calls within it)
- Note parameters, return values, side effects

**For data flow:**
- Identify the data source (API endpoint, file read, user input, database query)
- Trace transformations: each function that modifies the data
- Identify the data sink (render, write, response, log)
- Note validation, sanitization, and error handling along the path

**For modules/packages:**
- Map imports: who imports this module? What does this module import?
- Identify the public API (exported functions, classes, constants)
- Find tests: `test_*`, `*_test.*`, `*spec.*` files
- Check for docs: README, docstrings, comments

**For architecture:**
- Identify layers: entry points, business logic, data access, utilities
- Map inter-module dependencies
- Find configuration: env vars, config files, constants
- Identify patterns: MVC, event-driven, pipeline, plugin system

### 5. VISUALIZE
Generate ASCII diagrams to show relationships. Choose the appropriate format:

**Dependency tree:**
```
module_a
  ├── module_b
  │   ├── helper_1
  │   └── helper_2
  └── module_c
      └── shared_utils
```

**Call flow:**
```
user_input → validate() → process() → save_to_db()
                              ↓
                         transform()
                              ↓
                         enrich() → external_api()
```

**Data flow:**
```
[API Request] → parse_body() → validate_schema() → business_logic()
                                                        ↓
                                              [DB Write] ← format_record()
                                                        ↓
                                              [API Response] ← serialize()
```

**Architecture overview:**
```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   CLI/API   │────→│  Core Logic  │────→│  Storage    │
│  (entry)    │     │  (process)   │     │  (persist)  │
└─────────────┘     └──────────────┘     └─────────────┘
       ↑                   ↓
┌─────────────┐     ┌──────────────┐
│   Config    │     │   Utilities  │
│  (settings) │     │  (helpers)   │
└─────────────┘     └──────────────┘
```

### 6. SAVE FINDINGS
- `remember_this("[exploration summary]", "exploring [topic/codebase]", "type:learning,area:architecture")`
- Include: key files, relationships discovered, patterns found
- Save diagrams if they capture important architectural knowledge
- Tag with relevant area tags (area:frontend, area:backend, area:infra, etc.)
