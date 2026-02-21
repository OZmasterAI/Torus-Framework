---
name: security-scan
description: Run a comprehensive security scan of the framework
user_invocable: true
---

# Security Scan

Run a comprehensive security scan of the Torus framework's gates, hooks, state files, and MCP tools.

## Steps
1. Check all 17 gate files exist and export proper `check()` functions
2. Verify Gate 17 injection defense patterns are up to date
3. Scan MCP tool registrations for description mismatches
4. Check for hardcoded secrets in hooks/shared/*.py
5. Verify state files don't contain sensitive data
6. Check circuit breaker state for stuck-open gates
7. Audit .file_claims.json for stale claims
8. Report findings with severity levels

## Usage
Use this skill to run a security audit of the framework before deploying changes or after adding new components.

Run `python3 /home/crab/.claude/skills/security-scan/scripts/scan.py` for a programmatic scan report.

---

## When to use
When the user says "security scan", "scan for vulnerabilities", "check security", "audit security",
"security audit", "find security issues", or wants to review the framework for risks.

## Commands
- `/security-scan` — Full security audit across all components
- `/security-scan --component mcp|skills|hooks|agents` — Scan a specific component only
- `/security-scan --severity critical|high` — Show only findings at or above severity level

---

## Phase 1: INVENTORY — Catalog All Components

Read the following files to build the component inventory:

**MCP Servers** — from `settings.json`:
```
/home/crab/.claude/settings.json
```
Extract the `mcpServers` block. For each server record:
- Name, command, args, env vars (flag any with secrets/tokens in env)
- Transport type (stdio vs sse vs http)

**Skills** — glob all SKILL.md files:
```
/home/crab/.claude/skills/*/SKILL.md
```
For each skill record: name, trigger phrases, what commands it runs.

**Hooks** — from `settings.json`:
```
/home/crab/.claude/settings.json  →  hooks block
```
For each hook record: event type, matcher, command string.

Also read gate files:
```
/home/crab/.claude/hooks/gates/gate_*.py   (glob)
```

**Agents** — glob all agent definitions:
```
/home/crab/.claude/agents/*.md
```
For each agent record: name, tools list, any capability overrides.

Print a brief inventory summary before proceeding to Phase 2:
```
INVENTORY COMPLETE
  MCP servers:  N
  Skills:       N
  Hooks:        N  (gates: N, other: N)
  Agents:       N
```

---

## Phase 2: SCAN — Check Each Component for Risks

### 2a. MCP Server Risks

For each MCP server in the inventory:

**Injection risks in command/args:**
- Does the `command` or any `args` entry include shell metacharacters (`$`, `` ` ``, `&&`, `||`, `;`, `>`, `<`, `|`) that could be injection vectors?
- Are args constructed from user input without sanitization?
- Flag: **High** if shell metacharacters present, **Medium** if args are dynamic

**Hardcoded secrets:**
- Scan `env` block values for patterns: `sk-`, `ghp_`, `token`, `password`, `secret`, `key`, `api_key`, `Bearer`
- Use regex: `(?i)(secret|token|password|api.?key|bearer)\s*[=:]\s*\S+`
- Flag: **Critical** if secret pattern matches a literal value (not an env var reference like `$VAR`)

**Overly broad filesystem access:**
- Does the server command give access to `/` or `~` without restriction?
- Flag: **Medium** if broad path access granted without need

**Network exposure:**
- Does the server use `sse` or `http` transport vs `stdio`?
- Flag: **Medium** if non-stdio (potential SSRF or network exposure)

### 2b. Hook Command Risks

For each hook entry in settings.json:

**Command injection via hook input:**
- Hook commands receive JSON on stdin. Does the command pipe stdin directly to shell eval or subprocess without validation?
- Check for: `eval`, `exec`, `os.system`, `subprocess.call` with unsanitized stdin data
- Flag: **High** if direct stdin-to-exec path exists

**Overly broad matchers:**
- Does the hook `match` field use `.*` or `*` patterns that catch all tools?
- Flag: **Medium** if matcher is unrestricted; **Info** if restricted to specific tools

**Privilege escalation in hook scripts:**
- Scan hook Python files for `sudo`, `chmod 777`, `setuid`, `os.getuid() == 0`
- Flag: **High** if privilege escalation present

**Gate bypass patterns:**
- Look for `--no-verify`, `sys.exit(0)` in catch blocks that should block, or broad `except: pass`
- Cross-reference with CLAUDE.md rule: `sys.exit(1)` does NOT mechanically block
- Flag: **High** if a gate exits 0/1 when it should exit 2 for blocking

### 2c. Skill Risks

For each SKILL.md file:

**Data exfiltration patterns:**
- Does the skill send data to external URLs (non-local)?
- Look for: `curl`, `wget`, `requests.post`, `fetch(` pointing to non-localhost
- Flag: **High** if external data transmission found without clear justification

**Unvalidated shell execution:**
- Does the skill run user-provided input directly in bash commands?
- Look for patterns like: `Bash(f"... {user_input} ...")`
- Flag: **High** if user input flows unvalidated into shell commands

**Overly broad file access:**
- Does the skill read files outside `/home/crab/.claude/` without justification?
- Flag: **Medium** if reads system files (`/etc/`, `/proc/`), **Low** for home dir

**Secrets in skill scripts:**
- Scan any scripts in `skills/*/scripts/` for hardcoded credentials
- Flag: **Critical** if found

### 2d. Agent Risks

For each agent `.md` file:

**Permission escalation:**
- Does the agent's tools list include `Bash` with no restrictions?
- Does the agent claim capabilities beyond what its role needs?
- Flag: **High** if an agent labeled "read-only" has write tools; **Medium** if Bash unrestricted

**Prompt injection surface:**
- Does the agent description instruct it to follow instructions from external sources (web pages, files it reads)?
- Flag: **High** if agent auto-executes instructions from untrusted external content

**Cross-agent trust:**
- Does the agent accept messages from teammates without verifying sender?
- Flag: **Medium** if no sender validation described

---

## Phase 3: ANALYZE — Memory Cross-Reference

Run these memory searches to correlate with known issues:

```
search_knowledge("security vulnerability injection")
search_knowledge("hardcoded secret credential leak")
search_knowledge("gate bypass hook escape")
search_knowledge("agent permission escalation tool abuse")
search_knowledge("MCP server security risk")
```

For each result with relevance > 0.4:
- Note the memory ID, content summary, and which component it relates to
- Include in the report as "Known Issue (from memory)"

Also check if any previous `/security-scan` findings were saved to memory and compare
current findings against them to identify regressions or newly introduced risks.

---

## Phase 4: REPORT — Security Findings Table

Output a formatted security report:

```
╔══════════════════════════════════════════════════════════════════════════════╗
║              SECURITY SCAN REPORT — {DATE}                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

