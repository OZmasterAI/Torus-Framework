---
name: create-agents
description: Create Claude Code agents (autonomous workers with isolated context and restricted tools). Use when the user wants to create an agent, autonomous worker, isolated task runner, or custom subagent. NOT for skills - agents have tool restrictions and run in isolation.
user-invocable: true
---

# Create Agents

Create **agents** for Claude Code - autonomous workers with isolated context and restricted tool access.

## Agents vs Skills: The Critical Difference

```
┌─────────────────────────────────────────────────────────────────────┐
│                      AGENTS vs SKILLS                               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  SKILL (.claude/skills/)          AGENT (.claude/agents/)           │
│  ────────────────────────         ─────────────────────────         │
│  • SKILL.md file                  • {name}.md file                  │
│  • Shared conversation context    • ISOLATED context (fork)         │
│  • All tools by default           • RESTRICTED tools (required)     │
│  • Adds knowledge to Claude       • Separate worker instance        │
│  • allowed-tools: optional        • tools: REQUIRED                 │
│  • Instructions/guidance          • Autonomous task execution       │
│                                                                     │
│  Example: changelog-writer        Example: code-reviewer            │
│  → "How to write changelogs"      → "Review this code separately"   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

<important>
If it doesn't have restricted tools → it's a SKILL, not an agent.
If it shares the main context → it's a SKILL, not an agent.
</important>

## Agent File Location

```
~/.claude/agents/{name}.md     # Personal (all projects)
.claude/agents/{name}.md       # Project-specific (git-tracked)
```

## Agent Frontmatter Schema

```yaml
---
name: agent-name                    # Required: lowercase + hyphens, max 64 chars
description: What it does and when  # Required: max 1024 chars, specific triggers
tools: Tool1, Tool2                 # Required: restricted tool list
model: inherit                      # Optional: haiku, sonnet, opus, inherit
permissionMode: default             # Optional: default, acceptEdits, bypassPermissions
skills: skill1, skill2              # Optional: skills to load into agent
hooks:                              # Optional: lifecycle hooks
  PreToolUse: [...]
  PostToolUse: [...]
  Stop: [...]
---
```

## Workflow: Creating an Agent

### Step 1: Determine if it's really an agent

Ask yourself:
1. Does it need **isolated context**? (won't clutter main conversation)
2. Does it need **restricted tools**? (security, focus)
3. Is it a **delegated task**? (not just guidance)

If NO to all → create a Skill instead.

### Step 2: Gather requirements

<questions>
Use AskUserQuestion to clarify:

1. **Purpose**: What task should this agent perform?
2. **Tools needed**: Which tools are required?
   - Read-only: `Read, Grep, Glob`
   - With editing: `Read, Grep, Glob, Edit`
   - With execution: `Read, Grep, Glob, Bash`
   - With web access: `Read, Grep, Glob, WebSearch, WebFetch`
3. **Model**: Haiku (fast/cheap), Sonnet (balanced), Opus (best)?
4. **Invocation**: User-triggered or Claude-delegated?
</questions>

### Step 3: Design the agent prompt

Apply prompt engineering best practices:

<prompt_structure>
1. **Role/Identity**: Who is this agent?
2. **Context**: What background does it need?
3. **Task**: What does it do?
4. **Process**: Step-by-step workflow
5. **Constraints**: What it must/must not do
6. **Output Format**: Expected response structure
</prompt_structure>

### Step 4: Write the agent file

Create `~/.claude/agents/{name}.md` with:

```markdown
---
name: {name}
description: {specific description with trigger keywords}
tools: {minimal required tools}
model: {haiku|sonnet|opus|inherit}
---

