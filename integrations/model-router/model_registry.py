"""Model Registry — loads config and tracks model health."""

import os
import time
import tomllib
from dataclasses import dataclass, field
from typing import Optional

DEFAULT_CONFIG = os.path.join(os.path.dirname(__file__), "router_config.toml")


@dataclass
class ModelInfo:
    name: str
    model_id: str
    api_key: str
    reasoning: bool = False
    vision: bool = False
    # Health tracking
    last_success: float = 0.0
    last_error: float = 0.0
    last_error_msg: str = ""
    total_calls: int = 0
    total_errors: int = 0
    total_latency_ms: float = 0.0

    @property
    def avg_latency_ms(self) -> float:
        successful = self.total_calls - self.total_errors
        if successful <= 0:
            return 0.0
        return self.total_latency_ms / successful

    @property
    def success_rate(self) -> float:
        if self.total_calls == 0:
            return 1.0
        return (self.total_calls - self.total_errors) / self.total_calls

    @property
    def is_healthy(self) -> bool:
        if self.total_calls == 0:
            return True  # untested = assume healthy
        if self.total_calls < 3:
            return True  # not enough data
        return self.success_rate > 0.3

    def record_success(self, latency_ms: float):
        self.last_success = time.time()
        self.total_calls += 1
        self.total_latency_ms += latency_ms

    def record_error(self, error_msg: str):
        self.last_error = time.time()
        self.last_error_msg = error_msg
        self.total_calls += 1
        self.total_errors += 1

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "model_id": self.model_id,
            "reasoning": self.reasoning,
            "vision": self.vision,
            "healthy": self.is_healthy,
            "total_calls": self.total_calls,
            "total_errors": self.total_errors,
            "success_rate": round(self.success_rate, 2),
            "avg_latency_ms": round(self.avg_latency_ms, 1),
        }


class Registry:
    def __init__(self, config_path: str = DEFAULT_CONFIG):
        with open(config_path, "rb") as f:
            self._config = tomllib.load(f)

        self.port = self._config.get("service", {}).get("port", 18800)
        self.host = self._config.get("service", {}).get("host", "127.0.0.1")
        self.default_timeout = self._config.get("service", {}).get("default_timeout", 15)
        self.max_concurrent = self._config.get("service", {}).get("max_concurrent", 17)

        self.judge = self._config.get("judge", {})
        self.memory_config = self._config.get("memory", {})
        self.schedules_config = self._config.get("schedules", [])

        self.models: dict[str, ModelInfo] = {}
        for name, cfg in self._config.get("models", {}).items():
            self.models[name] = ModelInfo(
                name=name,
                model_id=cfg["id"],
                api_key=cfg["api_key"],
                reasoning=cfg.get("reasoning", False),
                vision=cfg.get("vision", False),
            )

    def get_model(self, name: str) -> Optional[ModelInfo]:
        return self.models.get(name)

    def list_models(self) -> list[dict]:
        return [m.to_dict() for m in self.models.values()]

    def healthy_models(self) -> list[ModelInfo]:
        return [m for m in self.models.values() if m.is_healthy]

    def pick_models(self, n: int = None, names: list[str] = None) -> list[ModelInfo]:
        """Pick N models by name or from healthy pool."""
        if names:
            return [self.models[n] for n in names if n in self.models]
        pool = self.healthy_models()
        if n is None or n >= len(pool):
            return pool
        # Sort by fewest calls (spread load) then pick top N
        pool.sort(key=lambda m: m.total_calls)
        return pool[:n]
