"""Chain Step SDK — Utility wrapper for skill chain monitoring.

Provides ChainStepWrapper that any /chain skill step uses to track:
- Elapsed time per step
- Token estimate delta per step
- Tool call count delta per step
- Efficiency metrics (tokens/call, calls/second, gate blocks)

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

    def __init__(self, skill_name, step_num, total_steps, state, session_id="main", chain_id=""):
        self.skill_name = skill_name
        self.step_num = step_num
        self.total_steps = total_steps
        self.session_id = session_id
        self.chain_id = chain_id or f"{session_id}_{int(time.time())}"
        self.start_time = time.time()
        self.start_tokens = state.get("session_token_estimate", 0)
        self.start_tool_calls = state.get("tool_call_count", 0)
        self.start_gate_blocks = state.get("gate_block_count", 0)

    def complete(self, state, outcome="success", summary=""):
        """Call when step finishes. Returns metrics dict for summary table.

        Args:
            state: Current state dict (read for end-of-step metrics)
            outcome: "success", "failure", or "skipped"
            summary: Brief description of what happened
        """
        elapsed = max(time.time() - self.start_time, 0.001)
        tokens_used = state.get("session_token_estimate", 0) - self.start_tokens
        tool_calls = state.get("tool_call_count", 0) - self.start_tool_calls
        gate_blocks = state.get("gate_block_count", 0) - self.start_gate_blocks

        # Efficiency metrics
        tokens_per_call = round(tokens_used / max(tool_calls, 1), 1)
        calls_per_sec = round(tool_calls / elapsed, 2)

        return {
            "skill": self.skill_name,
            "step": f"{self.step_num}/{self.total_steps}",
            "chain_id": self.chain_id,
            "outcome": outcome,
            "elapsed_s": round(elapsed, 1),
            "tokens_est": tokens_used,
            "tool_calls": tool_calls,
            "tokens_per_call": tokens_per_call,
            "calls_per_sec": calls_per_sec,
            "gate_blocks": gate_blocks,
            "summary": summary,
        }



def compute_chain_efficiency(step_metrics):
    """Compute aggregate efficiency metrics across all chain steps.

    Args:
        step_metrics: List of dicts from ChainStepWrapper.complete()

    Returns:
        Dict with aggregate efficiency stats.
    """
    if not step_metrics:
        return {"total_steps": 0, "efficiency_score": 0.0}

    total_tokens = sum(m.get("tokens_est", 0) for m in step_metrics)
    total_calls = sum(m.get("tool_calls", 0) for m in step_metrics)
    total_blocks = sum(m.get("gate_blocks", 0) for m in step_metrics)
    total_time = sum(m.get("elapsed_s", 0) for m in step_metrics)
    successes = sum(1 for m in step_metrics if m.get("outcome") == "success")

    # Efficiency score: penalize high token usage, gate blocks, failures
    success_rate = successes / len(step_metrics)
    block_penalty = min(1.0, total_blocks * 0.1)  # each block costs 10%
    token_efficiency = 1.0 / (1.0 + total_tokens / max(total_calls, 1) / 1000)
    score = round(success_rate * (1.0 - block_penalty) * (0.5 + 0.5 * token_efficiency), 4)

    return {
        "total_steps": len(step_metrics),
        "successes": successes,
        "total_tokens": total_tokens,
        "total_calls": total_calls,
        "total_blocks": total_blocks,
        "total_time_s": round(total_time, 1),
        "avg_tokens_per_call": round(total_tokens / max(total_calls, 1), 1),
        "efficiency_score": score,
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
