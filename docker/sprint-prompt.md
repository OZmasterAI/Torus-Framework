You are running in an isolated Docker container with a worktree copy of the Torus framework. Your goal is a self-evolution sprint.

## Context
- You are on branch `evolution-sprint` — a separate git worktree
- Security mode: REFACTOR (you can freely modify framework files)
- Agent Teams: ENABLED (experimental feature)
- Analytics MCP: ENABLED (gate dashboard, health monitor, anomaly detection)
- Dormant skills activated: diagnose, introspect, sprint, super-health, security-scan, refactor, report
- Dormant agents activated: team-lead, code-reviewer, test-writer
- Memory server: running on host at :8741 (shared with main instance)

## Your Mission
Run /super-evolve to analyze the framework and make improvements. Focus areas:

1. **Gate effectiveness** — Use /diagnose to analyze which gates are most/least effective, optimize
2. **Code quality** — Use /review and /refactor on framework files (hooks/shared/, hooks/gates/)
3. **Test coverage** — Use test-writer agent to fill gaps
4. **Security hardening** — Use /security-scan to find and fix vulnerabilities
5. **Performance** — Profile gate execution, find bottlenecks

## Rules
- Save ALL findings and decisions to memory (remember_this) — the main instance will benefit
- Commit meaningful changes with descriptive messages
- Run tests after every change (python3 hooks/test_framework.py)
- Do NOT modify memory_server.py (it runs on host, not in this container)
- You have full edit access to everything else
- Use agent teams for parallel work when possible

## Start
Begin with /super-evolve to get a full picture, then prioritize and execute improvements.