Scanned:  {N} MCP servers | {N} skills | {N} hooks | {N} agents
Findings: {N} Critical | {N} High | {N} Medium | {N} Low | {N} Info

┌──────────────────────┬──────────┬──────────┬───────────────────────────────┬─────────────────────────────────┐
│ Component            │ Type     │ Risk     │ Finding                        │ Recommendation                  │
├──────────────────────┼──────────┼──────────┼───────────────────────────────┼─────────────────────────────────┤
│ mcp/memory           │ MCP      │ Critical │ Hardcoded token in env block   │ Move to env var: $MEMORY_TOKEN  │
│ hooks/gate_02.py     │ Hook     │ High     │ broad except swallows blocks   │ Replace except:pass with reraise│
│ skills/learn         │ Skill    │ Medium   │ Reads external URLs unchecked  │ Validate URL against allowlist  │
│ agents/builder.md    │ Agent    │ Medium   │ Bash tool unrestricted         │ Scope to specific path prefixes │
│ settings.json        │ Hook     │ Low      │ Matcher .* catches all tools   │ Restrict to specific tool list  │
└──────────────────────┴──────────┴──────────┴───────────────────────────────┴─────────────────────────────────┘
```

**Risk Level Definitions:**
- **Critical** — Immediate exploitation possible (hardcoded secrets, RCE paths)
- **High** — Significant risk requiring prompt remediation (injection vectors, gate bypasses)
- **Medium** — Moderate risk, fix in next sprint (overly broad permissions, weak validation)
- **Low** — Minor risk or defense-in-depth improvement (informational policy gaps)
- **Info** — Observation, no immediate action required

If no findings at a risk level, omit that section from the summary count.

**Always show the raw finding**, not just a category label.

---

## Phase 5: REMEDIATE — Specific Fix Guidance

For each Critical or High finding, provide specific remediation:

Format:
```
[CRITICAL] mcp/memory — Hardcoded token
  File:   /home/crab/.claude/settings.json:42
  Fix:    Replace literal "sk-abc123" with environment variable reference
  Code:   "env": { "MEMORY_TOKEN": "$MEMORY_TOKEN" }
  Verify: grep -r "sk-" ~/.claude/settings.json → should return 0 lines

[HIGH] hooks/gate_02.py — Broad except swallows blocking exit
  File:   /home/crab/.claude/hooks/gates/gate_02.py:87
  Fix:    Replace `except: pass` with `except Exception as e: raise`
          Or ensure sys.exit(2) is called inside the except block
  Verify: Run test_framework.py gate_02 tests → all should pass
```

For Medium findings, provide brief guidance:
```
[MEDIUM] agents/builder.md — Unrestricted Bash tool
  Suggestion: Add note to agent instructions restricting Bash to /home/crab/.claude/ paths
  Priority: Next sprint
```

---

## Rules

- **Read-only analysis** — never modify files, settings.json, hooks, or agents during scan
- **Show evidence** — quote the actual risky line/pattern, not just a vague description
- **Risk levels are absolute** — do not downgrade Critical findings because "it's probably fine"
- **Save findings to memory** after generating the report:
  ```
  remember_this(
    content="Security scan {DATE}: {N} Critical, {N} High findings. Top issue: {summary}",
    context="Security audit of Torus framework components",
    tags=["type:learning", "area:security", "security-scan", "priority:high"]
  )
  ```
- If a previous scan exists in memory, note any **regressions** (issues that were fixed but reappeared)
- If **zero findings**: still save to memory with `"Security scan {DATE}: clean — no findings"`
- Do not scan files outside `/home/crab/.claude/` unless the user explicitly requests it

---

## Example Invocation

User: "Run a security scan"

Expected flow:
1. Read settings.json → extract MCP servers and hooks
2. Glob skills/*/SKILL.md → read each
3. Glob agents/*.md → read each
4. Glob hooks/gates/gate_*.py → read each
5. Run memory searches for known issues
6. Generate findings table
7. Generate remediation steps for Critical/High
8. Save summary to memory
9. Present report to user
