---
name: create-skill
description: Create new Claude Code skills with best practices. Use when the user wants to create, build, or develop a new skill, or when they mention SKILL.md, skill creation, or custom commands.
user-invocable: true
---

# Create Skill

## Overview

This skill guides you through creating high-quality Claude Code skills following Anthropic's best practices and prompt engineering principles.

## Quick Start

When creating a new skill:

1. **Ask for skill requirements** - Understand what the skill should do
2. **Design the skill structure** - Plan files and progressive disclosure
3. **Write the SKILL.md** - Create the main instruction file
4. **Add reference files** - Create supporting documentation if needed
5. **Test and iterate** - Verify the skill works as expected

## Skill Creation Process

### Step 1: Gather Requirements

Ask the user:
- What should the skill do?
- When should it be triggered (auto-discovery keywords)?
- What tools does it need access to?
- Should it be user-invocable (slash command)?

### Step 2: Create Directory Structure

```
~/.claude/skills/{skill-name}/
├── SKILL.md              # Required: Main instructions
├── reference.md          # Optional: Detailed documentation
├── examples.md           # Optional: Usage examples
└── scripts/              # Optional: Utility scripts
    └── helper.py
```

**Location Guide:**
| Location | Path | Scope |
|:---------|:-----|:------|
| Personal | `~/.claude/skills/` | All your projects |
| Project | `.claude/skills/` | Current repository |

### Step 3: Write SKILL.md

Use this template:

```yaml
---
name: skill-name
description: [Specific description with keywords for auto-discovery. Describe WHAT it does and WHEN to use it.]
user-invocable: true
allowed-tools: [Optional: Tool restrictions]
---

# Skill Title

## Quick Start

[Essential instructions - what Claude needs to know immediately]

## Workflow

[Step-by-step process]

## Examples

[Concrete input/output examples]

## Advanced Features

For detailed reference, see [reference.md](reference.md).
```

## Best Practices Checklist

### Description (Critical for Auto-Discovery)

<good_description>
description: Extract text and tables from PDF files, fill forms, merge documents. Use when working with PDF files or when the user mentions PDFs, forms, or document extraction.
</good_description>

<bad_description>
description: Helps with documents
</bad_description>

**Rules:**
- Include specific keywords users might mention
- State WHAT it does AND WHEN to use it
- Write in third person ("Processes files" not "I process files")
- Be specific, not vague

### Content Guidelines

<conciseness>
- Keep SKILL.md under 500 lines
- Only include what Claude doesn't already know
- Claude is smart - don't over-explain
- Challenge each piece: "Does Claude really need this?"
</conciseness>

<progressive_disclosure>
- Put essential info in SKILL.md
- Link to detailed docs in separate files
- Claude loads additional files only when needed
</progressive_disclosure>

<consistent_terminology>
- Choose one term and stick with it
- "API endpoint" everywhere, not "URL/route/path"
- "Extract" everywhere, not "pull/get/retrieve"
</consistent_terminology>

### Prompt Engineering Principles

<explicit_instructions>
Be direct and explicit. Tell Claude exactly what to do.

LESS EFFECTIVE: "Handle errors appropriately"
MORE EFFECTIVE: "Catch exceptions, log the error message, and return a structured error response with status code and message."
</explicit_instructions>

<provide_context>
Explain WHY, not just WHAT.

LESS EFFECTIVE: "Always validate input"
MORE EFFECTIVE: "Validate input because this data comes from external users and could contain malicious content or unexpected formats."
</provide_context>

<use_examples>
Show concrete input/output pairs:

**Example:**
Input: User request to format date
Output:
```javascript
const formatted = new Intl.DateTimeFormat('en-US').format(date);
```
</use_examples>

<xml_tags>
Use XML tags for structured sections - Claude is fine-tuned to respond to them:

```xml
<task>Description</task>
<constraints>Limits</constraints>
<output_format>Expected format</output_format>
```
</xml_tags>

### Degrees of Freedom

| Level | When to Use | Example |
|:------|:------------|:--------|
| **High** | Multiple approaches valid | General code review guidance |
| **Medium** | Preferred pattern exists | Template with customization |
| **Low** | Consistency critical | Exact script sequences |

### Tool Restrictions

```yaml
allowed-tools: Read, Grep, Glob, Bash(python:*)
```

Common patterns:
- Read-only: `Read, Grep, Glob`
- With Python: `Read, Bash(python:*)`
- Full access: omit `allowed-tools`

## Frontmatter Reference

```yaml
---
name: skill-name                    # Required: Unique identifier
description: Description here       # Required: For auto-discovery
user-invocable: true               # Optional: Show in slash menu (default: true)
disable-model-invocation: false    # Optional: Block Skill tool (default: false)
allowed-tools: Read, Grep          # Optional: Restrict available tools
context: fork                      # Optional: Run in isolated context
agent: Explore                     # Optional: Use specific agent type
hooks:                             # Optional: Lifecycle hooks
  PreToolUse:
    - matcher: "Bash"
      hooks:
        - type: command
          command: "./check.sh"
---
```

## Testing the Skill

After creating the skill:

1. **Test auto-discovery** - Ask Claude something matching the description
2. **Test slash command** - Use `/skill-name` directly
3. **Test with different models** - Haiku needs more guidance, Opus needs less
4. **Iterate based on results** - Refine instructions if needed

## Common Patterns

### Validation Workflow
```markdown
1. Run validation: `script validate input`
2. Review results
3. Fix any issues
4. Re-validate until passing
```

### Multi-Step Process
```markdown
## Workflow
1. [First step]
2. [Second step]
3. [Verification step]
4. [Final step]
```

### Script Integration
```markdown
## Scripts

- `scripts/analyze.py` - Analyzes input
- `scripts/process.py` - Processes data
- `scripts/validate.py` - Validates output

Run scripts, don't load their contents into context.
```

## Additional Resources

For detailed examples and advanced patterns, see:
- [examples.md](examples.md) - Complete skill examples
- [reference.md](reference.md) - Full frontmatter reference
