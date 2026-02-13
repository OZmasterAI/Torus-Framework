"""Gate 10: MODEL COST GUARD (Blocking + Advisory)

Two-step enforcement for sub-agent model selection:

Step 1 (BLOCKING): Blocks Task calls with no explicit model parameter.
  Forces every sub-agent spawn to include a deliberate model choice,
  preventing silent inheritance of the parent's expensive model.

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

# Recommended models per agent type.
# Key: subagent_type → set of recommended models.
# Any model not in the set triggers an advisory warning.
RECOMMENDED_MODELS = {
    "Explore":          {"haiku", "sonnet"},
    "Plan":             {"haiku", "sonnet"},
    "general-purpose":  {"sonnet", "opus"},
    "Bash":             {"haiku", "sonnet"},
    "builder":           {"sonnet", "opus"},      # needs Edit/Write, complex tasks
    "researcher":        {"haiku", "sonnet"},      # read-only research
    "auditor":           {"haiku", "sonnet"},      # read-only security review
    "stress-tester":     {"haiku", "sonnet"},      # runs tests, read-heavy
    "claude-code-guide": {"haiku"},                # documentation lookup only
    "statusline-setup":  {"haiku"},                # simple config changes
}

# Human-readable suggestions per agent type (shown in warnings)
MODEL_SUGGESTIONS = {
    "Explore":          "haiku or sonnet (read-only exploration doesn't need opus)",
    "Plan":             "haiku or sonnet (planning is read-only, save cost)",
    "general-purpose":  "sonnet or opus (needs Edit/Write — haiku may lack capability)",
    "Bash":             "haiku or sonnet (command execution doesn't need opus)",
    "builder":           "sonnet or opus (full implementation agent needs Edit/Write)",
    "researcher":        "haiku or sonnet (read-only exploration and analysis)",
    "auditor":           "haiku or sonnet (code review is read-only)",
    "stress-tester":     "haiku or sonnet (test execution doesn't need opus)",
    "claude-code-guide": "haiku (documentation lookup only, minimal capability needed)",
    "statusline-setup":  "haiku (simple config file edits only)",
}


def check(tool_name, tool_input, state, event_type="PreToolUse"):
    """Block Task calls without a model; warn on model/agent mismatches."""
    if event_type != "PreToolUse":
        return GateResult(blocked=False, gate_name=GATE_NAME)

    if tool_name not in AGENT_SPAWN_TOOLS:
        return GateResult(blocked=False, gate_name=GATE_NAME)

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

    # ── Step 2: Model mismatch → WARN (never block) ──
    recommended = RECOMMENDED_MODELS.get(subagent_type)
    if recommended and model not in recommended:
        suggestion = MODEL_SUGGESTIONS.get(subagent_type, "check model choice")
        warning = (
            f"[{GATE_NAME}] WARNING: Task '{description}' uses {subagent_type} "
            f"agent with model '{model}'. Recommended: {suggestion}"
        )
        print(warning, file=sys.stderr)
        return GateResult(
            blocked=False,
            gate_name=GATE_NAME,
            message=warning,
        )

    # Model specified and matches recommendations — pass silently
    return GateResult(blocked=False, gate_name=GATE_NAME)
