"""Gate 10: MODEL COST GUARD (Blocking + Advisory)

Two-step enforcement for sub-agent model selection:

Step 1 (BLOCKING): Blocks Task calls with no explicit model parameter.
  Forces every sub-agent spawn to include a deliberate model choice,
  preventing silent inheritance of the parent's expensive model.

Step 1b (BUDGET): 4-tier budget degradation when budget_degradation=ON:
  - NORMAL  (0-40% used):   No restrictions
  - LOW_COMPUTE (40-80%):   opus → sonnet (auto-downgrade)
  - CRITICAL (80-95%):      everything → haiku (auto-downgrade)
  - DEAD     (95%+):        Block all sub-agent spawns

Step 2 (ADVISORY): Warns when the chosen model seems mismatched for the
  agent type. For example, using opus for a read-only Explore agent, or
  haiku for a general-purpose builder that needs full capabilities.

Model guidance:
  - "haiku"  — fast/cheap: research, search, exploration, simple file ops
  - "sonnet" — balanced: moderate analysis, testing, single-file creation
  - "opus"   — full power: complex implementation, multi-file refactoring
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.gate_result import GateResult

GATE_NAME = "GATE 10: MODEL COST GUARD"

# Sub-agent tool names that must specify a model
AGENT_SPAWN_TOOLS = {"Task"}

MODEL_GUIDANCE = (
    "Add a model parameter: haiku (research/search), "
    "sonnet (analysis/testing), opus (complex implementation)"
)

# ── Role-Based Model Profiles ──
# Users set active profile in LIVE_STATE.json "model_profile" field.
# Each profile maps agent ROLES (planning/execution/verification) to models.
# Gate 10 infers the role from subagent_type, then enforces the profile's model.

# Agent type → role mapping (active agents only — dormant agents removed)
# Roles: planning (architecture), research (read-only lookup), execution (read+write), verification (read+run)
AGENT_ROLE_MAP = {
    # Planning role: architecture decisions, implementation design
    "Plan":              "planning",     # Anthropic built-in: implementation planning, read-only
    # Research role: read-only lookup, search, exploration (doesn't need opus)
    "Explore":           "research",     # Anthropic built-in: codebase search, read-only
    "researcher":        "research",     # Read-only research (Glob/Grep/Read/WebSearch, memory)
    "claude-code-guide": "research",     # Anthropic built-in: Claude Code documentation lookup
    # Execution role: builds, implements, writes code
    "builder":           "execution",    # Full implementation (Edit/Write/Bash + memory + causal chain)
    "general-purpose":   "execution",    # Anthropic built-in: multi-step tasks with all tools
    "Bash":              "execution",    # Anthropic built-in: command execution
    "statusline-setup":  "execution",    # Anthropic built-in: edits statusline config
    "debugger":          "execution",    # Diagnoses + fixes gate/hook/state issues (Edit/Write/Bash + causal chain)
    # Verification role: tests, audits, reviews (read + run, no code changes)
    "stress-tester":     "verification", # Runs test suites, reports pass/fail (Bash for tests + memory)
    "security":          "verification", # Security audit: OWASP, gate bypass, secrets (Bash for analysis only)
    "perf-analyzer":     "verification", # Profiles bottlenecks: hooks, gates, LanceDB (Bash for timing only)
}

# Profile → role → model
MODEL_PROFILES = {
    "quality": {
        "description": "Maximum quality — opus for planning+execution, sonnet for research+verification",
        "role_models": {"planning": "opus", "research": "sonnet", "execution": "opus", "verification": "sonnet"},
        "warn_on_opus": False,
    },
    "balanced": {
        "description": "Default — opus for planning, sonnet for research+execution+verification",
        "role_models": {"planning": "opus", "research": "sonnet", "execution": "sonnet", "verification": "sonnet"},
        "warn_on_opus": True,
    },
    "efficient": {
        "description": "Opus planning, sonnet work, haiku verification — best cost/quality ratio",
        "role_models": {"planning": "opus", "research": "sonnet", "execution": "sonnet", "verification": "haiku"},
        "warn_on_opus": True,
    },
    "lean": {
        "description": "Opus planning only, haiku for all read-only — minimal spend with smart planning",
        "role_models": {"planning": "opus", "research": "haiku", "execution": "sonnet", "verification": "haiku"},
        "warn_on_opus": True,
    },
    "budget": {
        "description": "Cost-minimizing — sonnet for planning+execution, haiku for research+verification",
        "role_models": {"planning": "sonnet", "research": "haiku", "execution": "sonnet", "verification": "haiku"},
        "warn_on_opus": True,
    },
}

# Recommended models per agent type.
# Key: subagent_type → set of recommended models.
# Any model not in the set triggers an advisory warning.
RECOMMENDED_MODELS = {
    "Explore":           {"haiku", "sonnet"},
    "Plan":              {"opus", "sonnet"},
    "general-purpose":   {"sonnet", "opus"},
    "Bash":              {"haiku", "sonnet"},
    "builder":           {"sonnet", "opus"},       # needs Edit/Write, complex tasks
    "researcher":        {"haiku", "sonnet"},      # read-only research
    "security":          {"sonnet"},               # security auditing needs reasoning
    "stress-tester":     {"haiku", "sonnet"},      # runs tests, read-heavy
    "perf-analyzer":     {"sonnet"},               # profiling needs reasoning
    "debugger":          {"sonnet", "opus"},        # debugging can be complex
    "claude-code-guide": {"haiku"},                # documentation lookup only
    "statusline-setup":  {"haiku"},                # simple config changes
}

# Human-readable suggestions per agent type (shown in warnings)
MODEL_SUGGESTIONS = {
    "Explore":           "haiku or sonnet (read-only exploration doesn't need opus)",
    "Plan":              "opus or sonnet (planning needs strong reasoning for architecture decisions)",
    "general-purpose":   "sonnet or opus (needs Edit/Write — haiku may lack capability)",
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


def check(tool_name, tool_input, state, event_type="PreToolUse"):
    """Block Task calls without a model; warn on model/agent mismatches."""
    if event_type != "PreToolUse":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if tool_name not in AGENT_SPAWN_TOOLS:
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if not isinstance(tool_input, dict):
        tool_input = {}

    model = tool_input.get("model", "")
    description = tool_input.get("description", "sub-agent task")
    subagent_type = tool_input.get("subagent_type", "unknown")

    # ── Step 1: No model → BLOCK ──
    if not model:
        return GateResult(
            blocked=True,
            gate_name=GATE_NAME,
            message=(
                f"[{GATE_NAME}] BLOCKED: Task '{description}' ({subagent_type}) "
                f"has no explicit model parameter. Without one, it inherits the "
                f"parent's model (likely opus). {MODEL_GUIDANCE}"
            ),
        )

    # ── Step 1b: 4-tier budget degradation ──
    # Tiers: NORMAL (0-40%) → LOW_COMPUTE (40-80%) → CRITICAL (80-95%) → DEAD (95%+)
    # Reads LIVE_STATE.json only when toggle is ON (0 file reads when OFF)
    budget_tier = "normal"
    try:
        from shared.state import get_live_toggle
        budget_on = get_live_toggle("budget_degradation", False)
        budget_limit = int(get_live_toggle("session_token_budget", 0) or 0) if budget_on else 0
        if budget_on and budget_limit > 0:
            subagent_tokens = state.get("subagent_total_tokens", 0)
            session_tokens = state.get("session_token_estimate", 0)
            used = subagent_tokens + session_tokens
            usage_pct = used / budget_limit

            # Determine tier
            if usage_pct >= 0.95:
                budget_tier = "dead"
            elif usage_pct >= 0.80:
                budget_tier = "critical"
            elif usage_pct >= 0.40:
                budget_tier = "low_compute"
            # else: normal (default)

            # Store tier in state for other gates/statusline to read
            state["budget_tier"] = budget_tier

            if budget_tier == "dead":
                return GateResult(
                    blocked=True,
                    gate_name=GATE_NAME,
                    message=(
                        f"[{GATE_NAME}] BLOCKED [DEAD TIER]: 95%+ of session token budget "
                        f"({used:,}/{budget_limit:,} tokens, {usage_pct:.0%}). "
                        f"No more sub-agent spawns. Use /wrap-up to end session."
                    ),
                )

            if budget_tier == "critical":
                if model != "haiku":
                    original = model
                    tool_input["model"] = "haiku"
                    model = "haiku"
                    print(
                        f"[{GATE_NAME}] CRITICAL TIER: {usage_pct:.0%} budget used — "
                        f"downgrading {original}→haiku ({used:,}/{budget_limit:,} tokens)",
                        file=sys.stderr,
                    )

            elif budget_tier == "low_compute":
                if model == "opus":
                    tool_input["model"] = "sonnet"
                    model = "sonnet"
                    print(
                        f"[{GATE_NAME}] LOW_COMPUTE TIER: {usage_pct:.0%} budget used — "
                        f"downgrading opus→sonnet ({used:,}/{budget_limit:,} tokens)",
                        file=sys.stderr,
                    )
    except Exception:
        pass  # Budget check is fail-open

    # ── Step 1c: Role-based model profile enforcement ──
    # Reads "model_profile" from LIVE_STATE.json (quality/balanced/budget)
    # Infers agent role from subagent_type, then enforces profile's model for that role
    try:
        from shared.state import get_live_toggle
        profile_name = get_live_toggle("model_profile", "balanced") or "balanced"
        profile = MODEL_PROFILES.get(profile_name, MODEL_PROFILES["balanced"])

        role = AGENT_ROLE_MAP.get(subagent_type)
        if role:
            role_models = profile.get("role_models", {})
            target_model = role_models.get(role)
            if target_model and target_model != model:
                original = model
                model = target_model
                tool_input["model"] = model
                print(
                    f"[{GATE_NAME}] PROFILE '{profile_name}': {original}→{model} "
                    f"({role} role) for {subagent_type} agent '{description}'",
                    file=sys.stderr,
                )
    except Exception:
        pass  # Profile check is fail-open

    # ── Step 2: Model mismatch → WARN (never block) ──
    # Track model usage by agent type for learning
    model_usage = state.setdefault("model_agent_usage", {})
    usage_key = f"{subagent_type}:{model}"
    model_usage[usage_key] = model_usage.get(usage_key, 0) + 1

    recommended = RECOMMENDED_MODELS.get(subagent_type)
    if recommended and model not in recommended:
        # Suppress warning if this combo has been used 3+ times (proven pattern)
        if model_usage.get(usage_key, 0) >= 3:
            return GateResult(blocked=False, gate_name=GATE_NAME)
        suggestion = MODEL_SUGGESTIONS.get(subagent_type, "check model choice")
        uses = model_usage.get(usage_key, 0)
        warning = (
            f"[{GATE_NAME}] WARNING: Task '{description}' uses {subagent_type} "
            f"agent with model '{model}' (used {uses}x). Recommended: {suggestion}"
        )
        print(warning, file=sys.stderr)
        return GateResult(
            blocked=False,
            gate_name=GATE_NAME,
            message=warning,
        )

    # Model specified and matches recommendations — pass silently
    return GateResult(blocked=False, gate_name=GATE_NAME)
