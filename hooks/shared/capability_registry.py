"""Agent capability registry for dynamic task routing.

Provides a structured mapping of agent capabilities to task requirements,
enabling intelligent routing of tasks to the most appropriate agent.

Usage:
    from shared.capability_registry import match_agent, recommend_model, get_agent_info
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# AGENT_CAPABILITIES
# Each agent entry describes:
#   - description: human-readable summary
#   - skills:      list of capability tags the agent excels at
#   - preferred_model: default model tier for this agent ("haiku", "sonnet", "opus")
#   - max_complexity: 1-5 scale (5 = handles the most complex tasks)
#   - can_delegate: True if the agent may spawn sub-agents
# ---------------------------------------------------------------------------
AGENT_CAPABILITIES: dict[str, dict] = {
    "researcher": {
        "description": "Searches external sources, reads docs, and synthesises findings.",
        "skills": ["research", "search", "summarise", "read-docs", "fact-check"],
        "preferred_model": "haiku",
        "max_complexity": 3,
        "can_delegate": False,
    },
    "builder": {
        "description": "Implements features, writes production code, and ships changes.",
        "skills": ["implement", "code", "write-file", "edit-file", "debug", "refactor"],
        "preferred_model": "sonnet",
        "max_complexity": 5,
        "can_delegate": True,
    },
    "auditor": {
        "description": "Inspects code and infrastructure for security and compliance issues.",
        "skills": ["security", "audit", "compliance", "vulnerability-scan", "policy-check"],
        "preferred_model": "sonnet",
        "max_complexity": 4,
        "can_delegate": False,
    },
    "code-reviewer": {
        "description": "Reviews pull requests and diffs for correctness and style.",
        "skills": ["review", "code-quality", "style", "pr-review", "static-analysis"],
        "preferred_model": "sonnet",
        "max_complexity": 4,
        "can_delegate": False,
    },
    "performance-analyzer": {
        "description": "Profiles execution, identifies bottlenecks, and recommends optimisations.",
        "skills": ["profiling", "benchmark", "latency", "throughput", "memory-analysis"],
        "preferred_model": "sonnet",
        "max_complexity": 4,
        "can_delegate": False,
    },
    "explorer": {
        "description": "Maps unknown codebases, traces call graphs, and documents structure.",
        "skills": ["explore", "map-codebase", "trace", "read-docs", "discovery"],
        "preferred_model": "haiku",
        "max_complexity": 3,
        "can_delegate": False,
    },
    "test-writer": {
        "description": "Authors unit, integration, and property-based tests.",
        "skills": ["test", "write-tests", "coverage", "mocking", "assertions"],
        "preferred_model": "sonnet",
        "max_complexity": 4,
        "can_delegate": False,
    },
    "stress-tester": {
        "description": "Runs load tests, fuzzing campaigns, and chaos experiments.",
        "skills": ["load-test", "fuzz", "chaos", "stress", "reliability"],
        "preferred_model": "haiku",
        "max_complexity": 3,
        "can_delegate": False,
    },
    "team-lead": {
        "description": "Orchestrates multi-agent teams, plans waves, and resolves conflicts.",
        "skills": ["orchestrate", "plan", "delegate", "coordinate", "prioritise"],
        "preferred_model": "opus",
        "max_complexity": 5,
        "can_delegate": True,
    },
    "optimizer": {
        "description": "Rewrites hot paths, tunes algorithms, and reduces resource usage.",
        "skills": ["optimise", "refactor", "algorithm", "complexity-reduction", "performance"],
        "preferred_model": "sonnet",
        "max_complexity": 5,
        "can_delegate": False,
    },
}

# ---------------------------------------------------------------------------
# TASK_REQUIREMENTS
# Each task type maps to:
#   - required_skills: at least one must match an agent's skill list
#   - min_complexity:  agent.max_complexity must be >= this value to qualify
#   - preferred_agents: ordered list of ideal agents (first = best fit)
# ---------------------------------------------------------------------------
TASK_REQUIREMENTS: dict[str, dict] = {
    "feature-implementation": {
        "required_skills": ["implement", "code", "write-file"],
        "min_complexity": 3,
        "preferred_agents": ["builder", "optimizer"],
    },
    "bug-fix": {
        "required_skills": ["debug", "code", "implement"],
        "min_complexity": 2,
        "preferred_agents": ["builder", "code-reviewer"],
    },
    "code-review": {
        "required_skills": ["review", "code-quality", "static-analysis"],
        "min_complexity": 2,
        "preferred_agents": ["code-reviewer", "auditor"],
    },
    "security-audit": {
        "required_skills": ["security", "audit", "vulnerability-scan"],
        "min_complexity": 3,
        "preferred_agents": ["auditor", "code-reviewer"],
    },
    "performance-tuning": {
        "required_skills": ["profiling", "optimise", "benchmark"],
        "min_complexity": 3,
        "preferred_agents": ["performance-analyzer", "optimizer"],
    },
    "test-generation": {
        "required_skills": ["test", "write-tests", "coverage"],
        "min_complexity": 2,
        "preferred_agents": ["test-writer", "builder"],
    },
    "research": {
        "required_skills": ["research", "search", "summarise"],
        "min_complexity": 1,
        "preferred_agents": ["researcher", "explorer"],
    },
    "orchestration": {
        "required_skills": ["orchestrate", "plan", "delegate"],
        "min_complexity": 4,
        "preferred_agents": ["team-lead"],
    },
}

# ---------------------------------------------------------------------------
# Model tier -> actual model ID mapping
# ---------------------------------------------------------------------------
_MODEL_IDS: dict[str, str] = {
    "haiku": "claude-haiku-4-5",
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-6",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def match_agent(task_type: str, *, exclude: list[str] | None = None) -> str | None:
    """Return the best agent name for a given task type.

    Selects from TASK_REQUIREMENTS[task_type].preferred_agents in order,
    verifying that each candidate meets the skill and complexity requirements.
    Returns None if the task_type is unknown or no agent qualifies.

    Args:
        task_type:  Key from TASK_REQUIREMENTS (e.g. "bug-fix").
        exclude:    Agent names to skip (e.g. already-busy agents).

    Returns:
        Name of the best matching agent, or None.
    """
    if task_type not in TASK_REQUIREMENTS:
        return None

    req = TASK_REQUIREMENTS[task_type]
    required_skills: list[str] = req["required_skills"]
    min_complexity: int = req["min_complexity"]
    exclude_set: set[str] = set(exclude or [])

    for agent_name in req["preferred_agents"]:
        if agent_name in exclude_set:
            continue
        agent = AGENT_CAPABILITIES.get(agent_name)
        if agent is None:
            continue
        complexity_ok = agent["max_complexity"] >= min_complexity
        skill_ok = any(s in agent["skills"] for s in required_skills)
        if complexity_ok and skill_ok:
            return agent_name

    # Fallback: scan all agents by score
    best_name: str | None = None
    best_score: int = -1
    for agent_name, agent in AGENT_CAPABILITIES.items():
        if agent_name in exclude_set:
            continue
        if agent["max_complexity"] < min_complexity:
            continue
        skill_matches = sum(1 for s in required_skills if s in agent["skills"])
        if skill_matches > best_score:
            best_score = skill_matches
            best_name = agent_name

    return best_name if best_score > 0 else None


def recommend_model(agent_name: str) -> str:
    """Return the recommended model ID string for the given agent.

    Falls back to sonnet if the agent is unknown.

    Args:
        agent_name: Key from AGENT_CAPABILITIES.

    Returns:
        Full model ID string (e.g. "claude-sonnet-4-6").
    """
    agent = AGENT_CAPABILITIES.get(agent_name)
    if agent is None:
        return _MODEL_IDS["sonnet"]
    tier = agent.get("preferred_model", "sonnet")
    return _MODEL_IDS.get(tier, _MODEL_IDS["sonnet"])


def get_agent_info(agent_name: str) -> dict | None:
    """Return a copy of the capability dict for agent_name, or None if unknown.

    The returned dict includes all fields from AGENT_CAPABILITIES plus a
    derived "model_id" key with the resolved model ID string.

    Args:
        agent_name: Key from AGENT_CAPABILITIES.

    Returns:
        Dict with agent metadata, or None.
    """
    agent = AGENT_CAPABILITIES.get(agent_name)
    if agent is None:
        return None
    result = dict(agent)
    result["model_id"] = _MODEL_IDS.get(agent["preferred_model"], _MODEL_IDS["sonnet"])
    return result
