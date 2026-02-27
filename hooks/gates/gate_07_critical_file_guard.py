"""Gate 7: CRITICAL FILE PROTECTION (Tier 3 — Domain-specific)

High-risk files (database configs, auth modules, payment code, CI/CD pipelines,
etc.) require a memory query before editing. This prevents blind edits to
the most dangerous parts of the codebase.

Customize CRITICAL_PATTERNS for your project.
"""

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.gate_result import GateResult
from shared.state import get_memory_last_queried

GATE_NAME = "GATE 7: CRITICAL FILE GUARD"

# File patterns considered high-risk (customize per project)
CRITICAL_PATTERNS = [
    (r"(models|schema|migration).*\.py$", "Database models"),
    (r"(auth|login|session|jwt|oauth).*\.py$", "Authentication"),
    (r"(payment|billing|stripe|charge).*\.py$", "Payment processing"),
    (r"\.env$", "Environment variables"),
    (r"docker-compose.*\.ya?ml$", "Docker orchestration"),
    (r"Dockerfile$", "Docker build"),
    (r"\.github/workflows/.*\.ya?ml$", "CI/CD pipeline"),
    (r"(nginx|apache|caddy).*\.conf$", "Web server config"),
    (r"(settings|config)\.py$", "App settings"),
    (r"manage\.py$", "Django management"),
    (r"requirements\.txt$", "Python dependencies"),
    (r"package\.json$", "Node dependencies"),
    (r"Cargo\.toml$", "Rust dependencies"),
    (r"\.ssh/", "SSH directory"),
    (r"authorized_keys$", "SSH authorized keys"),
    (r"id_(rsa|ed25519|ecdsa|dsa)(\.pub)?$", "SSH key files"),
    (r"sudoers", "Sudo configuration"),
    (r"crontab$", "Cron schedule"),
    (r"cron\.d/", "Cron directory"),
    (r"\.pem$", "PEM certificates"),
    (r"\.key$", "Private key files"),
    (r"\.pgpass$", "PostgreSQL password file"),
    (r"\.aws/credentials$", "AWS credentials"),
    (r"\.docker/config\.json$", "Docker auth config"),
    (r"sudoers\.d/", "Sudo rules directory"),
    (r"\.netrc$", "FTP/HTTP password file"),
    (r"\.npmrc$", "npm auth tokens"),
    (r"\.pypirc$", "PyPI auth tokens"),
    # Self-Healing Framework core files (self-protection)
    (r"hooks/enforcer\.py$", "Framework core"),
    (r"hooks/shared/state\.py$", "Framework state"),
    (r"hooks/gates/gate_\d+.*\.py$", "Gate file"),
    (r"hooks/tracker\.py$", "Framework tracker"),
    (r"hooks/boot\.py$", "Framework boot"),
    (r"hooks/memory_server\.py$", "Memory server"),
    (r"hooks/pre_compact\.py$", "Framework compaction"),
    (r"dashboard/server\.py$", "Dashboard backend"),
]


def check(tool_name, tool_input, state, event_type="PreToolUse"):
    if event_type != "PreToolUse":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if tool_name not in ("Edit", "Write", "NotebookEdit"):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if not isinstance(tool_input, dict):
        tool_input = {}

    file_path = tool_input.get("file_path", "") or tool_input.get("notebook_path", "")
    basename = os.path.basename(file_path)

    # Check if file matches critical patterns
    matched_category = None
    for pattern, category in CRITICAL_PATTERNS:
        if re.search(pattern, file_path, re.IGNORECASE):
            matched_category = category
            break

    if not matched_category:
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Critical file: require memory query (checks both enforcer state AND MCP sideband file)
    import time
    last_query = get_memory_last_queried(state)
    elapsed = time.time() - last_query

    # Require memory query within last 5 minutes for critical files (aligned with Gate 4)
    if elapsed > 300:
        return GateResult(
            blocked=True,
            message=f"[{GATE_NAME}] BLOCKED: '{basename}' is a critical file ({matched_category}). "
                    f"Query memory about this file/component before editing. Use search_knowledge() first.",
            gate_name=GATE_NAME,
            severity="critical",
        )

    return GateResult(blocked=False, gate_name=GATE_NAME)