{Agent instructions following prompt engineering best practices}
```

### Step 5: Test and iterate

1. Invoke: Ask Claude to use the agent or trigger via description
2. Verify: Check tool restrictions work
3. Iterate: Refine based on behavior

## Tool Restriction Patterns

<tool_patterns>
| Use Case | Tools | Rationale |
|:---------|:------|:----------|
| Code analysis (read-only) | `Read, Grep, Glob` | No modifications |
| Code review with suggestions | `Read, Grep, Glob` | Analysis only |
| Code modifications | `Read, Grep, Glob, Edit` | Can edit files |
| File creation | `Read, Grep, Glob, Write` | Can create new files |
| Test runner | `Read, Grep, Glob, Bash` | Execute tests |
| Git operations (read) | `Read, Bash(git status, git log, git diff)` | Restricted bash |
| Git operations (write) | `Read, Bash(git add, git commit, git push)` | Git commands only |
| Research | `Read, Grep, Glob, WebSearch, WebFetch` | Web access |
| Documentation | `Read, Grep, Glob, Write` | Generate docs |
</tool_patterns>

### Bash Restriction Patterns

```yaml
# Only specific commands
tools: Bash(npm test, npm run lint)

# Command prefixes with wildcards
tools: Bash(git:*, npm:*, python:*)

# Read-only git
tools: Bash(git status, git log, git diff, git branch)
```

## Prompt Engineering Best Practices

### Use XML Tags for Structure

```markdown
<context>
Background information the agent needs
</context>

<instructions>
Step-by-step process:
1. First step
2. Second step
3. Third step
</instructions>

<constraints>
- Must do X
- Must NOT do Y
- Always Z
</constraints>

<output_format>
Expected response structure
</output_format>
```

### Provide Examples (Multishot)

```markdown
<examples>
<example>
<input>User asks to review auth.js</input>
<output>
## Code Review: auth.js

### Critical Issues
- Line 45: SQL injection vulnerability

### Recommendations
- Add input validation
</output>
</example>
</examples>
```

### Motivate Rules (Explain Why)

```markdown
<!-- BAD: bare rule -->
Never use console.log

<!-- GOOD: motivated rule -->
Avoid console.log in production code because it can expose
sensitive data and impacts performance. Use a structured
logger instead.
```

### Be Explicit and Direct

```markdown
<!-- BAD: vague -->
Review the code and give feedback

<!-- GOOD: explicit -->
Review the code for:
1. Security vulnerabilities (OWASP Top 10)
2. Performance issues (O(n²) loops, memory leaks)
3. Code style violations

For each issue found, provide:
- File and line number
- Severity (Critical/Warning/Info)
- Specific fix recommendation
```

### Allow Uncertainty

```markdown
<constraints>
- If you're unsure about something, say so rather than guessing
- Flag ambiguous requirements with [NEEDS CLARIFICATION]
- Ask for more context if the task is unclear
</constraints>
```

## Agent Templates

### Read-Only Analyzer

```markdown
---
name: code-analyzer
description: Analyze code for quality, security, and performance issues. Use when asked to review, audit, or analyze code quality without making changes.
tools: Read, Grep, Glob
model: sonnet
---

You are a senior code analyst specializing in code quality and security.

<context>
You analyze code without making modifications. Your role is to identify
issues, explain their impact, and recommend fixes.
</context>

<instructions>
When analyzing code:
1. Read the target files thoroughly
2. Identify issues by category (security, performance, style)
3. Prioritize by severity (Critical > Warning > Info)
4. Provide specific, actionable recommendations
</instructions>

<output_format>
## Analysis: {filename}

### Critical Issues
- **[Line X]** {Issue description}
  - Impact: {What could go wrong}
  - Fix: {Specific recommendation}

### Warnings
- **[Line X]** {Issue description}

### Suggestions
- {General improvement ideas}
</output_format>

<constraints>
- Do NOT modify any files
- Do NOT execute any commands
- Focus on actionable, specific feedback
- If unsure about severity, err on the side of caution
</constraints>
```

### Code Modifier

```markdown
---
name: code-fixer
description: Fix code issues identified during review. Use when asked to fix, repair, or correct code problems.
tools: Read, Grep, Glob, Edit
model: sonnet
---

You are a code repair specialist who fixes issues precisely and safely.

<context>
You fix code issues by making minimal, targeted changes. You prioritize
correctness and avoid unnecessary modifications.
</context>

<instructions>
When fixing code:
1. Read the file to understand context
2. Identify the specific issue to fix
3. Make the minimal change needed
4. Verify the fix doesn't break other code
</instructions>

<constraints>
- Make MINIMAL changes - fix only what's broken
- Do NOT refactor unrelated code
- Do NOT add features beyond the fix
- Preserve existing code style
- If a fix is risky, explain the risk first
</constraints>

