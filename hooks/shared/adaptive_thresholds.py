"""Adaptive Gate Thresholds — Learn optimal strictness from outcomes.

Tracks gate decision correctness and adjusts thresholds using EMA.
Tier 1 safety gates are never adjusted.

Public API:
    from shared.adaptive_thresholds import (
        get_threshold, record_gate_outcome, adjust_thresholds,
        get_threshold_report, load_thresholds, save_thresholds,
    )
"""

import json
import os
import time
from typing import Dict, Optional, Set

_RAMDISK_DIR = f"/run/user/{os.getuid()}/claude-hooks"
_DISK_DIR = os.path.join(os.path.expanduser("~"), ".claude", "hooks", ".state")
_THRESHOLD_FILENAME = "gate_thresholds.json"

# Tier 1 gates are immutable — never adjust their thresholds
IMMUTABLE_GATES: Set[str] = {
    "gates.gate_01_read_before_edit",
    "gates.gate_02_no_destroy",
    "gates.gate_03_test_before_deploy",
}

# Default thresholds for gates that support adaptation
DEFAULT_THRESHOLDS: Dict[str, dict] = {
    "gates.gate_14_confidence_check": {"default": 0.70, "min": 0.50, "max": 0.95},
    "gates.gate_16_code_quality":     {"default": 0.60, "min": 0.40, "max": 0.90},
    "gates.gate_19_hindsight":        {"default": 0.65, "min": 0.45, "max": 0.90},
    "gates.gate_20_self_check":       {"default": 0.60, "min": 0.40, "max": 0.85},
}

LEARNING_RATE = 0.05
MAX_FEEDBACK_LOG = 100

# Thresholds for triggering adjustment
FALSE_NEG_RATE_TRIGGER = 0.10   # Tighten when > 10% false negatives
FALSE_POS_RATE_TRIGGER = 0.20   # Loosen when > 20% false positives
MIN_SAMPLES = 10                # Minimum samples before adjusting


def _threshold_path():
    ramdisk = os.path.join(_RAMDISK_DIR, _THRESHOLD_FILENAME)
    disk = os.path.join(_DISK_DIR, _THRESHOLD_FILENAME)
    if os.path.isdir(_RAMDISK_DIR):
        return ramdisk, disk
    return disk, None


