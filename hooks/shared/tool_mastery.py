"""Tool Mastery Tracking — Task-context-aware tool usage learning.

Extends tool_profiles.py with task-type awareness. Tracks which tools
succeed for which task types and computes mastery levels.

Public API:
    from shared.tool_mastery import (
        record_tool_use, get_mastery_level, get_task_preferences,
        get_mastery_report, suggest_tool, load_mastery, save_mastery,
    )
"""

import json
import math
import os
import time
from typing import Dict, List, Optional, Tuple

_RAMDISK_DIR = f"/run/user/{os.getuid()}/claude-hooks"
_DISK_DIR = os.path.join(os.path.expanduser("~"), ".claude", "hooks", ".state")
_MASTERY_FILENAME = "tool_mastery.json"

TASK_TYPES = {"fix", "feature", "refactor", "test", "explore", "review", "debug", "unknown"}
TRACKED_TOOLS = {"Edit", "Write", "Bash", "Read", "Grep", "Glob", "NotebookEdit", "Agent", "Skill"}

# Mastery thresholds: (level_name, min_uses, min_success_rate)
MASTERY_LEVELS = [
    ("expert", 200, 0.90),
    ("proficient", 50, 0.80),
    ("competent", 10, 0.70),
    ("novice", 0, 0.0),
]

MAX_TASK_TYPES = 20


def _mastery_path():
    ramdisk = os.path.join(_RAMDISK_DIR, _MASTERY_FILENAME)
    disk = os.path.join(_DISK_DIR, _MASTERY_FILENAME)
    if os.path.isdir(_RAMDISK_DIR):
        return ramdisk, disk
    return disk, None


def load_mastery() -> dict:
    primary, fallback = _mastery_path()
    for path in (primary, fallback):
        if path and os.path.exists(path):
            try:
                with open(path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                continue
    return _default_mastery()


def save_mastery(data: dict) -> None:
    primary, mirror = _mastery_path()
    content = json.dumps(data, indent=2)
    for path in (primary, mirror):
        if path:
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w") as f:
                    f.write(content)
            except IOError:
                pass


def _default_mastery() -> dict:
    return {"tool_task_stats": {}, "mastery_levels": {}, "task_tool_preferences": {}, "last_updated": 0.0}


def record_tool_use(data, tool_name, task_type="unknown", success=True, duration_ms=0.0):
    """Record a tool use with task context. Mutates and returns data."""
    if tool_name not in TRACKED_TOOLS:
        return data
    task_type = task_type if task_type in TASK_TYPES else "unknown"
    stats = data.setdefault("tool_task_stats", {})
    tool_stats = stats.setdefault(tool_name, {})
    if task_type not in tool_stats and len(tool_stats) >= MAX_TASK_TYPES:
        return data

    entry = tool_stats.setdefault(task_type, {"success": 0, "failure": 0, "avg_duration_ms": 0.0, "_duration_sum": 0.0})
    if success:
        entry["success"] = entry.get("success", 0) + 1
    else:
        entry["failure"] = entry.get("failure", 0) + 1
    if duration_ms > 0:
        total = entry.get("success", 0) + entry.get("failure", 0)
        entry["_duration_sum"] = entry.get("_duration_sum", 0.0) + duration_ms
        entry["avg_duration_ms"] = round(entry["_duration_sum"] / max(total, 1), 1)

    _recompute_mastery(data, tool_name)
    _recompute_task_preferences(data, task_type)
    data["last_updated"] = time.time()
    return data


def _recompute_mastery(data, tool_name):
    stats = data.get("tool_task_stats", {}).get(tool_name, {})
    total_s = sum(t.get("success", 0) for t in stats.values())
    total_f = sum(t.get("failure", 0) for t in stats.values())
    total = total_s + total_f
    rate = total_s / total if total > 0 else 1.0
    level = "novice"
    for lvl, min_uses, min_rate in MASTERY_LEVELS:
        if total >= min_uses and rate >= min_rate:
            level = lvl
            break
    data.setdefault("mastery_levels", {})[tool_name] = {"level": level, "total_uses": total, "success_rate": round(rate, 4)}


def _recompute_task_preferences(data, task_type):
    """Recompute optimal tool ordering using Wilson score lower bound."""
    stats = data.get("tool_task_stats", {})
    scores = []
    for tool, task_stats in stats.items():
        if task_type not in task_stats:
            continue
        e = task_stats[task_type]
        s, f = e.get("success", 0), e.get("failure", 0)
        n = s + f
        if n == 0:
            continue
        p = s / n
        z = 1.96
        wilson = (p + z*z/(2*n) - z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))) / (1 + z*z/n)
        scores.append((tool, wilson))
    scores.sort(key=lambda x: x[1], reverse=True)
    data.setdefault("task_tool_preferences", {})[task_type] = [t[0] for t in scores]


def get_mastery_level(data, tool_name):
    return data.get("mastery_levels", {}).get(tool_name, {"level": "novice", "total_uses": 0, "success_rate": 1.0})


def get_task_preferences(data, task_type):
    return data.get("task_tool_preferences", {}).get(task_type, [])


def suggest_tool(data, task_type, action="", exclude=None):
    """Suggest best tool for a task type, optionally filtered by action hint."""
    prefs = get_task_preferences(data, task_type)
    excl = set(exclude or [])
    hints = {"edit": {"Edit", "Write"}, "search": {"Grep", "Glob", "Read"}, "run": {"Bash"}, "read": {"Read", "Glob"}, "delegate": {"Agent"}}
    hint_set = hints.get(action.lower(), set())
    if hint_set:
        for t in prefs:
            if t not in excl and t in hint_set:
                return t
    for t in prefs:
        if t not in excl:
            return t
    return None


def get_mastery_report(data):
    levels = data.get("mastery_levels", {})
    prefs = data.get("task_tool_preferences", {})
    dist = {"expert": 0, "proficient": 0, "competent": 0, "novice": 0}
    for info in levels.values():
        dist[info.get("level", "novice")] = dist.get(info.get("level", "novice"), 0) + 1
    total = sum(i.get("total_uses", 0) for i in levels.values())
    weakest, w_rate = None, 1.0
    for tool, info in levels.items():
        if info.get("total_uses", 0) >= 10 and info.get("success_rate", 1.0) < w_rate:
            weakest, w_rate = tool, info["success_rate"]
    return {
        "mastery_levels": levels, "task_preferences": prefs, "level_distribution": dist,
        "total_tool_uses": total, "weakest_tool": weakest,
        "weakest_rate": round(w_rate, 4) if weakest else None,
        "tracked_task_types": list(prefs.keys()), "last_updated": data.get("last_updated", 0.0),
    }


def infer_task_type(state):
    """Infer current task type from session state."""
    ct = state.get("current_task_type", "")
    if ct in TASK_TYPES:
        return ct
    if state.get("fix_chain_active") or state.get("current_error"):
        return "fix"
    if state.get("tool_call_count", 0) < 5 and state.get("last_tool_name", "") in ("Read", "Grep", "Glob"):
        return "explore"
    return "unknown"