<examples>
<example>
<issue>SQL injection in query</issue>
<fix>
Replace string concatenation with parameterized query:
```python
# Before
cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")

# After
cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
```
</fix>
</example>
</examples>
```

### Test Runner

```markdown
---
name: test-runner
description: Run tests and analyze results. Use when asked to run tests, check test coverage, or verify code changes.
tools: Read, Grep, Glob, Bash(npm test, pytest, go test, cargo test)
model: haiku
---

You are a test execution specialist.

<instructions>
1. Detect the test framework from project files
2. Run the appropriate test command
3. Parse and summarize results
4. For failures, analyze the cause and suggest fixes
</instructions>

<framework_detection>
| Files | Framework | Command |
|:------|:----------|:--------|
| package.json with jest | Jest | `npm test` |
| pytest.ini, conftest.py | Pytest | `pytest -v` |
| go.mod | Go | `go test ./...` |
| Cargo.toml | Rust | `cargo test` |
</framework_detection>

<output_format>
## Test Results

**Status**: {PASS/FAIL}
**Passed**: {X}/{Total}
**Failed**: {Y}
**Duration**: {time}

### Failures
{For each failure:}
- **{test_name}**: {error_message}
  - Cause: {likely reason}
  - Fix: {suggestion}
</output_format>
```

### Researcher

```markdown
---
name: researcher
description: Research topics using web search and documentation. Use when asked to find information, research solutions, or look up documentation.
tools: Read, Grep, Glob, WebSearch, WebFetch
model: sonnet
---

You are a technical researcher who finds accurate, up-to-date information.

<instructions>
1. Understand the research question
2. Search the codebase first for existing solutions
3. If needed, search the web for documentation/solutions
4. Synthesize findings with clear sources
</instructions>

<constraints>
- Always cite sources with URLs
- Prefer official documentation over blog posts
- Indicate confidence level for each finding
- Flag outdated information (check dates)
</constraints>

<output_format>
## Research: {topic}

### Summary
{1-2 paragraph synthesis}

### Findings

**{Finding 1}**
- Source: [{title}]({url})
- Confidence: {High/Medium/Low}
- Details: {explanation}

### Recommendations
{Based on research, what should be done}

### Sources
- [{title}]({url})
- [{title}]({url})
</output_format>
```

## Common Mistakes to Avoid

<anti_patterns>
**1. No tool restrictions**
```yaml
# BAD - this is a skill, not an agent
---
name: my-agent
description: Does stuff
---
```

**2. Overly broad tools**
```yaml
# BAD - too permissive
tools: Read, Write, Edit, Bash, WebSearch, WebFetch, Task
```

**3. Vague description**
```yaml
# BAD - won't trigger correctly
description: Helps with code

# GOOD - specific triggers
description: Review Python code for security vulnerabilities, performance issues, and PEP8 compliance. Use when asked to review, audit, or check Python code quality.
```

**4. Missing constraints**
```markdown
# BAD - no guardrails
Do whatever the user asks

# GOOD - clear boundaries
<constraints>
- Only analyze, never modify
- Ask for clarification if task is ambiguous
- Flag security concerns immediately
</constraints>
```

**5. No examples**
```markdown
# BAD - abstract instructions only
Analyze the code and report issues

# GOOD - concrete examples
<examples>
<example>
<input>Review auth.py</input>
<output>
## Security Issues
- **Line 23**: Hardcoded password
  - Severity: Critical
  - Fix: Use environment variable
</output>
</example>
</examples>
```
</anti_patterns>

## Post-Creation Checklist

After creating an agent, verify:

<checklist>
- [ ] File is in `~/.claude/agents/{name}.md` or `.claude/agents/{name}.md`
- [ ] `name` is lowercase with hyphens only
- [ ] `description` includes specific trigger keywords
- [ ] `tools` field is present and minimal
- [ ] Instructions use XML tags for structure
- [ ] Constraints are explicit
- [ ] Examples are provided for complex tasks
- [ ] Agent can be invoked and works correctly
</checklist>

## References

For detailed documentation:
- [reference.md](reference.md) - Complete frontmatter schema
- [templates.md](templates.md) - More agent templates
- [examples.md](examples.md) - Real-world agent examples
