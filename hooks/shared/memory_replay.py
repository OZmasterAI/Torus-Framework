"""Memory Replay — autonomous strengthening, interference, and tier auto-flow.

Triggered at session boundaries. Selects important memories for replay,
strengthens them and their graph edges, applies interference to competitors,
and promotes/demotes tiers based on usage patterns.

Public API:
    from shared.memory_replay import (
        select_replay_candidates,
        compute_interference,
        evaluate_tier_flow,
        run_replay_cycle,
        AdaptiveWeights,
    )
"""

import json
import math
import os
import time
from typing import Any, Dict, List, Optional

# --- Replay selection constants ---
REPLAY_MAX_AGE_DAYS = 30
REPLAY_BATCH_SIZE = 8

# --- Interference thresholds ---
INTERFERENCE_SIMILARITY_THRESHOLD = 0.75
RETROACTIVE_DECAY = 0.15

# --- Tier auto-flow thresholds ---
PROMOTE_RETRIEVAL_THRESHOLD = 8   # T3->T2 or T2->T1
DEMOTE_STALENESS_DAYS = 60        # T1->T2 or T2->T3 if no retrievals in this window
DEMOTE_MIN_RETRIEVALS = 2         # must have fewer than this to demote


def _parse_session_time(ts) -> float:
    """Parse session_time or timestamp to float epoch. Returns time.time() on failure."""
    if ts is None:
        return time.time()
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, str):
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt.timestamp()
        except (ValueError, AttributeError):
            pass
    return time.time()


def select_replay_candidates(
    memories: List[Dict],
    max_candidates: int = REPLAY_BATCH_SIZE,
) -> List[Dict]:
    """Score and select top memories for replay.

    Priority = importance * recency * (1 + connectivity).
    Filters out memories older than REPLAY_MAX_AGE_DAYS.
    """
    now = time.time()
    scored = []
    for m in memories:
        ts = _parse_session_time(m.get("session_time") or m.get("timestamp"))
        age_days = max(0.001, (now - ts) / 86400)
        if age_days > REPLAY_MAX_AGE_DAYS:
            continue
        tier = int(m.get("tier") or 3)
        retrieval_count = int(m.get("retrieval_count") or 0)

        recency = max(0, 1.0 - age_days / REPLAY_MAX_AGE_DAYS)
        importance = {1: 1.0, 2: 0.7, 3: 0.4}.get(tier, 0.4)
        connectivity = min(0.5, 0.05 * math.log1p(retrieval_count))

        priority = importance * recency * (1.0 + connectivity)
        scored.append({**m, "_replay_priority": priority})

    scored.sort(key=lambda x: x["_replay_priority"], reverse=True)
    return scored[:max_candidates]


def compute_interference(
    new_mem: Dict,
    old_mem: Dict,
    similarity: float,
) -> Dict:
    """Determine if new memory should suppress old one (retroactive interference).

    Returns {"action": "suppress", "tier_change": int, "reason": str}
    or {"action": "none"}.
    """
    if similarity < INTERFERENCE_SIMILARITY_THRESHOLD:
        return {"action": "none"}

    new_tier = int(new_mem.get("tier") or 3)
    old_tier = int(old_mem.get("tier") or 3)
    new_tags = str(new_mem.get("tags") or "")

    # Corrections/fixes always suppress older versions
    is_correction = any(t in new_tags for t in ("type:fix", "type:correction"))

    if is_correction or new_tier < old_tier:
        demoted_tier = min(3, old_tier + 1)
        return {
            "action": "suppress",
            "tier_change": demoted_tier,
            "reason": f"retroactive interference (sim={similarity:.2f})",
        }

    return {"action": "none"}


def evaluate_tier_flow(
    memory: Dict,
    ltp_status: str = "none",
) -> Optional[int]:
    """Check if a memory should be promoted or demoted.

    Returns new tier (int) or None if no change.
    """
    tier = int(memory.get("tier") or 2)
    retrieval_count = int(memory.get("retrieval_count") or 0)
    ts = _parse_session_time(memory.get("session_time") or memory.get("timestamp"))
    age_days = max(0, (time.time() - ts) / 86400)

    # Promotion: high retrieval count or LTP full
    if tier > 1 and (retrieval_count >= PROMOTE_RETRIEVAL_THRESHOLD or ltp_status == "full"):
        return tier - 1

    # Demotion: old with few retrievals, not LTP-protected
    if tier < 3 and age_days > DEMOTE_STALENESS_DAYS and retrieval_count < DEMOTE_MIN_RETRIEVALS:
        if ltp_status in ("none", "burst"):
            return tier + 1

    return None


