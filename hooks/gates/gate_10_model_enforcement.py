"""Gate 10: MODEL COST GUARD (Blocking + Advisory)

Enforces model profiles for sub-agent spawns via two mechanisms:

1. **Agent tool** (primary): Sets tool_input["model"] directly to enforce
   the active profile model before the agent spawns.

2. **Task tool** (legacy): Blocks Task calls without explicit model param.
   Enforces profile-based model via tool_input["model"] override.

Budget degradation: 4-tier system (NORMAL/LOW_COMPUTE/CRITICAL/DEAD)
when budget_degradation=ON in config.json.

Advisory warnings: Warns when model seems mismatched for agent type.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.gate_result import GateResult
from shared.model_profiles import (
    MODEL_PROFILES,
    AGENT_ROLE_MAP,
    RECOMMENDED_MODELS,
    MODEL_SUGGESTIONS,
    get_model_for_agent,
)

GATE_NAME = "GATE 10: MODEL COST GUARD"

AGENT_SPAWN_TOOLS = {"Task", "Agent"}

MODEL_GUIDANCE = (
    "Add a model parameter: haiku (research/search), "
    "sonnet (analysis/testing), opus (complex implementation)"
)


def _check_agent_tool(tool_input, state):
    """Handle Agent tool calls: enforce model profile via tool_input["model"]."""
    subagent_type = tool_input.get("subagent_type", "")
    description = tool_input.get("description", "agent task")

    if not subagent_type:
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Get active profile
    try:
        from shared.state import get_live_toggle

        profile_name = get_live_toggle("model_profile", "balanced") or "balanced"
    except Exception:
        profile_name = "balanced"

    target_model = get_model_for_agent(profile_name, subagent_type)
    if not target_model:
        # Unknown agent type -- allow, just track
        model_usage = state.setdefault("model_agent_usage", {})
        usage_key = f"{subagent_type}:unknown"
        model_usage[usage_key] = model_usage.get(usage_key, 0) + 1
        return GateResult(blocked=False, gate_name=GATE_NAME)

    # Budget degradation for Agent tool
    try:
        from shared.state import get_live_toggle

        budget_on = get_live_toggle("budget_degradation", False)
        budget_limit = (
            int(get_live_toggle("session_token_budget", 0) or 0) if budget_on else 0
        )
        if budget_on and budget_limit > 0:
            subagent_tokens = state.get("subagent_total_tokens", 0)
            session_tokens = state.get("session_token_estimate", 0)
            used = subagent_tokens + session_tokens
            usage_pct = used / budget_limit

            state["budget_tier"] = (
                "dead"
                if usage_pct >= 0.95
                else "critical"
                if usage_pct >= 0.80
                else "low_compute"
                if usage_pct >= 0.40
                else "normal"
            )

            if state["budget_tier"] == "dead":
                return GateResult(
                    blocked=True,
                    gate_name=GATE_NAME,
                    message=(
                        f"[{GATE_NAME}] BLOCKED [DEAD TIER]: 95%+ of session token budget "
                        f"({used:,}/{budget_limit:,} tokens, {usage_pct:.0%}). "
                        f"No more sub-agent spawns. Use /wrap-up to end session."
                    ),
                )

            # Degrade target model based on budget tier
            if state["budget_tier"] == "critical" and target_model != "haiku":
                original = target_model
                target_model = "haiku"
                print(
                    f"[{GATE_NAME}] CRITICAL TIER: {usage_pct:.0%} budget -- "
                    f"downgrading {original}->haiku for {subagent_type}",
                    file=sys.stderr,
                )
            elif state["budget_tier"] == "low_compute" and target_model == "opus":
                target_model = "sonnet"
                print(
                    f"[{GATE_NAME}] LOW_COMPUTE TIER: {usage_pct:.0%} budget -- "
                    f"downgrading opus->sonnet for {subagent_type}",
                    file=sys.stderr,
                )
    except Exception:
        pass  # Budget check is fail-open

    # Enforce model directly (model param restored in Claude Code 2.1.72)
    tool_input["model"] = target_model
    print(
        f"[{GATE_NAME}] PROFILE '{profile_name}': {subagent_type} -> {target_model} ({description})",
        file=sys.stderr,
    )

    # Track usage
    model_usage = state.setdefault("model_agent_usage", {})
    usage_key = f"{subagent_type}:{target_model}"
    model_usage[usage_key] = model_usage.get(usage_key, 0) + 1

    return GateResult(blocked=False, gate_name=GATE_NAME)


def _check_task_tool(tool_input, state):
    """Handle Task tool calls: enforce model param + profile + budget."""
    model = tool_input.get("model", "")
    description = tool_input.get("description", "sub-agent task")
    subagent_type = tool_input.get("subagent_type", "unknown")

    # Step 1: No model -> BLOCK
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

    # Step 1b: Budget degradation
    budget_tier = "normal"
    try:
        from shared.state import get_live_toggle

        budget_on = get_live_toggle("budget_degradation", False)
        budget_limit = (
            int(get_live_toggle("session_token_budget", 0) or 0) if budget_on else 0
        )
        if budget_on and budget_limit > 0:
            subagent_tokens = state.get("subagent_total_tokens", 0)
            session_tokens = state.get("session_token_estimate", 0)
            used = subagent_tokens + session_tokens
            usage_pct = used / budget_limit

            if usage_pct >= 0.95:
                budget_tier = "dead"
            elif usage_pct >= 0.80:
                budget_tier = "critical"
            elif usage_pct >= 0.40:
                budget_tier = "low_compute"

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
                        f"[{GATE_NAME}] CRITICAL TIER: {usage_pct:.0%} budget used -- "
                        f"downgrading {original}->haiku ({used:,}/{budget_limit:,} tokens)",
                        file=sys.stderr,
                    )

            elif budget_tier == "low_compute":
                if model == "opus":
                    tool_input["model"] = "sonnet"
                    model = "sonnet"
                    print(
                        f"[{GATE_NAME}] LOW_COMPUTE TIER: {usage_pct:.0%} budget used -- "
                        f"downgrading opus->sonnet ({used:,}/{budget_limit:,} tokens)",
                        file=sys.stderr,
                    )
    except Exception:
        pass  # Budget check is fail-open

    # Step 1c: Role-based profile enforcement
    try:
        from shared.state import get_live_toggle

        profile_name = get_live_toggle("model_profile", "balanced") or "balanced"
        profile = MODEL_PROFILES.get(profile_name, MODEL_PROFILES["balanced"])
        role = AGENT_ROLE_MAP.get(subagent_type)
        if role:
            target_model = profile["role_models"].get(role)
            if target_model and target_model != model:
                original = model
                model = target_model
                tool_input["model"] = model
                print(
                    f"[{GATE_NAME}] PROFILE '{profile_name}': {original}->{model} "
                    f"({role} role) for {subagent_type} agent '{description}'",
                    file=sys.stderr,
                )
    except Exception:
        pass  # Profile check is fail-open

    # Step 2: Advisory warnings
    model_usage = state.setdefault("model_agent_usage", {})
    usage_key = f"{subagent_type}:{model}"
    model_usage[usage_key] = model_usage.get(usage_key, 0) + 1

    recommended = RECOMMENDED_MODELS.get(subagent_type)
    if recommended and model not in recommended:
        if model_usage.get(usage_key, 0) >= 3:
            return GateResult(blocked=False, gate_name=GATE_NAME)
        suggestion = MODEL_SUGGESTIONS.get(subagent_type, "check model choice")
        uses = model_usage.get(usage_key, 0)
        warning = (
            f"[{GATE_NAME}] WARNING: Task '{description}' uses {subagent_type} "
            f"agent with model '{model}' (used {uses}x). Recommended: {suggestion}"
        )
        print(warning, file=sys.stderr)
        return GateResult(blocked=False, gate_name=GATE_NAME, message=warning)

    return GateResult(blocked=False, gate_name=GATE_NAME)


def check(tool_name, tool_input, state, event_type="PreToolUse"):
    """Route to Agent or Task handler."""
    if event_type != "PreToolUse":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if tool_name not in AGENT_SPAWN_TOOLS:
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if not isinstance(tool_input, dict):
        tool_input = {}

    if tool_name == "Agent":
        return _check_agent_tool(tool_input, state)
    else:
        return _check_task_tool(tool_input, state)
