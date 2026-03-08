"""OpenRouter async HTTP client — single completion calls."""

import time
from typing import Optional

import httpx

from model_registry import ModelInfo

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


async def complete(
    prompt: str,
    model: ModelInfo,
    system_prompt: Optional[str] = None,
    max_tokens: int = 2048,
    timeout: float = 15.0,
) -> dict:
    """Send a single completion request to OpenRouter.

    Returns: {text, model, name, latency_ms, input_tokens, output_tokens, error}
    """
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model.model_id,
        "messages": messages,
        "max_tokens": max_tokens,
    }

    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {model.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            data = resp.json()

        latency_ms = (time.monotonic() - start) * 1000

        # Check for API errors
        if "error" in data:
            error_msg = data["error"].get("message", str(data["error"]))
            model.record_error(error_msg)
            return {
                "text": "",
                "model": model.model_id,
                "name": model.name,
                "latency_ms": round(latency_ms, 1),
                "input_tokens": 0,
                "output_tokens": 0,
                "error": error_msg,
            }

        # Extract response
        choice = data.get("choices", [{}])[0]
        text = choice.get("message", {}).get("content", "")
        usage = data.get("usage", {})

        model.record_success(latency_ms)
        return {
            "text": text,
            "model": model.model_id,
            "name": model.name,
            "latency_ms": round(latency_ms, 1),
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "error": None,
        }

    except httpx.TimeoutException:
        latency_ms = (time.monotonic() - start) * 1000
        model.record_error("timeout")
        return {
            "text": "",
            "model": model.model_id,
            "name": model.name,
            "latency_ms": round(latency_ms, 1),
            "input_tokens": 0,
            "output_tokens": 0,
            "error": f"Timeout after {timeout}s",
        }
    except Exception as e:
        latency_ms = (time.monotonic() - start) * 1000
        model.record_error(str(e))
        return {
            "text": "",
            "model": model.model_id,
            "name": model.name,
            "latency_ms": round(latency_ms, 1),
            "input_tokens": 0,
            "output_tokens": 0,
            "error": str(e),
        }
