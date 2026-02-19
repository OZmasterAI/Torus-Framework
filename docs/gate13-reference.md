# Gate 13: Workspace Isolation — Session Exemption Rules

Gate 13 uses a shared `.file_claims.json` file to prevent two agents editing the same file simultaneously.
Session exemption rules (both the claim-writer in tracker.py and the gate check apply the same logic):

| Agent type | session_id | Writes claims? | Checked by Gate 13? |
|---|---|---|---|
| Main session | `"main"` | No | No — always exempt |
| Task subagent | unique UUID | Yes | Yes |
| Team member agent | unique UUID | Yes | Yes |

The main session is exempt by design — it is the orchestrator and should not be blocked by its own
subagents' claims. Regular Task subagents and team member agents are fully subject to the gate.
Stale claims (>2h) are ignored and cleaned up automatically.
