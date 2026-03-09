"""Long-Term Potentiation (LTP) tracker for memory access patterns.

Tracks per-memory activation history and assigns LTP protection levels
that reduce decay rates for frequently accessed memories.

Levels:
    none  → 1.0  (no protection)
    burst → 0.5  (5+ accesses in 24h)
    weekly→ 0.33 (3+ accesses/week for 2+ weeks)
    full  → 0.1  (10+ total accesses)

Public API:
    from shared.ltp_tracker import LTPTracker
"""

import json
import os
import time
from typing import Dict, Optional

# LTP status → decay factor multiplier (lower = slower decay)
_DECAY_FACTORS: Dict[str, float] = {
    "none": 1.0,
    "burst": 0.5,
    "weekly": 0.33,
    "full": 0.1,
}

_DEFAULT_PATH = os.path.expanduser("~/.claude/data/memory/ltp_state.json")


class LTPTracker:
    """Track memory access patterns and assign LTP protection levels."""

    def __init__(self, db_path: str = _DEFAULT_PATH):
        self._path = db_path
        self._state: Dict[str, dict] = {}
        self._load()

    def _load(self):
        if os.path.exists(self._path):
            try:
                with open(self._path, "r") as f:
                    self._state = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._state = {}

    def _save(self):
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        tmp = self._path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self._state, f)
        os.replace(tmp, self._path)

    def _ensure_entry(self, memory_id: str) -> dict:
        if memory_id not in self._state:
            self._state[memory_id] = {
                "access_timestamps": [],
                "status": "none",
                "total_accesses": 0,
            }
        return self._state[memory_id]

    def record_access(self, memory_id: str) -> str:
        """Record an access and re-evaluate LTP status. Returns new status."""
        entry = self._ensure_entry(memory_id)
        now = time.time()
        entry["access_timestamps"].append(now)
        entry["total_accesses"] = entry.get("total_accesses", 0) + 1

        # Prune timestamps older than 30 days to bound storage
        cutoff = now - (30 * 86400)
        entry["access_timestamps"] = [t for t in entry["access_timestamps"] if t > cutoff]

        entry["status"] = self._evaluate_status(entry)
        self._save()
        return entry["status"]

    def _evaluate_status(self, entry: dict) -> str:
        """Determine LTP level from access history."""
        total = entry.get("total_accesses", 0)
        timestamps = entry.get("access_timestamps", [])

        # Full LTP: 10+ total accesses (highest priority)
        if total >= 10:
            return "full"

        # Weekly: 3+ accesses/week for 2+ weeks
        if len(timestamps) >= 6 and self._has_weekly_pattern(timestamps):
            return "weekly"

        # Burst: 5+ accesses in last 24h
        if self._recent_access_count(timestamps, hours=24) >= 5:
            return "burst"

        return "none"

    def _recent_access_count(self, timestamps: list, hours: int = 24) -> int:
        """Count accesses within the last N hours."""
        cutoff = time.time() - (hours * 3600)
        return sum(1 for t in timestamps if t > cutoff)

    def _has_weekly_pattern(self, timestamps: list) -> bool:
        """Check if there are 3+ accesses/week for at least 2 distinct weeks."""
        if not timestamps:
            return False
        now = time.time()
        week_counts: Dict[int, int] = {}
        for t in timestamps:
            week_num = int((now - t) / (7 * 86400))
            week_counts[week_num] = week_counts.get(week_num, 0) + 1
        qualifying_weeks = sum(1 for c in week_counts.values() if c >= 3)
        return qualifying_weeks >= 2

    def get_status(self, memory_id: str) -> str:
        """Get current LTP status for a memory."""
        entry = self._state.get(memory_id)
        if entry is None:
            return "none"
        return entry.get("status", "none")

    def get_decay_factor(self, memory_id: str) -> float:
        """Get decay factor multiplier for a memory's LTP status."""
        status = self.get_status(memory_id)
        return _DECAY_FACTORS.get(status, 1.0)
