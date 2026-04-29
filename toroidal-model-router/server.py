"""Model Router REST API — aiohttp server on :18800."""

import asyncio
import json

from aiohttp import web

from client import complete
from engine import compare, fan_out, research, save_results
from model_registry import Registry
from scheduler import Scheduler

registry = Registry()
scheduler = Scheduler(registry)


async def handle_health(request):
    return web.json_response(
        {
            "status": "ok",
            "models": len(registry.models),
            "healthy": len(registry.healthy_models()),
        }
    )


async def handle_models(request):
    return web.json_response(registry.list_models())


async def handle_completion(request):
    body = await request.json()
    prompt = body.get("prompt", "")
    model_name = body.get("model")
    timeout = body.get("timeout", registry.default_timeout)
    max_tokens = body.get("max_tokens", 2048)

    if not prompt:
        return web.json_response({"error": "prompt required"}, status=400)

    if model_name:
        model = registry.get_model(model_name)
        if not model:
            return web.json_response(
                {"error": f"Unknown model: {model_name}"}, status=404
            )
    else:
        pool = registry.healthy_models()
        if not pool:
            return web.json_response({"error": "No healthy models"}, status=503)
        pool.sort(key=lambda m: m.total_calls)
        model = pool[0]

    result = await complete(prompt, model, max_tokens=max_tokens, timeout=timeout)
    return web.json_response(result)


async def handle_fan_out(request):
    body = await request.json()
    prompt = body.get("prompt", "")
    n = body.get("n")
    models = body.get("models")
    timeout = body.get("timeout", registry.default_timeout)
    max_tokens = body.get("max_tokens", 2048)

    if not prompt:
        return web.json_response({"error": "prompt required"}, status=400)

    results = await fan_out(
        prompt,
        registry,
        n=n,
        models=models,
        timeout=timeout,
        max_tokens=max_tokens,
    )
    return web.json_response(results)


async def handle_compare(request):
    body = await request.json()
    prompt = body.get("prompt", "")
    models = body.get("models")
    timeout = body.get("timeout", registry.default_timeout)
    max_tokens = body.get("max_tokens", 2048)

    if not prompt:
        return web.json_response({"error": "prompt required"}, status=400)

    result = await compare(
        prompt,
        registry,
        models=models,
        timeout=timeout,
        max_tokens=max_tokens,
    )
    path = save_results(result, label="compare")
    result["saved_to"] = path
    return web.json_response(result, dumps=lambda o: json.dumps(o, default=str))


async def handle_research(request):
    body = await request.json()
    topic = body.get("topic", "")
    n = body.get("n")  # None = all models
    timeout = body.get("timeout", 45.0)

    if not topic:
        return web.json_response({"error": "topic required"}, status=400)

    result = await research(topic, registry, n=n, timeout=timeout)
    path = save_results(result, label="research")
    result["saved_to"] = path
    return web.json_response(result, dumps=lambda o: json.dumps(o, default=str))


async def handle_ping(request):
    """Quick ping of all models with a trivial prompt."""
    results = await fan_out("Say OK", registry, timeout=10.0, max_tokens=16)
    summary = []
    for r in results:
        summary.append(
            {
                "name": r.get("name", "unknown"),
                "ok": not r.get("error"),
                "latency_ms": r.get("latency_ms", 0),
                "error": r.get("error"),
            }
        )
    summary.sort(key=lambda s: (not s["ok"], s["latency_ms"]))
    return web.json_response(
        {
            "total": len(summary),
            "healthy": sum(1 for s in summary if s["ok"]),
            "results": summary,
        }
    )


async def handle_add_schedule(request):
    body = await request.json()
    prompt = body.get("prompt", "")
    cron = body.get("cron", "")
    models = body.get("models")
    n = body.get("n")
    expires_in = body.get("expires_in", 86400)

    if not prompt or not cron:
        return web.json_response({"error": "prompt and cron required"}, status=400)

    sched = scheduler.add_schedule(
        prompt, cron, models=models, n=n, expires_in=expires_in
    )
    return web.json_response(sched.to_dict())


async def handle_list_schedules(request):
    return web.json_response(scheduler.list_schedules())


async def handle_delete_schedule(request):
    schedule_id = request.match_info["id"]
    if scheduler.remove_schedule(schedule_id):
        return web.json_response({"deleted": schedule_id})
    return web.json_response({"error": "Not found"}, status=404)


def create_app():
    app = web.Application()
    app.router.add_get("/health", handle_health)
    app.router.add_get("/models", handle_models)
    app.router.add_post("/completion", handle_completion)
    app.router.add_post("/fan-out", handle_fan_out)
    app.router.add_post("/compare", handle_compare)
    app.router.add_post("/research", handle_research)
    app.router.add_get("/ping", handle_ping)
    app.router.add_post("/schedule", handle_add_schedule)
    app.router.add_get("/schedules", handle_list_schedules)
    app.router.add_delete("/schedule/{id}", handle_delete_schedule)
    return app


async def on_startup(app):
    scheduler.start()


if __name__ == "__main__":
    app = create_app()
    app.on_startup.append(on_startup)
    web.run_app(app, host=registry.host, port=registry.port)
