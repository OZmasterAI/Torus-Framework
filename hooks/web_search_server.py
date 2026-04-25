#!/usr/bin/env python3
"""Torus Framework — Web Search MCP Server

Semantic search over locally indexed web pages (LanceDB web_pages collection).

Run standalone: python3 web_search_server.py
Used via MCP: configured in .claude/mcp.json
"""

import argparse
import functools
import os
import sys
import traceback

from mcp.server.fastmcp import FastMCP

_HOOKS_DIR = os.path.dirname(__file__)
if _HOOKS_DIR not in sys.path:
    sys.path.insert(0, _HOOKS_DIR)

# ── Transport config — streamable-http default, --stdio for pipe mode ──
_NET_HOST = os.environ.get("WEB_SEARCH_HOST", "127.0.0.1")
_NET_PORT = int(os.environ.get("WEB_SEARCH_PORT", "8745"))

_parser = argparse.ArgumentParser(add_help=False)
_parser.add_argument("--http", action="store_true", default=True)
_parser.add_argument("--stdio", action="store_true", default=False)
_parser.add_argument("--port", type=int, default=_NET_PORT)
_args, _ = _parser.parse_known_args()

if _args.stdio:
    _args.http = False

if _args.http:
    mcp = FastMCP("web-search", host=_NET_HOST, port=_args.port)
else:
    mcp = FastMCP("web-search")

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


def crash_proof(fn):
    """Wrap MCP tool handler so exceptions return error dicts instead of crashing the server."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            tb = traceback.format_exc()
            print(f"[Web Search MCP] {fn.__name__} error: {e}\n{tb}", file=sys.stderr)
            return {"error": f"{fn.__name__} failed: {type(e).__name__}: {e}"}

    return wrapper


@mcp.tool()
@crash_proof
def web_search(query: str, n_results: int = 5) -> dict:
    """Search locally indexed web pages via LanceDB semantic search.

    Args:
        query: Search query for semantic matching. Empty returns no results.
        n_results: Max results to return (1-20, default 5).
    """
    if not query or not query.strip():
        return {"results": [], "count": 0, "source": "web_lancedb"}

    n_results = max(1, min(20, n_results))

    from shared import memory_socket

    try:
        result = memory_socket.query(
            "web_pages",
            query_texts=[query],
            n_results=n_results,
            include=["metadatas", "documents", "distances"],
        )
    except memory_socket.WorkerUnavailable as e:
        return {"error": f"Memory worker unavailable: {e}", "source": "web_lancedb"}
    except RuntimeError as e:
        if "Unknown collection" in str(e):
            return {"results": [], "count": 0, "source": "web_lancedb"}
        raise

    if not result or not result.get("ids") or not result["ids"][0]:
        return {"results": [], "count": 0, "source": "web_lancedb"}

    hits = []
    ids = result["ids"][0]
    docs = result.get("documents", [[]])[0]
    metas = result.get("metadatas", [[]])[0]
    dists = result.get("distances", [[]])[0]

    for i, doc_id in enumerate(ids):
        meta = metas[i] if i < len(metas) else {}
        doc = docs[i] if i < len(docs) else ""
        dist = dists[i] if i < len(dists) else 1.0
        similarity = round(1.0 - dist, 3)

        hits.append(
            {
                "id": doc_id,
                "url": meta.get("url", "unknown"),
                "title": meta.get("title", "Untitled"),
                "chunk_index": meta.get("chunk_index", 0),
                "total_chunks": meta.get("total_chunks", 1),
                "similarity": similarity,
                "preview": doc[:200] + "..." if len(doc) > 200 else doc,
            }
        )

    return {"results": hits, "count": len(hits), "source": "web_lancedb"}


if __name__ == "__main__":
    _mode = "stdio" if _args.stdio else "streamable-http"
    if _args.http:
        print(
            f"[Web Search MCP] Starting {_mode} on {_NET_HOST}:{_args.port}",
            file=sys.stderr,
        )
    mcp.run(transport=_mode)
