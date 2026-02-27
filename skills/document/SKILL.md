# /document — Auto-Generate and Maintain Documentation

## When to use
When the user says "document", "docs", "docstring", "README", "API docs", "architecture", "changelog", or wants to create, update, or fill gaps in project documentation.

Complements `/explore` (understanding code) by converting that understanding into **persistent, readable documentation**.

## Steps

### 1. MEMORY CHECK
- `search_knowledge("documentation")` — find prior documentation decisions and patterns
- `search_knowledge("[project name] conventions")` — find project-specific style rules
- `search_knowledge("type:decision area:docs")` — find past documentation choices
- If documentation patterns exist, follow them for consistency

### 2. DETECT GAPS
Scan the project for missing or outdated documentation:

**Check for:**
- **README.md** — Does it exist? Is it up to date? Does it cover setup, usage, architecture?
- **Docstrings** — Scan public functions/classes for missing docstrings
  - Grep for `def ` and `class ` definitions, check if preceded by docstrings
- **API documentation** — Are endpoints documented? Are request/response schemas described?
- **CHANGELOG** — Does one exist? Is it current with recent changes?
- **Configuration docs** — Are environment variables, config files, and settings documented?
- **Architecture docs** — Is the high-level structure documented anywhere?

Present the gap analysis to the user:
```
Documentation gaps found:
  [x] README.md — exists but missing architecture section
  [ ] API docs — no endpoint documentation found
  [x] Docstrings — 12/30 public functions have docstrings (40%)
  [ ] CHANGELOG — not found
  [x] Config — .env.example exists with comments
```

Ask the user which gaps to fill.

### 3. ANALYZE CODE
For the selected documentation targets, extract information from the code:

**For README/setup docs:**
- Find entry points (`main.py`, `index.js`, `Makefile`, `package.json` scripts)
- Identify dependencies (requirements.txt, package.json, go.mod)
- Find configuration (env vars, config files, CLI arguments)
- Check for Docker/container setup

**For API documentation:**
- Find route/endpoint definitions (Flask routes, Express handlers, API decorators)
- Extract request parameters, body schemas, response formats
- Identify authentication/authorization requirements
- Find error response patterns

**For docstrings:**
- Read each undocumented public function/class
- Analyze parameters, return types, side effects, exceptions
- Check for existing docstring style in the project (Google, NumPy, reST)
- Match the existing convention

**For architecture docs:**
- Map module structure and dependencies
- Identify layers (entry, business logic, data, utilities)
- Find key patterns (MVC, event-driven, pipeline, plugin)
- Use `/explore` visualization patterns for ASCII diagrams

### 4. GENERATE
Create documentation matching the project's conventions:

**README sections** (as needed):
- Project title and description
- Prerequisites and installation
- Quick start / usage examples
- Configuration reference
- Architecture overview (with ASCII diagram)
- Contributing guidelines
- License

**Docstrings** (match project style):
```python
# Google style (default if no convention detected)
def function_name(param1: str, param2: int) -> bool:
    """Brief description of what the function does.

    Args:
        param1: Description of param1.
        param2: Description of param2.

    Returns:
        Description of return value.

    Raises:
        ValueError: When param1 is empty.
    """
```

**API documentation:**
```
## POST /api/endpoint
Description of what this endpoint does.

**Request:**
- Header: `Authorization: Bearer <token>`
- Body: `{ "field": "value" }`

**Response (200):**
`{ "result": "value" }`

**Errors:**
- 400: Invalid request body
- 401: Missing or invalid token
```

**Architecture diagrams** (ASCII, using `/explore` patterns):
```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   CLI/API   │────>│  Core Logic  │────>│  Storage    │
└─────────────┘     └──────────────┘     └─────────────┘
```

### 5. REVIEW
**NEVER auto-save documentation without user approval.**

- Present all generated documentation to the user
- Show exactly where each piece will be written (file path, location in file)
- Ask for feedback and refinements:
  - "Does this accurately describe the behavior?"
  - "Should I adjust the level of detail?"
  - "Any sections to add or remove?"
- Iterate on feedback until the user approves
- Only proceed to write after explicit approval

### 6. SAVE
After user approval:

- Write the approved documentation to the appropriate files
- For docstrings, use Edit to insert them at the correct locations
- For new files (README, CHANGELOG), use Write
- Run any doc generation tools if configured (Sphinx, JSDoc, etc.)
- `remember_this("[docs generated: summary]", "documenting [project/module]", "type:feature,area:docs,outcome:success")`
- Include: what was documented, conventions followed, files created/modified
