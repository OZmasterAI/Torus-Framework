"""Skill Invocation Tracker — Prompt self-optimization via outcome tracking.

Tracks which skill invocations succeed vs fail, computes per-skill
effectiveness metrics, and generates improvement recommendations for
SKILL.md files.

Design: from arxiv survey (2507.21046) — self-supervised prompt optimization
where models generate preference-paired outputs and refine instructions
without external labels.

Public API:
    from shared.skill_tracker import (
        record_skill_invocation, get_skill_stats, get_skill_recommendations,
        get_improvement_candidates, load_skill_data, save_skill_data,
    )
"""

import json
import os
import time
from typing import Dict, List, Optional

_RAMDISK_DIR = f"/run/user/{os.getuid()}/claude-hooks"
_DISK_DIR = os.path.join(os.path.expanduser("~"), ".claude", "hooks", ".state")
_SKILL_FILENAME = "skill_tracker.json"

MAX_INVOCATIONS_PER_SKILL = 200
MAX_CONTEXT_SAMPLES = 20
MAX_RECOMMENDATIONS = 50


def _skill_path():
    ramdisk = os.path.join(_RAMDISK_DIR, _SKILL_FILENAME)
    disk = os.path.join(_DISK_DIR, _SKILL_FILENAME)
    if os.path.isdir(_RAMDISK_DIR):
        return ramdisk, disk
    return disk, None


