"""Agent capability registry for dynamic task routing and access control.

Provides a structured mapping of agent capabilities to task requirements,
enabling intelligent routing of tasks to the most appropriate agent.
Also provides an ACL subsystem for per-agent-type permission enforcement.

Usage:
    from shared.capability_registry import (
        match_agent, recommend_model, get_agent_info,
        define_agent_acl, check_agent_permission,
    )
"""

from __future__ import annotations

import fnmatch

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
# AGENT_ACLS
# Per-agent-type access control lists.
# Each entry describes:
#   - allowed_tools:  explicit allow-list of tool names ("*" = all tools)
#   - denied_tools:   deny-list evaluated AFTER allowed_tools
#                     (supports fnmatch patterns)
#   - allowed_paths:  list of fnmatch path patterns the agent may access
#                     ("*" = any path)
#
# Evaluation order: denied_tools > allowed_tools > denied by default.
# Path check is applied only when a file_path is provided to
# check_agent_permission(); if no path is specified it is not evaluated.
# ---------------------------------------------------------------------------
AGENT_ACLS: dict[str, dict] = {
    # Explore / Plan agents — read-only: may not write, edit, or execute.
    "explorer": {
        "allowed_tools": ["Read", "Glob", "Grep", "mcp__memory__search_knowledge",
                          "mcp__memory__get_memory"],
        "denied_tools": ["Edit", "Write", "NotebookEdit", "Bash", "Task"],
        "allowed_paths": ["*"],
    },
    "researcher": {
        "allowed_tools": ["Read", "Glob", "Grep", "mcp__memory__search_knowledge",
                          "mcp__memory__get_memory", "mcp__memory__remember_this",
                          "WebSearch", "WebFetch"],
        "denied_tools": ["Edit", "Write", "NotebookEdit", "Bash"],
        "allowed_paths": ["*"],
    },
    # Builder — full access, but hard-block destructive shell patterns.
    "builder": {
        "allowed_tools": ["*"],
        "denied_tools": [],          # path-level rm -rf guard applied in check
        "allowed_paths": ["*"],
    },
    # Bash / shell execution agent — no destructive filesystem commands.
    "bash": {
        "allowed_tools": ["Bash", "Read", "Glob", "Grep"],
        "denied_tools": [],          # rm -rf guard enforced in check_agent_permission
        "allowed_paths": ["*"],
    },
    # Auditor — read + memory write, no code modification.
    "auditor": {
        "allowed_tools": ["Read", "Glob", "Grep", "Bash",
                          "mcp__memory__search_knowledge",
                          "mcp__memory__get_memory",
                          "mcp__memory__remember_this"],
        "denied_tools": ["Edit", "Write", "NotebookEdit"],
        "allowed_paths": ["*"],
    },
    # Code reviewer — read + memory, no writes.
    "code-reviewer": {
        "allowed_tools": ["Read", "Glob", "Grep",
                          "mcp__memory__search_knowledge",
                          "mcp__memory__get_memory",
                          "mcp__memory__remember_this"],
        "denied_tools": ["Edit", "Write", "NotebookEdit", "Bash"],
        "allowed_paths": ["*"],
    },
    # Team lead — full orchestration, no direct file edits (delegates to builders).
    "team-lead": {
        "allowed_tools": ["*"],
        "denied_tools": ["Edit", "Write", "NotebookEdit"],
        "allowed_paths": ["*"],
    },
    # Test writer — may write/edit test files only.
    "test-writer": {
        "allowed_tools": ["Read", "Glob", "Grep", "Edit", "Write", "Bash",
                          "mcp__memory__search_knowledge",
                          "mcp__memory__get_memory",
                          "mcp__memory__remember_this"],
        "denied_tools": [],
        "allowed_paths": ["*/test*", "*/tests/*", "*/spec*", "*_test.py",
                          "*_spec.py", "test_*.py"],
    },
    # Stress tester — Bash execution, no writes to source.
    "stress-tester": {
        "allowed_tools": ["Bash", "Read", "Glob", "Grep"],
        "denied_tools": ["Edit", "Write", "NotebookEdit"],
        "allowed_paths": ["*"],
    },
    # Performance analyzer — read + run benchmarks, no source writes.
    "performance-analyzer": {
        "allowed_tools": ["Bash", "Read", "Glob", "Grep",
                          "mcp__memory__search_knowledge",
                          "mcp__memory__get_memory",
                          "mcp__memory__remember_this"],
        "denied_tools": ["Edit", "Write", "NotebookEdit"],
        "allowed_paths": ["*"],
    },
    # Optimizer — full write access (refactors production code).
    "optimizer": {
        "allowed_tools": ["*"],
        "denied_tools": [],
        "allowed_paths": ["*"],
    },
}

