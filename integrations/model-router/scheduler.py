"""Scheduler — config-driven + dynamic cron for autonomous model dispatch."""

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from engine import fan_out, save_results
from model_registry import Registry


@dataclass
class Schedule:
    id: str
    prompt: str
    cron_expr: str  # "minute hour day month weekday"
    models: Optional[list[str]] = None
    n: Optional[int] = None
    created_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None  # None = persistent
    last_fired: float = 0.0
    fire_count: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "prompt": self.prompt,
            "cron_expr": self.cron_expr,
            "models": self.models,
            "n": self.n,
            "created_at": datetime.fromtimestamp(self.created_at).isoformat(),
            "expires_at": datetime.fromtimestamp(self.expires_at).isoformat() if self.expires_at else None,
            "last_fired": datetime.fromtimestamp(self.last_fired).isoformat() if self.last_fired else None,
            "fire_count": self.fire_count,
        }


def _parse_cron_field(field_str: str, min_val: int, max_val: int) -> set[int]:
    """Parse a single cron field into a set of matching values."""
    if field_str == "*":
        return set(range(min_val, max_val + 1))

    values = set()
    for part in field_str.split(","):
        if "/" in part:
            base, step = part.split("/", 1)
            step = int(step)
            if base == "*":
                start = min_val
            else:
                start = int(base)
            values.update(range(start, max_val + 1, step))
        elif "-" in part:
            lo, hi = part.split("-", 1)
            values.update(range(int(lo), int(hi) + 1))
        else:
            values.add(int(part))
    return values


def cron_matches(cron_expr: str, dt: datetime) -> bool:
    """Check if a datetime matches a cron expression (minute hour day month weekday)."""
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        return False

    minute_set = _parse_cron_field(parts[0], 0, 59)
    hour_set = _parse_cron_field(parts[1], 0, 23)
    day_set = _parse_cron_field(parts[2], 1, 31)
    month_set = _parse_cron_field(parts[3], 1, 12)
    weekday_set = _parse_cron_field(parts[4], 0, 6)

    return (
        dt.minute in minute_set
        and dt.hour in hour_set
        and dt.day in day_set
        and dt.month in month_set
        and dt.weekday() in weekday_set
    )


class Scheduler:
    def __init__(self, registry: Registry):
        self.registry = registry
        self.schedules: dict[str, Schedule] = {}
        self._task: Optional[asyncio.Task] = None
        self._load_config_schedules()

    def _load_config_schedules(self):
        """Load persistent schedules from config."""
        for cfg in self.registry.schedules_config:
            sid = cfg.get("id", str(uuid.uuid4())[:8])
            self.schedules[sid] = Schedule(
                id=sid,
                prompt=cfg["prompt"],
                cron_expr=cfg["cron"],
                models=cfg.get("models"),
                n=cfg.get("n"),
                expires_at=None,
            )

    def add_schedule(
        self,
        prompt: str,
        cron_expr: str,
        models: Optional[list[str]] = None,
        n: Optional[int] = None,
        expires_in: float = 86400,
    ) -> Schedule:
        """Add a dynamic schedule (auto-expires after expires_in seconds)."""
        sid = str(uuid.uuid4())[:8]
        sched = Schedule(
            id=sid,
            prompt=prompt,
            cron_expr=cron_expr,
            models=models,
            n=n,
            expires_at=time.time() + expires_in,
        )
        self.schedules[sid] = sched
        return sched

    def remove_schedule(self, schedule_id: str) -> bool:
        return self.schedules.pop(schedule_id, None) is not None

    def list_schedules(self) -> list[dict]:
        self._cleanup_expired()
        return [s.to_dict() for s in self.schedules.values()]

    def _cleanup_expired(self):
        now = time.time()
        expired = [
            sid for sid, s in self.schedules.items()
            if s.expires_at and s.expires_at < now
        ]
        for sid in expired:
            del self.schedules[sid]

    async def _tick(self):
        """Check all schedules against current time, fire matching ones."""
        now = datetime.now()
        self._cleanup_expired()

        for sched in list(self.schedules.values()):
            if not cron_matches(sched.cron_expr, now):
                continue
            if sched.last_fired and (time.time() - sched.last_fired) < 60:
                continue

            sched.last_fired = time.time()
            sched.fire_count += 1

            try:
                results = await fan_out(
                    sched.prompt, self.registry,
                    n=sched.n, models=sched.models,
                    timeout=20.0,
                )
                save_results(
                    {"schedule_id": sched.id, "prompt": sched.prompt, "results": results},
                    label=f"schedule_{sched.id}",
                )
            except Exception:
                pass

    async def run(self):
        """Main scheduler loop — ticks every 60 seconds."""
        while True:
            await self._tick()
            await asyncio.sleep(60)

    def start(self, loop=None):
        """Start the scheduler as a background task."""
        if self._task is None or self._task.done():
            self._task = asyncio.ensure_future(self.run())
        return self._task

    def stop(self):
        if self._task and not self._task.done():
            self._task.cancel()