def load_thresholds() -> dict:
    primary, fallback = _threshold_path()
    for path in (primary, fallback):
        if path and os.path.exists(path):
            try:
                with open(path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                continue
    return _default_data()


def save_thresholds(data: dict) -> None:
    primary, mirror = _threshold_path()
    content = json.dumps(data, indent=2)
    for path in (primary, mirror):
        if path:
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w") as f:
                    f.write(content)
            except IOError:
                pass


def _default_data() -> dict:
    gt = {}
    for gate, cfg in DEFAULT_THRESHOLDS.items():
        gt[gate] = {
            "current": cfg["default"],
            "default": cfg["default"],
            "min": cfg["min"],
            "max": cfg["max"],
            "true_positives": 0,
            "false_positives": 0,
            "true_negatives": 0,
            "false_negatives": 0,
            "last_adjusted": 0.0,
        }
    return {"gate_thresholds": gt, "feedback_log": [], "learning_rate": LEARNING_RATE, "last_updated": 0.0}


def get_threshold(data: dict, gate_name: str) -> float:
    """Get current adaptive threshold for a gate."""
    gt = data.get("gate_thresholds", {}).get(gate_name)
    if gt:
        return gt.get("current", gt.get("default", 0.5))
    cfg = DEFAULT_THRESHOLDS.get(gate_name)
    return cfg["default"] if cfg else 0.5


def record_gate_outcome(
    data: dict,
    gate_name: str,
    gate_blocked: bool,
    tool_succeeded: bool,
) -> dict:
    """Record whether a gate's decision was correct.

    Confusion matrix:
    - gate_blocked=True  + tool would have failed  = true positive
    - gate_blocked=True  + tool would have succeeded = false positive
    - gate_blocked=False + tool succeeded = true negative
    - gate_blocked=False + tool failed    = false negative

    Since we can't know if a blocked tool *would* have failed, we use:
    - blocked + later fix succeeded = false positive (block was unnecessary)
    - blocked + no resolution = true positive (block prevented harm)
    """
    if gate_name in IMMUTABLE_GATES:
        return data

    gt = data.setdefault("gate_thresholds", {})
    if gate_name not in gt:
        cfg = DEFAULT_THRESHOLDS.get(gate_name, {"default": 0.5, "min": 0.3, "max": 0.95})
        gt[gate_name] = {
            "current": cfg["default"], "default": cfg["default"],
            "min": cfg.get("min", 0.3), "max": cfg.get("max", 0.95),
            "true_positives": 0, "false_positives": 0,
            "true_negatives": 0, "false_negatives": 0, "last_adjusted": 0.0,
        }

    entry = gt[gate_name]
    if gate_blocked and not tool_succeeded:
        entry["true_positives"] = entry.get("true_positives", 0) + 1
    elif gate_blocked and tool_succeeded:
        entry["false_positives"] = entry.get("false_positives", 0) + 1
    elif not gate_blocked and tool_succeeded:
        entry["true_negatives"] = entry.get("true_negatives", 0) + 1
    elif not gate_blocked and not tool_succeeded:
        entry["false_negatives"] = entry.get("false_negatives", 0) + 1

    data["last_updated"] = time.time()
    return data


def adjust_thresholds(data: dict) -> list:
    """Run threshold adjustment pass. Returns list of adjustment descriptions."""
    adjustments = []
    lr = data.get("learning_rate", LEARNING_RATE)
    gt = data.get("gate_thresholds", {})
    log = data.setdefault("feedback_log", [])

    for gate_name, entry in gt.items():
        if gate_name in IMMUTABLE_GATES:
            continue

        tp = entry.get("true_positives", 0)
        fp = entry.get("false_positives", 0)
        tn = entry.get("true_negatives", 0)
        fn = entry.get("false_negatives", 0)
        total = tp + fp + tn + fn

        if total < MIN_SAMPLES:
            continue

        current = entry.get("current", entry.get("default", 0.5))
        lo, hi = entry.get("min", 0.3), entry.get("max", 0.95)
        old = current

        # False negative rate: missed bad calls (should tighten)
        total_negatives = tn + fn
        if total_negatives > 0 and fn / total_negatives > FALSE_NEG_RATE_TRIGGER:
            target = min(hi, current + 0.1)
            current = current + lr * (target - current)

        # False positive rate: unnecessary blocks (should loosen)
        total_positives = tp + fp
        if total_positives > 0 and fp / total_positives > FALSE_POS_RATE_TRIGGER:
            target = max(lo, current - 0.1)
            current = current + lr * (target - current)

        current = max(lo, min(hi, round(current, 4)))

        if abs(current - old) > 0.001:
            entry["current"] = current
            entry["last_adjusted"] = time.time()
            action = "tightened" if current > old else "loosened"
            desc = f"{gate_name}: {action} {old:.4f} -> {current:.4f}"
            adjustments.append(desc)
            log.append({
                "gate": gate_name, "action": action,
                "old_threshold": old, "new_threshold": current,
                "reason": f"FN={fn}/{total_negatives}, FP={fp}/{total_positives}",
                "timestamp": time.time(),
            })

    # Cap feedback log
    if len(log) > MAX_FEEDBACK_LOG:
        data["feedback_log"] = log[-MAX_FEEDBACK_LOG:]

    data["last_updated"] = time.time()
    return adjustments


def record_feedback(data: dict, gate_name: str, was_correct: bool, context: str = "") -> dict:
    """Record external feedback (e.g., from chain_refinement) about a gate decision."""
    if gate_name in IMMUTABLE_GATES:
        return data
    # Map feedback to confusion matrix: correct block = TP, incorrect block = FP
    return record_gate_outcome(data, gate_name, gate_blocked=True, tool_succeeded=not was_correct)


def get_threshold_report(data: dict) -> dict:
    """Get full report of all adaptive threshold states."""
    gt = data.get("gate_thresholds", {})
    summary = []
    for gate, entry in sorted(gt.items()):
        total = sum(entry.get(k, 0) for k in ("true_positives", "false_positives", "true_negatives", "false_negatives"))
        tp = entry.get("true_positives", 0)
        fp = entry.get("false_positives", 0)
        precision = tp / max(tp + fp, 1)
        fn = entry.get("false_negatives", 0)
        tn = entry.get("true_negatives", 0)
        recall = tp / max(tp + fn, 1) if (tp + fn) > 0 else 1.0
        summary.append({
            "gate": gate,
            "current": entry.get("current"),
            "default": entry.get("default"),
            "total_samples": total,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "immutable": gate in IMMUTABLE_GATES,
        })
    recent_log = data.get("feedback_log", [])[-10:]
    return {"thresholds": summary, "recent_adjustments": recent_log, "last_updated": data.get("last_updated", 0.0)}
