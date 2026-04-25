"""MCP Bridge — thin FastMCP wrapper over model-router REST API."""

import argparse
import os
import socket
import subprocess
import sys
import time
from typing import Optional

import httpx
from mcp.server.fastmcp import FastMCP

ROUTER_URL = "http://127.0.0.1:18800"
ROUTER_PORT = 18800
_server_proc = None

# ── Transport config — streamable-http default, --stdio for pipe mode ──
_NET_HOST = os.environ.get("MODEL_ROUTER_MCP_HOST", "127.0.0.1")
_NET_PORT = int(os.environ.get("MODEL_ROUTER_MCP_PORT", "8747"))

_parser = argparse.ArgumentParser(add_help=False)
_parser.add_argument("--http", action="store_true", default=True)
_parser.add_argument("--stdio", action="store_true", default=False)
_parser.add_argument("--port", type=int, default=_NET_PORT)
_args, _ = _parser.parse_known_args()

if _args.stdio:
    _args.http = False

if _args.http:
    mcp = FastMCP("model-router", host=_NET_HOST, port=_args.port)
else:
    mcp = FastMCP("model-router")

# ── OAuth discovery stubs (Claude Code does RFC 9728/8414 probing) ──
if _args.http:
    from starlette.requests import Request
    from starlette.responses import Response

    @mcp.custom_route("/.well-known/oauth-authorization-server", methods=["GET"])
    async def _oauth_as_metadata(request: Request) -> Response:
        return Response(status_code=404)

    @mcp.custom_route("/.well-known/oauth-protected-resource", methods=["GET"])
    async def _oauth_protected_resource(request: Request) -> Response:
        return Response(status_code=404)

    @mcp.custom_route("/.well-known/openid-configuration", methods=["GET"])
    async def _openid_config(request: Request) -> Response:
        return Response(status_code=404)

    @mcp.custom_route("/register", methods=["POST"])
    async def _oauth_register(request: Request) -> Response:
        return Response(status_code=404)

    @mcp.custom_route("/authorize", methods=["GET"])
    async def _oauth_authorize(request: Request) -> Response:
        return Response(status_code=404)


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _ensure_server():
    """Auto-launch server.py if not already listening."""
    global _server_proc
    if _port_open(ROUTER_PORT):
        return
    server_path = os.path.join(os.path.dirname(__file__), "server.py")
    _server_proc = subprocess.Popen(
        [sys.executable, server_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Wait up to 5s for server to be ready
    for _ in range(50):
        if _port_open(ROUTER_PORT):
            return
        time.sleep(0.1)


_ensure_server()


async def _post(path: str, data: dict) -> dict:
    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(f"{ROUTER_URL}{path}", json=data)
        return resp.json()


async def _get(path: str) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(f"{ROUTER_URL}{path}")
        return resp.json()


@mcp.tool()
async def model_fan_out(prompt: str, n: int = 5, models: str = "") -> str:
    """Fan out a prompt to N free models in parallel.

    Args:
        prompt: The prompt to send to all models
        n: Number of models to query (default 5)
        models: Optional comma-separated model names to use
    """
    data = {"prompt": prompt, "n": n}
    if models:
        data["models"] = [m.strip() for m in models.split(",")]
    results = await _post("/fan-out", data)

    lines = [f"Fan-out to {len(results)} models:\n"]
    for r in results:
        if r.get("error"):
            lines.append(f"  X {r.get('name', '?')}: {r['error']}")
        else:
            text = r.get("text", "")[:200]
            lines.append(
                f"  + {r.get('name', '?')} ({r.get('latency_ms', 0):.0f}ms): {text}"
            )
    return "\n".join(lines)


@mcp.tool()
async def model_compare(prompt: str, models: str = "") -> str:
    """Compare responses from multiple free models, scored and ranked.

    Args:
        prompt: The prompt to compare across models
        models: Optional comma-separated model names
    """
    data = {"prompt": prompt}
    if models:
        data["models"] = [m.strip() for m in models.split(",")]
    result = await _post("/compare", data)

    lines = [
        f"Compared {result.get('total', 0)} models ({result.get('successful', 0)} successful):\n"
    ]
    for r in result.get("results", []):
        score = r.get("score", 0)
        if r.get("error"):
            lines.append(f"  [{score:.1f}] X {r.get('name', '?')}: {r['error']}")
        else:
            text = r.get("text", "")[:300]
            lines.append(
                f"  [{score:.1f}] {r.get('name', '?')} ({r.get('latency_ms', 0):.0f}ms):\n    {text}"
            )
    if result.get("saved_to"):
        lines.append(f"\nSaved to: {result['saved_to']}")
    return "\n".join(lines)


@mcp.tool()
async def model_research(topic: str, n: int = 0) -> str:
    """Research a topic using multiple free models and synthesize results.

    Args:
        topic: The research topic or question
        n: Number of models to query (0 = all, default all)
    """
    data = {"topic": topic}
    if n > 0:
        data["n"] = n
    result = await _post("/research", data)
    synthesis = result.get("synthesis", "No synthesis available.")
    if result.get("saved_to"):
        synthesis += f"\n\nSaved to: {result['saved_to']}"
    return synthesis


@mcp.tool()
async def model_schedule(
    prompt: str, cron_expr: str, models: str = "", n: int = 0
) -> str:
    """Schedule a recurring prompt to run on free models via cron.

    Args:
        prompt: The prompt to run on schedule
        cron_expr: Cron expression (minute hour day month weekday), e.g. '0 */6 * * *'
        models: Optional comma-separated model names
        n: Number of models per run (0 = all)
    """
    data = {"prompt": prompt, "cron": cron_expr}
    if models:
        data["models"] = [m.strip() for m in models.split(",")]
    if n > 0:
        data["n"] = n
    result = await _post("/schedule", data)
    if result.get("error"):
        return f"Error: {result['error']}"
    return f"Schedule created: {result.get('id', '?')} — cron: {cron_expr}"


@mcp.tool()
async def list_models() -> str:
    """List all available free models with health status."""
    models = await _get("/models")
    lines = [
        f"{'Name':<25} {'Healthy':<8} {'Calls':<6} {'Errors':<7} {'Avg ms':<8} {'Success%'}"
    ]
    lines.append("-" * 75)
    for m in models:
        lines.append(
            f"{m['name']:<25} {'yes' if m['healthy'] else 'NO':<8} "
            f"{m['total_calls']:<6} {m['total_errors']:<7} "
            f"{m['avg_latency_ms']:<8.0f} {m['success_rate'] * 100:.0f}%"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    _mode = "stdio" if _args.stdio else "streamable-http"
    if _args.http:
        print(
            f"[Model Router MCP] Starting {_mode} on {_NET_HOST}:{_args.port}",
            file=sys.stderr,
        )
    mcp.run(transport=_mode)
