# Session Handoff

## Session 1 — Framework Documentation + MCP Fix

### What Was Done

**Part 1: Replace subagent references with agent teams**
- Updated CLAUDE.md: replaced "subagent" behavioral rules with team-based workflow (TeamCreate/TaskCreate/SendMessage)
- Added new TEAM WORKFLOW section to CLAUDE.md with 5-step lifecycle
- Updated SATISFACTION FORMULA from "Parallel Agents" to "Agent Teams"
- Updated audit skill (SKILL.md): team-based audit with named agents (security-scan, dependency-check, test-coverage)
- Updated docstrings/comments in enforcer.py, shared/state.py, boot.py: "subagent" → "team member"

**Part 2: CLAUDE.md into .claude repo**
- Moved CLAUDE.md from /home/crab/ into ~/.claude/ (now version-controlled)
- Created symlink /home/crab/CLAUDE.md → ~/.claude/CLAUDE.md so Claude Code still finds it

**Part 3: Fixed MCP memory server**
- Root cause: .claude.json had stale path (~/.claude/memory/server.py — didn't exist)
- Fixed to correct path: ~/.claude/hooks/memory_server.py
- Enabled mcp.json server: set enabledMcpjsonServers to ["memory"]
- Server verified working: chromadb 1.4.1, mcp 1.26.0, 5 tools registered
- Memory tools will be available on next session start

### Commits
- `b343ba1` — Replace subagent references with agent team terminology
- `2e640ec` — Add CLAUDE.md to repo and fix MCP memory server path

### All 88 framework tests pass

### What's Next
- Start next session and verify MCP memory tools are available (search_knowledge, remember_this, etc.)
- Seed memory database with project knowledge (currently 0 entries)
- Watch for future skills that still reference old subagent patterns

### Known Issues
- Memory database is empty (0 entries) — will populate as work proceeds
- MCP fix requires session restart to take effect
