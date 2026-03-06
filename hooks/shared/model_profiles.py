"""Shared model profile definitions for agent model enforcement.

Extracted from gate_10 to avoid boot->gate import coupling.
Used by: boot_pkg/maintenance.py (sync_agent_models), gate_10 (runtime enforcement).
"""

# Agent type -> role mapping
# Roles: planning, research, execution, verification
AGENT_ROLE_MAP = {
    "plan":              "planning",
    "Plan":              "planning",
    "explore":           "research",
    "Explore":           "research",
    "researcher":        "research",
    "claude-code-guide": "research",
    "builder":           "execution",
    "general-purpose":   "execution",
    "Bash":              "execution",
    "statusline-setup":  "execution",
    "debugger":          "execution",
    "stress-tester":     "verification",
    "security":          "verification",
    "perf-analyzer":     "verification",
}

# Profile -> role -> model
MODEL_PROFILES = {
    "quality": {
        "description": "Maximum quality -- opus for planning+execution, sonnet for research+verification",
        "role_models": {"planning": "opus", "research": "sonnet", "execution": "opus", "verification": "sonnet"},
        "warn_on_opus": False,
    },
    "balanced": {
        "description": "Default -- opus for planning, sonnet for research+execution+verification",
        "role_models": {"planning": "opus", "research": "sonnet", "execution": "sonnet", "verification": "sonnet"},
        "warn_on_opus": True,
    },
    "efficient": {
        "description": "Opus planning, sonnet work, haiku verification -- best cost/quality ratio",
        "role_models": {"planning": "opus", "research": "sonnet", "execution": "sonnet", "verification": "haiku"},
        "warn_on_opus": True,
    },
    "lean": {
        "description": "Opus planning only, haiku for all read-only -- minimal spend with smart planning",
        "role_models": {"planning": "opus", "research": "haiku", "execution": "sonnet", "verification": "haiku"},
        "warn_on_opus": True,
    },
    "budget": {
        "description": "Cost-minimizing -- sonnet for planning+execution, haiku for research+verification",
        "role_models": {"planning": "sonnet", "research": "haiku", "execution": "sonnet", "verification": "haiku"},
        "warn_on_opus": True,
    },
}

# Recommended models per agent type (for advisory warnings)
RECOMMENDED_MODELS = {
    "Explore":           {"haiku", "sonnet"},
    "explore":           {"haiku", "sonnet"},
    "Plan":              {"opus", "sonnet"},
    "plan":              {"opus", "sonnet"},
    "general-purpose":   {"sonnet", "opus"},
    "Bash":              {"haiku", "sonnet"},
    "builder":           {"sonnet", "opus"},
    "researcher":        {"haiku", "sonnet"},
    "security":          {"sonnet"},
    "stress-tester":     {"haiku", "sonnet"},
    "perf-analyzer":     {"sonnet"},
    "debugger":          {"sonnet", "opus"},
    "claude-code-guide": {"haiku"},
    "statusline-setup":  {"haiku"},
}

# Human-readable suggestions per agent type (shown in warnings)
MODEL_SUGGESTIONS = {
    "Explore":           "haiku or sonnet (read-only exploration doesn't need opus)",
    "explore":           "haiku or sonnet (read-only exploration doesn't need opus)",
    "Plan":              "opus or sonnet (planning needs strong reasoning for architecture decisions)",
    "plan":              "opus or sonnet (planning needs strong reasoning for architecture decisions)",
    "general-purpose":   "sonnet or opus (needs Edit/Write -- haiku may lack capability)",
    "Bash":              "haiku or sonnet (command execution doesn't need opus)",
    "builder":           "sonnet or opus (full implementation agent needs Edit/Write)",
    "researcher":        "haiku or sonnet (read-only exploration and analysis)",
    "security":          "sonnet (security auditing needs reasoning, not opus-level)",
    "stress-tester":     "haiku or sonnet (test execution doesn't need opus)",
    "perf-analyzer":     "sonnet (profiling needs reasoning, not opus-level)",
    "debugger":          "sonnet or opus (debugging complex issues may need full power)",
    "claude-code-guide": "haiku (documentation lookup only, minimal capability needed)",
    "statusline-setup":  "haiku (simple config file edits only)",
}


def get_model_for_agent(profile_name, agent_name):
    """Return the target model string for an agent under the given profile.

    Returns None if agent_name is not in AGENT_ROLE_MAP.
    """
    role = AGENT_ROLE_MAP.get(agent_name)
    if not role:
        return None
    profile = MODEL_PROFILES.get(profile_name, MODEL_PROFILES["balanced"])
    return profile["role_models"].get(role)
