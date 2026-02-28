"""Tool recommendation engine for the Torus self-healing framework.

Tracks tool call outcomes (success/block/error) and recommends alternative
tools when detecting suboptimal patterns. Uses session history to learn
which tool sequences have the best success rates.

Design:
- Pure functions over session state dicts (no I/O, no side effects)
- Integrates with metrics_collector for tracking acceptance rates
- Fail-open: all exceptions return empty/neutral results

Public API:
    build_tool_profile(state)        -> Dict[tool, ToolProfile]
    recommend_alternative(tool, state) -> Optional[Recommendation]
    get_recommendation_stats(state)  -> Dict
    should_recommend(tool, state)    -> bool
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


# ── Data containers ──────────────────────────────────────────────────────────

@dataclass
class ToolProfile:
    """Aggregated success metrics for a single tool.

    Attributes:
        tool_name:    Name of the tool (e.g., "Edit", "Write", "Bash").
        call_count:   Total times this tool was called.
        block_count:  Times a gate blocked this tool call.
        error_count:  Times the tool call resulted in an error.
        success_rate: Fraction of calls that succeeded (0.0-1.0).
        block_rate:   Fraction of calls that were blocked (0.0-1.0).
    """
    tool_name: str
    call_count: int = 0
    block_count: int = 0
    error_count: int = 0
    success_rate: float = 1.0
    block_rate: float = 0.0


@dataclass
class Recommendation:
    """A tool recommendation with context.

    Attributes:
        original_tool:    The tool that was about to be called.
        suggested_tool:   The recommended alternative.
        reason:           Human-readable explanation.
        confidence:       How confident the recommendation is (0.0-1.0).
        original_success: Success rate of the original tool.
        suggested_success: Success rate of the suggested tool.
    """
    original_tool: str
    suggested_tool: str
    reason: str
    confidence: float
    original_success: float
    suggested_success: float


# ── Constants ────────────────────────────────────────────────────────────────

# Minimum calls before we consider a tool's stats reliable
MIN_CALLS_FOR_STATS = 5

# Block rate above this triggers a recommendation check
BLOCK_RATE_THRESHOLD = 0.3

# The alternative must be at least this much better (absolute improvement)
MIN_IMPROVEMENT = 0.15

# Tool equivalence groups: tools that can substitute for each other
TOOL_EQUIVALENCES: Dict[str, List[str]] = {
    "Edit": ["Write"],
    "Write": ["Edit"],
    "Grep": ["Glob"],
    "Glob": ["Grep"],
}

# Tools that are always appropriate (never recommend against these)
ALWAYS_OK_TOOLS = {"Read", "Glob", "Grep", "WebSearch", "WebFetch"}

# Sequence-based recommendations: if tool A was blocked after tool B,
# recommend inserting tool C between them
SEQUENCE_FIXES: List[Tuple[str, str, str, str]] = [
    # (preceding, blocked_tool, insert_tool, reason)
    ("Glob", "Edit", "Read", "Read the file before editing"),
    ("Grep", "Edit", "Read", "Read the file before editing"),
    ("Glob", "Write", "Read", "Read the file before overwriting"),
    ("Grep", "Write", "Read", "Read the file before overwriting"),
    ("Edit", "Bash", "Read", "Verify the edit before running tests"),
    ("Write", "Bash", "Read", "Verify the write before running tests"),
]


# ── Core functions ───────────────────────────────────────────────────────────

def build_tool_profile(state: dict) -> Dict[str, ToolProfile]:
    """Build success/block profiles for all tools from session state.

    Extracts tool call counts and gate block outcomes to compute
    per-tool success and block rates.

    Args:
        state: Session state dict with keys:
            - tool_call_counts: Dict[str, int] (tool -> call count)
            - gate_block_outcomes: List[Dict] (each with 'tool' key)
            - tool_errors: Dict[str, int] (tool -> error count, optional)

    Returns:
        Dict mapping tool name -> ToolProfile with computed rates.
    """
    tool_counts: Dict[str, int] = state.get("tool_call_counts", {})
    gate_blocks: list = state.get("gate_block_outcomes", [])
    tool_errors: Dict[str, int] = state.get("tool_errors", {})

    # Count blocks per tool
    block_counts: Dict[str, int] = {}
    for block in gate_blocks:
        if isinstance(block, dict):
            tool = block.get("tool", block.get("tool_name", ""))
            if tool:
                block_counts[tool] = block_counts.get(tool, 0) + 1

    profiles: Dict[str, ToolProfile] = {}
    all_tools = set(tool_counts.keys()) | set(block_counts.keys())

    for tool in all_tools:
        calls = tool_counts.get(tool, 0)
        blocks = block_counts.get(tool, 0)
        errors = tool_errors.get(tool, 0)

        if calls > 0:
            success_rate = max(0.0, (calls - blocks - errors) / calls)
            block_rate = min(1.0, blocks / calls)
        else:
            success_rate = 1.0
            block_rate = 0.0

        profiles[tool] = ToolProfile(
            tool_name=tool,
            call_count=calls,
            block_count=blocks,
            error_count=errors,
            success_rate=success_rate,
            block_rate=block_rate,
        )

    return profiles


def should_recommend(tool: str, state: dict) -> bool:
    """Check if a recommendation should be generated for this tool.

    Returns True when:
    1. The tool has enough history (>= MIN_CALLS_FOR_STATS)
    2. The tool's block rate exceeds BLOCK_RATE_THRESHOLD
    3. The tool is not in ALWAYS_OK_TOOLS

    Args:
        tool: Name of the tool about to be called.
        state: Session state dict.

    Returns:
        True if a recommendation check is warranted.
    """
    if tool in ALWAYS_OK_TOOLS:
        return False

    profiles = build_tool_profile(state)
    profile = profiles.get(tool)

    if not profile:
        return False

    if profile.call_count < MIN_CALLS_FOR_STATS:
        return False

    return profile.block_rate > BLOCK_RATE_THRESHOLD


def recommend_alternative(
    tool: str,
    state: dict,
    recent_tools: Optional[List[str]] = None,
) -> Optional[Recommendation]:
    """Generate a tool recommendation if a better alternative exists.

    Checks two recommendation sources:
    1. Tool equivalences: If an equivalent tool has a better success rate
    2. Sequence fixes: If the preceding tool sequence suggests inserting
       an intermediate step (e.g., Read before Edit)

    Args:
        tool: Name of the tool about to be called.
        state: Session state dict.
        recent_tools: Last few tools called (for sequence-based recs).

    Returns:
        A Recommendation if a better alternative exists, None otherwise.
    """
    if tool in ALWAYS_OK_TOOLS:
        return None

    profiles = build_tool_profile(state)
    original = profiles.get(tool)

    if not original or original.call_count < MIN_CALLS_FOR_STATS:
        return None

    # 1. Check sequence-based fixes first (higher priority)
    if recent_tools:
        preceding = recent_tools[-1] if recent_tools else ""
        for pre, blocked, insert, reason in SEQUENCE_FIXES:
            if pre == preceding and blocked == tool:
                return Recommendation(
                    original_tool=tool,
                    suggested_tool=insert,
                    reason=f"Consider: {reason} (insert {insert} before {tool})",
                    confidence=0.8,
                    original_success=original.success_rate,
                    suggested_success=1.0,  # Read/verify steps rarely fail
                )

    # 2. Check tool equivalences
    equivalents = TOOL_EQUIVALENCES.get(tool, [])
    best_alt: Optional[Recommendation] = None
    best_improvement = 0.0

    for alt_tool in equivalents:
        alt_profile = profiles.get(alt_tool)
        if not alt_profile:
            continue

        # Only recommend if the alternative has enough data too
        if alt_profile.call_count < MIN_CALLS_FOR_STATS:
            continue

        improvement = alt_profile.success_rate - original.success_rate
        if improvement >= MIN_IMPROVEMENT and improvement > best_improvement:
            confidence = min(1.0, improvement / 0.5)  # Scale: 0.15→0.3, 0.5→1.0
            best_alt = Recommendation(
                original_tool=tool,
                suggested_tool=alt_tool,
                reason=(
                    f"{alt_tool} has {alt_profile.success_rate:.0%} success rate "
                    f"vs {original.success_rate:.0%} for {tool} this session"
                ),
                confidence=confidence,
                original_success=original.success_rate,
                suggested_success=alt_profile.success_rate,
            )
            best_improvement = improvement

    return best_alt


def get_recommendation_stats(state: dict) -> dict:
    """Get summary statistics for tool recommendations.

    Args:
        state: Session state dict.

    Returns:
        Dict with keys:
            tools_analyzed: Number of tools with profiles
            tools_at_risk: Tools with block_rate > threshold
            top_blockers: Top 3 most-blocked tools [(name, rate)]
            healthiest: Top 3 highest success rate tools [(name, rate)]
    """
    profiles = build_tool_profile(state)

    if not profiles:
        return {
            "tools_analyzed": 0,
            "tools_at_risk": [],
            "top_blockers": [],
            "healthiest": [],
        }

    # Filter to tools with enough data
    reliable = {
        k: v for k, v in profiles.items()
        if v.call_count >= MIN_CALLS_FOR_STATS
    }

    at_risk = [
        p.tool_name for p in reliable.values()
        if p.block_rate > BLOCK_RATE_THRESHOLD
    ]

    top_blockers = sorted(
        [(p.tool_name, p.block_rate) for p in reliable.values()],
        key=lambda x: x[1],
        reverse=True,
    )[:3]

    healthiest = sorted(
        [(p.tool_name, p.success_rate) for p in reliable.values()],
        key=lambda x: x[1],
        reverse=True,
    )[:3]

    return {
        "tools_analyzed": len(profiles),
        "tools_at_risk": at_risk,
        "top_blockers": top_blockers,
        "healthiest": healthiest,
    }