# Runtime-registered ACL overrides (populated via define_agent_acl).
_ACL_OVERRIDES: dict[str, dict] = {}

# Shell command fragments that are always blocked for the "bash" agent type
# and any agent that calls Bash (enforced as a belt-and-suspenders guard).
_DESTRUCTIVE_BASH_PATTERNS: tuple[str, ...] = (
    "rm -rf",
    "rm -fr",
    "DROP TABLE",
    "DROP DATABASE",
    "mkfs",
    ":(){:|:&};:",      # fork bomb
    "dd if=",
    "> /dev/",
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def define_agent_acl(
    agent_type: str,
    *,
    allowed_tools: list[str] | None = None,
    denied_tools: list[str] | None = None,
    allowed_paths: list[str] | None = None,
) -> None:
    """Register or override the ACL for an agent type at runtime.

    Merges with any existing entry — only the keys you supply are updated.
    To replace an ACL entirely, call this function with all three arguments.

    Args:
        agent_type:    Agent type key (e.g. "builder", "explorer").
        allowed_tools: Tool names permitted for this agent type.
                       Use ["*"] to allow all tools.
        denied_tools:  Tool names (or fnmatch patterns) that are blocked.
        allowed_paths: fnmatch path patterns the agent may access.
                       Use ["*"] to allow all paths.
    """
    existing: dict = dict(_ACL_OVERRIDES.get(agent_type) or AGENT_ACLS.get(agent_type) or {})
    if allowed_tools is not None:
        existing["allowed_tools"] = list(allowed_tools)
    if denied_tools is not None:
        existing["denied_tools"] = list(denied_tools)
    if allowed_paths is not None:
        existing["allowed_paths"] = list(allowed_paths)
    _ACL_OVERRIDES[agent_type] = existing


def check_agent_permission(
    agent_type: str,
    tool_name: str,
    file_path: str | None = None,
) -> bool:
    """Return True if agent_type is permitted to call tool_name on file_path.

    Evaluation rules (in priority order):
    1. Destructive Bash guard — any agent issuing a destructive shell
       command via the Bash tool is denied regardless of ACL.
    2. Deny list   — if tool_name matches any pattern in denied_tools → DENY.
    3. Allow list  — if allowed_tools == ["*"] or tool_name is in
                     allowed_tools → ALLOW (subject to path check).
    4. Default     — DENY (fail-closed).
    5. Path check  — if a file_path is provided and allowed_paths != ["*"],
                     the path must match at least one pattern in allowed_paths;
                     otherwise DENY.

    Unknown agent types are treated as having no permissions (DENY all).

    Args:
        agent_type: Agent type key (e.g. "builder").
        tool_name:  Name of the tool being called (e.g. "Edit").
        file_path:  Optional file path being accessed; used for path-level ACL.

    Returns:
        True if the action is permitted, False otherwise.
    """
    # Resolve ACL: runtime override takes precedence over built-in default.
    acl: dict | None = _ACL_OVERRIDES.get(agent_type) or AGENT_ACLS.get(agent_type)
    if acl is None:
        return False  # unknown agent type → deny

    allowed_tools: list[str] = acl.get("allowed_tools", [])
    denied_tools: list[str] = acl.get("denied_tools", [])
    allowed_paths: list[str] = acl.get("allowed_paths", ["*"])

    # 1. Destructive Bash guard (belt-and-suspenders, independent of ACL).
    if tool_name == "Bash" and file_path:
        for pattern in _DESTRUCTIVE_BASH_PATTERNS:
            if pattern in file_path:
                return False

    # 2. Deny list (fnmatch patterns supported).
    for denied in denied_tools:
        if fnmatch.fnmatch(tool_name, denied):
            return False

    # 3. Allow list.
    tool_allowed = (
        allowed_tools == ["*"]
        or tool_name in allowed_tools
        or any(fnmatch.fnmatch(tool_name, pat) for pat in allowed_tools if "*" in pat)
    )
    if not tool_allowed:
        return False

    # 4. Path check (skip when no path provided or paths are fully open).
    if file_path and allowed_paths != ["*"]:
        path_ok = any(fnmatch.fnmatch(file_path, pat) for pat in allowed_paths)
        if not path_ok:
            return False

    return True


def get_agent_acl(agent_type: str) -> dict | None:
    """Return the effective ACL dict for agent_type, or None if unknown.

    Runtime overrides take precedence over built-in defaults.

    Args:
        agent_type: Agent type key.

    Returns:
        Dict with keys ``allowed_tools``, ``denied_tools``, ``allowed_paths``,
        or None if the agent type has no registered ACL.
    """
    acl = _ACL_OVERRIDES.get(agent_type) or AGENT_ACLS.get(agent_type)
    return dict(acl) if acl else None


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
