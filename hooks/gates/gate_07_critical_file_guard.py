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
    r"(models|schema|migration).*\.py$",      # Database models/migrations
    r"(auth|login|session|jwt|oauth).*\.py$",  # Authentication
    r"(payment|billing|stripe|charge).*\.py$", # Payment processing
    r"\.env$",                                 # Environment variables
    r"docker-compose.*\.ya?ml$",              # Docker orchestration
    r"Dockerfile$",                           # Docker build
    r"\.github/workflows/.*\.ya?ml$",         # CI/CD pipelines
    r"(nginx|apache|caddy).*\.conf$",         # Web server config
    r"(settings|config)\.py$",                # App settings
    r"manage\.py$",                           # Django management
    r"requirements\.txt$",                    # Dependencies
    r"package\.json$",                        # Node dependencies
    r"Cargo\.toml$",                          # Rust dependencies
]


def check(tool_name, tool_input, state, event_type="PreToolUse"):
    if event_type != "PreToolUse":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if tool_name not in ("Edit", "Write"):
        return GateResult(blocked=False, gate_name=GATE_NAME)

    file_path = tool_input.get("file_path", "")
    basename = os.path.basename(file_path)

    # Check if file matches critical patterns
    is_critical = False
    for pattern in CRITICAL_PATTERNS:
        if re.search(pattern, file_path, re.IGNORECASE):
            is_critical = True
            break

    if not is_critical:
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Critical file: require memory query (checks both enforcer state AND MCP sideband file)
    import time
    last_query = get_memory_last_queried(state)
    elapsed = time.time() - last_query

    # Require memory query within last 3 minutes for critical files
    if elapsed > 180:
        return GateResult(
            blocked=True,
            message=f"[{GATE_NAME}] BLOCKED: '{basename}' is a critical file. Query memory about this file/component before editing. Use search_knowledge() first.",
            gate_name=GATE_NAME,
        )

    return GateResult(blocked=False, gate_name=GATE_NAME)
