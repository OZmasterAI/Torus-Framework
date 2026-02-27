"""Chain Step SDK — Utility wrapper for skill chain monitoring.

Provides ChainStepWrapper that any /chain skill step uses to track:
- Elapsed time per step
- Token estimate delta per step
- Tool call count delta per step

This is NOT a gate — it's a utility library that the /chain skill references.
Metrics are captured passively by reading state before/after each step.

Usage (from /chain skill):
    wrapper = ChainStepWrapper("fix", 1, 3, state, session_id)
    # ... run the skill step ...
    metrics = wrapper.complete(state, outcome="success", summary="Fixed import bug")
"""

import time


class ChainStepWrapper:
    """Wraps a single skill chain step with monitoring and metrics."""

    def __init__(self, skill_name, step_num, total_steps, state, session_id="main"):
        self.skill_name = skill_name
        self.step_num = step_num
        self.total_steps = total_steps
        self.session_id = session_id
        self.start_time = time.time()
        self.start_tokens = state.get("session_token_estimate", 0)
        self.start_tool_calls = state.get("tool_call_count", 0)

    def complete(self, state, outcome="success", summary=""):
        """Call when step finishes. Returns metrics dict for summary table.

        Args:
            state: Current state dict (read for end-of-step metrics)
            outcome: "success", "failure", or "skipped"
            summary: Brief description of what happened
        """
        elapsed = time.time() - self.start_time
        tokens_used = state.get("session_token_estimate", 0) - self.start_tokens
        tool_calls = state.get("tool_call_count", 0) - self.start_tool_calls

        return {
            "skill": self.skill_name,
            "step": f"{self.step_num}/{self.total_steps}",
            "outcome": outcome,
            "elapsed_s": round(elapsed, 1),
            "tokens_est": tokens_used,
            "tool_calls": tool_calls,
            "summary": summary,
        }


def format_chain_mapping(goal, skills, step_metrics, total_time, total_tool_calls, final_outcome):
    """Format a chain mapping string for memory storage.

    Args:
        goal: The user's original goal text
        skills: List of skill names in the chain
        step_metrics: List of dicts from ChainStepWrapper.complete()
        total_time: Total elapsed time in seconds
        total_tool_calls: Total tool calls across all steps
        final_outcome: "success", "partial", or "failure"

    Returns:
        Formatted string suitable for remember_this()
    """
    chain_str = " -> ".join(skills)
    per_step = "; ".join(
        f"{m['skill']}({m['outcome']}, {m['elapsed_s']}s, {m['tool_calls']} calls)"
        for m in step_metrics
    )
    return (
        f"Chain mapping: '{goal}' → [{chain_str}]. "
        f"Per-step: [{per_step}]. "
        f"Total: {round(total_time, 1)}s, {total_tool_calls} tool calls. "
        f"Outcome: {final_outcome}"
    )