def load_skill_data() -> dict:
    primary, fallback = _skill_path()
    for path in (primary, fallback):
        if path and os.path.exists(path):
            try:
                with open(path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                continue
    return {"skills": {}, "recommendations": [], "last_updated": 0.0}


def save_skill_data(data: dict) -> None:
    primary, mirror = _skill_path()
    content = json.dumps(data, indent=2)
    for path in (primary, mirror):
        if path:
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w") as f:
                    f.write(content)
            except IOError:
                pass


def record_skill_invocation(
    data: dict,
    skill_name: str,
    success: bool,
    context: str = "",
    duration_s: float = 0.0,
    error_hint: str = "",
) -> dict:
    """Record a skill invocation outcome.

    Args:
        data: Skill tracker data dict.
        skill_name: Name of the skill (e.g. "fix", "commit", "test").
        success: Whether the invocation achieved its goal.
        context: Brief context of what was being done.
        duration_s: How long the skill took in seconds.
        error_hint: If failed, what went wrong (brief).

    Returns:
        Mutated data dict.
    """
    skills = data.setdefault("skills", {})
    skill = skills.setdefault(skill_name, {
        "success_count": 0, "failure_count": 0,
        "total_duration_s": 0.0, "invocations": [],
        "success_contexts": [], "failure_contexts": [],
    })

    if success:
        skill["success_count"] = skill.get("success_count", 0) + 1
    else:
        skill["failure_count"] = skill.get("failure_count", 0) + 1

    if duration_s > 0:
        skill["total_duration_s"] = skill.get("total_duration_s", 0.0) + duration_s

    # Track invocation for pattern analysis
    inv = {"success": success, "ts": time.time()}
    if context:
        inv["context"] = context[:200]
    if error_hint:
        inv["error"] = error_hint[:200]

    invocations = skill.setdefault("invocations", [])
    invocations.append(inv)
    if len(invocations) > MAX_INVOCATIONS_PER_SKILL:
        skill["invocations"] = invocations[-MAX_INVOCATIONS_PER_SKILL:]

    # Track success/failure contexts separately for paired comparison
    if success and context:
        ctxs = skill.setdefault("success_contexts", [])
        ctxs.append(context[:200])
        if len(ctxs) > MAX_CONTEXT_SAMPLES:
            skill["success_contexts"] = ctxs[-MAX_CONTEXT_SAMPLES:]
    elif not success and context:
        ctxs = skill.setdefault("failure_contexts", [])
        ctxs.append(context[:200])
        if len(ctxs) > MAX_CONTEXT_SAMPLES:
            skill["failure_contexts"] = ctxs[-MAX_CONTEXT_SAMPLES:]

    data["last_updated"] = time.time()
    return data


def get_skill_stats(data: dict, skill_name: str) -> dict:
    """Get effectiveness stats for a skill."""
    skill = data.get("skills", {}).get(skill_name, {})
    s = skill.get("success_count", 0)
    f = skill.get("failure_count", 0)
    total = s + f
    rate = s / total if total > 0 else 1.0
    avg_dur = skill.get("total_duration_s", 0.0) / max(total, 1)

    # Trend: compare last 10 vs previous 10
    invs = skill.get("invocations", [])
    trend = "stable"
    if len(invs) >= 20:
        recent = invs[-10:]
        previous = invs[-20:-10]
        recent_rate = sum(1 for i in recent if i.get("success")) / 10
        prev_rate = sum(1 for i in previous if i.get("success")) / 10
        if recent_rate - prev_rate > 0.15:
            trend = "improving"
        elif prev_rate - recent_rate > 0.15:
            trend = "declining"

    return {
        "skill": skill_name,
        "success_count": s,
        "failure_count": f,
        "total_invocations": total,
        "success_rate": round(rate, 4),
        "avg_duration_s": round(avg_dur, 1),
        "trend": trend,
    }


def get_improvement_candidates(data: dict, min_invocations: int = 5) -> List[dict]:
    """Find skills that could benefit from SKILL.md improvements.

    Returns skills sorted by improvement potential (low success rate + high usage).
    """
    candidates = []
    for name, skill in data.get("skills", {}).items():
        s = skill.get("success_count", 0)
        f = skill.get("failure_count", 0)
        total = s + f
        if total < min_invocations:
            continue
        rate = s / total
        if rate >= 0.95:
            continue  # already very good

        # Improvement potential = (1 - success_rate) * log(total_uses)
        import math
        potential = (1 - rate) * math.log1p(total)

        candidates.append({
            "skill": name,
            "success_rate": round(rate, 4),
            "total_invocations": total,
            "improvement_potential": round(potential, 4),
            "failure_contexts": skill.get("failure_contexts", [])[-5:],
            "success_contexts": skill.get("success_contexts", [])[-5:],
        })

    candidates.sort(key=lambda c: c["improvement_potential"], reverse=True)
    return candidates


def get_skill_recommendations(data: dict) -> List[dict]:
    """Generate SKILL.md improvement recommendations based on tracked outcomes.

    Analyzes paired success/failure contexts to suggest specific changes.
    """
    candidates = get_improvement_candidates(data)
    recs = []

    for c in candidates[:MAX_RECOMMENDATIONS]:
        rec = {
            "skill": c["skill"],
            "success_rate": c["success_rate"],
            "total_invocations": c["total_invocations"],
            "suggestions": [],
        }

        # Analyze failure patterns
        fail_ctxs = c.get("failure_contexts", [])
        succ_ctxs = c.get("success_contexts", [])

        if fail_ctxs and not succ_ctxs:
            rec["suggestions"].append(
                f"Skill '{c['skill']}' has failures but no recorded successes. "
                "Consider revising the SKILL.md instructions or adding guard conditions."
            )
        elif fail_ctxs:
            # Look for words common in failures but rare in successes
            fail_words = set()
            for ctx in fail_ctxs:
                fail_words.update(ctx.lower().split())
            succ_words = set()
            for ctx in succ_ctxs:
                succ_words.update(ctx.lower().split())
            fail_unique = fail_words - succ_words
            if fail_unique:
                sample = sorted(fail_unique)[:5]
                rec["suggestions"].append(
                    f"Failures tend to involve: {', '.join(sample)}. "
                    "Consider adding handling for these cases in SKILL.md."
                )

        if c["success_rate"] < 0.5:
            rec["suggestions"].append(
                f"Success rate below 50% ({c['success_rate']:.0%}). "
                "Major revision recommended — check if the skill's assumptions still hold."
            )
        elif c["success_rate"] < 0.8:
            rec["suggestions"].append(
                f"Success rate at {c['success_rate']:.0%}. "
                "Minor refinement — review recent failure contexts for common patterns."
            )

        if rec["suggestions"]:
            recs.append(rec)

    return recs
