"""Fan-out engine — parallel dispatch, compare, research."""

import asyncio
import json
import os
import time
from datetime import datetime
from typing import Optional

from client import complete
from model_registry import ModelInfo, Registry

RESULTS_DIR = os.path.expanduser("~/data/model-router/results")


async def fan_out(
    prompt: str,
    registry: Registry,
    n: Optional[int] = None,
    models: Optional[list[str]] = None,
    system_prompt: Optional[str] = None,
    timeout: float = 15.0,
    max_tokens: int = 2048,
) -> list[dict]:
    """Dispatch prompt to N models in parallel, return all results."""
    pool = registry.pick_models(n=n, names=models)
    if not pool:
        return [{"error": "No models available"}]

    tasks = [
        complete(
            prompt,
            m,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            timeout=timeout,
        )
        for m in pool
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    out = []
    for r in results:
        if isinstance(r, Exception):
            out.append({"text": "", "error": str(r), "name": "unknown"})
        else:
            out.append(r)
    return out


def _score_result(result: dict) -> float:
    """Heuristic quality score (0-5) based on response characteristics."""
    if result.get("error") or not result.get("text"):
        return 0.0

    text = result["text"]
    score = 1.0  # baseline for any response

    # Length: reward substance, penalize empty/very short
    length = len(text)
    if length > 50:
        score += 1.0
    if length > 200:
        score += 0.5
    if length > 500:
        score += 0.5

    # Speed bonus
    latency = result.get("latency_ms", 10000)
    if latency < 2000:
        score += 0.5
    if latency < 1000:
        score += 0.5

    # Penalize very long responses (possibly garbage)
    if length > 5000:
        score -= 0.5

    return min(5.0, max(0.0, score))


async def compare(
    prompt: str,
    registry: Registry,
    models: Optional[list[str]] = None,
    timeout: float = 15.0,
    max_tokens: int = 2048,
) -> dict:
    """Fan out, score, and rank results."""
    results = await fan_out(
        prompt, registry, models=models, timeout=timeout, max_tokens=max_tokens
    )

    for r in results:
        r["score"] = _score_result(r)

    results.sort(key=lambda r: r["score"], reverse=True)

    successful = [r for r in results if not r.get("error")]
    failed = [r for r in results if r.get("error")]

    return {
        "prompt": prompt,
        "total": len(results),
        "successful": len(successful),
        "failed": len(failed),
        "results": results,
        "best": results[0] if results else None,
    }


async def research(
    topic: str,
    registry: Registry,
    n: Optional[int] = None,
    timeout: float = 45.0,
) -> dict:
    """Fan out a research query with a research-oriented system prompt."""
    system_prompt = (
        "You are a research assistant. Provide a clear, factual, and concise "
        "summary on the given topic. Include key points, recent developments, "
        "and practical implications. Be specific and cite facts where possible."
    )

    results = await fan_out(
        topic,
        registry,
        n=n,
        system_prompt=system_prompt,
        timeout=timeout,
        max_tokens=4096,
    )

    for r in results:
        r["score"] = _score_result(r)
    results.sort(key=lambda r: r["score"], reverse=True)

    successful = [r for r in results if r.get("text")]
    failed = [r for r in results if not r.get("text")]

    # Synthesize: include all successful responses
    synthesis = ""
    if successful:
        synthesis = f"Research: {topic}\n\n"
        synthesis += f"Queried {len(results)} models, {len(successful)} responded"
        if failed:
            synthesis += f" ({len(failed)} failed)"
        synthesis += ".\n\n"
        for i, r in enumerate(successful, 1):
            synthesis += f"--- {r['name']} (score: {r['score']:.1f}) ---\n"
            synthesis += r["text"][:2000] + "\n\n"

    return {
        "topic": topic,
        "total": len(results),
        "successful": len(successful),
        "synthesis": synthesis,
        "results": results,
    }


def save_results(data: dict, label: str = "result"):
    """Save results to disk for memory integration."""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(RESULTS_DIR, f"{label}_{ts}.json")
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    return path
