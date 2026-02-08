# /audit — Full Project Audit

## When to use
When the user says "audit", "review", "check everything", or wants a comprehensive project review.

## Steps
1. **MEMORY CHECK** — deep_query("project issues bugs warnings") for known problems
2. **CODE AUDIT** — Spawn parallel agents for:
   - **Security scan**: Look for hardcoded secrets, SQL injection, XSS, command injection
   - **Dependency check**: Review requirements.txt / package.json for outdated or vulnerable packages
   - **Test coverage**: Run tests and note failures or missing coverage
3. **INFRASTRUCTURE AUDIT**:
   - Check Dockerfile / docker-compose for issues
   - Review environment variables and configs
   - Check for exposed ports or insecure defaults
4. **GATE AUDIT**:
   - Verify all 8 gates are working: run test cases for each gate
   - Check gate state file for anomalies
   - Verify boot sequence works
5. **MEMORY AUDIT**:
   - Check memory_stats() for health
   - Look for stale or contradictory memories
6. **REPORT**:
   - Present findings organized by severity (Critical / Warning / Info)
   - Save audit results to memory with tag "audit"
   - Update LIVE_STATE.json with audit date and findings
