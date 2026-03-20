"""Learning Feedback Loop — Connects gate outcomes, chain refinements, and tool mastery.

Coordinator module that feeds outcomes between subsystems:
- Gate outcomes → adaptive_thresholds (record correctness)
- Chain refinement outcomes → adaptive_thresholds (feedback)
- Tool mastery data → gate routing (inform Q-values)

Public API:
    from shared.learning_loop import (
        process_gate_result, process_fix_outcome, get_learning_stats,
    )
"""

import time
from typing import Dict, Optional


def process_gate_result(
    gate_name: str,
    gate_blocked: bool,
    tool_name: str,
    tool_succeeded: bool,
    task_type: str = "unknown",
    duration_ms: float = 0.0,
) -> dict:
    """Process a gate result and feed it into adaptive thresholds and tool mastery.

    Call this after a tool use completes (PostToolUse) to record:
    1. Whether the gate's decision was correct (→ adaptive_thresholds)
    2. Tool mastery data with task context (→ tool_mastery)

    Returns dict with status of each subsystem update.
    """
    results = {"threshold_updated": False, "mastery_updated": False, "errors": []}

    # Update adaptive thresholds
    try:
        from shared.adaptive_thresholds import load_thresholds, save_thresholds, record_gate_outcome
        data = load_thresholds()
        record_gate_outcome(data, gate_name, gate_blocked, tool_succeeded)
        save_thresholds(data)
        results["threshold_updated"] = True
    except Exception as e:
        results["errors"].append(f"threshold: {e}")

    # Update tool mastery
    try:
        from shared.tool_mastery import load_mastery, save_mastery, record_tool_use
        mastery = load_mastery()
        record_tool_use(mastery, tool_name, task_type, tool_succeeded, duration_ms)
        save_mastery(mastery)
        results["mastery_updated"] = True
    except Exception as e:
        results["errors"].append(f"mastery: {e}")

    return results


def process_fix_outcome(
    error_pattern: str,
    strategy: str,
    success: bool,
    gate_involved: str = "",
) -> dict:
    """Process a fix chain outcome and feed back to adaptive thresholds.

    When a fix chain completes, this tells the threshold system whether
    the gate that originally flagged the issue was helpful.

    Args:
        error_pattern: The error that was being fixed.
        strategy: The fix strategy used.
        success: Whether the fix succeeded.
        gate_involved: The gate that originally flagged the issue (if known).

    Returns:
        Dict with update status.
    """
    results = {"feedback_recorded": False, "errors": []}

    if gate_involved:
        try:
            from shared.adaptive_thresholds import load_thresholds, save_thresholds, record_feedback
            data = load_thresholds()
            # If fix succeeded after gate block, gate was correct (TP)
            # If fix failed, gate block didn't help enough (still counts as TP but less useful)
            record_feedback(data, gate_involved, was_correct=success)
            save_thresholds(data)
            results["feedback_recorded"] = True
        except Exception as e:
            results["errors"].append(f"feedback: {e}")

    return results


def get_learning_stats() -> dict:
    """Summary of learning loop activity across all subsystems."""
    stats = {"mastery": None, "thresholds": None, "errors": []}

    try:
        from shared.tool_mastery import load_mastery, get_mastery_report
        mastery = load_mastery()
        report = get_mastery_report(mastery)
        stats["mastery"] = {
            "total_uses": report.get("total_tool_uses", 0),
            "level_distribution": report.get("level_distribution", {}),
            "task_types_tracked": len(report.get("tracked_task_types", [])),
            "weakest_tool": report.get("weakest_tool"),
        }
    except Exception as e:
        stats["errors"].append(f"mastery: {e}")

    try:
        from shared.adaptive_thresholds import load_thresholds, get_threshold_report
        data = load_thresholds()
        report = get_threshold_report(data)
        thresholds = report.get("thresholds", [])
        adjusted = sum(1 for t in thresholds if t.get("current") != t.get("default"))
        stats["thresholds"] = {
            "gates_tracked": len(thresholds),
            "gates_adjusted": adjusted,
            "recent_adjustments": len(report.get("recent_adjustments", [])),
        }
    except Exception as e:
        stats["errors"].append(f"thresholds: {e}")

    return stats