def run_replay_cycle(
    memories: List[Dict],
    ltp_tracker=None,
    knowledge_graph=None,
    collection=None,
) -> Dict:
    """Execute a full replay cycle. Returns stats dict.

    Steps:
    1. Select top candidates for replay (record access + strengthen graph)
    2. Boost salience for entities in high-activation clusters
    3. Evaluate tier auto-flow on all memories (promote/demote)
    4. Apply edge decay to knowledge graph
    """
    stats = {
        "replayed": 0, "promoted": 0, "demoted": 0,
        "edges_decayed": 0, "edges_pruned": 0,
    }

    # 1. Select candidates and replay
    candidates = select_replay_candidates(memories)
    replayed_ids = []
    for mem in candidates:
        mid = mem.get("id", "")
        if not mid:
            continue
        if ltp_tracker:
            ltp_tracker.record_access(mid)
        replayed_ids.append(mid)
        stats["replayed"] += 1

    if knowledge_graph and len(replayed_ids) >= 2:
        knowledge_graph.strengthen_coretrieval(replayed_ids)

    # 2. Boost salience for entities in high-activation clusters
    if knowledge_graph:
        try:
            clusters = knowledge_graph.get_high_activation_clusters(min_activation=3)
            for cluster in clusters[:3]:
                knowledge_graph.boost_entity_salience(list(cluster), delta=0.05)
        except Exception:
            pass

    # 3. Tier auto-flow on all memories
    tier_updates = []
    for mem in memories:
        mid = mem.get("id", "")
        if not mid:
            continue
        ltp_status = ltp_tracker.get_status(mid) if ltp_tracker else "none"
        new_tier = evaluate_tier_flow(mem, ltp_status)
        if new_tier is not None:
            old_tier = int(mem.get("tier") or 2)
            tier_updates.append((mid, new_tier))
            if new_tier < old_tier:
                stats["promoted"] += 1
            else:
                stats["demoted"] += 1

    if collection and tier_updates:
        for mid, new_tier in tier_updates:
            try:
                collection.update(ids=[mid], metadatas=[{"tier": new_tier}])
            except Exception:
                continue

    # 4. Edge decay
    if knowledge_graph:
        try:
            decay_result = knowledge_graph.decay_edges(half_life_hours=168)
            stats["edges_decayed"] = decay_result.get("decayed", 0)
            stats["edges_pruned"] = decay_result.get("pruned", 0)
        except Exception:
            pass

    return stats


# --- Adaptive Weights ---

_WEIGHT_DEFAULTS = {
    "ltp_blend": 0.3,         # LTP score blend ratio (currently hardcoded 0.3)
    "graph_discount": 0.8,    # graph-enriched result discount (currently 0.8)
    "tier_boost_t1": 0.05,    # T1 boost (currently +0.05)
    "tier_boost_t3": -0.02,   # T3 penalty (currently -0.02)
}
_LEARNING_RATE = 0.03
_WEIGHT_FLOOR = 0.05
_WEIGHT_CEILING = 0.95
_DEFAULT_WEIGHTS_PATH = os.path.expanduser("~/.claude/data/memory/adaptive_weights.json")


class AdaptiveWeights:
    """Track and adjust scoring weights based on retrieval outcome signals."""

    def __init__(self, path: str = _DEFAULT_WEIGHTS_PATH):
        self._path = path
        self._weights: Dict[str, float] = dict(_WEIGHT_DEFAULTS)
        self._load()

    def _load(self):
        if os.path.exists(self._path):
            try:
                with open(self._path) as f:
                    stored = json.load(f)
                self._weights.update(
                    {k: float(v) for k, v in stored.items() if k in _WEIGHT_DEFAULTS}
                )
            except (json.JSONDecodeError, OSError, ValueError):
                pass

    def _save(self):
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        tmp = self._path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self._weights, f)
        os.replace(tmp, self._path)

    def get_weights(self) -> Dict[str, float]:
        """Return current weight values."""
        return dict(self._weights)

    def record_signal(self, weight_name: str, positive: bool):
        """Adjust a weight based on a positive or negative outcome signal."""
        if weight_name not in self._weights:
            return
        delta = _LEARNING_RATE if positive else -_LEARNING_RATE
        self._weights[weight_name] = max(
            _WEIGHT_FLOOR,
            min(_WEIGHT_CEILING, self._weights[weight_name] + delta),
        )
        self._save()
